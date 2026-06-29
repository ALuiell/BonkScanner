@echo off
setlocal

set "VENV_DIR=.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "PIP_EXE=%VENV_DIR%\Scripts\pip.exe"
set "PYINSTALLER_EXE=%VENV_DIR%\Scripts\pyinstaller.exe"

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

echo [BUILD] Building executable...
"%PYINSTALLER_EXE%" --clean --noupx --noconfirm --noconsole --onefile --icon="media/bonkscanner_icon.ico" --name "BonkScanner" --hidden-import unicodedata --hidden-import win32cred --hidden-import win32timezone --hidden-import keyring --add-data "media/bonkscanner_icon.ico;media" --add-data "media/settings_icon.png;media" --add-data "media/help_icon.svg;media" --add-data "media/bonkscanner_icon2.png;media" --add-data "media/checkmark.svg;media" --add-data "media/patreon_logo.svg;media" --add-data "media/kofi_logo.svg;media" --add-data "media/github_logo.svg;media" --add-data "media/discord_logo.svg;media" --add-data "media/overlay/index.html;media/overlay" --add-data "media/overlay/overlay.css;media/overlay" --add-data "media/overlay/overlay.js;media/overlay" --add-data "media/overlay/game_preview.jpg;media/overlay" --add-data "docs/help/help_ru.txt;docs/help" --add-data "docs/help/help_eng.txt;docs/help" --add-data "docs/help/help_ukr.txt;docs/help" main.py

if errorlevel 1 (
    echo [ERROR] PyInstaller failed to build the executable.
    pause
    exit /b 1
)

echo [DONE] Executable built successfully! You can find it in the "dist" folder.
pause
endlocal
