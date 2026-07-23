from __future__ import annotations

import src

import types
import unittest
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import threading
import time

import gui_app
from ui import dialogs as gui_dialogs
import gui_in_game_overlay
from ui import layout as gui_layout
import gui_overlay
import gui_run_control
import gui_scanner
from session_stats import SessionStats
from ui import shared as gui_shared
from ui import styles as gui_styles
import infra.process as infra_process
import ui.tabs.player_stats.live_stats as ui_player_stats_live
import ui.tabs.player_stats.recordings as ui_player_stats_recordings
import ui.tabs.templates.panel as ui_tabs_templates_panel
from app.snapshot_store import LiveSnapshotStore, live_snapshot_store
from app.run_lifecycle import run_lifecycle
from app.refresh_tasks import (
    ensure_refresh_coordinator,
    player_stats_refresh_required,
    refresh_tasks,
)
from tests.support.compare_runs import build_compare_runs_tab
from tests.support.scanner import build_pair
from tests.support.refresh_tasks import build_refresh_tasks
from tests.support.run_lifecycle import build_run_lifecycle, install_run_lifecycle
from core.tracker.chaos import CHAOS_TOME_GAME_STAT_ORDER
from ui.tabs.player_stats.live_stats import LiveStatsTab
from tests.support.player_stats import (
    RecordingItemsSectionView,
    RecordingStatCardsView,
    items_section_over,
    attach_player_stats_view,
    build_live_stats_tab,
    build_recordings_tab,
)
from ui.tabs.player_stats.stat_cards import StatCardsView, chaos_stats_in_game_order
from ui.tabs.compare_runs import tab as compare_runs_tab
from app import config, player_stats_refresh
from app.player_stats_memory import player_stats_memory
from gui_app import MegabonkApp
from ui.dialogs import (
    SettingsDialog,
    TemplateManagerDialog,
    TwitchCommandSettingsDialog,
)
from app.vod_capture import (
    PLAYER_STATS_RECORDING_SEED_GRACE_SECONDS,
    _stage_index_signals_new_run,
    vod_capture,
)
from tests.support.vod_capture import build_vod_capture
from projections.item_sort import (
    ITEM_SORT_DEFAULT,
    ITEM_SORT_RARITY_ASC,
    ITEM_SORT_RARITY_DESC,
)
from infra.memory.reader import MemoryReadError, ProcessNotFoundError
from app.player_stats_view import player_stats_view
from core.game_state import RuntimeGameMode, RuntimeGameState
from core.tracker.live_run import LiveRunTracker
from app.coordinator import AppCoordinator, RefreshLoop
from app.refresh_coordinator import RefreshTickContext
from PySide6.QtCore import QRect
from projections import formatting

# The modules `gui.py`'s `_PATCH_COMPAT_MODULES` used to propagate a `setattr`
# across. Step 15 deletes that facade, so the propagation moves here -- to the
# tests, which are the only thing that ever needed it. Production code imports
# names from wherever they actually live.
_PATCH_TARGETS = (
    gui_app,
    gui_dialogs,
    gui_layout,
    gui_overlay,
    gui_run_control,
    gui_scanner,
    gui_shared,
    gui_styles,
    ui_tabs_templates_panel,
    infra_process,
    ui_player_stats_live,
    ui_player_stats_recordings,
)


def make_client_coordinator() -> SimpleNamespace:
    """A minimal `AppCoordinator` stand-in for `object.__new__` app doubles.

    Step 20h removed the `__dict__` fallback from `MegabonkApp`'s two client
    properties, so a double that assigns `player_stats_client` needs a real
    carrier for it. The fields here are exactly the `AppCoordinator.__init__`
    ones the owner-taking resolvers read *unconditionally* once a coordinator
    exists: `snapshot_store` (`app/snapshot_store.py`) and `refresh_coordinator`
    (`app/refresh_tasks.py`), plus the two clients. The other six resolvers
    `getattr(..., None)` first and then `setattr` their service, and a
    `SimpleNamespace` takes that write exactly like `AppCoordinator` does.

    A real `AppCoordinator` would also build a `LiveRunTracker`, a
    `LocalOverlayServer` and a `VodRecorder`, and would rewire
    `vod_storage`'s settings as a side effect -- none of which these doubles
    want, and the recorder in particular is the fake they install themselves.

    `client` joined the list at step 25d, when `MegabonkApp.client` lost its own
    `__dict__` fallback. It is here even though no surviving double assigns it,
    because of how the property fails without it: `_client_owner()` would return
    this namespace and the missing attribute would raise `AttributeError` *out of
    a property* -- which is precisely the condition that makes Python fall back
    to `__getattr__`, and `MegabonkApp.__getattr__` forwards to `self.window`. A
    double that read `app.client` would be answered by a widget instead of
    failing. That is the silent wrong answer the header above `_client_owner`
    describes, not a hypothetical.
    """
    return SimpleNamespace(
        client=None,
        player_stats_client=None,
        player_stats_game_data_client=None,
        snapshot_store=LiveSnapshotStore(),
        refresh_coordinator=None,
    )


@contextmanager
def patch_everywhere(name, value=None, **kwargs):
    """Patch `name` on every module that defines it.

    Replaces `_GuiFacadeModule.__setattr__`, which did exactly this --
    `for module in _PATCH_COMPAT_MODULES: if hasattr(module, name): setattr(...)`.
    A name like `win32gui` is read by two modules (`gui_run_control` and
    `infra.process`, since step 10c split that code path), so patching only one
    of them silently leaves half the path live.
    """
    targets = [m for m in _PATCH_TARGETS if hasattr(m, name)]
    if not targets:
        raise AssertionError(f"no module defines {name!r} -- did it move?")
    # One object, propagated -- not one mock per module. The facade assigned a
    # single value across every module, so a test that asserts on the mock sees
    # calls made through any of them.
    if value is None:
        value = MagicMock(**kwargs)
    with ExitStack() as stack:
        for module in targets:
            stack.enter_context(patch.object(module, name, value))
        yield value


class FakeEntry:
    def __init__(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def text(self) -> str:
        return self.value

    def setText(self, value: str) -> None:
        self.value = value


class FakeVar:
    def __init__(self, value: bool) -> None:
        self.value = value

    def get(self) -> bool:
        return self.value

    def set(self, value: bool) -> None:
        self.value = value


class FakeSpinBox:
    def __init__(self, value: int) -> None:
        self._value = value

    def value(self) -> int:
        return self._value

    def setValue(self, value: int) -> None:
        self._value = value


class FakeComboBox:
    def __init__(self, value: str) -> None:
        self.value = value

    def currentText(self) -> str:
        return self.value


class FakeCheckbox:
    def __init__(self, value: bool) -> None:
        self.value = value

    def isChecked(self) -> bool:
        return self.value

    def setChecked(self, value: bool) -> None:
        self.value = value


class FakeSettingsMaster:
    def __init__(self) -> None:
        self.events: list[str] = []

    def setup_hotkeys(self) -> None:
        self.events.append("setup_hotkeys")

    def update_status_ui(self) -> None:
        self.events.append("update_status_ui")

    def apply_run_control_mode(self) -> None:
        self.events.append("apply_run_control_mode")

    def log(self, _message: str, tag: str | None = None) -> None:
        del tag
        self.events.append("log")


class FakeThread:
    def __init__(self, *, target: object, args: tuple[object, ...] = (), daemon: bool) -> None:
        self.target = target
        self.args = args
        self.daemon = daemon
        self.started = False

    def start(self) -> None:
        self.started = True

    def is_alive(self) -> bool:
        return self.started


class FakeAliveThread:
    def is_alive(self) -> bool:
        return True


class FakeLabel:
    def __init__(self, text: str = "") -> None:
        self.value = text

    def setText(self, text: str) -> None:
        self.value = text

    def text(self) -> str:
        return self.value


class FakeControl:
    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)

    def isEnabled(self) -> bool:
        return self.enabled


class FakeOverlayTimer:
    def __init__(self) -> None:
        self.start_calls = 0
        self.stop_calls = 0
        self.interval = None
        self.callback = None
        self.timeout = SimpleNamespace(connect=self._connect)

    def _connect(self, callback) -> None:
        self.callback = callback

    def setInterval(self, interval: int) -> None:
        self.interval = interval

    def start(self) -> None:
        self.start_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1


class FakeOverlayServer:
    def __init__(self, *, port: int = 17845) -> None:
        self.port = port
        self.is_running = False
        self.last_error = None

    def start(self) -> None:
        self.is_running = True

    def stop(self) -> None:
        self.is_running = False


def build_overlay_test_component(*, template_stats=None, session_rerolls: int = 0):
    tracker = LiveRunTracker()
    server = FakeOverlayServer()
    state_store = SimpleNamespace(set_state=MagicMock())
    coordinator = SimpleNamespace(
        live_run_tracker=tracker,
        overlay_server=server,
        overlay_state_store=state_store,
        rebuild_overlay_server=lambda **kwargs: FakeOverlayServer(port=kwargs["port"]),
    )
    session_stats = SessionStats(
        tracker,
        template_stats=lambda: template_stats or {},
        rerolls=lambda: session_rerolls,
        snapshot_tracked_item_config=lambda: config.TWITCH_BOT,
    )
    overlay = gui_overlay.Overlay(
        coordinator,
        session_stats=session_stats,
        stats_tab=lambda: None,
        stats_tracked_items_label=lambda: None,
        overlay_tab_active=lambda: True,
        server_rebuilt=lambda _server: None,
    )
    return overlay


def build_in_game_overlay_test_component(
    *,
    tracker=None,
    is_scanning=lambda: False,
    is_recording=lambda: False,
    is_game_window_active=lambda _process_name: False,
    find_game_window=None,
):
    return gui_in_game_overlay.InGameOverlay(
        tracker=lambda: tracker,
        is_scanning=is_scanning,
        is_recording=is_recording,
        is_game_window_active=is_game_window_active,
        find_game_window=find_game_window,
        schedule=lambda callback: callback(),
        schedule_idle=lambda _callback: None,
        timer_factory=FakeOverlayTimer,
    )


class FakeInGameOverlayWindow:
    def __init__(self, *, visible: bool = False, edit_mode: bool = False) -> None:
        self._visible = visible
        self.edit_mode = edit_mode
        self.widgets = {}
        self.show_calls = 0
        self.hide_calls = 0
        self.sync_calls = 0

    def isVisible(self) -> bool:
        return self._visible

    def show(self) -> None:
        self._visible = True
        self.show_calls += 1

    def hide(self) -> None:
        self._visible = False
        self.hide_calls += 1

    def sync_geometry_to_target(self) -> None:
        self.sync_calls += 1

    def screen(self):
        return None


class FakeTabWidget:
    def __init__(self, active_tab: str) -> None:
        self.active_tab = active_tab

    def currentIndex(self) -> int:
        return 0

    def tabText(self, _index: int) -> str:
        return self.active_tab


class FakeKeyboardModule:
    def __init__(self) -> None:
        self.press_and_release_calls: list[str] = []
        self.add_hotkey_calls: list[tuple[str, object]] = []
        self.hook_calls: list[object] = []
        self.hook_remove_calls = 0
        self.unhook_all_calls = 0
        self._scan_codes: dict[str, int] = {}

    def press_and_release(self, key: str) -> None:
        self.press_and_release_calls.append(key)

    def key_to_scan_codes(self, key_name: str) -> tuple[int, ...]:
        normalized = key_name.strip().lower()
        if normalized not in self._scan_codes:
            self._scan_codes[normalized] = len(self._scan_codes) + 1
        return (self._scan_codes[normalized],)

    def parse_hotkey(self, hotkey: str):
        return tuple(
            tuple(self.key_to_scan_codes(key) for key in step.split("+"))
            for step in hotkey.split(",")
        )

    def hook(self, callback: object):
        self.hook_calls.append(callback)

        def remove() -> None:
            self.hook_remove_calls += 1

        return remove

    def add_hotkey(self, hotkey: str, callback: object):
        self.add_hotkey_calls.append((hotkey, callback))
        return lambda: None

    def unhook_all(self) -> None:
        self.unhook_all_calls += 1


class FakeRecordingRecorder:
    def __init__(self, *, is_recording: bool = True, should_capture: bool = False) -> None:
        self.is_recording = is_recording
        self.should_capture_value = should_capture
        self.start_calls: list[dict[str, object]] = []
        self.stop_calls = 0
        self.capture_calls: list[dict[str, object]] = []

    def start(self, *, name: str | None = None, seed: int | None = None) -> Path:
        self.is_recording = True
        self.start_calls.append({"name": name, "seed": seed})
        return Path(f"recording-{len(self.start_calls)}.jsonl")

    def stop(self) -> None:
        self.is_recording = False
        self.stop_calls += 1

    def should_capture(self) -> bool:
        return self.should_capture_value

    def capture(
        self,
        stats,
        items=(),
        weapons=(),
        tomes=(),
        banishes=(),
        damage_sources=(),
        *,
        chaos_tome=None,
        chests_per_minute=None,
        game_time_seconds=None,
        mob_kills=None,
        kps_at_capture=None,
        minute_avg_kps_at_capture=None,
        five_minute_avg_kps_at_capture=None,
        run_avg_kps_at_capture=None,
        player_level=None,
        map_seed=None,
        stage_ptr=0,
        stage_index=None,
        stage_time_seconds=None,
        chests_opened=None,
        chests_total=None,
        pots_total=None,
        paid_chests=None,
        key_procs=None,
        free_chests=None,
        keys_count=None,
        expected_key_procs=None,
        chests_opened_by_stage=None,
        chests_total_by_stage=None,
    ):
        snapshot = SimpleNamespace(
            stats=stats,
            items=tuple(items),
            weapons=tuple(weapons),
            tomes=tuple(tomes),
            chaos_tome=chaos_tome,
            banishes=tuple(banishes),
            damage_sources=tuple(damage_sources),
            chests_per_minute=chests_per_minute,
            game_time_seconds=game_time_seconds,
            mob_kills=mob_kills,
            kps_at_capture=kps_at_capture,
            minute_avg_kps_at_capture=minute_avg_kps_at_capture,
            five_minute_avg_kps_at_capture=five_minute_avg_kps_at_capture,
            run_avg_kps_at_capture=run_avg_kps_at_capture,
            player_level=player_level,
            map_seed=map_seed,
            stage_ptr=stage_ptr,
            stage_index=stage_index,
            stage_time_seconds=stage_time_seconds,
            chests_opened=chests_opened,
            chests_total=chests_total,
            pots_total=pots_total,
            paid_chests=paid_chests,
            key_procs=key_procs,
            free_chests=free_chests,
            keys_count=keys_count,
            expected_key_procs=expected_key_procs,
            chests_opened_by_stage=chests_opened_by_stage,
            chests_total_by_stage=chests_total_by_stage,
            time_label="00:00",
        )
        self.capture_calls.append(
            {
                "stats": stats,
                "items": tuple(items),
                "weapons": tuple(weapons),
                "tomes": tuple(tomes),
                "chaos_tome": chaos_tome,
                "banishes": tuple(banishes),
                "damage_sources": tuple(damage_sources),
                "chests_per_minute": chests_per_minute,
                "game_time_seconds": game_time_seconds,
                "mob_kills": mob_kills,
                "kps_at_capture": kps_at_capture,
                "minute_avg_kps_at_capture": minute_avg_kps_at_capture,
                "five_minute_avg_kps_at_capture": five_minute_avg_kps_at_capture,
                "run_avg_kps_at_capture": run_avg_kps_at_capture,
                "player_level": player_level,
                "map_seed": map_seed,
                "stage_ptr": stage_ptr,
                "stage_index": stage_index,
                "stage_time_seconds": stage_time_seconds,
                "chests_opened": chests_opened,
                "chests_total": chests_total,
                "pots_total": pots_total,
                "paid_chests": paid_chests,
                "key_procs": key_procs,
                "free_chests": free_chests,
                "keys_count": keys_count,
                "expected_key_procs": expected_key_procs,
                "chests_opened_by_stage": chests_opened_by_stage,
                "chests_total_by_stage": chests_total_by_stage,
            }
        )
        self.should_capture_value = False
        return snapshot


class FakeSeedStateClient:
    def __init__(self, states: list[object]) -> None:
        self.states = list(states)
        self.close_calls = 0

    def get_map_generation_state(self) -> SimpleNamespace:
        state = self.states.pop(0) if self.states else None
        if isinstance(state, SimpleNamespace):
            return state
        if isinstance(state, dict):
            return SimpleNamespace(
                map_seed=state.get("map_seed"),
                current_stage_ptr=state.get("current_stage_ptr", 0),
            )
        return SimpleNamespace(map_seed=state, current_stage_ptr=0)

    def close(self) -> None:
        self.close_calls += 1


class FakeCtypesFunction:
    def __init__(self, callback):
        self.callback = callback
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.callback(*args)


class FakeUser32:
    def __init__(self) -> None:
        self.attach_calls: list[tuple[int, int, bool]] = []
        self.keybd_event_calls: list[tuple[int, int, int, int]] = []
        self.AttachThreadInput = FakeCtypesFunction(self._attach_thread_input)
        self.keybd_event = FakeCtypesFunction(self._keybd_event)

    def _attach_thread_input(self, current_thread: int, target_thread: int, attach: bool) -> bool:
        self.attach_calls.append((current_thread, target_thread, attach))
        return True

    def _keybd_event(self, key: int, scan: int, flags: int, extra: int) -> None:
        self.keybd_event_calls.append((key, scan, flags, extra))


class FakeKernel32:
    def __init__(self, current_thread: int = 10) -> None:
        self.GetCurrentThreadId = FakeCtypesFunction(lambda: current_thread)


class FakeWindll:
    def __init__(self, user32: FakeUser32, kernel32: FakeKernel32) -> None:
        self.user32 = user32
        self.kernel32 = kernel32


class FakeForegroundGui:
    def __init__(self, *, fail_always: bool = False) -> None:
        self.fail_always = fail_always
        self.foreground_window = 222
        self.set_foreground_calls: list[int] = []
        self.show_window_calls: list[tuple[int, int]] = []
        self.bring_window_to_top_calls: list[int] = []

    def IsIconic(self, _window: int) -> bool:
        return False

    def ShowWindow(self, window: int, command: int) -> None:
        self.show_window_calls.append((window, command))

    def SetForegroundWindow(self, window: int) -> None:
        self.set_foreground_calls.append(window)
        if self.fail_always or len(self.set_foreground_calls) == 1:
            raise RuntimeError("foreground denied")
        self.foreground_window = window

    def GetForegroundWindow(self) -> int:
        return self.foreground_window

    def BringWindowToTop(self, window: int) -> None:
        self.bring_window_to_top_calls.append(window)


class FakeForegroundProcess:
    def GetWindowThreadProcessId(self, window: int) -> tuple[int, int]:
        thread_by_window = {
            111: 20,
            222: 30,
        }
        return thread_by_window.get(window, 40), 9000 + window


class GuiRunControlTests(unittest.TestCase):
    def test_completed_run_blocks_all_refresh_demands(self) -> None:
        app = SimpleNamespace(
            _is_live_stats_tab_active=lambda: True,
            player_stats_vod_recorder=SimpleNamespace(is_recording=True),
            _is_player_stats_recording_armed=lambda: True,
            overlay_should_refresh_live_stats=lambda: True,
            _in_game_overlay_requires_tracker_refresh=lambda: True,
            _is_twitch_bot_active=lambda: True,
        )

        install_run_lifecycle(app, completed_run=True)

        self.assertFalse(player_stats_refresh_required(app))
        self.assertFalse(refresh_tasks(app)._should_refresh_fast_kps())
        self.assertFalse(refresh_tasks(app)._should_refresh_powerup_tracker())
        self.assertFalse(refresh_tasks(app)._should_refresh_expected_chest_inputs())
        self.assertFalse(refresh_tasks(app)._should_refresh_chaos_tome())

    def test_core_run_demand_keeps_snapshot_and_expected_chests_active(self) -> None:
        app = SimpleNamespace(
            _is_live_stats_tab_active=lambda: False,
            player_stats_vod_recorder=SimpleNamespace(is_recording=False),
            _is_player_stats_recording_armed=lambda: False,
            overlay_should_refresh_live_stats=lambda: False,
            _is_twitch_bot_active=lambda: False,
            _twitch_command_refresh_active=lambda _command: False,
        )
        # Pause is an active run: `is_active_run` covers PAUSED_IN_GAME, which
        # is what keeps the snapshot cadence alive through a pause even though
        # `completed_run` is set.
        install_run_lifecycle(
            app,
            cached_state=RuntimeGameState(mode=RuntimeGameMode.PAUSED_IN_GAME),
            checked_at=10.0,
            completed_run=True,
        )
        # The `app._player_stats_refresh_required = lambda: MegabonkApp.
        # _player_stats_refresh_required(app)` stub that used to sit here is
        # gone with the method: `_should_refresh_full_player_snapshot` calls the
        # module-level `player_stats_refresh_required(self)` directly now. It was
        # also already dead -- `is_active_run()` is True under PAUSED_IN_GAME and
        # short-circuits the `or` before the predicate is reached, which is the
        # very thing this test asserts.

        self.assertTrue(refresh_tasks(app)._should_refresh_full_player_snapshot())
        self.assertTrue(refresh_tasks(app)._should_refresh_expected_chest_inputs())

    def test_core_lifecycle_probe_is_cached_and_marks_game_over_once(self) -> None:
        app = SimpleNamespace(
            live_run_tracker=SimpleNamespace(mark_run_completed=MagicMock()),
        )
        states = iter(
            (
                RuntimeGameState(mode=RuntimeGameMode.IN_GAME),
                RuntimeGameState(mode=RuntimeGameMode.GAME_OVER),
            )
        )
        reads: list[str] = []

        def read_activity_state(_context=None):
            reads.append("read")
            return next(states)

        player_stats_memory(app).read_player_stats_runtime_activity_state = read_activity_state
        player_stats_memory(app).close_player_stats_game_data_client = lambda: None
        # `run_lifecycle`'s activity reader now calls the real
        # `player_stats_memory(app)._read_player_stats_runtime_activity_state_safe`,
        # so the underlying read is stubbed on the service and the safe wrapper
        # is the genuine code under test rather than a hand-rolled forward.
        # The service, resolved the way production resolves it -- there is no
        # coordinator on an app double, so this takes the `__dict__` branch.
        lifecycle = run_lifecycle(app)
        lifecycle.set_completed(True)

        with patch.object(time, "monotonic", side_effect=(10.0, 10.5, 11.0)):
            self.assertEqual(lifecycle.refresh().mode, RuntimeGameMode.IN_GAME)
            self.assertFalse(lifecycle.completed_run)
            self.assertEqual(lifecycle.refresh().mode, RuntimeGameMode.IN_GAME)
            self.assertEqual(lifecycle.refresh().mode, RuntimeGameMode.GAME_OVER)

        self.assertEqual(reads, ["read", "read"])
        self.assertTrue(lifecycle.completed_run)
        app.live_run_tracker.mark_run_completed.assert_called_once_with()

    def test_refresh_uses_fresh_core_lifecycle_state_for_vod_gate(self) -> None:
        lifecycle = build_run_lifecycle(
            cached_state=RuntimeGameState(mode=RuntimeGameMode.PAUSED_IN_GAME),
            checked_at=10.0,
            game_states=lambda: (_ for _ in ()).throw(
                AssertionError("VOD refresh should use the cached lifecycle state")
            ),
        )

        with patch.object(time, "monotonic", return_value=10.5):
            state = lifecycle.state_for_refresh()

        self.assertEqual(state.mode, RuntimeGameMode.PAUSED_IN_GAME)

    def test_formats_full_chests_card(self) -> None:
        self.assertEqual(
            formatting.chests_card_values(
                {1: 46, 2: 46, 3: 42},
                {1: 46, 2: 46, 3: 46},
                134,
                138,
                52,
                71,
                11,
                17,
                75.44,
            ),
            {
                "maps": "T1:46/46 T2:46/46 T3:42/46",
                "total": "134/138",
                "paid_free": "52 / 11",
                "key_procs": "71/123 (57.7%)",
                "expected": "75.4",
                "keys": "17 (63.0%)",
            },
        )

    def test_formats_midrun_chests_card_with_minimum_total(self) -> None:
        self.assertEqual(
            formatting.chests_card_values(
                {1: -1, 2: 20},
                {1: 46, 2: 46},
                51,
                92,
                17,
                34,
                None,
                0,
                None,
                True,
            ),
            {
                "maps": "T1:--/46 T2:20/46",
                "total": "51+/92",
                "paid_free": "17 / --",
                "key_procs": "34/51 (66.7%)",
                "expected": "--",
                "keys": "0 (0.0%)",
            },
        )

    def build_recording_app(self) -> MegabonkApp:
        app = object.__new__(MegabonkApp)
        app.__dict__["coordinator"] = make_client_coordinator()
        app.player_stats_vod_recorder = FakeRecordingRecorder()
        app.player_stats_vod_snapshots = ["snapshot"]
        app.player_stats_selected_snapshot_index = 0
        app.player_stats_game_data_client = None
        # The nine recording-lifecycle names that stood here are
        # `VodCapture`'s fields now; tests that poke them reach the
        # service through `vod_capture(app)`.
        app.player_stats_client = SimpleNamespace(
            get_run_timer=lambda: 21.5,
            get_killed_mobs=lambda: 37,
            get_player_level=lambda owner_stats=None: 2,
            get_live_tomes=lambda owner_stats=None: (),
        )
        app.player_stats_status_label = FakeLabel()
        app.player_stats_rows = {}
        app.player_stats_items_label = FakeLabel()
        app.player_stats_banishes_label = FakeLabel()
        live_snapshot_store(app).live_banishes = ()
        app.player_stats_in_game_time_label = FakeLabel()
        app.player_stats_chests_per_minute_label = FakeLabel()
        app.player_stats_powerups_duration_label = FakeLabel()
        app.player_stats_mob_kills_label = FakeLabel()
        app.player_stats_level_label = FakeLabel()
        app.player_stats_new_items_label = FakeLabel()
        app.player_stats_stage_summary_labels = []
        app.vods_banishes_label = FakeLabel()
        app._refresh_vods_list_if_visible = lambda: None
        # Step 19: the Live Stats tab is an injected object, not four loose
        # stubs standing in for MRO-resolved methods. `RecordingPlayerStatsView`
        # pins the port's signatures, so an operation added to `PlayerStatsView`
        # fails here loudly instead of being absorbed.
        app._live_stat_cards = RecordingStatCardsView()
        app._live_items_section = RecordingItemsSectionView()
        attach_player_stats_view(app)
        player_stats_memory(app).close_player_stats_client = lambda: None
        player_stats_memory(app).read_player_stats_only = lambda _context=None: ({}, 0x1234)
        player_stats_memory(app).read_passive_items_only = lambda owner_stats=None, _context=None: ()
        # Both lifecycle readers, and deliberately the same value: production
        # computes `mode` identically in get_runtime_game_state and the cheaper
        # cached get_runtime_activity_state (verified exhaustively over every
        # input combination -- the extra `and not is_game_over` is unreachable).
        # A double whose two readers disagree is a fiction, and step 8b's move to
        # the cached reader is what exposed that this one did.
        _runtime_state = RuntimeGameState(
            mode=RuntimeGameMode.IN_GAME,
            is_playing=True,
        )
        player_stats_memory(app).read_player_stats_runtime_game_state = lambda _context=None: _runtime_state
        player_stats_memory(app).read_player_stats_runtime_activity_state = lambda _context=None: _runtime_state
        app._is_live_stats_tab_active = lambda: True
        app._is_twitch_bot_active = lambda: False
        app.log_messages = []
        app.log = lambda message, tag=None: app.log_messages.append((message, tag))
        # A real tracker keeps the update -> runtime_snapshot round trip honest:
        # VOD capture reads its kwargs from the snapshot, not from local values.
        app.live_run_tracker = LiveRunTracker()
        app.overlay_state_store = None
        return app

    def setUp(self) -> None:
        self.original_config_values = {
            "HOTKEY": config.HOTKEY,
            "HOTKEY_GAME_KEY_WHITELIST": deepcopy(config.HOTKEY_GAME_KEY_WHITELIST),
            "RESET_HOTKEY": config.RESET_HOTKEY,
            "PLAYER_STATS_RECORD_HOTKEY": config.PLAYER_STATS_RECORD_HOTKEY,
            "AUTO_START_RECORDING": config.AUTO_START_RECORDING,
            "SHOW_OBS_REMINDER_ON_START_SCANNER": config.SHOW_OBS_REMINDER_ON_START_SCANNER,
            "MAP_LOAD_DELAY": config.MAP_LOAD_DELAY,
            "RESET_HOLD_DURATION": config.RESET_HOLD_DURATION,
            "TOTAL_REROLLS": config.TOTAL_REROLLS,
            "ACTIVE_TEMPLATES": deepcopy(config.ACTIVE_TEMPLATES),
            "EVALUATION_MODE": config.EVALUATION_MODE,
            "SCORES_SYSTEM": deepcopy(config.SCORES_SYSTEM),
            "TEMPLATES": deepcopy(config.TEMPLATES),
        }
        self.original_user_config = deepcopy(config.user_config)

    def tearDown(self) -> None:
        for name, value in self.original_config_values.items():
            setattr(config, name, value)
        config.user_config.clear()
        config.user_config.update(self.original_user_config)










    def test_settings_save_updates_community_settings_and_applies_run_control_mode(self) -> None:
        master = FakeSettingsMaster()
        vod_capture(master).player_stats_auto_recording_suppressed = True
        destroyed: list[bool] = []
        dialog = types.SimpleNamespace(
            hotkey_entry=FakeEntry("f7"),
            reset_hotkey_entry=FakeEntry("r"),
            record_hotkey_entry=FakeEntry("f8"),
            auto_start_recording_var=FakeVar(True),
            show_obs_reminder_on_start_scanner_var=FakeVar(True),
            map_load_delay_entry=FakeEntry("0.5"),
            reset_hold_duration_entry=FakeEntry("0.25"),
            record_interval_entry=FakeEntry("60"),
            master=master,
            destroy=lambda: destroyed.append(True),
        )

        with patch.object(config, "save_config") as save_config:
            with patch.object(config, "update_game_reset_time") as update_game_reset_time:
                SettingsDialog.save(dialog)

        self.assertTrue(config.AUTO_START_RECORDING)
        self.assertTrue(config.SHOW_OBS_REMINDER_ON_START_SCANNER)
        self.assertFalse(vod_capture(master).player_stats_auto_recording_suppressed)
        self.assertTrue(config.user_config["AUTO_START_RECORDING"])
        self.assertTrue(config.user_config["SHOW_OBS_REMINDER_ON_START_SCANNER"])
        self.assertIn("apply_run_control_mode", master.events)
        self.assertTrue(save_config.called)
        self.assertTrue(update_game_reset_time.called)
        self.assertEqual(destroyed, [True])

    def test_twitch_command_settings_save_persists_commands_announcement_interval(self) -> None:
        accepted: list[bool] = []
        dialog = types.SimpleNamespace(
            stat_checkboxes={"Damage": FakeCheckbox(True)},
            stats_tpl_entry=FakeEntry("Live Stats: {Damage}"),
            templates_entries={"stats": FakeEntry("Live Stats: {Damage}")},
            disabled_item_checkboxes={"Anvil": FakeCheckbox(True), "Coin": FakeCheckbox(False)},
            commands_announcement_interval_spin=FakeSpinBox(42),
            accept=lambda: accepted.append(True),
        )

        with patch.object(config, "save_config") as save_config:
            TwitchCommandSettingsDialog.save(dialog)

        self.assertEqual(config.TWITCH_BOT["commands_announcement_interval_minutes"], 42)
        self.assertEqual(config.TWITCH_BOT["highlighted_disabled_items"], ["Anvil"])
        self.assertEqual(accepted, [True])
        save_config.assert_called_once_with(config.user_config)

    def test_twitch_command_settings_save_refreshes_session_snapshot_immediately(self) -> None:
        refreshed: list[bool] = []
        master = types.SimpleNamespace(
            live_run_tracker=types.SimpleNamespace(set_tracked_item_rules=lambda _rules: None),
            _combined_tracked_item_rules=lambda: (),
            _refresh_session_stats_snapshot=lambda: refreshed.append(True),
        )
        dialog = types.SimpleNamespace(
            stat_checkboxes={"Damage": FakeCheckbox(True)},
            stats_tpl_entry=FakeEntry("Live Stats: {Damage}"),
            templates_entries={"stats": FakeEntry("Live Stats: {Damage}")},
            disabled_item_checkboxes={},
            commands_announcement_interval_spin=FakeSpinBox(30),
            twitch_use_session_tracked_items_cb=FakeCheckbox(False),
            twitch_tags_layout=object(),
            master=master,
            accept=lambda: None,
        )

        with patch.object(config, "save_config"):
            TwitchCommandSettingsDialog.save(dialog)

        self.assertEqual(config.TWITCH_BOT["tracked_items_source"], "custom")
        self.assertEqual(refreshed, [True])

    def test_twitch_command_settings_filter_shows_ingame_disabled_items_without_show_all(self) -> None:
        class FakeGridItem:
            def __init__(self, widget: object) -> None:
                self._widget = widget

            def widget(self) -> object:
                return self._widget

        class FakeGrid:
            def __init__(self) -> None:
                self.widgets: list[object] = []

            def count(self) -> int:
                return len(self.widgets)

            def itemAt(self, index: int) -> FakeGridItem:
                return FakeGridItem(self.widgets[index])

            def removeWidget(self, widget: object) -> None:
                self.widgets.remove(widget)

            def addWidget(self, widget: object, _row: int, _col: int) -> None:
                self.widgets.append(widget)

        class FilterCheckbox(FakeCheckbox):
            def __init__(self, value: bool, *, is_disabled_ingame: bool = False) -> None:
                super().__init__(value)
                self.visible = True
                self.props = {"is_disabled_ingame": is_disabled_ingame}

            def property(self, name: str) -> object:
                return self.props.get(name)

            def setVisible(self, value: bool) -> None:
                self.visible = value

        grid = FakeGrid()
        disabled_cb = FilterCheckbox(False, is_disabled_ingame=True)
        normal_cb = FilterCheckbox(False)
        selected_cb = FilterCheckbox(True)
        dialog = types.SimpleNamespace(
            disabled_search_input=FakeEntry(""),
            show_all_disabled_items_cb=FakeCheckbox(False),
            disabled_grid=grid,
            disabled_item_checkboxes={
                "Disabled Sword": disabled_cb,
                "Normal Ring": normal_cb,
                "Selected Tome": selected_cb,
            },
        )

        TwitchCommandSettingsDialog.filter_disabled_items(dialog)

        self.assertEqual(grid.widgets, [disabled_cb, selected_cb])
        self.assertTrue(disabled_cb.visible)
        self.assertFalse(normal_cb.visible)
        self.assertTrue(selected_cb.visible)

    def test_twitch_command_settings_reset_restores_default_interval(self) -> None:
        dialog = types.SimpleNamespace(
            _init_guard=False,
            stat_checkboxes={"Damage": FakeCheckbox(False), "XP Gain": FakeCheckbox(False)},
            stats_tpl_entry=FakeEntry("custom"),
            disabled_item_checkboxes={"Anvil": FakeCheckbox(True)},
            templates_entries={"stats": FakeEntry("custom"), "disabled": FakeEntry("custom")},
            commands_announcement_interval_spin=FakeSpinBox(99),
        )

        TwitchCommandSettingsDialog.reset_to_defaults(dialog)

        self.assertEqual(
            dialog.commands_announcement_interval_spin.value(),
            config.DEFAULT_TWITCH_BOT["commands_announcement_interval_minutes"],
        )

    # Twenty-four tests stood in this module until step 25c. Their subject was
    # `ScannerMixin` or `RunControlMixin`, and step 25 converted both into
    # `gui_scanner.Scanner` and `gui_run_control.RunControl`. They are in
    # `test_scanner_run_control.py` now, built through
    # `tests/support/scanner.py`'s real constructors -- moved, not copied,
    # which is the migration rule `test_componentization_inventory`'s header
    # states and what steps 21c/21d/22c/24b each did with theirs.
    #
    # The two `on_closing` tests below stayed. Their subject is
    # `MegabonkApp.on_closing`: a shutdown order over nine owners, which is the
    # application's and not a component's, so an app double is still the honest
    # fixture.




















    def test_load_selected_vod_converts_qt_string_path_to_path(self) -> None:
        loaded_vod = types.SimpleNamespace(
            metadata=types.SimpleNamespace(path=Path("run.jsonl"), name="Run"),
            snapshots=(),
        )
        app = build_recordings_tab()
        app._loaded_vod = None
        app._snapshot_index = None
        app._name_entry = None
        app.refresh_loaded_vod_ui = lambda: None
        app.refresh_vods_list = lambda: None

        with patch_everywhere("load_vod", return_value=loaded_vod) as load_vod:
            app.load_selected_vod("C:/tmp/run.jsonl")

        load_vod.assert_called_once_with(Path("C:/tmp/run.jsonl"))
        self.assertIs(app._loaded_vod, loaded_vod)

    def test_load_selected_vod_disables_old_recording_actions_until_background_load_finishes(self) -> None:
        old_vod = types.SimpleNamespace(
            metadata=types.SimpleNamespace(path=Path("old.jsonl"), name="Old"),
            snapshots=(object(),),
        )
        loaded_vod = types.SimpleNamespace(
            metadata=types.SimpleNamespace(path=Path("new.jsonl"), name="New"),
            snapshots=(object(),),
        )
        # `schedule=` is what puts the load on a worker thread: the mixin read
        # `self.after` and `self._invoker` off the shared namespace to decide,
        # and `RecordingsTab` takes one injected callable instead. Passing it is
        # how this test still exercises the *background* branch it is named for.
        app = build_recordings_tab(schedule=lambda callback: callback())
        app._loaded_vod = old_vod
        app._snapshot_index = 0
        app._compare_start_index = None
        app._name_entry = FakeEntry("Old")
        app._name_entry.setEnabled = lambda enabled: setattr(app._name_entry, "enabled", bool(enabled))
        app._rename_btn = FakeControl()
        app._cleanup_btn = FakeControl()
        app._delete_btn = FakeControl()
        app._slider = FakeControl()
        app._compare_set_btn = FakeControl()
        app._compare_clear_btn = FakeControl()
        app._status_label = FakeLabel()
        app.refresh_loaded_vod_ui = lambda: None
        app.refresh_vods_list = lambda: None
        threads: list[object] = []

        def make_thread(*, target, name, daemon):
            del name, daemon
            thread = types.SimpleNamespace(target=target, start=lambda: None)
            threads.append(thread)
            return thread

        with patch_everywhere("load_vod", return_value=loaded_vod):
            with patch.object(threading, "Thread", side_effect=make_thread):
                app.load_selected_vod("C:/tmp/new.jsonl")

                self.assertIsNone(app._loaded_vod)
                self.assertFalse(app._name_entry.enabled)
                self.assertFalse(app._rename_btn.isEnabled())
                self.assertFalse(app._cleanup_btn.isEnabled())
                self.assertFalse(app._delete_btn.isEnabled())
                self.assertFalse(app._slider.isEnabled())
                self.assertFalse(app._compare_set_btn.isEnabled())
                self.assertFalse(app._compare_clear_btn.isEnabled())

                with patch_everywhere("rename_vod") as rename_vod:
                    app.rename_selected_vod()
                rename_vod.assert_not_called()

                threads[0].target()

        self.assertIs(app._loaded_vod, loaded_vod)
        self.assertTrue(app._name_entry.enabled)
        self.assertTrue(app._rename_btn.isEnabled())
        self.assertTrue(app._cleanup_btn.isEnabled())
        self.assertTrue(app._delete_btn.isEnabled())
        self.assertTrue(app._slider.isEnabled())
        self.assertTrue(app._compare_set_btn.isEnabled())
        self.assertFalse(app._compare_clear_btn.isEnabled())

    def test_load_selected_vod_clears_old_ui_when_load_fails(self) -> None:
        app = build_recordings_tab()
        app._loaded_vod = types.SimpleNamespace(snapshots=(object(),))
        app._snapshot_index = 0
        app._compare_start_index = None
        app._name_entry = FakeEntry("Old")
        app._name_entry.setEnabled = lambda enabled: setattr(app._name_entry, "enabled", bool(enabled))
        app._rename_btn = FakeControl()
        app._cleanup_btn = FakeControl()
        app._delete_btn = FakeControl()
        app._slider = FakeControl()
        app._compare_set_btn = FakeControl()
        app._compare_clear_btn = FakeControl()
        app._status_label = FakeLabel()
        app._clear_loaded_vod_selection = MagicMock()

        with patch_everywhere("load_vod", side_effect=ValueError("broken file")):
            app.load_selected_vod("C:/tmp/broken.jsonl")

        app._clear_loaded_vod_selection.assert_called_once_with()
        self.assertIsNone(app._loaded_vod)
        self.assertEqual(app._status_label.text(), "Could not load recording: broken file")
        self.assertFalse(app._name_entry.enabled)
        self.assertFalse(app._rename_btn.isEnabled())
        self.assertTrue(app._cleanup_btn.isEnabled())
        self.assertFalse(app._delete_btn.isEnabled())
        self.assertFalse(app._slider.isEnabled())

    def test_template_manager_dialog_expands_selected_template(self) -> None:
        MegabonkApp._ensure_qt_application()
        templates = [
            {"id": 1, "name": "LIGHT", "color": "GREEN"},
            {"id": 2, "name": "PERFECT", "color": "YELLOW"},
        ]
        dialog = TemplateManagerDialog(None, templates, lambda _original, _updated: True)

        first_details = dialog.card_widgets[1]["details"]
        second_details = dialog.card_widgets[2]["details"]
        self.assertTrue(first_details.isHidden())
        self.assertTrue(second_details.isHidden())

        dialog.toggle_template(2)
        self.assertEqual(dialog.expanded_template_id, 2)
        self.assertTrue(first_details.isHidden())
        self.assertFalse(second_details.isHidden())

        dialog.close()

    def test_template_manager_dialog_save_updates_template_and_collapses_card(self) -> None:
        MegabonkApp._ensure_qt_application()
        saved: list[tuple[dict, dict]] = []
        templates = [{"id": 9, "name": "Custom", "micro": 1, "color": "MAGENTA"}]
        dialog = TemplateManagerDialog(None, templates, lambda original, updated: saved.append((original, updated)) or True)

        form = dialog.card_widgets[9]["form"]
        form.micro_entry.setText("3")
        dialog.toggle_template(9)
        dialog.save_template(9, form)

        self.assertEqual(saved[0][0]["id"], 9)
        self.assertEqual(saved[0][1]["micro"], 3)
        self.assertEqual(dialog.templates[0]["micro"], 3)
        self.assertIsNone(dialog.expanded_template_id)
        self.assertTrue(dialog.card_widgets[9]["details"].isHidden())

        dialog.close()


    # `test_format_stats_includes_bald_heads_when_active_template_requires_it`
    # stood here until step 22a. `format_stats` is `app.map_scoring`'s now, and
    # a free function needs no app double at all -- the test moved whole to
    # `test_map_scoring.py` and took one `object.__new__(MegabonkApp)` with it.

    # Three template doubles stood here until step 22c:
    # `test_edit_template_dialog_opens_template_manager`,
    # `test_save_checkbox_state_updates_runtime_templates_without_restart` and
    # `test_refresh_scores_ui_updates_runtime_tiers_without_restart`. Their
    # subject is `ui.tabs.templates.TemplatesPanel` now, so they call its real
    # constructor in `test_templates_panel.py` -- the migration order this
    # file's header states.




    def test_recording_run_state_split_starts_new_file_when_seed_changes(self) -> None:
        # stage_index fell (2 -> 0): a new run started, even though the timer
        # alone (4.0s, far below the old 120.0s baseline) would also have said
        # "new run" under the pre-8b heuristic. Kept low here specifically so
        # this test cannot pass by accident if the tie-break path is reached.
        app = self.build_recording_app()
        vod_capture(app).player_stats_recording_seed = 111
        vod_capture(app).player_stats_recording_stage_ptr = 0x1000
        vod_capture(app).player_stats_recording_stage_index = 2
        vod_capture(app).player_stats_recording_run_time_seconds = 120.0
        app.player_stats_client = SimpleNamespace(get_run_timer=lambda: 4.0, get_killed_mobs=lambda: 37)
        app.player_stats_game_data_client = FakeSeedStateClient(
            [SimpleNamespace(map_seed=222, current_stage_ptr=0x2000, stage_index=0)]
        )

        action = vod_capture(app).sync_run_state()

        self.assertEqual(action, "split")
        self.assertEqual(app.player_stats_vod_recorder.stop_calls, 1)
        self.assertEqual(app.player_stats_vod_recorder.start_calls, [{"name": None, "seed": 222}])
        self.assertEqual(vod_capture(app).player_stats_recording_seed, 222)
        self.assertEqual(vod_capture(app).player_stats_recording_stage_index, 0)
        self.assertEqual(app.player_stats_vod_snapshots, [])
        self.assertIn("auto-split", app.log_messages[0][0])

    def test_recording_run_state_does_not_split_when_seed_changes_between_stages(self) -> None:
        # stage_index rose (0 -> 1): a map transition, not a new run, even
        # though the seed also changed. The timer (123.0s, above the 120.0s
        # baseline) would agree under the old heuristic too -- see the
        # unreadable-timer variant below for the case that used to get this
        # wrong.
        app = self.build_recording_app()
        vod_capture(app).player_stats_recording_seed = 111
        vod_capture(app).player_stats_recording_stage_ptr = 0x1000
        vod_capture(app).player_stats_recording_stage_index = 0
        vod_capture(app).player_stats_recording_run_time_seconds = 120.0
        app.player_stats_client = SimpleNamespace(get_run_timer=lambda: 123.0, get_killed_mobs=lambda: 37)
        app.player_stats_game_data_client = FakeSeedStateClient(
            [SimpleNamespace(map_seed=222, current_stage_ptr=0x2000, stage_index=1)]
        )

        action = vod_capture(app).sync_run_state()

        self.assertIsNone(action)
        self.assertEqual(app.player_stats_vod_recorder.stop_calls, 0)
        self.assertEqual(app.player_stats_vod_recorder.start_calls, [])
        self.assertEqual(vod_capture(app).player_stats_recording_seed, 222)
        self.assertEqual(vod_capture(app).player_stats_recording_stage_ptr, 0x2000)
        self.assertEqual(vod_capture(app).player_stats_recording_stage_index, 1)
        self.assertEqual(vod_capture(app).player_stats_recording_run_time_seconds, 123.0)
        self.assertEqual(app.log_messages, [])

    def test_recording_run_state_does_not_split_when_stage_ptr_changes_inside_same_run(self) -> None:
        # Forest/Desert shape: seed constant, stage_ptr changes at 1 -> 2 -> 3,
        # stage_index increments cleanly alongside it.
        app = self.build_recording_app()
        vod_capture(app).player_stats_recording_seed = 111
        vod_capture(app).player_stats_recording_stage_ptr = 0x1000
        vod_capture(app).player_stats_recording_stage_index = 0
        vod_capture(app).player_stats_recording_run_time_seconds = 120.0
        app.player_stats_client = SimpleNamespace(get_run_timer=lambda: 123.0, get_killed_mobs=lambda: 37)
        app.player_stats_game_data_client = FakeSeedStateClient(
            [SimpleNamespace(map_seed=111, current_stage_ptr=0x2000, stage_index=1)]
        )

        action = vod_capture(app).sync_run_state()

        self.assertIsNone(action)
        self.assertEqual(app.player_stats_vod_recorder.stop_calls, 0)
        self.assertEqual(app.player_stats_vod_recorder.start_calls, [])
        self.assertEqual(vod_capture(app).player_stats_recording_seed, 111)
        self.assertEqual(vod_capture(app).player_stats_recording_stage_ptr, 0x2000)
        self.assertEqual(vod_capture(app).player_stats_recording_stage_index, 1)
        self.assertEqual(vod_capture(app).player_stats_recording_run_time_seconds, 123.0)
        self.assertEqual(app.log_messages, [])

    def test_recording_run_state_does_not_split_when_run_timer_read_fails_mid_transition(self) -> None:
        """The bug step 8b exists to fix, in its original form.

        An ordinary Forest map transition (seed and stage_ptr both change) while
        the run-timer read fails on the loading screen. The pre-8b code asked
        `_seed_change_looks_like_same_run(120.0, None)`, got False because the
        timer was None, and split the recording in two. stage_index rose 0 -> 1
        and says plainly that this is the same run.
        """
        app = self.build_recording_app()
        vod_capture(app).player_stats_recording_seed = 111
        vod_capture(app).player_stats_recording_stage_ptr = 0x1000
        vod_capture(app).player_stats_recording_stage_index = 0
        vod_capture(app).player_stats_recording_run_time_seconds = 120.0
        app.player_stats_client = SimpleNamespace(
            get_run_timer=lambda: None,  # the failed read
            get_killed_mobs=lambda: 37,
        )
        app.player_stats_game_data_client = FakeSeedStateClient(
            [SimpleNamespace(map_seed=222, current_stage_ptr=0x2000, stage_index=1)]
        )

        action = vod_capture(app).sync_run_state()

        self.assertIsNone(action)
        self.assertEqual(app.player_stats_vod_recorder.stop_calls, 0)
        self.assertEqual(app.player_stats_vod_recorder.start_calls, [])
        self.assertEqual(vod_capture(app).player_stats_recording_stage_index, 1)
        self.assertEqual(app.log_messages, [])

    def test_recording_run_state_does_not_split_when_stage_index_is_unreadable(self) -> None:
        # The bug step 8b exists to fix: a failed read must not be read as an
        # answer. stage_ptr changed (so the decision block is reached at all),
        # but stage_index came back None -- the guard must wait for the next
        # tick rather than fall back to any other signal.
        app = self.build_recording_app()
        vod_capture(app).player_stats_recording_seed = 111
        vod_capture(app).player_stats_recording_stage_ptr = 0x1000
        vod_capture(app).player_stats_recording_stage_index = 1
        vod_capture(app).player_stats_recording_run_time_seconds = 120.0
        app.player_stats_client = SimpleNamespace(get_run_timer=lambda: 4.0, get_killed_mobs=lambda: 37)
        app.player_stats_game_data_client = FakeSeedStateClient(
            [SimpleNamespace(map_seed=111, current_stage_ptr=0x2000, stage_index=None)]
        )

        action = vod_capture(app).sync_run_state()

        self.assertIsNone(action)
        self.assertEqual(app.player_stats_vod_recorder.stop_calls, 0)
        self.assertEqual(app.player_stats_vod_recorder.start_calls, [])
        # State must be untouched, not adopted -- there was nothing to decide.
        self.assertEqual(vod_capture(app).player_stats_recording_seed, 111)
        self.assertEqual(vod_capture(app).player_stats_recording_stage_ptr, 0x1000)
        self.assertEqual(vod_capture(app).player_stats_recording_stage_index, 1)
        self.assertEqual(vod_capture(app).player_stats_recording_run_time_seconds, 120.0)
        self.assertEqual(app.log_messages, [])

    def test_recording_run_state_splits_when_stage_index_unchanged_and_timer_regresses(self) -> None:
        # A run that died and restarted at the same stage_index (typically 0,
        # per the Graveyard live check) -- the tie-break the four rules
        # reserve for "unchanged".
        app = self.build_recording_app()
        vod_capture(app).player_stats_recording_seed = 111
        vod_capture(app).player_stats_recording_stage_ptr = 0x1000
        vod_capture(app).player_stats_recording_stage_index = 0
        vod_capture(app).player_stats_recording_run_time_seconds = 400.0
        app.player_stats_client = SimpleNamespace(get_run_timer=lambda: 2.0, get_killed_mobs=lambda: 0)
        app.player_stats_game_data_client = FakeSeedStateClient(
            [SimpleNamespace(map_seed=999, current_stage_ptr=0x9000, stage_index=0)]
        )

        action = vod_capture(app).sync_run_state()

        self.assertEqual(action, "split")
        self.assertEqual(vod_capture(app).player_stats_recording_seed, 999)
        self.assertEqual(vod_capture(app).player_stats_recording_stage_index, 0)

    def test_recording_run_state_does_not_split_when_stage_index_unchanged_and_timer_unreadable(self) -> None:
        # Unspecified by the four documented rules, so the conservative default
        # applies: missing timer data must not manufacture a split either.
        app = self.build_recording_app()
        vod_capture(app).player_stats_recording_seed = 111
        vod_capture(app).player_stats_recording_stage_ptr = 0x1000
        vod_capture(app).player_stats_recording_stage_index = 0
        vod_capture(app).player_stats_recording_run_time_seconds = 400.0
        app.player_stats_client = SimpleNamespace(get_run_timer=lambda: None, get_killed_mobs=lambda: 0)
        app.player_stats_game_data_client = FakeSeedStateClient(
            [SimpleNamespace(map_seed=999, current_stage_ptr=0x9000, stage_index=0)]
        )

        action = vod_capture(app).sync_run_state()

        self.assertIsNone(action)
        self.assertEqual(app.player_stats_vod_recorder.stop_calls, 0)
        self.assertEqual(vod_capture(app).player_stats_recording_seed, 999)
        self.assertEqual(vod_capture(app).player_stats_recording_stage_index, 0)

    def test_stage_index_signals_new_run_direct(self) -> None:
        signals = _stage_index_signals_new_run
        # index unreadable -> do not decide
        self.assertIsNone(signals(1, None, 100.0, 50.0))
        # no baseline yet -> adopt without splitting
        self.assertFalse(signals(None, 0, None, 10.0))
        # rose -> same run
        self.assertFalse(signals(1, 2, 100.0, 105.0))
        # fell -> new run
        self.assertTrue(signals(2, 0, 100.0, 5.0))
        # unchanged + timer regressed -> new run
        self.assertTrue(signals(0, 0, 400.0, 2.0))
        # unchanged + timer held -> same run
        self.assertFalse(signals(0, 0, 400.0, 405.0))
        # unchanged + timer missing -> do not manufacture a split
        self.assertFalse(signals(0, 0, 400.0, None))
        self.assertFalse(signals(0, 0, None, 2.0))

    def test_recording_run_state_stops_after_seed_missing_grace_period(self) -> None:
        app = self.build_recording_app()
        vod_capture(app).player_stats_recording_seed = 111
        app.player_stats_game_data_client = FakeSeedStateClient([None, None])

        with patch.object(time, "monotonic", return_value=100.0):
            first_action = vod_capture(app).sync_run_state()

        with patch.object(
            time,
            "monotonic",
            return_value=100.0 + PLAYER_STATS_RECORDING_SEED_GRACE_SECONDS + 1.0,
        ):
            second_action = vod_capture(app).sync_run_state()

        self.assertIsNone(first_action)
        self.assertEqual(second_action, "stopped")
        self.assertEqual(app.player_stats_vod_recorder.stop_calls, 1)
        self.assertFalse(app.player_stats_vod_recorder.is_recording)
        self.assertIsNone(vod_capture(app).player_stats_recording_seed)
        self.assertIn("auto-stopped", app.log_messages[0][0])

    def test_recording_run_state_keeps_file_open_while_paused(self) -> None:
        app = self.build_recording_app()
        player_stats_memory(app).read_player_stats_runtime_game_state = lambda _context=None: RuntimeGameState(
            mode=RuntimeGameMode.PAUSED_IN_GAME,
            is_playing=True,
            is_paused=True,
        )

        action = vod_capture(app).sync_run_state()

        self.assertEqual(action, "paused")
        self.assertTrue(app.player_stats_vod_recorder.is_recording)
        self.assertEqual(app.player_stats_vod_recorder.stop_calls, 0)
        self.assertEqual(vod_capture(app).player_stats_recording_waiting_mode, RuntimeGameMode.PAUSED_IN_GAME.value)

    def test_pausing_writes_the_status_line_through_the_view(self) -> None:
        """Covers the branch step 14c re-routed and the suite never asserted.

        `_sync_player_stats_recording_run_state` used to call `_set_text` on
        `player_stats_status_label` directly from `app/`; it now goes through
        `PlayerStatsView.set_recording_status_text`. The existing pause test drives
        this branch but asserts nothing about the text, so mutating the writer left
        the whole suite green -- which is why this assertion exists.
        """
        app = self.build_recording_app()
        app._is_live_stats_tab_active = lambda: True
        player_stats_memory(app).read_player_stats_runtime_game_state = lambda _context=None: RuntimeGameState(
            mode=RuntimeGameMode.PAUSED_IN_GAME,
            is_playing=True,
            is_paused=True,
        )

        action = vod_capture(app).sync_run_state()

        self.assertEqual(action, "paused")
        self.assertEqual(
            app.player_stats_status_label.text(),
            "Live player stats (recording paused)",
        )

    def test_recording_run_state_waits_after_game_over_without_disarming(self) -> None:
        app = self.build_recording_app()
        vod_capture(app).player_stats_recording_armed = True
        player_stats_memory(app).read_player_stats_runtime_game_state = lambda _context=None: RuntimeGameState(
            mode=RuntimeGameMode.GAME_OVER,
            is_playing=True,
            is_game_over=True,
        )

        action = vod_capture(app).sync_run_state()

        self.assertEqual(action, "waiting")
        self.assertFalse(app.player_stats_vod_recorder.is_recording)
        self.assertEqual(app.player_stats_vod_recorder.stop_calls, 1)
        self.assertTrue(vod_capture(app).player_stats_recording_armed)
        self.assertEqual(vod_capture(app).player_stats_recording_waiting_mode, RuntimeGameMode.GAME_OVER.value)

    def test_recording_run_state_waits_after_manual_menu_without_disarming(self) -> None:
        app = self.build_recording_app()
        vod_capture(app).player_stats_recording_armed = True
        player_stats_memory(app).read_player_stats_runtime_game_state = lambda _context=None: RuntimeGameState(
            mode=RuntimeGameMode.MAIN_MENU,
        )

        action = vod_capture(app).sync_run_state()

        self.assertEqual(action, "waiting")
        self.assertFalse(app.player_stats_vod_recorder.is_recording)
        self.assertEqual(app.player_stats_vod_recorder.stop_calls, 1)
        self.assertTrue(vod_capture(app).player_stats_recording_armed)
        self.assertEqual(vod_capture(app).player_stats_recording_waiting_mode, RuntimeGameMode.MAIN_MENU.value)

    def test_recording_run_state_starts_new_file_from_waiting_when_game_resumes(self) -> None:
        app = self.build_recording_app()
        app.player_stats_vod_recorder.is_recording = False
        vod_capture(app).player_stats_recording_armed = True
        vod_capture(app).player_stats_recording_waiting_mode = RuntimeGameMode.MAIN_MENU.value
        player_stats_memory(app).read_player_stats_runtime_game_state = lambda _context=None: RuntimeGameState(
            mode=RuntimeGameMode.IN_GAME,
            is_playing=True,
        )
        player_stats_memory(app).read_player_stats_recording_state = lambda _context=None: SimpleNamespace(
            map_seed=333,
            current_stage_ptr=0x3000,
        )

        action = vod_capture(app).sync_run_state()

        self.assertEqual(action, "started")
        self.assertTrue(app.player_stats_vod_recorder.is_recording)
        self.assertEqual(app.player_stats_vod_recorder.start_calls, [{"name": None, "seed": 333}])
        self.assertEqual(vod_capture(app).player_stats_recording_stage_ptr, 0x3000)
        self.assertIsNone(vod_capture(app).player_stats_recording_waiting_mode)

    def test_toggle_recording_stops_auto_recording_waiting_mode_for_session(self) -> None:
        app = self.build_recording_app()
        app.player_stats_vod_recorder.is_recording = False
        vod_capture(app).player_stats_recording_armed = False
        vod_capture(app).player_stats_recording_waiting_mode = RuntimeGameMode.MAIN_MENU.value
        app.refresh_live_player_stats_now = lambda *args, **kwargs: None

        with patch.object(config, "AUTO_START_RECORDING", True):
            self.assertTrue(vod_capture(app).is_recording_armed())

            vod_capture(app).toggle_recording()

            self.assertFalse(vod_capture(app).is_recording_armed())

        self.assertTrue(vod_capture(app).player_stats_auto_recording_suppressed)
        self.assertFalse(vod_capture(app).player_stats_recording_armed)
        self.assertFalse(app.player_stats_vod_recorder.is_recording)
        self.assertEqual(app.player_stats_vod_recorder.stop_calls, 1)
        self.assertEqual(app.player_stats_vod_recorder.start_calls, [])
        self.assertIn(("[*] Player stats recording stopped.", None), app.log_messages)

    def test_auto_start_recording_respects_session_suppression(self) -> None:
        # The real constructor with explicit fakes, not `object.__new__`.
        # `maybe_auto_start` takes every input as a keyword argument and does
        # no memory reads, so there is no real collaborator to lose here --
        # which is what makes this one honest to migrate and the
        # `_sync_run_state` scenarios above not. See
        # `tests/support/vod_capture.py`.
        service, world = build_vod_capture()
        service.player_stats_auto_recording_suppressed = True

        with patch.object(config, "AUTO_START_RECORDING", True):
            started = service.maybe_auto_start(
                stats={"Damage": SimpleNamespace(display_value="123", value=1.23)},
                run_timer_seconds=21.5,
                player_level=2,
                map_seed=777,
                stage_ptr=2,
            )

        self.assertFalse(started)
        self.assertEqual(service.player_stats_auto_start_detection_streak, 0)
        self.assertEqual(world.recorder.start_calls, [])

    def test_build_stage_summary_tracks_stage_transitions_and_item_stack_gains(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=20.0,
                stage_time_seconds=20.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=100,
                items=("Wrench x1",),
            ),
            SimpleNamespace(
                game_time_seconds=40.0,
                stage_time_seconds=40.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=160,
                items=("Wrench x2", "Beacon x1"),
            ),
            SimpleNamespace(
                game_time_seconds=60.0,
                stage_time_seconds=1.0,
                stage_ptr=0x2000,
                map_seed=22,
                mob_kills=200,
                items=("Wrench x2", "Beacon x1"),
            ),
            SimpleNamespace(
                game_time_seconds=90.0,
                stage_time_seconds=31.0,
                stage_ptr=0x2000,
                map_seed=22,
                mob_kills=260,
                items=("Wrench x3", "Beacon x1", "Ghost x1"),
            ),
            SimpleNamespace(
                game_time_seconds=120.0,
                stage_time_seconds=45.0,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=300,
                items=("Wrench x3", "Beacon x1", "Ghost x1"),
            ),
            SimpleNamespace(
                game_time_seconds=150.0,
                stage_time_seconds=2.0,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=360,
                items=("Wrench x3", "Beacon x2", "Ghost x1"),
            ),
            SimpleNamespace(
                game_time_seconds=180.0,
                stage_time_seconds=590.0,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=420,
                items=("Wrench x3", "Beacon x3", "Ghost x2"),
            ),
        ]

        rows = formatting.build_stage_summary(snapshots)

        self.assertEqual(rows[0]["kills"], "200")
        self.assertEqual(rows[0]["time"], "01:00")
        self.assertIn("#60A5FA", rows[0]["items"])
        self.assertIn(">1</span>", rows[0]["items"])
        self.assertIn("#22C55E", rows[0]["items"])
        self.assertEqual(rows[1]["kills"], "60")
        self.assertEqual(rows[1]["time"], "00:30")
        self.assertIn("#22C55E", rows[1]["items"])
        self.assertEqual(rows[2]["kills"], "60")
        self.assertEqual(rows[2]["time"], "00:30")
        # The `150.0` snapshot is the Stage 3 -> 4 boundary (same stage_ptr, the
        # timer collapses from 45.0 to 2.0) and it is the first read that shows
        # `Beacon x2`. That Beacon was picked up on Stage 3 and only became
        # visible on the read that detected the transition, so it belongs to
        # Stage 3. It used to land on Stage 4, which is the misattribution the
        # closing-snapshot credit fixes; the bucket append and the kill baseline
        # on the adjacent lines already used this same predicate.
        self.assertIn("#60A5FA", rows[2]["items"])
        self.assertIn(">1</span>", rows[2]["items"])
        self.assertEqual(rows[3]["kills"], "100")
        self.assertEqual(rows[3]["time"], "00:30")
        # Stage 4 keeps only what the `180.0` snapshot added -- one more Beacon
        # and one more Ghost -- rather than also absorbing Stage 3's tail.
        self.assertIn("#60A5FA", rows[3]["items"])
        self.assertIn("#22C55E", rows[3]["items"])

    def test_build_stage_summary_uses_early_new_stage_snapshot_as_previous_boundary(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=1310.0,
                stage_time_seconds=1310.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=90_000,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=1320.0,
                stage_time_seconds=1.0,
                stage_ptr=0x2000,
                map_seed=22,
                mob_kills=92_100,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=1380.0,
                stage_time_seconds=61.0,
                stage_ptr=0x2000,
                map_seed=22,
                mob_kills=101_000,
                items=(),
            ),
        ]

        rows = formatting.build_stage_summary(snapshots)

        self.assertEqual(rows[0]["kills"], "92,100")
        self.assertEqual(rows[0]["time"], "22:00")
        self.assertEqual(rows[1]["kills"], "8,900")
        self.assertEqual(rows[1]["time"], "01:00")

    def test_build_stage_summary_time_ignores_stage_timer_boss_skips(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=0.0,
                stage_time_seconds=0.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=0,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=480.0,
                stage_time_seconds=480.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=20_000,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=481.0,
                stage_time_seconds=595.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=20_500,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=1320.0,
                stage_time_seconds=1330.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=110_000,
                items=(),
            ),
        ]

        rows = formatting.build_stage_summary(snapshots)

        self.assertEqual(rows[0]["time"], "22:00")

    def test_build_stage_summary_detects_stage_four_after_wide_reset_gap(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=20.0,
                stage_time_seconds=20.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=1_000,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=80.0,
                stage_time_seconds=1.0,
                stage_ptr=0x2000,
                map_seed=22,
                mob_kills=4_000,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=140.0,
                stage_time_seconds=1.0,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=7_000,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=220.0,
                stage_time_seconds=220.0,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=10_000,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=280.0,
                stage_time_seconds=45.0,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=12_000,
                items=(),
            ),
        ]

        rows = formatting.build_stage_summary(snapshots)

        self.assertEqual(rows[2]["kills"], "3,000")
        self.assertEqual(rows[2]["time"], "01:20")
        self.assertEqual(rows[3]["kills"], "2,000")
        self.assertEqual(rows[3]["time"], "00:00")

    def test_build_stage_summary_does_not_treat_early_stage_three_timer_reset_as_stage_four(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=20.0,
                stage_time_seconds=20.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=300,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=80.0,
                stage_time_seconds=1.0,
                stage_ptr=0x2000,
                map_seed=22,
                mob_kills=900,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=140.0,
                stage_time_seconds=1.0,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=1_500,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=150.0,
                stage_time_seconds=2.0,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=1_525,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=152.0,
                stage_time_seconds=1.0,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=1_550,
                items=(),
            ),
        ]

        rows = formatting.build_stage_summary(snapshots)

        self.assertEqual(rows[2]["kills"], "50")
        self.assertEqual(rows[2]["time"], "00:12")
        self.assertEqual(rows[3]["kills"], "--")

    def test_build_stage_summary_detects_stage_four_when_boss_lives_past_one_minute(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=20.0,
                stage_time_seconds=20.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=300,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=80.0,
                stage_time_seconds=1.0,
                stage_ptr=0x2000,
                map_seed=22,
                mob_kills=900,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=140.0,
                stage_time_seconds=1.0,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=1_500,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=450.0,
                stage_time_seconds=100.0,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=2_500,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=472.0,
                stage_time_seconds=590.0,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=2_564,
                items=(),
            ),
        ]

        rows = formatting.build_stage_summary(snapshots)

        self.assertEqual(rows[2]["kills"], "1,000")
        self.assertEqual(rows[2]["time"], "05:10")
        self.assertEqual(rows[3]["kills"], "64")
        self.assertEqual(rows[3]["time"], "00:00")

    def test_build_stage_summary_detects_stage_four_when_first_visible_snapshot_is_ghost_phase(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=20.0,
                stage_time_seconds=20.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=1_000,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=80.0,
                stage_time_seconds=1.0,
                stage_ptr=0x2000,
                map_seed=22,
                mob_kills=4_000,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=140.0,
                stage_time_seconds=1.0,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=7_000,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=5089.87,
                stage_time_seconds=2121.84,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=583_852,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=5109.79,
                stage_time_seconds=604.39,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=584_478,
                items=(),
            ),
        ]

        rows = formatting.build_stage_summary(snapshots)

        self.assertEqual(rows[2]["kills"], "0")
        self.assertEqual(rows[2]["time"], "00:00")
        self.assertEqual(rows[3]["kills"], "577,478")
        self.assertEqual(rows[3]["time"], "00:19")

    def test_build_stage_summary_reconciles_last_stage_kills_with_final_total(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=20.0,
                stage_time_seconds=20.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=100,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=40.0,
                stage_time_seconds=40.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=160,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=60.0,
                stage_time_seconds=1.0,
                stage_ptr=0x2000,
                map_seed=22,
                mob_kills=200,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=90.0,
                stage_time_seconds=31.0,
                stage_ptr=0x2000,
                map_seed=22,
                mob_kills=260,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=120.0,
                stage_time_seconds=45.0,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=300,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=150.0,
                stage_time_seconds=2.0,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=360,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=180.0,
                stage_time_seconds=590.0,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=425,
                items=(),
            ),
        ]

        rows = formatting.build_stage_summary(snapshots)

        self.assertEqual(rows[0]["kills"], "200")
        self.assertEqual(rows[1]["kills"], "60")
        self.assertEqual(rows[2]["kills"], "60")
        self.assertEqual(rows[3]["kills"], "105")

    def test_build_stage_summary_stage_one_time_starts_from_run_zero(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=180.0,
                stage_time_seconds=180.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=12_000,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=1320.0,
                stage_time_seconds=1320.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=110_000,
                items=(),
            ),
        ]

        rows = formatting.build_stage_summary(snapshots)

        self.assertEqual(rows[0]["time"], "22:00")

    def test_build_stage_summary_stage_one_kills_ignores_missing_initial_kill_reads(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=0.0,
                stage_time_seconds=0.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=None,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=10.0,
                stage_time_seconds=10.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=None,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=20.0,
                stage_time_seconds=20.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=12,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=30.0,
                stage_time_seconds=30.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=128,
                items=(),
            ),
        ]

        rows = formatting.build_stage_summary(snapshots)

        self.assertEqual(rows[0]["kills"], "128")

    def test_build_stage_summary_later_stage_kills_use_transition_baseline_when_reads_are_missing(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=100.0,
                stage_time_seconds=100.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=10_000,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=120.0,
                stage_time_seconds=1.0,
                stage_ptr=0x2000,
                map_seed=22,
                mob_kills=12_000,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=130.0,
                stage_time_seconds=11.0,
                stage_ptr=0x2000,
                map_seed=22,
                mob_kills=None,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=140.0,
                stage_time_seconds=21.0,
                stage_ptr=0x2000,
                map_seed=22,
                mob_kills=None,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=150.0,
                stage_time_seconds=31.0,
                stage_ptr=0x2000,
                map_seed=22,
                mob_kills=18_500,
                items=(),
            ),
        ]

        rows = formatting.build_stage_summary(snapshots)

        self.assertEqual(rows[1]["kills"], "6,500")

    def test_build_stage_summary_counts_duplicate_item_entries(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=5.0,
                stage_time_seconds=5.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=10,
                items=("Wrench x1", "Cheese x1"),
            ),
            SimpleNamespace(
                game_time_seconds=15.0,
                stage_time_seconds=15.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=20,
                items=("Wrench x3", "Cheese x1", "Cheese x1", "Anvil x2"),
            ),
        ]

        rows = formatting.build_stage_summary(snapshots)

        self.assertIn("#FACC15", rows[0]["items"])
        self.assertIn("#22C55E", rows[0]["items"])

    def test_build_stage_summary_ignores_corrupt_item_stack_counts(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=5.0,
                stage_time_seconds=5.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=10,
                items=("Wrench x1",),
            ),
            SimpleNamespace(
                game_time_seconds=15.0,
                stage_time_seconds=15.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=20,
                items=("Wrench x759271589",),
            ),
            SimpleNamespace(
                game_time_seconds=25.0,
                stage_time_seconds=25.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=30,
                items=("Wrench x2",),
            ),
        ]

        rows = formatting.build_stage_summary(snapshots)

        self.assertEqual(rows[0]["item_rarities"]["COMMON"], 1)
        self.assertNotIn("759271589", rows[0]["items"])

    def test_build_stage_summary_ignores_single_snapshot_item_drop_recoveries(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=10.0,
                stage_time_seconds=10.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=10,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=20.0,
                stage_time_seconds=20.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=20,
                items=("Za Warudo x1",),
            ),
            SimpleNamespace(
                game_time_seconds=30.0,
                stage_time_seconds=30.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=30,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=40.0,
                stage_time_seconds=40.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=40,
                items=("Za Warudo x1",),
            ),
        ]

        rows = formatting.build_stage_summary(snapshots)

        self.assertEqual(rows[0]["items"].count("&#9679;"), 1)
        self.assertIn(">1</span>", rows[0]["items"])

    def test_build_stage_summary_ignores_unavailable_item_snapshots(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=10.0, stage_time_seconds=10.0, stage_ptr=0x1000,
                map_seed=11, mob_kills=10, items=("Za Warudo x1",), items_available=True,
            ),
            SimpleNamespace(
                game_time_seconds=20.0, stage_time_seconds=20.0, stage_ptr=0x1000,
                map_seed=11, mob_kills=20, items=(), items_available=False,
            ),
            SimpleNamespace(
                game_time_seconds=30.0, stage_time_seconds=30.0, stage_ptr=0x1000,
                map_seed=11, mob_kills=30, items=("Za Warudo x2",), items_available=True,
            ),
            SimpleNamespace(
                game_time_seconds=40.0, stage_time_seconds=40.0, stage_ptr=0x1000,
                map_seed=11, mob_kills=40, items=("Za Warudo x2",), items_available=True,
            ),
        ]

        rows = formatting.build_stage_summary(snapshots)

        self.assertIn(">1</span>", rows[0]["items"])

    def test_build_stage_summary_counts_reacquired_items_after_confirmed_consumption(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=10.0,
                stage_time_seconds=10.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=10,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=20.0,
                stage_time_seconds=20.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=20,
                items=("Za Warudo x1",),
            ),
            SimpleNamespace(
                game_time_seconds=30.0,
                stage_time_seconds=30.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=30,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=40.0,
                stage_time_seconds=40.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=40,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=50.0,
                stage_time_seconds=50.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=50,
                items=("Za Warudo x1",),
            ),
        ]

        rows = formatting.build_stage_summary(snapshots)

        self.assertIn(">2</span>", rows[0]["items"])

    def test_build_stage_summary_late_attach_uses_raw_stage_two_row(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=120.0,
                stage_time_seconds=40.0,
                stage_ptr=0x2000,
                map_seed=22,
                stage_index=1,
                mob_kills=1_000,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=150.0,
                stage_time_seconds=70.0,
                stage_ptr=0x2000,
                map_seed=22,
                stage_index=1,
                mob_kills=1_250,
                items=(),
            ),
        ]

        rows = formatting.build_stage_summary(snapshots)

        self.assertEqual(rows[0]["kills"], "--")
        self.assertEqual(rows[1]["kills"], "250")
        self.assertEqual(rows[1]["time"], "01:10")
        self.assertEqual(rows[2]["kills"], "--")

    def test_build_stage_summary_late_attach_uses_raw_stage_three_row_without_auto_stage_four(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=240.0,
                stage_time_seconds=80.0,
                stage_ptr=0x3000,
                map_seed=33,
                stage_index=2,
                mob_kills=2_000,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=300.0,
                stage_time_seconds=140.0,
                stage_ptr=0x3000,
                map_seed=33,
                stage_index=2,
                mob_kills=2_600,
                items=(),
            ),
        ]

        rows = formatting.build_stage_summary(snapshots)

        self.assertEqual(rows[0]["kills"], "--")
        self.assertEqual(rows[1]["kills"], "--")
        self.assertEqual(rows[2]["kills"], "600")
        self.assertEqual(rows[2]["time"], "02:20")
        self.assertEqual(rows[3]["kills"], "--")

    def test_build_stage_summary_attach_on_stage_four_uses_collapsed_chest_total_marker(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=240.0,
                stage_time_seconds=80.0,
                stage_ptr=0x3000,
                map_seed=33,
                stage_index=2,
                chests_total=15,
                mob_kills=2_000,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=300.0,
                stage_time_seconds=140.0,
                stage_ptr=0x3000,
                map_seed=33,
                stage_index=2,
                chests_total=15,
                mob_kills=2_600,
                items=(),
            ),
        ]

        rows = formatting.build_stage_summary(snapshots)

        self.assertEqual(rows[0]["kills"], "--")
        self.assertEqual(rows[1]["kills"], "--")
        self.assertEqual(rows[2]["kills"], "--")
        self.assertEqual(rows[3]["kills"], "600")
        self.assertEqual(rows[3]["time"], "01:00")

    def test_build_stage_summary_attach_on_stage_four_uses_zero_chest_total_marker(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=240.0,
                stage_time_seconds=80.0,
                stage_ptr=0x3000,
                map_seed=33,
                stage_index=2,
                chests_total=0,
                mob_kills=2_000,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=300.0,
                stage_time_seconds=140.0,
                stage_ptr=0x3000,
                map_seed=33,
                stage_index=2,
                chests_total=0,
                mob_kills=2_600,
                items=(),
            ),
        ]

        rows = formatting.build_stage_summary(snapshots)

        self.assertEqual(rows[0]["kills"], "--")
        self.assertEqual(rows[1]["kills"], "--")
        self.assertEqual(rows[2]["kills"], "--")
        self.assertEqual(rows[3]["kills"], "600")
        self.assertEqual(rows[3]["time"], "01:00")

    def test_item_total_count_includes_stacks_and_duplicate_entries(self) -> None:
        total = formatting._item_total_count(
            ("Wrench x3", "Anvil x2", "Anvil x1", "Moldy Cheese")
        )

        self.assertEqual(total, 7)

    def test_sort_items_for_display_supports_rarity_modes(self) -> None:
        items = ("Wrench x1", "Anvil x1", "Beacon x1", "Spiky Shield x1", "Key x1")

        self.assertEqual(
            formatting.sort_items_for_display(items, ITEM_SORT_DEFAULT),
            items,
        )
        self.assertEqual(
            formatting.sort_items_for_display(items, ITEM_SORT_RARITY_DESC),
            ("Anvil x1", "Spiky Shield x1", "Beacon x1", "Wrench x1", "Key x1"),
        )
        self.assertEqual(
            formatting.sort_items_for_display(items, ITEM_SORT_RARITY_ASC),
            ("Wrench x1", "Key x1", "Beacon x1", "Spiky Shield x1", "Anvil x1"),
        )

    def test_update_player_stats_timer_auto_stops_recording_when_game_is_closed(self) -> None:
        app = self.build_recording_app()
        app._is_shutting_down = False
        app.after_calls = []
        app.after = lambda delay, callback: app.after_calls.append((delay, callback))
        vod_capture(app).player_stats_recording_seed = 111
        app.player_stats_game_data_client = FakeSeedStateClient([None, None])
        app.overlay_should_refresh_live_stats = lambda: False
        app._is_twitch_bot_active = lambda: False

        def failing_read_player_stats_only(_context=None) -> tuple[dict[str, object], int]:
            raise ProcessNotFoundError("game closed")

        player_stats_memory(app).read_player_stats_only = failing_read_player_stats_only

        fallback_client = FakeSeedStateClient([None, None])
        # Step 14c moved the lazy `GameDataClient(...)` construction out of
        # the player-stats mixin into both app-layer modules -- the memory reads and
        # `refresh_live_player_stats_now` each build one. Patch both, so this test
        # keeps asserting "no lazily-created client can reach the real game",
        # which is the whole point of the fallback.
        with patch("app.player_stats_memory.GameDataClient", return_value=fallback_client), \
             patch.object(player_stats_refresh, "GameDataClient", return_value=fallback_client):
            with patch.object(config, "AUTO_START_RECORDING", False), \
                 patch.object(time, "monotonic", return_value=100.0):
                MegabonkApp.update_player_stats_timer(app)

            with patch.object(config, "AUTO_START_RECORDING", False), \
                 patch.object(
                    time,
                    "monotonic",
                    return_value=100.0 + PLAYER_STATS_RECORDING_SEED_GRACE_SECONDS + 1.0,
                ):
                MegabonkApp.update_player_stats_timer(app)

        self.assertEqual(app.player_stats_vod_recorder.stop_calls, 1)
        self.assertFalse(app.player_stats_vod_recorder.is_recording)

    def test_refresh_loop_reschedules_after_tick_exception(self) -> None:
        # The reschedule moved from update_player_stats_timer's own finally into
        # RefreshLoop (step 12a): a tick that raises must still reschedule, so a
        # transient lifecycle read failure cannot terminate the driver.
        schedule_calls: list[tuple[int, object]] = []
        loop = RefreshLoop(
            tick=lambda: (_ for _ in ()).throw(RuntimeError("lifecycle failed")),
            schedule=lambda delay, callback: schedule_calls.append((delay, callback)),
            is_active=lambda: True,
            interval_ms=lambda: int(config.FAST_TRACKER_INTERVAL_MS),
        )

        with self.assertRaisesRegex(RuntimeError, "lifecycle failed"):
            loop.start()

        self.assertEqual(
            schedule_calls,
            [(int(config.FAST_TRACKER_INTERVAL_MS), loop._step)],
        )

    def test_refresh_loop_does_not_reschedule_once_inactive(self) -> None:
        # The is-active gate replaces the old _is_shutting_down checks: once the
        # app is stopping, neither the tick nor a follow-up reschedule runs.
        ticks: list[int] = []
        schedule_calls: list[tuple[int, object]] = []
        loop = RefreshLoop(
            tick=lambda: ticks.append(1),
            schedule=lambda delay, callback: schedule_calls.append((delay, callback)),
            is_active=lambda: False,
            interval_ms=lambda: 500,
        )

        loop.start()

        self.assertEqual(ticks, [])
        self.assertEqual(schedule_calls, [])

    def test_recording_lifecycle_keeps_its_own_cadence_under_the_500ms_driver(self) -> None:
        # The whole risk of collapsing the two timers: the recording lifecycle
        # used to be a 10 s timer's body, and the surviving driver runs 20x
        # faster. Its interval must come from the task, not from the timer --
        # which is also what let step 8b move it to 1 s without touching the
        # driver or the 10 s snapshot.
        app = self.build_recording_app()
        app._is_shutting_down = False
        app.player_stats_vod_recorder.is_recording = False
        app._is_live_stats_tab_active = lambda: False
        app.overlay_should_refresh_live_stats = lambda: False
        app._is_twitch_bot_active = lambda: False
        player_stats_memory(app).read_player_stats_runtime_activity_state = lambda _context=None: RuntimeGameState(
            mode=RuntimeGameMode.MAIN_MENU,
        )
        app.after = lambda delay, callback: None
        sync_calls: list[int] = []
        vod_capture(app).sync_run_state = lambda _context=None: sync_calls.append(1) and None

        now = [1000.0]
        with patch.object(time, "monotonic", side_effect=lambda: now[0]), \
             patch.object(config, "AUTO_START_RECORDING", False), \
             patch.object(config, "IN_GAME_OVERLAY", {"enabled": False, "widgets": {}}):
            for _ in range(40):  # 40 ticks x 500 ms = 20 s of driver time
                MegabonkApp.update_player_stats_timer(app)
                now[0] += 0.5

        # 20 s of ticking / the task's 1 s interval -- not 40, which is what
        # inheriting the driver's 500 ms would give.
        self.assertEqual(len(sync_calls), 20)

    def test_recording_lifecycle_reuses_the_cached_lifecycle_state(self) -> None:
        # What makes 1 s affordable. The sync used to call the uncached, heavier
        # get_runtime_game_state() itself; at 10 s that was one extra heavy read
        # per 10 s, at 1 s it would be one per second. The 500 ms driver already
        # refreshes the cheap cached state once a second, so the sync reads that
        # instead and issues no read of its own.
        app = self.build_recording_app()
        app._is_shutting_down = False
        app._is_live_stats_tab_active = lambda: False
        app.overlay_should_refresh_live_stats = lambda: False
        app._is_twitch_bot_active = lambda: False
        app.after = lambda delay, callback: None

        heavy_reads: list[int] = []
        player_stats_memory(app).read_player_stats_runtime_game_state = lambda _context=None: heavy_reads.append(1) or RuntimeGameState(
            mode=RuntimeGameMode.MAIN_MENU,
        )
        cheap_reads: list[int] = []
        cheap_read_contexts: list = []

        def read_runtime_activity_state(context=None):
            cheap_reads.append(1)
            cheap_read_contexts.append(context)
            return RuntimeGameState(mode=RuntimeGameMode.MAIN_MENU)

        player_stats_memory(app).read_player_stats_runtime_activity_state = (
            read_runtime_activity_state
        )

        now = [1000.0]
        with patch.object(time, "monotonic", side_effect=lambda: now[0]), \
             patch.object(config, "AUTO_START_RECORDING", False), \
             patch.object(config, "IN_GAME_OVERLAY", {"enabled": False, "widgets": {}}):
            for _ in range(20):  # 10 s of driver time
                MegabonkApp.update_player_stats_timer(app)
                now[0] += 0.5

        self.assertEqual(heavy_reads, [], "the sync must not issue its own uncached read")
        self.assertEqual(len(cheap_reads), 10)  # 10 s / the 1 s lifecycle probe
        self.assertTrue(all(context is not None for context in cheap_read_contexts))

    def test_recording_lifecycle_failure_is_contained_to_its_task(self) -> None:
        # The recording sync used to be the timer callback's own body, so a
        # failure escaped into Qt. It is a coordinator task now, which reports
        # failures instead of propagating them -- the tick must survive. (The
        # reschedule that keeps the driver alive is RefreshLoop's job now, tested
        # separately in test_refresh_loop_reschedules_after_tick_exception.)
        app = self.build_recording_app()
        app._is_shutting_down = False
        app.after = lambda delay, callback: None
        vod_capture(app).sync_run_state = lambda _context=None: (_ for _ in ()).throw(
            RuntimeError("lifecycle failed")
        )

        MegabonkApp.update_player_stats_timer(app)

        diagnostics = {
            entry.task_id: entry
            # Not `app._refresh_coordinator`: this double has a coordinator
            # now (step 20h), so that is where `ensure_refresh_coordinator`
            # stored it -- the same accessor production reads it through.
            for entry in ensure_refresh_coordinator(app).diagnostics()
        }
        self.assertIn("lifecycle failed", diagnostics["recording_lifecycle"].last_error or "")

    # `test_refresh_right_tab_after_switch_immediately_refreshes_live_stats`
    # **moved** to `test_tab_router.py` at step 26, which made the router an
    # object. It built an app double and called the unbound mixin method with
    # it as `self`; its subject has a constructor now.

    def test_update_player_stats_timer_skips_hidden_live_stats_when_not_recording(self) -> None:
        app = self.build_recording_app()
        app._is_shutting_down = False
        app.player_stats_vod_recorder.is_recording = False
        app._is_live_stats_tab_active = lambda: False
        app.overlay_should_refresh_live_stats = lambda: False
        app._is_twitch_bot_active = lambda: False
        player_stats_memory(app).read_player_stats_runtime_activity_state = lambda _context=None: RuntimeGameState(
            mode=RuntimeGameMode.MAIN_MENU,
        )
        app.after_calls = []
        app.after = lambda delay, callback: app.after_calls.append((delay, callback))
        read_calls: list[str] = []
        player_stats_memory(app).read_player_stats_only = lambda _context=None: read_calls.append("stats") or ({}, 0x1234)

        with patch.object(config, "AUTO_START_RECORDING", False), \
             patch.object(config, "IN_GAME_OVERLAY", {"enabled": False, "widgets": {}}):
            MegabonkApp.update_player_stats_timer(app)

        self.assertEqual(read_calls, [])
    def test_update_player_stats_timer_refreshes_hidden_live_stats_when_auto_start_enabled(self) -> None:
        app = self.build_recording_app()
        app._is_shutting_down = False
        app.player_stats_vod_recorder.is_recording = False
        app._is_live_stats_tab_active = lambda: False
        app.after_calls = []
        app.after = lambda delay, callback: app.after_calls.append((delay, callback))
        vod_capture(app).sync_run_state = lambda _context=None: None
        refresh_calls: list[str] = []
        app.refresh_live_player_stats_now = lambda *args, **kwargs: refresh_calls.append("refresh")

        with patch.object(config, "AUTO_START_RECORDING", True):
            MegabonkApp.update_player_stats_timer(app)

        self.assertEqual(refresh_calls, ["refresh"])
    def test_update_player_stats_timer_refreshes_hidden_live_stats_when_in_game_overlay_luck_rarity_enabled(self) -> None:
        app = self.build_recording_app()
        app._is_shutting_down = False
        app.player_stats_vod_recorder.is_recording = False
        app._is_live_stats_tab_active = lambda: False
        app.overlay_should_refresh_live_stats = lambda: False
        app._is_twitch_bot_active = lambda: False
        app.after_calls = []
        app.after = lambda delay, callback: app.after_calls.append((delay, callback))
        vod_capture(app).sync_run_state = lambda _context=None: None
        refresh_calls: list[str] = []
        app.refresh_live_player_stats_now = lambda *args, **kwargs: refresh_calls.append("refresh")

        overlay_cfg = {
            "enabled": True,
            "widgets": {
                "luck_rarity": {"enabled": True},
            },
        }
        with patch.object(config, "AUTO_START_RECORDING", False), \
             patch.object(config, "IN_GAME_OVERLAY", overlay_cfg):
            MegabonkApp.update_player_stats_timer(app)

        self.assertEqual(refresh_calls, ["refresh"])
    def test_update_player_stats_timer_refreshes_hidden_live_stats_when_in_game_overlay_stats_enabled(self) -> None:
        app = self.build_recording_app()
        app._is_shutting_down = False
        app.player_stats_vod_recorder.is_recording = False
        app._is_live_stats_tab_active = lambda: False
        app.overlay_should_refresh_live_stats = lambda: False
        app._is_twitch_bot_active = lambda: False
        app.after_calls = []
        app.after = lambda delay, callback: app.after_calls.append((delay, callback))
        vod_capture(app).sync_run_state = lambda _context=None: None
        refresh_calls: list[str] = []
        app.refresh_live_player_stats_now = lambda *args, **kwargs: refresh_calls.append("refresh")

        overlay_cfg = {
            "enabled": True,
            "widgets": {
                "stats": {"enabled": True},
            },
        }
        with patch.object(config, "AUTO_START_RECORDING", False), \
             patch.object(config, "IN_GAME_OVERLAY", overlay_cfg):
            MegabonkApp.update_player_stats_timer(app)

        self.assertEqual(refresh_calls, ["refresh"])
    def test_update_player_stats_timer_refreshes_hidden_live_stats_when_in_game_overlay_event_timer_enabled(self) -> None:
        app = self.build_recording_app()
        app._is_shutting_down = False
        app.player_stats_vod_recorder.is_recording = False
        app._is_live_stats_tab_active = lambda: False
        app.overlay_should_refresh_live_stats = lambda: False
        app._is_twitch_bot_active = lambda: False
        app.after_calls = []
        app.after = lambda delay, callback: app.after_calls.append((delay, callback))
        vod_capture(app).sync_run_state = lambda _context=None: None
        refresh_calls: list[str] = []
        app.refresh_live_player_stats_now = lambda *args, **kwargs: refresh_calls.append("refresh")

        overlay_cfg = {
            "enabled": True,
            "widgets": {
                "event_timer": {"enabled": True},
            },
        }
        with patch.object(config, "AUTO_START_RECORDING", False), \
             patch.object(config, "IN_GAME_OVERLAY", overlay_cfg):
            MegabonkApp.update_player_stats_timer(app)

        self.assertEqual(refresh_calls, ["refresh"])
    def test_powerup_demand_is_active_when_in_game_overlay_powerups_enabled(self) -> None:
        app = self.build_recording_app()
        app._is_shutting_down = False
        app.player_stats_vod_recorder.is_recording = False
        app._is_live_stats_tab_active = lambda: False
        app.overlay_should_refresh_live_stats = lambda: False
        app._is_twitch_bot_active = lambda: False

        overlay_cfg = {
            "enabled": True,
            "widgets": {
                "powerups": {"enabled": True},
                "kps": {"enabled": False},
            },
        }
        with patch.object(config, "AUTO_START_RECORDING", False), \
             patch.object(config, "IN_GAME_OVERLAY", overlay_cfg):
            self.assertTrue(refresh_tasks(app)._should_refresh_powerup_tracker())

    def test_combat_demand_is_active_when_in_game_overlay_kps_enabled(self) -> None:
        app = self.build_recording_app()
        app._is_shutting_down = False
        app.player_stats_vod_recorder.is_recording = False
        app._is_live_stats_tab_active = lambda: False
        app.overlay_should_refresh_live_stats = lambda: False
        app._is_twitch_bot_active = lambda: False

        overlay_cfg = {
            "enabled": True,
            "widgets": {
                "powerups": {"enabled": False},
                "kps": {"enabled": True},
            },
        }
        with patch.object(config, "AUTO_START_RECORDING", False), \
             patch.object(config, "IN_GAME_OVERLAY", overlay_cfg):
            self.assertTrue(refresh_tasks(app)._should_refresh_fast_kps())

    def test_event_timer_demand_is_active_when_in_game_overlay_event_timer_enabled(self) -> None:
        app = self.build_recording_app()
        app._is_shutting_down = False
        app.player_stats_vod_recorder.is_recording = False
        app._is_live_stats_tab_active = lambda: False
        app.overlay_should_refresh_live_stats = lambda: False
        app._is_twitch_bot_active = lambda: False

        overlay_cfg = {
            "enabled": True,
            "widgets": {
                "powerups": {"enabled": False},
                "kps": {"enabled": False},
                "event_timer": {"enabled": True},
            },
        }
        with patch.object(config, "AUTO_START_RECORDING", False), \
             patch.object(config, "IN_GAME_OVERLAY", overlay_cfg):
            self.assertTrue(refresh_tasks(app)._should_refresh_fast_stage_timer())

    def test_stage_summary_fast_demands_are_active_for_twitch_stages(self) -> None:
        app = self.build_recording_app()
        app.player_stats_vod_recorder.is_recording = False
        app._is_live_stats_tab_active = lambda: False
        app._is_twitch_bot_active = lambda: True

        twitch_cfg = {
            **config.TWITCH_BOT,
            "stage_announcements": False,
            "commands": {
                **config.TWITCH_BOT.get("commands", {}),
                "kps": False,
                "stages": True,
            },
        }
        with patch.object(config, "TWITCH_BOT", twitch_cfg), \
             patch.object(config, "IN_GAME_OVERLAY", {"enabled": False, "widgets": {}}), \
             patch.object(config, "OVERLAY", {"widgets": []}):
            self.assertTrue(refresh_tasks(app)._should_refresh_fast_kps())
            self.assertTrue(refresh_tasks(app)._should_refresh_fast_stage_timer())

    def test_stage_timer_demand_is_active_while_recording(self) -> None:
        app = self.build_recording_app()
        app._is_live_stats_tab_active = lambda: False
        app._is_twitch_bot_active = lambda: False

        with patch.object(config, "IN_GAME_OVERLAY", {"enabled": False, "widgets": {}}), \
             patch.object(config, "OVERLAY", {"widgets": []}):
            self.assertTrue(refresh_tasks(app)._should_refresh_fast_stage_timer())


    def test_should_refresh_powerup_tracker_when_event_timer_enabled(self) -> None:
        app = self.build_recording_app()
        app._is_live_stats_tab_active = lambda: False
        app._is_twitch_bot_active = lambda: False

        overlay_cfg = {
            "enabled": True,
            "widgets": {
                "powerups": {"enabled": False},
                "event_timer": {"enabled": True},
            },
        }
        with patch.object(config, "IN_GAME_OVERLAY", overlay_cfg):
            self.assertTrue(refresh_tasks(app)._should_refresh_powerup_tracker())

    def test_refresh_live_player_stats_now_keeps_stats_when_items_fail(self) -> None:
        app = object.__new__(MegabonkApp)
        # Assigns no client, but the refresh reads `player_stats_game_data_client`
        # on the way to the map stats; it wants that read to answer `None`, not
        # to raise. The coordinator is where a `None` client lives now.
        app.__dict__["coordinator"] = make_client_coordinator()
        app.player_stats_vod_recorder = FakeRecordingRecorder(is_recording=False)
        app.player_stats_vod_snapshots = []
        app.player_stats_selected_snapshot_index = None
        vod_capture(app).player_stats_recording_armed = False
        vod_capture(app).player_stats_auto_recording_suppressed = True
        app.player_stats_status_label = FakeLabel()
        stat_label = FakeLabel()
        app.player_stats_rows = {"Damage": stat_label}
        app.player_stats_items_label = FakeLabel()
        app.player_stats_banishes_label = FakeLabel()
        live_snapshot_store(app).live_banishes = ()
        app.player_stats_in_game_time_label = FakeLabel()
        app.player_stats_chests_per_minute_label = FakeLabel()
        app.player_stats_powerups_duration_label = FakeLabel()
        app.player_stats_mob_kills_label = FakeLabel()
        app.player_stats_level_label = FakeLabel()
        app.player_stats_new_items_label = FakeLabel()
        app.player_stats_stage_summary_labels = []
        app._live_stat_cards = RecordingStatCardsView()
        app._live_items_section = items_section_over(app.player_stats_items_label)
        player_stats_memory(app)._get_player_stats_client = lambda: SimpleNamespace(
            get_run_timer=lambda: 21.5,
            get_killed_mobs=lambda: 37,
            get_player_level=lambda owner_stats=None: 2,
        )
        player_stats_memory(app).close_player_stats_client = lambda: None
        attach_player_stats_view(app).refresh_player_stats_timeline_ui = lambda *args, **kwargs: None
        app._refresh_vods_list_if_visible = lambda: None
        app._is_live_stats_tab_active = lambda: True
        player_stats_memory(app).read_player_stats_only = lambda _context=None: (
            {
                "Damage": SimpleNamespace(display_value="123", value=1.23),
                "Powerup Multiplier": SimpleNamespace(display_value="1.5x", value=1.5),
            },
            0x1234,
        )

        def fail_items(owner_stats=None, _context=None):
            raise MemoryReadError("items missing")

        player_stats_memory(app).read_passive_items_only = fail_items
        app.live_run_tracker = SimpleNamespace(
            update=lambda *args, **kwargs: None,
            update_chests_and_keys=lambda *args, **kwargs: None,
            mark_read_failed=lambda *args, **kwargs: None,
            stage_summary_rows=lambda: [],
            current_ui_kps=lambda: None,
        )
        app.overlay_state_store = None
        with patch.object(config, "AUTO_START_RECORDING", False):
            result = MegabonkApp.refresh_live_player_stats_now(app)

        self.assertTrue(result)
        self.assertEqual(app.player_stats_status_label.text(), "Live player stats")
        self.assertEqual(stat_label.text(), "123")
        self.assertEqual(app.player_stats_items_label.text(), "Items unavailable")
        self.assertEqual(app.player_stats_chests_per_minute_label.text(), "Average chests/min: --")
        self.assertEqual(app.player_stats_powerups_duration_label.text(), "Powerups: 22s | Clock: 18s")
        self.assertEqual(app.player_stats_in_game_time_label.text(), "In-Game Time: 00:21")
        self.assertEqual(app.player_stats_mob_kills_label.text(), "Mob Kills: 37")
        self.assertEqual(app.player_stats_level_label.text(), "Level: 2")
        self.assertEqual(app.player_stats_new_items_label.text(), "Live snapshot")
        self.assertEqual(app.player_stats_banishes_label.text(), "No banishes yet")

    def test_refresh_live_player_stats_now_keeps_recording_after_primary_read_failure(self) -> None:
        app = self.build_recording_app()
        app.player_stats_vod_recorder = FakeRecordingRecorder(is_recording=True)
        app.player_stats_status_label.setText("Live player stats (recording)")
        player_stats_memory(app)._read_live_player_stats_data = lambda: (_ for _ in ()).throw(
            MemoryReadError("transient player read")
        )

        result = MegabonkApp.refresh_live_player_stats_now(app)

        self.assertFalse(result)
        self.assertTrue(app.player_stats_vod_recorder.is_recording)
        self.assertEqual(app.player_stats_status_label.text(), "Live player stats (recording)")

    def test_refresh_chaos_tome_tracker_updates_powerups_when_in_game_overlay_window_is_not_visible(self) -> None:
        powerup_reads: list[int] = []
        powerup_updates: list[object] = []
        powerup_snapshot = SimpleNamespace(active=["Rage"])
        client = SimpleNamespace(
            resolve_owner_stats=lambda: 0x1234,
            get_powerup_tracking_snapshot=lambda owner_stats: powerup_reads.append(owner_stats) or powerup_snapshot,
            get_expected_chest_inputs=lambda owner_stats: (7, 3),
            get_chaos_tracking_state=lambda owner_stats: (None, {}),
        )
        refreshed: list[str] = []
        service, world = build_refresh_tasks(stats_client=client)
        world.view.refresh_powerups_card = lambda: refreshed.append("label")
        world.tracker.update_powerups = lambda snapshot: powerup_updates.append(snapshot)

        overlay_cfg = {
            "enabled": True,
            "widgets": {
                "powerups": {"enabled": True},
                "kps": {"enabled": False},
            },
        }
        with patch.object(config, "IN_GAME_OVERLAY", overlay_cfg), \
             patch.object(time, "monotonic", return_value=100.0):
            self.assertTrue(service._refresh_powerups_task(RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)))

        self.assertEqual(powerup_reads, [0x1234])
        self.assertEqual(powerup_updates, [powerup_snapshot])
        self.assertEqual(refreshed, ["label"])

    def test_refresh_chaos_tome_tracker_updates_fast_stage_timer_when_event_timer_enabled(self) -> None:
        fast_stage_updates: list[dict[str, object]] = []
        client = SimpleNamespace(
            resolve_owner_stats=lambda: 0x1234,
            get_powerup_tracking_snapshot=lambda owner_stats: SimpleNamespace(active=["Rage"]),
            get_expected_chest_inputs=lambda owner_stats: (7, 3),
            get_stage_timer_context=lambda: (25.0, 2, 480.0),
            get_chaos_tracking_state=lambda owner_stats: (None, {}),
        )
        service, world = build_refresh_tasks(stats_client=client)
        world.tracker.update_fast_stage_timer = lambda **kwargs: fast_stage_updates.append(kwargs)

        overlay_cfg = {
            "enabled": True,
            "widgets": {
                "powerups": {"enabled": False},
                "kps": {"enabled": False},
                "event_timer": {"enabled": True},
            },
        }
        with patch.object(config, "IN_GAME_OVERLAY", overlay_cfg), \
             patch.object(time, "monotonic", return_value=100.0):
            self.assertTrue(service._refresh_event_timer_task(RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)))

        self.assertEqual(
            fast_stage_updates,
            [
                {
                    "stage_timer_seconds": 25.0,
                    "stage_index": 2,
                    "stage_duration_seconds": 480.0,
                }
            ],
        )

    def test_refresh_chaos_tome_tracker_updates_kps_when_in_game_overlay_window_is_not_visible(self) -> None:
        run_timer_reads: list[int] = []
        mob_kill_reads: list[int] = []
        tracked_kills: list[tuple[float, int]] = []
        client = SimpleNamespace(
            resolve_owner_stats=lambda: 0x1234,
            get_expected_chest_inputs=lambda owner_stats: (7, 3),
            get_run_timer=lambda: run_timer_reads.append(1) or 21.5,
            get_killed_mobs=lambda: mob_kill_reads.append(1) or 37,
            get_chaos_tracking_state=lambda owner_stats: (None, {}),
        )
        service, world = build_refresh_tasks(stats_client=client)
        world.tracker.track_kills = (
            lambda run_timer, mob_kills: tracked_kills.append((run_timer, mob_kills))
        )
        world.tracker.current_ui_kps = lambda: 123

        overlay_cfg = {
            "enabled": True,
            "widgets": {
                "powerups": {"enabled": False},
                "kps": {"enabled": True},
            },
        }
        with patch.object(config, "IN_GAME_OVERLAY", overlay_cfg), \
             patch.object(time, "monotonic", return_value=100.0):
            self.assertTrue(service._refresh_combat_metrics_task(RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)))

        self.assertEqual(run_timer_reads, [1])
        self.assertEqual(mob_kill_reads, [1])
        self.assertEqual(tracked_kills, [(21.5, 37)])

    def test_owner_stats_is_shared_by_due_fast_tasks(self) -> None:
        owner_reads: list[str] = []
        client = SimpleNamespace(
            resolve_owner_stats=lambda: owner_reads.append("owner") or 0x1234,
            get_powerup_tracking_snapshot=lambda _owner: SimpleNamespace(active=[]),
            get_expected_chest_inputs=lambda _owner: (7, 3),
            get_chaos_tracking_state=lambda _owner: (None, {}),
        )
        service, _world = build_refresh_tasks(stats_client=client)
        context = RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)

        self.assertTrue(service._refresh_powerups_task(context))
        self.assertTrue(service._refresh_expected_chest_inputs_task(context))
        self.assertTrue(service._refresh_chaos_tome_task(context))

        self.assertEqual(owner_reads, ["owner"])

    def test_powerup_failure_does_not_block_other_owner_tasks(self) -> None:
        expected_updates: list[tuple[int, int]] = []
        chaos_updates: list[dict[str, object]] = []
        client = SimpleNamespace(
            resolve_owner_stats=lambda: 0x1234,
            get_powerup_tracking_snapshot=lambda _owner: (_ for _ in ()).throw(
                MemoryReadError("powerups unavailable")
            ),
            get_expected_chest_inputs=lambda _owner: (7, 3),
            get_chaos_tracking_state=lambda _owner: (2, {1: ()}),
        )
        service, world = build_refresh_tasks(stats_client=client)
        world.tracker.track_expected_key_procs = (
            lambda bought, keys: expected_updates.append((bought, keys))
        )
        world.tracker.update_chaos_tome = lambda **kwargs: chaos_updates.append(kwargs)
        context = RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)

        self.assertFalse(service._refresh_powerups_task(context))
        self.assertTrue(service._refresh_expected_chest_inputs_task(context))
        self.assertTrue(service._refresh_chaos_tome_task(context))

        self.assertEqual(expected_updates, [(7, 3)])
        self.assertEqual(chaos_updates, [{"chaos_level": 2, "permanent_modifiers": {1: ()}}])

    def test_repeated_memory_errors_close_cached_player_stats_client(self) -> None:
        closed: list[str] = []
        client = SimpleNamespace(
            close=lambda: closed.append("closed"),
            resolve_owner_stats=lambda: 0x1234,
            get_chaos_tracking_state=(
                lambda _owner: (_ for _ in ()).throw(MemoryReadError("stale handle"))
            ),
        )
        service, world = build_refresh_tasks(stats_client=client)
        world.snapshot_store.last_seed = 1
        world.snapshot_store.last_run_timer = 2.0
        # The failure path also marks the feature failed, and that marker raising
        # must not swallow the reconnect -- which is the other half of this test.
        world.tracker.mark_feature_failed = lambda *_args: (_ for _ in ()).throw(
            RuntimeError("feature-state update failed")
        )

        self.assertFalse(service._refresh_chaos_tome_task(RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)))
        self.assertFalse(service._refresh_chaos_tome_task(RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)))
        self.assertIsNotNone(world.stats_client)
        self.assertEqual(closed, [])

        self.assertFalse(service._refresh_chaos_tome_task(RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)))
        self.assertIsNone(world.stats_client)
        self.assertEqual(closed, ["closed"])

    def test_successful_memory_read_resets_error_streak(self) -> None:
        client = SimpleNamespace(
            resolve_owner_stats=lambda: 0x1234,
            get_chaos_tracking_state=lambda _owner: (2, {}),
        )
        service, world = build_refresh_tasks(stats_client=client)
        world.memory._player_stats_memory_error_streak = 2

        self.assertTrue(service._refresh_chaos_tome_task(RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)))
        self.assertEqual(world.memory._player_stats_memory_error_streak, 0)

    def test_chaos_refresh_throttles_expected_chest_reads_to_500ms(self) -> None:
        expected_reads: list[int] = []
        tracked: list[tuple[int, int]] = []
        client = SimpleNamespace(
            resolve_owner_stats=lambda: 0x1234,
            get_expected_chest_inputs=lambda owner_stats: (
                expected_reads.append(owner_stats) or 7,
                3,
            ),
            get_chaos_tracking_state=lambda owner_stats: (None, {}),
        )
        service, world = build_refresh_tasks(stats_client=client)
        world.tracker.track_expected_key_procs = (
            lambda bought, keys: tracked.append((bought, keys))
        )

        with patch.object(time, "monotonic", side_effect=(100.0, 100.25, 100.5)):
            self.assertTrue(service._refresh_expected_chest_inputs_task(RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)))
            self.assertTrue(service._refresh_expected_chest_inputs_task(RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)))
            self.assertTrue(service._refresh_expected_chest_inputs_task(RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)))

        self.assertEqual(expected_reads, [0x1234, 0x1234, 0x1234])
        self.assertEqual(tracked, [(7, 3), (7, 3), (7, 3)])

    def test_combat_refresh_reads_the_complete_pair_on_every_demanded_tick(self) -> None:
        run_timer_reads: list[int] = []
        mob_kill_reads: list[int] = []
        tracked_kills: list[tuple[float, int]] = []

        client = SimpleNamespace(
            resolve_owner_stats=lambda: 0x1234,
            get_expected_chest_inputs=lambda owner_stats: (7, 3),
            get_run_timer=MagicMock(side_effect=lambda: run_timer_reads.append(1) or next(run_timer_values)),
            get_killed_mobs=lambda: mob_kill_reads.append(1) or 37,
            get_chaos_tracking_state=lambda owner_stats: (None, {}),
        )
        run_timer_values = iter((21.5, 21.5, 22.5))
        # The web-overlay KPS widget is the demand here, so the port is injected
        # active rather than assembled from `config.OVERLAY` plus a running
        # server: what this test asserts is the throttle, not the config parse.
        service, world = build_refresh_tasks(stats_client=client, widget_refresh_active=True)
        world.tracker.track_kills = (
            lambda run_timer, mob_kills: tracked_kills.append((run_timer, mob_kills))
        )
        world.tracker.current_ui_kps = lambda: 123

        with patch.object(time, "monotonic", side_effect=(100.0, 100.25, 101.0)):
            self.assertTrue(service._refresh_combat_metrics_task(RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)))
            self.assertTrue(service._refresh_combat_metrics_task(RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)))
            self.assertTrue(service._refresh_combat_metrics_task(RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)))

        self.assertEqual(run_timer_reads, [1, 1, 1])
        self.assertEqual(mob_kill_reads, [1, 1, 1])
        self.assertEqual(tracked_kills, [(21.5, 37), (21.5, 37), (22.5, 37)])
        self.assertEqual(len(world.overlay_syncs), 3)

    def _fast_kps_app_with_live_stats_tab_showing(self, label):
        """A fast-KPS app double with the Live Stats tab *active*.

        Every other fast-KPS test above sets `_is_live_stats_tab_active` to
        False, so the branch that writes the mob-kills line was uncovered --
        neutering that writer left all 582 tests green. Step 17a rerouted it
        through `PlayerStatsView`, so it gets covered here.
        """
        app = object.__new__(MegabonkApp)
        app._is_live_stats_tab_active = lambda: True
        app.overlay_should_refresh_live_stats = lambda: False
        app._is_twitch_bot_active = lambda: False
        app.player_stats_mob_kills_label = label
        attach_player_stats_view(app).set_stage_summary_rows = lambda rows: None
        app.update_overlay_state_from_tracker = lambda: None
        app.overlay_server = SimpleNamespace(is_running=False)
        player_stats_memory(app)._get_player_stats_client = lambda: SimpleNamespace(
            resolve_owner_stats=lambda: 0x1234,
            get_expected_chest_inputs=lambda owner_stats: (7, 3),
            get_run_timer=lambda: 21.5,
            get_killed_mobs=lambda: 37,
            get_chaos_tracking_state=lambda owner_stats: (None, {}),
        )
        app.live_run_tracker = SimpleNamespace(
            track_expected_key_procs=lambda bought, keys: None,
            update_chaos_tome=lambda **kwargs: None,
            track_kills=lambda run_timer, mob_kills: None,
            update_fast_run_timer=lambda run_timer: None,
            current_ui_kps=lambda: 123,
            current_minute_avg_kps=lambda: 90,
            current_five_minute_avg_kps=lambda: 75,
            chaos_tome_snapshot=lambda: None,
            stage_summary_rows=lambda: [],
        )
        return app

    def test_fast_kps_writes_the_mob_kills_line_when_live_stats_is_showing(self) -> None:
        label = FakeLabel()
        app = self._fast_kps_app_with_live_stats_tab_showing(label)

        with patch.object(config, "OVERLAY", {"widgets": []}), patch.object(
            time, "monotonic", side_effect=(100.0, 101.0)
        ):
            self.assertTrue(refresh_tasks(app)._refresh_combat_metrics_task(RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)))

        # The real formatter, through the real MRO: player_stats_view(app)
        # returns app, whose set_mob_kills_text comes from LiveStatsTabMixin.
        self.assertEqual(label.text(), formatting.format_mob_kills(37, 123))
        self.assertEqual(label.text(), "Mob Kills: 37 (123/s)")

    def test_fast_kps_mob_kills_goes_through_the_player_stats_view_port(self) -> None:
        """An injected view receives it, and the widget is left alone.

        This is what distinguishes the port from the old direct `_set_text`
        write: with a substitute view in place, nothing touches the label.
        """
        label = FakeLabel()
        app = self._fast_kps_app_with_live_stats_tab_showing(label)
        received: list[str] = []
        stage_rows: list = []
        app._player_stats_view = SimpleNamespace(
            set_mob_kills_text=lambda text: received.append(text),
            # Step 19 moved the stage-summary write onto the same port, for the
            # same reason: `refresh_tasks` was reaching the labels widget
            # directly. An injected view now has to satisfy both, which is what
            # proves neither still reaches around the port.
            set_stage_summary_rows=lambda rows: stage_rows.append(rows),
            set_in_game_time_text=lambda text: None,
            set_kps_averages_text=lambda text: None,
        )

        with patch.object(config, "OVERLAY", {"widgets": []}), patch.object(
            time, "monotonic", side_effect=(100.0, 101.0)
        ):
            self.assertTrue(refresh_tasks(app)._refresh_combat_metrics_task(RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)))

        self.assertEqual(received, ["Mob Kills: 37 (123/s)"])
        self.assertEqual(label.text(), "")
        self.assertEqual(len(stage_rows), 1)

    def test_chaos_refresh_skips_fast_kps_reads_when_overlay_kps_widget_is_disabled(self) -> None:
        run_timer_reads: list[int] = []
        mob_kill_reads: list[int] = []
        tracked_kills: list[tuple[float, int]] = []

        client = SimpleNamespace(
            resolve_owner_stats=lambda: 0x1234,
            get_expected_chest_inputs=lambda owner_stats: (7, 3),
            get_run_timer=lambda: run_timer_reads.append(1) or 21.5,
            get_killed_mobs=lambda: mob_kill_reads.append(1) or 37,
            get_chaos_tracking_state=lambda owner_stats: (None, {}),
        )
        # Every consumer of fast KPS is off: no tab, no recorder, no Twitch, and
        # the web-overlay port injected inactive. The in-game overlay stays a
        # real `config` read, because that is the branch this test names.
        service, world = build_refresh_tasks(stats_client=client)
        world.tracker.track_kills = (
            lambda run_timer, mob_kills: tracked_kills.append((run_timer, mob_kills))
        )

        with patch.object(
            config,
            "IN_GAME_OVERLAY",
            {"enabled": False, "widgets": {}},
        ):
            self.assertFalse(service._should_refresh_fast_kps())

        self.assertEqual(run_timer_reads, [])
        self.assertEqual(mob_kill_reads, [])
        self.assertEqual(tracked_kills, [])
        self.assertEqual(world.overlay_syncs, [])

    def test_combat_refresh_keeps_kills_current_while_game_timer_is_frozen(self) -> None:
        run_timer_reads: list[int] = []
        mob_kill_reads: list[int] = []
        tracked_kills: list[tuple[float, int]] = []

        run_timer_values = iter((21.5, 21.5, 21.5))
        client = SimpleNamespace(
            resolve_owner_stats=lambda: 0x1234,
            get_expected_chest_inputs=lambda owner_stats: (7, 3),
            get_run_timer=MagicMock(side_effect=lambda: run_timer_reads.append(1) or next(run_timer_values)),
            get_killed_mobs=lambda: mob_kill_reads.append(1) or 37,
            get_chaos_tracking_state=lambda owner_stats: (None, {}),
        )
        service, world = build_refresh_tasks(stats_client=client, widget_refresh_active=True)
        world.tracker.track_kills = (
            lambda run_timer, mob_kills: tracked_kills.append((run_timer, mob_kills))
        )
        world.tracker.current_ui_kps = lambda: 123

        with patch.object(time, "monotonic", side_effect=(100.0, 100.25, 101.0)):
            self.assertTrue(service._refresh_combat_metrics_task(RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)))
            self.assertTrue(service._refresh_combat_metrics_task(RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)))
            self.assertTrue(service._refresh_combat_metrics_task(RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)))

        self.assertEqual(run_timer_reads, [1, 1, 1])
        self.assertEqual(mob_kill_reads, [1, 1, 1])
        self.assertEqual(tracked_kills, [(21.5, 37), (21.5, 37), (21.5, 37)])
        self.assertEqual(len(world.overlay_syncs), 3)

    def test_refresh_live_player_stats_now_captures_while_hidden_recording(self) -> None:
        app = self.build_recording_app()
        app.player_stats_vod_recorder = FakeRecordingRecorder(is_recording=True, should_capture=True)
        app.player_stats_vod_snapshots = []
        app.player_stats_selected_snapshot_index = None
        app._is_live_stats_tab_active = lambda: False
        tome = SimpleNamespace(
            name="Damage",
            level=3,
            stat_id=12,
            stat_label="Damage",
            display_value="1.25x",
            tome_id=0,
        )
        player_stats_memory(app)._get_player_stats_client = lambda: SimpleNamespace(
            get_live_weapons=lambda owner_stats=None: (),
            get_live_tomes=lambda owner_stats=None: (tome,),
            get_live_banishes=lambda: ("Clover", "Golden Tome"),
            get_run_timer=lambda: 21.5,
            get_stage_timer_context=lambda: (9.0, 2, None),
            get_stage_timer=lambda: 9.0,
            get_killed_mobs=lambda: 37,
            get_player_level=lambda owner_stats=None: 2,
        )
        app.player_stats_game_data_client = SimpleNamespace(
            get_map_generation_state=lambda: SimpleNamespace(
                map_seed=None,
                current_stage_ptr=0,
            ),
            get_map_activity_values=lambda: {
                "Chests": SimpleNamespace(current=4, max=15),
                "Pots": SimpleNamespace(current=0, max=5),
            }
        )
        timeline_calls: list[str] = []
        snapshot_calls: list[str] = []
        attach_player_stats_view(app).refresh_player_stats_timeline_ui = lambda *args, **kwargs: timeline_calls.append("timeline")
        attach_player_stats_view(app).display_player_stats_snapshot = lambda *args, **kwargs: snapshot_calls.append("snapshot")
        player_stats_memory(app).read_player_stats_only = lambda _context=None: ({"Damage": SimpleNamespace(display_value="123", value=1.23)}, 0x1234)
        player_stats_memory(app).read_passive_items_only = lambda owner_stats=None, _context=None: ("Wrench x2",)

        result = MegabonkApp.refresh_live_player_stats_now(app)

        self.assertTrue(result)
        self.assertEqual(len(app.player_stats_vod_recorder.capture_calls), 1)
        self.assertEqual(app.player_stats_vod_recorder.capture_calls[0]["items"], ("Wrench x2",))
        self.assertEqual(app.player_stats_vod_recorder.capture_calls[0]["tomes"], (tome,))
        self.assertEqual(app.player_stats_vod_recorder.capture_calls[0]["banishes"], ("Clover", "Golden Tome"))
        self.assertEqual(app.player_stats_vod_recorder.capture_calls[0]["game_time_seconds"], 21.5)
        self.assertEqual(app.player_stats_vod_recorder.capture_calls[0]["mob_kills"], 37)
        self.assertEqual(app.player_stats_vod_recorder.capture_calls[0]["player_level"], 2)
        self.assertEqual(app.player_stats_vod_recorder.capture_calls[0]["stage_index"], 2)
        self.assertIsNotNone(app.player_stats_vod_recorder.capture_calls[0]["chests_total"])
        self.assertIsNotNone(app.player_stats_vod_recorder.capture_calls[0]["pots_total"])
        self.assertEqual(snapshot_calls, [])
        self.assertEqual(timeline_calls, ["timeline"])

    def _map_activity_app(self, activity_values, *, active_run: bool):
        """A recording app whose map-activity read returns `activity_values`."""
        app = self.build_recording_app()
        app._is_live_stats_tab_active = lambda: False
        state = RuntimeGameState(
            mode=RuntimeGameMode.IN_GAME if active_run else RuntimeGameMode.MAIN_MENU,
            is_playing=active_run,
        )
        player_stats_memory(app).read_player_stats_runtime_game_state = (
            lambda _context=None: state
        )
        player_stats_memory(app).read_player_stats_runtime_activity_state = (
            lambda _context=None: state
        )
        run_lifecycle(app).refresh()
        player_stats_memory(app)._get_player_stats_client = lambda: SimpleNamespace(
            get_live_weapons=lambda owner_stats=None: (),
            get_live_tomes=lambda owner_stats=None: (),
            get_live_banishes=lambda: (),
            get_run_timer=lambda: 21.5,
            get_stage_timer_context=lambda: (9.0, 0, None),
            get_stage_timer=lambda: 9.0,
            get_killed_mobs=lambda: 37,
            get_player_level=lambda owner_stats=None: 2,
        )
        closes: list[int] = []
        app.player_stats_game_data_client = SimpleNamespace(
            get_map_generation_state=lambda: SimpleNamespace(
                map_seed=None,
                current_stage_ptr=0,
            ),
            get_map_activity_values=lambda: activity_values,
            close=lambda: closes.append(1),
        )
        return app, closes

    def test_an_empty_map_activity_read_recycles_the_game_data_client(self) -> None:
        """`get_map_activity_values` returns `{}` -- it does not raise -- whenever
        any pointer in its chain reads zero. A stale client therefore answered
        "no activities" forever without ever advancing the reconnect streak, and
        `refresh_now` skips the powerup map-context publish on an empty read.
        Observed live on 2026-07-23: the chests card froze and every powerup lost
        its start/end while the rest of the app looked healthy.
        """
        app, closes = self._map_activity_app({}, active_run=True)

        for _ in range(3):
            MegabonkApp.refresh_live_player_stats_now(app)

        self.assertEqual(len(closes), 1)
        self.assertEqual(
            player_stats_memory(app)._player_stats_game_data_memory_error_streak, 0
        )

    def test_an_empty_map_activity_read_outside_a_run_is_not_a_failure(self) -> None:
        """Menu and loading screens legitimately have no activities. Counting
        those would recycle the client every ten seconds while the game sits on
        the main menu."""
        app, closes = self._map_activity_app({}, active_run=False)

        for _ in range(3):
            MegabonkApp.refresh_live_player_stats_now(app)

        self.assertEqual(closes, [])
        self.assertEqual(
            player_stats_memory(app)._player_stats_game_data_memory_error_streak, 0
        )

    def test_a_populated_map_activity_read_publishes_the_powerup_map_context(self) -> None:
        """The other side of the same branch: a good read must still reach the
        publish, which is what powerups need to show start and end times."""
        app, closes = self._map_activity_app(
            {
                "Chests": SimpleNamespace(current=4, max=46),
                "Pots": SimpleNamespace(current=0, max=55),
            },
            active_run=True,
        )

        MegabonkApp.refresh_live_player_stats_now(app)

        self.assertEqual(closes, [])
        context = app.live_run_tracker.powerup_map_context()
        self.assertIsNotNone(context)
        self.assertFalse(context.is_graveyard)
        self.assertEqual((context.activity_max or {}).get("Chests"), 46)

    def test_refresh_live_player_stats_now_does_not_capture_while_paused(self) -> None:
        app = self.build_recording_app()
        app.player_stats_vod_recorder = FakeRecordingRecorder(is_recording=True, should_capture=True)
        app.player_stats_vod_snapshots = []
        app.player_stats_selected_snapshot_index = None
        app._is_live_stats_tab_active = lambda: False
        player_stats_memory(app).read_player_stats_runtime_game_state = lambda _context=None: RuntimeGameState(
            mode=RuntimeGameMode.PAUSED_IN_GAME,
            is_playing=True,
            is_paused=True,
        )
        player_stats_memory(app)._get_player_stats_client = lambda: SimpleNamespace(
            get_live_weapons=lambda owner_stats=None: (),
            get_live_tomes=lambda owner_stats=None: (),
            get_live_banishes=lambda: (),
            get_run_timer=lambda: 21.5,
            get_stage_timer=lambda: 9.0,
            get_killed_mobs=lambda: 37,
            get_player_level=lambda owner_stats=None: 2,
        )
        player_stats_memory(app).read_player_stats_only = lambda _context=None: (
            {"Damage": SimpleNamespace(display_value="123", value=1.23)},
            0x1234,
        )
        player_stats_memory(app).read_passive_items_only = lambda owner_stats=None, _context=None: ("Wrench x2",)

        result = MegabonkApp.refresh_live_player_stats_now(app)

        self.assertTrue(result)
        self.assertEqual(app.player_stats_vod_recorder.capture_calls, [])
        self.assertEqual(app.player_stats_vod_snapshots, [])

    def test_refresh_live_player_stats_now_does_not_capture_when_runtime_state_is_unknown(self) -> None:
        app = self.build_recording_app()
        app.player_stats_vod_recorder = FakeRecordingRecorder(is_recording=True, should_capture=True)
        app.player_stats_vod_snapshots = []
        app.player_stats_selected_snapshot_index = None
        app._is_live_stats_tab_active = lambda: False
        player_stats_memory(app).read_player_stats_runtime_game_state = lambda _context=None: (_ for _ in ()).throw(
            MemoryReadError("runtime state unavailable")
        )
        player_stats_memory(app)._get_player_stats_client = lambda: SimpleNamespace(
            get_live_weapons=lambda owner_stats=None: (),
            get_live_tomes=lambda owner_stats=None: (),
            get_live_banishes=lambda: (),
            get_run_timer=lambda: 21.5,
            get_stage_timer=lambda: 9.0,
            get_killed_mobs=lambda: 37,
            get_player_level=lambda owner_stats=None: 2,
        )
        player_stats_memory(app).read_player_stats_only = lambda _context=None: (
            {"Damage": SimpleNamespace(display_value="123", value=1.23)},
            0x1234,
        )
        player_stats_memory(app).read_passive_items_only = lambda owner_stats=None, _context=None: ("Wrench x2",)

        result = MegabonkApp.refresh_live_player_stats_now(app)

        self.assertTrue(result)
        self.assertEqual(app.player_stats_vod_recorder.capture_calls, [])
        self.assertEqual(app.player_stats_vod_snapshots, [])

    def test_refresh_live_player_stats_now_updates_live_view_while_recording(self) -> None:
        app = self.build_recording_app()
        app.player_stats_vod_recorder = FakeRecordingRecorder(is_recording=True, should_capture=False)
        app.player_stats_vod_snapshots = []
        app.player_stats_selected_snapshot_index = None
        app._is_live_stats_tab_active = lambda: True
        tome = SimpleNamespace(
            name="Armor",
            level=2,
            stat_id=4,
            stat_label="Armor",
            display_value="20%",
            tome_id=5,
        )
        player_stats_memory(app)._get_player_stats_client = lambda: SimpleNamespace(
            get_live_weapons=lambda owner_stats=None: (),
            get_live_tomes=lambda owner_stats=None: (tome,),
            get_live_banishes=lambda: ("Clover", "Golden Tome"),
            get_run_timer=lambda: 21.5,
            get_stage_timer=lambda: 9.0,
            get_killed_mobs=lambda: 37,
            get_player_level=lambda owner_stats=None: 2,
        )
        display_calls: list[dict[str, object]] = []
        attach_player_stats_view(app).display_player_stats = lambda stats, items=(), **kwargs: display_calls.append(
            {"stats": stats, "items": tuple(items), "kwargs": kwargs}
        )
        player_stats_memory(app).read_player_stats_only = lambda _context=None: ({"Damage": SimpleNamespace(display_value="123", value=1.23)}, 0x1234)
        player_stats_memory(app).read_passive_items_only = lambda owner_stats=None, _context=None: ("Wrench x2",)

        result = MegabonkApp.refresh_live_player_stats_now(app)

        self.assertTrue(result)
        self.assertEqual(len(display_calls), 1)
        self.assertEqual(display_calls[0]["items"], ("Wrench x2",))
        self.assertEqual(display_calls[0]["kwargs"]["tomes"], (tome,))
        self.assertEqual(display_calls[0]["kwargs"]["banishes"], ("Clover", "Golden Tome"))
        self.assertEqual(display_calls[0]["kwargs"]["status_text"], "Live player stats (recording)")

    def test_refresh_live_player_stats_now_auto_starts_recording_after_stable_run_detection(self) -> None:
        app = self.build_recording_app()
        app.player_stats_vod_recorder = FakeRecordingRecorder(is_recording=False, should_capture=False)
        app.player_stats_vod_snapshots = []
        app.player_stats_selected_snapshot_index = None
        app._is_live_stats_tab_active = lambda: False
        player_stats_memory(app).read_player_stats_only = lambda _context=None: ({"Damage": SimpleNamespace(display_value="123", value=1.23)}, 0x1234)
        player_stats_memory(app).read_passive_items_only = lambda owner_stats=None, _context=None: ()
        player_stats_memory(app).read_player_stats_recording_state = lambda _context=None: SimpleNamespace(map_seed=777, current_stage_ptr=2)
        player_stats_memory(app)._get_player_stats_client = lambda: SimpleNamespace(
            get_run_timer=lambda: 21.5,
            get_stage_timer=lambda: 9.0,
            get_killed_mobs=lambda: 37,
            get_player_level=lambda owner_stats=None: 2,
        )

        with patch.object(config, "AUTO_START_RECORDING", True):
            first = MegabonkApp.refresh_live_player_stats_now(app)
            second = MegabonkApp.refresh_live_player_stats_now(app)

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertEqual(app.player_stats_vod_recorder.start_calls, [{"name": None, "seed": 777}])
        self.assertTrue(app.player_stats_vod_recorder.is_recording)
        self.assertEqual(vod_capture(app).player_stats_recording_stage_ptr, 2)
        self.assertEqual(vod_capture(app).player_stats_recording_run_time_seconds, 21.5)
        self.assertIn(("[*] Player stats recording auto-started: recording-1.jsonl", "success"), app.log_messages)

    def test_refresh_live_player_stats_now_does_not_auto_start_without_active_run_signal(self) -> None:
        app = self.build_recording_app()
        app.player_stats_vod_recorder = FakeRecordingRecorder(is_recording=False, should_capture=False)
        app.player_stats_vod_snapshots = []
        app.player_stats_selected_snapshot_index = None
        app._is_live_stats_tab_active = lambda: False
        player_stats_memory(app).read_player_stats_only = lambda _context=None: ({}, 0x1234)
        player_stats_memory(app).read_passive_items_only = lambda owner_stats=None, _context=None: ()
        player_stats_memory(app).read_player_stats_recording_state = lambda _context=None: SimpleNamespace(map_seed=None, current_stage_ptr=0)
        player_stats_memory(app)._get_player_stats_client = lambda: SimpleNamespace(
            get_run_timer=lambda: 0.0,
            get_stage_timer=lambda: None,
            get_killed_mobs=lambda: None,
            get_player_level=lambda owner_stats=None: None,
        )

        with patch.object(config, "AUTO_START_RECORDING", True):
            result = MegabonkApp.refresh_live_player_stats_now(app)

        self.assertTrue(result)
        self.assertEqual(app.player_stats_vod_recorder.start_calls, [])
        self.assertFalse(app.player_stats_vod_recorder.is_recording)

    def test_refresh_live_player_stats_now_does_not_auto_start_when_runtime_state_is_unknown(self) -> None:
        app = self.build_recording_app()
        app.player_stats_vod_recorder = FakeRecordingRecorder(is_recording=False, should_capture=False)
        app.player_stats_vod_snapshots = []
        app.player_stats_selected_snapshot_index = None
        app._is_live_stats_tab_active = lambda: False
        player_stats_memory(app).read_player_stats_runtime_game_state = lambda _context=None: (_ for _ in ()).throw(
            MemoryReadError("runtime state unavailable")
        )
        player_stats_memory(app).read_player_stats_only = lambda _context=None: (
            {"Damage": SimpleNamespace(display_value="123", value=1.23)},
            0x1234,
        )
        player_stats_memory(app).read_passive_items_only = lambda owner_stats=None, _context=None: ()
        player_stats_memory(app).read_player_stats_recording_state = lambda _context=None: SimpleNamespace(map_seed=777, current_stage_ptr=2)
        player_stats_memory(app)._get_player_stats_client = lambda: SimpleNamespace(
            get_run_timer=lambda: 21.5,
            get_stage_timer=lambda: 9.0,
            get_killed_mobs=lambda: 37,
            get_player_level=lambda owner_stats=None: 2,
        )

        with patch.object(config, "AUTO_START_RECORDING", True):
            result = MegabonkApp.refresh_live_player_stats_now(app)

        self.assertTrue(result)
        self.assertEqual(vod_capture(app).player_stats_auto_start_detection_streak, 0)
        self.assertEqual(app.player_stats_vod_recorder.start_calls, [])
        self.assertFalse(app.player_stats_vod_recorder.is_recording)

    def test_toggle_player_stats_recording_captures_snapshot_without_items(self) -> None:
        app = self.build_recording_app()
        app.player_stats_vod_recorder = FakeRecordingRecorder(is_recording=False, should_capture=True)
        app.player_stats_vod_snapshots = []
        app.player_stats_selected_snapshot_index = None
        player_stats_memory(app)._read_player_stats_recording_seed_safe = lambda: 321
        player_stats_memory(app).read_player_stats_only = lambda _context=None: ({"Damage": SimpleNamespace(display_value="123", value=1.23)}, 0x1234)

        def fail_items(owner_stats=None, _context=None):
            raise MemoryReadError("items missing")

        player_stats_memory(app).read_passive_items_only = fail_items

        with patch.object(config, "AUTO_START_RECORDING", False):
            vod_capture(app).toggle_recording()

        self.assertEqual(len(app.player_stats_vod_recorder.capture_calls), 1)
        self.assertEqual(app.player_stats_vod_recorder.capture_calls[0]["items"], ())

    def test_refresh_live_player_stats_now_preserves_last_known_items_when_read_fails(self) -> None:
        app = self.build_recording_app()
        app.player_stats_vod_recorder = FakeRecordingRecorder(is_recording=True, should_capture=True)
        app.player_stats_vod_snapshots = []
        app.player_stats_selected_snapshot_index = None
        live_snapshot_store(app).last_known_items = ("Wrench x2", "Clover x1")
        weapon = SimpleNamespace(weapon_id=1, name="Bone")
        tome = SimpleNamespace(tome_id=0, name="Damage")
        damage = SimpleNamespace(source_key="Bone", source_name="Bone", damage=123.0)
        live_snapshot_store(app).last_known_weapons = (weapon,)
        live_snapshot_store(app).last_known_tomes = (tome,)
        live_snapshot_store(app).last_known_damage_sources = (damage,)
        live_snapshot_store(app).last_known_banishes = ("Clover",)
        app._is_live_stats_tab_active = lambda: False
        player_stats_memory(app).read_player_stats_only = lambda _context=None: (
            {"Damage": SimpleNamespace(display_value="123", value=1.23)},
            0x1234,
        )

        def fail_items(owner_stats=None, _context=None):
            raise MemoryReadError("items missing")

        player_stats_memory(app).read_passive_items_only = fail_items
        player_stats_memory(app).read_player_stats_recording_state = lambda _context=None: SimpleNamespace(map_seed=777, current_stage_ptr=2)

        player_stats_memory(app)._get_player_stats_client = lambda: SimpleNamespace(
            get_run_timer=lambda: 21.5,
            get_stage_timer=lambda: 9.0,
            get_killed_mobs=lambda: 37,
            get_player_level=lambda owner_stats=None: 2,
            get_live_weapons=lambda *_args, **_kwargs: (),
            get_live_tomes=lambda *_args, **_kwargs: (),
            get_live_banishes=lambda *_args, **_kwargs: (),
            get_live_damage_sources=lambda *_args, **_kwargs: (),
        )

        result = MegabonkApp.refresh_live_player_stats_now(app)

        self.assertTrue(result)
        self.assertEqual(len(app.player_stats_vod_recorder.capture_calls), 1)
        self.assertEqual(
            app.player_stats_vod_recorder.capture_calls[0]["items"],
            ("Wrench x2", "Clover x1"),
        )
        self.assertEqual(app.player_stats_vod_recorder.capture_calls[0]["weapons"], (weapon,))
        self.assertEqual(app.player_stats_vod_recorder.capture_calls[0]["tomes"], (tome,))
        self.assertEqual(app.player_stats_vod_recorder.capture_calls[0]["damage_sources"], (damage,))
        self.assertEqual(app.player_stats_vod_recorder.capture_calls[0]["banishes"], ("Clover",))

    def test_refresh_live_player_stats_now_preserves_last_known_items_when_read_is_empty(self) -> None:
        app = self.build_recording_app()
        app.player_stats_vod_recorder = FakeRecordingRecorder(is_recording=True, should_capture=True)
        app.player_stats_vod_snapshots = []
        live_snapshot_store(app).last_known_items = ("Wrench x2", "Clover x1")
        player_stats_memory(app).read_player_stats_recording_state = lambda _context=None: SimpleNamespace(map_seed=777, current_stage_ptr=2)
        player_stats_memory(app).read_passive_items_only = lambda owner_stats=None, _context=None: ()

        result = MegabonkApp.refresh_live_player_stats_now(app)

        self.assertTrue(result)
        self.assertEqual(
            app.player_stats_vod_recorder.capture_calls[0]["items"],
            ("Wrench x2", "Clover x1"),
        )
        self.assertEqual(live_snapshot_store(app).last_known_items, ("Wrench x2", "Clover x1"))

    def test_read_live_player_stats_data_accepts_empty_inventory_at_new_match_start(self) -> None:
        app = self.build_recording_app()
        live_snapshot_store(app).last_known_items = ("Wrench x2",)
        live_snapshot_store(app).last_seed = 123
        live_snapshot_store(app).last_run_timer = 45.0
        player_stats_memory(app).read_passive_items_only = lambda owner_stats=None, _context=None: ()
        player_stats_memory(app).read_player_stats_recording_state = lambda _context=None: SimpleNamespace(map_seed=777, current_stage_ptr=2)
        player_stats_memory(app)._get_player_stats_client = lambda: SimpleNamespace(
            get_run_timer=lambda: 2.0,
            get_stage_timer_context=lambda: (2.0, 0, 600.0),
            get_killed_mobs=lambda: 0,
            get_player_level=lambda owner_stats=None: 1,
        )

        result = player_stats_memory(app)._read_live_player_stats_data()

        self.assertEqual(result[1], ())
        self.assertTrue(result[2])
        self.assertEqual(live_snapshot_store(app).last_known_items, None)

    def test_stop_player_stats_recording_refreshes_live_stats_without_items(self) -> None:
        app = object.__new__(MegabonkApp)
        app.player_stats_vod_recorder = FakeRecordingRecorder(is_recording=True)
        app.player_stats_vod_snapshots = ["snapshot"]
        app.player_stats_selected_snapshot_index = 0
        vod_capture(app).player_stats_recording_seed = 111
        vod_capture(app).player_stats_recording_seed_missing_since = 200.0
        vod_capture(app).player_stats_recording_armed = False
        vod_capture(app).player_stats_auto_recording_suppressed = True
        app.player_stats_status_label = FakeLabel()
        stat_label = FakeLabel()
        app.player_stats_rows = {"Damage": stat_label}
        app.player_stats_items_label = FakeLabel()
        app.player_stats_banishes_label = FakeLabel()
        live_snapshot_store(app).live_banishes = ()
        app.player_stats_in_game_time_label = FakeLabel()
        app.player_stats_chests_per_minute_label = FakeLabel()
        app.player_stats_mob_kills_label = FakeLabel()
        app.player_stats_level_label = FakeLabel()
        app.player_stats_new_items_label = FakeLabel()
        app.player_stats_stage_summary_labels = []
        app._live_stat_cards = RecordingStatCardsView()
        app._live_items_section = items_section_over(app.player_stats_items_label)
        player_stats_memory(app)._get_player_stats_client = lambda: SimpleNamespace(
            get_run_timer=lambda: 21.5,
            get_killed_mobs=lambda: 37,
            get_player_level=lambda owner_stats=None: 2,
        )
        player_stats_memory(app).close_player_stats_client = lambda: None
        player_stats_memory(app).close_player_stats_game_data_client = lambda: None
        attach_player_stats_view(app).refresh_player_stats_timeline_ui = lambda *args, **kwargs: None
        app._refresh_vods_list_if_visible = lambda: None
        app._is_live_stats_tab_active = lambda: True
        app.log = lambda *args, **kwargs: None
        player_stats_memory(app).read_player_stats_only = lambda _context=None: ({"Damage": SimpleNamespace(display_value="123", value=1.23)}, 0x1234)

        def fail_items(owner_stats=None, _context=None):
            raise MemoryReadError("items missing")

        player_stats_memory(app).read_passive_items_only = fail_items
        app.live_run_tracker = SimpleNamespace(
            update=lambda *args, **kwargs: None,
            update_chests_and_keys=lambda *args, **kwargs: None,
            mark_read_failed=lambda *args, **kwargs: None,
            stage_summary_rows=lambda: [],
            current_ui_kps=lambda: None,
        )
        app.overlay_state_store = None
        with patch.object(config, "AUTO_START_RECORDING", False):
            vod_capture(app).stop_recording()

        self.assertEqual(app.player_stats_vod_recorder.stop_calls, 1)
        self.assertEqual(app.player_stats_status_label.text(), "Live player stats")
        self.assertEqual(stat_label.text(), "123")
        self.assertEqual(app.player_stats_items_label.text(), "Items unavailable")
        self.assertEqual(app.player_stats_in_game_time_label.text(), "In-Game Time: 00:21")
        self.assertEqual(app.player_stats_mob_kills_label.text(), "Mob Kills: 37")
        self.assertEqual(app.player_stats_level_label.text(), "Level: 2")
        self.assertEqual(app.player_stats_new_items_label.text(), "Live snapshot")

    def test_display_player_stats_snapshot_shows_in_game_time_in_status_and_summary(self) -> None:
        app = object.__new__(MegabonkApp)
        app.player_stats_vod_snapshots = []
        calls: list[dict[str, object]] = []
        snapshot = SimpleNamespace(
            stats={"Damage": SimpleNamespace(display_value="123", value=1.23)},
            items=("Wrench x2",),
            tomes=(SimpleNamespace(name="Damage", level=3, stat_id=12, stat_label="Damage", display_value="1.25x", tome_id=0),),
            banishes=("Clover", "Golden Tome"),
            chests_per_minute=1.5,
            game_time_seconds=81.75,
            mob_kills=42,
            player_level=4,
            time_label="01:00",
        )
        view = build_live_stats_tab(vod_snapshots=lambda: [snapshot])
        view.display_player_stats = lambda stats, items=(), **kwargs: calls.append(
            {"stats": stats, "items": tuple(items), "kwargs": kwargs}
        )

        view.display_player_stats_snapshot(snapshot)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["kwargs"]["status_text"], "Recorded snapshot 1/1 at 01:00 | In-Game Time: 01:21")
        self.assertEqual(calls[0]["kwargs"]["game_time_seconds"], 81.75)
        self.assertEqual(calls[0]["kwargs"]["mob_kills"], 42)
        self.assertEqual(calls[0]["kwargs"]["player_level"], 4)
        self.assertEqual(calls[0]["kwargs"]["tomes"], snapshot.tomes)
        self.assertEqual(calls[0]["kwargs"]["banishes"], snapshot.banishes)

    def test_display_player_stats_snapshot_uses_compact_segment_compare_text(self) -> None:
        calls: list[dict[str, object]] = []
        previous = SimpleNamespace(
            stats={},
            items=("Wrench x1",),
            game_time_seconds=60.0,
            mob_kills=100,
            player_level=3,
            time_label="01:00",
        )
        current = SimpleNamespace(
            stats={},
            items=("Wrench x3", "Za Warudo x1"),
            tomes=(),
            banishes=(),
            chests_per_minute=None,
            game_time_seconds=90.0,
            mob_kills=133,
            player_level=3,
            time_label="01:30",
        )
        view = build_live_stats_tab(vod_snapshots=lambda: [previous, current])
        view.display_player_stats = lambda stats, items=(), **kwargs: calls.append(
            {"stats": stats, "items": tuple(items), "kwargs": kwargs}
        )

        view.display_player_stats_snapshot(current)

        self.assertIn("+3</span>", calls[0]["kwargs"]["new_items_text"])
        self.assertIn("Time:</span> 00:30", calls[0]["kwargs"]["new_items_text"])
        self.assertIn("Kills:</span> +33", calls[0]["kwargs"]["new_items_text"])
        self.assertNotIn("Za Warudo +1", calls[0]["kwargs"]["new_items_text"])

    def test_display_loaded_vod_snapshot_shows_legacy_in_game_fallback(self) -> None:
        app = build_recordings_tab()
        app._status_label = FakeLabel()
        app._slider_time_label = FakeLabel()
        app.vods_items_label = FakeLabel()
        app._in_game_time_label = FakeLabel()
        app._chests_per_minute_label = FakeLabel()
        app._mob_kills_label = FakeLabel()
        app._kps_averages_label = FakeLabel()
        app._level_label = FakeLabel()
        app._new_items_label = FakeLabel()
        app._banishes_label = FakeLabel()
        app._stage_summary_labels = []
        app._rows = {"Damage": FakeLabel()}
        app._stat_cards = RecordingStatCardsView()
        app._items_section = items_section_over(app.vods_items_label)
        app._snapshot_index = None
        snapshot = SimpleNamespace(
            stats={"Damage": SimpleNamespace(display_value="123", value=1.23)},
            items=("Wrench x1",),
            tomes=(),
            banishes=(),
            chests_per_minute=1.23,
            game_time_seconds=None,
            mob_kills=None,
            player_level=None,
            time_label="00:00",
        )
        metadata = SimpleNamespace(name="Legacy run")
        app._loaded_vod = SimpleNamespace(metadata=metadata, snapshots=[snapshot])

        app.display_loaded_vod_snapshot(0)

        self.assertEqual(app._status_label.text(), "Legacy run | 1/1 at 00:00 | In-Game Time: --")
        self.assertEqual(app._in_game_time_label.text(), "In-Game Time: --")
        self.assertEqual(app._mob_kills_label.text(), "Mob Kills: --")
        self.assertEqual(app._kps_averages_label.text(), "KPS: 60s -- | 5m --")
        self.assertEqual(app._level_label.text(), "Level: --")
        self.assertEqual(app._new_items_label.text(), "No previous snapshot")
        self.assertEqual(app._banishes_label.text(), "No banishes yet")
        self.assertEqual(app.vods_items_label.text(), "Wrench x1")

    def test_display_loaded_vod_snapshot_updates_damage_sources_tab(self) -> None:
        app = build_recordings_tab()
        app._status_label = FakeLabel()
        app._slider_time_label = FakeLabel()
        app.vods_items_label = FakeLabel()
        app._in_game_time_label = FakeLabel()
        app._chests_per_minute_label = FakeLabel()
        app._mob_kills_label = FakeLabel()
        app._kps_averages_label = FakeLabel()
        app._level_label = FakeLabel()
        app._new_items_label = FakeLabel()
        app._banishes_label = FakeLabel()
        app._stage_summary_labels = []
        app._rows = {}
        app._stat_cards = RecordingStatCardsView()
        app._items_section = RecordingItemsSectionView()
        app.resolve_snapshot_chests_per_minute = lambda snapshot: getattr(snapshot, "chests_per_minute", None)
        attach_player_stats_view(app).set_stage_summary_rows = lambda rows: None
        app._resolve_vod_compare_base_snapshot = lambda index: None
        app._vod_compare_segment_snapshots = lambda index: ()
        app._refresh_vod_compare_controls = lambda *args, **kwargs: None
        app._refresh_vod_compare_details = lambda *args, **kwargs: None
        app._compare_start_index = None
        app._compare_details_expanded = False
        snapshot = SimpleNamespace(
            stats={},
            items=(),
            weapons=(),
            tomes=(),
            banishes=(),
            damage_sources=(SimpleNamespace(source_key="Katana", source_name="Katana", damage=1234.0),),
            chests_per_minute=1.23,
            game_time_seconds=60.0,
            mob_kills=10,
            kps_at_capture=150,
            minute_avg_kps_at_capture=243,
            five_minute_avg_kps_at_capture=221,
            run_avg_kps_at_capture=138,
            player_level=2,
            time_label="01:00",
        )
        metadata = SimpleNamespace(name="Run")
        app._loaded_vod = SimpleNamespace(metadata=metadata, snapshots=[snapshot])

        app.display_loaded_vod_snapshot(0)

        self.assertEqual(len(app._stat_cards.damage_sources), 1)
        sources, status_text = app._stat_cards.damage_sources[0]
        self.assertIsNone(status_text)
        self.assertEqual(sources[0].source_name, "Katana")
        self.assertEqual(app._mob_kills_label.text(), "Mob Kills: 10 (150/s)")
        self.assertEqual(app._kps_averages_label.text(), "KPS: 60s 243/s | 5m 221/s")

    def test_format_in_game_time_truncates_fractional_seconds(self) -> None:
        self.assertEqual(formatting.format_in_game_time(None), "In-Game Time: --")
        self.assertEqual(formatting.format_in_game_time(21.52338219), "In-Game Time: 00:21")
        self.assertEqual(formatting.format_in_game_time(3661.9), "In-Game Time: 01:01:01")

    def test_format_mob_kills_formats_missing_and_positive_values(self) -> None:
        self.assertEqual(formatting.format_mob_kills(None), "Mob Kills: --")
        self.assertEqual(formatting.format_mob_kills(42), "Mob Kills: 42")
        self.assertEqual(formatting.format_mob_kills(1291146), "Mob Kills: 1,291,146")

    def test_format_kps_averages_formats_missing_and_positive_values(self) -> None:
        self.assertEqual(
            formatting.format_kps_averages(None, None),
            "KPS: 60s -- | 5m --",
        )
        self.assertEqual(
            formatting.format_kps_averages(243, 221),
            "KPS: 60s 243/s | 5m 221/s",
        )

    def test_format_player_level_formats_missing_and_positive_values(self) -> None:
        self.assertEqual(formatting.format_player_level(None), "Level: --")
        self.assertEqual(formatting.format_player_level(4), "Level: 4")

    def test_format_powerups_duration_uses_powerup_multiplier(self) -> None:
        stats = {
            "Powerup Multiplier": SimpleNamespace(value=1.5, display_value="1.5x"),
        }

        self.assertEqual(
            formatting.format_powerups_duration(stats),
            "Powerups: 22s | Clock: 18s",
        )
        self.assertEqual(formatting.format_powerups_duration({}), "Powerups: --")

    def test_nearest_snapshot_index_prefers_in_game_time(self) -> None:
        snapshots = (
            SimpleNamespace(game_time_seconds=10.0, elapsed_seconds=100),
            SimpleNamespace(game_time_seconds=40.0, elapsed_seconds=200),
            SimpleNamespace(game_time_seconds=90.0, elapsed_seconds=300),
        )

        self.assertEqual(compare_runs_tab._nearest_snapshot_index(snapshots, 43.0), 1)

    def test_compare_run_loading_error_clears_previous_side_content(self) -> None:
        app = build_compare_runs_tab()
        app._vod_a = object()
        app._vod_b = None
        app._index_a = 4
        app._index_b = None
        app._run_a_status_label = FakeLabel("Old recording")
        app._run_a_timeline_label = FakeLabel("Old timeline")
        app._run_a_summary_label = FakeLabel("Old summary")
        app._run_a_slider = MagicMock()
        app._run_a_items_view = RecordingItemsSectionView()
        app._set_compare_runs_diff_cards = MagicMock()
        app._refresh_compare_runs_item_details_button = MagicMock()
        app._refresh_compare_runs_selected_labels = MagicMock()

        app._set_compare_run_error("a", "Could not load recording")

        self.assertIsNone(app._vod_a)
        self.assertIsNone(app._index_a)
        self.assertEqual(app._run_a_timeline_label.text(), "Timeline: --")
        self.assertEqual(app._run_a_summary_label.text(), "--")
        self.assertIn("Could not load recording", app._run_a_status_label.text())
        self.assertEqual(app._run_a_items_view.updates, [((), "--")])
        app._run_a_slider.setEnabled.assert_called_once_with(False)

    def test_compare_runs_diff_skips_disabled_optional_sections(self) -> None:
        app = build_compare_runs_tab()
        snapshot_a = SimpleNamespace(stats={}, items=())
        snapshot_b = SimpleNamespace(stats={}, items=())
        app._vod_a = SimpleNamespace(snapshots=(snapshot_a,))
        app._vod_b = SimpleNamespace(snapshots=(snapshot_b,))
        app._index_a = 0
        app._index_b = 0
        app._items_enabled = False
        app._stage_summary_enabled = False
        app._weapons_enabled = False
        app._tomes_enabled = False
        app._chaos_enabled = False
        app._item_details_expanded = False
        app._compare_run_selected_stat_labels = MagicMock(return_value=("Damage",))
        app._set_compare_runs_diff_cards = MagicMock()
        app._refresh_compare_runs_item_details_button = MagicMock()

        # Patched on `projections.formatting`, not stubbed on the tab: step 21d
        # deleted the nine `format_compare_runs_*` passthroughs, so the tab calls
        # the projection directly and that is where the seam is now.
        with patch.multiple(
            formatting,
            format_compare_runs_overview_diff=MagicMock(return_value="overview"),
            format_compare_runs_stats_diff=MagicMock(return_value="stats"),
            format_compare_runs_items_diff=MagicMock(return_value="items"),
            format_compare_runs_stage_summary_diff=MagicMock(return_value="stages"),
            format_compare_runs_weapons_diff=MagicMock(return_value="weapons"),
            format_compare_runs_tomes_diff=MagicMock(return_value="tomes"),
            format_compare_runs_chaos_diff=MagicMock(return_value="chaos"),
        ):
            app._refresh_compare_runs_diff()

            formatting.format_compare_runs_items_diff.assert_not_called()
            formatting.format_compare_runs_stage_summary_diff.assert_not_called()
            formatting.format_compare_runs_weapons_diff.assert_not_called()
            formatting.format_compare_runs_tomes_diff.assert_not_called()
            formatting.format_compare_runs_chaos_diff.assert_not_called()

        app._set_compare_runs_diff_cards.assert_called_once_with(
            "overview",
            stats_text="stats",
            items_text="--",
            stage_summary_text="--",
            weapons_text="--",
            tomes_text="--",
            chaos_text="--",
            show_items=False,
            show_stage_summary=False,
            show_weapons=False,
            show_tomes=False,
            show_chaos=False,
        )

    def test_format_compare_runs_diff_shows_core_deltas(self) -> None:
        snapshot_a = SimpleNamespace(
            game_time_seconds=120.0,
            elapsed_seconds=100,
            mob_kills=1000,
            player_level=10,
            items=("Key x1", "Za Warudo x1"),
            stats={"Damage": SimpleNamespace(value=1.25, display_value="1.25x")},
        )
        snapshot_b = SimpleNamespace(
            game_time_seconds=126.0,
            elapsed_seconds=130,
            mob_kills=1500,
            player_level=12,
            items=("Key x3",),
            stats={"Damage": SimpleNamespace(value=1.5, display_value="1.50x")},
        )
        vod_a = SimpleNamespace(metadata=SimpleNamespace(name="Run A"))
        vod_b = SimpleNamespace(metadata=SimpleNamespace(name="Run B"))

        result = formatting.format_compare_runs_diff(vod_a, snapshot_a, vod_b, snapshot_b)

        self.assertIn("Mode:</span> Run B compared to Run A", result)
        self.assertIn("Time offset:</span> +00:06", result)
        self.assertIn("Kill Difference:</span> +500", result)
        self.assertIn("Level Difference:</span> +2", result)
        self.assertIn("Item Difference:</span> +1", result)
        self.assertIn("Damage:</span> 1.25x -> 1.50x (+0.25)", result)

    def test_format_compare_runs_diff_uses_selected_stat_labels(self) -> None:
        snapshot_a = SimpleNamespace(
            game_time_seconds=120.0,
            elapsed_seconds=100,
            mob_kills=1000,
            player_level=10,
            items=(),
            stats={
                "Damage": SimpleNamespace(value=1.25, display_value="1.25x"),
                "Luck": SimpleNamespace(value=0.5, display_value="50%"),
            },
        )
        snapshot_b = SimpleNamespace(
            game_time_seconds=120.0,
            elapsed_seconds=100,
            mob_kills=1000,
            player_level=10,
            items=(),
            stats={
                "Damage": SimpleNamespace(value=1.5, display_value="1.50x"),
                "Luck": SimpleNamespace(value=0.75, display_value="75%"),
            },
        )
        vod = SimpleNamespace(metadata=SimpleNamespace(name="Run"))

        result = formatting.format_compare_runs_diff(
            vod,
            snapshot_a,
            vod,
            snapshot_b,
            stat_labels=("Damage",),
        )

        self.assertIn("Damage:</span>", result)
        self.assertNotIn("Luck:</span>", result)

    def test_format_compare_runs_diff_formats_percent_stat_delta_from_display(self) -> None:
        snapshot_a = SimpleNamespace(
            game_time_seconds=120.0,
            elapsed_seconds=100,
            mob_kills=1000,
            player_level=10,
            items=(),
            stats={"Difficulty": SimpleNamespace(value=1.0, display_value="100%")},
        )
        snapshot_b = SimpleNamespace(
            game_time_seconds=120.0,
            elapsed_seconds=100,
            mob_kills=1000,
            player_level=10,
            items=(),
            stats={"Difficulty": SimpleNamespace(value=2.0, display_value="200%")},
        )
        vod = SimpleNamespace(metadata=SimpleNamespace(name="Run"))

        result = formatting.format_compare_runs_diff(
            vod,
            snapshot_a,
            vod,
            snapshot_b,
            stat_labels=("Difficulty",),
        )

        self.assertIn("Difficulty:</span> 100% -> 200% (+100%)", result)

    def test_format_compare_runs_diff_can_include_item_difference_section(self) -> None:
        snapshot_a = SimpleNamespace(
            game_time_seconds=120.0,
            elapsed_seconds=100,
            mob_kills=1000,
            player_level=10,
            items=("Key x4", "Giant Fork x1"),
            stats={},
        )
        snapshot_b = SimpleNamespace(
            game_time_seconds=120.0,
            elapsed_seconds=100,
            mob_kills=1000,
            player_level=10,
            items=("Key x1", "Lightning Orb x2", "Beefy Ring x1"),
            stats={},
        )
        vod = SimpleNamespace(metadata=SimpleNamespace(name="Run"))

        result = formatting.format_compare_runs_diff(
            vod,
            snapshot_a,
            vod,
            snapshot_b,
            include_items=True,
            stat_labels=(),
        )

        self.assertIn(">Items</span>", result)
        self.assertIn("B has more:</span>", result)
        self.assertIn("Lightning Orb</span> +2", result)
        self.assertIn("Beefy Ring</span> +1", result)
        self.assertIn("A has more:</span>", result)
        self.assertIn("Giant Fork</span> -1", result)
        self.assertIn("Key</span> -3", result)

    def test_format_compare_runs_diff_can_expand_item_details_by_rarity(self) -> None:
        snapshot_a = SimpleNamespace(
            game_time_seconds=120.0,
            elapsed_seconds=100,
            mob_kills=1000,
            player_level=10,
            items=("Key x4", "Giant Fork x1"),
            stats={},
        )
        snapshot_b = SimpleNamespace(
            game_time_seconds=120.0,
            elapsed_seconds=100,
            mob_kills=1000,
            player_level=10,
            items=("Key x1", "Lightning Orb x2", "Beefy Ring x1"),
            stats={},
        )
        vod = SimpleNamespace(metadata=SimpleNamespace(name="Run"))

        result = formatting.format_compare_runs_diff(
            vod,
            snapshot_a,
            vod,
            snapshot_b,
            include_items=True,
            item_details_expanded=True,
            stat_labels=(),
        )

        self.assertIn("<table", result)
        self.assertIn(">Name</td>", result)
        self.assertIn(">A</td>", result)
        self.assertIn(">B</td>", result)
        self.assertIn(">Diff</td>", result)
        self.assertIn("Lightning Orb</span>", result)
        self.assertIn("+2</span>", result)
        self.assertIn("Key</span>", result)
        self.assertIn("-3</span>", result)
        self.assertGreaterEqual(result.count("&#9679;"), 3)

    def test_format_compare_runs_diff_can_include_weapon_and_tome_sections(self) -> None:
        weapon_stat_a = SimpleNamespace(label="Damage", display_value="10")
        weapon_stat_b = SimpleNamespace(label="Damage", display_value="20")
        weapon_a = SimpleNamespace(
            name="Sword",
            level=2,
            upgrade_stat_ids=(12,),
            upgraded_stats={12: weapon_stat_a},
        )
        weapon_b = SimpleNamespace(
            name="Sword",
            level=4,
            upgrade_stat_ids=(12,),
            upgraded_stats={12: weapon_stat_b},
        )
        tome_a = SimpleNamespace(name="Damage", level=1, stat_label="Damage", display_value="1.10x")
        tome_b = SimpleNamespace(name="Damage", level=3, stat_label="Damage", display_value="1.30x")
        snapshot_a = SimpleNamespace(
            game_time_seconds=120.0,
            elapsed_seconds=100,
            mob_kills=1000,
            player_level=10,
            items=(),
            stats={},
            weapons=(weapon_a,),
            tomes=(tome_a,),
        )
        snapshot_b = SimpleNamespace(
            game_time_seconds=120.0,
            elapsed_seconds=100,
            mob_kills=1000,
            player_level=10,
            items=(),
            stats={},
            weapons=(weapon_b,),
            tomes=(tome_b,),
        )
        vod = SimpleNamespace(metadata=SimpleNamespace(name="Run"))

        result = formatting.format_compare_runs_diff(
            vod,
            snapshot_a,
            vod,
            snapshot_b,
            include_weapons=True,
            include_tomes=True,
            stat_labels=(),
        )

        self.assertIn(">Weapons</span>", result)
        self.assertIn(">Sword</span>", result)
        self.assertIn(">Damage</td>", result)
        self.assertIn(">A</td>", result)
        self.assertIn(">B</td>", result)
        self.assertIn(">Diff</td>", result)
        self.assertIn(">10</td>", result)
        self.assertIn(">20</td>", result)
        self.assertIn(">+10</span>", result)
        self.assertIn(">Tomes</span>", result)
        self.assertIn("Lv. 1 -> 3", result)
        self.assertIn(">+0.20x</span>", result)

    def test_configured_compare_run_stat_labels_reads_valid_saved_config(self) -> None:
        original_config = deepcopy(config.user_config)
        try:
            config.user_config.clear()
            config.user_config["COMPARE_RUN_STAT_LABELS"] = ["Luck", "Not Real", "Damage"]

            result = compare_runs_tab.configured_compare_run_stat_labels()

            self.assertEqual(result, ("Luck", "Damage"))
        finally:
            config.user_config.clear()
            config.user_config.update(original_config)

    def test_configured_compare_run_sections_reads_saved_config(self) -> None:
        original_config = deepcopy(config.user_config)
        try:
            config.user_config.clear()
            config.user_config["COMPARE_RUN_SECTIONS"] = {
                "items": True,
                "stage_summary": True,
                "weapons": False,
                "tomes": True,
                "unknown": True,
            }

            result = compare_runs_tab.configured_compare_run_sections()

            self.assertEqual(
                result,
                {
                    "items": True,
                    "stage_summary": True,
                    "weapons": False,
                    "tomes": True,
                    "chaos": False,
                },
            )
        finally:
            config.user_config.clear()
            config.user_config.update(original_config)

    def test_format_compare_runs_stage_summary_diff_uses_selected_snapshot_progress(self) -> None:
        snapshot_a_1 = SimpleNamespace(
            game_time_seconds=30.0,
            mob_kills=10,
            items=("Key x1",),
            stage_ptr=0,
            map_seed=11,
            stage_time_seconds=30.0,
        )
        snapshot_a_2 = SimpleNamespace(
            game_time_seconds=60.0,
            mob_kills=25,
            items=("Key x2",),
            stage_ptr=0,
            map_seed=11,
            stage_time_seconds=60.0,
        )
        snapshot_b_1 = SimpleNamespace(
            game_time_seconds=35.0,
            mob_kills=12,
            items=("Key x1", "Wrench x1"),
            stage_ptr=0,
            map_seed=22,
            stage_time_seconds=35.0,
        )
        snapshot_b_2 = SimpleNamespace(
            game_time_seconds=75.0,
            mob_kills=40,
            items=("Key x3", "Wrench x1"),
            stage_ptr=0,
            map_seed=22,
            stage_time_seconds=75.0,
        )
        vod_a = SimpleNamespace(snapshots=(snapshot_a_1, snapshot_a_2))
        vod_b = SimpleNamespace(snapshots=(snapshot_b_1, snapshot_b_2))

        result = formatting.format_compare_runs_stage_summary_diff(vod_a, 1, vod_b, 1)

        self.assertIn("Stage 1", result)
        self.assertIn("01:00", result)
        self.assertIn("01:15", result)
        self.assertIn("(+00:15)", result)
        self.assertIn("25", result)
        self.assertIn("40", result)
        self.assertIn("(+15)", result)
        self.assertIn("&rarr;", result)

    def test_save_compare_run_stat_selection_persists_checked_labels(self) -> None:
        app = build_compare_runs_tab()
        app._stat_checkboxes = {
            "Damage": SimpleNamespace(isChecked=lambda: True),
            "Luck": SimpleNamespace(isChecked=lambda: False),
            "Difficulty": SimpleNamespace(isChecked=lambda: True),
        }

        with patch.object(config, "save_config") as save_config:
            app._save_compare_run_stat_selection()

        self.assertEqual(config.user_config["COMPARE_RUN_STAT_LABELS"], ["Damage", "Difficulty"])
        save_config.assert_called_once_with(config.user_config)

    def test_auto_close_compare_runs_chooser_if_ready_closes_after_both_runs_selected(self) -> None:
        refreshed = []
        app = build_compare_runs_tab()
        app._chooser_expanded = True
        app._guided_selection_active = True
        app._vod_a = object()
        app._vod_b = object()
        app.set_compare_runs_chooser_expanded = (
            lambda expanded, guided=False: refreshed.append((expanded, guided))
        )

        app._auto_close_compare_runs_chooser_if_ready()

        self.assertEqual(refreshed, [(False, False)])

    def test_auto_close_compare_runs_chooser_if_ready_keeps_open_when_selection_incomplete(self) -> None:
        refreshed = []
        app = build_compare_runs_tab()
        app._chooser_expanded = True
        app._guided_selection_active = True
        app._vod_a = object()
        app._vod_b = None
        app._refresh_compare_runs_chooser = lambda: refreshed.append(True)

        app._auto_close_compare_runs_chooser_if_ready()

        self.assertTrue(app._chooser_expanded)
        self.assertEqual(refreshed, [])

    def test_auto_close_compare_runs_chooser_if_ready_keeps_manual_chooser_open(self) -> None:
        refreshed = []
        app = build_compare_runs_tab()
        app._chooser_expanded = True
        app._guided_selection_active = False
        app._vod_a = object()
        app._vod_b = object()
        app.set_compare_runs_chooser_expanded = (
            lambda expanded, guided=False: refreshed.append((expanded, guided))
        )

        app._auto_close_compare_runs_chooser_if_ready()

        self.assertEqual(refreshed, [])

    def test_ensure_compare_runs_chooser_for_empty_selection_opens_guided_mode(self) -> None:
        calls = []
        # `is_active` is the tab-bar question, injected rather than reached for:
        # the router that answers it stays `gui_layout`'s until step 26.
        app = build_compare_runs_tab(is_active=lambda: True)
        app._vod_a = None
        app._vod_b = None
        app._chooser_expanded = False
        app.set_compare_runs_chooser_expanded = (
            lambda expanded, guided=False: calls.append((expanded, guided))
        )

        app.ensure_compare_runs_chooser_for_empty_selection()

        self.assertEqual(calls, [(True, True)])

    def test_ensure_compare_runs_chooser_for_empty_selection_skips_when_runs_already_selected(self) -> None:
        calls = []
        app = build_compare_runs_tab(is_active=lambda: True)
        app._vod_a = object()
        app._vod_b = object()
        app._chooser_expanded = False
        app.set_compare_runs_chooser_expanded = (
            lambda expanded, guided=False: calls.append((expanded, guided))
        )

        app.ensure_compare_runs_chooser_for_empty_selection()

        self.assertEqual(calls, [])

    def test_diff_new_items_includes_new_stacks_and_new_names(self) -> None:
        result = formatting.diff_new_items(
            ("Wrench x1", "Dice x1"),
            ("Wrench x3", "Dice x1", "Holy Book x1"),
        )

        self.assertEqual(result, ("Holy Book x1", "Wrench x2"))

    def test_diff_item_gains_sorts_by_rarity_and_gain(self) -> None:
        result = formatting.diff_item_gains(
            ("Wrench x1", "Key x1", "Beefy Ring x1"),
            ("Wrench x3", "Key x7", "Beefy Ring x6", "Za Warudo x4", "Golden Shield x1"),
        )

        self.assertEqual(
            result,
            (
                ("Za Warudo", 4),
                ("Beefy Ring", 5),
                ("Golden Shield", 1),
                ("Key", 6),
                ("Wrench", 2),
            ),
        )

    def test_format_item_gains_by_rarity_uses_one_dot_per_rarity_row(self) -> None:
        result = formatting.format_item_gains_by_rarity(
            (
                ("Za Warudo", 4),
                ("Wizards Hat", 3),
                ("Beefy Ring", 5),
                ("Key", 6),
            )
        )

        self.assertIn("Za Warudo +4</span> |", result)
        self.assertIn("Wizard&#x27;s Hat +3</span>", result)
        self.assertIn("Beefy Ring +5", result)
        self.assertIn("Key +6", result)
        self.assertEqual(result.count("&#9679;"), 3)

    def test_format_snapshot_item_gains_preview_uses_compact_totals(self) -> None:
        base = SimpleNamespace(
            game_time_seconds=120.0,
            mob_kills=100,
            player_level=4,
            items=("Wrench x1",),
        )
        current = SimpleNamespace(
            game_time_seconds=270.0,
            mob_kills=420,
            player_level=9,
            items=("Wrench x3", "Za Warudo x4", "Beefy Ring x5"),
        )

        result = formatting.format_snapshot_item_gains_preview(base, current)

        self.assertIn("Items:", result)
        self.assertIn("+11</span>", result)
        self.assertIn("Time:</span> 02:30", result)
        self.assertIn("Kills:</span> +320", result)
        self.assertIn("Levels:</span> +5", result)
        self.assertNotIn("Za Warudo +4", result)

    def test_segment_changes_track_broken_za_warudo_and_lost_items(self) -> None:
        snapshots = (
            SimpleNamespace(items=("Wrench x1",)),
            SimpleNamespace(items=("Wrench x1", "Za Warudo x1", "Key x3")),
            SimpleNamespace(items=("Wrench x1", "Key x1")),
        )

        result = formatting.summarize_item_segment_changes(snapshots)

        self.assertEqual(result["gained"], (("Za Warudo", 1), ("Key", 3)))
        self.assertEqual(result["broken"], (("Za Warudo", 1),))
        self.assertEqual(result["lost"], (("Key", 2),))

    def test_format_snapshot_item_gains_preview_counts_broken_items_as_gained(self) -> None:
        base = SimpleNamespace(
            game_time_seconds=120.0,
            mob_kills=100,
            player_level=4,
            items=("Wrench x1",),
        )
        middle = SimpleNamespace(
            game_time_seconds=180.0,
            mob_kills=150,
            player_level=4,
            items=("Wrench x1", "Za Warudo x1"),
        )
        current = SimpleNamespace(
            game_time_seconds=240.0,
            mob_kills=250,
            player_level=5,
            items=("Wrench x1",),
        )

        result = formatting.format_snapshot_item_gains_preview(
            base,
            current,
            segment_snapshots=(base, middle, current),
        )

        self.assertIn("+1</span>", result)
        self.assertNotIn("Broken:</span>", result)
        self.assertNotIn("Za Warudo -1", result)

    def test_format_snapshot_item_gains_preview_hides_zero_item_total(self) -> None:
        base = SimpleNamespace(
            game_time_seconds=120.0,
            mob_kills=100,
            player_level=4,
            items=("Wrench x1",),
        )
        current = SimpleNamespace(
            game_time_seconds=150.0,
            mob_kills=110,
            player_level=4,
            items=("Wrench x1",),
        )

        result = formatting.format_snapshot_item_gains_preview(base, current)

        self.assertIn("Items:</span> <span style=\"color:#98A7BA;\">--</span>", result)
        self.assertNotIn("+0", result)

    def test_format_snapshot_item_changes_details_separates_gained_broken_and_lost(self) -> None:
        base = SimpleNamespace(items=("Wrench x1",))
        middle = SimpleNamespace(items=("Wrench x1", "Za Warudo x1", "Key x3"))
        current = SimpleNamespace(items=("Wrench x1", "Key x1"))

        result = formatting.format_snapshot_item_changes_details(
            base,
            current,
            segment_snapshots=(base, middle, current),
        )

        self.assertIn("Gained", result)
        self.assertIn("Za Warudo +1", result)
        self.assertIn("Broken", result)
        self.assertIn("Za Warudo -1 broken", result)
        self.assertIn("Lost", result)
        self.assertIn("Key -2", result)

    def test_format_snapshot_compare_summary_includes_segment_deltas(self) -> None:
        base = SimpleNamespace(
            game_time_seconds=120.0,
            mob_kills=100,
            player_level=4,
            items=("Wrench x1",),
        )
        current = SimpleNamespace(
            game_time_seconds=270.0,
            mob_kills=420,
            player_level=9,
            items=("Wrench x3", "Za Warudo x1"),
        )

        result = formatting.format_snapshot_compare_summary(base, current, base_index=3, current_index=8)

        self.assertEqual(
            result,
            "Snapshot 4 -> 9 | 02:00 -> 04:30 | +320 kills | +5 levels | +3 items",
        )

    def test_format_snapshot_new_items_handles_first_snapshot_and_no_changes(self) -> None:
        snapshot = SimpleNamespace(items=("Wrench x1",))

        self.assertEqual(formatting.format_snapshot_new_items(None, snapshot), "No previous snapshot")
        self.assertEqual(
            formatting.format_snapshot_new_items(snapshot, SimpleNamespace(items=("Wrench x1",))),
            "No new items since previous snapshot",
        )

    def test_merge_banish_appearance_order_preserves_existing_sequence_and_appends_new(self) -> None:
        result = formatting.merge_banish_appearance_order(
            ("Clover", "Golden Tome"),
            ("Golden Tome", "Clover", "Battery"),
        )

        self.assertEqual(result, ("Clover", "Golden Tome", "Battery"))

    def test_format_items_rich_text_colors_name_only(self) -> None:
        result = formatting.format_items_rich_text(("Wrench x2", "Bonker x1", "Crypt Key x1"))

        self.assertIn('color: #22C55E', result)
        self.assertIn('>Wrench</span> x2', result)
        self.assertIn('color: #FACC15', result)
        self.assertIn('>Big Bonk</span> x1', result)
        self.assertIn('Crypt key x1', result)
        self.assertNotIn('color: #22C55E;">Wrench x2</span>', result)

    def test_format_items_rich_text_supports_gloves_aliases(self) -> None:
        result = formatting.format_items_rich_text(("Gloves Blood x1", "Gloves Power x1"))

        self.assertIn('>Slurp Gloves</span> x1', result)
        self.assertIn('color: #E879F9', result)
        self.assertIn('>Power Gloves</span> x1', result)
        self.assertIn('color: #FACC15', result)

    def test_format_items_rich_text_supports_flappy_feathers_alias(self) -> None:
        result = formatting.format_items_rich_text(("Flappy Feathers x1",))

        self.assertIn('>Feathers</span> x1', result)
        self.assertIn('color: #60A5FA', result)

    def test_format_items_rich_text_handles_display_name_variants(self) -> None:
        result = formatting.format_items_rich_text(
            (
                "Borgor x1",
                "Bob Lantern x1",
                "Bob's Lantern x1",
                "Grandma's Secret Tonic x1",
                "Gloves Cursed x1",
                "No Implementation x1",
                "Pot Steel x1",
                "Sucky Hoof x1",
            )
        )

        self.assertIn('>Borgar</span> x1', result)
        self.assertIn('color: #22C55E', result)
        self.assertIn(">Bob&#x27;s Light</span> x1", result)
        self.assertIn(">Grandma&#x27;s Secret Tonic</span> x1", result)
        self.assertIn(">Cursed Grabbies</span> x1", result)
        self.assertIn('color: #E879F9', result)
        self.assertIn(">The One Ring</span> x1", result)
        self.assertIn("color: #F97316", result)
        self.assertIn('>Pot (stainless steel)</span> x1', result)
        self.assertIn(">Sucky Magnet</span> x1", result)
        self.assertIn('color: #FACC15', result)

    def test_normalize_item_name_for_rarity_handles_aliases_and_gloves_rule(self) -> None:
        self.assertEqual(formatting._normalize_item_name_for_rarity("Flappy Feathers"), "Feathers")
        self.assertEqual(formatting._normalize_item_name_for_rarity("Gloves Power"), "Glove Power")
        self.assertEqual(formatting._normalize_item_name_for_rarity("Borgor"), "Borgar")
        self.assertEqual(formatting._normalize_item_name_for_rarity("Bob Lantern"), "Bobs Lantern")
        self.assertEqual(formatting._normalize_item_name_for_rarity("Bob's Lantern"), "Bobs Lantern")
        self.assertEqual(formatting._normalize_item_name_for_rarity("Gloves Cursed"), "Glove Curse")
        self.assertEqual(formatting._normalize_item_name_for_rarity("No Implementation"), "Golden Ring")
        self.assertEqual(formatting._normalize_item_name_for_rarity("The One Ring"), "Golden Ring")
        self.assertEqual(formatting._normalize_item_name_for_rarity("Pot Steel"), "Pot")
        self.assertEqual(formatting._normalize_item_name_for_rarity("Sucky Hoof"), "Sucky Magnet")
        self.assertEqual(formatting._normalize_item_name_for_rarity("Wrench"), "Wrench")

    def test_overlay_settings_persist_auto_start_checkbox(self) -> None:
        component = build_overlay_test_component()
        component.overlay_port_entry = FakeEntry("17845")
        component.overlay_auto_start_cb = FakeCheckbox(True)
        component.overlay_widget_checkboxes = {}
        component.overlay_stats_checkboxes = None
        component.overlay_stage_summary_bg_checkbox = None
        component.overlay_banishes_bg_checkbox = None
        component.overlay_tracked_rules_list = None
        component.update_overlay_state_from_tracker = MagicMock()
        component.refresh_overlay_ui = MagicMock()
        overlay_cfg = deepcopy(config.DEFAULT_OVERLAY)

        with patch.object(config, "OVERLAY", overlay_cfg), \
             patch.object(config, "user_config", {}), \
             patch.object(config, "save_config") as save_config:
            component.save_overlay_settings_from_ui()

            self.assertTrue(config.OVERLAY["auto_start"])
            self.assertTrue(config.user_config["OVERLAY"]["auto_start"])
            save_config.assert_called_once_with(config.user_config)

    def test_overlay_autostart_uses_auto_start_setting(self) -> None:
        component = build_overlay_test_component()
        component.start_overlay_server = MagicMock()
        component.update_overlay_state_from_tracker = MagicMock()

        with patch.object(config, "OVERLAY", {"enabled": True, "auto_start": False}):
            component.apply_overlay_autostart()
        component.start_overlay_server.assert_not_called()

        with patch.object(config, "OVERLAY", {"enabled": False, "auto_start": True}):
            component.apply_overlay_autostart()
        component.start_overlay_server.assert_called_once_with()
        self.assertEqual(component.update_overlay_state_from_tracker.call_count, 2)

    def test_normalize_item_name_for_display_replaces_no_implementation(self) -> None:
        self.assertEqual(formatting._normalize_item_name_for_display("No Implementation"), "The One Ring")
        self.assertEqual(formatting._normalize_item_name_for_display("Golden Ring"), "The One Ring")
        self.assertEqual(formatting._normalize_item_name_for_display("Sucky Hoof"), "Sucky Magnet")

    def test_split_item_stack_suffix_handles_plain_names(self) -> None:
        self.assertEqual(formatting._split_item_stack_suffix("Wrench x2"), ("Wrench", " x2"))
        self.assertEqual(formatting._split_item_stack_suffix("Ghost"), ("Ghost", ""))

    def test_on_closing_stops_supported_runtime_resources(self) -> None:
        destroyed: list[bool] = []
        closed: list[str] = []
        app = object.__new__(MegabonkApp)
        # The scanner and run control are real objects on the app now (step
        # 25c), so the two the shutdown sequence drives are built rather than
        # stubbed: `shutdown()` is what sets both events, and `stop_hotkeys()`
        # is what clears the manager. Stubbing them would leave this test
        # asserting the order of five calls it made itself.
        scanner, run_control = build_pair()
        app.__dict__["_scanner"] = scanner
        app.__dict__["_run_control"] = run_control
        scanner.close_client = lambda: closed.append("client")
        app.destroy = lambda: destroyed.append(True)
        app._is_shutting_down = False
        # `app._cancel_right_tab_transition = lambda: closed.append("transition")`
        # stood here and `"transition"` was asserted first in the order below.
        # Step 26 deleted the method: its body was `return None` and had never
        # been anything else, so this recorder was pinning the position of a
        # no-op. The other six steps keep their order, which is what the test
        # is for.
        player_stats_memory(app).close_player_stats_client = lambda: closed.append("player_stats")
        player_stats_memory(app).close_player_stats_game_data_client = lambda: closed.append("player_stats_game_data")
        app.close_overlay_server = lambda: closed.append("overlay")
        app.stop_in_game_overlay = lambda: closed.append("in_game_overlay")
        app.stop_twitch_bot = lambda: closed.append("twitch")
        app.player_stats_vod_recorder = None

        with patch_everywhere("keyboard", None):
            MegabonkApp.on_closing(app)

        self.assertTrue(scanner.stop_event.is_set())
        self.assertTrue(scanner.scan_event.is_set())
        self.assertEqual(destroyed, [True])
        self.assertEqual(
            closed,
            ["client", "player_stats", "player_stats_game_data", "overlay", "in_game_overlay", "twitch"],
        )

    def test_app_coordinator_shutdown_closes_the_memory_clients(self) -> None:
        # step 12c: the coordinator owns the three clients, so it closes them.
        coordinator = AppCoordinator.__new__(AppCoordinator)
        closed: list[str] = []
        coordinator.client = SimpleNamespace(close=lambda: closed.append("client"))
        coordinator.player_stats_client = SimpleNamespace(
            close=lambda: closed.append("player_stats")
        )
        coordinator.player_stats_game_data_client = SimpleNamespace(
            close=lambda: closed.append("player_stats_game_data")
        )

        coordinator.shutdown()

        self.assertEqual(closed, ["client", "player_stats", "player_stats_game_data"])
        self.assertIsNone(coordinator.client)
        self.assertIsNone(coordinator.player_stats_client)
        self.assertIsNone(coordinator.player_stats_game_data_client)
        coordinator.shutdown()  # idempotent

    def test_on_closing_delegates_client_teardown_to_the_coordinator(self) -> None:
        # step 12c: when a coordinator is present, on_closing tears the clients
        # down through it rather than the three mixin close methods.
        destroyed: list[bool] = []
        closed: list[str] = []
        app = object.__new__(MegabonkApp)
        scanner, run_control = build_pair()
        app.__dict__["_scanner"] = scanner
        app.__dict__["_run_control"] = run_control
        app.coordinator = SimpleNamespace(shutdown=lambda: closed.append("coordinator"))
        app.destroy = lambda: destroyed.append(True)
        app._is_shutting_down = False
        scanner.close_client = lambda: closed.append("component_client")
        player_stats_memory(app).close_player_stats_client = lambda: closed.append("mixin_player_stats")
        player_stats_memory(app).close_player_stats_game_data_client = lambda: closed.append("mixin_game_data")
        app.close_overlay_server = lambda: None
        app.stop_in_game_overlay = lambda: None
        app.stop_twitch_bot = lambda: None
        app.player_stats_vod_recorder = None

        with patch_everywhere("keyboard", None):
            MegabonkApp.on_closing(app)

        self.assertEqual(closed, ["coordinator"])
        self.assertEqual(destroyed, [True])

    def test_refresh_live_player_stats_now_parses_single_key(self) -> None:
        app = object.__new__(MegabonkApp)
        app.__dict__["coordinator"] = make_client_coordinator()
        app.player_stats_vod_recorder = FakeRecordingRecorder(is_recording=False)
        app.player_stats_vod_snapshots = []
        app.player_stats_selected_snapshot_index = None
        app.player_stats_status_label = FakeLabel()
        app.player_stats_rows = {}
        app.player_stats_items_label = FakeLabel()
        app.player_stats_banishes_label = FakeLabel()
        live_snapshot_store(app).live_banishes = ()
        app.player_stats_in_game_time_label = FakeLabel()
        app.player_stats_chests_per_minute_label = FakeLabel()
        app.player_stats_mob_kills_label = FakeLabel()
        app.player_stats_level_label = FakeLabel()
        app.player_stats_new_items_label = FakeLabel()
        app.player_stats_stage_summary_labels = []
        player_stats_memory(app)._get_player_stats_client = lambda: SimpleNamespace(
            get_run_timer=lambda: 21.5,
            get_killed_mobs=lambda: 37,
            get_player_level=lambda owner_stats=None: 2,
        )
        player_stats_memory(app).close_player_stats_client = lambda: None
        player_stats_memory(app).close_player_stats_game_data_client = lambda: None
        attach_player_stats_view(app).refresh_player_stats_timeline_ui = lambda *args, **kwargs: None
        app._refresh_vods_list_if_visible = lambda: None
        app._is_live_stats_tab_active = lambda: False
        app.overlay_should_refresh_live_stats = lambda: False
        app._is_twitch_bot_active = lambda: False
        player_stats_memory(app).read_player_stats_only = lambda _context=None: ({}, 0x1234)
        player_stats_memory(app).read_passive_items_only = lambda owner_stats=None, _context=None: ("Key",)
        player_stats_memory(app).read_player_stats_recording_state = lambda _context=None: SimpleNamespace(
            map_seed=None,
            current_stage_ptr=0,
        )
        player_stats_memory(app)._read_player_stats_runtime_game_state_safe = lambda _context=None: None
        vod_capture(app).maybe_auto_start = lambda **kwargs: None
        app.mark_overlay_read_failed = lambda *args, **kwargs: None
        app.update_overlay_state_from_tracker = lambda: None
        app.refresh_session_tracked_item_stats_ui = lambda: None

        chests_and_keys_args = []
        app.live_run_tracker = SimpleNamespace(
            update=lambda *args, **kwargs: None,
            get_chests_and_keys=lambda: (12, 50, 3, 1, {1: 12}, {1: 50}),
            update_chests_and_keys=lambda chests, total, keys: chests_and_keys_args.append((chests, total, keys)),
            mark_read_failed=lambda *args, **kwargs: None,
            stage_summary_rows=lambda: [],
            current_ui_kps=lambda: None,
        )

        def fail_map_stats():
            raise RuntimeError("temporary map stats failure")

        app.player_stats_game_data_client = SimpleNamespace(
            get_map_stats=fail_map_stats
        )
        app.overlay_state_store = None

        result = MegabonkApp.refresh_live_player_stats_now(app)
        self.assertTrue(result)
        self.assertEqual(chests_and_keys_args, [(12, 50, 1)])

    def test_session_tracked_items_stats_tab_includes_seed_percent(self) -> None:
        component = build_overlay_test_component(template_stats={
            "template_a": {"history": [1, 2]},
            "template_b": {"history": [3, 4]},
        })
        tracker = SimpleNamespace(
            tracked_item_rows_for_rules=lambda _rules: [
                {
                    "id": "kevin_plug",
                    "label": "Kevin + Electric Plug",
                    "count": 2,
                    "mode": "map_1_only",
                }
            ]
        )
        component.live_run_tracker = tracker
        component.session_stats._tracker = tracker

        text = gui_overlay.format_tracked_item_rows_for_stats_tab(
            component.session_stats.session_tracked_item_stat_rows()
        )

        self.assertEqual(text, "Kevin + Electric Plug T1: 2 (50.00%)")

    def test_apply_in_game_overlay_settings_stops_without_restarting_overlay(self) -> None:
        overlay = build_in_game_overlay_test_component()
        overlay.in_game_overlay_window = FakeInGameOverlayWindow(visible=True)
        status_updates: list[str] = []
        overlay._update_igo_status_ui = lambda: status_updates.append("status")
        overlay._overlay_fast_tick = lambda: status_updates.append("fast")
        overlay._overlay_slow_tick = lambda: status_updates.append("slow")

        overlay_cfg = {"enabled": False, "widgets": {}}
        with patch.object(config, "IN_GAME_OVERLAY", overlay_cfg):
            overlay.apply_in_game_overlay_settings()

        self.assertEqual(overlay.in_game_overlay_window.hide_calls, 1)
        self.assertEqual(overlay.overlay_fast_timer.stop_calls, 1)
        self.assertEqual(overlay.overlay_slow_timer.stop_calls, 1)
        self.assertEqual(status_updates, ["status"])

    def test_apply_in_game_overlay_settings_restarts_runtime_when_edit_mode_left_window_visible(self) -> None:
        overlay = build_in_game_overlay_test_component()
        overlay.in_game_overlay_window = FakeInGameOverlayWindow(visible=True, edit_mode=True)
        overlay.in_game_overlay_window.widgets = {}
        status_updates: list[str] = []
        overlay._update_igo_status_ui = lambda: status_updates.append("status")
        overlay._overlay_fast_tick = lambda: status_updates.append("fast")
        overlay._overlay_slow_tick = lambda: status_updates.append("slow")

        overlay_cfg = {"enabled": True, "widgets": {}}
        with patch.object(config, "IN_GAME_OVERLAY", overlay_cfg):
            overlay.apply_in_game_overlay_settings()

        self.assertEqual(overlay.overlay_fast_timer.start_calls, 1)
        self.assertEqual(overlay.overlay_slow_timer.start_calls, 1)
        self.assertEqual(status_updates, ["fast", "slow", "status"])

    def test_overlay_fast_tick_hides_disabled_overlay_even_if_game_is_active(self) -> None:
        tracker = SimpleNamespace(
            runtime_snapshot=lambda: SimpleNamespace(
                latest_snapshot=None,
                kps={},
                powerups=SimpleNamespace(),
                powerup_map_context=None,
                fast_stage_timer=None,
                graveyard_main_map_events_active=False,
            )
        )
        overlay = build_in_game_overlay_test_component(
            tracker=tracker,
            is_game_window_active=lambda _process_name: True,
        )
        overlay.in_game_overlay_window = FakeInGameOverlayWindow(visible=True)

        overlay_cfg = {
            "enabled": False,
            "widgets": {
                "kps": {"enabled": False},
                "powerups": {"enabled": False},
            },
        }
        with patch.object(config, "IN_GAME_OVERLAY", overlay_cfg):
            overlay._overlay_fast_tick()

        self.assertEqual(overlay.in_game_overlay_window.hide_calls, 1)
        self.assertFalse(overlay.in_game_overlay_window.isVisible())

    def test_overlay_fast_tick_syncs_geometry_before_showing_game_overlay(self) -> None:
        tracker = SimpleNamespace(
            runtime_snapshot=lambda: SimpleNamespace(
                latest_snapshot=None,
                kps={},
                powerups=SimpleNamespace(),
                powerup_map_context=None,
                fast_stage_timer=None,
                graveyard_main_map_events_active=False,
            )
        )
        overlay = build_in_game_overlay_test_component(
            tracker=tracker,
            is_game_window_active=lambda _process_name: True,
        )
        overlay.in_game_overlay_window = FakeInGameOverlayWindow(visible=False)

        overlay_cfg = {
            "enabled": True,
            "widgets": {
                "kps": {"enabled": False},
                "powerups": {"enabled": False},
            },
        }
        with patch.object(config, "IN_GAME_OVERLAY", overlay_cfg):
            overlay._overlay_fast_tick()

        self.assertEqual(overlay.in_game_overlay_window.sync_calls, 1)
        self.assertEqual(overlay.in_game_overlay_window.show_calls, 1)

    def test_overlay_fast_tick_refreshes_slow_widgets_when_overlay_becomes_visible(self) -> None:
        # Asserted on `luck_rarity`, not on `scanner`. The scanner plaque moved
        # to the fast tick -- it reads app state, not the snapshot -- so it is
        # painted on every tick and would satisfy this test whether the
        # become-visible refresh happened or not. `luck_rarity` is the only
        # widget left on the slow path, which makes it the only one that can
        # prove this branch runs.
        luck_widget = SimpleNamespace(set_text=MagicMock(), set_probabilities=MagicMock())
        tracker = SimpleNamespace(
            runtime_snapshot=lambda: SimpleNamespace(
                latest_snapshot=None,
                kps={},
                powerups=SimpleNamespace(),
                powerup_map_context=None,
                fast_stage_timer=None,
                graveyard_main_map_events_active=False,
            )
        )
        overlay = build_in_game_overlay_test_component(
            tracker=tracker,
            is_scanning=lambda: True,
            is_game_window_active=lambda _process_name: True,
        )
        overlay.in_game_overlay_window = FakeInGameOverlayWindow(visible=False)
        overlay.in_game_overlay_window.widgets = {
            "scanner": SimpleNamespace(set_text=MagicMock()),
            "recording": SimpleNamespace(set_text=MagicMock()),
            "luck_rarity": luck_widget,
            "kps": SimpleNamespace(set_text=MagicMock()),
            "powerups": SimpleNamespace(set_text=MagicMock(), setVisible=MagicMock()),
        }
        overlay_cfg = {
            "enabled": True,
            "widgets": {
                "scanner": {"enabled": True},
                "recording": {"enabled": False},
                "luck_rarity": {"enabled": True},
                "kps": {"enabled": False},
                "powerups": {"enabled": False},
            },
        }
        with patch.object(config, "IN_GAME_OVERLAY", overlay_cfg):
            became_visible = overlay._overlay_fast_tick()

        self.assertTrue(became_visible)
        luck_widget.set_probabilities.assert_called_once()

    def test_overlay_fast_tick_paints_the_status_plaques_every_tick(self) -> None:
        """They read app state, not game memory: the scan flag flips the moment
        the user starts a scan, and `REC` flips on the record button or on
        `sync_run_state`, which runs every second. On the 10 s tick a streamer
        watched the plaque appear up to ten seconds after starting."""
        scanner_widget = SimpleNamespace(set_text=MagicMock())
        recording_widget = SimpleNamespace(set_text=MagicMock())
        tracker = SimpleNamespace(
            runtime_snapshot=lambda: SimpleNamespace(
                latest_snapshot=None,
                kps={},
                powerups=SimpleNamespace(),
                powerup_map_context=None,
                fast_stage_timer=None,
                graveyard_main_map_events_active=False,
            )
        )
        overlay = build_in_game_overlay_test_component(
            tracker=tracker,
            is_scanning=lambda: True,
            is_recording=lambda: True,
            is_game_window_active=lambda _process_name: True,
        )
        overlay.in_game_overlay_window = FakeInGameOverlayWindow(visible=True)
        overlay.in_game_overlay_window.widgets = {
            "scanner": scanner_widget,
            "recording": recording_widget,
        }
        overlay_cfg = {
            "enabled": True,
            "widgets": {
                "scanner": {"enabled": True},
                "recording": {"enabled": True},
                "luck_rarity": {"enabled": False},
                "kps": {"enabled": False},
                "stats": {"enabled": False},
                "powerups": {"enabled": False},
            },
        }
        with patch.object(config, "IN_GAME_OVERLAY", overlay_cfg):
            overlay._overlay_fast_tick()
            overlay._overlay_fast_tick()

        self.assertEqual(scanner_widget.set_text.call_count, 2)
        self.assertEqual(recording_widget.set_text.call_count, 2)

    def test_overlay_status_plaques_survive_a_missing_runtime_snapshot(self) -> None:
        """No game attached is exactly when a scan gets started or stopped, and
        the `runtime_snapshot is None` early return is what used to keep the
        plaques frozen through it."""
        scanner_widget = SimpleNamespace(set_text=MagicMock())
        overlay = build_in_game_overlay_test_component(
            tracker=SimpleNamespace(runtime_snapshot=lambda: None),
            is_scanning=lambda: True,
            is_game_window_active=lambda _process_name: True,
        )
        overlay.in_game_overlay_window = FakeInGameOverlayWindow(visible=True)
        overlay.in_game_overlay_window.widgets = {"scanner": scanner_widget}
        overlay_cfg = {
            "enabled": True,
            "widgets": {
                "scanner": {"enabled": True},
                "recording": {"enabled": False},
                "luck_rarity": {"enabled": False},
                "kps": {"enabled": False},
                "stats": {"enabled": False},
                "powerups": {"enabled": False},
            },
        }
        with patch.object(config, "IN_GAME_OVERLAY", overlay_cfg):
            overlay._overlay_fast_tick()

        scanner_widget.set_text.assert_called_once()

    def test_overlay_stats_caps_follow_the_fast_stage_context(self) -> None:
        """The stats themselves come from the 10 s snapshot and cannot be
        fresher. The stage index and stage timer are not decoration though --
        they pick the Difficulty and XP Gain caps -- and they were read off
        `latest_snapshot` while the Event Timer beside them already used the
        fast context."""
        tracker = SimpleNamespace(
            runtime_snapshot=lambda: SimpleNamespace(
                latest_snapshot=SimpleNamespace(
                    stage_index=0,
                    stage_duration_seconds=480.0,
                    stage_timer_seconds=12.0,
                    stats={},
                ),
                kps={},
                powerups=SimpleNamespace(),
                powerup_map_context=SimpleNamespace(is_graveyard=False),
                fast_stage_timer=SimpleNamespace(
                    stage_index=2,
                    stage_duration_seconds=480.0,
                    stage_timer_seconds=85.0,
                ),
                graveyard_main_map_events_active=False,
            )
        )
        overlay = build_in_game_overlay_test_component(
            tracker=tracker,
            is_game_window_active=lambda _process_name: True,
        )
        overlay.in_game_overlay_window = FakeInGameOverlayWindow(visible=True)
        overlay.in_game_overlay_window.widgets = {
            "stats": SimpleNamespace(set_text=MagicMock())
        }
        overlay._refresh_in_game_overlay_slow_widgets = lambda *_args: None
        overlay_cfg = {
            "enabled": True,
            "widgets": {
                "scanner": {"enabled": False},
                "recording": {"enabled": False},
                "kps": {"enabled": False},
                "stats": {"enabled": True, "selected_stats": ["Difficulty"]},
                "event_timer": {"enabled": False},
                "powerups": {"enabled": False},
            },
        }
        builder = MagicMock(return_value="<div></div>")
        with patch.object(config, "IN_GAME_OVERLAY", overlay_cfg), patch.object(
            gui_in_game_overlay, "build_stats_overlay_html", builder
        ):
            overlay._overlay_fast_tick()

        builder.assert_called_once()
        _snapshot, _selected, stage_index, stage_timer, _duration, _graveyard = (
            builder.call_args.args
        )
        self.assertEqual(stage_index, 2)
        self.assertEqual(stage_timer, 85.0)

    def test_in_game_overlay_target_geometry_uses_game_window_rect(self) -> None:
        overlay = build_in_game_overlay_test_component(
            find_game_window=lambda _process_name: 321,
        )
        overlay.in_game_overlay_window = FakeInGameOverlayWindow()

        fake_win32gui = SimpleNamespace(GetWindowRect=lambda _window: (100, 200, 740, 680))
        with patch.object(gui_in_game_overlay, "win32gui", fake_win32gui):
            rect = overlay._in_game_overlay_target_geometry()

        self.assertIsInstance(rect, QRect)
        self.assertEqual(rect, QRect(100, 200, 640, 480))

    def test_in_game_overlay_target_geometry_prefers_game_client_area(self) -> None:
        overlay = build_in_game_overlay_test_component(
            find_game_window=lambda _process_name: 321,
        )
        overlay.in_game_overlay_window = FakeInGameOverlayWindow()

        fake_win32gui = SimpleNamespace(
            GetWindowRect=lambda _window: (90, 170, 750, 690),
            GetClientRect=lambda _window: (0, 0, 640, 480),
            ClientToScreen=lambda _window, point: (100 + point[0], 200 + point[1]),
        )
        with patch.object(gui_in_game_overlay, "win32gui", fake_win32gui):
            rect = overlay._in_game_overlay_target_geometry()

        self.assertEqual(rect, QRect(100, 200, 640, 480))

    def test_in_game_overlay_target_geometry_returns_none_without_game_window_outside_edit_mode(self) -> None:
        overlay = build_in_game_overlay_test_component(
            find_game_window=lambda _process_name: None,
        )
        overlay.in_game_overlay_window = FakeInGameOverlayWindow(edit_mode=False)

        with patch.object(gui_in_game_overlay, "win32gui", SimpleNamespace()):
            rect = overlay._in_game_overlay_target_geometry()

        self.assertIsNone(rect)

    def test_in_game_overlay_powerups_html_uses_tracker_stage_times(self) -> None:
        snapshot = SimpleNamespace(
            active=(
                SimpleNamespace(
                    name="Shield",
                    remaining_seconds=15.0,
                    pickup_offset_seconds=-5.0,
                    expiration_offset_seconds=15.0,
                    pickup_ui="01:45",
                    expires_ui="01:25",
                ),
            ),
            powerup_multiplier_display="1x",
        )

        html = gui_in_game_overlay.build_powerups_overlay_html(
            snapshot,
            current_run_time_seconds=80.0,
        )

        self.assertIn("01:45 -&gt; 01:25", html.replace("→", "-&gt;"))
        self.assertIn("Shield:", html)


    def test_in_game_overlay_luck_rarity_html_formats_game_rarity_order(self) -> None:
        snapshot = SimpleNamespace(
            stats={
                "Luck": SimpleNamespace(value=0.5, display_value="50%"),
            },
        )

        html = gui_in_game_overlay.build_luck_rarity_overlay_html(snapshot)

        self.assertIn("#FACC15", html)
        self.assertIn("#E879F9", html)
        self.assertIn("#60A5FA", html)
        self.assertIn("#22C55E", html)
        self.assertIn("3.08%", html)
        self.assertIn("9.62%", html)
        self.assertIn("18.79%", html)
        self.assertIn("68.52%", html)

    def test_overlay_slow_tick_updates_luck_rarity_widget_from_latest_snapshot(self) -> None:
        widget = SimpleNamespace(set_text=MagicMock())
        tracker = SimpleNamespace(
            runtime_snapshot=lambda: SimpleNamespace(
                latest_snapshot=SimpleNamespace(
                    stats={"Luck": SimpleNamespace(value=1.0, display_value="100%")}
                ),
                kps={},
                powerups=SimpleNamespace(),
                powerup_map_context=None,
                fast_stage_timer=None,
                graveyard_main_map_events_active=False,
            )
        )
        overlay = build_in_game_overlay_test_component(tracker=tracker)
        overlay.in_game_overlay_window = FakeInGameOverlayWindow(visible=True)
        overlay.in_game_overlay_window.widgets = {
            "scanner": SimpleNamespace(set_text=MagicMock()),
            "recording": SimpleNamespace(set_text=MagicMock()),
            "luck_rarity": widget,
        }

        overlay_cfg = {
            "widgets": {
                "scanner": {"enabled": False},
                "recording": {"enabled": False},
                "luck_rarity": {"enabled": True},
            },
        }
        with patch.object(config, "IN_GAME_OVERLAY", overlay_cfg):
            overlay._overlay_slow_tick()

        widget.set_text.assert_called_once()
        rendered_html = widget.set_text.call_args.args[0]
        self.assertIn("4.74%", rendered_html)
        self.assertIn("12.43%", rendered_html)
        self.assertIn("20.39%", rendered_html)
        self.assertIn("62.43%", rendered_html)

    def test_overlay_fast_tick_uses_fast_stage_timer_context_for_event_timer(self) -> None:
        widget = SimpleNamespace(set_text=MagicMock())
        tracker = SimpleNamespace(
            runtime_snapshot=lambda: SimpleNamespace(
                latest_snapshot=SimpleNamespace(
                stage_index=0,
                stage_duration_seconds=480.0,
                stage_timer_seconds=85.0,
            ),
            kps={},
            powerups=SimpleNamespace(),
            powerup_map_context=SimpleNamespace(is_graveyard=False),
            fast_stage_timer=SimpleNamespace(
                stage_index=2,
                stage_duration_seconds=480.0,
                stage_timer_seconds=85.0,
            ),
            graveyard_main_map_events_active=False,
            )
        )
        overlay = build_in_game_overlay_test_component(
            tracker=tracker,
            is_game_window_active=lambda _process_name: True,
        )
        overlay.in_game_overlay_window = FakeInGameOverlayWindow(visible=True)
        overlay.in_game_overlay_window.widgets = {"event_timer": widget}
        overlay._refresh_in_game_overlay_slow_widgets = lambda *_args: None

        overlay_cfg = {
            "enabled": True,
            "widgets": {
                "kps": {"enabled": False},
                "stats": {"enabled": False},
                "event_timer": {"enabled": True, "warning_seconds": 15},
                "powerups": {"enabled": False},
            },
        }
        with patch.object(config, "IN_GAME_OVERLAY", overlay_cfg):
            overlay._overlay_fast_tick()

        widget.set_text.assert_called_once()
        rendered_html = widget.set_text.call_args.args[0]
        self.assertIn("Boss at 6:30", rendered_html)

    def test_overlay_fast_tick_preserves_graveyard_stage_duration_for_event_timer(self) -> None:
        widget = SimpleNamespace(set_text=MagicMock())
        tracker = SimpleNamespace(
            runtime_snapshot=lambda: SimpleNamespace(
                latest_snapshot=SimpleNamespace(
                    stage_index=2,
                    stage_duration_seconds=960.0,
                    stage_timer_seconds=175.0,
                ),
                kps={},
                powerups=SimpleNamespace(),
                powerup_map_context=SimpleNamespace(is_graveyard=True),
                fast_stage_timer=SimpleNamespace(
                    stage_index=2,
                    stage_duration_seconds=480.0,
                    stage_timer_seconds=175.0,
                ),
                graveyard_main_map_events_active=True,
            )
        )
        overlay = build_in_game_overlay_test_component(
            tracker=tracker,
            is_game_window_active=lambda _process_name: True,
        )
        overlay.in_game_overlay_window = FakeInGameOverlayWindow(visible=True)
        overlay.in_game_overlay_window.widgets = {"event_timer": widget}
        overlay._refresh_in_game_overlay_slow_widgets = lambda *_args: None

        overlay_cfg = {
            "enabled": True,
            "widgets": {
                "kps": {"enabled": False},
                "stats": {"enabled": False},
                "event_timer": {"enabled": True, "warning_seconds": 15},
                "powerups": {"enabled": False},
            },
        }
        with patch.object(config, "IN_GAME_OVERLAY", overlay_cfg):
            overlay._overlay_fast_tick()

        rendered_html = widget.set_text.call_args.args[0]
        self.assertIn("Boss at 13:00", rendered_html)

    def test_overlay_fast_tick_shows_event_timer_preview_in_edit_mode(self) -> None:
        widget = SimpleNamespace(set_text=MagicMock())
        tracker = SimpleNamespace(
            runtime_snapshot=lambda: SimpleNamespace(
                latest_snapshot=None,
                kps={},
                powerups=SimpleNamespace(),
                powerup_map_context=None,
                fast_stage_timer=None,
                graveyard_main_map_events_active=False,
            )
        )
        overlay = build_in_game_overlay_test_component(tracker=tracker)
        overlay.in_game_overlay_window = FakeInGameOverlayWindow(visible=True, edit_mode=True)
        overlay.in_game_overlay_window.widgets = {"event_timer": widget}
        overlay._refresh_in_game_overlay_slow_widgets = lambda *_args: None

        overlay_cfg = {
            "enabled": True,
            "widgets": {
                "kps": {"enabled": False},
                "stats": {"enabled": False},
                "event_timer": {"enabled": True, "warning_seconds": 15},
                "powerups": {"enabled": False},
            },
        }
        with patch.object(config, "IN_GAME_OVERLAY", overlay_cfg):
            overlay._overlay_fast_tick()

        widget.set_text.assert_called_once()
        rendered_html = widget.set_text.call_args.args[0]
        self.assertIn("Event Timer (preview)", rendered_html)

    def test_no_mixin_method_is_nested_inside_a_function(self) -> None:
        """A method that lands inside a function instead of a class is invisible.

        Step 15 hit this: `format_live_powerups_card` was appended to `cards.py`
        at the wrong indentation and became a nested function inside the
        module-level `_set_items_text`. The file parsed, AST identity held, and
        all 568 tests passed -- but `MegabonkApp` no longer had the method. A
        `def` taking `self` as its first parameter while nested inside another
        function is that mistake's fingerprint.
        """
        import ast
        import pathlib

        src_root = pathlib.Path(__file__).resolve().parent.parent
        offenders = []
        for path in src_root.rglob("*.py"):
            if "__pycache__" in path.parts or "tests" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for inner in node.body:
                    if not isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    args = inner.args.args
                    if not args or args[0].arg != "self":
                        continue
                    # A decorator's inner wrapper legitimately takes self and
                    # forwards it -- `@wraps(...)` is what marks one.
                    if any(
                        (isinstance(d, ast.Call) and getattr(d.func, "id", "") == "wraps")
                        or getattr(d, "id", "") == "wraps"
                        for d in inner.decorator_list
                    ):
                        continue
                    offenders.append(f"{path.name}:{inner.lineno} {inner.name}")

        self.assertEqual(offenders, [])

    def test_rehomed_player_stats_methods_resolve_on_the_app(self) -> None:
        """Step 15 dissolved `PlayerStatsMixin`; these moved to three new homes.

        Step 19 moved two of the three off the app entirely:
        `format_live_powerups` and `format_live_powerups_card` are
        `LiveStatsTab`'s, and the app reaches the tab through the port rather
        than through its own MRO. Asserting they are *absent* is the same
        guarantee in the other direction -- if either came back as an app
        attribute, the mixin would be back with it.
        """
        # Step 20 retired `LiveSnapshotStoreMixin`, so the guarantee inverts the
        # same way the Live Stats one did at step 19: assert the accessor is
        # *absent* from the app and resolves as a module-level function. If it
        # came back as an app attribute, the mixin would be back with it.
        self.assertFalse(
            hasattr(MegabonkApp, "_ensure_live_snapshot_store"),
            "_ensure_live_snapshot_store is on MegabonkApp again; "
            "app.snapshot_store.live_snapshot_store replaced it",
        )
        self.assertEqual(live_snapshot_store.__module__, "app.snapshot_store")
        for name in ("format_live_powerups", "format_live_powerups_card"):
            self.assertFalse(
                hasattr(MegabonkApp, name),
                f"{name} is on MegabonkApp again; it belongs to LiveStatsTab",
            )
            self.assertEqual(
                getattr(LiveStatsTab, name).__module__,
                "ui.tabs.player_stats.live_stats",
                name,
            )

        # The eight snapshot-store compat properties are gone, not relocated.
        # They had zero production readers -- only the suite poked them -- so
        # they were a compatibility surface for test doubles rather than a
        # layer, and the tests that used them now hold the store itself.
        for name in (
            "player_stats_last_known_items",
            "player_stats_last_known_weapons",
            "player_stats_last_known_tomes",
            "player_stats_last_known_damage_sources",
            "player_stats_last_known_banishes",
            "player_stats_live_banishes",
            "player_stats_last_seed",
            "player_stats_last_run_timer",
        ):
            self.assertFalse(
                hasattr(MegabonkApp, name),
                f"{name} is back on MegabonkApp; it belongs to LiveSnapshotStore",
            )

    def test_player_stats_view_defaults_to_the_app_itself(self) -> None:
        """The default view must be the app object, or step 14c's inversion would
        have changed dispatch rather than just naming it. App doubles are built with
        object.__new__ and never run __init__, so this has to work with no injection.
        """
        app = object.__new__(MegabonkApp)

        self.assertIs(player_stats_view(app), app)

    def test_recording_status_text_is_written_through_the_injected_view(self) -> None:
        """The port is a real seam, not decoration: an injected view receives the
        render calls, and the app layer never touches the widget. Before step 14c,
        `_sync_player_stats_recording_run_state` called `_set_text` on
        `player_stats_status_label` directly from `app/`.
        """
        app = self.build_recording_app()
        app.player_stats_vod_recorder.is_recording = True

        class RecordingView:
            def __init__(self) -> None:
                self.status_texts: list[str] = []
                self.timeline_refreshes = 0

            def set_recording_status_text(self, text: str) -> None:
                self.status_texts.append(text)

            def refresh_player_stats_timeline_ui(self) -> None:
                self.timeline_refreshes += 1

        view = RecordingView()
        app._player_stats_view = view
        self.assertIs(player_stats_view(app), view)

        # No class-attribute patch any more: before step 19 `MegabonkApp`
        # itself satisfied the port, so this had to install a method to prove
        # the *injected* view won. Now the app has no such method at all, which
        # is a stronger statement of the same thing.
        player_stats_view(app).set_recording_status_text("Live player stats (recording)")
        player_stats_view(app).refresh_player_stats_timeline_ui()

        self.assertEqual(view.status_texts, ["Live player stats (recording)"])
        self.assertEqual(view.timeline_refreshes, 1)
        # the real widget was never touched
        self.assertEqual(app.player_stats_status_label.text(), "")

    def test_chaos_tome_signature_resolves_its_ordering_helper(self) -> None:
        """Step 14b moved `_chaos_stats_in_game_order` into `PlayerStatsCardsMixin`
        but left this call site qualified with `PlayerStatsMixin`, where the name no
        longer exists -- an unguarded AttributeError on every Chaos Tome render with a
        non-None tome. Nothing covered the path, so the suite stayed green.

        Retargeted at step 19, not deleted. The renderer is now
        `StatCardsView` and the helper is the module-level
        `chaos_stats_in_game_order`, which is what removes the original
        failure mode: a free function cannot be orphaned by its class
        moving, and it was the last *production* class-qualified call site
        in the step-18 inventory. The assertion is unchanged, so this still
        fails if the signature stops resolving its ordering helper.
        """
        # Two stats, ordered against the game table rather than insertion
        # order. The original single-stat fixture passed against a signature
        # that had stopped calling the ordering helper altogether -- one stat
        # sorts identically however you sort it -- so it asserted only that
        # the name resolved, not that it was used. Verified by mutation.
        first = SimpleNamespace(stat_id=9, label="Nine", display_delta="+9", rolls=1)
        second = SimpleNamespace(stat_id=1, label="One", display_delta="+1", rolls=2)
        chaos_tome = SimpleNamespace(level=2, ambiguous_rolls=0, stats=(first, second))
        self.assertLess(
            CHAOS_TOME_GAME_STAT_ORDER.get(second.stat_id, 999),
            CHAOS_TOME_GAME_STAT_ORDER.get(first.stat_id, 999),
            "fixture must be out of game order, or this asserts nothing",
        )

        signature = StatCardsView._chaos_tome_signature_for(chaos_tome)

        self.assertEqual(
            signature,
            (2, 0, ((1, "One", "+1", 2), (9, "Nine", "+9", 1))),
        )

    def test_chaos_stats_in_game_order_sorts_by_the_game_order_table(self) -> None:
        """The ordering itself, which the signature test above cannot see.

        `_chaos_tome_signature_for` calls the helper but a single stat is
        ordered identically however the helper sorts, so that test passes
        against a helper that does not sort at all.
        """
        stats = tuple(
            SimpleNamespace(stat_id=stat_id, label=f"Stat {stat_id}", display_delta="+1", rolls=0)
            for stat_id in (9, 2, 14, 1)
        )
        chaos_tome = SimpleNamespace(level=1, ambiguous_rolls=0, stats=stats)

        ordered = chaos_stats_in_game_order(chaos_tome)
        positions = [CHAOS_TOME_GAME_STAT_ORDER.get(s.stat_id, 999) for s in ordered]

        self.assertEqual(positions, sorted(positions))
        self.assertNotEqual(
            [s.stat_id for s in ordered],
            [s.stat_id for s in stats],
            "fixture must not already be in game order, or this asserts nothing",
        )


if __name__ == "__main__":
    unittest.main()
