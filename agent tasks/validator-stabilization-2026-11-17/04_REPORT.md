# 04 — Scanner/Validator lifecycle, IPC tail, run overlap and cleanup

Date: 2026-11-17
Disposition: Static controller state-machine race CONFIRMED; observed real-game Stopping symptom CORROBORATED but its exact execution path remains OPEN. Read-only analysis; NO tests, replay, game, Scanner, Validator, ETW, UAC, server or system configuration were started or changed.

## 1. Scope, revisions, source inventory

The scope follows F:/Python/BonkScanner/docs/updates/functional_updates.md:43-84,125-176 and the repositories' AGENTS.md files. The agreed pilot uses an ordinary Scanner process to own the sender and session keys and a separately elevated worker to own read-only observations and temporary Security audit settings. Missing evidence must remain unknown/partial; only a confirmed end with server-accepted final evidence may support a completed report. No new sensors, hooks, required services or mandatory dependencies are proposed.

Repository HEAD and pre-existing working tree:
- Scanner, F:/Python/BonkScanner: branch live-validator; HEAD c955c68daafbedbbd3f07e9aa8afbb1bee3a2453; upstream ahead 1, behind 0; eight pre-existing untracked task prompts. No tracked Scanner source modifications.
- Validator, F:/Python/BonkScanner_validator: branch main; HEAD 21c943216087e3f752a27af496c353d43ea85a85; upstream ahead 3, behind 0; clean.
- Independent docs checkout F:/Python/BonkScanner/docs: branch main; HEAD 7ec676f14f9b11f12f2b07742954ae0e3b844032, ahead 3; pre-existing modified development/game_lab.md was not touched.

Inspected implementation (line references refer to the above revisions):
- Validator src/bonkscanner_validator/controller.py:15-133,145-209,230-278,280-398; worker.py:25-179,182-299,326-498; ipc.py:164-219,235-288; transport.py:162-253,325-382,435-475,477-627,662-693; engine.py:111-135,300-324,830-844,878-1053,1055-1143,1329-1354,1702-1734; security_audit.py:158-248; launcher.py:195-250; direct_open.py:129-162.
- Scanner src/ui/validator.py:30-47,108-144,235-248,269-369,464-564; src/app/validator.py:1-14; src/app/runtime.py:241-308,321-430; src/app/shutdown.py:10-59; src/gui_app.py:1107-1153,1362-1423.
- Existing tests reviewed, NOT rerun: Validator tests/test_validator_controller.py:12-37,123-239; test_validator_worker.py:78-167,233-319; test_validator_ipc.py (bounded IPC and peer validation cases); test_nonblocking_finalization.py:21-110; test_deferred_controller_delivery.py:28-75. Scanner src/tests/test_validator_ui.py:15-56,100-144,218-239; test_validator_shutdown_ui.py:33-95; test_validator_integration.py:11-88; test_app_runtime.py:186-274.
- CodeGraph was queried first for both repositories. The Validator CodeGraph index is unavailable ("CodeGraph index is not present for this project"); read-only MCP PowerShell source inspection was used instead. The workspace_read endpoint returned an empty object for the existing prompt; read-only MCP shell confirmed its content.

Saved evidence (inspected, not modified):
A. F:/Python/BonkScanner/.local/validator-start-trace/retest-kit/captures/session-20261117-093004-1afdfe/: metadata.json, manifest.json, summary.json, RESULTS.md, FINAL_REAL_STAGE_REVIEW_2026-11-17.md, manual.jsonl, scanner-26764.jsonl, validator-18452-005877f2cb7940fb8e82ac846cb0884a.jsonl. Capture revisions: Scanner c955c68daafb and Validator 21c943216087; real MegaBonk 1.0.69 stage/boss playthrough.
B. F:/Python/BonkScanner/.local/validator-start-trace/retest-kit/captures/session-20261117-080026-ba7a2e/: metadata.json, QA_DIRECT_GAME_LAB_INTERIM_2026-11-17.md, C05_direct_restart_during_finalization_r1.json, scanner-19788.jsonl, validator-18420-f05734986a514c13807bad9437b2727f.jsonl. Capture revisions: Scanner c42346b7d235 and Validator 21c943216087. The C05 attempt was inconclusive as full successful acceptance because of an unplanned game death.
Times below are UTC, reconstructed against each capture's own metadata.started_utc and metadata.started_perf_counter_ns. Never compare raw perf_counter_ns values between Windows boots.

## 2. Confirmed and open findings

### F1. A stale Stopping state is a source-proven race; root cause of the specific 11-second incident is not yet proven

Scanner ValidatorTab._disable calls controller.disable(timeout=0) and immediately refreshes (src/ui/validator.py:245-247). The controller requests stop, makes zero-budget thread joins and writes state=stopping if either observer or sender is alive (controller.py:380-395). In _observe finally, stop_requested is read ONCE before worker.stop and before notifying observer_done (controller.py:112-125); only if that earlier value was true does _observe change state to disabled (lines 126-133). The _send thread continues transport tick/close and has no terminal state publication (lines 326-340).

Legal race: observer enters finally (for example UAC rejection, failure or observed worker end) with stop_requested=False; GUI then calls disable(timeout=0), sets stop and state=stopping; observer continues, skips its conditional disabled transition; sender closes and exits without changing state. Both threads can now be dead, snapshot.busy=False, but controller.state remains stopping. This is a genuine state-machine hole derived from the code; the precise interleaving was NOT reproduced in a newly run test.

Opposite legal race: observer publishes disabled when it finishes local cleanup even while sender is still inside its 3-second close/drain. GUI paints Off from state immediately rather than waiting for busy=False; the displayed status can therefore promise cleanup prematurely. The correct criterion is not worker-PID disappearance, nor merely reader exit.

Snapshot.enabled is reader_alive AND not stop.is_set; snapshot.busy is only reader/sender thread liveness (controller.py:349-359). The UI makes Enable visible when enabled=False and clickable when busy=False (src/ui/validator.py:344-352). Thus stale Stopping plus busy=False can expose an actionable Enable beside an incorrect Stopping header. The 250 ms Qt timer tries nonblocking snapshots; failed lock acquisition returns None and preserves the old paint (src/ui/validator.py:140-144,279-286 and controller.py:345-378). Contention is a possible contributor but not independently shown to persist for 11 seconds.

The real-game review FINAL_REAL_STAGE_REVIEW_2026-11-17.md, section "UI Stop issue observed", records at least 11 seconds of Validator · Stopping AFTER elevated worker children disappeared. Raw worker validator-18452-*.jsonl:30728-30733 shows ETW stop and a no-active-run observer_stopped finalization between 07:44:04.280 and 07:44:04.287 UTC. Scanner scanner-26764.jsonl:886 shows trace_shutdown at 07:45:59.912 UTC. THESE ARE NOT a complete timestamped GUI Stop-to-Off chain. There are no controller.disable, observer-finally, sender close, GUI snapshot/paint or independent worker-PID exit records in the captured JSONLs. Therefore the exact cause/duration of the observed 11-second symptom remains OPEN: a stuck live cleanup owner, stale terminal state, skipped GUI refreshes, or a combination. Do not claim the source race alone explains it.

### F2. C05 verifies old-run ownership under overlap, with strict acceptance limits

Worker validator-18420-*.jsonl:13573 (06:08:00.754 UTC) begins finalization of old run e06ec6f2-3dbf-47d5-9c0b-e10e4d013071 with reason context_lost. Line 13577 starts new run df66a719-ad64-4eb5-8bcb-c750a24b72da at the same moment. Old run_end retains e06ec6f2-... at line 13653 (06:08:02.200 UTC), and the old finalizer ends at line 13654 (06:08:02.264 UTC). New audit setup is only observed afterward at line 13656 (06:08:02.407 UTC). Lines 13666-13670 show the next overlap (old df66... finalization, new e0c0f107-40da-4195-b519-a270a3596148); old df66... terminal at 13745 (06:08:03.973 UTC), finalization at 13746 and subsequent audit arm at 13748. Thus the old end appears after a new start and retains its old ID.

Engine._freeze_finalization detaches old run-specific ETW/Security owners and prepares a fresh owner for the next run (engine.py:967-1015). _collect_finalizations delivers completed futures in submission order under original IDs (921-942); Security rearm is deferred until old finalizers have completed (830-837,1329-1343). The subsequent audit is marked finalization_overlap/late_attachment rather than clean (engine.py:300-322). Each DirectOpenTrace has a UUID-based ETW session name (direct_open.py:129-142), but the captures do NOT enumerate simultaneously live ETW sessions, so independent ETW ownership/cleanup is still an acceptance check. Controller._event retains separate tracked IDs, routes old run_end and late payload to the old session, and only updates the current UI from the current ID (controller.py:149-204). Source-level tests cover these behaviors (test_nonblocking_finalization.py:21-101 and test_deferred_controller_delivery.py:28-75).

QA_DIRECT_GAME_LAB_INTERIM_2026-11-17.md reports 11,13,12 fresh sensor polls inside the three C05 finalization windows and partial Security status. C05_direct_restart_during_finalization_r1.json shows status stopped_on_failure: game died unexpectedly and the scripted exit-to-menu action could not execute. Old ID routing and continuing polling are observed on those builds, but clean repeated C05 acceptance, native SACL restoration, IPC ACK receipt, and server ACK receipt are NOT proven. A worker run_end trace is not an ACK from the Scanner or its server.

### F3. Stop has independent IPC, collector and network owners with separate deadlines

Expected ordering:

(1) GUI Stop -> ValidatorTab._disable -> ValidatorController.disable(timeout=0). State becomes stopping while reader/sender may remain live. No GUI-thread networking or blocking join is intended.

(2) _observe stops polling; WorkerClient.stop(timeout=2) sends stop, collects a finite tail of event frames, ACKs each by sequence, optionally receives ready(stopped=True) plus skipped diagnostic counters, and then closes handles (worker.py:139-179; ipc.py:235-272). WorkerClient.stop catches ALL exceptions during this loop and silently ignores them at worker.py:165-166; closed handles and status disabled therefore do NOT prove the last run_end, its ACK or child exit.

(3) Elevated worker serve.io_loop sees stop and sets drain_requested, waits at most 1 second for tail_ready, then transmits frames/receives ACKs within about a 1.75-second drain window, one credited head at a time (worker.py:381-412). Engine owner calls engine.finish(observer_stopped) and waits for frozen finalizers before tail_ready (worker.py:456-471; engine.py:1702-1719). Security finish includes a 1.25-second grace/query/restoration (security_audit.py:185-216). Worker lifetime watchdog can force-exit a dedicated process after roughly 2.25 seconds following drain/stop if cleanup stalls (worker.py:342-353,491-498): bounded lifetime, NOT a guarantee of graceful Security restoration or tail delivery.

(4) Back in controller._observe finally, any tail is routed; _interrupt(reason) finishes old deferred sessions lacking a verified terminal packet with no fabricated payload, and the current session with explicit unknown/partial gap as required; _stop and observer_done are set (controller.py:113-133,280-324).

(5) The independent _send loop ticks transport until observer_done; then it calls TransportManager.close(timeout=3) off the GUI thread (controller.py:326-340). Transport tick launches at most two daemon ValidatorNetwork jobs, with an HTTP timeout of one second per blocking operation, not an absolute whole-request deadline (transport.py:435-475,602-627). Transport.close attempts bounded delivery, snapshots unacknowledged finishes as finish_unconfirmed, notes discarded_on_close and releases queued bytes (transport.py:672-693). Transport's request-job threads are not explicitly joined by this path and are excluded from controller.busy. True server completion demands ACK, not just local finish_requested.

(6) Controller state should move from stopping to a truthful terminal state ONLY after local observer and sender cleanup; delivery outcome and native independent Security restoration must remain separate. Presently there is no unique end-of-both-threads terminal state publisher.

IPC _CreditSlot has 672 KiB primary evidence budget, 32 KiB processAccess and 24 KiB Security diagnostic budgets (worker.py:18-22,182-299); byte reservations remain until engine consumes a credited ACK. Primary overflow generates a terminal loss after accepted FIFO items, while local diagnostics may be coalesced/dropped with skip counts. Controller maps terminal loss to ipc_queue_capacity and unknown coverage (controller.py:205-248,280-324). Existing source tests cover FIFO/ACK/loss and watchdog, but not the full combined pressure + Security query + disconnected server + Stop scenario.

### F4. Bounded frozen finalizers fail closed by design; actual queue-exhaustion behavior has inadequate test coverage

Engine creates a ThreadPoolExecutor(max_workers=1) and pending deque with explicit limit=12 (engine.py:123-127). _collect_finalizations drains in FIFO submission order, emitting a terminal under the saved run ID; on future exception, it emits finalization_failed and does not create a fake successful run_end (engine.py:921-942). _complete_frozen attempts Security and access cleanup on failure (945-965). _finish checks pending count >=12 and emits finalization_capacity_exhausted then raises RuntimeError BEFORE freezing the new session (1017-1038). Executor.submit failure runs synchronous context_lost cleanup and propagates (1042-1051). Engine.close drains outstanding finalizers for resource ownership even if their terminal events cannot subsequently cross IPC (1721-1734). A worker exception/forced exit must therefore remain unconfirmed at the parent/server.

Crucially test_nonblocking_finalization.py:104-110 checks ONLY the configured numeric limit and unbounded deque shape; it does not actually populate twelve pending futures, trigger the thirteenth rejection, inject cleanup failure or prove resources were released. A real offline queue-limit case is a required regression gate, NOT TESTED.

### F5. Enable, pending UAC and app shutdown gates are bounded, but native end-to-end acceptance is pending

Controller.enable refuses reuse while reader/sender thread is alive (controller.py:44-47), then creates fresh stop/done events and two new threads (68-85). It does not wait for separate network-job threads or independently prove native recovery process exit. UAC launch uses runas with Win32 error 1223 mapped to an unapproved startup (launcher.py:195-250). Pending named-pipe accept checks cancellation (ipc.py:164-219); controller.disable requests stop for a worker still starting, without prematurely closing a connected tail pipe (controller.py:380-388; worker.py:44-97,133-137). Native Stop during pending UAC and rapid Enable-after-Stop have not been exercised here.

Scanner window close keeps Qt running, hides window, stops Validator tab polling, closes Validator on a background thread and polls completion with short Qt timers (src/gui_app.py:1362-1423; src/app/runtime.py:241-308). A shared 15-second shutdown deadline, usual 5-second Validator close budget and explicit timeout/forced-exit path exist (src/app/shutdown.py:10-46; src/app/runtime.py:347-430; src/gui_app.py:1107-1153). Qt tests in test_validator_shutdown_ui.py:33-95 use controlled doubles; they are not real elevated-worker/slow-server Windows acceptance. Transport and GUI distinguish finish_requested, finish_acknowledged, confirmed_run_end_ms, partial and finish_unconfirmed (transport.py:217-253,637-660,672-693; src/ui/validator.py:511-552). None is equivalent to mere PID disappearance.

## 3. Minimal correction / diagnosis plan — proposal only, NOT IMPLEMENTED

P0. Give the controller ONE generation-scoped terminal transition owner. Disable should request stop and set stopping while local owners are running. After observer has finished tail/interrupt and sender has returned from transport close, finalize as disabled for expected Stop/UAC cancellation, or stopped/warning for actual failure, without overwriting newer generation state. A nonblocking snapshot reconciliation can self-heal an exited generation as a defense in depth. Do not display Off while the sender is still draining; do not hold Qt or a game sensor for network flush. Do not equate terminal local cleanup with confirmed server delivery or verified native Security restoration. Touch only ValidatorController.enable,disable,_observe,_send,_snapshot and the Scanner UI display policy if needed. Preserve the explicitly incomplete transport state and existing fail-closed behavior.

Before attributing the historical 11 seconds to that race, capture a small opt-in event trail (bounded, monotonic timestamp, controller generation, localRunId and small booleans/counters only):
- Qt Stop click, state/busy on each changed render and skipped try_snapshot.
- Controller.disable requested / returned (thread alive states, timeout), observer finally entry/exit and sampled stop_requested, observer_done.
- WorkerClient.stop start/end and reason (ready.stopped ACK vs timed out/exception), tail frame/ACK/loss/skipped counts, observed process-exit status.
- Frozen finalizer queue/dequeue/failure/overflow by original run ID; old/new native ETW session identity; Security restoration result.
- Sender transport.close begin/end with pending network jobs, finish ACK vs finish_unconfirmed/discarded counts, and single terminal-state publication.

Keep observability lightweight, off hot paths, and avoid recording raw private process data. WorkerClient.stop swallowing the exact tail error should be made diagnostically visible without changing its fail-closed deadlines. Review controller.py:187-196 stop-time reason override of an already-confirmed natural run_end only against a controlled ordered test and the server contract; the current conservative downgrade is not proof of a false success.

Do not enlarge the finalizer limit without evidence. Keep one ETW/Security finalizer at a time, explicit lost coverage and protection against wrongly attaching old evidence to new runs.

Minimal-effective-protection decision: CORE reliability/evidence-integrity correction. Threat = falsely reported clean/completed status from tail, finalizer, or stop races. Existing ETW/census/Security/modules/files observe different abuse surfaces but cannot fill missing terminal evidence. Marginal gain = correct association, bounded resource cleanup, honest coverage/delivery, not a new detector. Cost = small synchronization and targeted native regression matrix; risks = teardown complexity, permissions and platform compatibility. Trust boundary remains an untrusted modifiable client; no claim of attestation.

## 4. Deferred tests for integrator — each NOT TESTED in this investigation

L1 — NOT TESTED. Offline deterministic barrier: enter _observe finally with stop_requested=False, then GUI-equivalent disable(timeout=0), finish sender close and poll snapshot. Expect stopping only while owner alive, then disabled exactly once, busy=False; FAIL if permanent stopping, early Off while sender alive or previous generation overwrites next. Windows NO, UAC NO, Game NO, Server NO.

L2 — NOT TESTED. Windows Enable -> waiting/active -> Stop -> OFF -> Enable, 5 repetitions. Expect new worker identity and fresh transport, no stale old UI/ID writes, responsive Qt and no leaked threads; FAIL on double worker, permanently busy/stopping, orphan process. Windows YES, UAC YES, Game OPTIONAL, Server NO.

L3 — NOT TESTED. Native UAC decline and Stop while UAC prompt/pipe accept pending; immediate Enable attempted during cleanup. Expect bounded cancellation, no late worker activation, next Enable only after previous owner done; FAIL on late activation, reused pipe or stuck state. Windows YES, UAC YES, Game NO, Server NO.

L4 — NOT TESTED. Close app with active worker and during frozen Security finalization. Expect Qt event loop responsive, truthful shared-deadline report, persisted history and no unreported orphan; FAIL on GUI freeze, silent forced exit or fabricated completed report. Windows YES, UAC YES, Game OPTIONAL, Server OPTIONAL.

L5 — NOT TESTED. Configure slow/disconnected/429 receiver; queue active payload and final packet; request Stop. Expect bounded local OFF and separate finish_unconfirmed/discarded_on_close when no server ACK; FAIL if green completion without ACK, unbounded GUI stop, lost delivery status. Windows OPTIONAL, UAC NO, Game NO, Server YES (controlled).

L6 — NOT TESTED. Stop during real Security 4663 delivery wait/query; separately force recovery helper failure. Expect final partial/cancelled/unknown with actual restoration result and independently elevated SACL + audit-policy readback; FAIL if missing tail becomes clean or failed restoration is reported verified. Windows YES, UAC YES, Game YES, Server NO.

L7 — NOT TESTED. Stress evidence FIFO near 672 KiB and 24 KiB audit diagnostics, Stop with delayed/failed IPC ACK. Expect FIFO ACK ordering, skipped-local counters, terminal loss after accepted prefix, no duplicated old/new terminal; FAIL on silently dropped complete coverage or orphan queue. Windows OPTIONAL, UAC OPTIONAL, Game OPTIONAL, Server NO.

L8 — NOT TESTED. 5–10 controlled C05 overlaps with verified game actions and no accidental death. Expect old run_end under OLD localRunId after new start, fresh native ETW names and stopped sessions, Security rearm only after prior restoration, current UI not overwritten, fresh ~100ms sensor polls and labeled misses. FAIL on ID collision/cross-run evidence, orphan finalizer, invented confirmed end, or polling pause linked to cleanup. Windows YES, UAC YES, Game YES, Server OPTIONAL.

L9 — NOT TESTED. Offline fixture with 12 unresolved finalizer futures; request a 13th, then release/fail/cancel and close. Expect capacity log/exception, no fabricated run_end, all owners ultimately cleaned, clear unconfirmed status; FAIL if >12 pending, silent drop, deadlock or clean report on exception. Windows NO, UAC NO, Game NO, Server NO.

L10 — NOT TESTED. Native Windows normal/forced-stop with independent before/after enumeration of worker, ETW sessions, recovery child and Security SACL/policy. Expect every native resource closed/restored or explicitly marked unknown with reason; FAIL on orphan ETW/finalizer/recovery child or inference from PID alone. Windows YES, UAC YES, Game YES, Server NO.

L11 — NOT TESTED. Deliberately hold controller/transport snapshot locks while Qt polls, then release. Expect refresh skip and recovery on next polls, no stale terminal state and responsive GUI; FAIL on permanent old header or unbounded UI lock wait. Windows OPTIONAL, UAC NO, Game NO, Server NO.

L12 — NOT TESTED. Crash worker mid-overlap of two IDs, with receiver enabled, and separately Stop immediately after confirmed natural run_end. Expect missing old terminal remains unconfirmed and active interval gets explicit gap; completed report only on accepted verified finish; FAIL on favorable report built on missing data or old ID attached to new attempt. Windows YES, UAC YES, Game YES, Server YES.

Historical checkpoints, NOT newly rerun: QA_DIRECT_GAME_LAB_INTERIM_2026-11-17.md reports Validator 286 tests + 33 subtests, Scanner UI/report 31 tests, server pure tests 106 on Scanner c42346b / Validator 21c9432; it does NOT imply native packaged/UAC or successful full C05 acceptance. FINAL_REAL_STAGE_REVIEW_2026-11-17.md on Scanner c955c68 / Validator 21c9432 reports one confirmed natural stage 0->1->2 end, approximately 1.537581-second deferred finalization with 12 fresh sensor polls and a separate unresolved Stopping symptom; it does not prove complete Security 4663 coverage or independently verified SACL restoration.

## 5. Exact shared invariants with other agents

01 security-clock: Original run wall/QPC bounds stay with its frozen Security audit; clock_changed invalidates full coverage, never clean.
02 security-collection: Cancelled/failed Security query and skipped local diagnostic IPC are absence of evidence, not evidence of no access.
03 audit-recovery: Restoring temporary Security SACL/policy belongs to recovery owner; PID absence is not independently verified restoration and a new generation must not race it.
05 run-boundaries: Old frozen ETW/Security and deferred terminal packets retain their original localRunId even if new run_start occurs first.
06 polling-performance: Sensor/Qt responsiveness, fresh sample counts and tail/cleanup latency are distinct measurements; do not count cached snapshots as fresh reads.
07 server-assessment: Local stop, worker terminal emission, IPC ACK, network finish ACK, confirmed game end, coverage and public report status are independent predicates.

## 6. Missing evidence, remaining hypotheses, and conclusion

The retained JSONLs contain engine/sensor/finalization events and Scanner game/enable traces, but NO timestamped GUI Stop events, controller generation/lock state, observer-finally or observer_done, sender drain completion, actual tail IPC/ACK transcript, successive UI paints, or server ACKs. A historical operator measured >11 seconds of Stopping after worker disappearance, but the original log does not identify why the header remained so. C05 proves worker engine deferred IDs and polling at the tested revision, NOT independently enumerated ETW sessions or acknowledged delivery.

Confirmed: the present controller has a potential permanent Stopping interleaving and a premature Off interleaving; old/new run separation and bounded failure modes are present in code and backed by limited captures/tests. Open: which owner caused the observed 11 seconds, native restoration in all failure paths, actual 12->13 finalizer queue failure semantics and full end-to-end ACK delivery. Prioritize the generation-scoped status correction and minimally instrumented native Stop matrix without broadening the protection surface.
