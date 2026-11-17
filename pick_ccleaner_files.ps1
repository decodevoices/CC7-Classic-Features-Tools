# CCleaner 7 patcher v1.0
# Shows a file picker and prints the chosen path (nothing if cancelled).
param(
    [switch]$Any,
    [switch]$Grey,
    [string]$Title  = "Select CCleaner.exe",
    [string]$Filter = "CCleaner.exe|CCleaner.exe|Executables (*.exe)|*.exe",
    [string]$InitialDir = ""
)
Add-Type -AssemblyName System.Windows.Forms
$candidates = @(
    "$env:ProgramFiles\CCleaner 7",
    "$env:ProgramFiles\CCleaner",
    "${env:ProgramFiles(x86)}\CCleaner"
)
if (-not $InitialDir) {
    foreach ($c in $candidates) { if (Test-Path $c) { $InitialDir = $c; break } }
}
if ($Any) {
    $Title  = "Browse for the .exe to patch"
    $Filter = "Executables (*.exe)|*.exe|All files (*.*)|*.*"
}
if ($Grey) {
    $Title  = "Grey theme: select CCleaner.exe  OR  spawn-ccleaner.css (in gui\assets)"
    $Filter = "CCleaner.exe or theme file|CCleaner.exe;spawn-ccleaner.css;spawn-ccleaner-dark.css|All files (*.*)|*.*"
}
$dlg = New-Object System.Windows.Forms.OpenFileDialog
$dlg.Title = $Title
$dlg.Filter = $Filter
$dlg.CheckFileExists = $true
if ($InitialDir) { $dlg.InitialDirectory = $InitialDir }
if ($dlg.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
    [Console]::Out.WriteLine($dlg.FileName)
}
