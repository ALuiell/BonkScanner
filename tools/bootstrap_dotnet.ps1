[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$DotnetInstallUrl = "https://dot.net/v1/dotnet-install.ps1"

function Fail($Message) {
    Write-Host "[ERROR] $Message" -ForegroundColor Red
    exit 1
}

function Test-DotnetSdkInstalled {
    param(
        [string]$DotnetExe,
        [string]$ExpectedVersion
    )

    if (-not (Test-Path -LiteralPath $DotnetExe)) {
        return $false
    }

    $SdkLines = @(& $DotnetExe --list-sdks 2>$null)
    foreach ($SdkLine in $SdkLines) {
        if ($SdkLine -match "^$([Regex]::Escape($ExpectedVersion))\s") {
            return $true
        }
    }

    return $false
}

try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
    $ToolsDir = Join-Path $RepoRoot ".tools"
    $DownloadsDir = Join-Path $ToolsDir "downloads"
    $DotnetDir = Join-Path $ToolsDir "dotnet"
    $DotnetCliHomeDir = Join-Path $ToolsDir "dotnet-home"
    $InstallScript = Join-Path $DownloadsDir "dotnet-install.ps1"
    $GlobalJsonPath = Join-Path $RepoRoot "global.json"

    if (-not (Test-Path -LiteralPath $GlobalJsonPath)) {
        Fail "global.json was not found at $GlobalJsonPath."
    }

    $GlobalJson = Get-Content -LiteralPath $GlobalJsonPath -Raw | ConvertFrom-Json
    $SdkVersion = [string]$GlobalJson.sdk.version
    if ([string]::IsNullOrWhiteSpace($SdkVersion)) {
        Fail "global.json does not contain sdk.version."
    }

    New-Item -ItemType Directory -Force -Path $DownloadsDir, $DotnetDir, $DotnetCliHomeDir | Out-Null

    $env:DOTNET_ROOT = $DotnetDir
    $env:DOTNET_CLI_HOME = $DotnetCliHomeDir
    $env:DOTNET_CLI_TELEMETRY_OPTOUT = "1"
    $env:DOTNET_NOLOGO = "1"
    $env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE = "1"
    $env:DOTNET_GENERATE_ASPNET_CERTIFICATE = "false"
    $env:DOTNET_ADD_GLOBAL_TOOLS_TO_PATH = "false"
    $env:DOTNET_MULTILEVEL_LOOKUP = "0"

    if (-not (Test-Path -LiteralPath $InstallScript)) {
        Write-Host "[SETUP] Downloading dotnet-install.ps1..."
        Invoke-WebRequest -Uri $DotnetInstallUrl -OutFile $InstallScript
    }

    $DotnetExe = Join-Path $DotnetDir "dotnet.exe"
    if (-not (Test-DotnetSdkInstalled -DotnetExe $DotnetExe -ExpectedVersion $SdkVersion)) {
        Write-Host "[SETUP] Recreating local .NET SDK layout..."
        if (Test-Path -LiteralPath $DotnetDir) {
            Remove-Item -LiteralPath $DotnetDir -Recurse -Force
        }
        New-Item -ItemType Directory -Force -Path $DotnetDir | Out-Null
    }

    Write-Host "[SETUP] Installing .NET SDK $SdkVersion into $DotnetDir..."
    & $InstallScript -InstallDir $DotnetDir -Version $SdkVersion -Architecture x64 -NoPath

    if (-not (Test-Path -LiteralPath $DotnetExe)) {
        Fail "dotnet.exe was not found after install: $DotnetExe."
    }

    if (-not (Test-DotnetSdkInstalled -DotnetExe $DotnetExe -ExpectedVersion $SdkVersion)) {
        Fail "Local dotnet install did not expose SDK $SdkVersion."
    }

    Write-Host "[VERIFY] Checking local .NET SDK..."
    & $DotnetExe --info
    if ($LASTEXITCODE -ne 0) {
        Fail "Local dotnet verification failed with exit code $LASTEXITCODE."
    }

    Write-Host "[DONE] .NET SDK $SdkVersion is ready at $DotnetDir."
}
catch {
    Fail "Failed to bootstrap .NET SDK. $($_.Exception.Message)"
}
