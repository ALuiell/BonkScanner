@echo off
setlocal

set "VENV_DIR=.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "PIP_EXE=%VENV_DIR%\Scripts\pip.exe"
set "PYINSTALLER_EXE=%VENV_DIR%\Scripts\pyinstaller.exe"
set "HOOK_PROJECT=native\BonkHook"
set "HOOK_PUBLISH_DIR=%HOOK_PROJECT%\bin\Release\net8.0\win-x64\publish"

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Virtual environment was not found.
    echo Run start.bat first to create .venv and install dependencies.
    pause
    exit /b 1
)


if not exist "%PYINSTALLER_EXE%" (
    echo [SETUP] Installing PyInstaller...
    "%PIP_EXE%" install pyinstaller
    if errorlevel 1 (
        echo [ERROR] Failed to install PyInstaller.
        pause
        exit /b 1
    )
)

echo [BUILD] Publishing native hook...
call tools\build_native_hook.bat

if errorlevel 1 (
    echo [ERROR] Failed to publish native hook.
    pause
    exit /b 1
)

if not exist "%HOOK_PUBLISH_DIR%\BonkHook.dll" (
    echo [ERROR] Native hook DLL was not found after publish: "%HOOK_PUBLISH_DIR%\BonkHook.dll"
    pause
    exit /b 1
)

echo [BUILD] Building executable...
"%PYINSTALLER_EXE%" --clean --noconfirm --noconsole --onefile --icon="media/bonkscanner_icon.ico" --name "BonkScanner" --hidden-import unicodedata --add-data "media/bonkscanner_icon.ico;media" --add-data "media/settings_icon.png;media" --add-binary "%HOOK_PUBLISH_DIR%\*.dll;%HOOK_PUBLISH_DIR%" main.py

if errorlevel 1 (
    echo [ERROR] PyInstaller failed to build the executable.
    pause
    exit /b 1
)

echo [DONE] Executable built successfully! You can find it in the "dist" folder.
pause
endlocal
