$ErrorActionPreference = 'Continue'
$base = 'F:\Python\BonkScanner\agent tasks\validator-stabilization-2026-11-17\acceptance'
$subcat = '{0CCE921F-69AE-11D9-BED3-505054503030}'
$before = & auditpol.exe /get /subcategory:$subcat 2>&1
$before | Out-File -LiteralPath (Join-Path $base 'kernel_object_policy_before_v2.txt') -Encoding utf8
$py = 'C:\Users\heave\AppData\Local\Programs\Python\Python312\python.exe'
& $py 'F:\Python\BonkScanner_validator\scripts\security_audit_acceptance.py' stand --result (Join-Path $base 'security4663_owned_stand_v2.json') *> (Join-Path $base 'security4663_owned_stand_v2.log')
$exitCode = $LASTEXITCODE
$after = & auditpol.exe /get /subcategory:$subcat 2>&1
$after | Out-File -LiteralPath (Join-Path $base 'kernel_object_policy_after_v2.txt') -Encoding utf8
[pscustomobject]@{exitCode=$exitCode; startedBy='Elevated UAC-controlled Windows acceptance'; timestamp=(Get-Date -Format o)} |
    ConvertTo-Json | Out-File -LiteralPath (Join-Path $base 'windows_stand_exit_v2.json') -Encoding utf8
