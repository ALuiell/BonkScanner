# Live IPC correction / acceptance handoff

## Current live-acceptance update: IPC deadlines (2026-11-17)

**Overall remains PARTIAL. Source/owned-process IPC regressions PASS; long-duration real-game acceptance is RUNNING, not PASS.** This update supersedes any earlier suggestion that source remediation already closed every live reliability issue.

Real-game runs exposed a worker IPC receive timeout and long Scanner event handling. The current implementation separates **15-second idle-before-first-byte** from **2-second remaining-frame delivery**, preserving terminal handling of partial frames, identity/sequence validation and bounded Stop/parent-death cleanup. A real 6,016-ms IPC wait was survived; the matching parent payload handler took 6,005.32 ms. The deeper cause inside that handler remains unproven and must be profiled, not hidden by further timeout increases.

Full Validator: **313 passed + 36 subtests**. Scanner integration/GUI/recording selection: **63 passed**. Native Windows regression survives a 5.1-second idle then delivers shutdown tail; partial header/body prefixes still terminate within the short frame budget. The exact EXE is `scratch/validator-ipcfix-dist/BonkScanner_Validator_LiveFix.exe`, SHA-256 `b546431cbad04f7983654a48e7a7d8d87b96c2d5e0554ce28ac06961bd914e66` (58,232,001 bytes).

The first patched live segment finalized as `context_lost`, with server finish ACK seq 97 and Security restoration reported Verified; it is partial evidence, not a clean completed run. After a supported Resume-only operation, the **actual guarded 25-minute capture began at 13:58:55 Europe/Kyiv**. The current run is `01e285cb-9fcf-42d4-b1c9-4223cb4529dd`, server session `4ab63c10-d2e0-4a01-9a95-c25d19ee7027`. At 14:01 it had accepted batch seq 124 and was still open. Same worker PID 31336 / creation FILETIME 134393899851830462. Neither game restart nor timer/stat modification was performed in this continuation.

Evidence: `acceptance/live-game-20261117-ipcfix/guarded_capture/`, `latest_status.json`, server checkpoints and per-process JSONL. The failed first resource-monitor invocation did not produce a capture; do not credit it. The guarded monitor now stops its OWN measurement on worker loss/identity change and rejects paused/inactive preflight. No delayed test results may be declared successful merely because a timer elapsed. A read-only results check is scheduled for approximately 14:25; no game/Scanner restart is authorized by it.

Canonical maintainer note: `docs/validator/validation/ipc_idle_frame_deadlines_2026-11-17.md` in the separate Docs repository. All changes are uncommitted. Do not confuse current live evidence with the older first/second-cycle matrices below.

---

