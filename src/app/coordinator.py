"""``AppCoordinator`` -- the owner of the runtime instances the GUI used to build
for itself.

Step 11 is ownership only. Construction moves here; the 500 ms GUI timer still
drives the tick and the mixins still reach these instances through the shared
``self``. Step 12 inverts that, and it is the step that needs the live checks.

Only construction moved, deliberately. The memory-client lifecycle
(``client``, ``player_stats_client``, ``player_stats_game_data_client``) stays on
``MegabonkApp``: those are opened and closed in response to scanner and read
failures, so moving them is a lifecycle change, which is step 12's job and needs
the game running to verify.

``AppCoordinator`` imports no PySide6 and holds no widget.
"""
from __future__ import annotations

from typing import Any, Sequence

from app.refresh_coordinator import RefreshCoordinator
from app.snapshot_store import LiveSnapshotStore
from infra.overlay_server import LocalOverlayServer, OverlayStateStore
from infra.vod_storage import VodRecorder
from live_run_tracker import LiveRunTracker


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
        self.overlay_state_store = OverlayStateStore()
        self.live_run_tracker = LiveRunTracker(
            tracked_item_rules=tracked_item_rules,
            stale_after_seconds=stale_after_seconds,
        )
        self.overlay_server = LocalOverlayServer(
            host=overlay_host,
            port=overlay_port,
            state_store=self.overlay_state_store,
        )
        self.snapshot_store = LiveSnapshotStore()
        self.vod_recorder = VodRecorder(interval_seconds=vod_interval_seconds)


        # Filled by ``ensure_refresh_coordinator`` rather than here: the tasks it
        # registers are bound to the owner's methods, so the coordinator cannot
        # build it without the owner. Step 12 is where those tasks stop being
        # owner-bound and this can become a plain constructor call.
        self.refresh_coordinator: RefreshCoordinator | None = None

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
        )
        return self.overlay_server

    def tick(self) -> None:
        if self.refresh_coordinator is not None:
            self.refresh_coordinator.tick()

    def diagnostics(self) -> dict[str, Any]:
        if self.refresh_coordinator is None:
            return {}
        return self.refresh_coordinator.diagnostics()
