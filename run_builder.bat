@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m tools.config_builder_app
) else (
  python -m tools.config_builder_app
)
endlocal
