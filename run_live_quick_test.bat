@echo off
REM ============================================================
REM  Opportunities Radar - quick LIVE test on 10 companies only
REM  Fast way to check live collection works before the full run.
REM ============================================================
cd /d "%~dp0"
title Opportunities Radar - live quick test

if not exist ".venv\Scripts\radar.exe" (
  echo   Please run setup_and_run.bat first.
  pause
  exit /b 1
)

echo Collecting LIVE data for the first 10 companies ^(quick test^)...
call ".venv\Scripts\radar.exe" init-db
call ".venv\Scripts\radar.exe" ingest --live --limit 10
call ".venv\Scripts\radar.exe" dashboard
start "" "data\exports\dashboard.html"
echo.
echo   Done. If this looked right, run the full run_live.bat next.
echo.
pause
