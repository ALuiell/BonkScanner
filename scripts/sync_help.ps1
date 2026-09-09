[CmdletBinding()]
param(
    [switch]$Check
)

$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$documentationHelp = Join-Path $repositoryRoot "docs\help"
$packagedHelp = Join-Path $repositoryRoot "src\media\help"
$helpFiles = @(
    "help_eng.txt",
    "help_ru.txt",
    "help_ukr.txt"
)

if (-not (Test-Path -LiteralPath $documentationHelp -PathType Container)) {
    throw "Documentation help directory was not found: $documentationHelp"
}

if (-not $Check) {
    New-Item -ItemType Directory -Path $packagedHelp -Force | Out-Null

    foreach ($name in $helpFiles) {
        $source = Join-Path $documentationHelp $name
        $destination = Join-Path $packagedHelp $name

        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "Canonical help file was not found: $source"
        }

        Copy-Item -LiteralPath $source -Destination $destination -Force
    }
}

$drift = @()
foreach ($name in $helpFiles) {
    $source = Join-Path $documentationHelp $name
    $destination = Join-Path $packagedHelp $name

    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        $drift += "$name (canonical file missing)"
        continue
    }

    if (-not (Test-Path -LiteralPath $destination -PathType Leaf)) {
        $drift += "$name (packaged mirror missing)"
        continue
    }

    $sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $source).Hash
    $destinationHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash
    if ($sourceHash -ne $destinationHash) {
        $drift += "$name (content differs)"
    }
}

if ($drift.Count -gt 0) {
    throw "In-app help is not synchronized: $($drift -join ', ')"
}

if ($Check) {
    Write-Output "[OK] Canonical documentation help matches src/media/help."
} else {
    Write-Output "[OK] Synchronized canonical documentation help to src/media/help."
}
