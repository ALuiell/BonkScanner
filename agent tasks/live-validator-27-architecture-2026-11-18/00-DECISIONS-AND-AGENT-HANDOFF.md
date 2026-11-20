# Live Validator 27 — architecture research decisions and agent handoff

## Decision after three discussion rounds

The owner approved three **independent research tasks**, not implementation. Priority: 03 long-run Security 4663 first, 02 pre-run evidence binding second, 01 CandidateRun economics conditional on actual evidence. The objective is the simplest credible, low-cost Live Validator on an approximately USD 10/month VPS. No feature, sensor, server policy, new run detector, or production assessment change is approved by this handoff.

The research agents may read current source, existing tests, maintainer documentation, saved traces and prior reports. They must not change code, tests, configuration, documentation, Git history, running processes, Windows audit policy/SACL, ETW sessions, Scanner, Validator, game, GameLab, worker or server. They must not run tests, replay or new experiments. Each agent may write only its assigned REPORT file in this directory when its separate research task is run. This handoff creates no reports.

| Task | Research decision | Distinct question | Implementation gate |
| --- | --- | --- | --- |
| 01 CandidateRun / Deferred Enrollment | ACCEPT FOR RESEARCH; conditional economics | How much real server work is attributable to short confirmed runs, and can it be reduced without losing accepted adverse evidence? | No actual saved HTTP/DB evidence means NO-GO for immediate implementation; a source model may specify a future minimal measurement. |
| 02 Warm Observer / Pre-Run Evidence Buffer | ACCEPT FOR RESEARCH | Which pre-run events were observed, which are unassigned, and which can be bound to a run without false attribution? | No concrete, temporally assignable saved events means NO-GO for binding or buffering. |
| 03 Incremental Security Audit 4663 | ACCEPT FOR RESEARCH, highest priority | Which of detail cap, scan/time budget and Security log retention limits long runs, and which bounded design fixes the demonstrated problem? | Any missing/duplicate range, unsafe clock mapping, unclear recovery or unbounded cost means NO-GO for a favorable completeness claim. |

Explicitly deferred or rejected for now: a combined CandidateRun+Warm state machine, a new run detector, heavy global menu ETW, Scanner SEARCHING/FOUND or menuMusic as a trusted gate, arbitrary five-minute Security polling, removal of the zero-to-zero uncertainty marker, and softening `result_limit`. The approved D2/assessment-v5 work is separate; pinned historical reports, API negotiation, registry and catalogue versions remain intact. The later integrator, in a different dialogue, will compare the three reports and decide whether any implementation proposal merits owner approval.

Read current scope in `F:/Python/BonkScanner/docs/updates/functional_updates.md` and D2 boundaries in `F:/Python/BonkScanner/docs/validator/validation/assessment_v5_boundary_semantics_D2_2026-11-17.md`. Prior independent work is under `F:/Python/BonkScanner/agent tasks/validator-stabilization-2026-11-17/`, especially 01–07 prompts and their reports. The C14 10/10 verified native restarts in 05_REPORT are a controlled game-action result, not ten accepted Validator sessions or universal correlation. The separate 8/8 source-instance controls in `docs/validator/validation/source_access_correlation_2026-11-16.md` do not establish exact target identity across all Windows conditions. Keep observations, source inferences and untested hypotheses separate.

## Independent ownership and output

- Agent 01 owns the economic/semantic analysis of Validator transport and server enrollment, delivery and lifecycle. It reads Scanner status only as an advisory input and does not decide temporal ETW/4663 binding. Its sole output is `01_REPORT.md`.
- Agent 02 owns pre-run time and identity binding in the existing Validator engine/process-access path. It reads server assessment only to preserve current semantics and does not redesign enrollment or Security journal reading. Its sole output is `02_REPORT.md`.
- Agent 03 owns Security 4663 query, journal, audit recovery and long-run cost analysis. It reads run-boundary and server code only to preserve interfaces and quality gates; it does not change run detection or D2/v5. Its sole output is `03_REPORT.md`.
- Every report must identify inspected revisions, paths and trace event/time references, mark each claim `PROVEN FROM LOGS`, `SOURCE-INFERRED` or `NOT OBSERVED`, state Go/No-Go with decisive evidence, and list later tests as `NOT TESTED` with prerequisites. A read-only source review cannot certify a packaged EXE, a ten-hour Windows run, VPS capacity or client trust.

## Exact copy-ready prompts for the three separate agent dialogues

Изучи задачу по пути F:\Python\BonkScanner\agent tasks\live-validator-27-architecture-2026-11-18\01-candidate-run-economics.md. Работай только с исходниками и уже сохранёнными данными; не запускай тесты или живые процессы. Создай только указанный в задаче 01_REPORT.md и верни путь и ключевой Go/No-Go.

Изучи задачу по пути F:\Python\BonkScanner\agent tasks\live-validator-27-architecture-2026-11-18\02-pre-run-evidence-binding.md. Работай только с исходниками и уже сохранёнными данными; не запускай тесты или живые процессы. Создай только указанный в задаче 02_REPORT.md и верни путь и ключевой Go/No-Go.

Изучи задачу по пути F:\Python\BonkScanner\agent tasks\live-validator-27-architecture-2026-11-18\03-long-run-security-4663.md. Работай только с исходниками и уже сохранёнными данными; не запускай тесты, Windows Security audit или живые процессы. Создай только указанный в задаче 03_REPORT.md и верни путь и ключевой Go/No-Go.
