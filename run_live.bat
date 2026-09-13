@echo off
REM ============================================================
REM  Opportunities Radar - collect REAL public data (live)
REM  Run setup_and_run.bat once first. This can take minutes.
REM ============================================================
cd /d "%~dp0"
title Opportunities Radar - live run

if not exist ".venv\Scripts\radar.exe" (
  echo   Please run setup_and_run.bat first.
  pause
  exit /b 1
)

echo Collecting LIVE public data for all companies.
echo This is slow on purpose ^(polite to the news sites^). Please wait...
call ".venv\Scripts\radar.exe" init-db
call ".venv\Scripts\radar.exe" ingest --live
call ".venv\Scripts\radar.exe" dashboard

echo Opening the dashboard in your browser...
start "" "data\exports\dashboard.html"
echo.
echo   Done. If Yahoo Finance came back empty, that is the known issue - tell Claude.
echo.
pause
