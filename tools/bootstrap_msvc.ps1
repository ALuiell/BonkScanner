[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$PortableMsvcUrl = "https://gist.github.com/mmozeiko/7f3162ec2988e81e56d5c4e22cde9977/raw/portable-msvc.py"

function Fail($Message) {
    Write-Host "[ERROR] $Message" -ForegroundColor Red
    exit 1
}

function Find-Python {
    param([string]$RepoRoot)

    $LocalPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"

    if (Test-Path -LiteralPath $LocalPython) {
        return @{ Exe = $LocalPython; Args = @() }
    }

    $PyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($null -ne $PyLauncher) {
        return @{ Exe = $PyLauncher.Source; Args = @("-3") }
    }

    $Python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -ne $Python) {
        return @{ Exe = $Python.Source; Args = @() }
    }

    Fail "Python 3 was not found. Install Python or run start.bat to create the project .venv, then retry."
}

try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
    $ToolsDir = Join-Path $RepoRoot ".tools"
    $DownloadsDir = Join-Path $ToolsDir "downloads"
    $PortableScript = Join-Path $DownloadsDir "portable-msvc.py"
    $SetupBat = Join-Path $ToolsDir "msvc\setup_x64.bat"

    New-Item -ItemType Directory -Force -Path $ToolsDir, $DownloadsDir | Out-Null

    if (-not (Test-Path -LiteralPath $PortableScript)) {
        Write-Host "[SETUP] Downloading portable-msvc.py..."
        Invoke-WebRequest -Uri $PortableMsvcUrl -OutFile $PortableScript
    }

    if (-not (Test-Path -LiteralPath $SetupBat)) {
        $Python = Find-Python -RepoRoot $RepoRoot
        $PythonExe = $Python["Exe"]
        $PythonArgs = $Python["Args"]

        Write-Host "[SETUP] Installing portable MSVC/Windows SDK into $ToolsDir\msvc..."
        Push-Location $ToolsDir
        try {
            & $PythonExe @PythonArgs $PortableScript --accept-license --vs 2022 --target x64 --host x64
            if ($LASTEXITCODE -ne 0) {
                Fail "portable-msvc.py failed with exit code $LASTEXITCODE."
            }
        }
        finally {
            Pop-Location
        }
    }

    if (-not (Test-Path -LiteralPath $SetupBat)) {
        Fail "setup_x64.bat was not found after bootstrap: $SetupBat."
    }

    Write-Host "[VERIFY] Checking portable MSVC linker and SDK environment..."
    & cmd.exe /d /s /c "call ""$SetupBat"" && where.exe link.exe && where.exe cl.exe && if not defined INCLUDE exit /b 11 && if not defined LIB exit /b 12"
    switch ($LASTEXITCODE) {
        0 { }
        11 { Fail "INCLUDE was not set after calling $SetupBat. Portable MSVC did not initialize correctly. Fallback: install Visual Studio Build Tools with the Desktop development with C++ workload." }
        12 { Fail "LIB was not set after calling $SetupBat. Portable MSVC did not initialize correctly. Fallback: install Visual Studio Build Tools with the Desktop development with C++ workload." }
        default { Fail "cl.exe/link.exe were not discoverable after calling $SetupBat. Portable MSVC did not initialize correctly. Fallback: install Visual Studio Build Tools with the Desktop development with C++ workload." }
    }

    Write-Host "[DONE] Portable MSVC toolchain is ready at $ToolsDir\msvc."
}
catch {
    Fail "Failed to bootstrap portable MSVC. $($_.Exception.Message) Portable MSVC did not come up, so NativeAOT cannot build without a linker environment."
}
