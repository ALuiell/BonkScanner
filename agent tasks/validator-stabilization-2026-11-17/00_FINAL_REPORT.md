# 00 FINAL REPORT — Live Validator stabilization integration

## Current live-acceptance update: IPC deadlines (2026-11-17)

**Overall remains PARTIAL. Source/owned-process IPC regressions PASS; long-duration real-game acceptance is RUNNING, not PASS.** This update supersedes any earlier suggestion that source remediation already closed every live reliability issue.

Real-game runs exposed a worker IPC receive timeout and long Scanner event handling. The current implementation separates **15-second idle-before-first-byte** from **2-second remaining-frame delivery**, preserving terminal handling of partial frames, identity/sequence validation and bounded Stop/parent-death cleanup. A real 6,016-ms IPC wait was survived; the matching parent payload handler took 6,005.32 ms. The deeper cause inside that handler remains unproven and must be profiled, not hidden by further timeout increases.

Full Validator: **313 passed + 36 subtests**. Scanner integration/GUI/recording selection: **63 passed**. Native Windows regression survives a 5.1-second idle then delivers shutdown tail; partial header/body prefixes still terminate within the short frame budget. The exact EXE is `scratch/validator-ipcfix-dist/BonkScanner_Validator_LiveFix.exe`, SHA-256 `b546431cbad04f7983654a48e7a7d8d87b96c2d5e0554ce28ac06961bd914e66` (58,232,001 bytes).

The first patched live segment finalized as `context_lost`, with server finish ACK seq 97 and Security restoration reported Verified; it is partial evidence, not a clean completed run. After a supported Resume-only operation, the **actual guarded 25-minute capture began at 13:58:55 Europe/Kyiv**. The current run is `01e285cb-9fcf-42d4-b1c9-4223cb4529dd`, server session `4ab63c10-d2e0-4a01-9a95-c25d19ee7027`. At 14:01 it had accepted batch seq 124 and was still open. Same worker PID 31336 / creation FILETIME 134393899851830462. Neither game restart nor timer/stat modification was performed in this continuation.

Evidence: `acceptance/live-game-20261117-ipcfix/guarded_capture/`, `latest_status.json`, server checkpoints and per-process JSONL. The failed first resource-monitor invocation did not produce a capture; do not credit it. The guarded monitor now stops its OWN measurement on worker loss/identity change and rejects paused/inactive preflight. No delayed test results may be declared successful merely because a timer elapsed. A read-only results check is scheduled for approximately 14:25; no game/Scanner restart is authorized by it.

Canonical maintainer note: `docs/validator/validation/ipc_idle_frame_deadlines_2026-11-17.md` in the separate Docs repository. All changes are uncommitted. Do not confuse current live evidence with the older first/second-cycle matrices below.

---


**Date:** 2026-11-17 (Europe/Kyiv)  
**Integrator:** Aluiel_MCP, direct MCP execution on the registered Windows workspace  
**Disposition:** **PARTIAL — SOURCE AND CONTROLLED-STAND STABILIZATION VERIFIED; NOT RELEASE-READY**  
**Scope authority:** 00-integrator.md and independent reports 01_REPORT.md through 07_REPORT.md in this directory.

## Second-cycle authoritative update (2026-11-17)

**Implementation remediation: COMPLETE for currently confirmed, reproducible defects. Release acceptance: PARTIAL / NOT READY.** This document originally recorded the first integration cycle. The full independently executed follow-up, new evidence and latest acceptance matrix are in **[00_SECOND_PASS_REPORT.md](00_SECOND_PASS_REPORT.md)** and supersede older counts, worktree descriptions and test-limits below.

The second-cycle changes additionally fixed: Security clock sampling after potentially blocking trace I/O; possible UTC/QPC discontinuity during deferred Security grace/query; UAC refusal incorrectly displaying Off while owners were active; stale prior worker generation; repeated per-event Security issue strings; and unsafe unbounded GameLab native restart batches (now capped at 100 with pre-execution checks). The source-level changes preserve conservative attribution and version-pinned v4 server assessment.

**Latest completed suites:** Validator **304 passed + 33 subtests**; Scanner **546 passed + 24 subtests**; local Django/PostgreSQL **119 passed + 1 skipped** (120 collected); GameLab **211 passed**. Aggregate: **1,180 passed test cases + 57 subtests, 1 skipped**. Native owned Windows Security 4663: **40 actual events / 24 details / 16 omitted, exhausted query, recovery verified**. Ordinary Controller to UAC elevated worker: **two successful Enable / Stopping / disabled cycles**. Two overlapping synthetic controller runs both reached **real local Django/PostgreSQL**, with distinct persistent session IDs, acknowledged finish, no diagnostics dropped and preserved critical restoration conflicts. New saved predicate replay matched **69 confirmations in 59,519 observation records**, zero per-scenario mismatches.

**Still unaccepted:** the newly built isolated packaged Scanner/Validator operating through its ordinary GUI and UAC worker in a running MegaBonk game; repeated real-game C05/Stop and true Boss Room/same-identity restart ground truth; 20-30-minute resource/cleanup measurement; independent global policy Off/On/Off (initial host state was already Success); production HTTPS/external users; and manual catalogue curation. Any data-only row limit should continue to block favorable *pinned v4* results until a **separately versioned** policy is approved. No raw client report is remote attestation.

**Isolated packaging update:** The current working-tree Scanner/Validator was successfully built as an isolated 58,228,938-byte Windows onefile executable, with the required bundled Validator modules. Unelevated worker dispatch returned expected code 3 and bad-parent recovery dispatch returned expected code 4. The existing distribution EXE was not overwritten; see [00_SECOND_PASS_REPORT.md](00_SECOND_PASS_REPORT.md), section 8, and acceptance/packaged_onefile_second_pass.json. This is a packaging/security bootstrap PASS, not a real-game or packaged GUI/UAC acceptance.

**Historical scope note:** The earlier table below says GameLab source was unchanged because that was true at the *first* cycle. The second cycle safely amended the two already user-modified GameLab files to bound `--count` and added two offline tests; all other pre-existing user edits and receipts were preserved. All HEADs are unchanged and integration patches remain uncommitted. The first-pass validation matrices below remain as-of records, not the current final status; rely on [00_SECOND_PASS_REPORT.md](00_SECOND_PASS_REPORT.md) for the consolidated current matrix.

---

## Executive decision

The integrator reconciled all seven investigation reports with code, saved traces, and controlled tests, then implemented narrow reliability fixes in the Validator and server. All completed final source test suites passed. A local Django/PostgreSQL durability replay passed, and owned-process Windows/UAC Security and ETW acceptance produced new independent evidence. The old real game run remains useful *historical* proof of its original revisions, but there was **no new live MegaBonk, packaged Scanner/Validator, GUI end-to-end, or 20–30-minute resource acceptance** of the changed source during this integration.

Accordingly, the stated product ambition of leaving *only* process-catalogue population incomplete is **not yet verified**. There are no known failing final source suites and the principal proven P0 code defects have targeted regression coverage. However, outstanding native acceptance criteria cannot be represented as PASS. Do **not** deploy or declare release readiness based on this report.

The process catalogue is an interpretation/triage layer. Requested rights (successful ETW direct-open requests) and sampled granted rights (Census) are **capabilities**, not proof of memory manipulation. Security 4663 is observed exercise of an auditable right under specific coverage and attribution limits; it is not, by itself, proof of cheating. All client-side evidence remains self-reported by a user-controlled machine.

## 1. Repository and evidence baseline

| Repository | Registered project | Initial / final HEAD | Current integration state |
|---|---|---|---|
| Scanner | bonkscanner | c955c68, live-validator | Existing source unchanged; untracked task prompts, original reports, and new acceptance evidence |
| Validator | bonkscanner_validator | 21c9432, main | Five modified tracked source/tool files and one new test file, **uncommitted** |
| Validator server | bonkscanner_validator_server | 904c394, main | Five modified tracked files, **uncommitted** |
| Experiments / GameLab | bonkscanner_experiments | 65f41a5, main | User-owned dirty GameLab files/receipts preserved; no source edits |
| Nested Docs | bonkscanner_docs | 7ec676f, main | User-owned development/game_lab.md edit preserved; no source edits |

HEAD values are source baselines, not post-patch commit hashes: these changes are intentionally uncommitted. Existing unpublished commits were preserved. No branch switch, reset, clean, commit, push, production deployment, or modification of original captures took place. CodeGraph was attempted but lacked the needed index, so code was inspected with MCP Windows PowerShell.

Original evidence retained, not rewritten:

- Primary natural gameplay: F:/Python/BonkScanner/.local/validator-start-trace/retest-kit/captures/session-20261117-093004-1afdfe/FINAL_REAL_STAGE_REVIEW_2026-11-17.md and adjacent JSONL/metadata. This used Scanner c955c68, Validator 21c9432, MegaBonk 1.0.69, GameAssembly SHA-256 4350a7ae25ba7aec35677c213fdceabbb638676bb00ab59131d7d9c37b6e3d9e.
- Previous direct QA: captures/session-20261117-080026-ba7a2e/QA_DIRECT_GAME_LAB_INTERIM_2026-11-17.md, including C01/C02/C03/C05/C14/C15; earlier Scanner c42346b.
- Heavy waves/performance: captures/session-20261117-091510-f305cc and captures/session-20261117-084736-6cb590/wave-perf-heavy-20261117-090438.
- Existing run-boundary documents: Docs validator/run_boundary_assessment_upgrade_2026-11-17.md and validation/run_boundary_assessment_P07_P08_fix_2026-11-17.md. P07/P08 were already implemented before this integration.

The natural 09:30 run had one local run identity across genuine stages 0→1→2, then one confirmed natural end. This is positive *old-revision* evidence, not new post-patch native proof. The exact independent Boss Room entry marker was unavailable. The Security result was partial, with late_attachment, clock_changed, run_boundary_unknown, result_limit. Windows System Event 1, record 198240, and its Time-Service records independently support an actual +2318 ms Windows UTC step near 09:33; it is not evidence of a map transition or cheating.

## 2. Diagnoses and implemented corrections

### 01 — Security clocks, frozen finalization, trusted spans

**Confirmed defects:** A frozen finish UTC value was compared with a newly sampled QPC only after asynchronous finalizer queue/drain, which can invent clock_changed from scheduling delay. A still-open audit span could extend across a fresh sensor gap over 500 ms. Separately, the historical trace had a **real** UTC correction and therefore could legitimately be marked clock_changed.

**Fix:** Validator engine.py now brackets each UTC observation with QPC-before/QPC-after, retries wide brackets and uses offset confidence ranges (50 ms disagreement tolerance, 5 ms bracket-quality limit). Run begin, fresh audit samples, re-arm and terminal freeze use coherent anchors. The original immutable terminal pair is passed to the deferred finalizer; no later QPC reading is substituted. A >500 ms fresh-to-fresh gap closes the old Security span and reopens a new one without inventing observation during the hole. Actual clock discontinuities still invalidate unsafe attribution. A single pre-step QPC→UTC conversion is not reused to correlate foreign Security rows across a detected step. Bounded local-only diagnostics identify first issue origins and clock-pair provenance.

**Tests:** New fixtures cover 499/501 ms, large positive and negative clock steps, normal jitter, wide sampling brackets, delayed finish, invalidated spans and 32-span capacity. They do not change the system clock. Remaining untested: sustained gradual clock slew and all native timing interleavings on the new packaged build.

### 02 — 4663 read provenance and 24-row evidence preservation

**Confirmed risk:** The original first-24 details strategy could hide later foreign/right-use detail while continuing to count aggregate read/write records. The old queryCompleted field combined integrity, omitted-detail and query-status semantics; it was not a measured EvtNext-exhaustion witness.

**Fix:** Validator security_audit.py now records **local-only bounded** read stop reason (exhausted, scan_budget, time_budget, cancelled, failed, plus no/native-fixture variants), retrieved/rendered/accepted/filtered/duplicate/parse counts. Native EOF is the only affirmative normal exhaustion marker. Exact read/write aggregate rights continue beyond the 24 detail rows. The per-group 24-row sample retains eight earliest, eight priority historical and eight latest rows; selection is deterministic and bounded, without duplicating a record in the retained sample. Omitted details and result_limit remain explicit; selected rows are rendered chronologically at finish. Raw XML, private PIDs and handles were **not added** to the negotiated server wire contract. The scan cap, time budget, and memory limits were not increased.

**Decision:** Do not unilaterally reclassify result_limit as a clean query or relax server v4 critical gates. Improving the interpretation of read exhaustiveness, detail truncation and source attribution remotely requires a separately versioned negotiated aggregate protocol and calibrated policies.

### 03 — Windows policy/SACL recovery and cross-repository enum

**Proven cross-layer defect:** audit_settings.py could legitimately report preserved_external_change after protecting an external policy/SACL edit, but Validator's diagnostic schema and server v3 contract did not accept it. Transport could drop the **whole** optional diagnostic summary and thereby lose a critical restoration state.

**Fix:** Added preserved_external_change as a supported restoration status in Validator protocol.py and Server contract/v3/schema.json. Server v4 remains fail-closed and can independently label this status critical as audit_restoration_external_change when no stronger integrity issue is present. Added unit/transport and Django grading regressions.

**Controlled native evidence:** An elevated UAC-owned stand independently read temporary target SACL before, during and after, with observed SACL ACE and matching before/after SHA256, and tested ordinary Stop, target exit, and recovery after worker crash. The machine-wide Kernel Object audit policy was already Success before this stand and remained Success after it; thus native policy **OFF→ON→OFF switching was NOT tested**. No foreign system audit policy was overwritten.

### 04 — Scanner GUI status, Validator lifecycle and cleanup

**Source-proven race:** The observer's one-time stop_requested read in finally could skip a late GUI Stop, leaving stale Stopping after both observer and sender exited. Conversely, it could display Off before sender's bounded transport drain had ended. The exact cause of the historical ≥11-second Stopping symptom is not directly proven by its old JSONL, which lacks GUI/transport state transitions.

**Fix:** Validator controller.py establishes a generation-aware stop/disabled flow and nonblocking snapshot reconciliation: Stopping while either local owner is alive, Off only after both have terminated, and stopped/error preserved for unexpected termination. New source fixtures verify sender-drain ownership. The existing frozen-run finalization limit remains 12, and the synthetic 13th attempt is rejected fail-closed instead of fabricated as clean. UAC, IPC/network/ETW and old-run cleanup ownership remain separate.

**Not proved:** 5–10 native C05 survive/restart/exit overlaps on the patched build, actual intermittent shutdown timing, live UAC cancellation, hostile/offline transport drain and packaged GUI cycles.

### 05 — Start/end and recording boundaries

**Decision: no speculative detector change.** Current predicate source and historical evidence already support cautious late attachment, one ID across stage0→1→2, stage/Boss-like timer rollback controls and conservative end confirmation. There was no new raw, independently verified same-pointer/same-seed restart sequence that justified changing the Scanner VOD guard or Validator detector.

**Fresh replay check:** Executed source-only predicate replays for the three saved archives and independently compared the current cases to their actual pinned after-fix JSON **case** schema: 41,333/42 controlled, 15,090/22 chaos, 3,096/5 followup; total **59,519 saved observations, 69 confirmations, zero per-scenario mismatches**. The original attempts to pass the after-fix case file through --shadow / --require-shadow-match failed because that CLI argument expects an events-shaped shadow file, not a cases-shaped pinned result; those failed invocations are not accepted evidence. The successful exact comparison and inputs are recorded in acceptance/replay_verification_20261117.json. Replay is not physical ground truth or a new game run.

### 06 — Polling, ETW/Census, ImageLoad and resource cost

**Source conclusions retained:** Earlier isolated >500-ms intervals were physical start-to-start delays, not proof of slow memory reads or a causal FPS penalty. The nominal 100-ms worker loop is not hard real time. Scanner CPU and elevated worker CPU must be measured separately. No additional sensor, always-on Security reader or high-frequency Census poll was added.

**Fresh owned Windows ETW fixture:** A separate controlled experiment, not the production Validator, successfully observed owned process/thread opens and ImageLoad/ImageUnload, including 3 DLL load and 3 unload matches, with a total 12 lifecycle rows, 21 acquisition rows, zero events/buffers lost, zero local drops, no decoder errors, native ETW stop/consumer/close status 0. A non-owned enumeration path was deliberately skipped. The first attempt with an output directory containing spaces failed to start the actor; the successful rerun used a short scratch path. Evidence copied to acceptance/etw_m2_summary.json and companion owned ground-truth files. This does **not** prove the patched production ETW/Census loop, native independent owner cleanup on GUI Stop, or 20–30-minute resource stability.

### 07 — Delivery, version-pinned assessment, private catalogue

**Server and transport evidence:** The existing v3 sender supports negotiated features and immutable in-process retries, while the Django/PostgreSQL server persists accepted sequence/digest/ACK transactionally. New cross-repo enum tests preserve the external-change restoration reason instead of silently discarding diagnostics. Server private process-review now excludes failed ETW returnStatus from *successful* requested-rights triage without rewriting older pinned report assessments. Source tests cover v4 neutrality for unknown Requested/Granted capability and survival of independent file findings during partial Security evidence.

**Fresh local durability:** The existing scripts/check_local_durability.py enrolled a synthetic session via HTTP, verified provisional invisibility, accepted the finish, restarted local Django/PostgreSQL and verified the **same finish ACK and public projection** after idempotent retry. The local session ID is a33f35b3-bf6a-4002-a87b-faf9faa77a07; the health endpoint, JSON report API and pilot HTML report independently returned HTTP 200 after restart. The public synthetic assessment remained inconclusive, not falsely favorable. PostgreSQL test suite and operator-only export/review are recorded below. No production or external hosting was touched.

**Bounded limitation:** The client has RAM buffering and bounded drain, **not** a persistent crash-durable local spool. An offline client that dies can still leave finish_unconfirmed. This is an explicit product trade-off, not evidence of guaranteed exactly-once delivery after client restart.

## 3. Executed acceptance commands and results

| Layer / test | Type | Result | Exact command or evidence |
|---|---|---|---|
| Validator baseline | Source pytest, before patch | **PASS** — 286 tests + 33 subtests | bonkscanner_validator: py -3.12 -m pytest -q tests |
| Validator final | Source pytest, after patch | **PASS** — 298 tests + 33 subtests | bonkscanner_validator: py -3.12 -m pytest -q tests; includes 12 integrator fixtures |
| Scanner Validator UI/report/shutdown/recording | Source Qt offscreen pytest | **PASS** — 63 tests | Scanner src/tests/test_validator_integration.py, test_validator_ui.py, test_validator_reports.py, test_validator_shutdown_ui.py, test_active_recording_feed.py, test_recordings_segment_and_stages.py |
| Scanner run/recording predicate suite | Source pytest | **PASS** — 483 tests + 24 subtests | src/tests/test_gui_run_control.py, test_run_control.py, test_live_run_tracker.py, test_scenario_trace.py, test_vod_storage.py, test_fast_run_timer.py |
| Scanner narrow unittest | Source unittest | **PASS** — 27 tests | .venv python -m unittest discover -s src/tests -p test_validator*.py |
| GameLab | User-owned workspace, offline | **PASS** — 173 + 36 tests | bonkscanner_experiments: py -3.12 lab.py test |
| Validator P07/P08/controlled/chaos/followup | **Saved source-only replay** | **PASS** — 59,519 rows, 69 confirmations, 0 mismatches | acceptance/replay_verification_20261117.json + three detailed replay JSON outputs |
| Server database migrations/suites | **Local development Django/PostgreSQL** | **PASS** — 120 tests, 1 skipped | docker compose up --build --wait; docker compose exec -T web python manage.py test --keepdb --noinput --verbosity 1 |
| Server accepted finish + retry after DB/web restart | **Real HTTP to local dev DB** with synthetic evidence | **PASS** | py -3.12 scripts/check_local_durability.py; identical ACK and public projection after restart |
| Server HTTP public projection | Local dev service GET | **PASS** | /healthz, /v3/sessions/a33f35b3-bf6a-4002-a87b-faf9faa77a07 and /reports/a33f35b3-bf6a-4002-a87b-faf9faa77a07 each returned 200 |
| Server private triage/export | Local operator commands | **PASS** | acceptance/private_report_synthetic.json, private_census_summary.log, private_process_review.json; keep private |
| Security 4663 owned-process/Stop/exit/worker crash | **Elevated native Windows/UAC**, owned fixtures | **PASS with native-scope limits** | acceptance/security4663_owned_stand_v2.json, windows_stand_exit_v2.json (exit 0); 3 accepted ambiguous events, exhausted read, owned recovery verified |
| Independent SACL before/during/after | **Elevated native Windows/UAC** | **PASS** | SHA256 before==after, active differs; active audit ACE read independently; accompanying v2 JSON |
| Kernel Object global policy switching | **Elevated native Windows/UAC** | **PARTIAL** | Before/active/after all Success; baseline restoration observed but OFF→ON→OFF never exercised |
| Owned process/thread and ImageLoad ETW | **Elevated native Windows/UAC, separate experiment** | **PASS with scope limits** | acceptance/etw_m2_summary.json, audit-policy-readonly and ground-truth files; zero ETW loss, stop/close 0 |
| Packaged Scanner + patched Validator in game | **Native production-form acceptance** | **NOT TESTED** | No active MegaBonk during integration; dist/BonkScanner.exe predates source patches; no rebuilt packaged executable acceptance |
| Full real Scanner→worker→IPC→HTTP→PostgreSQL→browser run | **Single-session native end-to-end** | **NOT TESTED** | Local synthetic HTTP and source transport tests passed separately; no matching live localRunId/sessionId/ACK from updated packaged game |
| Long-running 20–30-minute performance/Stop | **Native resource acceptance** | **NOT TESTED** | Prior short historical resource baselines exist, not post-patch long duration |

A first Django test invocation requested deletion of a pre-existing test database and was stopped; the successful run used --keepdb and --noinput, preserving the prior test DB. The first external auditpol wrapper accidentally targeted IPsec Main Mode, not Kernel Object; the entire v2 native readback with the **correct 0cce921f-69ae-11d9-bed3-505054503030 GUID** supersedes those earlier files. The first ETW actor launch failed due to a spaces-sensitive legacy test script; the successful short-path ETW fixture supersedes it. These setup errors must not be counted as passing acceptance.

## 4. Acceptance matrix by original investigation

| Workstream / invariant | Status | Basis and explicit gap |
|---|---|---|
| 01 coherent UTC/QPC pairs, frozen deferred end, true ±2318 ms step, wide bracket | **PASS (fixture)** | tests/test_integrator_stabilization.py; real historical time step separately verified by prior Windows Event 1 |
| 01 complete native Security continuity after clock step and long gradual drift | **NOT TESTED** | New native game data and controlled drift fixtures not captured |
| 01/05 >500-ms run observation gap cannot extend 4663 binding; 32-span limit | **PASS (fixture)** | 499/501 ms and 33+ span synthetic regressions |
| 02 0/24/25/100 rows, rights counts and stratified details | **PASS (fixture)** | integrator tests and security_audit_limits.py; no unbounded read |
| 02 finite EvtNext scan vs EOF, failed query, cancellation, local reason accounting | **PASS / PARTIAL** | Source tests for normal cap/EOF/failure; native 3-row query exhausted; native dense >24 Security journal not exercised |
| 02 native foreign handle target attribution with same-image duplicate processes | **PARTIAL** | Owned 4663 events remain ambiguous; exact target never inferred; large noisy/native saturation not independently measured |
| 03 preserved_external_change propagation from producer through Validator/server v3 | **PASS (source and contract)** | Enum + transport and v4 Django tests, no lost entire diagnostic |
| 03 independent policy/SACL before/active/after, normal Stop and worker death | **PARTIAL** | SACL fully observed on live fixture, policy initially Success; no physical policy toggle or forced helper-death branch |
| 04 Stopping stale/premature Off, sender drain ownership | **PASS (source fixture)** | Controller reconciliation and Qt source tests, no new packaged GUI instrumentation |
| 04 native C05 overlaps, rapid Enable→Stop→Off→Enable, UAC cancel, hostile transport | **NOT TESTED** | Old captures support some run-ID separation only at older revisions; no new native sequence |
| 04 bounded frozen queue 12/13 and old-run ID isolation | **PASS (source fixture)** | Integrator saturation and existing deferred tests; native 13th with OS handles not tested |
| 05 known/late start, confirmed/unknown end, 0→1→2, rollback, P07/P08 | **PASS (source replay); PARTIAL (native)** | Saved 69 confirmations and historical original game; post-patch live not run |
| 05 exact Boss Room boundary and same-seed/same-pointer restart ground truth | **NOT TESTED** | No independent Boss marker or verified native same-pointer scenario |
| 06 native ETW requested openings, process/thread/image lifecycle | **PASS (owned fixture); PARTIAL (Validator)** | Dedicated ETW experiment passed; production patched ETW+Census fallback not rerun |
| 06 20–30-minute resource, Scanner CPU vs elevated worker, post-Stop ETW owners | **NOT TESTED** | Prior 35–40s resource data are historical, no new long run or per-function profile |
| 07 Django/PostgreSQL persistence, exact retry ACK, public/private separation, v4 tests | **PASS (local dev/synthetic)** | 120 Django tests, local HTTP restart durability, public 200, private export |
| 07 version pins v1–v4, retained independent findings, non-favorable partial Security | **PASS (source/server tests)** | Django assessment and legacy tests; production deployment/version acceptance not tested |
| 07 live Scanner→worker→IPC→Transport→DB→browser in one confirmed game run | **NOT TESTED** | Synthetic DB and local sender suites were separate |
| 07 process catalogue code/failed-ETW triage | **PASS (mechanism)** | Private review filter and Django regression |
| 07 process catalogue completeness on diverse third-party machines | **PARTIAL / OPEN** | Requires corroborated cross-user samples and manual curation |

**Status interpretation:** PASS (fixture/source) never means native-game PASS. PARTIAL and NOT TESTED cannot be converted into a favorable report, and a client observation never becomes trusted attestation.

## 5. Remaining blockers, priorities and release gate

1. **Updated packaged Scanner/Validator and actual game not accepted.** There was no live MegaBonk at integration time; the existing distributed EXE was built before these changes. A new matching packaged build and normal user-process/UAC worker session must prove actual starting, ending and stage transitions without changing system time, plus native GUI Stop/Off and server ACK at the same run ID. Do not retroactively claim the prior old-build 09:30 capture proves the patched code.
2. **Native lifecycle stress and cleanup.** Execute 5–10 completed C05 restart/Stop overlaps, old and new run owners, bounded IPC tail, real UAC cancel, worker/helper interruption, slow/offline endpoint, and independent SACL/policy readback. The privileged machine-wide policy must not be reset blindly; deliberate external edits must remain intact. Capture exact PID/HWND and owner generation; no global mouse or keyboard input.
3. **Resource/staleness acceptance.** After native short cases stabilize, collect 20–30 minutes of CPU by *Scanner versus worker*, handles, threads, private memory, sensor freshness and ETW queue status, then Stop and confirm cleanup. Existing FPS runs are non-deterministic and should not be repeated as causal experiments.
4. **Coverage and marker gaps.** A genuine Boss Room marker is still absent; independent current-stage flag/operator reference is needed before claiming exact boundary. Native dense Security >24, true journal gap, same-image ambiguity and policy OFF→ON→OFF remain partial or untested. Gradual UTC slews and scheduler jitter beyond synthetic fixtures remain open.
5. **Server end-to-end native delivery and hosting.** Obtain same-session localRunId, session ID, accepted sequence/ACK, durable PostgreSQL row and public/private GET for the patched packaged game. Local dev server success is not proof of production TLS, operational uptime or deployment. Client crash-durable spooling is not implemented by policy.
6. **Catalogue population.** The classification and private triage mechanism works, but a complete benign process catalogue cannot be inferred from a single machine. Keep owner lifetime, signer/image identity, access success and potential 4663 use distinctions conservative.

The integrator deliberately rejected speculative run-detector changes, unlimited audit buffering, a persistent Security reader, broader anti-cheat sensors, changes to wall-clock policy, and a client crash-durable spool without further scope approval. These would add cost and uncertainty without proven marginal benefit for the confirmed P0 fixes.

## 6. Reproduction and safety notes

- Local acceptance folder: F:/Python/BonkScanner/agent tasks/validator-stabilization-2026-11-17/acceptance. Contains new replay JSON, owned Windows policy/SACL proofs, ETW M2 summary and ground truth, plus **operator-private** synthetic export/review; do not distribute raw private export.
- Native Security canonical evidence: security4663_owned_stand_v2.json and kernel_object_policy_before_v2.txt / kernel_object_policy_after_v2.txt. Ignore the older non-v2 auditpol IPsec evidence for this purpose.
- Source test entry points: Validator tests/test_integrator_stabilization.py, tests/test_security_audit.py, tests/test_security_audit_limits.py and existing full suite; Scanner selected source test files listed in §3; Server Django sessions/tests/test_assessment_v4.py and test_delivery.py.
- Windows 11 build 26200. The ordinary MCP gateway is **not elevated**, and a normal auditpol query without privilege returns error 0x522. Only the isolated native fixture used a standard Windows RunAs/UAC flow, with no secure-desktop bypass. The game and Windows system clock were not changed by integrator tests.
- Local Docker Compose was explicitly turned on by the user and operated exclusively against the documented development server/volume. It was rebuilt and temporarily restarted for durability tests; production was untouched.
- No original JSONL captures were altered. All pre-existing GameLab and Docs user work and unpublished commits remain in place.

## Final acceptance statement

**P0 source reliability and selected native Windows safety fixtures: verified in the stated scopes.**  
**Local Django/PostgreSQL transaction, retry and public/private projection: verified with synthetic HTTP.**  
**New packaged Validator with real gameplay, same-session server chain, repeated native Stop/UAC, and long-duration resource stability: NOT TESTED.**

**OVERALL: PARTIAL. RELEASE GATE: NOT SATISFIED.** Process-catalogue completeness may remain as a known product backlog, but the unexecuted native acceptance gates above are additional unresolved verification work, not automatically successful components.

