@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "REPO_ROOT=%%~fI"

if exist "%REPO_ROOT%\.tools\dotnet" (
    echo [CLEAN] Removing "%REPO_ROOT%\.tools\dotnet"...
    rmdir /s /q "%REPO_ROOT%\.tools\dotnet"
)

if exist "%REPO_ROOT%\.tools\msvc" (
    echo [CLEAN] Removing "%REPO_ROOT%\.tools\msvc"...
    rmdir /s /q "%REPO_ROOT%\.tools\msvc"
)

echo [DONE] Local SDK/toolchain folders removed.
endlocal
