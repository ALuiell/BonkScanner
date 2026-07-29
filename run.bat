@echo off
setlocal

set "VENV_DIR=.venv"
set "PYTHONW_EXE=%VENV_DIR%\Scripts\pythonw.exe"

pushd "%~dp0"

if not exist "%PYTHONW_EXE%" (
    echo [ERROR] Virtual environment was not found.
    echo Run start.bat first to create .venv and install dependencies.
    pause
    popd
    exit /b 1
)

start "" "%PYTHONW_EXE%" src\main.py
if errorlevel 1 (
    echo [ERROR] BonkScanner exited with an error.
    pause
    popd
    exit /b 1
)

popd
endlocal
