@echo off
setlocal

set "REPO_ROOT=%~dp0"
set "PYTHON=%REPO_ROOT%.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo Project virtualenv was not found at .venv\Scripts\python.exe.
    echo Run start.bat first to create .venv.
    exit /b 1
)

if "%~1"=="" (
    "%PYTHON%" -m unittest discover -s tests
) else (
    "%PYTHON%" -m unittest %*
)
