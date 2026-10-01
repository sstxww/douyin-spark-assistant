@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Please install Python 3.11+ from https://www.python.org/downloads/ and enable Add Python to PATH.
  pause
  exit /b 1
)
if not exist .venv\Scripts\python.exe (
  python -m venv .venv
  if errorlevel 1 goto :fail
)
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :fail
.venv\Scripts\python.exe -m playwright install chromium
if errorlevel 1 goto :fail
.venv\Scripts\python.exe setup_gui.py
if errorlevel 1 goto :fail
exit /b 0
:fail
echo Setup stopped. Please check the error above and your network connection.
pause
exit /b 1
