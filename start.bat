@echo off
setlocal
REM SmartStreet one-command start for Windows
cd /d "%~dp0"
title SmartStreet

REM --- find a working Python (py launcher preferred, then python) ---
set PY=
where py >nul 2>nul && set PY=py
if "%PY%"=="" ( where python >nul 2>nul && set PY=python )

if "%PY%"=="" (
  echo.
  echo [ERROR] Python was not found on this computer.
  echo Install Python 3.10+ from https://www.python.org/downloads/
  echo IMPORTANT: on the installer's first screen, tick "Add python.exe to PATH".
  echo Then re-run start.bat.
  echo.
  pause
  exit /b 1
)

echo Using Python: %PY%
%PY% --version

if not exist ".venv\" (
  echo Creating virtual environment...
  %PY% -m venv .venv
  if errorlevel 1 ( echo [ERROR] Could not create venv. & pause & exit /b 1 )
)

call .venv\Scripts\activate.bat

echo Installing dependencies (first run only, may take a minute)...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 ( echo [ERROR] Dependency install failed. & pause & exit /b 1 )

echo.
echo ============================================================
echo   SmartStreet is starting on http://localhost:8000
echo   Leave this window OPEN. Close it to stop the server.
echo ============================================================
echo.
python run.py

echo.
echo Server stopped.
pause
