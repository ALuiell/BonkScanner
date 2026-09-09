@echo off
setlocal

pushd "%~dp0"
if errorlevel 1 (
    echo [ERROR] Failed to open the BonkScanner repository directory:
    echo         %~dp0
    pause
    exit /b 1
)

set "VENV_DIR=.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Virtual environment was not found.
    echo Run start.bat first to create .venv and install dependencies.
    pause
    popd
    exit /b 1
)


"%PYTHON_EXE%" -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    echo [SETUP] Installing PyInstaller...
    "%PYTHON_EXE%" -m pip install pyinstaller
    if errorlevel 1 (
        echo [ERROR] Failed to install PyInstaller.
        pause
        popd
        exit /b 1
    )
)

REM Assets go in by DIRECTORY, not one --add-data per file. The old list named
REM 18 files by hand, and three of them were simply never added: obs_icon.svg,
REM twitch_icon.svg and in_game_icon.svg. They render fine from source, so the
REM only symptom was a '?' placeholder on the OBS Overlay, Twitch Bot and
REM In-Game Overlay tabs of a built exe -- TabHero draws that when its icon
REM fails to load. A forgotten file cannot happen with a directory rule.
REM
REM src\media is therefore the ship set, including the application QSS theme,
REM and nothing that must not ship may sit in it. Local/reference assets that
REM may be useful later belong under the ignored ui_assets directory instead.
REM
REM BonkScanner.spec is this script's OUTPUT, not its input. Every run
REM regenerates it from these flags, which is why it is gitignored and why
REM editing it by hand never survives.
echo [BUILD] Building executable...
"%PYTHON_EXE%" -m PyInstaller --clean --noupx --noconfirm --noconsole --onefile --paths="src" --icon="src\media\bonkscanner_icon.ico" --name "BonkScanner" --hidden-import unicodedata --hidden-import win32cred --hidden-import win32timezone --hidden-import keyring --add-data "src\media;media" src\main.py

if errorlevel 1 (
    echo [ERROR] PyInstaller failed to build the executable.
    pause
    popd
    exit /b 1
)

echo [DONE] Executable built successfully! You can find it in the "dist" folder.
pause
popd
endlocal
