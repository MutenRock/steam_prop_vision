@echo off
setlocal
cd /d "%~dp0"

python -m venv .venv
if errorlevel 1 (
  echo Failed to create venv. Make sure Python is installed and on PATH.
  pause
  exit /b 1
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo.
echo Done. You can now run:
echo   run_gui.bat
echo   run_builder.bat
pause
endlocal
