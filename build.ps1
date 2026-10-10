# Build script for NitroMaster Pro (PowerShell).
# Produces dist\NitroMasterPro.exe (onefile, windowed, x64).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "[1/3] Installing build dependencies..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

Write-Host "[2/3] Running test suite..."
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed." }

Write-Host "[3/3] Building executable..."
python -m PyInstaller --clean --noconfirm NitroMaster.spec
if ($LASTEXITCODE -ne 0) { throw "Build failed." }

Write-Host "Build complete: dist\NitroMasterPro.exe" -ForegroundColor Green
