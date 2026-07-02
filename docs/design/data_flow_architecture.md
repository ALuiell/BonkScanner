# BonkScanner Data Flow Architecture

## 1. Introduction

- **Why this document exists:** To provide a structural overview of the data pipelines in the BonkScanner / MegabonkReroll project. It helps developers understand where data originates, how often it is updated, where the state is stored, and who consumes it.
- **What it describes:** Data sources, refresh loops (fast vs. slow), state repositories, and data consumers.
- **How to read it:** Follow the flow from Raw Sources -> Updaters -> State Stores -> Consumers. Reference the architecture diagram and the summary table for quick lookups.

```mermaid
flowchart TD
    %% Sources
    subgraph Sources [Data Sources]
        GM[Game Memory]
        CFG[User Config / config.py]
    end

    %% Fast Refresh Loop
    subgraph FastRefresh [Fast Refresh Path 500ms]
        FastTimer[update_chaos_tome_tracker_timer]
        FastTimer -->|Read Kills, Timer, Powerups, Chaos| GM
    end

    %% Slow Refresh Loop
    subgraph SlowRefresh [Slow Refresh Path 10s]
        SlowTimer[update_player_stats_timer]
        SlowTimer -->|Read Items, Weapons, Banishes| GM
    end

    %% State Owners
    subgraph StateOwners [State / Source of Truth]
        LRT(LiveRunTracker)
        FLS(Full Live Snapshot)
        OS(OverlayStateStore)
        VODR(VodRecorder)
    end

    FastTimer -->|Update KPS, Chaos, Chests| LRT
    SlowTimer -->|Emit Snapshot| FLS
    SlowTimer -->|Sync Items| LRT
    LRT -->|Build State| OS
    FLS -->|Capture at Intervals| VODR

    %% Consumers
    subgraph Consumers [Data Consumers]
        UI[Live Stats Tab UI]
        OBS[OBS Overlay / Widgets]
        TB[Twitch Bot]
        VODC[VOD / Compare Runs]
    end

    FLS --> UI
    LRT --> UI
    LRT --> TB
    OS -.-> OBS
    VODR --> VODC
```

## 2. Data Sources (Raw Sources)

For each feature, the data begins its journey here.

- **Game Memory / Memory Readers**
  - **What it is:** Direct memory reading of the target game process.
  - **Code location:** `src/memory.py`, `src/gui_player_stats.py` (e.g., `_get_player_stats_client()`).
  - **Data extracted:** Player stats (luck, damage), run timer, mob kills, items, weapons, chaos tome level, expected chest inputs, powerup tracking snapshots, banishes.
- **Config / User Config**
  - **What it is:** Configuration settings read from disk or defined at runtime.
  - **Code location:** `src/config.py` (`OVERLAY`, `TWITCH_BOT`, etc.).
  - **Data extracted:** Refresh intervals (`PLAYER_STATS_REFRESH_MS`, `CHAOS_TOME_TRACKER_INTERVAL_MS`), overlay tracked item rules, Twitch bot commands.
- **Runtime-derived Values**
  - **What it is:** Values calculated dynamically based on raw memory data over time.
  - **Code location:** `src/live_run_tracker.py`, `src/run_summary.py`.
  - **Data extracted:** Kills per Second (KPS), stage summaries, RPM (rerolls per minute).
- **VOD Snapshots**
  - **What it is:** Saved JSON records of completed runs.
  - **Code location:** `src/vod_storage.py`.
  - **Data extracted:** Full historical snapshots for the Compare Runs UI.

## 3. Updaters / Refresh Loops

This section defines the active logic that pulls from data sources and pushes to state stores.

- **Slow Full Live Stats Refresh**
  - **Code location:** `src/gui_player_stats.py` (`update_player_stats_timer`)
  - **Updates:** Full live snapshot including items, weapons, banishes, and general player stats.
  - **Cadence:** Every 10 seconds (`PLAYER_STATS_REFRESH_MS`).
  - **Triggers:** Active when the Live Stats tab is open, recording is armed, or overlay/Twitch bot is active.
  - **Destination:** Emits full live snapshots, updates LiveRunTracker with stage transitions and item updates.
- **Fast KPS, Chaos, and Powerup Refresh**
  - **Code location:** `src/gui_player_stats.py` (`update_chaos_tome_tracker_timer`, `refresh_chaos_tome_tracker_now`)
  - **Updates:** Kills, run timer, Chaos Tome modifiers, Powerup snapshots, Chest counters.
  - **Cadence:** Every 500 ms (`CHAOS_TOME_TRACKER_INTERVAL_MS`).
  - **Triggers:** Active under same conditions as the slow refresh.
  - **Destination:** Directly pushes data into `LiveRunTracker`.
- **Overlay State Updates**
  - **Code location:** `src/gui_overlay.py` (`update_overlay_state_from_tracker`)
  - **Updates:** Rebuilds the combined JSON payload for the web-based OBS overlay.
  - **Cadence:** On-demand after fast or slow refreshes.
  - **Destination:** `OverlayStateStore`.
- **VOD Snapshot Capture**
  - **Code location:** `src/gui_player_stats.py` -> `src/vod_storage.py`
  - **Updates:** Records historical run states for later review.
  - **Cadence:** Configurable, typically every 30 seconds (`PLAYER_STATS_RECORD_INTERVAL_SECONDS`).
- **Twitch Bot Command Read Path**
  - **Code location:** `src/twitch_bot.py`
  - **Updates:** Pulls stats directly from the state stores to respond to chat.
  - **Cadence:** Asynchronous socket loop, on-demand.

## 4. State Stores / Source of Truth

This describes where the most authoritative version of the data lives.

- **LiveRunTracker (`src/live_run_tracker.py`)**
  - **What it stores:** Tracks dynamic runtime metrics: kills history, fast-moving KPS, Chaos Tome state, Powerup mapping, chest open/purchased logic, and custom tracked items.
  - **Source of truth for:** Fast-refresh features, historical kills/KPS timeline, stage-specific context.
- **Full Live Snapshot (in-memory variables in `gui_player_stats.py`)**
  - **What it stores:** The heavy payload read every 10 seconds (complete item list, weapons, banishes, stage transitions).
  - **Source of truth for:** Slow-moving heavy data fields that don't need real-time visualization.
- **OverlayStateStore (`src/overlay_state.py`)**
  - **What it stores:** The exact JSON dictionary representation of the overlay UI, derived from LiveRunTracker.
  - **Source of truth for:** HTTP clients (OBS).
- **VodRecorder (`src/vod_storage.py`)**
  - **What it stores:** Serialized historical snapshots of runs on disk.
  - **Source of truth for:** The "Compare Runs" tab and the "VODs" list.

## 5. Data Consumers

This defines who is reading the data at the end of the pipeline.

- **Live Stats Tab** (`src/gui_player_stats.py`)
  - **Reads:** `LiveRunTracker` (for KPS/Chaos/Powerups) and direct memory snapshots (for Items/Banishes/Weapons).
  - **Cadence:** Updated directly by the GUI loops (500ms / 10s).
- **OBS Overlay / Widgets** (`src/overlay_server.py`)
  - **Reads:** `OverlayStateStore` (via HTTP endpoints).
  - **Cadence:** Clients poll the HTTP server or connect via server-side events.
- **Twitch Bot** (`src/twitch_bot.py`)
  - **Reads:** Primarily `LiveRunTracker` and `config.TWITCH_BOT`.
  - **Cadence:** On-demand when a user types a command in chat.
- **Recordings / Compare Runs** (`src/gui_app.py`, `src/gui_player_stats.py`)
  - **Reads:** `VodRecorder` snapshots.
  - **Cadence:** Interactive user inspection.

## 6. Metric / Feature Tracking Matrix

| Metric / Feature | Raw Source | Updater / Refresh Path | Refresh Interval | State Owner | Consumers |
|------------------|------------|------------------------|------------------|-------------|-----------|
| KPS | Game memory (kills, timer) | Fast KPS refresh | 500 ms | LiveRunTracker | Live Stats, Overlay, Twitch bot |
| Mob kills | Game memory | Fast KPS refresh | 500 ms | LiveRunTracker | Live Stats, Overlay, VOD |
| Run timer | Game memory | Fast KPS refresh | 500 ms | LiveRunTracker | Live Stats, Overlay, VOD, Twitch bot |
| Player stats | Game memory | Slow full refresh | 10 s | Full live snapshot | Live Stats, Overlay, VOD |
| Tracked items | Game memory | Slow full refresh | 10 s | LiveRunTracker / Snapshot | Live Stats, Overlay |
| Stage summary | Derived from items/timer | Slow full refresh | 10 s | Full live snapshot | Live Stats, Compare Runs |
| Banishes | Game memory | Slow full refresh | 10 s | Full live snapshot | Live Stats |
| Chaos tome | Game memory | Fast Chaos refresh | 500 ms | LiveRunTracker | Live Stats, Overlay, Twitch bot |
| Powerups | Game memory | Fast Powerup refresh | 500 ms | LiveRunTracker | Live Stats |
| Chest counters | Game memory | Fast Chest refresh | 500 ms | LiveRunTracker | Live Stats |
| VOD snapshot data | In-memory snapshots | VodRecorder interval | ~30 s | VodRecorder | VOD list, Compare Runs |
| Overlay widget data | LiveRunTracker + config | Overlay state builder | ~500 ms | OverlayStateStore | OBS overlay / Widgets |

## 7. Current Architectural Observations

- **Clear Fast/Slow Separation:** The architecture successfully splits heavy memory reads (Items/Weapons) into a 10s slow lane and fast-moving metrics (KPS/Timer/Kills) into a 500ms fast lane. This minimizes game-process read overhead.
- **LiveRunTracker Evolution:** `LiveRunTracker` is naturally evolving into the primary state owner for all runtime derived logic.
- **Blurred Boundaries:** The boundary between what lives strictly in the "Slow Full Snapshot" lane versus what is aggregated into `LiveRunTracker` can occasionally be blurred (e.g., Tracked Items, Stage Summary).
- **Needs Confirmation:** Whether the Twitch Bot needs to pull any data from the slow lane, or if it naturally gets all required data by reading strictly from `LiveRunTracker` snapshots.

## 8. Suggested Future Maintenance Rule

When adding a new realtime feature, developers should immediately define:
- **Raw source:** Is it derived logic or direct memory read?
- **Updater cadence:** Can it be updated every 10s (slow lane) or does it need 500ms updates (fast lane)?
- **State owner:** Should it be tracked in `LiveRunTracker` (accumulated state) or just read statelessly into the live snapshot?
- **Consumers:** Will this be used by OBS, Twitch Bot, or just the local UI?
