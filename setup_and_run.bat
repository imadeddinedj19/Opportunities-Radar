@echo off
REM ============================================================
REM  Opportunities Radar - one-click setup + offline demo
REM  Double-click this file. First run installs everything.
REM ============================================================
cd /d "%~dp0"
title Opportunities Radar - setup

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo   Python was not found.
  echo   Install Python 3.11+ from https://www.python.org/downloads/
  echo   and tick "Add python.exe to PATH" on the first installer screen.
  echo.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating an isolated Python environment...
  python -m venv .venv
)

echo Installing the tool ^(first run only, may take a minute^)...
call ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
call ".venv\Scripts\python.exe" -m pip install --quiet -e .
if errorlevel 1 (
  echo.
  echo   Install failed. Copy the message above and send it to Claude.
  pause
  exit /b 1
)

echo Building the sample dashboard...
call ".venv\Scripts\radar.exe" init-db
call ".venv\Scripts\radar.exe" ingest --offline
call ".venv\Scripts\radar.exe" dashboard

echo Opening the dashboard in your browser...
start "" "data\exports\dashboard.html"

echo.
echo   Done. This was the OFFLINE sample. For real data, run  run_live.bat
echo.
pause
