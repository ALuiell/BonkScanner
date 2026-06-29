param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$TestArgs
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$env:PYTHONPATH = "{0};{1}" -f $RepoRoot, (Join-Path $RepoRoot "src")

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Project virtualenv was not found at .venv\Scripts\python.exe. Run start.bat first to create .venv."
}

if ($TestArgs.Count -eq 0) {
    $TestArgs = @("discover", "-s", (Join-Path $RepoRoot "src\tests"))
}

$PreviousLocation = Get-Location
try {
    Set-Location -LiteralPath $RepoRoot
    & $Python -m unittest @TestArgs
    exit $LASTEXITCODE
}
finally {
    Set-Location -LiteralPath $PreviousLocation
}