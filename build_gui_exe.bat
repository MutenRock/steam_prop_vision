@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo No .venv found. Run install_venv.bat first.
  pause
  exit /b 1
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install pyinstaller

REM Build Main GUI EXE
pyinstaller --noconfirm --clean --onefile --windowed ^
  --name "SimEnv_MainGUI" ^
  --paths "%CD%" ^
  "%CD%\gui\app.py"

echo.
echo EXE built in: dist\SimEnv_MainGUI.exe
pause
endlocal
