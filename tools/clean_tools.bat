@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "REPO_ROOT=%%~fI"

if exist "%REPO_ROOT%\.tools\dotnet\dotnet.exe" (
    echo [CLEAN] Shutting down local dotnet build servers...
    "%REPO_ROOT%\.tools\dotnet\dotnet.exe" build-server shutdown >nul 2>&1
)

if exist "%REPO_ROOT%\.tools\dotnet" (
    echo [CLEAN] Removing "%REPO_ROOT%\.tools\dotnet"...
    rmdir /s /q "%REPO_ROOT%\.tools\dotnet"
)

if exist "%REPO_ROOT%\.tools\msvc" (
    echo [CLEAN] Removing "%REPO_ROOT%\.tools\msvc"...
    rmdir /s /q "%REPO_ROOT%\.tools\msvc"
)

if exist "%REPO_ROOT%\.tools\nuget" (
    echo [CLEAN] Removing "%REPO_ROOT%\.tools\nuget"...
    rmdir /s /q "%REPO_ROOT%\.tools\nuget"
)

if exist "%REPO_ROOT%\.tools\dotnet-home" (
    echo [CLEAN] Removing "%REPO_ROOT%\.tools\dotnet-home"...
    rmdir /s /q "%REPO_ROOT%\.tools\dotnet-home"
)

echo [DONE] Local SDK/toolchain/cache folders removed.
endlocal
