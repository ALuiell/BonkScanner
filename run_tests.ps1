param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$TestArgs
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Project virtualenv was not found at .venv\Scripts\python.exe. Run start.bat first to create .venv."
}

if ($TestArgs.Count -eq 0) {
    $TestArgs = @("discover", "-s", "tests")
}

& $Python -m unittest @TestArgs
