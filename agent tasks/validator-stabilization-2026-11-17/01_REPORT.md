# 01_REPORT — Security 4663 clock integrity and run-boundary provenance

**Investigation date:** 2026-11-17  
**Status:** Read-only investigation completed; implementation and regression testing **NOT TESTED** in this task.  
**Scope:** Task 01, P0. No game, Scanner, Validator, server, ETW session, replay, or tests were started. Existing Windows event logs were **queried read-only**, without changing clock/audit settings. No code, test, capture, settings, or Git files were modified. This report is the sole intended write.

## 1. Executive findings

1. **The real capture contains a genuine host UTC step, not merely a suspected finalizer race.** The Windows System log, provider Microsoft-Windows-Kernel-General, Event ID 1, Record ID **198240**, at **2026-11-17 09:33:00.361 Europe/Kyiv**, records a forward adjustment of **2318 ms**: previous UTC 07:32:58.042388300, new UTC 07:33:00.361363600. The change was performed by svchost.exe (PID 15676). The Windows Time-Service events (System IDs 37 and 35, records 198238 and 198241; Operational IDs 261 and 265, records 18122 and 18124) associate it with synchronization to time.windows.com. Independently, UTC/QPC pairs saved in the capture diverge by approximately **+2317.6 ms** after that event. An actual clock discontinuity is sufficient to trigger the client's 50 ms guard. A map transition did **not** cause this step.
2. **There is also a separate, reproducible-in-principle code defect.** ObservationEngine._finish captures a frozen wall-clock end, while _finish_audit_impl compares that frozen value against a *new* perf_counter_ns obtained in the deferred finalizer. Queuing, ETW drain, or scheduler delay >50 ms can fabricate clock_changed with stable host clocks. The observed capture's finalization_begin-to-audit_finish_begin interval is approximately **14.137 ms**, so this particular trace does not support attributing its 2318 ms shift to finalizer delay. Fix the torn pair nevertheless.
3. **run_boundary_unknown is a multiplexed quality issue, not a single root cause or evidence of cheating.** It can originate in the sensor-bound span builder, its 32-span limit, a context_lost finish, a reversed query window, or per-record fallback when a Security 4663 timestamp lies outside known spans. In the investigated run, the real clock step would latch clock_changed and clear all spans before the later loading transitions; with empty spans, the final Security parser necessarily classifies any retained qualifying 4663 rows as ambiguous/run_boundary_unknown. The exact first issue mutation is not instrumented, so this final attribution is a strong code-and-timeline inference, not a directly logged intermediate state.
4. **Additional coverage defect found in review:** an actual fresh-sample gap greater than MAX_RUN_SAMPLE_GAP_SECONDS (0.5 s) is recorded in the main run payload, but a still-open Security span is extended on the next bound sample without checking the missed elapsed interval. This can overstate 4663 run binding even if no wall-clock change occurs. The main real-stage capture had **zero observed fresh-poll gaps >500 ms**, so this defect was not exercised there.
5. The user-played 1.0.69 Forest → Desert → third-stage/boss progression maintained **one** Validator localRunId and **one confirmed natural run_end** despite transient loading/idle, seed/pointer changes and genuine stage index 0→1→2. That proves useful detector stability for this build, **not** complete Security coverage: attachment was late and final 4663 status was partial, with late_attachment, clock_changed, run_boundary_unknown, result_limit, zero stored confirmed rows and 24 stored ambiguous rows. No private raw Security XML was retained in the supplied capture.

## 2. Provenance and limits

### 2.1 Repositories and revisions inspected

| Component | HEAD inspected | State at investigation | Primary source |
| --- | --- | --- | --- |
| Validator | 21c943216087e3f752a27af496c353d43ea85a85, main | Clean | F:/Python/BonkScanner_validator |
| Original Scanner | c955c68daafbedbbd3f07e9aa8afbb1bee3a2453, live-validator | Pre-existing untracked task prompts only | F:/Python/BonkScanner |
| Validator server | 904c3940c791afd1c57fc1432a0aa43914989441, main | Clean | F:/Python/BonkScanner_validator_server |
| Shared docs | 7ec676f14f9b11f12f2b07742954ae0e3b844032, main | Pre-existing modification to development/game_lab.md | F:/Python/BonkScanner/docs |

Read AGENTS.md from Validator, Scanner and docs, and docs/README.md plus docs/validator/README.md. The relevant scope of docs/updates/functional_updates.md, lines 43–83 and 125–184, is an opt-in, bounded local Security 4663 finish diagnostic; requested rights (ETW), held rights (Census), and exercised rights (4663) are distinct. No extra sensor or privileged persistent service is within this task. Cross-checked docs/validator/lenient_assessment_and_catalogue_policy.md, notably lines 3–26 and 64–86: the design requires critical Security integrity and honest boundaries, not invented evidence or a 4663 uptime percentage. This dated policy document is not itself proof of deployment; server v4 source currently contains relevant implementation and must be reconciled by agent 07.

CodeGraph was attempted first but **not indexed** for bonkscanner_validator ("CodeGraph index is not present for this project"). Read-only PowerShell source inspection was used instead. No live local Codex or tests used.

### 2.2 Evidence examined

Primary capture: F:/Python/BonkScanner/.local/validator-start-trace/retest-kit/captures/session-20261117-093004-1afdfe/

- FINAL_REAL_STAGE_REVIEW_2026-11-17.md (human review, qualified acceptance).
- metadata.json (07:30:04.361 UTC / QPC pair; Scanner c955c68, Validator 21c9432).
- manual.jsonl (four independent UTC/QPC operator markers).
- summary.json, RESULTS.md, manifest.json (poll counts, scenario, file provenance).
- validator-18452-005877f2cb7940fb8e82ac846cb0884a.jsonl (indexed event sequence numbers cited below; approximately 20 MB).
- scanner-26764.jsonl (recording and activity context; timestamps are QPC).
- Earlier capture F:/Python/BonkScanner/.local/validator-start-trace/retest-kit/captures/session-20261117-080026-ba7a2e/: QA_DIRECT_GAME_LAB_INTERIM_2026-11-17.md and validator-18420-f05734986a514c13807bad9437b2727f.jsonl. These refer to Scanner c42346b, Validator 21c9432 and MegaBonk 1.0.69/GameAssembly SHA-256 4350a7ae25ba7aec35677c213fdceabbb638676bb00ab59131d7d9c37b6e3d9e. A previous report says 286 Validator tests plus 33 subtests, 31 Scanner tests and 106 server subset tests passed under that earlier environment; **none was rerun here**.

Additionally read existing Windows event logs via Get-WinEvent, limited to 2026-11-17 09:28–09:45 local, then 09:32:50–09:33:10, selecting System and Microsoft-Windows-Time-Service/Operational. These are independent system records, not previously saved members of the capture archive. Record IDs are supplied for future confirmation; event retention is outside the capture's control.

### 2.3 Missing evidence / nonclaims

The trace does **not** save the paired UTC/QPC samples made by _begin, _sample_audit or _finish; the instant an issue is appended; the audit span array at freeze; actual Security 4663 XML, event UTC/record IDs and numeric handles; the full number of rows beyond the 24-row limit; the precise queue wait per task; independent elevated SACL/policy restoration readback; exact ETW/Security activation instant; or a raw Boss Room identity flag. Startup audit_setup_observed is an *armed acknowledgement*, not a measured activation time (trace event 15). The existing monitor is on a user-controlled machine; source observations alone cannot attest a clean client or prove that an unfamiliar process modified memory.

## 3. Reconstructed clocks: conclusive step and a retrospective timestamp trap

### 3.1 Two independent clock domains

Windows Security XML TimeCreated is **UTC system time**; security_audit.py lines 31–42 parse ISO UTC into Unix epoch nanoseconds. The Windows FILETIME representation counts 100 ns since 1601-01-01 UTC; subtract 116444736000000000 ticks and multiply by 100 to obtain Unix epoch nanoseconds (direct_open.py lines 122–126; rights_correlation.py lines 20–46 and 95–110). The source creation FILETIME is an identity/lifetime fact, not a monotonic elapsed-time clock.

ETW kernel event timestamps are **QPC ticks**, calibrated via QueryPerformanceCounter/Frequency and perf_counter, not UTC timestamps (direct_open.py lines 172–192 and 274–293). ETW groups and offsets use this QPC domain. The engine's run.origin and capturedThroughMs use self.clock / time.monotonic, commented as GetTickCount64 on the supported Python/Windows runtime, while ETW uses self._access_clock / time.perf_counter (engine.py lines 92–95 and 215). These elapsed-time sources must not be silently treated as identical UTC origins. QPC values from different Windows boots are incomparable; the capture's metadata and manifest explicitly warn about this.

The current rights correlation computes an ETW-origin UTC mapping as round(origin_qpc_s × 1e9) + initial (wall_minus_qpc_ns) in rights_correlation.py lines 36–42. This assumes that one UTC-minus-QPC offset is valid for the entire run. After a genuine UTC step, any post-step event positioned through that *pre-step* mapping may be misaligned by ~2.318 s. Security rows are conservatively unbound after the clock-change latch, so do not try to recover attribution by naively reusing that mapping.

### 3.2 Capture's measured offset residuals

Use metadata.json as the initial anchor (QPC 35459371560800 ns, UTC 07:30:04.361); compare each saved manual UTC/QPC pair in the **same Windows boot**. The columns below show the additional UTC-minus-QPC offset relative to that initial anchor (rounding of recorded UTC to milliseconds gives approximately ±1 ms precision).

| Source | Recorded UTC, 2026-11-17 | perf_counter_ns | Relative UTC−QPC residual |
| --- | --- | ---: | ---: |
| metadata.json | 07:30:04.361 | 35459371560800 | 0 ms, reference |
| manual.jsonl, scenario_selected | 07:30:44.295 | 35499306185900 | -0.625 ms |
| manual.jsonl, operator_native_stage_transition_pending | 07:30:44.451 | 35499462639100 | -1.078 ms |
| manual.jsonl, final_boss_killed_reported_by_user... | 07:39:03.857 | 35996549950000 | **+2317.611 ms** |
| manual.jsonl, user_finished_game_main_menu... | 07:43:49.880 | 36282572840100 | **+2317.721 ms** |

This independently pins a persistent offset change between the early and late markers. It alone cannot distinguish a step from an accumulated slew; **the independent Windows events do**:

- System / Microsoft-Windows-Kernel-General: **Event ID 1, Record ID 198240, 09:33:00.361+02:00**: UTC went from 07:32:58.042388300 to 07:33:00.361363600, Time Delta 2318 ms, svchost.exe PID 15676.
- System / Microsoft-Windows-Time-Service: **ID 37 / Record 198238 at 09:32:58.041**, NtpClient received valid time data; **ID 35 / Record 198241 at 09:33:00.362**, synchronized to time.windows.com.
- Microsoft-Windows-Time-Service/Operational: **ID 261 / Record 18122**, system time set at 09:33:00.361; **ID 265 / Record 18124**, time source synchronized; System Tick Count **35633031 ms** (about QPC 35633.031 s at this boot).

The detected change is not evidence of user cheating, game stage behavior or an audit-policy modification. The precise causal mechanism is a Windows time synchronization step, independently recorded by Windows. Whether a given clock-change should forever preclude a favorable assessment is a **coverage policy question**; it cannot be made safe by suppressing the reason.

**Timestamp trap:** the existing FINAL_REAL_STAGE_REVIEW chronology translates many validator QPC positions using the initial metadata UTC anchor. After the 09:33 jump, that extrapolation is ~2.318 seconds **earlier** than real wall UTC; the later manual marker already uses adjusted UTC. For example the review labels finalization_begin about 09:39:21.090, while its QPC 36016102022600 aligned to the post-step manual marker corresponds to approximately **09:39:23.409 local**. The relative QPC ordering/durations remain correct. Agents 04/05/07 must use event sequence + same-boot QPC for ordering and piecewise UTC anchors for wall times, not mix the two. Approximate post-step wall times in this report are derived from the rounded manual marker and are not a second independent log.

### 3.3 Sensor around the step

Windows Time-Service reported system tick 35633031 ms. Trace event **5805**, QPC 35633020659200, is a fresh **run** sample with sensor_ok=true, stage_index=0 and run_config=3140710084112. The next fresh sample, event **5810**, QPC 35633130388600, is also valid **run** with the same identity. Hence the time correction happened between ordinary healthy polls, not during a detected map transition or observed run restart. Given the 100–110 ms sensor cadence and 50 ms offset threshold, event 5810 is the **first plausible post-step _sample_audit invocation** that could latch clock_changed. This is an inference; the trace has no audit_clock_sample/audit_issue_added event to prove the exact mutation.

The comparison is with the run-start baseline, so once the +2.318 s step has occurred, every subsequent coherent sample would violate the threshold. No evidence shows a later return of UTC/QPC offset to its original value.

## 4. Attach → context changes → freeze → query → final result

The primary trace is indexed by the **sequence** field; line number in the unmodified JSONL equals sequence for the cited events. QPC is monotonic within this boot.

| Sequence | perf_counter_ns / action | Established observation |
| --- | --- | --- |
| 5 | 35482266656400, game_attached | Game PID 15492 attached; one attachment generation; process creation UTC 05:43:01.899936Z. |
| 12 → 15 | 35482272724900 → 35482459525600 | Security setup requested then **armed ACK**; armed_at_utc_ns 1794900627449578700, precise activation unknown. |
| 48 | 35483333065300 | First ETW healthy observation, precise activation unknown. |
| 61 → 62 | 35483659583700 → 35483660070900 | Candidate confirmed, then one run_start with attachment **attached_mid_run**, localRunId b559f571-ff61-4e9a-b71a-bc002e193717. The game timer was already ~256 s. |
| 5805 → 5810 | 35633020659200 → 35633130388600 | Healthy run samples on either side of independently observed W32Time step. |
| 12446 | 35803817458400 | Fresh run stage index 0→1; no new localRunId. |
| 12493 → 12501 → 12661 | 35804923090500 → 35805143853100 → 35809400790400 | First later loading, then idle, then reacquired valid run at stage 1. If clock_changed was already latched, _sample_audit returns before applying these bound=false transitions. |
| 14736 → 14779 → 14946 | 35863176687400 → 35864394253500 → 35868666042700 | Real stage 1→2, idle, valid run reacquired; same run ID. |
| 16601 → 16965 | 35911475926500 → 35920901815600 | Additional idle/reentry at stage index 2; Boss Room-compatible, without an independent raw boss-room flag. |
| 20613 → 20616 | 36016100392400 → 36016102022600 | First final ended sensor and finalization_begin reason=run_ended, confirmed_end=true. |
| 20618 → 20622 | 36016103533900 → 36016112939600 | ETW drain begin/end; new ETW trace starts separately while old run finalizes. |
| 20623 → 20624 | 36016116159600 → 36016116536000 | Old-run audit_finish_begin; Security delivery grace begins. |
| 20668 → 20669 | 36017371134700 → 36017371968100 | Delivery grace ends (~1.255 s after begin), Security query begins. |
| 20678 → 20679 | 36017551488500 → 36017579494800 | First *matching* 4663 record observed during final query, then query ends. This is **not** the first actual exercised-right operation time. |
| **20680** | **36017590342900** | First **observable** final audit reason list: status=partial; issues=[late_attachment, clock_changed, run_boundary_unknown, result_limit]; **0 stored confirmed rows, 24 stored ambiguous rows**. |
| 20681 → 20683 | 36017591027900 → 36017639603200 | Audit finish end, one confirmed run_end at sequence 20682, and deferred finalization end for the same old localRunId. |

Finalization_begin → audit_finish_begin is approximately **14.137 ms** in QPC. Finalization_begin → finalization_end is **1537.581 ms**, most of which includes deliberate Security delivery grace and query, not a sensor stall. The existing review records twelve fresh polls during finalization and no fresh-poll gaps >500 ms across the marked scenario (scenario median ~109 ms, maximum ~453.537 ms in extended recount). The **run-boundary identity** remained stable; Security **continuous coverage** was not established.

The initial attachment was late **by design of this test**. The code sets late_attachment when attachment != run_start_known, regardless of an earlier Security armed ACK. Do not convert that issue into a claim that the recovered segment was continuously observed from the game's actual start.

## 5. Code provenance: independent reasons and failure modes

### 5.1 Real clock step versus torn time pairs

- Validator engine.py **303–313**: _begin gets wall_clock_ns(), *then* time.perf_counter_ns(), and stores the single difference in run.audit.clock; initializes spans=[] and open=false, with late_attachment if the start was not fully known. A scheduler stall between these calls could produce an unrepresentative offset.
- engine.py **854–876**: _sample_audit gets wall then perf_counter_ns and checks abs(wall − QPC − initial_offset) > 50,000,000 ns. On failure it appends clock_changed, **clears every span**, sets open=false, and returns on all subsequent samples for the run. That is intentionally conservative for attribution but collapses all potentially sound pre-step spans into a run-level unknown.
- engine.py **1017–1053**: _finish freezes audit_end=wall_clock_ns() before trace emission, ETW cleanup and executor submission. It detaches run-specific state using _freeze_finalization (967–1015), and passes immutable audit_end through _complete_frozen/_finish_impl.
- engine.py **885–906**, specifically **900–902**: _finish_audit_impl compares **frozen audit_end** with a **fresh** perf_counter_ns taken after queue/drain delay. That is not an atomic or near-simultaneous pair. With an otherwise stable system and >50 ms elapsed, it discards spans and reports **false** clock_changed. Conversely the real 2318 ms W32Time step is independently proven here; do not claim this deferred comparison caused the captured event.
- engine.py **1333–1343**: re-arm after finalization overlap clears spans and updates audit.start, but **does not refresh audit.clock**. This can leave a stale offset for a newly armed segment. Existing issue history must not be erased blindly; anchor lifetime must be explicit.

What the source proves: a real discontinuity is detected conservatively; there is also a distinct false-positive mechanism. What the trace proves: a real +2318 ms discontinuity occurred, finalization reached audit_finish_begin within ~14 ms, and the final result has clock_changed. What remains unobserved: the first _sample_audit latch and any short scheduler stall in the two-clock read sequence. Those gaps cannot be filled from the final reason string.

### 5.2 Complete inventory of run_boundary_unknown origins

| Origin | Code | Meaning / independence |
| --- | --- | --- |
| A fresh Security audit sample is **not bound** | engine.py **854–869**, called in poll **1582–1590** | Adds run_boundary_unknown and closes current span when observing is false, game sensor is unknown/loading/idle, or the current run_config differs from the previous valid run sample. This does **not** by itself prove a new game or cheating. |
| More than 32 separated spans would be needed | engine.py **870–876** | On the 33rd new span, capacity is exhausted; appends the same issue without enrolling another span. Boundedness is intentional, but this reason conflates a representation limit with genuine run ambiguity. |
| Finish with **context_lost** | engine.py **895–900**; poll **1513–1540**, **1574–1581** | Explicitly adds run_boundary_unknown even before the Security record loop. Context-lost is an unconfirmed natural end, different from the real captured confirmed run_ended. For game_exited the code instead appends game_exited, although any unmatched row can independently add run_boundary_unknown. |
| Security query interval has start > end | security_audit.py **218–224** | Appends run_boundary_unknown and does not query that reversed interval; potentially different from loss of a game-context sample. |
| 4663 event outside every known UTC span | security_audit.py **110–155**, specifically **136–155** | In-span requires timestamp inside a span; otherwise row attribution is run_boundary_unknown and the issue is added. An empty span list makes *every* qualifying matched event unbound. This applies even if the run has a confirmed terminal end. |
| Expected late attachment | engine.py **278–333** | **Separately** adds late_attachment when the start is unknown or Security armed late. Not automatically run_boundary_unknown, and cannot prove the real pre-attachment segment. |
| Genuine sample interval >0.5 s | engine.py **1568–1573**, run_detection.py **12–16** | Main run payload opens an unknown gap, but audit span builder currently does not see this interval. This is a **latent missing attribution safeguard**, not a reliably raised Security run_boundary_unknown today. |
| run_config mutation | engine.py **1582–1590** and run_detection.py **47–71** | Can force a bound=false sample; a carefully confirmed new run instead finalizes the old session as context_lost. Do not interpret config/pointer/seed change alone as a restart. |
| Unconfirmed normal end | engine.py **1513–1524**, **483–497** | If terminal signal is not independently confirmed, _finish receives reason=context_lost, which triggers the above explicit issue. The captured run has confirmed_end=true; not the source in this case. |

Important distinction: _record classifies an **in-span foreign handle** as ambiguous/handle_lifetime_unverified, not run_boundary_unknown. Only the worker's own pinned process+handle may be confirmed by this code (security_audit.py **136–155**). rights_correlation.py **133–228** may produce bounded source matches for foreign activity, but cannot prove target-handle continuity from ETW requested rights or Census granted-right snapshots. A different process with the same executable path must remain ambiguous.

### 5.3 Interpreting the observed run's issue combination

The pre-step fresh samples are run/sensor_ok=true with stable run_config; the first non-run sensor after the confirmed start in the parsed primary trace is **sequence 12493, loading**, significantly **after** the 09:33 clock step. Thus the regular nonbound-sample route cannot be confidently named as the first origin of run_boundary_unknown here. With clock_changed latched and spans cleared, _sample_audit exits early on later loading/idle samples; _record's empty-span fallback at final query explains the reported run_boundary_unknown and all 24 stored ambiguous rows. This is the most economical code-consistent explanation, but cannot be promoted to a directly observed attribution without a span/issue mutation trace.

The final issue result_limit is **separate**: security_audit.py **19–20**, **141–155** keeps at most 24 detail rows per group, increments rowsOmitted and adds result_limit upon overflow. Therefore at least **25 qualifying ambiguous Security records** were processed in this case, not merely 24 total records. The exact total cannot be recovered from audit_final_result_observed, which logs the length of stored rows, not read/write totals or omitted count. The number 24 is **not** an event-scan limit (SCAN_LIMIT=2048, QUERY_SECONDS=0.8 in security_audit.py **17–20**, **71–107**).

In the earlier 08:00 capture under Validator **21c9432**, final audit at event **30011** in C14 contains **handle_lifetime_unverified without run_boundary_unknown** and one stored ambiguous row. Events **3117**, **9623**, **13651**, **13743**, **21385** and **34312** show several other legitimate partial combinations; **14339** shows finalization_overlap with late_attachment. These historical cases demonstrate that run_boundary_unknown is not inevitable for every foreign record or every audit and that an overlap is a separate provenance issue. They do **not** validate the proposed new timing fixes.

### 5.4 Incomplete spans and time-domain hazards

- **Missed poll overreach:** poll emits a main run gap if sample_finished − last_bound_at >0.5 s (engine.py **1568–1573**) but immediately calls _sample_audit(bound=true) (**1588–1590**). If audit.open=true, _sample_audit extends spans[-1][1] to the new wall time (**870–871**) across the unobserved interval. This is an unsafe assumption: a payload gap and a full Security span can simultaneously describe the same time. **Fix the semantic inconsistency** using a same-domain elapsed-time bound, not a larger 4663 collection rate.
- **Terminal tail:** when poll processes confirmed mode=ended/menu it calls _finish without calling _sample_audit for that sensor result (engine.py **1513–1524**); the last Security span may stop at an earlier fresh bound sample. Qualifying records in that tail can legitimately be unbound, even with confirmedRunEndMs present. Preserve honest tail uncertainty.
- **Stage transitions:** the real trace has loading/idle at sequences 12493/12501, 14779 and 16601, with healthy reacquisition at 12661, 14946 and 16965. Such intervals would split spans (and may append run_boundary_unknown) **if clock_changed had not already latched**. Treat their lengths and causes, not stage-index changes alone.
- **Clock reset:** when a genuine UTC step occurs, a single pre-step wall−QPC origin cannot safely align post-step Security TimeCreated with ETW QPC offsets or source-lifetime timestamps near the step. Preserve a time-alignment warning and do not silently extrapolate beyond a validated anchor segment.
- **Bounds:** no query can establish the actual beginning of an already-playing game. A 1.25 s delayed query completion is not a 1.25 s shift of the game-end boundary: the start/end interval is frozen before query, but the current implementation incorrectly checks that frozen wall time against delayed QPC.

## 6. Minimal proposed changes (no implementation in this task)

### P0.1 Coherent clock pairs on begin, every audit-bound sample, and freeze

Implement a tiny shared, opt-in-local timing helper that samples **QPC-before, precise-UTC-FILETIME, QPC-after** (all in the same thread, as closely together as possible). Use time.perf_counter_ns and the existing wall_clock_ns/GetSystemTimePreciseAsFileTime; no new dependency, hook, sensor, elevation or system clock modification. Store midpoint or, preferably, the **interval of possible wall−QPC offsets** [UTC − QPC_after, UTC − QPC_before], plus bracket width. Reject or retry unusually wide brackets; never label a descheduled sample as a proven clock jump. Track baseline and new offset confidence intervals; report clock_changed only when a real offset disagreement beyond the existing meaningful policy tolerance is supported by sufficiently tight pairs. A gradual correction is judged against the historical baseline and measured drift, not just adjacent samples. **Do not solve this by deleting clock_changed or arbitrarily increasing 50 ms.**

Owners: engine._begin, engine._sample_audit, engine._finish; low-level helper can live next to security_audit.wall_clock_ns. Keep UTC and QPC alongside one another on every run boundary, and associate the pair with the old run before freeze.

**Invariant:** any comparison of a UTC timestamp with QPC uses a near-synchronous measured pair, with explicit uncertainty. A true Windows time step of +2318 ms still produces a clock_changed integrity reason; 200 ms of executor delay with stable clocks does not.

### P0.2 Finish uses the frozen pair, not a deferred QPC read

Freeze the complete (end_utc_ns, end_qpc_ns/bracket, uncertainty) observation in _finish. Thread that immutable value through _freeze_finalization, _complete_frozen, _finish_impl and _finish_audit_impl. Remove the comparison of frozen end UTC to current finalizer QPC at engine.py line 900. The finalizer may separately sample *its own* coherent pair for diagnostics but may not retroactively treat queue residence as clock drift. Restore/recovery ownership remains the frozen run's; never block the fresh game sensor for the Security delivery grace.

**Invariant:** intentional queue pauses, ETW drain and 1.25 s Security grace cannot alone generate clock_changed; the initial and terminal anchor pairs determine the measured clock integrity of the run.

### P0.3 Couple audit span continuation to actual fresh coverage

Pass a monotonic/QPC fresh-sample timestamp and the **actual sensor-bound predecessor** to _sample_audit, not merely bound=true. On any fresh-to-fresh interval beyond MAX_RUN_SAMPLE_GAP_SECONDS or any explicit unknown/loading/config transition, close the preceding span, mark the interval as unbound, and append a bounded new span only after fresh binding resumes. Reuse the existing run-gap threshold and semantics from poll, with a documented choice of the corresponding monotonic clock; do not infer continuous Security coverage over missing data. Do not convert a stage change itself into a new run. Preserve a cap (currently 32 spans); distinguish span-cap exhaustion from game-context loss in **local diagnostics** for integrator review without adding a new public reason automatically.

**Invariant:** an interval acknowledged as a physical run-observation gap cannot be covered by a continuous Security attribution span; truthful out-of-span events remain ambiguous.

### P0.4 Anchor lifetime and correlation fail-closed

When audit.start is reset on re-arm at engine.py **1338–1343**, refresh its coherent offset anchor for that **new armed segment**, while retaining prior coverage/clock integrity issues and an explicit break in continuity. For the current single-origin correlation implementation, make an explicit fail-closed guard: if a real clock discontinuity makes the QPC→UTC origin invalid, do not time-join foreign Security rows to ETW/direct-open offsets across the step. Return partial/unmatched evidence (or rely on completely unbound spans, as today) rather than apparently exact first-use attribution. Any future post-step recovery requires **piecewise UTC/QPC mappings**, per-segment coverage and an explicit unknown transition interval; this is a separate policy/design decision, not a quick P0 extension.

**Invariant:** no unverified UTC/QPC conversion ever upgrades a foreign handle or ambiguous Security 4663 event to a confirmed target-lifetime fact.

### P0.5 Add bounded diagnostic provenance

Emit opt-in trace events **at the actual issue mutation** and at begin/finish clock-pair capture: run ID, phase (begin/sample/rearm/freeze/finalizer), reason, bracket width, offset residual/range, QPC, bound, previous gap, active span count and issue origin. Sample recurring healthy probes sparsely, but always record the **first crossing** and the first unbound/cap event, without raw 4663 XML, process-private paths, secrets or unbounded per-poll logs. Preserve separate counts of matched/retained/omitted rows at final summary so event 20680 no longer hides the underlying record total. Any new wire reason/field requires agent 07 review; local diagnostics should be the first step.

**Invariant:** a future capture can distinguish Windows step, slow slew, scheduler jitter, delayed finalizer, initial late attachment, nonbound sensor interval, span limit and query record fallback without guessing from one combined reason string.

### Cost, trust and scope decision

Threat addressed: incorrect use-attribution/false quality results from torn clocks and over-credited observation spans; **not** an additional malware or cheating detector. Existing ETW requested capabilities, Census snapshots, Security used-rights, module and file checks remain independent with their documented limitations. Marginal value: much lower false-positive clock_changed from finalization, more faithful Security gaps and less risk of false source/time matching. Cost: constant work for two extra perf-counter reads per bounded audit clock sample and a few in-memory fields/trace events, with no persistent service, new Windows privileges, extra census frequency, game hook, or raw event export. Treat as a **core reliability correction**. All evidence still comes from a user-controlled client, never remote attestation or automatic proof of cheating. P0.4 piecewise continuity/recovery beyond fail-closed is **deferred for evidence and policy agreement**, not an automatic expansion.

## 7. Interfaces for parallel agents / integrator

- **02 — Security collection and row classification:** keep the distinction between *record count*, stored 24-row sample and omitted records; preserve in-span own pinned reader versus in-span foreign handle versus out-of-span Security event. Supply a pure test for empty spans after clock jump, a 33rd span, and zero/short trailing interval. Never infer exact target from one executable path, PID, numeric handle or ETW/Census snapshots.
- **04 — Lifecycle/frozen finalization:** own the immutable end pair and its transfer to the executor; keep original localRunId, old recovery owner and restoration serialization, fast current sensor and bounded queue. Do not reacquire wall/QPC using one end from an older run and QPC from the new run. Re-arm must refresh timing anchor without retroactively filling old Security gaps.
- **05 — Run boundaries:** expose the validated known/mid-run start and confirmed/unconfirmed end, plus loading/idle and real physical sample-gap signals, to audit span builder. Stage 0→1→2, boss reentry and pointer/seed variation are not independent new-run signals. Do not equate confirmed terminal *game* boundary with complete *Security* event attribution.
- **06 — Polling (relevant dependency):** preserve measured fresh poll intervals, including >500 ms gaps, and a bounded miss reason. Align Security span closure to actual missed-interval semantics. An executor delay should not stall sensor polling.
- **07 — Wire/server assessment:** audit_summary in Validator src/bonkscanner_validator/run_diagnostics.py **77–100** marks clock_changed and result_limit as fatal for queryCompleted. run_boundary_unknown is not in that local fatal set (queryCompleted is a query-status property, not a claim of full run coverage). At server HEAD, sessions/assessment_quality.py **21–26, 107–138** treats **clock_changed, result_limit and run_boundary_unknown** as critical Security-quality issues; lines **147–162** separately assess game start/end/gaps. Therefore retained reason propagation must not silently grant full/qualified green or collapse genuine clock integrity into mere unknown-process catalogue context. Existing v4 source/tests (sessions/tests/test_assessment_v4.py **58–109**) exist, but no claim is made about deployed rule/version selection. Resolve the dated design-document status separately.
- **03 — Recovery (indirect dependency):** W32Time adjusting host UTC is neither a SACL change nor policy_changed. Preserve recovery verification and journal-gap semantics. Do not diagnose SACL restoration from an audit setup ACK.
- **Integrator:** use source revision pins above; treat human-review wall timestamps after 09:33 as potentially derived from stale baseline. Use sequence/QPC for chronological checks and the event-log record plus post-step anchor for UTC reconstruction.

## 8. Deferred regression and acceptance matrix

**Every item below: NOT TESTED during this investigation.** Previous historical QA is noted in section 2, under its own revisions and conditions. "Windows/UAC/Game/Server" flags specify *requirements for the deferred check*, not what was run here. Stub/mock tests may run on a non-Windows test host where appropriate.

| ID / status | Goal and input conditions | Expected result; explicit failure criterion | Windows / UAC / Game / Server |
| --- | --- | --- | --- |
| T01 **NOT TESTED** | Stable UTC/QPC pairs with injected 0–2 ms bracket latency, one known start and confirmed end; no Security rows. | No clock_changed; coherent nonempty spans bounded by actual samples. **Fail** if source reports changed clock or invents full pre-attachment coverage. | No / No / No / No |
| T02 **NOT TESTED** | Stable UTC offset but pause executor for 60, 250 and 1600 ms between freeze and _finish_audit_impl, and inject ~200 ms ETW drain delay. | Same frozen end UTC/QPC pair used; no false clock_changed; old ID remains on result, polling does not wait for grace. **Fail** if queued duration itself changes integrity or stalls new-run sensor. | No / No / No / No |
| T03 **NOT TESTED** | Simulate wall-clock sampling preemption by 80–250 ms *inside* QPC-before/UTC/QPC-after; true UTC offset stable. | Wide bracket is recognized as uncertain/retried, not a proven real jump; no false exact timestamp. **Fail** if one torn sample triggers clock_changed without evidence or silently credits coverage. | No / No / No / No |
| T04 **NOT TESTED** | Simulate smooth gradual clock correction of +5 ms/min and +10 ms/min and realistic scheduler jitter, using coherent samples over long runs. | Baseline drift retained, threshold crossing diagnosed by reliable interval comparison, no arbitrarily raised threshold; uncertainty distinguished from step. **Fail** if drift silently disappears from time integrity or jitter mimics a proven jump. | No / No / No / No |
| T05 **NOT TESTED** | Synthetic abrupt forward +2318 ms and backward -2318 ms between two fresh valid samples, with known run origin. | clock_changed recorded with event phase and explicit affected segments; no cross-step foreign-handle time join; no green full Security. **Fail** if reason suppressed, time aligned through single stale offset, or post-step rows falsely confirmed. | No / No / No / No |
| T06 **NOT TESTED** | Replay of **saved** System ID 1/Time-Service event data into a pure clock classifier and the metadata/manual pairs of primary capture; no actual Windows time change. | Detects the 2318 ms forward-step and can explain the +2317.6 ms stored offset residual. **Fail** if classified only as stage loading or executor delay. | No / No / No / No |
| T07 **NOT TESTED** | Stable UTC/QPC, fresh bound samples separated by 499 ms then 501/900 ms, including a paused game and resume. | At 499 ms, follow documented continuity rule; over 500 ms, open a genuine Security unbound interval and mark run-level gap even if both endpoint samples are valid. **Fail** if span bridges an >500 ms unknown interval. | No / No / No / No |
| T08 **NOT TESTED** | 31, 32, 33+ alternations of bound/unbound at stable time, followed by qualifying own-reader and foreign 4663 fixtures inside/outside spans. | Capacity bounded, truncation distinguishable, no fabricated 33rd known span; own pinned reader only confirmed when in-span, foreign handle always ambiguous. **Fail** if coverage silently rolls through cap or out-of-span row gets confirmed. | No / No / No / No |
| T09 **NOT TESTED** | Late attach, run_config change, loading/idle, stage 0→1→2, same-stage Boss Room-compatible idle, transient unknown, then confirmed end. | Exactly one run ID for native stage transitions; separate late_attachment, real Security gaps and confirmedRunEndMs; no fake restart. **Fail** if stage change restarts run or unknown spans become green. Real-game analogue: 09:30 capture, Validator 21c9432, Scanner c955c68; new implementation still requires fresh acceptance. | Yes / Yes / Yes / No |
| T10 **NOT TESTED** | Context_lost restart before natural end, game_exited, observer_stopped and terminal sample after last bound by >0.5 s. | Distinct finish reasons; no false confirmed end; restoration stays with old recovery; gap and issue provenance retained. **Fail** if one unconfirmed boundary gets a completed fully-bound Security report. | Source-only: No / No / No / No; native follow-up: Yes / Yes / Yes / No |
| T11 **NOT TESTED** | Consecutive fast runs while old Security grace/query is active, then rearm after restoration; inject clock step between runs. | Old run frozen clock pair and localRunId stable; next run rearm gets fresh coherent timing baseline and finalization_overlap/late_attachment where applicable; no audit state cross-contamination. **Fail** if old pair is compared to new-run perf or new session retroactively claims old gap. | No / No / No / No; Windows acceptance Yes / Yes / Yes / No |
| T12 **NOT TESTED** | Owned Windows Security 4663 stand; >24 qualifying rows, two same-path target processes, own pinned reader and foreign handles, deadline/journal gap/cancel cases. | Accurate total vs stored vs omitted counts, result_limit preserved, ambiguous attribution conservative, recovery policy/SACL read back independently. **Fail** if truncation becomes clean, private raw rows exported, or settings not restored. | Yes / Yes / No (owned processes) / No |
| T13 **NOT TESTED** | Server v3/v4 fixture with accepted Security clock_changed, result_limit, run_boundary_unknown, known/late attachment and both confirmed/unconfirmed ends; replay version-pinned rules. | Private quality remains critical/inconclusive for integrity failures; no favorable full/qualified status; positive independent file finding survives. **Fail** if lost issue or an unknown requested-right process becomes an accusation. | No / No / No / Yes (fixtures or Django service) |
| T14 **NOT TESTED** | End-to-end supported MegaBonk 1.0.69, normal Windows UAC, source or matching packaged Scanner/Validator build, real stage transitions, active Security, final ACK and independent recovery setting readback. | One confirmed run, clock diagnostics and query summary consistent with actual Windows time behavior, accurate gap provenance, no sensor stall; Security remains partial if real clock discontinuity or record limit persists. **Fail** on invented full coverage, unaccounted queue loss, missing run_end/ACK or failed restoration. | Yes / Yes / Yes / Yes |
| T15 **NOT TESTED** | Synthetic within-grace UTC step just before/after freeze and independently during delayed query, with forward/backward cases. | No comparison of stale wall to delayed QPC; event ordering and query filter remain conservative; any genuinely affected historical window is explicitly uncertain. **Fail** if old timestamps are silently remapped using a later UTC anchor or if queue delay is mistaken for clock step. | No / No / No / No |

**Do not change the real machine's system time as a test in this task.** Synthetic offset injection and saved event logs suffice for source-level regressions. Any future physical Windows time-change test requires a separate explicit safety decision; elevated owned-process Security tests likewise require a planned acceptance window.

## 9. Integration decision and explicit open questions

**Confirmed and directly supported:** real +2318 ms Windows Time step at 09:33; ~+2317.6 ms UTC/QPC residual in saved markers; coherent game run across stage transitions; terminal Security partial with four named reasons; no >500 ms observed sensor gap in the primary scenario; old-run finalization remained asynchronous; currently unsafe frozen-wall/current-QPC finish check; currently unbounded-in-time span extension across >500 ms missed sample in source.

**Expected limitations, not bugs by themselves:** attached_mid_run, finite row sample cap (with truthful result_limit), 32-span bound when flagged, foreign-handle-lifetime ambiguity, Security 4663 recording semantics, terminal tail uncertainty, and inability to prove 100% collection from an armed ACK.

**Open pending new instrumentation or acceptance:** the exact first _sample_audit clock_changed mutation (no pair log), whether any additional unrelated timing preemption occurred, raw 4663 timestamps/sources/count beyond 24, individual span start/stop times at freeze, independent post-run restoration, exact boss-room flag, behavior on diverse Windows versions/suspends, whether piecewise post-step rebinding can be shown safe under the v3 contract, and currently deployed server assessment-version selection.

**Recommended integrator order:** (1) P0 coherent/frozen clock pairs and origin logging; (2) physical-gap-aware Security spans; (3) source fixtures for clock step versus delayed finalization and >500 ms gaps; (4) 02/04/05/06 ownership reconciliation; (5) 07 wire/quality fixture; (6) explicitly authorized Windows/UAC/game/server acceptance. Do not ship a "clock_changed removed" patch or classify the 09:33 correction as proof of cheating. Do not equate successful local QA with deployed protection.
