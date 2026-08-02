@echo off
setlocal

pushd "%~dp0"

set "VENV_DIR=.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Virtual environment was not found.
    echo Run start.bat first to create .venv and install dependencies.
    pause
    popd
    exit /b 1
)

echo BonkScanner development mode
echo Changes in src\*.py and redisign_ui\*.qss restart the app automatically.
echo Keep this window open. Press Ctrl+C to stop.
echo.

"%PYTHON_EXE%" tools\dev_runner.py
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] Development runner exited with code %EXIT_CODE%.
    pause
)

popd
endlocal & exit /b %EXIT_CODE%
