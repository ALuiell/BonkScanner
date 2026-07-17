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

    def test_default_server_serves_the_real_overlay_page(self) -> None:
        server = LocalOverlayServer(port=free_port())
        server.start()
        try:
            with urlopen(f"http://127.0.0.1:{server.port}/overlay", timeout=2) as response:
                self.assertEqual(response.status, 200)
                self.assertIn(b"<", response.read(64))
        finally:
            server.stop()
