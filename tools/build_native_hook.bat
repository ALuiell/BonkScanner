@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "REPO_ROOT=%%~fI"

set "DOTNET_ROOT=%REPO_ROOT%\.tools\dotnet"
set "DOTNET_EXE=%DOTNET_ROOT%\dotnet.exe"
set "MSVC_SETUP=%REPO_ROOT%\.tools\msvc\setup_x64.bat"
set "HOOK_PROJECT=%REPO_ROOT%\native\BonkHook"
set "HOOK_DLL=%HOOK_PROJECT%\bin\Release\net8.0\win-x64\publish\BonkHook.dll"

cd /d "%REPO_ROOT%"

if not exist "%DOTNET_EXE%" (
    echo [SETUP] Local .NET SDK was not found. Bootstrapping...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%REPO_ROOT%\tools\bootstrap_dotnet.ps1"
    if errorlevel 1 (
        echo [ERROR] Failed to bootstrap local .NET SDK.
        exit /b 1
    )
)

if not exist "%MSVC_SETUP%" (
    echo [SETUP] Portable MSVC toolchain was not found. Bootstrapping...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%REPO_ROOT%\tools\bootstrap_msvc.ps1"
    if errorlevel 1 (
        echo [ERROR] Failed to bootstrap portable MSVC.
        echo [ERROR] Fallback: install Visual Studio Build Tools with the Desktop development with C++ workload.
        exit /b 1
    )
)

call "%MSVC_SETUP%"
if errorlevel 1 (
    echo [ERROR] Failed to initialize portable MSVC environment.
    exit /b 1
)

where.exe link.exe >nul 2>&1
if errorlevel 1 (
    echo [ERROR] link.exe was not found after initializing portable MSVC.
    echo [ERROR] Fallback: install Visual Studio Build Tools with the Desktop development with C++ workload.
    exit /b 1
)

set "PATH=%DOTNET_ROOT%;%PATH%"

echo [BUILD] Publishing native hook with project-local .NET SDK and portable MSVC...
"%DOTNET_EXE%" publish "%HOOK_PROJECT%" -c Release -r win-x64
if errorlevel 1 (
    echo [ERROR] Failed to publish native hook.
    exit /b 1
)

if not exist "%HOOK_DLL%" (
    echo [ERROR] Native hook DLL was not found after publish: "%HOOK_DLL%"
    exit /b 1
)

echo [DONE] Native hook built: "%HOOK_DLL%"
endlocal
