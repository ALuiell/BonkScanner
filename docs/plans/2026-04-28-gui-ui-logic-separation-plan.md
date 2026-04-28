# GUI UI-Logic Separation Implementation Plan

**Spec:** `docs/specs/2026-04-28-gui-ui-logic-separation-spec.md`

**Goal:** Refactor `gui.py` so it is primarily responsible for CustomTkinter view concerns while preserving all current user-visible BonkScanner behavior.

**Architecture:** Keep `gui.py` as the composition root for dialogs, widgets, button commands, log rendering, and UI state updates. Move non-UI behavior into small Python modules with direct unit tests: scanner/candidate helpers, Windows focus helpers, native-hook run-control orchestration, and the background scanner loop. Preserve existing `MegabonkApp` method names as thin delegating wrappers during the refactor so tests and callers can migrate gradually without changing runtime behavior.

**Tech Stack:** Python 3.12, `customtkinter`, `Pillow`, `keyboard`, `pywin32`, `pymem`, `unittest`, and existing batch entrypoints.

**Assumptions:** `config.py` remains the shared runtime settings source for this refactor. Existing GUI behavior, log text, hotkey semantics, native hook semantics, and scanner start/stop state transitions remain unchanged. The current test drift at `tests/test_gui_run_control.py` around `try_alt_attach_foreground_window` is handled by testing the extracted `window_control.try_attach_foreground_window` function and keeping only canonical wrapper names in `gui.py`.

---

## File Map

- Create: `scanner_logic.py` - pure scanner/candidate helpers currently embedded as `MegabonkApp` static/class methods and small config-driven evaluation wrappers.
- Create: `window_control.py` - Windows foreground/focus helpers currently embedded in `MegabonkApp`.
- Create: `app_run_control.py` - native-hook/keyboard run-control mode orchestration currently embedded in `MegabonkApp`.
- Create: `scanner_loop.py` - background map scanning workflow currently embedded in `MegabonkApp.background_loop`.
- Create: `tests/test_scanner_logic.py` - focused tests for candidate item validation, stat formatting, score calculation, and candidate evaluation wrappers.
- Create: `tests/test_window_control.py` - focused tests for foreground-window detection, window lookup, ALT attach fallback, and game process ID extraction.
- Create: `tests/test_app_run_control.py` - focused tests for run-control mode switching, hook detach logging, hook injection loop logging, and admin warning behavior.
- Create: `tests/test_scanner_loop.py` - focused tests for background scanner loop behavior currently covered through `MegabonkApp.background_loop`.
- Modify: `gui.py` - reduce to dialogs, widget construction, UI rendering, UI event wiring, and thin adapters to extracted modules.
- Modify: `tests/test_gui_run_control.py` - keep GUI integration coverage for `SettingsDialog`, `toggle_main_loop`, `hotkey_toggle_scanning`, `on_closing`, and wrapper delegation; move non-UI unit cases into the new focused test files.

## Spec Coverage

- `gui.py` is focused on UI responsibilities: Tasks 1 through 5 move pure logic, Windows interop, run-control orchestration, and scanner loop behavior out of `gui.py`; Task 6 prunes imports and leaves GUI adapters only.
- Non-UI logic is separated from the UI layer: Tasks 1, 2, 3, and 4 create dedicated non-UI modules with direct tests.
- Existing user-visible behavior remains unchanged: Each extraction task starts with tests that pin the existing log strings, state transitions, return values, and interaction branches before implementation.
- Cleanup does not expand scope into UX or feature changes: Task 6 limits cleanup to import removal, wrapper consolidation, and relocation of tests; no widget layout, labels, hotkeys, thresholds, or user flows are changed.
- Out of scope items stay out of scope: The plan does not add features, change config schema, alter game-memory offsets, change native hook behavior, change scoring rules, or redesign the GUI.

## Implementation Tasks

### Task 1: Extract Scanner Helper Logic

**Files:**
- Create: `scanner_logic.py`
- Create: `tests/test_scanner_logic.py`
- Modify: `gui.py`
- Modify: `tests/test_gui_run_control.py`

- [ ] **Step 1: Write or update the failing test**

Create `tests/test_scanner_logic.py` with direct tests for helpers currently on `MegabonkApp`:

- `item_name` returns `item.name` when present and `str(item)` otherwise.
- `has_required_shady_guy_item` returns true when one item name is in `REQUIRED_SHADY_GUY_ITEMS` and false for unrelated names.
- `shady_guy_count` reads `MapStat.SHADY_GUY.max`, falls back to `"Shady Guy"` in adapted stats, clamps negative and invalid values to zero.
- `format_stats(stats, scores_config)` preserves the exact text shape currently produced by `MegabonkApp.format_stats`, including normalized microwave display and score with one decimal.
- `calculate_map_score(stats, scores_config)` delegates to `logic.calculate_score`.
- `evaluate_candidate(stats, evaluation_mode, active_templates, templates, scores_config)` delegates to template matching in `"templates"` mode and score evaluation in `"scores"` mode.

Run: `python -m unittest tests.test_scanner_logic`
Expected: the command fails before implementation because `scanner_logic.py` does not exist.

- [ ] **Step 2: Implement the minimal change**

Create `scanner_logic.py` and move these non-UI helpers out of `gui.py`:

- `REQUIRED_SHADY_GUY_ITEMS`
- `item_name(item: object) -> str`
- `has_required_shady_guy_item(items: list[object], required_items: frozenset[str] = REQUIRED_SHADY_GUY_ITEMS) -> bool`
- `shady_guy_count(raw_stats: dict[object, object], stats: dict[str, int]) -> int`
- `format_stats(stats: dict, scores_config: dict) -> str`
- `calculate_map_score(stats: dict, scores_config: dict) -> float`
- `evaluate_candidate(stats: dict, evaluation_mode: str, active_templates: list[str], templates: list[dict], scores_config: dict) -> dict | None`

Update `gui.py` so `MegabonkApp.format_stats`, `MegabonkApp.calculate_map_score`, and `MegabonkApp.evaluate_candidate` are thin wrappers around `scanner_logic`. Replace direct references to `REQUIRED_SHADY_GUY_ITEMS`, `item_name`, `has_required_shady_guy_item`, and `shady_guy_count` inside `background_loop` with `scanner_logic` calls until Task 4 moves the loop.

- [ ] **Step 3: Run focused validation**

Run: `python -m unittest tests.test_scanner_logic tests.test_logic tests.test_runtime_stats`
Expected: all tests pass, proving scoring/template behavior and stat adaptation are unchanged.

Run: `python -m unittest tests.test_gui_run_control`
Expected: Task 1 introduces no new GUI integration failures; the known pre-existing `AttributeError` for `MegabonkApp.try_alt_attach_foreground_window` remains until Task 2 moves that coverage to `window_control.try_attach_foreground_window`.

### Task 2: Extract Windows Focus and Foreground Control

**Files:**
- Create: `window_control.py`
- Create: `tests/test_window_control.py`
- Modify: `gui.py`
- Modify: `tests/test_gui_run_control.py`

- [ ] **Step 1: Write or update the failing test**

Move the window/focus test cases out of `tests/test_gui_run_control.py` into `tests/test_window_control.py` and target module-level functions:

- `get_game_process_id(client)` returns `None` for missing clients and converts valid `client.memory._pm.process_id` values to `int`.
- `is_game_window_active(process_name, client, win32gui_module, win32process_module)` returns true when pywin32 modules are unavailable, matches the foreground process ID when available, and falls back to title matching when no client process ID exists.
- `bring_game_window_to_front(process_name, client, log, win32gui_module, win32process_module, ctypes_module)` uses direct `SetForegroundWindow`, then the ALT attach fallback after direct foreground failure, and logs the same warning text when no window is found.
- `try_attach_foreground_window(window, win32gui_module, win32process_module, ctypes_module)` detaches all attached threads even when foreground activation raises.

Run: `python -m unittest tests.test_window_control`
Expected: the command fails before implementation because `window_control.py` does not exist.

- [ ] **Step 2: Implement the minimal change**

Create `window_control.py` with module-level optional `win32gui` and `win32process` imports currently in `gui.py`. Move these methods from `MegabonkApp` into pure functions that receive the client, logger, and injectable platform modules:

- `get_game_process_id`
- `is_game_window_active`
- `wait_for_game_window_focus`
- `bring_game_window_to_front`
- `show_game_window`
- `try_attach_foreground_window`
- `send_alt_keypress`
- `is_visible_window`
- `find_game_window`
- `find_game_window_by_pid`
- `find_game_window_by_title`
- `handle_confirmed_target_window`

Keep `MegabonkApp` methods with the same current names as thin delegates to `window_control` so `background_loop` and existing callers still use `self.wait_for_game_window_focus`, `self.bring_game_window_to_front`, and `self.handle_confirmed_target_window`. Remove the stale `try_alt_attach_foreground_window` expectation from GUI tests by covering the canonical `window_control.try_attach_foreground_window` function directly.

- [ ] **Step 3: Run focused validation**

Run: `python -m unittest tests.test_window_control tests.test_gui_run_control`
Expected: all tests pass, including ALT attach fallback behavior and hook-mode target-window handling.

### Task 3: Extract Run-Control Mode Orchestration

**Files:**
- Create: `app_run_control.py`
- Create: `tests/test_app_run_control.py`
- Modify: `gui.py`
- Modify: `tests/test_gui_run_control.py`

- [ ] **Step 1: Write or update the failing test**

Move run-control orchestration tests from `tests/test_gui_run_control.py` into `tests/test_app_run_control.py` and target an `AppRunControl` class:

- Switching from native hook mode to keyboard mode detaches the previous loader, clears loader/thread state, increments generation, creates a `KeyboardRunControlProvider`, resets the native-hook admin warning flag, and preserves the existing success/warning log text.
- Enabling hook mode creates `NativeHookLoader`, creates `HookRunControlProvider`, increments generation, starts a daemon thread, and logs `[*] Native hook restart control enabled.`
- Admin warning behavior matches current startup and hook-enable behavior without duplicate warning logs.
- `native_hook_loop` logs wait, success, skipped, hook-load failure, not-ready retry, and unexpected error messages with the same text as today.

Run: `python -m unittest tests.test_app_run_control`
Expected: the command fails before implementation because `app_run_control.py` does not exist.

- [ ] **Step 2: Implement the minimal change**

Create `app_run_control.py` with an `AppRunControl` class that owns only run-control state and behavior:

- `native_hook_loader`
- `native_hook_thread`
- `native_hook_generation`
- `run_control_provider`
- `_native_hook_admin_warning_logged`
- `apply_run_control_mode(detach_hooks: bool = True)`
- `enable_keyboard_run_control()`
- `enable_hook_run_control()`
- `native_hook_loop(loader: NativeHookLoader, generation: int)`
- `check_admin_rights()`
- `is_running_as_admin()`
- `warn_if_native_hook_needs_admin()`

Inject `config`, `keyboard`, `threading`, `NativeHookLoader`, `HookRunControlProvider`, `KeyboardRunControlProvider`, `log`, and `stop_event` so the class is testable without widgets. Update `MegabonkApp.__init__` to create `self.run_control = AppRunControl(...)`, and keep existing `MegabonkApp` methods as thin wrappers/properties so the rest of the GUI can continue calling `self.apply_run_control_mode()`, `self.is_hook_run_control_active()`, and `self.is_keyboard_run_control_active()`.

- [ ] **Step 3: Run focused validation**

Run: `python -m unittest tests.test_app_run_control tests.test_run_control tests.test_gui_run_control`
Expected: all tests pass, proving provider behavior and GUI integration behavior are unchanged.

### Task 4: Extract Background Scanner Loop

**Files:**
- Create: `scanner_loop.py`
- Create: `tests/test_scanner_loop.py`
- Modify: `gui.py`
- Modify: `tests/test_gui_run_control.py`

- [ ] **Step 1: Write or update the failing test**

Move the current `background_loop` tests from `tests/test_gui_run_control.py` into `tests/test_scanner_loop.py` and target a `ScannerLoop` class or `run_scanner_loop` function with injected callbacks. Cover these existing behaviors:

- Stop wake cleanup clears `scan_event`, sets `is_running` false, sets `is_ready_to_start` false, closes the client, and schedules `update_status_ui`.
- Stable snapshot reuse does not perform a second `get_map_stats()` call before candidate validation.
- Candidate rejection logs remain unchanged for empty Shady Guy items, missing required Shady Guy items, Shady Guy item read failures, and vendor-item count mismatch.
- Confirmed candidate logs target text, stat text, Shady Guy items, calls `log_target_found`, calls `handle_confirmed_target_window`, clears running state, and updates status.
- Timeout forces a reroll and resets cached state.
- Lost process/module/memory errors clear running state, close the client, reset wait state, and log the same lost-connection message.

Run: `python -m unittest tests.test_scanner_loop`
Expected: the command fails before implementation because `scanner_loop.py` does not exist.

- [ ] **Step 2: Implement the minimal change**

Create `scanner_loop.py` with a testable scanner-loop object that owns only scanner workflow state and receives UI actions as callbacks:

- Inputs: `config`, `GameDataClient` factory, `adapt_map_stats`, `scanner_logic`, `stop_event`, `scan_event`, `log`, `after`, `update_status_ui`, `wait_for_game_window_focus`, `check_best_map`, `check_worst_map`, `evaluate_candidate`, `log_target_found`, `handle_confirmed_target_window`, `reroll_map`, and `close_client`.
- State: `client`, `is_running`, `is_ready_to_start`, cached generation state, cached stats, last reroll time, and first-scan flag.
- Output callbacks: state changes are reported back to `MegabonkApp` through narrow setters or a small mutable state object, not through widget access.

Update `MegabonkApp.background_loop` to delegate to `self.scanner_loop.run()` or pass a `ScannerLoopState` object into `scanner_loop.run_scanner_loop(...)`. Keep `MegabonkApp.toggle_main_loop` responsible for UI-mode selection, template checkbox reading, session-stat reset, thread creation, and status UI updates.

- [ ] **Step 3: Run focused validation**

Run: `python -m unittest tests.test_scanner_loop tests.test_gui_run_control`
Expected: all tests pass, proving scanner workflow behavior is unchanged after leaving `gui.py`.

### Task 5: Keep GUI as View and Thin Composition Layer

**Files:**
- Modify: `gui.py`
- Modify: `tests/test_gui_run_control.py`

- [ ] **Step 1: Write or update the failing test**

Trim `tests/test_gui_run_control.py` so it verifies GUI integration only:

- `SettingsDialog.save` persists settings and asks the app to apply run-control mode.
- `SettingsDialog.on_native_hook_toggle` prompts when enabling hooks and reverts on cancellation.
- `toggle_main_loop` reads selected template checkboxes, logs active profiles or active score tiers, initializes session stats, clears stale events, and starts a worker thread.
- `hotkey_toggle_scanning` refuses to start before readiness and toggles `scan_event` after readiness.
- `on_closing` signals stop, wakes scanner loop, asks run control to detach hooks, unhooks keyboard, closes the client, and destroys the window.

Run: `python -m unittest tests.test_gui_run_control`
Expected: all GUI integration tests pass after Tasks 1 through 4 and fail if `gui.py` no longer wires extracted services correctly.

- [ ] **Step 2: Implement the minimal change**

Make `gui.py` primarily contain:

- `resource_path`
- `COLOR_MAP`
- `center_toplevel`
- Dialog classes
- `MegabonkApp.__init__`
- `setup_ui`
- tab/list refresh methods
- dialog open methods
- hotkey setup and UI event handlers
- `update_status_ui`
- `animate_scanner_indicator`
- `log`
- `toggle_main_loop`
- `update_timer`
- `refresh_stats_ui`
- session-stat display methods
- thin wrapper methods that call `scanner_logic`, `window_control`, `app_run_control`, and `scanner_loop`

Remove direct non-UI imports from `gui.py` when their only remaining use is in extracted modules: top-level `ctypes`, `wintypes`, `subprocess`, direct `GameDataClient`, direct `MapStat`, direct hook-loader exceptions, direct memory exceptions, and direct `adapt_map_stats`. Keep `os`, `sys`, `threading`, `time`, `datetime`, `customtkinter`, `PIL.Image`, `updater`, `config`, `keyboard`, and extracted module imports where GUI composition still uses them.

- [ ] **Step 3: Run focused validation**

Run: `python -m py_compile gui.py scanner_logic.py window_control.py app_run_control.py scanner_loop.py`
Expected: all files compile without syntax errors.

Run: `python -m unittest tests.test_gui_run_control tests.test_scanner_logic tests.test_window_control tests.test_app_run_control tests.test_scanner_loop`
Expected: all focused refactor tests pass.

### Task 6: Full Regression and Scope Check

**Files:**
- Modify: `gui.py`
- Modify: `tests/test_gui_run_control.py`
- Test: `tests/test_scanner_logic.py`
- Test: `tests/test_window_control.py`
- Test: `tests/test_app_run_control.py`
- Test: `tests/test_scanner_loop.py`

- [ ] **Step 1: Write or update the failing test**

No new behavior tests are added in this task. Use the tests from Tasks 1 through 5 as the acceptance net and add assertions only when a behavior from the spec is not covered by the extracted unit tests.

Run: `python -m unittest discover -s tests`
Expected: all existing and new tests pass.

- [ ] **Step 2: Implement the minimal change**

Perform a final scope pass:

- Confirm `gui.py` no longer contains large blocks of pure scanner logic, Windows interop logic, native-hook run-control orchestration, or the scanner loop body.
- Confirm widget labels, log message text, hotkey names, settings persistence, scoring behavior, template matching, native hook behavior, and restart behavior were not intentionally changed.
- Confirm all extracted modules are imported by `gui.py` and covered by focused tests.
- Confirm `README.md`, `AGENT.md`, `config.json`, native hook files, and reverse docs are not modified for this refactor.

- [ ] **Step 3: Run focused validation**

Run: `git diff -- gui.py scanner_logic.py window_control.py app_run_control.py scanner_loop.py tests/test_gui_run_control.py tests/test_scanner_logic.py tests/test_window_control.py tests/test_app_run_control.py tests/test_scanner_loop.py`
Expected: the diff shows structural extraction, wrapper delegation, and test relocation only; no user-visible UI text or behavior changes outside existing log text preservation.

Run: `python -m unittest discover -s tests`
Expected: all tests pass.

## Validation

- `python -m py_compile gui.py scanner_logic.py window_control.py app_run_control.py scanner_loop.py` should compile every changed Python module.
- `python -m unittest tests.test_scanner_logic` should pass scanner helper extraction tests.
- `python -m unittest tests.test_window_control` should pass Windows focus/foreground extraction tests.
- `python -m unittest tests.test_app_run_control` should pass run-control orchestration extraction tests.
- `python -m unittest tests.test_scanner_loop` should pass scanner workflow extraction tests.
- `python -m unittest tests.test_gui_run_control` should pass GUI integration tests after they are narrowed to view wiring and lifecycle behavior.
- `python -m unittest discover -s tests` should pass the full Python test suite.

## Out of Scope

- New BonkScanner features.
- User-visible UX changes.
- Widget layout redesign.
- New configuration keys or config file schema changes.
- Scoring rule changes.
- Template matching rule changes.
- Memory offset changes.
- Native hook protocol changes.
- Build/package script changes.
- Documentation rewrites outside this implementation plan.
