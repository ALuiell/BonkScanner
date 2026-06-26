$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Path $MyInvocation.MyCommand.Path -Parent
$repoRoot = Split-Path -Path $scriptDir -Parent
$toolsRoot = Join-Path $repoRoot ".tools"
$msvcRoot = Join-Path $toolsRoot "msvc"
$vsAcquireScript = Join-Path $toolsRoot "portable-msvc.py"
$setupBat = Join-Path $msvcRoot "setup_x64.bat"
$portableMsvcRepo = "https://raw.githubusercontent.com/mmozeiko/build-tools/main/windows/portable-msvc.py"

New-Item -ItemType Directory -Force -Path $toolsRoot | Out-Null

if (Test-Path $setupBat) {
    Write-Host "[INFO] Portable MSVC setup already exists at $setupBat"
    return
}

if (-not (Test-Path $vsAcquireScript)) {
    Write-Host "[SETUP] Downloading portable MSVC bootstrap helper..."
    Invoke-WebRequest -Uri $portableMsvcRepo -OutFile $vsAcquireScript
}

$pythonCandidates = @(
    (Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
    (Get-Command py.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue)
) | Where-Object { $_ }

if (-not $pythonCandidates) {
    throw "Python was not found in PATH. Install Python 3 and rerun bootstrap_msvc.ps1."
}

$pythonExe = $pythonCandidates[0]
Write-Host "[SETUP] Bootstrapping portable MSVC and Windows SDK into $msvcRoot..."

if ((Split-Path $pythonExe -Leaf).ToLowerInvariant() -eq "py.exe") {
    & $pythonExe -3 $vsAcquireScript --output $msvcRoot
}
else {
    & $pythonExe $vsAcquireScript --output $msvcRoot
}

if ($LASTEXITCODE -ne 0 -or -not (Test-Path $setupBat)) {
    throw "portable-msvc bootstrap did not produce setup_x64.bat."
}

Write-Host "[DONE] Portable MSVC initialized under $msvcRoot"
