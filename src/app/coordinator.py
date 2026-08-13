"""``AppCoordinator`` -- the owner of the runtime instances the GUI used to build
for itself.

Step 11 gave it the runtime instances; the 500 ms GUI timer still drove the tick
and the mixins reached those instances through the shared ``self``. Step 12a
moved the driver loop here (``start_refresh_loop`` / ``RefreshLoop``): the GUI now
supplies only the thread hop and the tick body, and the coordinator owns when to
run and reschedule.

Step 12b moved the memory-client storage here too (``client``,
``player_stats_client``, ``player_stats_game_data_client``). The scanner and
player-stats mixins still decide *when* to (re)open and close them in response to
scanner state and read failures, but the instances now have a single owner --
reached through property delegation on those mixins -- which is what lets step 12d
close them from one shutdown path.

``AppCoordinator`` imports no PySide6 and holds no widget.
"""
from __future__ import annotations

from typing import Any, Callable, Sequence

from app.refresh_coordinator import RefreshCoordinator
from app.settings import ConfigBuildProgressionSettings, ConfigOverlaySettings, ConfigRecordingSettings
from app.build_progression import BuildProgressionService, active_definition_from_config
from app.snapshot_store import LiveSnapshotStore
from infra import vod_storage
from infra.overlay_server import LocalOverlayServer, OverlayStateStore
from infra.vod_storage import VodRecorder
from core.tracker.live_run import LiveRunTracker


class RefreshLoop:
    """The fast-tick driver loop, owned by ``AppCoordinator``.

    The GUI supplies only the mechanism: ``schedule`` is the thread hop
    (``MegabonkApp.after``) and ``tick`` is the per-tick body. The *policy* --
    the interval, the is-active gate, and the decision to reschedule -- lives
    here. Step 12d replaces ``schedule`` with a real lifecycle; when it does,
    neither ``tick`` nor this class changes.
    """

    def __init__(
        self,
        *,
        tick: Callable[[], Any],
        schedule: Callable[[int, Callable[[], Any]], Any],
        is_active: Callable[[], bool],
        interval_ms: Callable[[], int],
    ) -> None:
        self._tick = tick
        self._schedule = schedule
        self._is_active = is_active
        self._interval_ms = interval_ms

    def start(self) -> None:
        self._step()

    def _step(self) -> None:
        # Mirrors the two ``_is_shutting_down`` checks the GUI timer used to make:
        # do not tick once stopped, and do not reschedule after the tick if a
        # stop landed while it ran. A tick that raises still reschedules (the
        # ``finally``), exactly as the old ``update_player_stats_timer`` did.
        if not self._is_active():
            return
        try:
            self._tick()
        finally:
            if self._is_active():
                self._schedule(int(self._interval_ms()), self._step)


class AppCoordinator:
    def __init__(
        self,
        *,
        tracked_item_rules: Sequence[Any],
        stale_after_seconds: float,
        overlay_host: str,
        overlay_port: int,
        vod_interval_seconds: float,
    ) -> None:
        # infra/ depends on the settings ports in core/; this is where the
        # config-backed implementations get injected (step 11c).
        self.overlay_settings = ConfigOverlaySettings()
        vod_storage.use_settings(ConfigRecordingSettings())

        self.overlay_state_store = OverlayStateStore()
        self.live_run_tracker = LiveRunTracker(
            tracked_item_rules=tracked_item_rules,
            stale_after_seconds=stale_after_seconds,
        )
        self.build_progression_settings = ConfigBuildProgressionSettings()
        self.build_progression_service = BuildProgressionService(
            self.live_run_tracker,
            active_definition_from_config(self.build_progression_settings.read()),
        )
        self.overlay_server = LocalOverlayServer(
            host=overlay_host,
            port=overlay_port,
            state_store=self.overlay_state_store,
            settings=self.overlay_settings,
        )
        self.snapshot_store = LiveSnapshotStore()
        self.vod_recorder = VodRecorder(interval_seconds=vod_interval_seconds)

        # Memory-client instances (step 12b). The coordinator owns their storage;
        # MegabonkApp reaches them through property delegation. Creation and close
        # policy still lives in the scanner/player-stats mixins -- those decide
        # *when* to (re)open in response to scanner state and read failures -- but
        # the instances themselves now have a single owner, which is what lets
        # step 12d close them from one shutdown path.
        self.client = None
        self.player_stats_client = None
        self.player_stats_game_data_client = None


        # Filled by ``ensure_refresh_coordinator`` rather than here: the tasks it
        # registers are bound to the owner's methods, so the coordinator cannot
        # build it without the owner. Step 12 is where those tasks stop being
        # owner-bound and this can become a plain constructor call.
        self.refresh_coordinator: RefreshCoordinator | None = None

        # The fast-tick driver loop (step 12a). Held so ownership is real rather
        # than a fire-and-forget: the loop reschedules itself through the
        # injected ``schedule`` until ``is_active`` reports the app is stopping.
        self.refresh_loop: RefreshLoop | None = None

    def start_refresh_loop(
        self,
        *,
        tick: Callable[[], Any],
        schedule: Callable[[int, Callable[[], Any]], Any],
        is_active: Callable[[], bool],
        interval_ms: Callable[[], int],
    ) -> RefreshLoop:
        """Take ownership of the fast-tick driver loop and run its first tick.

        The GUI used to own this in ``update_player_stats_timer``'s
        ``try/finally``; now it hands the coordinator the thread hop
        (``schedule``) and the tick body, and the coordinator decides when to
        run and when to reschedule.
        """
        self.refresh_loop = RefreshLoop(
            tick=tick,
            schedule=schedule,
            is_active=is_active,
            interval_ms=interval_ms,
        )
        self.refresh_loop.start()
        return self.refresh_loop

    def rebuild_overlay_server(self, *, host: str, port: int) -> LocalOverlayServer:
        """Replace the overlay server with one bound to `port`.

        The server is not built once: the user can change the port in the UI and
        press start, and a bound server cannot be rebound. Ownership would be a
        lie if the rebuild happened anywhere else -- the coordinator's reference
        would go stale the first time the user restarted the server.
        """
        self.overlay_server = LocalOverlayServer(
            host=host,
            port=port,
            state_store=self.overlay_state_store,
            settings=self.overlay_settings,
        )
        return self.overlay_server

    def tick(self) -> None:
        if self.refresh_coordinator is not None:
            self.refresh_coordinator.tick()

    def diagnostics(self) -> dict[str, Any]:
        if self.refresh_coordinator is None:
            return {}
        return self.refresh_coordinator.diagnostics()

    def shutdown(self) -> None:
        """Release the memory clients the coordinator owns. Idempotent.

        Called from ``MegabonkApp.on_closing``. Closing them here -- rather than
        through three scattered mixin methods -- is what "the coordinator owns the
        lifecycle" means once step 12b gave it the instances: it holds them, so it
        closes them. The refresh loop needs no explicit stop -- its pending
        ``after`` callback sees ``is_active`` go false at shutdown and does not
        reschedule.
        """
        for attr in ("client", "player_stats_client", "player_stats_game_data_client"):
            instance = getattr(self, attr)
            if instance is None:
                continue
            try:
                instance.close()
            except Exception:
                pass
            setattr(self, attr, None)
