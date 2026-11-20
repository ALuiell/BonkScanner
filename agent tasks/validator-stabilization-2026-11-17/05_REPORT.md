# 05 — Run boundaries, run identity and Scanner recording consistency

**Investigation date:** 2026-11-17
**Priority / disposition:** P1 research; **no production code changes proposed without new evidence**. Existing detector: bounded pass for the captured conditions, not release acceptance.
**Execution boundary:** Read-only code, Git status, documentation, immutable JSONL and saved receipts. **No test, replay, game, Scanner, Validator, GameLab, ETW, UAC, or server process was started in this investigation.** The only authored artifact is this report. All deferred checks are **NOT TESTED** by this investigation.

## 1. Revisions, instructions and evidence provenance

| Repository | Observed HEAD | Working tree / ownership |
| --- | --- | --- |
| F:/Python/BonkScanner (Scanner) | c955c68 | Existing untracked agent tasks directory; not altered |
| F:/Python/BonkScanner_validator | 21c9432 | Clean at inspection |
| F:/Python/BonkScanner_experiments (GameLab) | 65f41a5 | User-owned modifications in game_lab/AGENTS.md, controls.py, game.py, run_control.py; untracked test_run_control.py and retained log receipts; not altered |
| F:/Python/BonkScanner/docs (independent Git repository) | 7ec676f | main ahead of origin by three, modified development/game_lab.md; not altered |

Instructions read: Scanner AGENTS.md, Validator AGENTS.md, Experiments AGENTS.md and game_lab/AGENTS.md. The experiments manifest entry in manifests/tools.json:389-397 identifies GameLab as a build-gated Windows x64 tool with explicitly mutating native commands; this research does not invoke them. CodeGraph was consulted for Scanner (indexed); Validator and Experiments reported no CodeGraph index, so their on-disk source was inspected directly.

Primary code inspected:
- Validator src/bonkscanner_validator/run_detection.py:12-135; engine.py:278-497,921-1145,1329-1591; run_diagnostics.py:12-96; controller.py:146-204,280-310.
- Validator tests/test_run_detection.py:21-195, tests/test_validator_engine.py:180-394,479-490, tests/test_run_diagnostics.py:8-49. Source inspection is **not** a new test run.
- Scanner src/app/run_lifecycle.py:168-231; src/core/game_state.py:59-130; src/infra/memory/game_data_client.py:194-281,283-412; src/app/vod_capture.py:80-123,475-618; src/app/validator_reports.py:91-123,148-295.
- Scanner src/tests/test_gui_run_control.py:2079-2268 and the run lifecycle tests at 805-971; src/tests/test_scenario_trace.py:15-133; src/tests/test_validator_reports.py:60-286.
- GameLab game_lab/run_control.py:12-150; game_lab/setup_common.py:103-151; game_lab/game.py:470-475; game_lab/test_run_control.py:14-122 (untracked, user-owned).

Maintained scope read at docs/updates/functional_updates.md:43-158,186-210. Design and historical verification reviewed at docs/validator/run_boundary_assessment_upgrade_2026-11-17.md:7-60, docs/validator/validation/run_boundary_assessment_code_review_2026-11-17.md:7-50, and docs/validator/validation/run_boundary_assessment_P07_P08_fix_2026-11-17.md:3-30. The design is explicitly pilot-only; no new sensor, production hook, game mutation, persistent service or mandatory dependency is approved here.

Historical proof is **revision-pinned**, not interchangeable:
- Controlled/chaos/follow-up predicate replay: Validator **21c9432**, 41,333 samples **42/42**, 15,090 **22/22**, 3,096 **5/5** compared with the shadow reference; **69/69 per-scenario count agreement across 59,519 non-atomic observations**. These are shadow-confirmation *counts*, not independent ground-truth run counts. See P07/P08 addendum:15-28 and Scanner .local/validator-start-trace/retest-kit/shadow-replay/production-predicates-*-after-fix.json.
- Earlier source suites: Validator 286 passing tests/33 subtests, Scanner validator UI/report subset 31, server pure tests 106 and GameLab tests 209, as reported in QA_DIRECT_GAME_LAB_INTERIM_2026-11-17.md. **Not rerun here.**
- C01/C02/C03/C05/C14/C15 live QA used Validator **21c9432**, Scanner **c42346b**, supported MegaBonk **1.0.69**, with GameLab changes dirty and locally owned. Later heavy-wave and natural stage traces used Scanner **c955c68**, Validator **21c9432**. Therefore neither earlier Scanner behavior nor user-owned GameLab behavior should be silently attributed to a different build.

## 2. Current boundary model and invariants

### 2.1 Start, identity, recovery and short attempts

1. An eligible candidate requires a supported, readable in-game state, a valid nonnegative timer and compatible identity. Validator new_run_signal (run_detection.py:31-71) treats raw stage index >0 to 0, an early stage-zero timer rollback greater than 0.05 seconds, or a **joint** first-stage seed **and** player object change as evidence. A changed stage pointer or seed **alone** does not identify a new attempt. A changed run configuration requires corroborating identity for the explicit configuration signal.
2. candidate_identity/candidate_compatible (run_detection.py:74-96) require consistent stage index and run configuration, plus agreement of available seed/player identifiers. Pointer reuse is possible; stage pointer is not an independent boundary. Genuine stage 0 to 1 to 2 increments, virtual Boss Room at raw index 2, and Graveyard phase transitions should stay in the original attempt.
3. _confirm_run_start_impl (engine.py:355-451) requires at least approximately **one second of positive observed active game-timer progress**, not one second elapsed on the wall clock. It does not infer missing observations from a pause, loading, unreadable state, sudden timer jump or physical poll gap. The five-second candidate budget is active-time-oriented. A very short GameLab restart can be real yet remain a diagnostic/superseded candidate without any Validator run_start.
4. Known starts can follow a fresh menu/end context or a recent, corroborated first-stage reset signal. Otherwise the binding is run_start_unknown or attached_mid_run; a physical gap greater than 500ms downgrades a previously known start to unknown (engine.py:403-410). Even run_start_known has the first observed active second **unenrolled for process-access evidence**: engine.py:325-333 records an explicit zero-offset unknown prefix. No boundary label alone proves full ETW/Security coverage.
5. P07 at saved samples #17603/#17604 (0.008 to 0.349 game seconds across 0.122 physical seconds) previously lost 0.341 seconds of confirmation credit. run_detection.advance_active now caps plausible timer bursts at the real polling interval; P07 confirmations were #17612 and #17622. P08 saw 0.628 to 0.695 game seconds entering pause; the observed 0.067 seconds is credited once, never during the paused interval; confirmations #19335 and #19346. See P07/P08 addendum:7-13 and tests/test_run_detection.py:72-155. This did **not** reduce the one-active-second threshold or cure unknown pre-start coverage.
6. An unobserved transition across a polling gap may reveal that a new run exists while leaving its true beginning, number of intervening short runs and audit continuity **unknown**. Never promote a recovered attempt to a directly witnessed start or claim that one GameLab native restart necessarily equals one independently confirmed Validator session.

### 2.2 End cause and confirmed boundary

- A fresh death/ended sample confirms the end only with a recent valid bound predecessor, matching run configuration, stage pointer/index and nondecreasing timer, without a prior unknown interval (engine.py:483-497 and 1513-1524). A stable menu, including menu_music_match with stale gameplay flags, needs frozen/non-advancing timer and **three fresh reads over at least 0.25 seconds**, with continuity from the preceding bound state (engine.py:453-481,1503-1524). One music-song sample is never sufficient.
- Only the independently confirmed run_ended path in the current implementation passes confirmed_end=True and adds confirmedRunEndMs, equal to the final payload capturedThroughMs (engine.py:1098-1103). A recognized replacement by another run currently closes the previous attempt with a marked all-channel unknown gap and **context_lost, confirmed_end=False** (engine.py:1528-1540). The new run may be well identified while the *old* end instant is not. Do not treat the old run as normally completed.
- Game process disappearance yields game_exited without confirmedRunEndMs (engine.py:1383-1386). An unreadable/loading context sustained for approximately 15 seconds yields context_lost, not a proved end (engine.py:1574-1581). Observer Stop and worker interruption also cannot imply a game termination. Unknown spans remain unknown; do not backfill timestamps or coverage.
- Finalization is deferred per-run (engine.py:921-1053). Old frozen ETW/Security state must retain its original localRunId; the new run continues polling, and its temporary native audit handoff is explicitly partial. Controller routes old payload and terminal packets via its tracked ID set, not merely the currently active UI ID (controller.py:146-204). A failed finalizer remains incomplete/inconclusive rather than fake full evidence.
- The current terminal reason string context_lost does not distinguish a **known replacement candidate** from a generic lost context at the public transport level. This is a narrow diagnostic expressiveness gap, **not** proof of incorrect identity, and cannot authorize a confirmed end. A non-contract-changing local diagnostic subreason may be considered only if later triage needs this distinction.

### 2.3 Scanner is a different lifecycle

Scanner RunLifecycle.refresh runs a cached ~1s activity probe and emits scanner_run_detected whenever cached state changes from inactive to active (src/app/run_lifecycle.py:168-205). A loading/idle phase can therefore emit a second activity-detected notification without starting any new recording. This event is **not** a recording-start event and is not comparable one-to-one to Validator run_start or localRunId.

Scanner recording uses a separate armed/started/stopped/split state (src/app/vod_capture.py:475-618): game over or main menu stops recording; PAUSED keeps it; UNKNOWN does not fabricate a stop; a falling raw stage index triggers a split, a rising index does not, and unchanged index plus a sufficiently large timer decrease can split when the seed/stage identity changed. The Scanner timer tolerance is 3.0 seconds (src/core/run_summary.py:29; src/app/vod_capture.py:80-123). Actual recording_started, recording_split and recording_ended events, plus the recorder files/IDs, are the evidence required to claim an extra recording.

**Source-level edge to preserve as an unproven risk:** src/app/vod_capture.py:573-578 returns early on **unchanged seed and stage pointer**, before examining timer or stage index. Consequently a genuine same-pointer/same-seed restart not observed through menu/death may not split the recording. However, forcibly treating a same-pointer timer rollback as a restart would falsely split the proven heavy-wave time rewinds. No live same-pointer/same-seed genuine restart with an independently proven outcome is present. Require a discriminating regression before proposing a change to this guard.

Scanner report association is also separate: src/app/validator_reports.py:91-123,254-295 requires the same game process and a unique, monotonic sample bracket on a stable stage pointer/index, not just shared seed or start time. A replacement transport generation requires fresh matching samples. Provisional runs do not create a public report link before acknowledgement; see tests/test_validator_reports.py:60-286.

## 3. Saved live traces: confirmation versus uncertainty

### A. C01/C02/C03/C05/C14/C15 — direct Windows/GameLab QA, earlier Scanner build

Evidence: Scanner .local/validator-start-trace/retest-kit/captures/session-20261117-080026-ba7a2e/QA_DIRECT_GAME_LAB_INTERIM_2026-11-17.md; C05_direct_restart_during_finalization_r1.json, C14_direct_new_gamelab_count_and_seed_search_r1.json, C15_gamelab_raw.json; validator-18420-f05734986a514c13807bad9437b2727f.jsonl, scanner-19788.jsonl and manual.jsonl.

- **C01:** confirmed real menu Play, one known Validator start, exit to menu and one confirmed end. Finalization about 1.523 seconds with 13 fresh polls. Physical max polling gap 576ms exists somewhere in the case; no attribution to finalization established.
- **C02:** eight independent GameLab verified rapid native restarts/changed seeds, but only one final long-lived Validator start (and confirmed end); this is compatible with the 1-active-second enrollment requirement, **not eight missed confirmed sessions**.
- **C03:** 30-second pause started with timer 0.28249 seconds; 262 fresh polls recorded paused=True and a frozen timer, then resumed and exited, one known start and confirmed end. Evidence supports pause retention for that tested duration.
- **C05:** original scripted case ended with the last player dead before the requested Exit; scripted result stopped_on_failure. Three Validator starts and three terminal packets; first two terminal causes context_lost/unconfirmed; last run_ended/confirmed. It **does** test overlapping deferred old/new identities, but **does not** complete a controlled survive-restart-survive-exit sequence.
- **C14:** the fixed-count GameLab series verified ten native restarts; only one long-lived Validator start/end is consistent with very short candidates. The seed-search series verified 13 restarts; its attempt #14 stopped on an invalid pointer with unknown completion, and no seed match was observed.
- **C15:** a run restarted from confirmed game_over (seed 768360451) to a verified new seed 1744736123 matching the requested pattern 1*; exactly one native call, status seed_matched. Later cleanup and death-related context are not evidence that the previous attempts had confirmed ends.
- Security evidence in these pilot cases remained partial (unknown run prefix, late_attachment, possible audit handoff overlap and handle attribution constraints). C01/C05/C14/C15 cleanup had some >500ms physical gaps; later polling/finalization investigation belongs to workstream 06, not automatic proof of blocking finalization.

**C05 precise chronological identity evidence** (validator JSONL sequence IDs / performance-counter timestamps, native receipts; all are existing recordings):
| Trace / receipt | Original event | Interpretation |
| --- | --- | --- |
| Validator #12874; candidate #12871 | Initial confirmed start | First local run enrolled |
| GameLab receipt 20261117T060759-run-restart-155042db.json, QPC 30534073500500..30534561452100 | Native restart; seed 1009623256 -> 1885590221 | Verified game action, **not** instant Validator confirmation |
| Validator #13572-#13577, QPC 30535765019600 finalization_begin | New candidate confirms; old run frozen as context_lost; new run_start follows | Previous run evidence still belongs to old ID |
| GameLab receipt 20261117T060801-run-restart-81fcd518.json, QPC 30535806003200..30536338645200 | Second verified native restart; seed 1885590221 -> 372670624 | Happens after the previous finalization begins |
| Validator #13653/#13654 | Old run_end context_lost, then finalization_end for e06ec6f2-3dbf-47d5-9c0b-e10e4d013071 | Arrives **after** new run_start #13577, preserves old ID |
| Validator #13665-#13670 | Candidate confirms, second context_lost finalization begins, next run_start follows | Third local run enrolled |
| Validator #13745/#13746 | Second deferred context_lost run_end/finalization_end for df66a719-ad64-4eb5-8bcb-c750a24b72da | Again routed to the old, not active, run |
| Validator #14276/#14341/#14342 | Final run_ended confirmed; deferred end for e0c0f107-40da-4195-b519-a270a3596148 | A separate proved death/end, not backdated to the earlier contexts |

C05 Scanner raw JSONL contains recording_ended(deleted_short) at QPC 30517309207900, recording_started at 30517313062400, recording_ended(deleted_short) at 30534892333400, recording_started at 30534895188500, and recording_ended(deleted_short) after game_over at 30553497130800. These are recorder-specific segments around real game activity; their count alone is not evidence of an extra/phantom recording. The QA case did not retain a complete independently reconciled recording-ID-to-every-Validator-run sequence. **Result: no demonstrated localRunId cross-contamination; C05 full end-to-end identity/recording reconciliation remains NOT TESTED.**

### B. Heavy-wave rollback negative controls — current Scanner build

Evidence: .local/validator-start-trace/retest-kit/captures/session-20261117-091510-f305cc/QA_HEAVY_FINAL_2026-11-17.md, QA_HEAVY_WAVE_TWICE.json, validator-*.jsonl, scanner-*.jsonl. Scanner c955c68 / Validator 21c9432. Three real game-timer rewind events approximately 275.5 -> 235 seconds occurred on raw Forest stage 0 with identical seed 1238173233 and the same player object; **zero additional Validator run_start** events. The single run was attached_mid_run; UI Stop produced observer_stopped with confirmed_end=false. HWAVE_01: 404 fresh polls, maximum 267.82ms; HWAVE_02: 407, maximum 372.82ms; no >500ms gaps in either window. The capture supports **no false restart from the observed rewind**, not proof that a genuine same-pointer/same-seed restart would be detected. Independent native Security SACL restoration was not verified.

### C. Actual natural stages 0 -> 1 -> 2 and game end — current Scanner build

Evidence: .local/validator-start-trace/retest-kit/captures/session-20261117-093004-1afdfe/FINAL_REAL_STAGE_REVIEW_2026-11-17.md, validator-18452-005877f2cb7940fb8e82ac846cb0884a.jsonl, scanner-26764.jsonl, manual.jsonl and RESULTS.md. Supported MegaBonk 1.0.69, PID 15492 throughout; Scanner c955c68, Validator 21c9432.

- Scanner recording_started before Validator attachment, 09:30:10.201; Validator joined midgame 09:30:27.255; Validator #61 candidate_confirm and #62 **the only** run_start at 09:30:28.648, attachment attached_mid_run. Scanner recording and Validator run have intentionally different start times.
- Stage 0 -> 1: 09:35:48.806, Validator raw sensor event **#12446**; transition to loading event **#12493** and idle **#12501**; new seed/player at stage1 event **#12661**. Stage 1 -> 2: 09:36:48.165, event **#14736**; idle **#14779**, new stage2 seed/player **#14946**.
- Around the possible Boss Room re-entry, raw stage index remained 2; idle **#16601**, resumed with same map seed but different player **#16965**. This is **compatible** with a boss-room transition at 09:37:36–09:37:45 but **cannot** pinpoint the exact Boss Room boundary: no independent raw isFinalBossStage sample/ground-truth scene flag was captured. Scanner has a MapGenerationState.is_final_boss_stage field (src/core/game_state.py:72-76), but that is not present in the Validator raw sensor field list (engine.py:1458-1462) for this capture.
- Human-reported boss kill ~09:39:03.857; Validator first ended sample raw event **#20613** at 09:39:21.089, finalization_begin **#20616** run_ended/confirmed=true; Scanner **one** recording_ended(kept) at 09:39:22.114, stage2; Validator run_end **#20682** run_ended/confirmed=true, finalization_end **#20683**. Both Validator start/end refer to localRunId **b559f571-ff61-4e9a-b71a-bc002e193717**.
- Scanner emitted **three scanner_run_detected** notifications during stage reentries but **no additional recording_started** and no recording_split. One retained Scanner recording and one Validator local run survived stage, seed, pointer, player, idle/loading changes.
- Deferred finalization lasted approximately 1537.6ms with 12 fresh polls during it, within-window maximum ~216.97ms. The final recount covered 6909 fresh polls with maximum 453.537ms and **zero >500ms gaps**. This is a bounded live success for sensor cadence; not a universal zero-gap guarantee.
- Security final result was **partial**: late_attachment, clock_changed, run_boundary_unknown and result_limit; only 24 ambiguous rows retained and none conclusively attributed. A result cap being exceeded does not mean there were only 24 underlying records. Audit-policy/SACL restoration not independently verified (non-elevated auditpol read error 0x522). After UI Stop, worker exited but Scanner displayed Validator Stopping for at least 11 seconds (cross-ownership issue for workstream 04). Those do not undermine the observed single-run boundary, but do block any full-security-coverage/release claim.

**Interpretation:** the natural full 0->1->2 passage was already observed on the current detector and should be treated as **historical positive evidence for these revisions** if the detector remains unchanged. Do not force another long Boss game merely to repeat the same count. The **exact** Boss Room boundary remains unverified until synchronized, independent scene flag or witnessed ground truth exists.

### D. Saved shadow rollback controls

The offline shadow-replay/BOSS-ROLLBACK-REVIEW.md models a stage2 boss timer correction of 286.086 -> 286.000 seconds, with unchanged stage pointer, seed and player, and 2s/4s/7s freezes. The corrected stage-zero-only predicate generated zero extra boss candidates/confirmations across six variants; 20 synthetic controls passed in the **historical** review. Before correction the shadow model generated false confirmations for some freezes. Retained saved replay counts matched 42 -> 42 controlled and 5 -> 5 follow-up. This is **bounded synthetic evidence**, not direct raw flag-backed Boss Room live proof.

## 4. GameLab test-instrument findings (separate from Validator correctness)

GameLab run_control.py:25-52 observes loading/resetting, process/run context, menu music, Pause UI, death and timer sanity. A native restart is verified by a *subsequently observed* seed change (run_control.py:122-150), not merely the return value of a native call. A seed search checks only **new verified** seeds, with fnmatchcase against the requested pattern (run_control.py:101-118). Existing tests/test_run_control.py:35-122 cover simple count/interval, pattern, starting-seed exclusion, error/unknown preservation, and a nonverified call. No live action was performed in this investigation.

| Retained GameLab receipt | Verified observations | Disposition |
| --- | --- | --- |
| game_lab/logs/20261117T061504-run-restart-series-7816b330.json | 10 requested, 10 native calls completed, 10 verified seed transitions; status verified | C14 fixed-count PASS for that build/session |
| game_lab/logs/20261117T061507-run-restart-series-0d1bc270.json | 15 maximum, pattern *7; 13 calls and 13 verified transitions; #14 recorded verified=false, no after; invalid pointer 0x2d95259dce1 | C14 pattern search **INCONCLUSIVE**, correct conservative fail/stop, not evidence that matching algorithm failed |
| game_lab/logs/20261117T061633-run-restart-series-e5802738.json | 6 maximum, pattern 1*; initial game_over=true, seed 768360451; exactly 1 completed and verified restart, new live seed 1744736123; status seed_matched | C15 first-new-match PASS for that build/session |

The Operation implementation writes a receipt **before** the native call, updates the step and native call count on return, and persists failed_or_unknown on failure (game_lab/setup_common.py:109-151). Thus a pending/unknown attempt is **not automatically retried**; prior verified transitions survive in the receipt. Death, an invalid pointer or changed context must stop the batch rather than be coerced into a success. The 14th C14 operation has no confirmed completion, and the later game_over observation does not prove why it failed.

**Confirmed test-tool issue:** --count is required positive but has **no upper bound** in GameLab run_control.py:54-64 and game.py:470-475. The lack of a cap permits extremely large unattended restart batches; this is a command safety/availability limit, not a Validator run-detection failure. **Smallest possible follow-up (GameLab owner only, not changed here):** agree a practical maximum (e.g. 100; a proposal, not an accepted product setting), validate it before any native executor call, and add 1/max/max+1/huge-int CLI and failed/dying context/receipt tests. Do not overwrite or commit the existing user-owned dirty GameLab work.

## 5. Confirmed, expected, still open and unavailable evidence

**Confirmed in the cited conditions:**
- Post-fix production predicate matches saved shadow confirmation counts on the three cited replay sets; P07/P08 lost-credit causes identified and corrected on Validator 21c9432.
- Real-game current-build stage0->1->2 one Validator ID and one Scanner recording; no false splits across real loading/idle/seed/player/stage-pointer changes.
- Heavy-wave stage-zero time rollback at fixed identity did not trigger a new Validator run.
- C05 older run_end events arrived after later run_starts yet retained their old IDs; deferred sensor polling continued. This rules out the *observed* class of misrouting in these captured packets.
- C14 10/10 fixed restart action, C15 verified new seed match, and GameLab persistence of an unknown 14th action. GameLab has no --count maximum.

**Expected, conservative limitations rather than proved failures:**
- Sub-one-active-second attempts not enrolled; late attachment not full-prefix coverage; known boundary not audit continuity; >500ms physical poll gap carries no timer credit; unknown preceding span stays unknown.
- Current replacement closes old run as context_lost without confirmedRunEndMs; process exit, Stop and prolonged unreadable context are unconfirmed. A real restart may exist without the exact old end being observable.
- Scanner activity redetection is not new recording; recording and Validator localRunId have different triggers and cadences.
- Security 4663 ambiguity, late attachment, observed clock_changed/result_limit and missing independent restoration read prevent full coverage/favorable status.

**Open hypotheses / data absent:**
1. A true same-pointer/same-seed **genuine** restart at stage0 may evade Scanner auto-split. Only a same-identity **in-run rewind** was observed; no independent real restart of this form exists in retained proof.
2. C05 repeat with the player kept alive and an independently verified *controlled* exit is absent; initial C05 was interrupted by death. Exact cross-layer recording IDs, client->server ACK order and receipts for that full sequence are not fully reconciled.
3. No synchronized raw isFinalBossStage / independent boss-scene flag in the natural stage capture; stage2 idle and player pointer change alone cannot locate the precise Boss Room boundary.
4. The true number of subsecond attempts *inside missing physical polling intervals* is unobserved. Seed/player/stage reads are not atomic; replay/shadow agreement cannot certify physical ground truth or missing initial ETW/Security time.
5. No elevated independent readback of restored audit policy/SACL in the cited live game, no proof of complete 4663 attribution, no release-packaged EXE/UAC/HTTPS/PostgreSQL acceptance.
6. The cause of C01/C05/C14/C15 occasional >500ms poll gaps and the wall-clock/QPC drift in the final natural capture is unresolved; neighboring workstreams own those diagnostics.

**Evidence that would resolve an ambiguous boundary without a new production sensor:** align existing raw GameLab receipts (native call boundaries, before/after seed, death, pointer validity), Scanner recording_started/split/ended with immutable recording ID, Validator sensor_poll_end sequence + physical delta + candidate_start/reset/confirm + run_start/run_end localRunId, and Controller transport delivery/ACK timestamps on the same monotonic-clock basis. Preserve explicit unknown spans when there is no intervening raw sample. For Boss Room proof, independently align the already known game isFinalBossStage read or a trustworthy operator timestamp with the existing sensor stream; do not represent this as production detection or add required hooks.

## 6. Minimal changes / decision filter

**Validator run detector:** **NO PATCH NOW**. There is no demonstrated remaining false run start or cross-run terminal ID leak on 21c9432 in the reviewed evidence; P07/P08 fixes are present. Adding stage pointer, seed-only, wall-clock-only or blanket 3s rollback signals would increase false positives on observed stage/Boss/rewind controls. Preserve one-active-second, first-stage gate, conservative unknown prefix, and confirmed-end contract. A future bug report must carry a specific raw sample sequence, physical timing, independent action receipt, and expected identity before proposing a targeted function change.

**Scanner recording:** no speculative change to vod_capture.sync_run_state at lines 573-578. First add a synthetic two-way control that distinguishes a corroborated same-identity true restart from a heavy-wave time rewind; decide on a minimal gate using independently known menu/death or strong first-stage evidence only if the genuine missed split is reproduced. Preserve current 0->1->2 behavior and historical recording format. This is a **candidate regression**, not a confirmed defect.

**GameLab:** the **only directly justified small source change** is an owner-approved positive --count maximum in RunControl.run and a CLI regression at game.py:473, plus test_run_control.py scenarios for the cap and incomplete attempts. Threat: accidental/unbounded native game mutations; current mitigation: count must be positive and operations stop on unknown; marginal value: bounded operator commands without extra sensor/cost. This tool has full native write privilege already; adding a count limit is no new trust claim. Leave dirty owner changes untouched until owner accepts a separate implementation task.

**Observability (optional, not blocking):** a diagnostic-only replacement-specific subreason in engine.py:1531-1540 could distinguish confirmed successor from generic lost context while still emitting context_lost / no confirmedRunEndMs; confirm it would aid integrator triage before changing a wire schema. Existing sensor evidence is enough for that local distinction; no new required channel is justified.

## 7. Deferred integrator checks and failure gates

All rows below are **NOT TESTED by this investigation**; a cited historical pass remains separate. W=Windows required; U=UAC/elevated worker required; G=real supported game required; S=configured server required. "Offline" means safe to run only in a later authorized integration session, not now.

| ID / status | Objective and prerequisites | Expected observation | Failure criterion | Needs |
| --- | --- | --- | --- | --- |
| R01 — NOT TESTED | Source-predicate replay at pinned Validator 21c9432 against unmodified controlled/chaos/follow-up archives | Per-scenario 42/42, 22/22, 5/5 matches; all gap/attachment semantics preserved | Any mismatch, lost P07/P08 confirmation or false full-prefix coverage | Offline; W no, U no, G no, S no |
| R02 — NOT TESTED | Natural stage 0->1->2 on supported game, Validator started before run if possible; record stage, seed, pointer and player | Exactly one localRunId, no false new run on stage increment/loading; one Scanner recording | Unexpected new run_start, confirmed old end, recording_split | W+G+U; S optional |
| R03 — NOT TESTED | Raw index2 virtual Boss transition with synchronized independent isFinalBossStage or equivalent scene marker | Exact Boss entrance verifiable; ~0.086s timer rollback/freeze does not start new attempt | False run_start or ungrounded exact Boss boundary claim | W+G; U for full Validator, S no |
| R04 — NOT TESTED | Small stage2 rollback 286.086->286.000, freezes 2/4/7 seconds; no real new run, using saved synthetic controls | Zero candidates/confirmations from rollback | Any additional run from pointer/timer alone | Offline; W no,U no,G no,S no |
| R05 — NOT TESTED | Graveyard internal stage0 same-pointer/same-seed transition; include changed player alone | Same attempt remains active | New run from player-only pointer or phase change | W+G; U for Validator, S no |
| R06 — NOT TESTED | Explicit first-stage true restart with controlled seed+player/config change and receipt; test same pointer reuse separately | Candidate reason requires corroboration, one new ID only after ~1 active second; old end unknown if not witnessed | False positive on seed/config/pointer alone, or unproved confirmed end | W+G+U; S optional |
| R07 — NOT TESTED | Loading/idle and temporarily invalid sensor reads during one run; include >15s unknown and reacquisition | Short transition retains run ID, longer loss closes context_lost/unconfirmed, preserved gap | Fabricated new start/end or lost unknown span | Offline first; W+G+U for native |
| R08 — NOT TESTED | C01 menu->Play->Pause/Exit/Confirm with raw song/timer/terminal samples | Known new start when fresh, stable menu and confirmed end only after repeated evidence | End from one song read or stale advancing timer | W+G+U; S optional |
| R09 — NOT TESTED | C02 8+ rapid verified native restarts, some shorter than one active second | GameLab receipts show all actions; Validator confirms only sufficiently observed attempts, never fabricates short sessions | Synthetic confirmed run per unverifiable attempt, incorrect old ID | W+G+U; S optional |
| R10 — NOT TESTED | C03 pause at early ~0.28s, hold 30 and 120 seconds, resume and exit | Candidate timer/identity preserved, no active credit during pause, final end proven separately | Wall-clock timeout, pause treated as active time, false new ID | Offline then W+G+U |
| R11 — NOT TESTED | P07 bounded burst at samples #17603/#17604 and physical time 0.122s | At most 0.122s credit, confirmations #17612/#17622 in pinned reduced control | First candidate lost, or credit exceeds physical interval | Offline; W no,U no,G no,S no |
| R12 — NOT TESTED | P08 timer 0.628->0.695 on pause entry; continuous pause then resume | Exactly 0.067s pre-pause credit; zero across pause, #19335/#19346 replay confirmations | Early wall-time confirmation or missed bounded pre-pause progress | Offline; W no,U no,G no,S no |
| R13 — NOT TESTED | Repeated C05 controlled restart during 4663 grace; player kept alive through an independently verified final Exit; instrument local IDs and ACK order | Old final run_end delivered to old ID after new start, no lost/duplicated payload, audit overlap partial; second run closed by proved event | Old payload bound to new ID, missing terminal, unsupported green, false recording | W+G+U+S for full delivery; local-only without S |
| R14 — NOT TESTED | Stage0 same seed+pointer genuine restart **with independent menu/death receipt** versus same-identity in-run timer rewind | Scanner recording identity follows witnessed restart but retains one recording for rewind | Missed proven restart or false rewind split | W+G; U optional, S no |
| R15 — NOT TESTED | True death event, recent matching run context, then restart | One confirmedRunEndMs only for validated game_over; next attempt separate; no cross-run artifact attribution | Confirmed end without recent matching predecessor, or old evidence moved to new ID | Offline then W+G+U; S optional |
| R16 — NOT TESTED | Explicit menu and menu_music_match with stale playing/timer, both 3 fresh reads and isolated single read | Three-read stable/frozen condition can confirm; singleton or advancing timer cannot | False end from transient music or stale moving timer | Offline then W+G+U |
| R17 — NOT TESTED | Game process exit, 15s unknown loading, and observer Stop without proved end | game_exited/context_lost/observer_stopped remain unconfirmed, no confirmedRunEndMs, unknown spans present | Finished/green status from unobserved termination | Offline then W+G+U; S optional |
| R18 — NOT TESTED | GameLab count 1/max/max+1/huge, seed-match and death/invalid pointer in middle, owner-approved bound | No native call outside agreed cap; receipts retain verified prefix and pending unknown suffix, no automatic retry | Unbounded calls, lost receipt, false seed_matched or automatic retry | Offline simulated; W+G only for later explicit native acceptance |
| R19 — NOT TESTED | Sensor and audit time-line stress across ≥500ms physical poll gap and deferred old finalizer | Physical gaps reported independently, no active-time credit across gap; Security overlap, clock drift and row cap remain partial | Fabricated continuous 4663/ETW or missed poll-gap metrics | W+U+G; S for assessment |
| R20 — NOT TESTED | Paired Scanner recording->Validator matching with new run before old deferred end; server acknowledgement and public report | Exact process/time/stage bracket matches, provisional links withheld until acknowledged; no replacement mislink; no green from unknown prefix | Report attached to wrong recording/run or falsely favorable | W+U+G+S |
| R21 — NOT TESTED | Native launch/stop/finalizer shutdown with multiple pending owners; game process and worker exit | Old IDs finish or fail closed within budget; Scanner leaves Stopping; audit SACL/policy independently read back | Stuck UI, resource leak, lost audit restoration, orphaned old run | W+U+G; S optional |

**Integrate historical passes rather than relabeling them as these newly executed checks.** R02 has a bounded prior real-game pass (natural 093004 capture) but precise Boss R03 is still unverified. R04 and R11/R12 have prior synthetic/replay evidence; R08-R10 have prior live evidence for narrower durations; R13 remains incomplete because C05 died; R14 genuine same-identity case has no live positive control. Re-run only after a relevant code change or to close a clearly specified remaining gate.

## 8. Interfaces to parallel workstreams

- **01 — Security clock/audit spans:** never derive 4663 time coverage or clock mapping from a known run_start label. Pass exact physical run origin, first audited/armed marker, lost prefix, clock_changed, result_limit, finalization_overlap and restoration evidence; natural stage capture has partial Security despite correct run identity. Owner must resolve wall/QPC mapping and cap without inventing confirmed source/target access.
- **04 — lifecycle / old run ID:** C05 #13653/#13654 and #13745/#13746 validate historical deferred old-ID routing; inspect worker shutdown, finalizer capacity and UI Stopping persistence separately. Avoid changing old-active session routing based on raw Scanner activity messages.
- **06 — polling/performance:** preserve actual physical fresh-sensor delta distributions and >500ms gap counts. C01/C05/C14/C15 had some >500ms gaps without proven cause; heavy-wave and natural-stage finalization did not. Do not infer ETW/Security continuity from nominal 100ms tick rate.
- **07 — server assessment/recording:** confirmedRunEndMs is independent of recording_ended; no confirmed end for context_lost, game_exited, observer_stopped. New/old localRunId transport packets must be immutable/version-pinned, accepted before exposing reports; a correct run boundary with late enrollment and partial Security can still be inconclusive in public assessment.

## 9. Final decision for integrator

**P1 boundary disposition: BOUNDED PASS, PILOT ONLY.** The strongest positive live evidence is current-build natural stage0->1->2 with one Validator run, one Scanner recording and a confirmed end, complemented by current-build negative heavy-wave rollbacks and C05 correct deferred old-ID routing on its earlier Scanner build. P07/P08 shadow discrepancy is already resolved by Validator 21c9432. There is no substantiated need to rewrite start predicates today.

**Targeted remaining gates:** (a) independent exact Boss Room raw flag, (b) completed/surviving C05 with full recording/ACK reconciliation, (c) genuine same-pointer/same-seed restart counterexample versus rewind, (d) native UAC/security restoration and unexplained physical gaps through workstreams 01/04/06/07, and (e) owner-approved GameLab --count cap. Never present missing start/end/sensor evidence as clean or a locally observed capability as proof of cheating or legitimacy.
