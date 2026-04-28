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

"%PYTHON_EXE%" -m unittest discover -s tests
set "TEST_EXIT_CODE=%ERRORLEVEL%"

if not "%TEST_EXIT_CODE%"=="0" (
    echo [ERROR] Test run failed with exit code %TEST_EXIT_CODE%.
    pause
    exit /b %TEST_EXIT_CODE%
)

echo [DONE] All tests passed.

endlocal
