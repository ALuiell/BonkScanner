from __future__ import annotations

from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import sys
import threading
from typing import Any, Callable
from urllib.parse import urlparse

import config


WIDGET_ROUTE_NAMES = {
    "stage_summary",
    "tracked_items",
    "stats",
    "banishes",
}


def _default_overlay_asset_dir() -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root is not None:
        return Path(bundle_root) / "media" / "overlay"
    return Path(__file__).resolve().parent / "media" / "overlay"


class OverlayStateStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {"status": "waiting"}

    def set_state(self, state: dict[str, Any]) -> None:
        with self._lock:
            self._state = dict(state)

    def get_state(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)


class _OverlayHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class LocalOverlayServer:
    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 17845,
        state_store: OverlayStateStore | None = None,
        asset_dir: Path | None = None,
    ) -> None:
        self.host = "127.0.0.1" if host != "127.0.0.1" else host
        self.port = int(port)
        self.state_store = state_store or OverlayStateStore()
        self.asset_dir = asset_dir or _default_overlay_asset_dir()
        self._server: _OverlayHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.last_error: str | None = None

    @property
    def is_running(self) -> bool:
        return self._server is not None and self._thread is not None and self._thread.is_alive()

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/overlay"

    def widget_url(self, widget_id: str) -> str:
        return f"{self.url}/{widget_id}"

    def start(self) -> None:
        if self.is_running:
            return
        self.last_error = None
        handler = partial(
            OverlayRequestHandler,
            state_provider=self.state_store.get_state,
            asset_dir=self.asset_dir,
        )
        try:
            self._server = _OverlayHTTPServer((self.host, self.port), handler)
        except OSError as exc:
            self._server = None
            self.last_error = str(exc)
            raise
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="BonkOverlayServer",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)


class OverlayRequestHandler(BaseHTTPRequestHandler):
    server_version = "BonkOverlay/1.0"

    def __init__(
        self,
        *args,
        state_provider: Callable[[], dict[str, Any]],
        asset_dir: Path,
        **kwargs,
    ) -> None:
        self._state_provider = state_provider
        self._asset_dir = asset_dir
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/overlay", "/overlay/", "/overlay/compact"}:
            self._serve_file(self._asset_dir / "index.html", "text/html; charset=utf-8")
            return
        if parsed.path.startswith("/overlay/"):
            widget_id = parsed.path.removeprefix("/overlay/").strip("/")
            if widget_id in WIDGET_ROUTE_NAMES:
                self._serve_file(self._asset_dir / "index.html", "text/html; charset=utf-8")
                return
        if parsed.path == "/api/overlay-state":
            self._serve_state()
            return
        if parsed.path.startswith("/assets/"):
            parts = [
                part
                for part in parsed.path.removeprefix("/assets/").split("/")
                if part and part not in {".", ".."}
            ]
            candidate = self._asset_dir.joinpath(*parts).resolve()
            try:
                candidate.relative_to(self._asset_dir.resolve())
            except ValueError:
                self._send_text(404, "Not found")
                return
            self._serve_file(candidate)
            return
        self._send_text(404, "Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/save-widget-positions":
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode('utf-8'))
                widget_id = data.get("id")
                
                # Update config with lock to prevent race conditions
                with config.config_lock:
                    overlay = dict(config.OVERLAY)
                    widgets = []
                    for widget in overlay.get("widgets", []):
                        if isinstance(widget, dict):
                            w = dict(widget)
                            if w.get("id") == widget_id:
                                if "x" in data and "y" in data:
                                    x_val = data["x"]
                                    y_val = data["y"]
                                    if x_val is None or y_val is None:
                                        w.pop("x", None)
                                        w.pop("y", None)
                                    else:
                                        w["x"] = int(x_val)
                                        w["y"] = int(y_val)
                                if "width" in data and "height" in data:
                                    w_val = data["width"]
                                    h_val = data["height"]
                                    if w_val is None or h_val is None:
                                        w.pop("width", None)
                                        w.pop("height", None)
                                    else:
                                        w["width"] = int(w_val)
                                        w["height"] = int(h_val)
                                if "scale" in data:
                                    scale_val = data["scale"]
                                    if scale_val is None:
                                        w.pop("scale", None)
                                    else:
                                        w["scale"] = max(0.4, min(float(scale_val), 4.0))
                            widgets.append(w)
                    overlay["widgets"] = widgets
                    config.OVERLAY = overlay
                    config.user_config["OVERLAY"] = config.OVERLAY
                    config.save_config(config.user_config)
                
                # Response
                body = json.dumps({"status": "success"}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self._send_text(400, f"Error: {e}")
            return
        elif parsed.path == "/api/save-canvas-resolution":
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode('utf-8'))
                width = int(data.get("width", 1920))
                height = int(data.get("height", 1080))
                
                # Update config with lock to prevent race conditions
                with config.config_lock:
                    overlay = dict(config.OVERLAY)
                    overlay["canvas_width"] = max(400, min(width, 7680))
                    overlay["canvas_height"] = max(300, min(height, 4320))
                    config.OVERLAY = overlay
                    config.user_config["OVERLAY"] = config.OVERLAY
                    config.save_config(config.user_config)
                
                # Response
                body = json.dumps({"status": "success"}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self._send_text(400, f"Error: {e}")
            return
        self._send_text(404, "Not found")

    def log_message(self, _format: str, *args) -> None:
        return

    def _serve_state(self) -> None:
        try:
            state = self._state_provider()
            if isinstance(state, dict):
                overlay_config = config.OVERLAY or {}
                from overlay_state import _widget_config_by_id
                state["widgets"] = _widget_config_by_id(overlay_config)
                state["canvas_width"] = int(overlay_config.get("canvas_width", 1920))
                state["canvas_height"] = int(overlay_config.get("canvas_height", 1080))
        except Exception as exc:
            state = {"status": "error", "error": str(exc)}
        body = json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except ConnectionAbortedError:
            pass
        except OSError as exc:
            if getattr(exc, "winerror", None) == 10053:
                pass
            else:
                raise

    def _serve_file(self, path: Path, content_type: str | None = None) -> None:
        if not path.exists() or not path.is_file():
            self._send_text(404, "Not found")
            return
        body = path.read_bytes()
        if content_type is None:
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except ConnectionAbortedError:
            pass
        except OSError as exc:
            if getattr(exc, "winerror", None) == 10053:
                pass
            else:
                raise

    def _send_text(self, status: int, text: str) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except ConnectionAbortedError:
            pass
        except OSError as exc:
            if getattr(exc, "winerror", None) == 10053:
                pass
            else:
                raise