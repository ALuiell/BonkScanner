@echo off
setlocal

set "VENV_DIR=.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Virtual environment was not found.
    echo Run start.bat first to create .venv and install dependencies.
    pause
    exit /b 1
)

start "" "%PYTHON_EXE%" main.py
if errorlevel 1 (
    echo [ERROR] BonkScanner exited with an error.
    pause
    exit /b 1
)

endlocal
