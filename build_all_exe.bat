@echo off
setlocal
cd /d "%~dp0"

call build_gui_exe.bat
call build_builder_exe.bat
endlocal
