"""Non-secret cache for the last validated supporter entitlement."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from infra.paths import application_path


_MAX_CACHE_BYTES = 64 * 1024


def default_cache_path() -> Path:
    return Path(application_path()) / "supporter_access_cache.json"


def _legacy_shared_cache_path() -> Path | None:
    """Return the pre-storage-update cache path for a legacy EXE profile.

    Older releases always kept this one non-secret cache in Local AppData.  A
    legacy installation now writes all new data beside its EXE, but it should
    still be able to read the already validated entitlement until the next
    successful server refresh.
    """
    from infra.data_storage import storage_context

    context = storage_context()
    if context.mode != "legacy" or context.recommended_dir is None:
        return None
    fallback = context.recommended_dir / "supporter_access_cache.json"
    return fallback if fallback != default_cache_path() else None


def _read_cache_file(target: Path) -> dict | None:
    try:
        if target.stat().st_size > _MAX_CACHE_BYTES:
            return None
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def read_access_cache(path: Path | None = None) -> dict | None:
    target = Path(path or default_cache_path())
    payload = _read_cache_file(target)
    if payload is not None or path is not None or target.exists():
        return payload
    fallback = _legacy_shared_cache_path()
    return _read_cache_file(fallback) if fallback is not None else None


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
    targets = [Path(path or default_cache_path())]
    if path is None:
        fallback = _legacy_shared_cache_path()
        if fallback is not None:
            targets.append(fallback)
    for target in targets:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
