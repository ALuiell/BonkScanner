"""Presentation preferences and a small read-only cache; no lifetime collection."""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
import threading

from app import config
from core.roll_analysis_view import normalize_selected_stats
from infra.roll_recording import RecordedRolls, file_signature, read_recorded_rolls

PREFERENCES_KEY = "ROLL_ANALYTICS_VIEW"


def view_preferences() -> tuple[tuple[int, ...], bool]:
    value = config.user_config.get(PREFERENCES_KEY, {})
    if not isinstance(value, dict):
        return (), False
    return normalize_selected_stats(value.get("selected_stats")), value.get("show_expected") is True


def save_view_preferences(selected_stats, show_expected: bool):
    value = {
        "selected_stats": list(normalize_selected_stats(selected_stats)),
        "show_expected": bool(show_expected),
    }
    return config.update_config(lambda candidate: candidate.__setitem__(PREFERENCES_KEY, value))


class RollRecordingCache:
    """At most four tiny two-source summaries, never full VODs or game objects."""

    def __init__(self, *, capacity: int = 4, reader=read_recorded_rolls):
        self._capacity = max(1, capacity)
        self._reader = reader
        self._lock = threading.Lock()
        self._entries: OrderedDict[Path, RecordedRolls] = OrderedDict()

    def load(self, path, *, cancelled=None) -> RecordedRolls:
        path = Path(path).resolve()
        signature = file_signature(path)
        with self._lock:
            value = self._entries.get(path)
            if value is not None and value.signature == signature:
                self._entries.move_to_end(path)
                return value
        value = self._reader(path, cancelled=cancelled)
        if cancelled is not None and cancelled():
            raise InterruptedError("Recording load cancelled")
        with self._lock:
            self._entries[path] = value
            self._entries.move_to_end(path)
            while len(self._entries) > self._capacity:
                self._entries.popitem(last=False)
        return value
