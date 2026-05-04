# Builds dist\PCChecker.exe — graphical Windows app (no console, no "python" window).
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path "launcher.py")) { throw "Run from repo root (launcher.py missing)." }

python -m pip install "pyinstaller>=6.0" -q

$args = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    "--windowed",
    "--name", "PCChecker",
    "--paths", ".",
    "--collect-all", "customtkinter",
    "--collect-all", "matplotlib",
    "--collect-all", "fastapi",
    "--collect-all", "uvicorn",
    "launcher.py"
)
Write-Host "Running: python $($args -join ' ')"
python @args
Write-Host ""
Write-Host "Done. Launch: .\dist\PCChecker.exe"
