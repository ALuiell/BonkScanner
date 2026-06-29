from __future__ import annotations

import src

import json
import socket
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from overlay_server import LocalOverlayServer, OverlayStateStore


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
                with urlopen(f"http://127.0.0.1:{server.port}/overlay/stats", timeout=2) as response:
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