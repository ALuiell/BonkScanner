"""Decode the bundled example recording used by the Quick Guide."""
import gzip
import json
from dataclasses import dataclass
from pathlib import Path

from infra.vod_storage import LoadedVod, VodMetadata, VodSnapshot, _record_to_snapshot


@dataclass(frozen=True)
class RunExample:
    character: str
    kill_count: int
    snapshots: tuple[VodSnapshot, ...]
    live_snapshot: VodSnapshot
    vod: LoadedVod


def read_run_example(asset_path: str | Path) -> RunExample:
    with gzip.open(asset_path, "rt", encoding="utf-8") as source:
        sample = json.load(source)
    records = sample["snapshots"]
    pool = {}
    snapshots = tuple(_record_to_snapshot(record, pool) for record in records)
    # The first map retains a usable chest denominator and loot counters.
    live_snapshot = next(
        snapshot
        for record, snapshot in zip(reversed(records), reversed(snapshots), strict=True)
        if snapshot.stage_index == 0 and not record.get("loot_reconstruction")
        and snapshot.loot_actual and snapshot.loot_expected
    )
    character, kill_count = sample["character"], sample["kill_count"]
    metadata = VodMetadata(
        Path("guide-example.jsonl"), f"{character} · {kill_count:,}", "", 10,
        snapshots[-1].elapsed_seconds, len(snapshots), character_name=character,
    )
    return RunExample(character, kill_count, snapshots, live_snapshot, LoadedVod(metadata, snapshots))
