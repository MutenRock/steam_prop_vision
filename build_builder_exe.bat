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

REM Build Config Builder EXE
pyinstaller --noconfirm --clean --onefile --windowed ^
  --name "SimEnv_ConfigBuilder" ^
  --paths "%CD%" ^
  "%CD%\tools\config_builder_app.py"

echo.
echo EXE built in: dist\SimEnv_ConfigBuilder.exe
pause
endlocal
