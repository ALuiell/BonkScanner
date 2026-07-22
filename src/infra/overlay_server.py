from __future__ import annotations

from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import sys
import threading
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from core.settings import NullOverlaySettings, OverlaySettings
from core.overlay_config import widget_config_by_id
from infra import paths


WIDGET_ROUTE_NAMES = {
    "stage_summary",
    "tracked_items",
    "stats",
    "kps",
    "banishes",
}


def _default_overlay_asset_dir() -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root is not None:
        return Path(bundle_root) / "media" / "overlay"
    # Anchored in infra/paths, not this file's own __file__: the assets live in
    # src/media/overlay and do not follow this module around. Deriving from
    # __file__ here meant step 10b's src/ -> src/infra/ move pointed this at
    # src/infra/media/overlay, and the overlay served 404 for every asset.
    return Path(paths.source_path()) / "media" / "overlay"


class OverlayStateStore:
    _EDIT_LAYOUT_FIELDS = {"x", "y", "width", "height", "scale"}

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._state: dict[str, Any] = {"status": "waiting"}
        self._edit_widget_signature = "[]"
        self._widget_revision = 0

    @classmethod
    def _editor_widget_settings(cls, state: dict[str, Any]) -> str:
        widgets = state.get("widgets") or {}
        if isinstance(widgets, dict):
            entries = widgets.items()
        elif isinstance(widgets, list):
            entries = (
                (str(widget.get("id") or ""), widget)
                for widget in widgets
                if isinstance(widget, dict)
            )
        else:
            return "[]"

        normalized = []
        for widget_id, widget in entries:
            if not widget_id or not isinstance(widget, dict):
                continue
            editor_settings = {
                str(key): value
                for key, value in widget.items()
                if key not in cls._EDIT_LAYOUT_FIELDS
            }
            editor_settings["id"] = str(widget_id)
            normalized.append(editor_settings)
        normalized.sort(key=lambda widget: widget["id"])
        return json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

    def set_state(self, state: dict[str, Any]) -> None:
        edit_widget_signature = self._editor_widget_settings(state)
        with self._condition:
            self._state = dict(state)
            if edit_widget_signature != self._edit_widget_signature:
                self._edit_widget_signature = edit_widget_signature
                self._widget_revision += 1
                self._condition.notify_all()

    def get_state(self) -> dict[str, Any]:
        with self._condition:
            return dict(self._state)

    def get_widget_revision(self) -> int:
        with self._condition:
            return self._widget_revision

    def wait_for_widget_revision(self, after_revision: int, timeout: float = 25.0) -> int:
        with self._condition:
            self._condition.wait_for(
                lambda: self._widget_revision != after_revision,
                timeout=timeout,
            )
            return self._widget_revision


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
        settings: OverlaySettings | None = None,
    ) -> None:
        self.host = "127.0.0.1" if host != "127.0.0.1" else host
        self.port = int(port)
        self.state_store = state_store or OverlayStateStore()
        self.settings = settings or NullOverlaySettings()
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
            widget_revision_provider=self.state_store.get_widget_revision,
            widget_revision_waiter=self.state_store.wait_for_widget_revision,
            asset_dir=self.asset_dir,
            settings=self.settings,
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
        widget_revision_provider: Callable[[], int],
        widget_revision_waiter: Callable[[int, float], int],
        asset_dir: Path,
        settings: OverlaySettings | None = None,
        **kwargs,
    ) -> None:
        self._state_provider = state_provider
        self._widget_revision_provider = widget_revision_provider
        self._widget_revision_waiter = widget_revision_waiter
        self._asset_dir = asset_dir
        self._settings = settings or NullOverlaySettings()
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
        if parsed.path == "/api/overlay-widget-revision":
            self._serve_widget_revision(parsed.query)
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
                
                def apply_widget_geometry(overlay):
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

                # The store takes the lock; this is the read-modify-write it
                # used to do inline under config.config_lock.
                self._settings.update(apply_widget_geometry)
                
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
                
                def apply_canvas_size(overlay):
                    overlay["canvas_width"] = max(400, min(width, 7680))
                    overlay["canvas_height"] = max(300, min(height, 4320))

                self._settings.update(apply_canvas_size)
                
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
                overlay_config = self._settings.read()
                # Re-read per request on purpose: the overlay editor POSTs new
                # widget geometry to this same server, and the browser must see
                # it on the next poll rather than waiting for the cached state
                # to be refreshed by a tracker update.
                state["widgets"] = widget_config_by_id(overlay_config)
                state["canvas_width"] = int(overlay_config.get("canvas_width", 1920))
                state["canvas_height"] = int(overlay_config.get("canvas_height", 1080))
                state["widget_revision"] = self._widget_revision_provider()
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

    def _serve_widget_revision(self, query: str) -> None:
        try:
            raw_after = parse_qs(query).get("after", ["0"])[0]
            after_revision = max(0, int(raw_after))
        except (TypeError, ValueError):
            self._send_text(400, "Invalid widget revision")
            return
        revision = self._widget_revision_waiter(after_revision, 25.0)
        body = json.dumps({"revision": revision}, separators=(",", ":")).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (ConnectionAbortedError, BrokenPipeError):
            pass
        except OSError as exc:
            if getattr(exc, "winerror", None) != 10053:
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
