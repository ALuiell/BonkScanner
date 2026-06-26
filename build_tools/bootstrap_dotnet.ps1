$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Path $MyInvocation.MyCommand.Path -Parent
$repoRoot = Split-Path -Path $scriptDir -Parent
$toolsRoot = Join-Path $repoRoot ".tools"
$dotnetRoot = Join-Path $toolsRoot "dotnet"
$dotnetExe = Join-Path $dotnetRoot "dotnet.exe"
$installScript = Join-Path $toolsRoot "dotnet-install.ps1"
$dotnetVersion = "8.0.411"

New-Item -ItemType Directory -Force -Path $toolsRoot | Out-Null
New-Item -ItemType Directory -Force -Path $dotnetRoot | Out-Null

$needsInstall = $true
if (Test-Path $dotnetExe) {
    try {
        $sdks = & $dotnetExe --list-sdks 2>$null
        if ($LASTEXITCODE -eq 0 -and $sdks) {
            $needsInstall = -not (($sdks -split "`r?`n") | Where-Object { $_ -like "$dotnetVersion*" })
        }
    }
    catch {
        $needsInstall = $true
    }
}

if (-not $needsInstall) {
    Write-Host "[INFO] Project-local .NET SDK $dotnetVersion is already available."
    return
}

if (-not (Test-Path $installScript)) {
    Write-Host "[SETUP] Downloading dotnet-install.ps1..."
    Invoke-WebRequest -Uri "https://dot.net/v1/dotnet-install.ps1" -OutFile $installScript
}

Write-Host "[SETUP] Installing .NET SDK $dotnetVersion into $dotnetRoot..."
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installScript `
    -Version $dotnetVersion `
    -InstallDir $dotnetRoot `
    -Architecture x64 `
    -NoPath

if ($LASTEXITCODE -ne 0 -or -not (Test-Path $dotnetExe)) {
    throw "dotnet-install failed to provision the SDK."
}

Write-Host "[DONE] Installed .NET SDK $dotnetVersion to $dotnetRoot"
