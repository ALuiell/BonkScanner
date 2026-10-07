"""Atomic compact lifetime totals and reconnect checkpoints in one transaction."""
from __future__ import annotations

import copy
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import tempfile
import threading

from core.roll_analytics import ROLL_SOURCES, ROLL_STAT_IDS, aggregate_roll_counts
from infra.merchant_history_store import _ProcessFileLock
from infra.paths import application_path


def validate_roll_history(payload) -> None:
    if not isinstance(payload, dict) or type(payload.get("v")) is not int or payload["v"] != 1:
        raise ValueError("Unsupported roll history format")
    totals, checkpoints = payload.get("totals"), payload.get("checkpoints")
    if not isinstance(totals, dict) or set(totals) != set(ROLL_SOURCES):
        raise ValueError("Invalid roll history sources")
    if not isinstance(checkpoints, dict):
        raise ValueError("Invalid roll checkpoints")
    def validate_counts(counts):
        if not isinstance(counts, dict):
            raise ValueError("Invalid stat counts")
        for key, value in counts.items():
            if key not in {str(i) for i in ROLL_STAT_IDS} or type(value) is not int or value < 0:
                raise ValueError("Invalid stat count")
    for counts in totals.values():
        validate_counts(counts)
    for scope, sources in checkpoints.items():
        if (len(scope) != 64 or any(c not in "0123456789abcdef" for c in scope)
                or not isinstance(sources, dict) or set(sources) - set(ROLL_SOURCES)):
            raise ValueError("Invalid roll checkpoint identity")
        for counts in sources.values():
            validate_counts(counts)
    lifetimes = payload.get("lifetimes", {})
    if not isinstance(lifetimes, dict):
        raise ValueError("Invalid lifetime identities")
    for scope, context in lifetimes.items():
        if (len(scope) != 64 or any(c not in "0123456789abcdef" for c in scope)
                or not isinstance(context, dict) or not isinstance(context.get("run_id"), str)
                or type(context.get("generation")) is not int or context["generation"] < 0):
            raise ValueError("Invalid lifetime identity")
        timer = context.get("timer")
        if timer is not None and (type(timer) not in (int, float) or not math.isfinite(timer) or timer < 0):
            raise ValueError("Invalid lifetime timer")


class RollHistoryStore:
    def __init__(self, path=None) -> None:
        self.path = Path(path or Path(application_path()) / "roll_history.json")
        self._mutex = threading.RLock()
        self._data = {"v": 1, "totals": {source: {} for source in ROLL_SOURCES},
                      "checkpoints": {}, "lifetimes": {}}
        self.error = None
        self._file_lock = _ProcessFileLock(self.path.with_suffix(".json.lock"))
        self.writable = self._file_lock.acquire()
        if not self.writable:
            self.error = "Roll history is read-only: open in another instance or inaccessible."
        if self.path.exists():
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                validate_roll_history(payload)
                payload.setdefault("lifetimes", {})
                self._data = payload
            except (OSError, ValueError, TypeError, UnicodeError) as exc:
                self.writable = False
                self.error = f"Roll history could not be read: {exc}"

    def snapshot(self, source):
        with self._mutex:
            counts = {int(k): v for k, v in self._data["totals"][source].items()}
        return aggregate_roll_counts(source, counts)

    def observe(self, scope, observations, *, collecting, baseline_sources=frozenset(),
                run_id="", run_timer=None, run_reset=False):
        if set(observations) - set(ROLL_SOURCES):
            raise ValueError("Unknown roll source")
        validated = {source: {str(i): count for i, count in counts.items()}
                     for source, counts in observations.items()}
        validate_roll_history({"v": 1, "totals": {source: {} for source in ROLL_SOURCES},
                               "checkpoints": {scope: validated}})
        with self._mutex:
            if not self.writable:
                return 0, False
            lifetime = self._data["lifetimes"].get(scope)
            generation = lifetime["generation"] if lifetime else 0
            if lifetime and run_id and lifetime["run_id"] != run_id:
                if not run_reset and run_timer is None:
                    # A new scanner UUID alone cannot distinguish a restart
                    # from recycled game addresses. Wait for the shared clock.
                    return 0, None
                if run_reset or (lifetime.get("timer") is not None and run_timer + 1 < lifetime["timer"]):
                    generation += 1
            checkpoint_scope = (sha256(f"{scope}:{generation}".encode()).hexdigest()
                                if generation else scope)
            previous_sources = self._data["checkpoints"].get(checkpoint_scope, {})
            unchanged = all(source in previous_sources and all(
                count <= previous_sources[source].get(str(stat_id), 0)
                for stat_id, count in counts.items()
            ) for source, counts in observations.items())
            first_clock = bool(run_id and lifetime and lifetime.get("timer") is None
                               and run_timer is not None)
            if unchanged and not first_clock and (not run_id or lifetime and lifetime["run_id"] == run_id):
                return 0, False
            candidate = copy.deepcopy(self._data)
            if run_id:
                candidate["lifetimes"][scope] = {
                    "run_id": run_id, "generation": generation,
                    "timer": run_timer if run_timer is not None else lifetime.get("timer") if lifetime else None,
                }
            checkpoint = candidate["checkpoints"].setdefault(checkpoint_scope, {})
            added = 0
            for source, counts in observations.items():
                previous = checkpoint.setdefault(source, {})
                for stat_id, count in counts.items():
                    key = str(stat_id)
                    old = previous.get(key, 0)
                    if count <= old:
                        continue
                    if collecting and source not in baseline_sources:
                        delta = count - old
                        totals = candidate["totals"][source]
                        totals[key] = totals.get(key, 0) + delta
                        added += delta
                    previous[key] = count
            if candidate == self._data:
                return 0, False
            validate_roll_history(candidate)
            try:
                self._atomic_write(candidate, self.path)
            except OSError as exc:
                self.error = f"Roll history could not be saved: {exc}"
                self.writable = False
                return 0, False
            self._data = candidate
            return added, True

    @staticmethod
    def _atomic_write(payload, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
                name = stream.name
                json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
        finally:
            if name is not None:
                try:
                    os.unlink(name)
                except FileNotFoundError:
                    pass

    def export_json(self, destination):
        target = Path(destination)
        if target.resolve() == self.path.resolve():
            raise ValueError("Export cannot replace the active history file.")
        with self._mutex:
            payload = copy.deepcopy(self._data)
        self._atomic_write(payload, target)

    def clear(self):
        with self._mutex:
            if not self.writable:
                raise ValueError(self.error or "Roll history is read-only.")
            candidate = copy.deepcopy(self._data)
            candidate["totals"] = {source: {} for source in ROLL_SOURCES}
            # Retain reconnect checkpoints so opening the same run after a
            # clear cannot repopulate history from already observed rolls.
            self._atomic_write(candidate, self.path)
            self._data = candidate

    def close(self):
        self._file_lock.close()
