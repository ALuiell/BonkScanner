$ErrorActionPreference = 'Stop'
$dir = 'F:\Python\BonkScanner\agent tasks\validator-stabilization-2026-11-17\acceptance'
$python = 'C:\Users\heave\AppData\Local\Programs\Python\Python312\python.exe'
$fixture = 'F:\Python\BonkScanner_validator\scripts\security_audit_acceptance.py'
& $python $fixture dense --result (Join-Path $dir 'security4663_dense_stand.json') *> (Join-Path $dir 'security4663_dense_stand.log')
$exit = $LASTEXITCODE
[pscustomobject]@{ExitCode=$exit; Timestamp=(Get-Date -Format o)} |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $dir 'security4663_dense_exit.json') -Encoding UTF8
exit $exit
