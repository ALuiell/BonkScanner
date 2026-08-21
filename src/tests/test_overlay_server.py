from __future__ import annotations

import src

import json
import socket
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app import config
from infra.overlay_server import (
    LocalOverlayServer,
    MIN_WIDGET_HEIGHT,
    MIN_WIDGET_WIDTH,
    OverlayStateStore,
    WIDGET_ROUTE_NAMES,
    _default_overlay_asset_dir,
)


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

    def test_api_overlay_state_replaces_non_finite_values_with_json_null(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            asset_dir = Path(temp_dir)
            (asset_dir / "index.html").write_text("<html></html>", encoding="utf-8")
            store = OverlayStateStore()
            store.set_state(
                {
                    "status": "live",
                    "overflow": float("inf"),
                    "nested": {"unreadable": float("nan")},
                }
            )
            server = LocalOverlayServer(
                port=free_port(), state_store=store, asset_dir=asset_dir
            )
            server.start()
            try:
                with urlopen(
                    f"http://127.0.0.1:{server.port}/api/overlay-state", timeout=2
                ) as response:
                    text = response.read().decode("utf-8")
            finally:
                server.stop()

        payload = json.loads(
            text,
            parse_constant=lambda constant: self.fail(
                f"overlay emitted non-standard JSON constant {constant}"
            ),
        )
        self.assertIsNone(payload["overflow"])
        self.assertIsNone(payload["nested"]["unreadable"])

    def test_overlay_editor_rejects_non_standard_json_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            asset_dir = Path(temp_dir)
            (asset_dir / "index.html").write_text("<html></html>", encoding="utf-8")
            server = LocalOverlayServer(port=free_port(), asset_dir=asset_dir)
            server.start()
            try:
                request = Request(
                    f"http://127.0.0.1:{server.port}/api/save-widget-positions",
                    data=b'{"id":"kps","scale":NaN}',
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(HTTPError) as raised:
                    urlopen(request, timeout=2)
                self.assertEqual(400, raised.exception.code)
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
                {"id": "build_progression", "max_rows": 13,
                 "show_completed": True, "show_border": True},
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
        self.assertEqual({"kps", "stats", "build_progression"}, set(widgets))
        # Coercions and clamps, so this fails if the normalization is bypassed
        # rather than merely relocated.
        self.assertEqual(4.0, widgets["kps"]["scale"])
        self.assertEqual(0.4, widgets["stats"]["scale"])
        self.assertEqual(20, widgets["kps"]["y"])
        self.assertEqual(5, widgets["kps"]["order"])
        self.assertEqual(20, widgets["stats"]["order"])
        self.assertEqual(["current", "run_avg"], widgets["kps"]["selected_kps_metrics"])
        self.assertEqual(["Damage", "Luck"], widgets["stats"]["selected_stats"])
        self.assertEqual(13, widgets["build_progression"]["max_rows"])
        self.assertTrue(widgets["build_progression"]["show_completed"])
        self.assertTrue(widgets["build_progression"]["show_border"])

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

    def test_every_overlay_widget_has_a_route(self) -> None:
        """The widget selector offers every configured widget as a source.

        It builds itself from the widget list, so a widget that exists in the
        config but not in `WIDGET_ROUTE_NAMES` is offered, copied, pasted into
        OBS and answered with 404 -- which is what `luck_rarity` did. Comparing
        the two lists is the only check that fails *before* the URL leaves the
        app.
        """
        configured = {widget["id"] for widget in config.DEFAULT_OVERLAY["widgets"]}
        self.assertEqual(configured, WIDGET_ROUTE_NAMES)

    def test_widget_overlay_route_serves_overlay_page(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            asset_dir = Path(temp_dir)
            (asset_dir / "index.html").write_text("<html>overlay</html>", encoding="utf-8")
            server = LocalOverlayServer(port=free_port(), asset_dir=asset_dir)
            server.start()
            try:
                # Every route, not just one: the set above is what the selector
                # copies from, so a name in it that the server does not serve is
                # the same 404 by another path.
                for widget_id in sorted(WIDGET_ROUTE_NAMES):
                    with self.subTest(widget=widget_id):
                        url = f"http://127.0.0.1:{server.port}/overlay/{widget_id}"
                        with urlopen(url, timeout=2) as response:
                            self.assertEqual(response.status, 200)
                            self.assertEqual(response.read().decode("utf-8"), "<html>overlay</html>")
            finally:
                server.stop()

    def test_state_requests_are_what_liveness_is_measured_from(self) -> None:
        """`is_running` cannot answer "is a Browser Source actually pulling?".

        A source pointed at the wrong port, or never added to the scene, leaves
        a perfectly healthy server -- so the OBS tab's preview badge reads this
        instead. Fetching the page is deliberately not enough: OBS loads the
        HTML once and then polls state, so only the state route counts.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            asset_dir = Path(temp_dir)
            (asset_dir / "index.html").write_text("<html></html>", encoding="utf-8")
            server = LocalOverlayServer(port=free_port(), asset_dir=asset_dir)
            server.start()
            try:
                # Never asked: not "a long time ago", which is a different
                # answer and a different badge.
                self.assertIsNone(server.seconds_since_state_request())

                with urlopen(f"http://127.0.0.1:{server.port}/overlay", timeout=2):
                    pass
                self.assertIsNone(
                    server.seconds_since_state_request(),
                    "serving the page counted as a client polling",
                )

                with urlopen(f"http://127.0.0.1:{server.port}/api/overlay-state", timeout=2):
                    pass
                elapsed = server.seconds_since_state_request()
                self.assertIsNotNone(elapsed)
                self.assertLess(elapsed, 5.0)
            finally:
                server.stop()

    def test_saved_widget_size_is_floored(self) -> None:
        """A widget cannot be persisted small enough to become ungrabbable.

        `.widget-wrapper.draggable` carries `resize: both`, and the native handle
        has no lower bound of its own. Anything under about 18px is a trap
        rather than a small widget: `setupDragAndDrop` reserves the bottom-right
        18px for that same handle, so the dead zone covers the whole element and
        `pointerdown` returns early every time. Nothing in the editor can undo
        it after that.

        The CSS `min-width`/`min-height` stop the drag before it reaches here.
        This floor is the backstop for a size arriving some other way -- a
        hand-edited config, or one saved before the floor existed -- so it is
        checked on the value that actually lands in settings.
        """
        overlay_config = {"widgets": [{"id": "kps", "width": 400, "height": 300}]}

        class Settings:
            def read(self):
                return overlay_config

            def update(self, mutate):
                mutate(overlay_config)

        with tempfile.TemporaryDirectory() as temp_dir:
            asset_dir = Path(temp_dir)
            (asset_dir / "index.html").write_text("<html></html>", encoding="utf-8")
            server = LocalOverlayServer(
                port=free_port(), asset_dir=asset_dir, settings=Settings()
            )
            server.start()
            try:
                request = Request(
                    f"http://127.0.0.1:{server.port}/api/save-widget-positions",
                    data=json.dumps({"id": "kps", "width": 3, "height": 2}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=2) as response:
                    self.assertEqual(200, response.status)
            finally:
                server.stop()

        saved = overlay_config["widgets"][0]
        self.assertEqual(MIN_WIDGET_WIDTH, saved["width"])
        self.assertEqual(MIN_WIDGET_HEIGHT, saved["height"])

    def test_saved_widget_size_above_the_floor_is_untouched(self) -> None:
        overlay_config = {"widgets": [{"id": "kps"}]}

        class Settings:
            def read(self):
                return overlay_config

            def update(self, mutate):
                mutate(overlay_config)

        with tempfile.TemporaryDirectory() as temp_dir:
            asset_dir = Path(temp_dir)
            (asset_dir / "index.html").write_text("<html></html>", encoding="utf-8")
            server = LocalOverlayServer(
                port=free_port(), asset_dir=asset_dir, settings=Settings()
            )
            server.start()
            try:
                request = Request(
                    f"http://127.0.0.1:{server.port}/api/save-widget-positions",
                    data=json.dumps({"id": "kps", "width": 321, "height": 74}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=2) as response:
                    self.assertEqual(200, response.status)
            finally:
                server.stop()

        self.assertEqual(321, overlay_config["widgets"][0]["width"])
        self.assertEqual(74, overlay_config["widgets"][0]["height"])

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
        self.assertIn("if (!el.isConnected) {", script)

    def test_editor_fits_the_canvas_and_measures_around_the_transform(self) -> None:
        """The editor scales the canvas down, and nothing may measure through it.

        The canvas is a fixed `canvas_width` x `canvas_height` box; the window
        the editor opens in is smaller. Without the fit, everything defaulting
        to `x: 1600` -- four of the six widgets, which is correct for a 1920 OBS
        scene -- sits off the right edge of the window and reads as "the widget
        never appears". That was the reported bug.

        The fit is a transform, and a transform is exactly the kind of thing the
        two size-measuring paths silently disagree with: `getBoundingClientRect`
        reports post-transform pixels, and both of them *write* what they read
        (one POSTs it, one pins it as an explicit width). Measuring through the
        transform would have shrunk every widget a little on every open, which
        is the failure mode the size floor above exists to make unrecoverable.
        So the units are pinned here, not just the scaling.
        """
        script = (_default_overlay_asset_dir() / "overlay.js").read_text(encoding="utf-8")
        style = (_default_overlay_asset_dir() / "overlay.css").read_text(encoding="utf-8")

        self.assertIn("function applyEditorScale()", script)
        self.assertIn("edit-canvas-frame", script)
        self.assertIn("#edit-canvas-frame", style)
        self.assertIn("transform: scale(var(--editor-scale, 1));", style)
        # Never enlarged past 1:1, and never shrunk into a postage stamp.
        self.assertIn("Math.max(EDITOR_MIN_SCALE, Math.min(1, fitWidth, fitHeight))", script)

        # Pointer deltas arrive in screen pixels and `left`/`top` are canvas
        # pixels; they agree only at scale 1.
        self.assertIn("const dx = (e.clientX - startX) / editorScale;", script)
        self.assertIn("const dy = (e.clientY - startY) / editorScale;", script)

        # Both writers of a persisted size read layout pixels.
        self.assertIn("const w = el.offsetWidth;", script)
        self.assertIn("const h = el.offsetHeight;", script)
        self.assertIn("const width = Math.max(1, currentElement.offsetWidth);", script)
        self.assertIn("const height = Math.max(1, currentElement.offsetHeight);", script)

        # The CSS half of the size floor, in step with the server's.
        self.assertIn(f"min-width: {MIN_WIDGET_WIDTH}px;", style)
        self.assertIn(f"min-height: {MIN_WIDGET_HEIGHT}px;", style)

    def test_default_positions_are_resolved_against_the_configured_canvas(self) -> None:
        """A widget nobody placed lands inside the canvas, whatever its size.

        `DEFAULT_COORDINATES` are written against a 1920x1080 scene, and were
        applied raw to any canvas. On a 1280-wide one `x: 1600` is not a poor
        placement -- the shell clips at its own edge, so the four widgets that
        default there were invisible and unreachable at every zoom and scroll
        position, in the editor *and* in OBS. Reported as "Tracked Items is the
        only widget that shows up"; the reporter's canvas was 720p.

        Both halves are pinned because either alone leaves the bug:

        - `x` scales, to keep the right-hand cluster right-anchored instead of
          drifting to the middle of a wider or narrower scene;
        - `y` does not, because it encodes gaps measured against widget heights
          that do not scale with the canvas -- scaling it re-creates the
          `banishes`/`luck_rarity` overlap those gaps were chosen to remove;
        - and neither can promise the widget is *inside*, because nothing has a
          size until it is in the document, so a measured clamp runs after.

        The clamp only ever touches `data-defaulted` elements. A dragged
        position is the user's, may legally sit further right than the clamp
        would place anything, and must not slide back when they let go.
        """
        script = (_default_overlay_asset_dir() / "overlay.js").read_text(encoding="utf-8")

        self.assertIn("const REFERENCE_CANVAS_WIDTH = 1920;", script)
        # `y` is carried through untouched; only `x` is mapped onto the canvas.
        self.assertIn("x: Math.round(reference.x * (canvasWidth / REFERENCE_CANVAS_WIDTH))", script)
        self.assertIn("y: reference.y,", script)
        self.assertNotIn("REFERENCE_CANVAS_HEIGHT", script)

        # The measured correction, and that it runs before anything reads a
        # position back out of the DOM.
        self.assertIn("function clampDefaultedWidgets()", script)
        self.assertIn('root.querySelectorAll(\'.widget-wrapper[data-defaulted="true"]\')', script)
        self.assertIn("const maxLeft = Math.max(0, canvasWidth - element.offsetWidth);", script)
        self.assertIn("const maxTop = Math.max(0, canvasHeight - element.offsetHeight);", script)
        self.assertIn("clampDefaultedWidgets();", script)

        # Marked on the way in, dropped the moment a drag owns the position.
        self.assertIn('const defaultedAttr = placed ? "" : ` data-defaulted="true"`;', script)
        self.assertIn('el.removeAttribute("data-defaulted");', script)

    def test_default_server_serves_the_real_overlay_page(self) -> None:
        server = LocalOverlayServer(port=free_port())
        server.start()
        try:
            with urlopen(f"http://127.0.0.1:{server.port}/overlay", timeout=2) as response:
                self.assertEqual(response.status, 200)
                self.assertIn(b"<", response.read(64))
        finally:
            server.stop()
