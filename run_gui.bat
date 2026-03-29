@echo off
setlocal
cd /d "%~dp0"

REM Prefer venv if exists
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m gui.app
) else (
  python -m gui.app
)
endlocal
