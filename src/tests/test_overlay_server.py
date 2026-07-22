from __future__ import annotations

import src

import json
import socket
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from infra.overlay_server import LocalOverlayServer, _default_overlay_asset_dir, OverlayStateStore


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class OverlayServerTests(unittest.TestCase):
    def test_widget_revision_ignores_layout_but_tracks_editor_settings(self) -> None:
        store = OverlayStateStore()
        self.assertEqual(store.get_widget_revision(), 0)

        store.set_state({"widgets": {"kps": {
            "id": "kps", "enabled": True, "width": 100, "background_opacity": 0.0,
        }}})
        self.assertEqual(store.get_widget_revision(), 1)

        store.set_state({"widgets": {"kps": {
            "id": "kps", "enabled": True, "width": 250, "background_opacity": 0.0,
        }}})
        self.assertEqual(store.get_widget_revision(), 1)

        store.set_state({"widgets": {"kps": {
            "id": "kps", "enabled": True, "width": 250, "background_opacity": 0.4,
        }}})
        self.assertEqual(store.get_widget_revision(), 2)

        store.set_state({"widgets": {"kps": {
            "id": "kps", "enabled": False, "width": 250, "background_opacity": 0.4,
        }}})
        self.assertEqual(store.get_widget_revision(), 3)

    def test_widget_revision_endpoint_returns_current_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            asset_dir = Path(temp_dir)
            (asset_dir / "index.html").write_text("<html></html>", encoding="utf-8")
            store = OverlayStateStore()
            store.set_state({"widgets": {"stats": {"id": "stats", "enabled": True}}})
            server = LocalOverlayServer(port=free_port(), state_store=store, asset_dir=asset_dir)
            server.start()
            try:
                with urlopen(
                    f"http://127.0.0.1:{server.port}/api/overlay-widget-revision?after=0",
                    timeout=2,
                ) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(payload, {"revision": 1})
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
            finally:
                server.stop()

    def test_api_overlay_state_returns_json_with_no_store(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            asset_dir = Path(temp_dir)
            (asset_dir / "index.html").write_text("<html></html>", encoding="utf-8")
            store = OverlayStateStore()
            store.set_state({"status": "live", "answer": 42})
            server = LocalOverlayServer(port=free_port(), state_store=store, asset_dir=asset_dir)
            server.start()
            try:
                with urlopen(f"http://127.0.0.1:{server.port}/api/overlay-state", timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(payload["status"], "live")
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
            finally:
                server.stop()

    def test_api_overlay_state_overrides_widgets_from_current_settings(self) -> None:
        """The served payload normalizes widget config read at request time.

        Step 17b moved that normalization from projections.obs (reached through
        a method-body import of a private name) down to core/overlay_config.py.
        _serve_state had no coverage at all, so nothing here would have noticed
        the move breaking it.

        The override is the behaviour worth pinning: the overlay editor POSTs new
        geometry to this same server, so a stale `widgets` value on the cached
        state must lose to freshly-read settings on the next poll.
        """
        overlay_config = {
            "canvas_width": 2560,
            "canvas_height": 1440,
            "widgets": [
                {"id": "kps", "order": 5, "y": "20", "scale": 9.9,
                 "selected_kps_metrics": ["current", "bogus", "run_avg"]},
                {"id": "stats", "order": "not-an-int", "scale": 0.01,
                 "selected_stats": ["Damage", "  ", "Luck"]},
                {"id": "  "},
                "not-a-dict",
            ],
        }

        class Settings:
            def read(self):
                return overlay_config

        with tempfile.TemporaryDirectory() as temp_dir:
            asset_dir = Path(temp_dir)
            (asset_dir / "index.html").write_text("<html></html>", encoding="utf-8")
            store = OverlayStateStore()
            store.set_state({
                "status": "live",
                "widgets": {"stale": "replaced"},
                "canvas_width": 1,
                "canvas_height": 2,
            })
            server = LocalOverlayServer(
                port=free_port(), state_store=store, asset_dir=asset_dir, settings=Settings()
            )
            server.start()
            try:
                with urlopen(f"http://127.0.0.1:{server.port}/api/overlay-state", timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.stop()

        widgets = payload["widgets"]
        self.assertNotIn("stale", widgets)
        self.assertEqual(2560, payload["canvas_width"])
        self.assertEqual(1440, payload["canvas_height"])
        # Blank ids and non-dict entries are dropped.
        self.assertEqual({"kps", "stats"}, set(widgets))
        # Coercions and clamps, so this fails if the normalization is bypassed
        # rather than merely relocated.
        self.assertEqual(4.0, widgets["kps"]["scale"])
        self.assertEqual(0.4, widgets["stats"]["scale"])
        self.assertEqual(20, widgets["kps"]["y"])
        self.assertEqual(5, widgets["kps"]["order"])
        self.assertEqual(20, widgets["stats"]["order"])
        self.assertEqual(["current", "run_avg"], widgets["kps"]["selected_kps_metrics"])
        self.assertEqual(["Damage", "Luck"], widgets["stats"]["selected_stats"])

    def test_unknown_route_returns_404(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            asset_dir = Path(temp_dir)
            (asset_dir / "index.html").write_text("<html></html>", encoding="utf-8")
            server = LocalOverlayServer(port=free_port(), asset_dir=asset_dir)
            server.start()
            try:
                with self.assertRaises(HTTPError) as raised:
                    urlopen(f"http://127.0.0.1:{server.port}/missing", timeout=2)
                self.assertEqual(raised.exception.code, 404)
            finally:
                server.stop()

    def test_widget_overlay_route_serves_overlay_page(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            asset_dir = Path(temp_dir)
            (asset_dir / "index.html").write_text("<html>overlay</html>", encoding="utf-8")
            server = LocalOverlayServer(port=free_port(), asset_dir=asset_dir)
            server.start()
            try:
                with urlopen(f"http://127.0.0.1:{server.port}/overlay/kps", timeout=2) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.read().decode("utf-8"), "<html>overlay</html>")
            finally:
                server.stop()

    def test_server_binds_to_loopback_host(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            asset_dir = Path(temp_dir)
            (asset_dir / "index.html").write_text("<html></html>", encoding="utf-8")
            server = LocalOverlayServer(host="0.0.0.0", port=free_port(), asset_dir=asset_dir)
            server.start()
            try:
                self.assertEqual(server._server.server_address[0], "127.0.0.1")
            finally:
                server.stop()


if __name__ == "__main__":
    unittest.main()


class OverlayAssetDirTests(unittest.TestCase):
    """The asset dir is a path into the repo, so a module move can silently break it.

    Step 10b moved overlay_server.py from src/ to src/infra/ while the dir was
    derived from this module's own __file__, and the overlay served 404 for every
    asset. No test noticed: none of them used the real asset dir, they all passed
    a temp one. The exe was fine throughout -- the frozen branch reads _MEIPASS.
    """

    def test_default_asset_dir_holds_the_overlay_page(self) -> None:
        asset_dir = _default_overlay_asset_dir()
        self.assertTrue(asset_dir.is_dir(), f"overlay assets missing: {asset_dir}")
        self.assertTrue(
            (asset_dir / "index.html").is_file(),
            f"overlay index.html missing under {asset_dir}",
        )

    def test_overlay_editor_watches_widget_revisions_without_state_polling(self) -> None:
        """Edit mode watches settings while normal overlay polling remains intact."""
        script = (_default_overlay_asset_dir() / "overlay.js").read_text(encoding="utf-8")
        self.assertIn("watchEditWidgetChanges();", script)
        self.assertIn("/api/overlay-widget-revision?after=", script)
        self.assertIn("if (!isEditMode) {\n      window.setTimeout(refresh, pollMs);", script)
        self.assertIn("syncEditModeWidgets(html, widgets);", script)
        self.assertIn("preserveEditWidgetLayout(currentElement, desiredElement);", script)
        self.assertIn("currentElement.replaceWith(desiredElement);", script)
        self.assertIn(".widget-wrapper.draggable:not([data-edit-initialized])", script)

    def test_default_server_serves_the_real_overlay_page(self) -> None:
        server = LocalOverlayServer(port=free_port())
        server.start()
        try:
            with urlopen(f"http://127.0.0.1:{server.port}/overlay", timeout=2) as response:
                self.assertEqual(response.status, 200)
                self.assertIn(b"<", response.read(64))
        finally:
            server.stop()
