# BonkScanner Functional Regression Audit Prompt

Repository: `F:\Python\MegabonkReroll`

This prompt defines a two-stage audit workflow designed to be both thorough and token-efficient:

1. A **Discovery Agent** inspects one product area and produces a compact evidence report.
2. A **Verification Agent** uses that report to quickly challenge the important claims, reproduce confirmed problems, and approve or reject the findings.

The report must contain enough structure, exact references, and proof that the Verification Agent does not need to rediscover the repository from scratch.

If the user does not explicitly select a mode, use **Discovery Mode** for the requested tab or subsystem only.

---

## 1. Primary Objective

Find functional regressions and architectural mistakes introduced by changes to data exchange, refresh coordination, `LiveRunTracker`, runtime snapshots, caches, background workers, and consumer-specific projections.

For every feature, trace the complete path:

```text
documented behavior
-> source of truth
-> memory/API/config read
-> validation and fallback
-> runtime snapshot
-> tracker/cache
-> calculation
-> UI
-> recording
-> replay
-> comparison
-> OBS overlay
-> Twitch
```

Do not stop after proving that a class, method, widget, or test exists. Prove that the correct value reaches every relevant consumer, survives lifecycle transitions, and recovers after partial or temporary failures.

The audit should prioritize real correctness problems over speculative hardening and highly artificial edge cases.

---

## 2. Non-Negotiable Working Rules

### Documentation first

When expected behavior is unclear, search in this order:

1. `README.md`
2. `docs/wiki/`
3. `docs/mechanics/`
4. `docs/design/`
5. `docs/recovery/`
6. tests
7. Git history and the `main` comparison
8. implementation code

Only ask the user when documentation, code, tests, and Git history still do not provide one clear answer.

Use this question workflow:

```text
question discovered
-> search documentation
-> inspect code/tests/history
-> state the best-supported interpretation
-> ask the user only for confirmation or the missing product decision
```

Do not ask questions that can be answered locally.

### Read-only discovery

During Discovery Mode:

- do not edit production code;
- do not add intentionally failing tests to the worktree;
- temporary read-only scripts are allowed;
- local test servers and browser checks are allowed when relevant;
- do not commit or push;
- preserve unrelated user changes in a dirty worktree.

After the user explicitly approves a fix:

1. add a regression test that reproduces the problem;
2. fix the root cause;
3. check every consumer of the shared value;
4. run focused tests;
5. run the broader relevant suite;
6. run the full suite when proportionate to the risk;
7. list every changed file;
8. commit or push only when separately requested.

### Evidence, not confidence

The sentence "tests pass" is not evidence that no bug exists.

Every important claim must be marked as one of:

- **PROVEN** — directly demonstrated by code plus a test, runtime observation, or reproducible script;
- **SUPPORTED** — strongly supported by code and documentation but not exercised end-to-end;
- **INFERRED** — likely, but a required runtime condition was unavailable;
- **OPEN QUESTION** — no authoritative answer exists locally.

Never label a subsystem "fully correct" only because happy-path unit tests pass.

### Token-efficient investigation

- Use `rg`/`rg --files` before broad file reads.
- Batch independent searches and tests when possible.
- Read only the relevant ranges after locating symbols.
- Do not paste full source files into the report.
- Do not paste command output longer than 20 lines; summarize it and include the exact command.
- Reference symbols and exact file lines instead of quoting code.
- Do not repeat the same architectural explanation in multiple sections; assign it an ID and reference that ID.
- Keep speculative ideas out of the confirmed issue list.
- A "no issue" conclusion must state what was actually checked.

---

## 3. Confirmed BonkScanner Product Rules

Treat these as established behavior. Do not ask the user to confirm them again unless current documentation or code directly contradicts them.

### General live-data behavior

- A failed read of one optional field must not invalidate the whole live snapshot.
- Keep the last known valid value for an individual field when that field temporarily fails.
- Recording should continue when optional reads fail.
- Do not invent large collections of arbitrary sanity limits. Add validation only for demonstrated realistic failures.
- The main goal is correct normal operation and recovery from real transient reads, not theoretical perfection.
- The architecture may read once and distribute the resulting state to multiple consumers. One active consumer must not prevent other configured consumers from receiving the same update.

### Forest and Desert stage detection

- Raw `stage_index = 0` means Stage 1.
- Raw `stage_index = 1` means Stage 2.
- Raw `stage_index = 2` means Stage 3.
- Derived Stage 4 detection is allowed only after the tracker has already reached Stage 3.
- Forest/Desert Stage 4 is not represented by a distinct reliable memory stage.
- A Stage 4 transition may be detected when activity totals collapse after entering the final map:
  - `chests_total < 46`, or
  - `pots_total < 55`.
- Timer reset and the other documented transition signals may also contribute.
- The collapse heuristic must never promote Stage 1 or Stage 2 directly to Stage 4.

### Graveyard

- Graveyard is one main Stage Summary map, even though it contains several internal phases.
- Raw stage identity remains effectively static across its phases.
- Strong Graveyard markers include `Pumpkin`, `Gravestones`, `Crypt Chests`, `Crypt Pots`, or `Chests.max == 69`.
- Crypt, main-map, boss, and post-boss phases must not be treated as ordinary Forest/Desert stage transitions.

### Recordings and consumers

- OBS Overlay does not require an active recording.
- Compare Runs is functionally autonomous and reads saved recordings, not current game memory.
- Active recording includes Chaos Tome roll data.
- Restarting the application may reconstruct state from fingerprints; consumers must receive the reconstructed current state without depending on an open UI tab.

---

## 4. Discovery Mode Deliverable

Create one Markdown evidence report for the requested tab or subsystem.

Recommended path:

```text
docs/audits/<area_slug>_audit_evidence.md
```

If the user requested analysis only and did not authorize a file, return the report in the response instead. Do not create extra files silently.

The report must follow the exact structure in Section 8. It should normally stay below **300 lines**. Use appendices only when a large UI inventory or test matrix genuinely requires them.

The Discovery Agent must optimize the report for a second agent that has not read the inspected files.

---

## 5. Required Discovery Procedure

### Step 1 — Establish repository state

Record:

- current branch;
- current commit SHA;
- merge base with `main`;
- dirty-worktree status;
- relevant changed files versus `main`;
- the repository instruction file used (`AGENT.md` or `AGENTS.md`), if present.

Do not include unrelated branch diffs in the functional analysis.

### Step 2 — Build the UI and feature inventory

List every visible and background element in scope:

- tabs and nested tabs;
- cards and groups;
- labels and counters;
- buttons and menus;
- checkboxes, inputs, selectors, and sliders;
- dialogs;
- background timers and workers;
- servers and external integrations;
- persistence keys;
- empty, loading, error, stale, and disabled states.

Assign stable IDs such as `UI-01`, `UI-02`, and `BG-01`. Later sections must reference these IDs rather than repeating descriptions.

### Step 3 — Build the symbol and ownership map

For every relevant class, function, or module, provide one compact row containing:

| ID | Symbol | Responsibility | Owns/mutates | Inputs | Outputs/consumers | Thread/lifecycle | Tests |
|---|---|---|---|---|---|---|---|

Include:

- UI mixins/classes;
- data readers/clients;
- immutable snapshot/projection types;
- trackers and caches;
- recorders/loaders;
- formatters/renderers;
- background workers/timers;
- HTTP/Twitch/overlay adapters;
- config normalization and persistence functions.

Use exact references such as `src/file.py:Class.method:123`. Do not paste class bodies.

### Step 4 — Reconstruct expected behavior

Create an **Expected Behavior Ledger**:

| ID | Expected behavior | Authority | Confidence | Notes |
|---|---|---|---|---|

Authority must point to documentation, tests, confirmed rules in this prompt, or Git history.

If the sources disagree, record the disagreement instead of choosing silently.

### Step 5 — Compare with `main`

For each relevant change, explain:

- previous source of truth;
- current source of truth;
- why it changed;
- which consumers changed;
- which consumers did not change but should have been reviewed;
- whether behavior, timing, lifecycle, or only structure changed.

Use a compact change table:

| Change ID | Files/symbols | Behavior before | Behavior now | Risk | Verification |
|---|---|---|---|---|---|

Do not dump the full diff.

### Step 6 — Build the end-to-end data-flow matrix

For every displayed or persisted value, trace:

| Flow ID | Value/feature | Source | Validation/fallback | Snapshot field | Tracker/cache | Calculation | Consumers | Reset/recovery | Evidence |
|---|---|---|---|---|---|---|---|---|---|

At minimum, identify:

- the authoritative value;
- who writes it;
- who reads it;
- whether it is copied or shared;
- whether it can be stale;
- what clears it;
- what happens after one failed read;
- what happens after a new run, stage transition, game exit, and application restart.

### Step 7 — Check lifecycle and failure scenarios

Exercise or inspect all applicable scenarios:

1. application starts before the game;
2. application attaches after a run already started;
3. game disappears during a read;
4. one optional field fails while others succeed;
5. one temporary incorrect value appears and then recovers;
6. timer moves backward or resets;
7. stage/map changes;
8. new run starts;
9. recording starts, pauses, resumes, and stops;
10. UI tab is hidden while a background consumer remains active;
11. worker or server fails to start;
12. port or resource is already occupied;
13. application closes while workers or servers are running;
14. config is invalid, partial, legacy, or missing;
15. saved data is partial, corrupt, or from an older schema;
16. two snapshots arrive close together or out of order;
17. a slow asynchronous result completes after the selection/context changed.

Only claim a scenario was checked when the report contains evidence for it.

### Step 8 — Inspect tests critically

Build a coverage matrix:

| Test ID | Test | What it proves | Important scenario not covered | Realistic fake? | Result |
|---|---|---|---|---|---|

Check whether tests:

- use realistic lifecycle ordering;
- cover multiple consecutive snapshots;
- cover transient/partial/stale data;
- cover reset and recovery;
- cover hidden-tab/background-consumer behavior;
- cover asynchronous selection races;
- verify persisted output and replay, not only in-memory objects;
- accidentally lock in incorrect behavior;
- use a fake that is much cleaner than real memory/API behavior.

Run focused tests first. Record the exact command and summarized result.

### Step 9 — Perform one real integration check when applicable

Examples:

- inspect current game memory and compare it with program output;
- load real recordings from the workspace;
- start the local overlay HTTP server and request actual routes;
- render the browser page and inspect the DOM;
- round-trip a config using a temporary path;
- compare two representative recordings end-to-end.

Use isolated temporary data for writes. Never overwrite the user's real config or recordings during an audit.

### Step 10 — Classify findings

A confirmed issue requires all of:

- observable incorrect behavior or a deterministic broken path;
- a concrete reproduction;
- a root cause;
- exact file/symbol references;
- an explanation of why current tests missed it;
- a proposed regression test;
- a fix direction without implementation.

Do not promote a code smell, theoretical race, or possible hardening idea into the confirmed issue list without proof.

---

## 6. Known Architectural Error Patterns to Search For

- One invalid field poisons the whole snapshot.
- A temporary read becomes permanent tracker state.
- A tracker only moves forward and cannot recover from a false transition.
- A shared mutable object is read while another thread changes it.
- A lock protects a container but not the complete logical transaction.
- UI state is incorrectly used as the source of truth for background consumers.
- Closing or hiding a tab stops a server, recorder, Overlay, or Twitch update.
- A consumer reads the tracker several times and combines values from different moments.
- A fallback reports success after only a partial read.
- An old async result overwrites a newer selection.
- Loading/error state leaves actions enabled for old data.
- An error clears the model but leaves old UI visible.
- A disabled optional section still performs expensive calculations.
- Already aggregated recording data is aggregated a second time.
- A legacy migration normalizes differently on load and save.
- Start failure leaves the UI reporting a running service.
- Two services can claim the same resource and both report success.
- A background exception prevents the next scheduled tick.
- A stopped worker/timer is restarted twice or never restarted.
- Reset clears the UI but not the tracker/cache, or vice versa.
- A fake memory/client never produces the partial states seen in the real game.

---

## 7. Area-Specific Audit Checklists

Use only the checklist for the requested area, plus shared dependencies that directly affect it.

### Templates

- create, edit, delete;
- built-in versus custom templates;
- enable/disable;
- inline editing;
- value normalization;
- config persistence;
- active selection;
- scanner evaluation parity;
- result display;
- reset and evaluation-mode changes;
- difference from `main`.

### Scores

- all stat weights;
- microwave multipliers;
- Light/Good/Perfect/Perfect+;
- automatic and manual thresholds;
- tier enable/disable;
- save/load/reset;
- score calculation;
- displayed score versus actual scanner decision;
- Templates/Scores switching;
- best/worst map;
- average rerolls per target.

### Logs and scanner lifecycle

- Start/Stop Scanner;
- connection and waiting states;
- map-ready stabilization;
- seed and map-stat reads;
- restart path;
- errors and recovery;
- hotkeys;
- worker/timer shutdown;
- log messages versus real actions;
- session reset;
- game disappearance.

### Session Stats

- Session Time;
- Session Rerolls;
- RPM;
- Best/Worst Map Found;
- Average Rerolls per Target;
- Tracked Items and rule settings;
- multi-item rules;
- Map 1 only;
- stage attribution;
- late attach;
- duplicate stack gains;
- transient item drops;
- new run and session reset;
- Templates/Scores switching;
- parity with `LiveRunTracker`, Overlay, and Twitch `!session`/`!items`.

### Live Stats

- recording controls and timeline;
- Items, total count, rarity, sorting, Show More;
- Run Summary;
- average chests/min;
- in-game time;
- mob kills and instant/60s/5m/run KPS;
- player level;
- chest statistics;
- Stage Summary: Stage, Time, Kills, Items;
- Segment Compare;
- Banishes;
- Stats;
- Weapons;
- Tomes;
- Chaos Tome;
- Damage Sources;
- Powerups;
- event/stage timers;
- unavailable and stale states;
- per-field last-known fallback;
- memory path, validation, snapshot consistency, reset, and recording connection for every block.

### Recordings

- manual start/stop;
- hotkey;
- auto-start/auto-stop;
- pause and continuation across stages;
- new file for a new run;
- snapshot interval;
- schema and metadata;
- items, stats, weapons, tomes, Chaos, banishes, damage sources, stage summary, chests, KPS, powerups when supported;
- timeline slider and nearest snapshot;
- rename/delete/cleanup;
- legacy `vods`;
- partial/corrupt JSONL;
- summary record;
- replay of old recordings;
- protection against saving an invalid live snapshot;
- async loading races;
- clearing old UI on loading failure.

### Compare Runs

- Run A/Run B selection;
- guided selection;
- swap;
- synchronization by in-game time;
- nearest snapshot;
- selected stats;
- overview;
- Stage Summary, Items, Weapons, Tomes, and Chaos diffs;
- gained/broken/lost semantics where documented;
- runs of different lengths;
- missing fields and legacy recordings;
- delta sign and formatting;
- no repeated aggregation;
- async selection/loading races;
- disabled sections do not perform unnecessary work.

### Twitch Bot

- OAuth connect/disconnect;
- token storage and revocation;
- target channel;
- auto-connect;
- start/stop/reconnect;
- access tiers;
- global and command cooldowns;
- command settings and templates;
- stage and periodic announcements;
- `!stats`, `!session`, `!bans`, `!disabled`, `!items`, `!weapons`, `!tomes`, `!chaos`, `!stages`, `!powerups`, `!kps`, `!chests`, `!scanner`, `!presets`, `!bonkhelp`;
- current thread-safe snapshot;
- no dependency on an open Live Stats tab.

### In-Game Overlay

- Scanner Status;
- Recording Status;
- KPS, 60s, 5m, run average;
- Stats;
- Active Powerups;
- Luck Rarity and rarity bar;
- Event Timer and warning threshold;
- source and refresh rate of every widget;
- show/hide, scale, position, drag, persistence, reset;
- start/stop, auto-start, click-through, always-on-top;
- screen and geometry handling;
- missing game and stale data;
- stage transition and new run;
- application shutdown.

### OBS/browser Overlay

- server start/stop and restart;
- loopback bind address and port;
- occupied port behavior;
- auto-start;
- `/overlay` and widget-specific URLs;
- edit mode;
- canvas size;
- drag, resize, and scale;
- config persistence using an isolated temporary config;
- Stage Summary;
- Tracked Items;
- Stats;
- KPS;
- Banishes;
- JSON serialization;
- HTML/JS rendering and escaping;
- thread-safe state;
- stale/no-game state;
- browser polling and cache behavior;
- hidden-tab independence;
- operation without recording;
- clean application shutdown;
- actual browser/DOM check, not only Python state tests.

### Settings and global functions

- Scan, Reset, and Record hotkeys;
- auto-start recording;
- OBS reminder;
- Min Reroll Delay;
- Reset Hold Duration and `quick_reset_time` synchronization;
- Snapshot Interval;
- Check for Updates;
- config defaults and migrations;
- save/load round trip;
- invalid config;
- packaged versus source mode;
- clean shutdown of timers, workers, overlays, and Twitch.

---

## 8. Exact Evidence Report Format

```markdown
# <Area> Audit Evidence Report

## 1. Audit identity
- Area:
- Mode: Discovery
- Branch:
- Commit:
- Merge base with main:
- Worktree state:
- Date:

## 2. Scope and exclusions
- Included:
- Excluded:
- Runtime limitations:

## 3. Documentation used
| Doc | Relevant rule | Lines/section |

## 4. UI/background inventory
| ID | Element/process | User action or trigger | Expected result | Implementation |

## 5. Symbol and ownership map
| ID | Symbol | Responsibility | Owns/mutates | Inputs | Consumers | Lifecycle/thread | Tests |

## 6. Expected Behavior Ledger
| ID | Expected behavior | Authority | Confidence | Notes |

## 7. Changes versus main
| ID | Files/symbols | Before | Now | Risk | Verification |

## 8. End-to-end data-flow matrix
| ID | Value | Source | Validation/fallback | Snapshot/cache | Consumers | Reset/recovery | Evidence |

## 9. Lifecycle and failure scenarios
| Scenario | Status | Evidence | Result |

## 10. Confirmed issues
### ISSUE-01: <short title>
- Severity:
- Confidence: Confirmed
- User-visible effect:
- Exact reproduction:
- Expected result:
- Actual result:
- Root cause:
- Evidence references:
- Why tests missed it:
- Affected consumers:
- Required regression test:
- Fix direction, without implementation:

## 11. Supported risks not yet proven
| Risk | Why plausible | Missing proof | Cheapest next check |

## 12. Questions for the user
Only unresolved product decisions. Include the best-supported interpretation before each question.

## 13. Verified behavior with no issue found
| Feature | What was checked | Evidence | Confidence |

## 14. Test and runtime evidence
| Command/check | Purpose | Result |

## 15. Recommended fix order
1. Confirmed correctness problems.
2. Data corruption or persistence problems.
3. Lifecycle/concurrency problems.
4. Performance problems with measured impact.
5. Documentation-only mismatches.

## 16. Verification handoff
- Claims that must be rechecked first:
- Minimal commands to rerun:
- Best reproduction scripts/steps:
- Files and symbols most likely to contain the root cause:
- Questions still blocking a decision:
- Recommended next area, but do not start it:
```

---

## 9. Verification Mode

The Verification Agent should consume the evidence report instead of repeating the full discovery process.

### Fast verification procedure

1. Confirm that the report commit matches the current commit. If not, inspect the relevant diff since the report.
2. Read Sections 10, 11, 14, and 16 first.
3. Re-run the minimal focused commands from Section 16.
4. Open only the exact symbols referenced by confirmed issues.
5. Independently reproduce every confirmed issue.
6. Challenge the strongest "no issue" claims with at least one end-to-end check.
7. Spot-check one representative flow for each major consumer in scope.
8. Reject any finding that lacks observable impact, reproduction, or root cause.
9. Identify any report claim contradicted by current code or runtime behavior.
10. Ask the user only for unresolved product decisions.

### Verification output

```markdown
# <Area> Verification Result

## Verdict
- Accepted findings:
- Rejected findings:
- New findings:
- Remaining questions:

## Claim review
| Claim/Issue ID | Verdict | Independent evidence | Notes |

## Commands rerun
| Command | Result |

## Required fixes
| Priority | Issue | Regression test | Root-cause location |

## Final area status
- Ready to fix / No fix required / Blocked by product decision
```

The Verification Agent must not accept statements such as "architecture is thread-safe", "the port error is handled", or "the browser page renders correctly" without checking the actual lock boundary, failure path, or rendered/runtime behavior.

---

## 10. Completion Criteria

An area audit is complete only when the report identifies, for every element in scope:

- documented purpose;
- source of truth;
- owning class/module;
- lifecycle and refresh trigger;
- validation and fallback;
- snapshot/cache behavior;
- reset and recovery behavior;
- all relevant consumers;
- difference from `main`;
- existing test coverage and its limits;
- transient and partial-data risks;
- evidence-backed status.

The report must let another agent verify the important conclusions without broadly rereading the repository.

Do not begin the next tab or subsystem without the user's command.

---

## 11. Start Command for a Discovery Agent

Use the following instruction with this prompt:

```text
Run Discovery Mode for <AREA> only.
Read project documentation first.
Do not modify production files.
Produce the evidence report using Section 8 exactly.
Optimize the report for a second agent that will verify it quickly.
Stop after the report and wait for confirmation before fixing anything or starting the next area.
```
