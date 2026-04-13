@echo off
setlocal

set "PYTHON_VERSION=3.12"
set "VENV_DIR=.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"

where py >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python launcher 'py' was not found.
    echo Install Python %PYTHON_VERSION% x64 from https://www.python.org/downloads/windows/
    pause
    exit /b 1
)

py -%PYTHON_VERSION% --version >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python %PYTHON_VERSION% x64 is not installed or not available through 'py'.
    echo Install Python %PYTHON_VERSION% x64 and make sure the Python launcher is enabled.
    pause
    exit /b 1
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [SETUP] Creating virtual environment in %VENV_DIR%...
    py -%PYTHON_VERSION% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [ERROR] Failed to create the virtual environment.
        pause
        exit /b 1
    )
)

echo [SETUP] Upgrading pip...
"%PYTHON_EXE%" -m pip install --upgrade pip
if errorlevel 1 (
    echo [ERROR] Failed to upgrade pip inside %VENV_DIR%.
    pause
    exit /b 1
)

echo [SETUP] Installing dependencies from requirements.txt...
"%PYTHON_EXE%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies from requirements.txt.
    pause
    exit /b 1
)

echo [DONE] Virtual environment is ready.
echo [DONE] To run the app later, use:
echo        %PYTHON_EXE% main.py
echo [DONE] Or activate the environment and run:
echo        .\%VENV_DIR%\Scripts\Activate.ps1

endlocal
