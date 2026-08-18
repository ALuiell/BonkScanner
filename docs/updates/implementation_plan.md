# Build Progression: Min/Max, Late-Completed, Dynamic Cap

Реализация всех открытых пунктов секции `[Partial]` Build Progression из [functional_updates.md](file:///f:/Python/MegabonkReroll/docs/updates/functional_updates.md#L95-L156).

## Scope

Три взаимосвязанные фичи, реализуемые последовательно:

| # | Feature | Суть |
|---|---------|------|
| 1 | **Min/Max copies** | Двухэтапное требование для предметов: min (обязательный) + optional max (финальная цель) |
| 2 | **Late-completed** | Требование, выполненное после дедлайна → оранжевый символ, не скрывается, отдельный build-complete state |
| 3 | **Dynamic cap** | Auto-cap для Spicy Meatball / Grandma's Secret Tonic через формулу радиуса и narrow SIZE source |

**Deferred** (per spec): Optional background panel для In-Game Overlay.

---

## Feature 1: Min/Max Item Copies

### Core Data Model

#### [MODIFY] [build_progression.py](file:///f:/Python/MegabonkReroll/src/core/build_progression.py)

**`BuildRequirement`** (line 63): add `max_required: float | None = None`.
Only meaningful for `ITEM` kind; stat/progress always `None`.

**`BuildProgressionRow`** (line 80): add `max_required: float | None = None`.
Needed for projections metadata and Twitch formatting.

### Evaluator Logic

#### [MODIFY] [build_progression.py](file:///f:/Python/MegabonkReroll/src/core/build_progression.py)

In `evaluate_build_progression` (line 159–210), change satisfaction and display logic:

```python
min_met = current is not None and current >= requirement.required

if requirement.max_required is not None:
    satisfied = current is not None and current >= requirement.max_required
    effective_target = requirement.max_required if min_met else requirement.required
    # Deadline applies only to min stage
    if min_met:
        deadline = RequirementDeadline()
        deadline_status, delta = RequirementStatus.NEUTRAL, None
else:
    satisfied = min_met
    effective_target = requirement.required
```

- `required_display` uses `effective_target` (not `requirement.required`)
- `row.required` set to `effective_target`
- `row.max_required` set to `requirement.max_required`
- Display: `0/1` → `1/15` → `15/15`

### Config Normalization

#### [MODIFY] [config.py](file:///f:/Python/MegabonkReroll/src/app/config.py)

In `normalize_build_definition_config` (line 707):
- For `kind == "item"`: read `raw.get("max_required")`
- Validate: positive integer, `max_required >= required`
- If invalid → omit from dict
- Existing configs without `max_required` migrate naturally (field absent = None)

### Config Adapters

#### [MODIFY] [build_progression.py](file:///f:/Python/MegabonkReroll/src/app/build_progression.py)

- `definition_from_config` (line 22): read `max_required` from raw dict
- `definition_to_config` (line 50): write `max_required` if not None
- `build_export_payload` (line 111): include `max_required` in portable data
- Import: passes through normalize which validates

### UI Editor

#### [MODIFY] [build_progression.py](file:///f:/Python/MegabonkReroll/src/ui/dialogs/build_progression.py)

**`_build_editor`** (line 737): replace single `Required` spinbox with:
- `self.min_required = QSpinBox()` — label "Min", range 1–99999
- `self.max_required = QSpinBox()` — label "Max", range 0–99999, `specialValueText=" "` (blank = no max)
- Show Min/Max row only for `kind == "item"`; stat/progress keep existing `Required` (QDoubleSpinBox)

**`_select_target`**: toggle visibility of Min/Max vs Required based on kind.

**`_add_or_update`**: read min/max for items; validate `max >= min` when max > 0.

**`_edit_rule`**: populate min/max from existing requirement.

**Rules list display**: show `Min {n} · Max {m}` badge when max is set; `Required {n}` otherwise.

---

## Feature 2: Late-Completed State

### Core Data Model

#### [MODIFY] [build_progression.py](file:///f:/Python/MegabonkReroll/src/core/build_progression.py)

**`BuildProgressionRow`**: add `late: bool = False`.

**`BuildProgressionSnapshot`**: add `late_complete: bool = False`.
True when `complete=True` and any row has `late=True`.

**`BuildProgressionEvaluation`**: add `late: Mapping[str, bool]`.
Per-requirement late flags, persisted by service between evaluations.

**`STATUS_SYMBOLS`**: add symbol for late state (proposed: `"✓"` — same checkmark but colored orange by presentation layer, distinguishing from green on-time `"✓"`).

### Evaluator Logic

#### [MODIFY] [build_progression.py](file:///f:/Python/MegabonkReroll/src/core/build_progression.py)

Add parameters to `evaluate_build_progression`:
```python
previous_min_satisfied_at: Mapping[str, float] | None = None,
previous_late: Mapping[str, bool] | None = None,
```

Late detection logic:
```python
min_met = current is not None and current >= requirement.required

# Track min satisfaction separately (for late detection)
min_newly_satisfied = min_met and requirement.id not in previous_min_satisfied_at

if min_newly_satisfied:
    late = deadline_status is RequirementStatus.OVERDUE
else:
    late = previous_late.get(requirement.id, False)

# Persist min_satisfied_at
if min_met:
    min_sat = previous_min_satisfied_at.get(requirement.id)
    if min_sat is None and run_time is not None:
        min_sat = max(0.0, float(run_time))
    if min_sat is not None:
        next_min_satisfied_at[requirement.id] = min_sat
```

Late row behavior:
- `row.late = late`
- Late rows use orange symbol color in presentation (status value remains as-is for sort/filter; `late` flag is an overlay on display)
- When `late=True` and working toward max (not fully satisfied): status = NEUTRAL but late flag persists

Build complete:
```python
late_complete = complete and any(row.late for row in rows)
```

### Service

#### [MODIFY] [build_progression.py](file:///f:/Python/MegabonkReroll/src/app/build_progression.py)

`BuildProgressionService`: add per-run state:
```python
_min_satisfied_at: dict[str, float] = {}
_late: dict[str, bool] = {}
```

Pass through to evaluator; update from evaluation result; reset on run change.

### Projections

#### [MODIFY] [build_progression.py](file:///f:/Python/MegabonkReroll/src/projections/build_progression.py)

Row hiding logic (line 32–76):
```python
incomplete = [r for r in rows if r.status is not RequirementStatus.SATISFIED or r.late]
# Late rows are NEVER hidden by show_completed toggle
regular_completed = [r for r in rows if r.status is RequirementStatus.SATISFIED and not r.late]
```

Add `"late": row.late` to payload row dict.

Add `"late_complete": snapshot.late_complete` to payload.

#### [MODIFY] [overlay.css](file:///f:/Python/MegabonkReroll/src/media/overlay/overlay.css)

```css
.build-row.late .build-symbol { color: #F97316; }  /* orange */
.build-complete.late { color: #F97316; }
```

#### [MODIFY] [overlay.js](file:///f:/Python/MegabonkReroll/src/media/overlay/overlay.js)

- Add `late` CSS class to row div when `row.late`
- Late build-complete: `"! BUILD COMPLETE"` in orange (instead of green `"✓ BUILD COMPLETE"`)

#### [MODIFY] [in_game_html.py](file:///f:/Python/MegabonkReroll/src/projections/in_game_html.py)

- Add `"late": "#F97316"` to colors
- When `row.late`: override symbol color to orange
- Late build-complete: orange `"! BUILD COMPLETE · MM:SS"`

### Twitch

#### [MODIFY] [build_progression.py](file:///f:/Python/MegabonkReroll/src/projections/build_progression.py)

In `format_twitch_build` (line 132): late-completed rows go into a `LATE:` group, not hidden with regular completed.

### Sort

#### [MODIFY] [build_progression.py](file:///f:/Python/MegabonkReroll/src/core/build_progression.py)

`_row_sort_key` (line 357): Late rows that are not fully satisfied sort among active rows (group 0/1, not group 3). Late + fully satisfied → group 3 but always shown.

---

## Feature 3: Dynamic Radius Cap

### Supported Items Catalog

#### [NEW] catalog in [build_progression.py](file:///f:/Python/MegabonkReroll/src/core/build_progression.py)

```python
CAP_SUPPORTED_ITEMS: frozenset[str] = frozenset({
    "Spicy Meatball",
    "Grandma's Secret Tonic",
})

def calculate_radius_cap(size: float) -> int | None:
    """Smallest n where Radius(n, S) = min(max((3+n)*S, 1), 8) reaches 8."""
    if size <= 0:
        return None
    n = max(1, math.ceil(8.0 / size - 3))
    # Verify due to float precision
    while min(max((3 + n) * size, 1), 8) < 8 and n < 10000:
        n += 1
    return n
```

### Core Data Model

#### [MODIFY] [build_progression.py](file:///f:/Python/MegabonkReroll/src/core/build_progression.py)

**`BuildRequirement`**: add `cap_tracking: bool = False`.

**`BuildProgressionRow`**: add `cap_unresolved: bool = False`.
True when cap_tracking=True but Size unavailable → display `{current}/—`.

### Memory Client

#### [MODIFY] [player_stats_client.py](file:///f:/Python/MegabonkReroll/src/infra/memory/player_stats_client.py)

Add `get_size()` following `get_luck()` pattern (line 418), with 3 immediate retry attempts and cache invalidation between each:

```python
def get_size(self, owner_stats: int | None = None) -> float | None:
    """Read Size (stat 9) with up to three physical attempts."""
    owner_stats = owner_stats or self._resolve_owner_stats()
    spec = PLAYER_STAT_SPEC_BY_LABEL.get("Size")
    if spec is None or spec.offset is None:
        return None
    for _ in range(3):
        try:
            entries = self._resolve_stats_entries_cached(owner_stats)
            return self.memory.read_float(entries + spec.offset)
        except MemoryReadError:
            self._cached_stats_entries = 0  # allow pointer re-resolve
    return None
```

### Read Sources

#### [MODIFY] [read_sources.py](file:///f:/Python/MegabonkReroll/src/app/read_sources.py)

Add constant: `SIZE = "memory.player_stats.size"` (alongside existing `LUCK`).

### Tracker & Snapshot

#### [MODIFY] [live_run.py](file:///f:/Python/MegabonkReroll/src/core/tracker/live_run.py)

Following `FastLuck` pattern:
- Add `FastSize` dataclass: `captured_at: float = 0.0, size: float | None = None`
- Add `FAST_SIZE_TTL_SECONDS = 3.0`
- Add `_fast_size: FastSize` to run state
- Add `update_fast_size(size)`, `_fresh_fast_size_unlocked()` methods
- Publish in `runtime_snapshot()`

#### [MODIFY] [snapshots.py](file:///f:/Python/MegabonkReroll/src/core/tracker/snapshots.py)

Add `size: float | None = None` to `RuntimeStateSnapshot`.

### Refresh Tasks

#### [MODIFY] [refresh_tasks.py](file:///f:/Python/MegabonkReroll/src/app/refresh_tasks.py)

Add `_publish_fast_size(context)`:
```python
def _publish_fast_size(self, context):
    if not self._build_progression_service().has_cap_demand():
        return
    try:
        client = self._fast_task_client(context)
        owner_stats = self._fast_task_owner_stats(context)
        size = read_memory_source(context, SIZE, lambda: client.get_size(owner_stats))
    except Exception:
        size = None
    update = getattr(self._tracker(), "update_fast_size", None)
    if callable(update):
        update(size)
```

Call in `_refresh_passive_items_task` alongside `_publish_fast_luck`.

In `_should_refresh_passive_items`: add `or self._build_progression_service().has_cap_demand()`.

### Service: Cap Capture Logic

#### [MODIFY] [build_progression.py](file:///f:/Python/MegabonkReroll/src/app/build_progression.py)

`BuildProgressionService`: add per-run state:
```python
@dataclass
class _CapState:
    last_item_count: int = 0
    captured_size: float | None = None
    calculated_cap: int | None = None

_cap_states: dict[str, _CapState]  # requirement_id -> state
```

Before evaluation, calculate effective caps:
```python
def _resolve_caps(self, runtime: RuntimeStateSnapshot) -> dict[str, int | None]:
    """Resolve dynamic cap targets. Only changes on item-count change."""
    item_counts = count_items(runtime.fast_items or ...)
    effective_caps: dict[str, int | None] = {}

    for req in self._definition.requirements:
        if not req.cap_tracking:
            continue
        current = item_counts.get(req.target, 0)
        state = self._cap_states.get(req.id, _CapState())

        if current < 1:
            state = _CapState()  # reset to first stage
        elif current != state.last_item_count:
            # Item count changed — capture Size from this pass
            size = runtime.size
            if size is not None and size > 0:
                cap = calculate_radius_cap(size)
                cap = max(cap, current) if cap else current  # never lower than owned
                state = _CapState(current, size, cap)
            else:
                state = _CapState(current, None, None)  # unresolved
        else:
            state = _CapState(current, state.captured_size, state.calculated_cap)

        self._cap_states[req.id] = state
        effective_caps[req.id] = state.calculated_cap

    return effective_caps
```

Before calling `evaluate_build_progression`, build an effective definition where cap-tracked items have `max_required` set to the resolved cap (or None if unresolved).

Add `has_cap_demand() -> bool`: returns True if active definition has any cap_tracking=True requirements.

### Config

#### [MODIFY] [config.py](file:///f:/Python/MegabonkReroll/src/app/config.py)

In `normalize_build_definition_config`:
- Read `raw.get("cap_tracking")` as bool
- Only valid when `kind == "item"` and `target in CAP_SUPPORTED_ITEMS`
- When `cap_tracking=True`: force `required=1`, preserve `max_required` for restore on toggle-off

### UI Editor

#### [MODIFY] [build_progression.py](file:///f:/Python/MegabonkReroll/src/ui/dialogs/build_progression.py)

For items in `CAP_SUPPORTED_ITEMS`:
- Show `self.cap_checkbox = QCheckBox("Track radius cap")` below Min/Max row
- When checked:
  - Replace Min/Max with `First copy [1]` (disabled) + `Cap [Auto]` (disabled)
  - Preserve existing manual max_required in hidden state
- When unchecked:
  - Restore manual Min/Max controls with preserved values

For items NOT in `CAP_SUPPORTED_ITEMS`: do not show checkbox.

### Evaluator: Cap-Unresolved State

#### [MODIFY] [build_progression.py](file:///f:/Python/MegabonkReroll/src/core/build_progression.py)

When evaluating a cap-tracked item with `max_required=None` (unresolved):
- `min_met = current >= 1` (yes, first copy received)
- `satisfied = False` (cap unknown, cannot confirm)
- `required_display = "—"` → display `1/—`
- `status = RequirementStatus.NEUTRAL`
- `row.cap_unresolved = True`

---

## Projections: Minimal Changes

#### [MODIFY] [build_progression.py](file:///f:/Python/MegabonkReroll/src/projections/build_progression.py)

`value = f"{row.current_display}/{row.required_display}"` — **unchanged**, evaluator sets correct display values.

Add to payload row:
```python
"late": row.late,
"cap_unresolved": row.cap_unresolved,
```

Add to payload:
```python
"late_complete": snapshot.late_complete,
```

---

## Tests

#### [MODIFY] [test_build_progression.py](file:///f:/Python/MegabonkReroll/src/tests/test_build_progression.py)

### Feature 1: Min/Max

| Test | Проверяет |
|------|-----------|
| `test_max_required_shows_min_target_before_min_met` | `0/1` when current=0, min=1, max=15 |
| `test_max_required_switches_to_max_after_min_met` | `1/15` when current=1 |
| `test_max_required_satisfied_only_at_max` | SATISFIED only at current≥15 |
| `test_max_required_deadline_only_on_min_stage` | Deadline active at 0/1, neutral at 1/15 |
| `test_max_required_losing_items_below_min_reactivates_deadline` | Drop below min → deadline returns |
| `test_max_equal_to_min_is_valid` | Max=Min=5 → standard single-target behavior |
| `test_config_normalization_validates_max_required` | Positive int, ≥ required; invalid → None |
| `test_config_normalization_drops_max_for_non_items` | stat/progress ignore max_required |
| `test_export_import_preserves_max_required` | JSON round-trip |
| `test_editor_shows_min_max_for_items_only` | Min/Max visible for items, Required for stats |

### Feature 2: Late-Completed

| Test | Проверяет |
|------|-----------|
| `test_requirement_satisfied_after_deadline_is_late` | Overdue→satisfied = late=True |
| `test_requirement_satisfied_before_deadline_is_not_late` | On-time = late=False |
| `test_late_flag_persists_through_max_stage` | min late + working on max → late=True |
| `test_late_rows_not_hidden_by_show_completed` | Late rows always in payload |
| `test_late_complete_build_state` | All done + some late → late_complete=True |
| `test_late_symbol_uses_orange_in_projections` | Late flag propagates to overlay payloads |
| `test_twitch_groups_late_separately` | Late rows in separate group |
| `test_run_reset_clears_late_state` | New run → late dict cleared |

### Feature 3: Dynamic Cap

| Test | Проверяет |
|------|-----------|
| `test_cap_formula_basic_calculation` | `calculate_radius_cap(1.0)` → 5 (since (3+5)*1=8) |
| `test_cap_formula_small_size` | Small S → larger n |
| `test_cap_formula_large_size` | Large S → n=1 |
| `test_cap_captures_size_on_first_copy` | 0→1 copies triggers Size capture |
| `test_cap_recalculates_on_item_count_change` | Count change → new capture |
| `test_cap_unresolved_when_size_unavailable` | Failed Size read → `1/—` |
| `test_cap_unresolved_not_retroactively_fixed` | Later Size success without count change → stays `1/—` |
| `test_cap_never_lower_than_owned` | cap=3, own 5 → target=5 |
| `test_cap_tracking_preserves_manual_max` | Toggle off restores manual max |
| `test_get_size_retries_three_times` | Memory client 3 attempts with cache reset |
| `test_size_source_only_when_cap_demand` | No cap rules → SIZE not read |
| `test_config_normalization_cap_tracking_only_supported_items` | Unknown items → cap_tracking=False |

---

## Open Questions

> [!IMPORTANT]
> **Late symbol:**
> Спецификация говорит "orange leading status symbol" но не уточняет какой именно символ.
> Предлагаю: `"✓"` (тот же чекмарк что и satisfied, но оранжевый `#F97316`).
> Это визуально показывает "выполнено, но с оговоркой" без введения нового символа.
> Альтернатива: `"!"` (но конфликтует с warning) или `"⚑"`.

> [!IMPORTANT]
> **Late build-complete display:**
> Предлагаю: `"! BUILD COMPLETE · MM:SS"` оранжевым (`#F97316`), вместо зелёного `"✓ BUILD COMPLETE"`.
> Альтернатива: `"✓ BUILD COMPLETE (LATE) · MM:SS"` — более явно, но длиннее.

> [!NOTE]
> **Editor badge для min/max:**
> При заданном max — `Min {n} · Max {m}`. Без max — `Required {n}` (как сейчас).

## Verification Plan

### Automated Tests
```bash
cd f:\Python\MegabonkReroll
python -m pytest src/tests/test_build_progression.py -v
```

### Manual Verification
- Build editor: Min/Max контролы для items, Required для stats
- Cap checkbox для Spicy Meatball / Grandma's Secret Tonic
- OBS overlay: green/orange/neutral count display, late symbol
- In-Game overlay: same states
- Twitch `!build`: late grouping
- Export/import build с max_required и cap_tracking
