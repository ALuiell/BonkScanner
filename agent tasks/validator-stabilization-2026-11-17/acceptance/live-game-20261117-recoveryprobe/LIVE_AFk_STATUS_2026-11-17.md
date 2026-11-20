# Live Validator / AFK acceptance ? live status, 2026-11-17

**State:** ACTIVE MEASUREMENT ? NOT COMPLETE. This file records facts, not release acceptance.

## Reproduced and repaired issues

- The first packaged worker crashed during real run_start_known due to a duplicated run_id argument on the new audit_clock_pair diagnostic. Fixed at begin/freeze/rearm; source full suite passed 306 tests and 33 subtests.
- The second packaged worker's 3-second recovery initialization deadline was too tight for cold onefile bootstrap. It now uses a bounded 15-second deadline only when frozen. Failures have distinguishable exit codes; original trust requirements remain intact.
- Independent helper diagnostic launched from python.exe was expected to fail authentication: its parent executable was not the same trusted EXE. The real packaged worker has now successfully armed Security.
- Current scratch onefile executable: F:\Python\BonkScanner\scratch\validator-recoveryprobe-dist\BonkScanner_Validator_LiveFix.exe
- SHA-256: 71F1159D5876B3511EE1EEDAEA71F598E76EBAEEDBD5775F7B61D573A2790614. This is a test package, not an approved release.

## Game and independent evidence

- MegaBonk PID 29100, 1.0.69, GameAssembly SHA-256 4350a7ae25ba7aec35677c213fdceabbb638676bb00ab59131d7d9c37b6e3d9e.
- No new game restart, game-time mutation, character modification, Windows time mutation or global desktop input in this AFK run.
- GameLab run resume returned verified around 12:55:58 local time; the existing game seed 1505568618 was retained, paused changed true to false, game timer started near 1.825 seconds.
- The game was subsequently observed at 192 seconds, stage 0 Forest, paused false, is_playing true and is_game_over false.
- This is a legitimate late attachment to an already paused game. Run boundary is run_start_unknown and Security reports late_attachment; a conservative/inconclusive report is expected even with stable sensors.

## Scanner, worker, Security and server

- GUI PID 1124; elevated worker PID 33752; recovery owner PID 32216; verified onefile process tree with Windows APIs.
- Packaged worker trace: audit_setup_observed status=armed, issues=[]; elapsed from setup requested was 2.61s. ETW observing.
- Run localRunId: ab174c40-3a7f-445f-9f62-0f179dbbf6e7. Real candidate_confirm and run_start emitted after unpause.
- Validator UI: Limited (late attachment), Delivery Connected, Security Collecting / Restoration Pending.
- Actual local Django/PostgreSQL provisional session ID dc676a10-9100-4b9a-a565-7a4505198fad. It had accepted seq=128, available=True, closed=False when independently queried.
- Native resource samples are appended to resources_25m.jsonl every 5 seconds for 1500 configured seconds. A read-only GameLab clock check runs about every 60 seconds.
- Source traces: scanner-1124.jsonl and validator-33752-*.jsonl. GameLab resume receipt: F:/Python/BonkScanner_experiments/game_lab/logs/20261117T105558-run-resume-b20c1b2b.json

## Remaining checks

Do not change game timers, pause, restart or run GameLab adversarial tests until the uninterrupted AFK measurement completes. Afterward verify final Security restoration/SACL, real session finish ACK, ETW/IPC gaps, process cleanup, resource trends and server verdict. This is RUNNING, not 20-30-minute PASS.
