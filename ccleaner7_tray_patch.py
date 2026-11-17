#!/usr/bin/env python3
"""
CCleaner 7 - "close = exit, minimize = tray" patcher
=====================================================

Edits CCleaner.exe (64-bit, "CCleanerLotus" UI) so that

  * clicking  X  fully EXITS the program (instead of keeping it resident),
  * clicking  -  hides the window to the notification area (system tray)
                 instead of leaving a button on the taskbar.
                 Clicking the tray icon (or starting CCleaner again) brings
                 the window back, using CCleaner's own restore code.

Nothing here touches licensing, activation or any feature gating.

No fixed offsets are used: every patch point is located by pattern, so the
script is meant to keep working on new builds. If a pattern is not found the
script says which one and refuses to write anything for that feature.

Pure standard-library Python 3.8+. Usage:

    python ccleaner7_tray_patch.py CCleaner.exe             # writes CCleaner.exe, backup CCleaner.exe.bak
    python ccleaner7_tray_patch.py CCleaner.exe -o out.exe  # write somewhere else, leave input alone
    python ccleaner7_tray_patch.py CCleaner.exe --dry-run   # only report what would be patched
    python ccleaner7_tray_patch.py CCleaner.exe --no-minimize   # only the "X exits" patch
    python ccleaner7_tray_patch.py CCleaner.exe --no-close      # only the "- to tray" patch

How it works (short version)
----------------------------
X button   The web UI sends "close-window"; native code turns it into
           SC_CLOSE, CCleaner's handler destroys the GUI and calls an
           "is anything still open?" routine. That routine calls
           PostQuitMessage only if a "resident/background" field is 0,
           otherwise it parks the process in the tray. We turn that
           conditional branch into an unconditional one. CCleaner's own
           guards (open modal, running task, ...) in front of it are kept.

- button   The web UI sends window-status-set/"minimized"; native code
           PostMessage()s SC_MINIMIZE (0xF020). We redirect that one site to a
           small stub in a new executable section:
               if FindWindowW(<tray window class>) != NULL   # tray icon exists
                   ShowWindow(hwnd, SW_MINIMIZE); ShowWindow(hwnd, SW_HIDE)
               else
                   original behaviour (normal minimize)
           The window stays "minimized" (so CCleaner's IsIconic -> SW_RESTORE
           path works) but is hidden, so it vanishes from the taskbar.

Because bytes change, the Authenticode signature becomes invalid; the
signature blob is removed from the output (it cannot be kept valid).
"""
__version__ = "1.0"

import argparse
import os
import re
import shutil
import struct
import sys

# ---- Patcholly banner (printed at start; silent if PATCHOLLY_NOBANNER is set) ----
BANNER = r"""
==============================================================

  ####    ###   #####   ####  #   #   ###   #      #      #   #
  #   #  #   #    #    #      #   #  #   #  #      #       # #
  ####   #####    #    #      #####  #   #  #      #        #
  #      #   #    #    #      #   #  #   #  #      #        #
  #      #   #    #     ####  #   #   ###   #####  #####    #

  CCLEANER CLASSIC PATCHER  //  v{VER}
==============================================================
"""


def print_banner():
    if not os.environ.get("PATCHOLLY_NOBANNER"):
        print(BANNER.replace("{VER}", __version__))


# --------------------------------------------------------------------------
# PE helpers
# --------------------------------------------------------------------------
SCN_CODE = 0x00000020
SCN_EXEC = 0x20000000
SCN_READ = 0x40000000


def align_up(v, a):
    return (v + a - 1) // a * a


class PE:
    def __init__(self, data):
        self.d = bytearray(data)
        d = self.d
        if d[:2] != b"MZ":
            raise ValueError("not an MZ/PE file")
        self.pe = struct.unpack_from("<I", d, 0x3C)[0]
        if d[self.pe:self.pe + 4] != b"PE\0\0":
            raise ValueError("PE signature missing")
        self.machine, self.nsec = struct.unpack_from("<HH", d, self.pe + 4)
        self.optsz = struct.unpack_from("<H", d, self.pe + 20)[0]
        self.opt = self.pe + 24
        magic = struct.unpack_from("<H", d, self.opt)[0]
        if self.machine != 0x8664 or magic != 0x20B:
            raise ValueError("only 64-bit (PE32+, x64) executables are supported")
        self.image_base = struct.unpack_from("<Q", d, self.opt + 24)[0]
        self.sec_align, self.file_align = struct.unpack_from("<II", d, self.opt + 32)
        self.size_of_image = struct.unpack_from("<I", d, self.opt + 56)[0]
        self.size_of_headers = struct.unpack_from("<I", d, self.opt + 60)[0]
        self.dd = self.opt + 112
        self.sec_table = self.opt + self.optsz
        self.sections = []
        for i in range(self.nsec):
            o = self.sec_table + 40 * i
            name = bytes(d[o:o + 8]).rstrip(b"\0").decode("latin1")
            vs, va, rs, ro = struct.unpack_from("<IIII", d, o + 8)
            ch = struct.unpack_from("<I", d, o + 36)[0]
            self.sections.append(dict(name=name, vs=vs, va=va, rs=rs, ro=ro, ch=ch, hdr=o))

    # --- address translation ------------------------------------------------
    def rva2off(self, rva):
        for s in self.sections:
            if s["va"] <= rva < s["va"] + max(s["vs"], s["rs"]):
                off = rva - s["va"]
                if off < s["rs"]:
                    return s["ro"] + off
                return None
        return None

    def va2off(self, va):
        return self.rva2off(va - self.image_base)

    def off2va(self, off):
        for s in self.sections:
            if s["ro"] <= off < s["ro"] + s["rs"]:
                return self.image_base + s["va"] + off - s["ro"]
        return None

    def code_ranges(self):
        """(file_off_start, file_off_end, va_start) for every executable section."""
        out = []
        for s in self.sections:
            if s["ch"] & SCN_EXEC and s["rs"]:
                size = min(s["vs"], s["rs"]) if s["vs"] else s["rs"]
                out.append((s["ro"], s["ro"] + size, self.image_base + s["va"]))
        return out

    # --- imports --------------------------------------------------------------
    def imports(self):
        """name -> IAT slot VA (names only; ordinals ignored)."""
        res = {}
        rva, size = struct.unpack_from("<II", self.d, self.dd + 8)
        if not rva:
            return res
        o = self.rva2off(rva)
        while True:
            oft, _, _, name, ft = struct.unpack_from("<IIIII", self.d, o)
            if not name and not ft:
                break
            thunk = self.rva2off(oft or ft)
            i = 0
            while True:
                e = struct.unpack_from("<Q", self.d, thunk + 8 * i)[0]
                if not e:
                    break
                if not (e >> 63):
                    no = self.rva2off(e & 0x7FFFFFFF)
                    nm = bytes(self.d[no + 2:no + 2 + 80]).split(b"\0")[0].decode("latin1")
                    res.setdefault(nm, self.image_base + ft + 8 * i)
                i += 1
            o += 20
        return res

    # --- wide / narrow string at VA -------------------------------------------
    def wstr(self, va, maxlen=128):
        o = self.va2off(va)
        if o is None:
            return None
        raw = bytes(self.d[o:o + maxlen * 2])
        end = 0
        while end + 1 < len(raw) and raw[end:end + 2] != b"\0\0":
            end += 2
        try:
            return raw[:end].decode("utf-16le")
        except UnicodeDecodeError:
            return None

    # --- checksum ---------------------------------------------------------------
    def fix_checksum(self):
        ck_off = self.opt + 64
        self.d[ck_off:ck_off + 4] = b"\0\0\0\0"
        data = bytes(self.d)
        if len(data) % 2:
            data += b"\0"
        s = 0
        for (w,) in struct.iter_unpack("<H", data):
            s += w
            s = (s & 0xFFFF) + (s >> 16)
        s = (s & 0xFFFF) + (s >> 16)
        s = (s + len(self.d)) & 0xFFFFFFFF
        struct.pack_into("<I", self.d, ck_off, s)


# --------------------------------------------------------------------------
# Pattern scanning
# --------------------------------------------------------------------------
def rip_target(pe, off, ilen_before_disp, total_len):
    """VA targeted by a rip-relative disp32 located at off+ilen_before_disp."""
    disp = struct.unpack_from("<i", pe.d, off + ilen_before_disp)[0]
    va = pe.off2va(off)
    return va + total_len + disp


def find_all(buf, pat_regex, start, end):
    return [m.start() for m in pat_regex.finditer(bytes(buf[start:end]))]


class Finder:
    def __init__(self, pe):
        self.pe = pe
        self.imps = pe.imports()
        self.ranges = pe.code_ranges()

    def need(self, *names):
        miss = [n for n in names if n not in self.imps]
        if miss:
            raise LookupError("import(s) not present in this build: " + ", ".join(miss))
        return [self.imps[n] for n in names]

    def scan_code(self, regex):
        """yield file offsets of regex matches inside executable sections"""
        rx = re.compile(regex, re.S)
        for s, e, _ in self.ranges:
            for m in rx.finditer(bytes(self.pe.d[s:e])):
                yield s + m.start(), m

    # ---- feature 1: quit instead of staying resident -------------------------
    def quit_stubs(self):
        """VAs of 'xor ecx,ecx ; [add rsp,N] ; call/jmp [PostQuitMessage]' blocks."""
        (pqm,) = self.need("PostQuitMessage")
        pe = self.pe
        stubs = {}
        rx = (rb"(?:\x31\xC9|\x33\xC9)(?:\x48\x83\xC4[\x00-\x7f])?"
              rb"(?:\xFF\x15|\x48\xFF\x25|\xFF\x25)(....)")
        for off, m in self.scan_code(rx):
            end_of_instr = off + (m.end(1) - m.start())   # end of the rip-relative instruction
            disp = struct.unpack("<i", m.group(1))[0]
            target = pe.off2va(end_of_instr) + disp
            if target == pqm:
                stubs[pe.off2va(off)] = off
        return stubs

    def find_quit_branches(self):
        """
        Conditional jumps (je) to a PostQuitMessage stub, directly preceded by a
        64-bit compare of a struct field (the 'is resident' test):
            cmp qword [reg+disp32], 0      REX.W 83 /7 modrm disp32 00
            cmp qword [reg+disp32], reg    REX.W 39 /r  modrm disp32
        Returns list of dict(off, kind, va, target, field).
        """
        pe = self.pe
        stubs = self.quit_stubs()
        found = []
        for off, m in self.scan_code(rb"\x74[\x00-\x7f]|\x0F\x84....|\xEB[\x00-\x7f]|\xE9....\x90"):
            va = pe.off2va(off)
            g = m.group(0)
            patched = False
            if g[0] == 0x74:
                tgt = va + 2 + g[1]
                kind, ilen = "short", 2
            elif g[0] == 0xEB:
                tgt = va + 2 + g[1]
                kind, ilen, patched = "short", 2, True
            elif g[0] == 0x0F:
                tgt = va + 6 + struct.unpack("<i", g[2:6])[0]
                kind, ilen = "near", 6
            else:
                tgt = va + 5 + struct.unpack("<i", g[1:5])[0]
                kind, ilen, patched = "near", 6, True
            if tgt not in stubs:
                continue
            field = None
            b = pe.d
            # cmp qword [reg+disp32], imm8(0)
            if off >= 8:
                p = off - 8
                if (0x48 <= b[p] <= 0x49 and b[p + 1] == 0x83 and (b[p + 2] & 0xC0) == 0x80
                        and (b[p + 2] >> 3) & 7 == 7 and (b[p + 2] & 7) != 4 and b[p + 7] == 0):
                    field = struct.unpack_from("<I", b, p + 3)[0]
            # cmp [reg+disp32], r64   /  cmp r64, [reg+disp32]
            if field is None and off >= 7:
                p = off - 7
                if (0x48 <= b[p] <= 0x4F and b[p + 1] in (0x39, 0x3B) and (b[p + 2] & 0xC0) == 0x80
                        and (b[p + 2] & 7) != 4):
                    field = struct.unpack_from("<I", b, p + 3)[0]
            if field is None:
                continue
            found.append(dict(off=off, kind=kind, va=va, target=tgt, field=field, ilen=ilen, patched=patched))
        return found

    # ---- feature 2: minimize -> tray -----------------------------------------
    def find_main_hwnd_disp(self):
        """
        CCleaner's own restore routine does   mov rbx,[rbx+DISP] ; mov rcx,rbx ;
        call [IsIconic] ; ... ShowWindow(hwnd, SW_RESTORE).  DISP is where the main
        GUI object keeps its HWND, which tells us which title-bar handler is "the"
        main window (other windows such as dialogs have a different offset).
        """
        (isic,) = self.need("IsIconic")
        pe = self.pe
        res = []
        for off, m in self.scan_code(rb"\xFF\x15(....)"):
            if pe.off2va(off + 6) + struct.unpack("<i", m.group(1))[0] != isic:
                continue
            back = bytes(pe.d[max(off - 48, 0):off])
            cand = [(mm.start(), struct.unpack("<I", mm.group(1))[0])
                    for mm in re.finditer(rb"[\x48\x49\x4C\x4D]\x8B[\x80-\xBF](....)", back, re.S)]
            cand = [c for c in cand if c[1] >= 0x40]
            if cand:
                res.append(cand[-1][1])
        return sorted(set(res))

    def find_minimize_sites(self):
        """
        'mov r8d,0xF020 ; jmp tail'  where  tail =
            xor r9d,r9d ; mov edx,0x112 ; mov rcx,[reg+disp32] ; call [PostMessageW]
        """
        (pm,) = self.need("PostMessageW")
        pe = self.pe
        sites = []
        rx = rb"\x41\xB8\x20\xF0\x00\x00(?:\xEB([\x00-\x7f])|\xE9(....))"
        for off, m in self.scan_code(rx):
            va = pe.off2va(off)
            if m.group(1) is not None:
                tail_va = va + 8 + m.group(1)[0]
                span = 8
            else:
                tail_va = va + 11 + struct.unpack("<i", m.group(2))[0]
                span = 11
            to = pe.va2off(tail_va)
            if to is None:
                continue
            t = bytes(pe.d[to:to + 24])
            mt = re.match(rb"(?:\x45\x33\xC9|\x45\x31\xC9)\xBA\x12\x01\x00\x00"
                          rb"([\x48\x49\x4C\x4D]\x8B[\x80-\xBF](....))\xFF\x15(....)", t, re.S)
            if not mt:
                continue
            call_end_va = tail_va + mt.end()
            if call_end_va + struct.unpack("<i", mt.group(3))[0] != pm:
                continue
            sites.append(dict(off=off, va=va, span=span, tail_va=tail_va,
                              load_hwnd=mt.group(1), disp=struct.unpack("<I", mt.group(2))[0],
                              resume_va=call_end_va))
        return sites

    def find_tray_class(self):
        """
        The tray icon lives on a hidden top-level window whose class is
        L"CCleaner <n> <guid>". It is registered next to the code that does
        RegisterWindowMessageW(L"TaskbarCreated"), so: find that string, find
        code referencing it, then the first matching class-name string
        referenced just after it.
        """
        pe = self.pe
        pat = re.compile(r"^CCleaner \d+ [0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
        tb = "TaskbarCreated".encode("utf-16le") + b"\0\0"
        cands = []
        for s in pe.sections:
            if s["ch"] & SCN_EXEC or not s["rs"]:
                continue
            data = bytes(pe.d[s["ro"]:s["ro"] + s["rs"]])
            for m in re.finditer(re.escape(tb), data):
                if m.start() % 2:
                    continue
                cands.append(pe.image_base + s["va"] + m.start())
        for tva in cands:
            for off, m in self.scan_code(rb"[\x48\x4C]\x8D[\x05\x0D\x15\x1D\x25\x2D\x35\x3D](....)"):
                ref = pe.off2va(off + 7) + struct.unpack("<i", m.group(1))[0]
                if ref != tva:
                    continue
                window = bytes(pe.d[off:off + 0x400])
                for mm in re.finditer(rb"[\x48\x4C]\x8D[\x05\x0D\x15\x1D\x25\x2D\x35\x3D](....)", window, re.S):
                    cva = pe.off2va(off + mm.end()) + struct.unpack("<i", mm.group(1))[0]
                    s_ = pe.wstr(cva)
                    if s_ and pat.match(s_):
                        return cva, s_
        # fallback: wide string directly before "TaskbarCreated"
        for tva in cands:
            for back in range(2, 0x80, 2):
                s_ = pe.wstr(tva - back)
                if s_ and pat.match(s_) and (tva - back) + (len(s_) + 1) * 2 == tva:
                    return tva - back, s_
        return None, None


# --------------------------------------------------------------------------
# Stub assembly (position independent, x64)
# --------------------------------------------------------------------------
class Asm:
    def __init__(self, base_va):
        self.base = base_va
        self.b = bytearray()
        self.fix = []   # (pos_of_rel32, kind, target_va_or_label)
        self.labels = {}

    @property
    def va(self):
        return self.base + len(self.b)

    def raw(self, bs):
        self.b += bs

    def lea_rcx_rip(self, target_va):
        self.raw(b"\x48\x8D\x0D")
        self.fix.append((len(self.b), target_va))
        self.raw(b"\0\0\0\0")

    def call_iat(self, slot_va):
        self.raw(b"\xFF\x15")
        self.fix.append((len(self.b), slot_va))
        self.raw(b"\0\0\0\0")

    def jmp_abs(self, target_va):
        self.raw(b"\xE9")
        self.fix.append((len(self.b), target_va))
        self.raw(b"\0\0\0\0")

    def resolve(self):
        for pos, tgt in self.fix:
            end = self.base + pos + 4
            struct.pack_into("<i", self.b, pos, tgt - end)
        return bytes(self.b)


def build_stub(base_va, cls_va, findwindow, showwindow, site):
    a = Asm(base_va)
    a.lea_rcx_rip(cls_va)               # lea  rcx,[trayClass]
    a.raw(b"\x31\xD2")                  # xor  edx,edx
    a.call_iat(findwindow)              # call [FindWindowW]
    a.raw(b"\x48\x85\xC0")              # test rax,rax
    jz_pos = len(a.b)
    a.raw(b"\x74\x00")                  # jz   .normal
    a.raw(site["load_hwnd"])            # mov  rcx,[reg+disp]   (copied from original)
    a.raw(b"\xBA\x06\x00\x00\x00")      # mov  edx,SW_MINIMIZE
    a.call_iat(showwindow)
    a.raw(site["load_hwnd"])            # mov  rcx,[reg+disp]
    a.raw(b"\x31\xD2")                  # xor  edx,edx   (SW_HIDE)
    a.call_iat(showwindow)
    a.jmp_abs(site["resume_va"])        # continue after the original PostMessageW
    normal = len(a.b)
    a.b[jz_pos + 1] = normal - (jz_pos + 2)
    a.raw(b"\x41\xB8\x20\xF0\x00\x00")  # mov  r8d,SC_MINIMIZE   (original instruction)
    a.jmp_abs(site["tail_va"])          # jmp  original PostMessageW tail
    return a


# --------------------------------------------------------------------------
# Applying
# --------------------------------------------------------------------------
def strip_signature_and_add_section(pe, name, payload_fn):
    """
    payload_fn(base_va) -> bytes. Returns (section_va_base). Removes the
    Authenticode blob (it is invalid after patching and sits at EOF), appends a
    new R+X section and fixes the headers.
    """
    d = pe.d
    # 1. drop certificate table if it lives at the end of the file
    cert_off, cert_size = struct.unpack_from("<II", d, pe.dd + 4 * 8)
    last_end = max(s["ro"] + s["rs"] for s in pe.sections if s["rs"])
    if cert_off:
        if cert_off + cert_size < len(d) and cert_off + cert_size != len(d):
            print("  ! certificate is not at end of file; leaving file tail untouched")
        else:
            del d[cert_off:]
        struct.pack_into("<II", d, pe.dd + 4 * 8, 0, 0)
    # 2. room for another section header?
    end_tbl = pe.sec_table + 40 * pe.nsec
    first_raw = min(s["ro"] for s in pe.sections if s["rs"])
    if end_tbl + 40 > first_raw or any(d[end_tbl:end_tbl + 40]):
        raise RuntimeError("no free room for an extra section header")
    # 3. layout
    new_va = align_up(max(s["va"] + max(s["vs"], s["rs"]) for s in pe.sections), pe.sec_align)
    base_va = pe.image_base + new_va
    payload = payload_fn(base_va)
    raw_off = align_up(len(d), pe.file_align)
    d += b"\0" * (raw_off - len(d))
    raw_size = align_up(len(payload), pe.file_align)
    d += payload + b"\0" * (raw_size - len(payload))
    # 4. header
    hdr = (name.encode().ljust(8, b"\0")
           + struct.pack("<IIIIIIHHI", len(payload), new_va, raw_size, raw_off, 0, 0, 0, 0,
                         SCN_CODE | SCN_EXEC | SCN_READ))
    d[end_tbl:end_tbl + 40] = hdr
    struct.pack_into("<H", d, pe.pe + 6, pe.nsec + 1)
    new_image = align_up(new_va + len(payload), pe.sec_align)
    struct.pack_into("<I", d, pe.opt + 56, new_image)
    size_of_code = struct.unpack_from("<I", d, pe.opt + 4)[0]
    struct.pack_into("<I", d, pe.opt + 4, size_of_code + raw_size)
    return base_va


def patch(path_in, path_out, do_close=True, do_min=True, dry=False, hwnd_disp_override=None, log=print):
    data = open(path_in, "rb").read()
    pe = PE(data)
    F = Finder(pe)
    changes = []   # (file_offset, new_bytes, description)
    stub_jobs = []
    problems = []

    # ---------------- X = exit -------------------------------------------------
    if do_close:
        log("[close] looking for the 'resident vs quit' branch ...")
        br = F.find_quit_branches()
        # keep the group that shares the most common field offset
        if br:
            from collections import Counter
            top = Counter(b["field"] for b in br).most_common(1)[0][0]
            br = [b for b in br if b["field"] == top]
        if not br:
            problems.append("close: no 'cmp [obj+field],0 ; je -> PostQuitMessage' branch found")
        for b in br:
            o = b["off"]
            cur = bytes(pe.d[o:o + b["ilen"]])
            if b["patched"]:
                log("  already patched @ VA 0x%X" % b["va"])
                continue
            if b["kind"] == "short":
                new = b"\xEB" + cur[1:2]
            else:
                rel = struct.unpack("<i", cur[2:6])[0]
                new = b"\xE9" + struct.pack("<i", rel + 1) + b"\x90"
            changes.append((o, new, "close: je->jmp (always quit when no window is open) @ VA 0x%X, field +0x%X"
                            % (b["va"], b["field"])))
            log("  found je @ VA 0x%X (file 0x%X, %s) testing field +0x%X" % (b["va"], o, b["kind"], b["field"]))

    # ---------------- minimize = tray ----------------------------------------------
    if do_min:
        log("[minimize] looking for the SC_MINIMIZE title-bar handler ...")
        try:
            if any(sec["name"] == ".tray" for sec in pe.sections):
                log("  '.tray' section already present -> minimize patch already applied")
                raise StopIteration
            (fw, sw) = F.need("FindWindowW", "ShowWindow")
            sites = F.find_minimize_sites()
            if not sites:
                raise LookupError("no 'mov r8d,0xF020 ; jmp -> PostMessageW(WM_SYSCOMMAND)' site found")
            disps = F.find_main_hwnd_disp()
            log("  title-bar handlers found: %d (HWND offsets: %s)" %
                (len(sites), ", ".join("+0x%X" % s["disp"] for s in sites)))
            if hwnd_disp_override is not None:
                disps = [hwnd_disp_override]
                log("  using forced main-window HWND offset +0x%X" % hwnd_disp_override)
            else:
                log("  main-window HWND offset (from CCleaner's own restore routine): %s" %
                    (", ".join("+0x%X" % x for x in disps) or "NOT FOUND"))
            main_sites = [s for s in sites if s["disp"] in disps]
            if not main_sites:
                raise LookupError("could not tell which handler belongs to the main window "
                                  "(use --hwnd-disp 0x... to force one of the offsets above)")
            cls_va, cls = F.find_tray_class()
            if not cls_va:
                raise LookupError("tray window class name not found")
            log("  tray window class: %r @ VA 0x%X" % (cls, cls_va))
            stub_jobs = [(s, fw, sw, cls_va) for s in main_sites]
        except StopIteration:
            pass
        except LookupError as e:
            problems.append("minimize: %s" % e)

    # ---------------- report / write -----------------------------------------------
    if problems:
        for p in problems:
            log("  !! " + p)
    nothing = not changes and not stub_jobs
    if dry:
        for c in changes:
            log("  would patch file 0x%X: %s -> %s   (%s)" % (c[0], bytes(pe.d[c[0]:c[0] + len(c[1])]).hex(), c[1].hex(), c[2]))
        for s, *_ in stub_jobs:
            log("  would redirect VA 0x%X (file 0x%X) to a new stub; bytes now %s" %
                (s["va"], s["off"], bytes(pe.d[s["off"]:s["off"] + s["span"]]).hex()))
        return 0 if not problems else 2
    # check for already-patched minimize site
    pending_jobs = []
    for job in stub_jobs:
        s = job[0]
        if pe.d[s["off"]] == 0xE9 and not bytes(pe.d[s["off"]:s["off"] + 6]) == b"\x41\xB8\x20\xF0\x00\x00":
            log("  minimize site @ VA 0x%X already patched" % s["va"])
        else:
            pending_jobs.append(job)
    if not changes and not pending_jobs:
        if problems:
            log("Nothing could be patched.")
            return 2
        log("Already patched - nothing to do.")
        return 3

    for off, new, desc in changes:
        pe.d[off:off + len(new)] = new
        log("  patched: " + desc)

    if pending_jobs:
        def payload(base_va):
            blob = bytearray()
            cur = base_va
            for (s, fw, sw, cls_va) in pending_jobs:
                stub = build_stub(cur, cls_va, fw, sw, s)
                b = stub.resolve()
                s["_stub_va"] = cur
                blob += b
                pad = (-len(blob)) % 16
                blob += b"\xCC" * pad
                cur = base_va + len(blob)
            return bytes(blob)
        base = strip_signature_and_add_section(pe, ".tray", payload)
        for (s, *_r) in pending_jobs:
            rel = s["_stub_va"] - (s["va"] + 5)
            new = b"\xE9" + struct.pack("<i", rel) + b"\x90" * (s["span"] - 5)
            pe.d[s["off"]:s["off"] + s["span"]] = new
            log("  patched: minimize -> tray stub at VA 0x%X, hooked @ VA 0x%X" % (s["_stub_va"], s["va"]))
    else:
        # only in-place edits: still invalidates signature; remove it for consistency
        cert_off, cert_size = struct.unpack_from("<II", pe.d, pe.dd + 32)
        if cert_off and cert_off + cert_size == len(pe.d):
            del pe.d[cert_off:]
            struct.pack_into("<II", pe.d, pe.dd + 32, 0, 0)
    pe.fix_checksum()
    with open(path_out, "wb") as f:
        f.write(pe.d)
    log("Wrote %s (%d bytes). Authenticode signature removed (it can't stay valid after patching)." % (path_out, len(pe.d)))
    return 0 if not problems else 2


def main(argv=None):
    ap = argparse.ArgumentParser(description="CCleaner 7: X = exit, '-' = minimize to tray")
    ap.add_argument("exe", help="path to CCleaner.exe (64-bit CCleaner 7 build)")
    ap.add_argument("-o", "--output", help="output file (default: patch in place, keeping <exe>.bak)")
    ap.add_argument("--dry-run", action="store_true", help="only show what would be patched")
    ap.add_argument("--no-close", action="store_true", help="skip the 'X exits' patch")
    ap.add_argument("--no-minimize", action="store_true", help="skip the 'minimize to tray' patch")
    ap.add_argument("--hwnd-disp", type=lambda x: int(x, 0), help="force main-window HWND field offset (advanced)")
    ap.add_argument("--version", action="version", version="ccleaner7_tray_patch %s" % __version__)
    a = ap.parse_args(argv)
    print_banner()
    print("CCleaner 7 patcher v%s" % __version__)

    if a.output:
        out = a.output
    else:
        out = a.exe
        if not a.dry_run:
            bak = a.exe + ".bak"
            if not os.path.exists(bak):
                shutil.copy2(a.exe, bak)
                print("Backup written: " + bak)
    try:
        return patch(a.exe, out, not a.no_close, not a.no_minimize, a.dry_run, a.hwnd_disp)
    except Exception as e:  # keep the message readable for end users
        print("ERROR: %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
