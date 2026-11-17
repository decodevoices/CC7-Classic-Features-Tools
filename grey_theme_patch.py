#!/usr/bin/env python3
"""Patcholly grey theme for CCleaner 7: edits the colour palette inside gui\\assets\\spawn-ccleaner.css
(light) and spawn-ccleaner-dark.css (dark). Buttons/accents stay blue; the blue-slate side menu, window
background and modal colours become neutral grey. Backups: <file>.orig (made once). --undo restores them.
Usage: grey_theme_patch.py [--undo] [--auto | <CCleaner folder or CCleaner.exe>]
Exit codes: 0 ok, 1 nothing changed, 2 usage, 3 CCleaner UI folder not found."""
import os, re, sys, shutil

__version__ = "1.0"

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


GREY = {
    "spawn-ccleaner.css": {            # light theme
        "desktop-menu": "68 68 68", "desktop-menu-state-a": "85 85 85", "desktop-menu-state-b": "99 99 99",
        "background": "245 245 245", "background-state-a": "90 90 90", "background-state-b": "90 90 90",
        "modal-action": "34 34 34",
    },
    "spawn-ccleaner-dark.css": {       # dark theme
        "desktop-menu": "28 28 28", "desktop-menu-state-a": "45 45 45", "desktop-menu-state-b": "56 56 56",
        "background": "43 43 43", "desktop-ipm-banner": "56 56 56", "modal-action": "36 36 36",
        "surface": "56 56 56", "surface-state-a": "68 68 68", "surface-state-b": "78 78 78",
    },
}
# second palette: the title bar and some widgets read these hex tokens (--o2-colors-*), not the rgb ones
HEX = {
    "spawn-ccleaner.css": {
        "desktop-menu": "444444", "desktop-menu-state-a": "555555", "desktop-menu-state-b": "636363",
        "background": "f5f5f5", "background-state-a": "5a5a5a", "background-state-b": "5a5a5a",
        "modal-action": "222222",
    },
    "spawn-ccleaner-dark.css": {
        "desktop-menu": "1c1c1c", "desktop-menu-state-a": "2d2d2d", "desktop-menu-state-b": "383838",
        "background": "2b2b2b", "desktop-ipm-banner": "383838", "modal-action": "242424",
        "surface": "383838", "surface-state-a": "444444", "surface-state-b": "4e4e4e",
    },
}
LIGHT_GRADIENT = ("linear-gradient(90deg, #f9fbff 0%, #f0f5ff 100%)", "linear-gradient(90deg, #fafafa 0%, #f0f0f0 100%)")


def _walk_for_assets(root, max_depth=6):
    """Look below root for a folder that contains spawn-ccleaner.css."""
    if not os.path.isdir(root):
        return None
    base = root.rstrip("\\/").count(os.sep)
    for dp, dn, fn in os.walk(root):
        if dp.count(os.sep) - base >= max_depth:
            dn[:] = []
        if "spawn-ccleaner.css" in fn:
            return dp
    return None


def find_assets(p):
    p = os.path.abspath(p.strip().strip('"').strip())
    if os.path.isfile(p):                      # an .exe (or any file) was given -> use its folder
        p = os.path.dirname(p)
    for cand in (p, os.path.join(p, "assets"), os.path.join(p, "gui", "assets"),
                 os.path.join(p, "CCleaner 7", "gui", "assets"), os.path.join(p, "App", "CCleaner 7", "gui", "assets")):
        if os.path.isfile(os.path.join(cand, "spawn-ccleaner.css")):
            return cand
    found = _walk_for_assets(p)                # any layout below the given folder
    if found:
        return found
    q = p                                      # a few levels up, but only inside a CCleaner/Piriform folder
    for _ in range(3):
        q = os.path.dirname(q)
        if not q or not re.search(r"ccleaner|piriform", os.path.basename(q), re.I):
            continue
        found = _walk_for_assets(q)
        if found:
            return found
    return None


def auto_find():
    """Search the usual install locations for CCleaner's gui\\assets folder."""
    roots = []
    for env in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)", "LOCALAPPDATA", "APPDATA"):
        base = os.environ.get(env)
        if not base:
            continue
        for name in ("CCleaner 7", "CCleaner", os.path.join("Piriform", "CCleaner"), "Piriform"):
            roots.append(os.path.join(base, name))
    seen = set()
    for r in roots:
        if r.lower() in seen:
            continue
        seen.add(r.lower())
        found = _walk_for_assets(r)
        if found:
            return found
    return None


def apply(assets):
    total = 0
    for fn, cols in GREY.items():
        path = os.path.join(assets, fn)
        if not os.path.isfile(path):
            print("  %s not found - skipped" % fn)
            continue
        bk = path + ".orig"
        if not os.path.isfile(bk):
            shutil.copyfile(path, bk)
            print("  backup written: %s" % bk)
        else:
            print("  backup exists:  %s" % bk)
        src = open(bk, encoding="utf-8", newline="").read()      # always start from the original
        n = 0
        for name, rgb in cols.items():
            pat = re.compile(r"(--p-%s-rgb\s*:\s*)\d+ \d+ \d+" % re.escape(name))
            src, k = pat.subn(lambda m: m.group(1) + rgb, src)
            n += k
        for name, hx in HEX.get(fn, {}).items():
            pat = re.compile(r"(--o2-colors-%s\s*:\s*)#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?(?![0-9a-fA-F])" % re.escape(name))
            src, k = pat.subn(lambda m: m.group(1) + "#" + hx + (m.group(2) or ""), src)
            n += k
        if fn == "spawn-ccleaner.css" and LIGHT_GRADIENT[0] in src:
            src = src.replace(LIGHT_GRADIENT[0], LIGHT_GRADIENT[1]); n += 1
        open(path, "w", encoding="utf-8", newline="").write(src)
        print("  %s: %d values changed" % (fn, n))
        total += n
    return total


def undo(assets):
    n = 0
    for fn in GREY:
        bk = os.path.join(assets, fn + ".orig")
        if os.path.isfile(bk):
            shutil.copyfile(bk, os.path.join(assets, fn)); n += 1
            print("  restored %s" % fn)
    return n


def already_applied(assets):
    """True if a theme file differs from its .orig backup, i.e. the grey theme is in place."""
    for fn in GREY:
        path = os.path.join(assets, fn)
        bk = path + ".orig"
        if os.path.isfile(path) and os.path.isfile(bk):
            if open(path, "rb").read() != open(bk, "rb").read():
                return True
    return False


def main():
    argv = sys.argv[1:]
    args = [a for a in argv if not a.startswith("--")]
    print_banner()
    print("Grey theme patch v%s" % __version__)
    if args:
        assets = find_assets(args[0])
        if not assets:
            print("gui\\assets\\spawn-ccleaner.css not found under: %s" % args[0])
            return 3
    elif "--auto" in argv:
        assets = auto_find()
        if not assets:
            print("CCleaner's gui\\assets folder was not found automatically.")
            return 3
    else:
        print("usage: grey_theme_patch.py [--undo] [--auto | <CCleaner folder or CCleaner.exe>]")
        return 2
    print("CCleaner UI: %s" % assets)
    if "--undo" in argv:
        return 0 if undo(assets) else 1
    if already_applied(assets):
        print("The grey theme is already applied here (.orig backups found).")
        return 4
    return 0 if apply(assets) else 1


if __name__ == "__main__":
    sys.exit(main())
