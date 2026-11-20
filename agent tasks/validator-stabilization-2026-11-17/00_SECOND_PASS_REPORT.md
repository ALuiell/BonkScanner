# 00 SECOND PASS — Live Validator stabilization

**Date:** 2026-11-17 (Europe/Kyiv)  
**Baseline repositories:** Scanner c955c68; Validator 21c9432; Server 904c394; Experiments 65f41a5; Docs 7ec676f. All integration changes remain **uncommitted**.  
**Decision:** **CONFIRMED SOURCE DEFECT REMEDIATION — COMPLETE FOR THE TESTED SCOPE. RELEASE ACCEPTANCE — PARTIAL / NOT RELEASE-READY.**

This second pass extends, and supersedes counts/statuses where they differ from, `00_FINAL_REPORT.md`'s original first-pass narrative. All native stand data and local HTTP sessions are independent of the original saved game captures. The originals have not been edited.

## 1. Re-examination and corrections

### R2-01 — Physical sensor timestamp versus delayed diagnostic I/O

**Finding:** The first clock fix still captured the UTC/QPC pair inside `_sample_audit`, after opt-in `sensor_poll_end` trace writes and diagnostic probe work. Synchronous disk I/O could delay processing after the physical game read, causing Security span timestamps to over-credit time the sensor had not actually observed. This mattered given the earlier >500-ms trace gap analysis.

**Fix:** `ObservationEngine.poll` now samples its paired UTC/QPC immediately after the fresh physical sample and before optional trace/probe calls, and threads that immutable pair to the same run's `_sample_audit`. If the poll actually replaces the run identity, the old run's pair cannot be reused for the new run. Synthetic regression deliberately delays trace emission and asserts real read → paired clock → trace → audit ordering.

### R2-02 — Clock discontinuity *during* deferred Security grace/query

**Finding:** A correct frozen terminal timestamp does not independently prove that Windows time stayed continuous during the Security grace, query and recovery phase. In particular, a backward time step after run end could put later 4663 events inside an old UTC timestamp window.

**Fix:** The finalizer checks fresh **coherent pairs**, not old wall clock against later unpaired QPC, before and after the bounded Security finish. Queue residence alone does not trigger drift. A detected step or uncertain clock bracket after collection now sets a local `timeDomainUntrusted` diagnostic, retains all exercised-right aggregate counts but demotes formerly exact 4663 rows and blocks foreign ETW/4663 correlation. Server v4 sees the existing critical `clock_changed` or `run_boundary_unknown` reasons and cannot issue a favorable report. Fixture tests cover a step during grace, post-query wide bracket, >2-second stable queue delay and positive/negative 2318-ms steps. **The machine clock was not altered.**

### R2-03 — UAC refusal / Stopping lifecycle

**Finding:** The observer could publish `disabled` as soon as `worker.start()` returned False, even though its finally cleanup and sender drain were still alive. A stale previous worker reference could survive into another controller generation.

**Fix:** Refused/UAC-cancelled startup now enters `stopping` and sets the stop event; only completed local owners permit the final `disabled` snapshot. `enable` clears the previous generation's worker reference and snapshots use one consistent `busy` value. Deterministic tests cover pending owner/Stop and a stale worker during immediate re-enable.

### R2-04 — 4663 repeated issues and evidence cap

**Finding:** Hundreds or thousands of identical qualifying events could append duplicate local issue strings before end-of-query deduplication. This consumed avoidable memory and time.

**Fix:** Issues are deduplicated during collection. Existing strict 2048-event/0.8-second query cap, 24-row-per-group detail cap, 8 earliest + 8 prioritized + 8 latest stratification and read/write aggregate preservation remain unchanged. A 1000-record fixture confirms exact totals, 976 omitted details and at most two distinct issue reasons.

### R2-05 — GameLab test-control safety (user-owned work preserved)

**Finding:** Unattended native `run restart --count` batches had no upper limit. Very large counts could loop without a bounded operator intent.

**Fix:** GameLab now accepts **1..100** attempts per native restart series, rejecting invalid values both at CLI parse and inside `RunControl.run`, before process inspection/native calls. Added `game_lab/test_restart_series_limit.py`; 0, -1, 101, huge integer, malformed integer and valid boundaries are covered. This changes only relevant lines in the user's existing modified `game_lab/game.py` and `game_lab/run_control.py`, with no reset/clean or loss of receipts.

## 2. Fresh native Windows evidence

### 2.1 Dense Security 4663

Controlled **elevated Windows UAC** stand, own target and own actor; no MegaBonk or global desktop input:

- `acceptance/security4663_dense_stand.json` and `security4663_dense_exit.json`: **PASS**, 40 distinct VM_READ handle exercises, exactly 40 retrieved/rendered/eligible 4663 records, all read bits counted, 24 retained details and 16 explicitly omitted details.
- Iterator exit **exhausted**, duplicate/parse rejects **0**; `result_limit` and `handle_lifetime_unverified` remained explicitly recorded rather than being confused with clean absence.
- Restoration **verified** and independently read policy/SACL returned to the exact initial snapshot; global Kernel Object policy was already Success at the start. Therefore OFF→ON→OFF policy switching was **not** tested.
- This establishes owned-fixture collection and the retention invariant, not 100% journal collection under arbitrary Windows settings or foreign lifetime identity.

### 2.2 Real elevated worker lifecycle, ordinary controller

`acceptance/controller_windows_uac_second_pass.json`: **PASS**, two separate ordinary Python source-controller → real Windows RunAs/UAC worker cycles with no game. Both reached `waiting_game`, then `stopping` while cleanup was live, and `disabled` with `busy=false` after approximately **0.25 / 0.20 seconds**, without errors. This is stronger than a source-only Qt fixture, but it is **not** a packaged EXE or actual game/GUI C05 test.

### 2.3 ETW and independent SACL evidence from first pass

Retained results: `acceptance/security4663_owned_stand_v2.json` (owned stop/exit/crash, SACL before/active/after), `acceptance/etw_m2_summary.json` (owned process/thread opens and DLL load/unload, 0 native losses, clean ETW stop). Windows build 26200. No unowned system policy edit or physical clock mutation was performed.

## 3. Fresh local PostgreSQL, ACK and report persistence

`acceptance/controller_transport_postgres_second_pass.json` and `controller_transport_postgres_second_pass.py`: **PASS**, two synthetic old/new overlapping `localRunId` sessions handed to the actual source `ValidatorController` and `TransportManager`, then accepted over HTTP by local development Django/PostgreSQL.

Both received distinct durable `sessionId`, `finishAcknowledged=true`, `status=finished`, `diagnosticSummariesDropped=false`, and public API HTTP 200 with server `sessionState=completed` and `assessment=inconclusive`. Independent operator-side database export confirmed both persisted `finishEvidence.security4663.restoration=preserved_external_change`, `issues=[policy_changed]`, `queryCompleted=false`. No favorable verdict or dropped diagnostic appeared. This is a **synthetic worker-event** check; the real IPC/elevated worker/game and these server sessions were not part of one end-to-end game run.

First-pass independent PostgreSQL restart fixture also verified bit-for-bit identical finish ACK/public report after Django and DB restart. Local development credentials remained private; no production host contacted.

## 4. Full second-pass regression results

| Layer | Scope | Outcome |
|---|---|---|
| Validator | `py -3.12 -m pytest -q tests`, current uncommitted source | **PASS — 304 pytest cases + 33 subtests** |
| Scanner | combined selected GUI, integration, recordings, run-control, timeline suites | **PASS — 546 pytest cases + 24 subtests** |
| Server | `docker compose exec -T web python manage.py test --keepdb --noinput --verbosity 1` | **PASS — 119 passed, 1 skipped** (120 collected) |
| GameLab | `py -3.12 lab.py test` | **PASS — 175 + 36 unittest cases** |
| Run predicates | Second read-only replay with current source against saved post-fix per-scenario case references | **PASS — 59,519 observations, 69 confirmations across 50 scenarios, 0 mismatches** |
| Win32 UAC worker smoke | two ordinary-process source controller cycles | **PASS**, no stale Stopping |
| Win32 dense 4663 | 40 owned operations / 40 qualifying records | **PASS**, exact 24+16 detail accounting and independent restore |
| Local controller→transport→Django/PostgreSQL | overlapping old/new synthetic run IDs | **PASS**, both persisted, ACKed, strict inconclusive grading |

The previously quoted first-pass source counts (Validator 298, Scanner 483+63, GameLab 173+36) are superseded by these **second-pass** runs. There are **1180 passed test cases and 57 additional subtests**, with 1 Django test skipped. Counting a 36-test GameLab suite as subtests or counting the skipped Django case as passed would be incorrect.

Source `compileall` and Git whitespace checks succeeded for Validator and Server. GameLab's pre-existing user-edited Windows-style line endings require the Git configuration-aware `git -c core.whitespace=cr-at-eol diff --check`; no actual trailing-space errors were seen under that setting. No source files were reset or normalized as part of the audit.

## 5. Final acceptance matrix after second pass

| Area | Source remediation | Newly proved by real/native system | Remaining boundary |
|---|---|---|---|
| 01 clock integrity, frozen end, span gaps, post-query step | **PASS** | Real Windows UTC-step historical event remains revision-pinned | No intentional machine clock step or long native game session on modified build |
| 02 4663 counts, 24 details, query EOF/bounds | **PASS** | **PASS**, 40 owned live events, exact 24 retained / 16 omitted | No adversarial journal churn, native multiple same-image games or 2048-event pressure stand |
| 03 SACL recovery/contract | **PASS** | **PASS** for owned SACL before/active/after and worker crash recovery; policy state unchanged | Policy OFF→ON→OFF, independent forced helper death/external edit, packaged exact-version verification |
| 04 lifecycle, Stopping, old run finalization | **PASS (source fixtures)** | **PASS** for 2 normal UAC source-worker Enable/Stop/Off cycles | Real GUI C05 stress, slow peer, Stop during drain, cancel UAC at secure desktop |
| 05 detector, P07/P08, recording association | **PASS (source/replay)** | Prior real game original-revision evidence only | Postpatch game 0→1→2, true restart/same-seed guard, independent Boss Room marker |
| 06 ETW/Census/Image and resources | **PASS (existing source tests)** | **PASS** on owned ETW experiment (first pass) | 20–30 minutes of real game + native worker, per-thread CPU, freshness/cleanup after Stop |
| 07 Django, idempotent ACK, private/public, v1–v4 version pins | **PASS** | **PASS** real local development PostgreSQL and controller-generated synthetic traffic | One real packaged Scanner→worker→IPC→HTTP→DB→browser run; external deployment |
| GameLab command safety | **PASS** | New CLI/direct method tests, 1..100 cap | Actual GameLab restart receipts during game acceptance |
| Process catalogue completeness | Mechanism and triage **PASS** | Current-machine synthetic/private mechanism only | Multi-OS benign process evidence, review and manual curation |

## 6. Unresolved issues requiring a later acceptance, explicit policy choice or user involvement

**No currently reproduced failing source regression remains in the tested code scope.** The following are **not** equivalent to completed acceptance:

1. **New matching packaged EXE and game:** Use the newly built isolated Validator package, pin its final registered build identity and game version, launch its GUI with normal UAC, then verify known/late start, real restarts, stage 0→1→2, natural end, Boss Room ground truth and recording/session linking. The old distributed EXE and saved captures cannot prove this new build.
2. **Real-game stress and resource profile:** 5–10 genuine C05 overlaps, Stop during finalization, offline/slow transport, repeated GUI cycles, independent ETW ownership/IPC tail and 20–30-minute Scanner-versus-worker CPU, handles/threads/memory plus post-Stop state. FPS causality was not established by earlier nondeterministic runs.
3. **Windows destructive/failure conditions:** Controlled Kernel Object policy OFF→ON→OFF and forced helper death/external policy/SACL changes require a separate owned Windows stand / VM and safe independent readback. On the present machine Kernel Object auditing already starts at Success; no unrelated administrative policy should be reset to manufacture a test.
4. **Security v4 presentation-policy choice:** A completely exhausted journal with more than 24 retained details still reports `result_limit` and blocks favorable grading under pinned v4. This is deliberate conservative policy, not incorrect read counts. Do **not** silently loosen the historical v4 decision. Any new rule that distinguishes harmless own-reader use or detail-only omission from actual query loss requires an explicitly versioned **v5** assessment, compatibility/retained-report tests and a decision about what remains inconclusive.
5. **Actual hosting and catalogue:** Local Docker is not production HTTPS/TLS, public deployment, external testers, server backup, release registration or a complete process catalogue. Catalogue samples require independent corroboration. A client crash before durable ACK is still subject to intentionally bounded RAM-only delivery; adding encrypted local crash-recovery spool is a separate product/security/privacy decision.
6. **Independent Boss/same-pointer ground truth:** Current historical traces cannot prove the exact Boss Room boundary or a same-pointer/same-seed genuine restart. Changing detector heuristics without a discriminating native event sequence risks resurrecting false splits.

**Release gate: NOT SATISFIED. Remediation of confirmed source defects and available controlled Windows/local server checks: COMPLETE for the stated scope.** This is a truthful split between implementation and real-game acceptance, not a claim that only process-catalogue content remains unfinished.

## 7. Safety and ownership

No Git commit, push, reset, clean, production deployment, profile migration, recorded capture rewrite, game memory mutation or physical Windows time change was performed. The existing GameLab worktree remains user-owned and dirty; only the two targeted count-limit changes and a new test were added to it. Docs user edits remain untouched. The separate Scanner `docs/` nested Git repository was not switched or overwritten. Local Windows UAC went through the standard consent mechanism.

Private evidence is under `F:/Python/BonkScanner/agent tasks/validator-stabilization-2026-11-17/acceptance`; do not publish `private_report_synthetic.json`, private triage or raw native identifiers without review.



## 8. Isolated packaged EXE build and safe bootstrap smoke

**PASS for packaging/bootstrap only; still NOT an in-game UAC acceptance.**
After second-pass source fixes, the existing Scanner PyInstaller 6.22.3 toolchain was used to build a distinct Windows 11 x64 onefile binary, with the currently installed editable Validator source, into:

`F:/Python/BonkScanner/scratch/validator-second-pass-dist/BonkScanner_Validator_SecondPass.exe`

The existing `dist/BonkScanner.exe` and user settings were **not** overwritten. The output was 58,228,938 bytes with SHA-256 `0a2ac96ea544db182d5d2392572f3bd658d9c5a9f5a62599644f0da4dc6aae3c`. The archive was inspected recursively and contains the bundled Validator modules `audit_recovery`, `controller`, `engine`, `security_audit`, `worker` and `protocol`. A non-elevated worker invocation with syntactically valid peer arguments exited with expected **3** (worker requires elevation), and an invalid-parent recovery bootstrap exited with expected **4** (identity validation failure). Neither entered normal GUI startup nor modified system audit settings.

Machine-readable evidence, including individual source file SHA-256 hashes tied to the uncommitted working tree, is `acceptance/packaged_onefile_second_pass.json` plus the independently executed `acceptance/packaged_bootstrap_probe.json` (the latter records the actual two process exit codes). The initial isolated build attempt failed only because moving the autogenerated spec changed relative media search paths; the successful build used absolute media/hook/script paths. This is test-setup recovery, not a failing Validator implementation.

**Still pending:** run the isolated executable through its *normal* GUI with an actual supported MegaBonk game, trigger the worker through normal packaged RunAs/UAC, verify repeated Stop and recovery, pin/approve the final build's release identity, and establish one same-session finish ACK at the server. The isolated smoke is not a signed/release-approved binary and cannot be described as native game acceptance.
