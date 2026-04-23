@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "REPO_ROOT=%%~fI"
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

set "DOTNET_ROOT=%REPO_ROOT%\.tools\dotnet"
set "DOTNET_EXE=%DOTNET_ROOT%\dotnet.exe"
set "MSVC_SETUP=%REPO_ROOT%\.tools\msvc\setup_x64.bat"
set "MSVC_ROOT=%REPO_ROOT%\.tools\msvc"
set "WINDOWS_KITS_ROOT=%MSVC_ROOT%\Windows Kits\10"
set "NUGET_ROOT=%REPO_ROOT%\.tools\nuget"
set "NUGET_PACKAGES_DIR=%NUGET_ROOT%\packages"
set "NUGET_HTTP_CACHE_DIR=%NUGET_ROOT%\http-cache"
set "NUGET_SCRATCH_DIR=%NUGET_ROOT%\scratch"
set "DOTNET_CLI_HOME_DIR=%REPO_ROOT%\.tools\dotnet-home"
set "HOOK_PROJECT=%REPO_ROOT%\native\BonkHook"
set "HOOK_DLL=%HOOK_PROJECT%\bin\Release\net8.0\win-x64\publish\BonkHook.dll"

cd /d "%REPO_ROOT%"

if not exist "%POWERSHELL_EXE%" (
    echo [ERROR] powershell.exe was not found at "%POWERSHELL_EXE%".
    echo [ERROR] Portable bootstrap requires Windows PowerShell to download the local toolchain.
    exit /b 1
)

if not exist "%NUGET_PACKAGES_DIR%" mkdir "%NUGET_PACKAGES_DIR%"
if not exist "%NUGET_HTTP_CACHE_DIR%" mkdir "%NUGET_HTTP_CACHE_DIR%"
if not exist "%NUGET_SCRATCH_DIR%" mkdir "%NUGET_SCRATCH_DIR%"
if not exist "%DOTNET_CLI_HOME_DIR%" mkdir "%DOTNET_CLI_HOME_DIR%"

if not exist "%DOTNET_EXE%" (
    echo [SETUP] Local .NET SDK was not found. Bootstrapping...
    "%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%REPO_ROOT%\tools\bootstrap_dotnet.ps1"
    if errorlevel 1 (
        echo [ERROR] Failed to bootstrap local .NET SDK.
        exit /b 1
    )
)

set "HAS_LOCAL_DOTNET_SDK="
for /f "delims=" %%S in ('"%DOTNET_EXE%" --list-sdks 2^>nul') do (
    set "HAS_LOCAL_DOTNET_SDK=1"
    goto :dotnet_sdk_ready
)

if not defined HAS_LOCAL_DOTNET_SDK (
    echo [SETUP] Local dotnet installation is incomplete. Reinstalling project-local SDK...
    "%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%REPO_ROOT%\tools\bootstrap_dotnet.ps1"
    if errorlevel 1 (
        echo [ERROR] Failed to repair the project-local .NET SDK.
        exit /b 1
    )
)

:dotnet_sdk_ready

if not exist "%MSVC_SETUP%" (
    echo [SETUP] Portable MSVC toolchain was not found. Bootstrapping...
    "%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%REPO_ROOT%\tools\bootstrap_msvc.ps1"
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

if "%WindowsSdkDir%"=="" set "WindowsSdkDir=%WINDOWS_KITS_ROOT%\"
if "%UniversalCRTSdkDir%"=="" set "UniversalCRTSdkDir=%WindowsSdkDir%"
if "%UCRTVersion%"=="" set "UCRTVersion=%WindowsSDKVersion%"

where.exe link.exe >nul 2>&1
if errorlevel 1 (
    echo [ERROR] link.exe was not found after initializing portable MSVC.
    echo [ERROR] NativeAOT cannot use the portable toolchain because the linker environment is incomplete.
    exit /b 1
)

where.exe cl.exe >nul 2>&1
if errorlevel 1 (
    echo [ERROR] cl.exe was not found after initializing portable MSVC.
    echo [ERROR] NativeAOT cannot use the portable toolchain because the compiler environment is incomplete.
    exit /b 1
)

if "%VCToolsInstallDir%"=="" (
    echo [ERROR] VCToolsInstallDir was not set after initializing portable MSVC.
    echo [ERROR] NativeAOT will ignore the portable toolchain unless the environment is complete.
    exit /b 1
)

if "%INCLUDE%"=="" (
    echo [ERROR] INCLUDE was not set after initializing portable MSVC.
    echo [ERROR] NativeAOT cannot use the portable toolchain because the include environment is incomplete.
    exit /b 1
)

if "%LIB%"=="" (
    echo [ERROR] LIB was not set after initializing portable MSVC.
    echo [ERROR] NativeAOT cannot use the portable toolchain because the library environment is incomplete.
    exit /b 1
)

if "%WindowsSdkDir%"=="" (
    echo [ERROR] WindowsSdkDir was not set after initializing portable MSVC.
    echo [ERROR] NativeAOT will ignore the portable toolchain unless the environment is complete.
    exit /b 1
)

if "%WindowsSDKVersion%"=="" (
    echo [ERROR] WindowsSDKVersion was not set after initializing portable MSVC.
    echo [ERROR] NativeAOT will ignore the portable toolchain unless the environment is complete.
    exit /b 1
)

if "%UniversalCRTSdkDir%"=="" (
    echo [ERROR] UniversalCRTSdkDir was not set after initializing portable MSVC.
    echo [ERROR] NativeAOT will ignore the portable toolchain unless the environment is complete.
    exit /b 1
)

if "%UCRTVersion%"=="" (
    echo [ERROR] UCRTVersion was not set after initializing portable MSVC.
    echo [ERROR] NativeAOT will ignore the portable toolchain unless the environment is complete.
    exit /b 1
)

set "PATH=%DOTNET_ROOT%;%PATH%"
set "DOTNET_ROOT=%DOTNET_ROOT%"
set "DOTNET_CLI_HOME=%DOTNET_CLI_HOME_DIR%"
set "DOTNET_CLI_TELEMETRY_OPTOUT=1"
set "DOTNET_NOLOGO=1"
set "DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1"
set "DOTNET_GENERATE_ASPNET_CERTIFICATE=false"
set "DOTNET_ADD_GLOBAL_TOOLS_TO_PATH=false"
set "DOTNET_MULTILEVEL_LOOKUP=0"
set "NUGET_PACKAGES=%NUGET_PACKAGES_DIR%"
set "NUGET_HTTP_CACHE_PATH=%NUGET_HTTP_CACHE_DIR%"
set "NUGET_SCRATCH=%NUGET_SCRATCH_DIR%"

echo [BUILD] Publishing native hook with project-local .NET SDK and portable MSVC...
"%DOTNET_EXE%" publish "%HOOK_PROJECT%" -c Release -r win-x64 /p:IlcUseEnvironmentalTools=true
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
