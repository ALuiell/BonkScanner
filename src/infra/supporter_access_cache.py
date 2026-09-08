"""Non-secret cache for the last validated supporter entitlement."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from infra.paths import application_path


_MAX_CACHE_BYTES = 64 * 1024


def default_cache_path() -> Path:
    local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
    root = Path(local_appdata) / "BonkScanner" if local_appdata else Path(application_path())
    return root / "supporter_access_cache.json"


def read_access_cache(path: Path | None = None) -> dict | None:
    target = Path(path or default_cache_path())
    try:
        if target.stat().st_size > _MAX_CACHE_BYTES:
            return None
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def write_access_cache(payload: dict, path: Path | None = None) -> None:
    target = Path(path or default_cache_path())
    target.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n"
    if len(rendered.encode("utf-8")) > _MAX_CACHE_BYTES:
        raise ValueError("Supporter access cache is unexpectedly large.")
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def delete_access_cache(path: Path | None = None) -> None:
    try:
        Path(path or default_cache_path()).unlink(missing_ok=True)
    except OSError:
        pass
