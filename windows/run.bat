@echo off
rem Runs ClipBridge from source (needs Python 3.10+ from python.org). First run installs the libraries.
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv 2>nul || python -m venv .venv
)
.venv\Scripts\python -m pip install -q --disable-pip-version-check -r requirements.txt
start "" .venv\Scripts\pythonw.exe ClipBridge.pyw
