@echo off
setlocal

for %%I in ("%~dp0.") do set "REPO_ROOT=%%~fI"
set "PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
set "PYTHONPATH=%REPO_ROOT%;%REPO_ROOT%\src"

if not exist "%PYTHON%" (
    echo Project virtualenv was not found at .venv\Scripts\python.exe.
    echo Run start.bat first to create .venv.
    exit /b 1
)

pushd "%REPO_ROOT%" >nul
if errorlevel 1 (
    echo Failed to change directory to "%REPO_ROOT%".
    exit /b 1
)

if "%~1"=="" (
    "%PYTHON%" -m unittest discover -s "%REPO_ROOT%\src\tests"
) else (
    "%PYTHON%" -m unittest %*
)

set "EXIT_CODE=%ERRORLEVEL%"
popd >nul
exit /b %EXIT_CODE%