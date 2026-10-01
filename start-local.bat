@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.11+ is required. Install it with Add Python to PATH enabled.
  pause
  exit /b 1
)
if not exist ".venv-local\Scripts\python.exe" python -m venv .venv-local
if errorlevel 1 goto failed
.venv-local\Scripts\python.exe -m pip install -r requirements-web.txt
if errorlevel 1 goto failed
.venv-local\Scripts\python.exe -m playwright install chromium
if errorlevel 1 goto failed
.venv-local\Scripts\python.exe start_local.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo Installation or startup failed. No message has been sent.
pause
exit /b 1
