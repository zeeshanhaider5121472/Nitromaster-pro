@echo off
REM Build NitroMasterPro.exe (onefile, windowed, x64). Run from the repo root.
setlocal
cd /d "%~dp0"

echo [1/3] Installing build dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

echo [2/3] Running test suite...
python -m pytest -q || goto :error

echo [3/3] Building executable...
python -m PyInstaller --clean --noconfirm NitroMaster.spec || goto :error

echo.
echo Build complete: dist\NitroMasterPro.exe
exit /b 0

:error
echo Build FAILED.
exit /b 1
