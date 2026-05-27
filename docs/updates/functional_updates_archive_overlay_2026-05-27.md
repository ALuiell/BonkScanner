# Functional Updates Overlay Archive

Date: 2026-05-27

This file archives the previous long-form handoff for the first overlay/live
tracker concept so `functional_updates.md` can stay focused on the latest
implementation direction.

Archived item:

- `4. Add A Local OBS Overlay Builder Backed By A Live Run Tracker`

## 4. Add A Local OBS Overlay Builder Backed By A Live Run Tracker

Status: `[Archived]`

Owner-facing summary:

- Build this as a local `OBS` / `Streamlabs` browser-source overlay, not as a
  Twitch API integration.
- The overlay should be configurable from a new `Overlay` tab.
- The overlay must work without `.jsonl` recording enabled.
- Any metric that needs history, such as `Stage Summary` or `Anvils on map 1`,
  should be powered by a new in-memory live run tracker.

### Recommended Decision

Implement the feature as three separate layers:

1. `Live snapshot source`
   - The existing live stats refresh already reads the game process and
     produces the raw ingredients.
   - The implementation should normalize those values once per refresh.
   - The normalized snapshot should then feed both recording and overlay
     analytics.

2. `Live run tracker`
   - A new in-memory object that stores short current-run history.
   - It computes stage summary, tracked item counters, item gains, per-stage
     kills, and other stream-facing derived metrics.
   - It never writes files and does not depend on recording state.

3. `Overlay server + UI builder`
   - A local loopback HTTP server serves browser overlay HTML and JSON state.
   - The desktop `Overlay` tab controls enabled widgets, tracked items, and
     display options.
   - `OBS` consumes the overlay URL as a Browser Source.

This is the cleanest implementation because it avoids turning `vod_storage.py`
into a live analytics dependency. Recording remains persistence. Overlay
tracking becomes live analytics.

### Non-Goals For The First Version

- Do not integrate with Twitch API, chat, EventSub, OAuth, or cloud services.
- Do not require a public web server.
- Do not require users to enable player stats recording.
- Do not implement WebSocket first. Polling a local JSON endpoint every
  `250-500ms` is enough for MVP and is easier to debug in `OBS`.
- Do not build a full drag-and-drop layout editor in the first pass.
- Do not try to count every possible advanced metric before the tracker shape is
  stable.

### Existing Code Anchors

Start implementation from these places:

- `gui_player_stats.py`
  - `_read_live_player_stats_data()` already reads:
    - stats
    - items
    - weapons
    - tomes
    - banishes
    - damage sources
    - run timer
    - stage timer
    - mob kills
    - player level
    - map seed
    - current stage pointer
  - `refresh_live_player_stats_now()` is the best first integration point for
    feeding the live tracker.
  - Current non-recording UI path passes `stage_summary_rows=None`.
  - Current recording path builds stage summary from
    `self.player_stats_vod_snapshots`.

- `gui_app.py`
  - `MegabonkApp.__init__()` owns long-lived runtime state.
  - Add tracker/server references here, for example:
    - `self.live_run_tracker`
    - `self.overlay_state`
    - `self.overlay_server`

- `vod_storage.py`
  - Keep this focused on saved `.jsonl` recordings.
  - Do not make overlay analytics depend on `VodRecorder`.

- `player_stats.py`
  - Has snapshot-like dataclasses and runtime reader types.
  - Avoid putting overlay-specific UI or server logic here.

- `gui_layout.py`
  - Add the new `Overlay` tab near `Live Stats`, `Recordings`, and
    `Compare Runs`.

- `config.py`
  - Add default config loading/persistence helpers for overlay settings.

### New Files To Add

Recommended files:

- `live_run_tracker.py`
  - Owns in-memory run history and derived metrics.
  - Pure Python, no Qt imports, no HTTP imports.
  - Unit-testable without the GUI.

- `overlay_state.py`
  - Defines overlay-facing dataclasses and JSON serialization.
  - Pure Python.
  - May include config normalization for widget settings.

- `overlay_server.py`
  - Owns local HTTP server lifecycle.
  - Uses only stdlib first: `http.server`, `socketserver`, `threading`,
    `json`, `mimetypes`, `pathlib`.
  - Binds to `127.0.0.1` by default.

- `gui_overlay.py`
  - `OverlayMixin` for the new tab and controls.
  - Keeps UI code out of tracker/server modules.

- `media/overlay/`
  - Static overlay assets:
    - `index.html`
    - `overlay.css`
    - `overlay.js`
  - Use plain browser code first. No build step.

### Data Model

Add a normalized snapshot model that is independent from recording:

```python
@dataclass(frozen=True)
class LiveRunSnapshot:
    captured_at: float
    stats: dict[str, PlayerStatValue]
    items: tuple[str, ...] = ()
    items_available: bool = True
    weapons: tuple[WeaponSnapshot, ...] = ()
    weapons_available: bool = False
    tomes: tuple[TomeSnapshot, ...] = ()
    tomes_available: bool = False
    banishes: tuple[str, ...] = ()
    damage_sources: tuple[DamageSourceSnapshot, ...] = ()
    damage_sources_available: bool = False
    chests_per_minute: float | None = None
    game_time_seconds: float | None = None
    stage_time_seconds: float | None = None
    mob_kills: int | None = None
    player_level: int | None = None
    map_seed: int | None = None
    stage_ptr: int = 0
```

### Live Tracker Responsibilities

- Accept `LiveRunSnapshot` every time live stats refresh succeeds.
- Keep a bounded list of snapshots for the current run.
- Reset when a true new run is detected.
- Compute stage summary rows.
- Compute tracked item counters from item deltas.
- Expose a JSON-friendly overlay state.

### Local HTTP Server

- Serve `/overlay`.
- Serve `/api/overlay-state`.
- Bind only to `127.0.0.1`.
- Stop cleanly on app shutdown.

### MVP Acceptance Criteria

- Overlay renders in `OBS` via a local browser URL.
- Overlay state updates without recording enabled.
- Stage summary works without recording.
- At least one tracked-item metric works.
