@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "REPO_ROOT=%%~fI"
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

if not exist "%POWERSHELL_EXE%" (
    echo [ERROR] powershell.exe was not found at "%POWERSHELL_EXE%".
    echo [ERROR] Portable toolchain bootstrap requires Windows PowerShell.
    exit /b 1
)

echo [SETUP] Bootstrapping project-local .NET SDK...
"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%REPO_ROOT%\tools\bootstrap_dotnet.ps1"
if errorlevel 1 (
    echo [ERROR] Failed to bootstrap the project-local .NET SDK.
    exit /b 1
)

echo [SETUP] Bootstrapping portable MSVC and Windows SDK...
"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%REPO_ROOT%\tools\bootstrap_msvc.ps1"
if errorlevel 1 (
    echo [ERROR] Failed to bootstrap portable MSVC and Windows SDK.
    echo [ERROR] Fallback: install Visual Studio Build Tools with the Desktop development with C++ workload.
    exit /b 1
)

echo [DONE] Portable build tools are ready under "%REPO_ROOT%\.tools".
endlocal
