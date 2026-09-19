"""Application service for asynchronous Shady Guy history writes."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import threading

from core.map_markers import MerchantStockCapture
from core.merchant_analytics import (
    MERCHANT_RARITY_NAMES,
    MerchantHistoryRecord,
    aggregate_merchant_history,
    merchant_family_from_context,
    stable_history_ids,
)
from infra.merchant_history_store import MerchantHistoryStore


@dataclass(frozen=True, slots=True)
class MerchantAnalyticsStatus:
    session_recorded: int
    total_recorded: int
    error: str | None
    writable: bool
    revision: int


class MerchantAnalyticsService:
    def __init__(self, store: MerchantHistoryStore | None = None) -> None:
        self.store = store or MerchantHistoryStore()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="merchant-history")
        self._lock = threading.RLock()
        self._known = {record.merchant_id: record for record in self.store.records()}
        self._pending: set[str] = set()
        self._session_recorded = 0
        self._revision = 0
        self._generation = 0
        self._closed = False

    def collection_available(self) -> bool:
        with self._lock:
            return not self._closed and bool(self.store.writable)

    def status(self) -> MerchantAnalyticsStatus:
        with self._lock:
            return MerchantAnalyticsStatus(
                session_recorded=self._session_recorded,
                total_recorded=len(self._known),
                error=self.store.error,
                writable=self.store.writable,
                revision=self._revision,
            )

    def snapshot(self, **filters):
        with self._lock:
            records = tuple(self._known.values())
        return aggregate_merchant_history(records, **filters)

    def record_confirmed_capture(self, capture: MerchantStockCapture, runtime_snapshot) -> bool:
        with self._lock:
            if self._closed or not self.store.writable:
                return False
        if len(capture.items) != 3 or runtime_snapshot is None:
            return False
        latest_snapshot = getattr(runtime_snapshot, "latest_snapshot", None)
        if latest_snapshot is None:
            return False
        capture_stage_ptr = int(getattr(capture, "stage_ptr", 0) or 0)
        runtime_stage_ptr = int(getattr(latest_snapshot, "stage_ptr", 0) or 0)
        if not capture_stage_ptr or capture_stage_ptr != runtime_stage_ptr:
            return False
        capture_raw_stage = getattr(capture, "raw_stage_index", None)
        runtime_raw_stage = getattr(latest_snapshot, "stage_index", None)
        if (
            capture_raw_stage is None
            or runtime_raw_stage is None
            or int(capture_raw_stage) != int(runtime_raw_stage)
        ):
            return False
        capture_map_seed = getattr(capture, "map_seed", None)
        runtime_map_seed = getattr(latest_snapshot, "map_seed", None)
        if (
            capture_map_seed is None
            or runtime_map_seed is None
            or int(capture_map_seed) != int(runtime_map_seed)
        ):
            return False
        stage = int(getattr(runtime_snapshot, "current_stage_index", 0) or 0)
        if not 1 <= stage <= 4:
            return False
        map_family = merchant_family_from_context(
            getattr(runtime_snapshot, "powerup_map_context", None)
        )
        if map_family is None:
            return False
        map_id, merchant_id = stable_history_ids(
            capture.map_id,
            capture.merchant_object_ptr,
            game_process_identity=str(
                getattr(capture, "game_process_identity", "") or ""
            ),
            map_seed=int(capture_map_seed),
            stage=stage,
        )
        rarity = int(capture.merchant_rarity)
        if not 0 <= rarity < len(MERCHANT_RARITY_NAMES):
            return False
        record = MerchantHistoryRecord(
            map_id=map_id,
            merchant_id=merchant_id,
            map_family=map_family,
            stage=stage,
            merchant_rarity=MERCHANT_RARITY_NAMES[rarity],
            item_ids=tuple(int(item.item_id) for item in capture.items),
        )
        with self._lock:
            if merchant_id in self._pending:
                return False
            existing = self._known.get(merchant_id)
            if existing == record:
                return False
            if existing is not None:
                return False
            self._pending.add(merchant_id)
            generation = self._generation
            try:
                self._executor.submit(self._append, record, generation)
            except RuntimeError:
                self._pending.discard(merchant_id)
                return False
        return True

    def clear(self) -> None:
        with self._lock:
            self._generation += 1
            self._pending.clear()
        future = self._executor.submit(self.store.clear)
        future.result()
        with self._lock:
            self._known.clear()
            self._revision += 1

    def export_json(self, destination) -> None:
        future = self._executor.submit(self.store.export_json, destination)
        future.result()

    def close(self, *, wait: bool = True) -> None:
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=wait, cancel_futures=False)
        self.store.close()

    def _append(self, record: MerchantHistoryRecord, generation: int) -> None:
        try:
            with self._lock:
                if generation != self._generation:
                    return
            appended = self.store.append(record)
            if appended:
                with self._lock:
                    if generation == self._generation:
                        self._known[record.merchant_id] = record
                        self._session_recorded += 1
                        self._revision += 1
        except Exception as exc:
            self.store.error = str(exc)
            self.store.writable = False
        finally:
            with self._lock:
                self._pending.discard(record.merchant_id)
