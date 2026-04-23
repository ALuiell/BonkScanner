[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$DotnetInstallUrl = "https://dot.net/v1/dotnet-install.ps1"

function Fail($Message) {
    Write-Host "[ERROR] $Message" -ForegroundColor Red
    exit 1
}

try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
    $ToolsDir = Join-Path $RepoRoot ".tools"
    $DownloadsDir = Join-Path $ToolsDir "downloads"
    $DotnetDir = Join-Path $ToolsDir "dotnet"
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

    New-Item -ItemType Directory -Force -Path $DownloadsDir, $DotnetDir | Out-Null

    if (-not (Test-Path -LiteralPath $InstallScript)) {
        Write-Host "[SETUP] Downloading dotnet-install.ps1..."
        Invoke-WebRequest -Uri $DotnetInstallUrl -OutFile $InstallScript
    }

    Write-Host "[SETUP] Installing .NET SDK $SdkVersion into $DotnetDir..."
    & $InstallScript -InstallDir $DotnetDir -Version $SdkVersion -Architecture x64 -NoPath

    $DotnetExe = Join-Path $DotnetDir "dotnet.exe"
    if (-not (Test-Path -LiteralPath $DotnetExe)) {
        Fail "dotnet.exe was not found after install: $DotnetExe."
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
