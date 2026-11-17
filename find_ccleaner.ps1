# CCleaner 7 patcher v1.0
# Finds every CCleaner.exe in Program Files, on the Desktop(s) and inside this patcher's folder
# and prints each full path once (one per line). Robust against unset OneDrive variables and
# against running under a different account: it also scans every user profile's Desktop.
param(
    [string]$ScriptDir = ""
)
$ErrorActionPreference = 'SilentlyContinue'
$found = New-Object System.Collections.Generic.List[string]
$seen  = New-Object System.Collections.Generic.HashSet[string] ([System.StringComparer]::OrdinalIgnoreCase)
$log   = New-Object System.Collections.Generic.List[string]

function Add-Hit([string]$p) {
    if ($p -and (Test-Path -LiteralPath $p -PathType Leaf)) {
        $full = (Resolve-Path -LiteralPath $p).ProviderPath
        if ($seen.Add($full)) { [void]$found.Add($full) }
    }
}
# every CCleaner.exe anywhere below a folder, whatever the layout
function Add-Tree([string]$root) {
    if (-not $root) { return }
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { return }
    [void]$log.Add("search: $root")
    Get-ChildItem -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue |
        Where-Object { (-not $_.PSIsContainer) -and ($_.Name -ieq 'CCleaner.exe') } |
        ForEach-Object { Add-Hit $_.FullName }
}

# ---- 1) installed CCleaner: Program Files (64-bit and 32-bit) ----
$pf = @($env:ProgramFiles, $env:ProgramW6432, ${env:ProgramFiles(x86)}) | Where-Object { $_ } | Select-Object -Unique
foreach ($root in $pf) {
    foreach ($r in @('CCleaner 7\CCleaner.exe','Piriform\CCleaner 7\CCleaner.exe','Piriform\CCleaner\CCleaner.exe','CCleaner\CCleaner.exe')) { Add-Hit (Join-Path $root $r) }
    Add-Tree (Join-Path $root 'Piriform')
}

# ---- 2) Desktop(s) ----
$deskRoots = New-Object System.Collections.Generic.List[string]
function Add-Desk([string]$d) {
    if ($d -and (Test-Path -LiteralPath $d -PathType Container) -and -not $deskRoots.Contains($d)) { [void]$deskRoots.Add($d) }
}
Add-Desk ([Environment]::GetFolderPath('Desktop'))
Add-Desk ([Environment]::GetFolderPath('CommonDesktopDirectory'))
if ($env:USERPROFILE)        { Add-Desk (Join-Path $env:USERPROFILE 'Desktop') }
if ($HOME)                   { Add-Desk (Join-Path $HOME 'Desktop') }
if ($env:OneDrive)           { Add-Desk (Join-Path $env:OneDrive 'Desktop') }
if ($env:OneDriveConsumer)   { Add-Desk (Join-Path $env:OneDriveConsumer 'Desktop') }
if ($env:OneDriveCommercial) { Add-Desk (Join-Path $env:OneDriveCommercial 'Desktop') }
if ($env:PUBLIC)             { Add-Desk (Join-Path $env:PUBLIC 'Desktop') }
# every user profile's Desktop (covers "run as a different admin" / multi-user)
if ($env:SystemDrive) {
    $usersDir = Join-Path $env:SystemDrive 'Users'
    if (Test-Path -LiteralPath $usersDir -PathType Container) {
        foreach ($u in @(Get-ChildItem -LiteralPath $usersDir -Directory -ErrorAction SilentlyContinue)) {
            Add-Desk (Join-Path $u.FullName 'Desktop')
        }
    }
}
foreach ($d in $deskRoots) { Add-Tree $d }

# ---- 3) the patcher's own folder (CCleaner put inside the patcher) ----
if ($ScriptDir) {
    $sd = $ScriptDir.TrimEnd('\', '.', '/')
    if ($sd) { Add-Tree $sd }
}

# ---- output (one path per line) ----
foreach ($f in $found) { [Console]::Out.WriteLine($f) }

# ---- diagnostic log next to the patcher (ignored by the .cmd) ----
if ($ScriptDir) {
    $sd = $ScriptDir.TrimEnd('\', '.', '/')
    if ($sd -and (Test-Path -LiteralPath $sd -PathType Container)) {
        $out = @()
        $out += "Folders searched:"
        $out += $log
        $out += ""
        $out += "CCleaner.exe found:"
        if ($found.Count -eq 0) { $out += "  (none)" } else { foreach ($f in $found) { $out += "  $f" } }
        Set-Content -LiteralPath (Join-Path $sd '_last_search.log') -Value $out -Encoding UTF8 -ErrorAction SilentlyContinue
    }
}
