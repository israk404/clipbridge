@echo off
rem Builds dist\ClipBridge.exe locally (the GitHub workflow does the same thing).
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv 2>nul || python -m venv .venv
)
.venv\Scripts\python -m pip install -q --disable-pip-version-check -r requirements.txt pyinstaller
.venv\Scripts\pyinstaller --noconfirm --onefile --windowed --name ClipBridge --icon assets\clipbridge.ico ClipBridge.pyw
echo.
echo Done: %~dp0dist\ClipBridge.exe
pause
