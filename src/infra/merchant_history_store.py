"""Durable append-only JSONL storage for merchant observations."""
from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile
import threading
from uuid import uuid4

from core.merchant_analytics import MAP_FAMILIES, MERCHANT_RARITY_NAMES, MerchantHistoryRecord
from infra.paths import application_path


class MerchantHistoryError(RuntimeError):
    pass


class MerchantHistoryConflict(MerchantHistoryError):
    pass


class _ProcessFileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._file = None
        self.error: str | None = None

    def acquire(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._file = self.path.open("a+b")
            if os.name == "nt":
                import msvcrt

                self._file.seek(0)
                if self._file.tell() == 0 and self.path.stat().st_size == 0:
                    self._file.write(b"0")
                    self._file.flush()
                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (OSError, IOError) as exc:
            self.error = str(exc)
            if self._file is not None:
                try:
                    self._file.close()
                except OSError:
                    pass
            self._file = None
            return False

    def close(self) -> None:
        if self._file is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        except (OSError, IOError):
            pass
        self._file.close()
        self._file = None


class MerchantHistoryStore:
    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path or Path(application_path()) / "merchant_history.jsonl")
        self._mutex = threading.RLock()
        self._records: dict[str, MerchantHistoryRecord] = {}
        self.error: str | None = None
        self._file_lock = _ProcessFileLock(self.path.with_suffix(self.path.suffix + ".lock"))
        self.writable = self._file_lock.acquire()
        if not self.writable:
            detail = self._file_lock.error
            self.error = (
                f"History is read-only: {detail}"
                if detail
                else "History is open in another BonkScanner instance."
            )
        self._load()

    def close(self) -> None:
        self._file_lock.close()

    def records(self) -> tuple[MerchantHistoryRecord, ...]:
        with self._mutex:
            return tuple(self._records.values())

    def append(self, record: MerchantHistoryRecord) -> bool:
        with self._mutex:
            existing = self._records.get(record.merchant_id)
            if existing is not None:
                if existing == record:
                    return False
                raise MerchantHistoryConflict(
                    f"Merchant {record.merchant_id} has a conflicting saved observation."
                )
            self._require_writable()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(asdict(record), ensure_ascii=False, separators=(",", ":")) + "\n"
            try:
                with self.path.open("a", encoding="utf-8", newline="") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
            except OSError as exc:
                self.writable = False
                self.error = f"History could not be written: {exc}"
                raise MerchantHistoryError(self.error) from exc
            self._records[record.merchant_id] = record
            return True

    def clear(self) -> None:
        with self._mutex:
            self._require_writable()
            self._atomic_write("")
            self._records.clear()

    def export_json(self, destination: str | os.PathLike[str]) -> None:
        target = Path(destination)
        if target.resolve() == self.path.resolve():
            raise MerchantHistoryError("Export destination cannot replace the history file.")
        payload = json.dumps(
            {"v": 1, "merchants": [asdict(record) for record in self.records()]},
            ensure_ascii=False,
            indent=2,
        ) + "\n"
        self._atomic_write(payload, path=target)

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = self.path.read_bytes()
        except OSError as exc:
            self.writable = False
            self.error = f"History could not be read: {exc}"
            return
        lines = raw.splitlines(keepends=True)
        valid_bytes = bytearray()
        for index, raw_line in enumerate(lines):
            has_newline = raw_line.endswith((b"\n", b"\r"))
            try:
                payload = json.loads(raw_line.decode("utf-8"))
                record = self._record_from_payload(payload)
            except Exception as exc:
                if index == len(lines) - 1 and not has_newline and self.writable:
                    try:
                        self._preserve_broken_tail(raw_line)
                        self._atomic_write_bytes(bytes(valid_bytes))
                    except OSError as repair_exc:
                        self.writable = False
                        self.error = f"History tail could not be repaired: {repair_exc}"
                    return
                self.writable = False
                self.error = f"History contains invalid data at line {index + 1}: {exc}"
                return
            existing = self._records.get(record.merchant_id)
            if existing is not None and existing != record:
                self.writable = False
                self.error = f"History contains conflicting merchant {record.merchant_id}."
                return
            self._records.setdefault(record.merchant_id, record)
            valid_bytes.extend(raw_line)
        if raw and lines and not lines[-1].endswith((b"\n", b"\r")) and self.writable:
            try:
                with self.path.open("ab") as stream:
                    stream.write(b"\n")
                    stream.flush()
                    os.fsync(stream.fileno())
            except OSError as exc:
                self.writable = False
                self.error = f"History newline could not be repaired: {exc}"

    @staticmethod
    def _record_from_payload(payload) -> MerchantHistoryRecord:
        if not isinstance(payload, dict) or payload.get("v") != 1:
            raise ValueError("unsupported merchant history version")
        family = payload.get("map_family")
        if family is not None and family not in MAP_FAMILIES:
            raise ValueError("invalid map_family")
        stage = int(payload["stage"])
        if not 1 <= stage <= 4:
            raise ValueError("invalid stage")
        rarity = str(payload["merchant_rarity"])
        if rarity not in MERCHANT_RARITY_NAMES:
            raise ValueError("invalid merchant_rarity")
        item_ids = tuple(int(value) for value in payload["item_ids"])
        if len(item_ids) != 3 or any(value < 0 for value in item_ids):
            raise ValueError("item_ids must contain three non-negative IDs")
        map_id = str(payload["map_id"])
        merchant_id = str(payload["merchant_id"])
        if len(map_id) != 32 or len(merchant_id) != 32:
            raise ValueError("invalid stable ID")
        return MerchantHistoryRecord(
            map_id=map_id,
            merchant_id=merchant_id,
            map_family=family,
            stage=stage,
            merchant_rarity=rarity,
            item_ids=item_ids,
        )

    def _preserve_broken_tail(self, tail: bytes) -> None:
        if not tail:
            return
        recovery = self.path.with_name(f"{self.path.name}.broken-{uuid4().hex[:8]}")
        self._atomic_write_bytes(tail, path=recovery)

    def _require_writable(self) -> None:
        if not self.writable:
            raise MerchantHistoryError(self.error or "History is read-only.")

    def _atomic_write(self, payload: str, *, path: Path | None = None) -> None:
        self._atomic_write_bytes(payload.encode("utf-8"), path=path)

    def _atomic_write_bytes(self, payload: bytes, *, path: Path | None = None) -> None:
        target = path or self.path
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, target)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
