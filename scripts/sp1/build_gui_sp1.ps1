# SP1: build GUI to one-file exe (PyInstaller). Run from repo root:
#   .\scripts\sp1\build_gui_sp1.ps1
# Optional: -Python <path\to\python.exe>

param(
    [string] $Python = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

function Get-PythonExe {
    if ($Python -and (Test-Path $Python)) { return $Python }
    $venvPy = Join-Path $RepoRoot "venv\Scripts\python.exe"
    if (Test-Path $venvPy) { return $venvPy }
    return "py"
}

$py = Get-PythonExe
Write-Host "Python: $py" -ForegroundColor Cyan

# pip install -e . (not .[gui]) avoids WinError32 overwriting venv\Scripts\delivery-vlm-gui.exe
& $py -m pip install -q -U pip
Push-Location $RepoRoot
try {
    & $py -m pip install -q -e "."
} finally {
    Pop-Location
}
& $py -m pip install -q "pyinstaller>=6.0" "sv-ttk>=2.6.0"

$spec = Join-Path $RepoRoot "scripts\sp1\delivery_vlm_gui_sp1.spec"
& $py -m PyInstaller --noconfirm --distpath (Join-Path $RepoRoot "dist\sp1") --workpath (Join-Path $RepoRoot "build\sp1") $spec

$exe = Join-Path $RepoRoot "dist\sp1\DeliverySlipVLM-GUI-SP1.exe"
if (Test-Path $exe) {
    Write-Host "OK: $exe" -ForegroundColor Green
} else {
    Write-Error "Output exe not found; see PyInstaller log above."
    exit 1
}
