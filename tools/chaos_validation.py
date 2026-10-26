from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import struct
import time
from typing import Any


# Application imports and writable diagnostic output have separate roots.
REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT = REPO_ROOT / "src"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "runtime" / "diagnostics" / "chaos"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.tracker.live_run import LiveRunTracker
from core.stats.formats import PlayerStatFormat
from core.stats.types import format_player_stat_delta
from infra.memory.player_stats_client import PlayerStatsClient


def _modifier_record(modifier: Any) -> dict[str, Any]:
    value_format = getattr(modifier, "value_format", PlayerStatFormat.FLAT)
    return {
        "stat_id": int(getattr(modifier, "stat_id", -1)),
        "object_ptr": int(getattr(modifier, "object_ptr", 0) or 0),
        "modify_type": getattr(modifier, "modify_type", None),
        "value_f32_hex": struct.pack("<f", float(getattr(modifier, "value", 0.0))).hex(),
        "label": str(getattr(modifier, "label", "")),
        "value": float(getattr(modifier, "value", 0.0)),
        "value_format": value_format.value,
    }


def _modifier_records(modifiers: dict[int, tuple[Any, ...]]) -> dict[str, list[dict[str, Any]]]:
    return {
        str(stat_id): [_modifier_record(modifier) for modifier in values]
        for stat_id, values in sorted(modifiers.items())
    }


def _modifier_totals(modifiers: dict[int, tuple[Any, ...]]) -> dict[int, float]:
    return {
        int(stat_id): sum(float(getattr(modifier, "value", 0.0)) for modifier in values)
        for stat_id, values in modifiers.items()
    }


def _player_stat_records(stats: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        label: {
            "value": getattr(stat, "value", None),
            "display": getattr(stat, "display_value", "--"),
        }
        for label, stat in stats.items()
    }


def _snapshot_records(tracker: LiveRunTracker) -> list[dict[str, Any]]:
    snapshot = tracker.chaos_tome_snapshot()
    if snapshot is None:
        return []
    return [
        {
            "stat_id": stat.stat_id,
            "label": stat.label,
            "value": stat.value,
            "display": stat.display_delta,
            "rolls": stat.rolls,
            "value_format": stat.value_format.value,
        }
        for stat in snapshot.stats
    ]


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_status(path: Path, **fields: Any) -> None:
    _write_json(path, {"updated_at": datetime.now().isoformat(timespec="seconds"), **fields})


def _build_report(
    *,
    run_id: str,
    start_level: int,
    end_level: int,
    start_modifiers: dict[int, tuple[Any, ...]],
    end_modifiers: dict[int, tuple[Any, ...]],
    start_stats: dict[str, Any],
    end_stats: dict[str, Any],
    tracker: LiveRunTracker,
    samples: int,
    read_errors: int,
    start_tracked: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    start_totals = _modifier_totals(start_modifiers)
    end_totals = _modifier_totals(end_modifiers)
    tracked = {record["stat_id"]: record for record in _snapshot_records(tracker)}
    baseline = {record["stat_id"]: record for record in (start_tracked or ())}
    stat_ids = sorted(set(start_totals) | set(end_totals) | set(tracked))
    rows = []

    for stat_id in stat_ids:
        label, value_format = PlayerStatsClient._resolve_stat_display(stat_id)
        raw_delta = end_totals.get(stat_id, 0.0) - start_totals.get(stat_id, 0.0)
        tracked_record = tracked.get(stat_id)
        tracked_delta = (float(tracked_record["value"]) if tracked_record else 0.0) - float(baseline.get(stat_id, {}).get("value", 0.0))
        difference = raw_delta - tracked_delta
        rows.append(
            {
                "stat_id": stat_id,
                "label": label,
                "raw_modifier_delta": raw_delta,
                "raw_display": format_player_stat_delta(raw_delta, value_format),
                "tracked_delta": tracked_delta,
                "tracked_display": format_player_stat_delta(tracked_delta, value_format),
                "difference": difference,
                "difference_display": format_player_stat_delta(difference, value_format),
                "tracked_rolls": (int(tracked_record["rolls"]) if tracked_record else 0) - int(baseline.get(stat_id, {}).get("rolls", 0)),
            }
        )

    start_player = _player_stat_records(start_stats)
    end_player = _player_stat_records(end_stats)
    player_rows = []
    for label in start_player:
        start_value = start_player[label]["value"]
        end_value = end_player.get(label, {}).get("value")
        if start_value is None or end_value is None:
            delta = None
        else:
            delta = float(end_value) - float(start_value)
        player_rows.append(
            {
                "label": label,
                "start": start_value,
                "end": end_value,
                "delta": delta,
                "start_display": start_player[label]["display"],
                "end_display": end_player.get(label, {}).get("display", "--"),
            }
        )

    tracked_rolls = sum(int(record["rolls"]) for record in tracked.values()) - sum(int(record["rolls"]) for record in baseline.values())
    expected_rolls = max(end_level - start_level, 0)
    mismatches = [row for row in rows if abs(float(row["difference"])) > 0.003]
    return {
        "run_id": run_id,
        "start_level": start_level,
        "end_level": end_level,
        "expected_rolls": expected_rolls,
        "tracked_rolls": tracked_rolls,
        "roll_difference": expected_rolls - tracked_rolls,
        "samples": samples,
        "read_errors": read_errors,
        "baseline_tracked": start_tracked or [],
        "comparison_scope": "raw shared permanent modifiers vs attributed Chaos; other sources may contribute to raw deltas",
        "modifier_comparison": rows,
        "mismatch_count": len(mismatches),
        "player_stats": player_rows,
    }


def _report_text(report: dict[str, Any]) -> str:
    lines = [
        f"Chaos validation: {report['run_id']}",
        f"Levels: {report['start_level']} -> {report['end_level']}",
        f"Expected rolls: {report['expected_rolls']}",
        f"Tracked rolls: {report['tracked_rolls']}",
        f"Roll difference: {report['roll_difference']}",
        f"Samples: {report['samples']}; read errors: {report['read_errors']}",
        "",
        "Permanent modifier comparison:",
    ]
    for row in report["modifier_comparison"]:
        marker = "OK" if abs(float(row["difference"])) <= 0.003 else "MISMATCH"
        lines.append(
            f"[{marker}] {row['label']}: raw {row['raw_display']}, "
            f"tracked {row['tracked_display']}, difference {row['difference_display']}, "
            f"rolls {row['tracked_rolls']}"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture a live Chaos Tome validation run.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--process", default="Megabonk.exe")
    parser.add_argument("--start-level", type=int, default=0)
    parser.add_argument("--start-current", action="store_true")
    parser.add_argument("--target-level", type=int, default=150)
    parser.add_argument("--interval-ms", type=int, default=250)
    parser.add_argument("--settle-samples", type=int, default=8)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--duration-seconds", type=float, default=0, help="Optional bounded capture duration.")
    parser.add_argument("--shared-sources", action="store_true", help="Use production Dice/Chaos source attribution and log pointers.")
    args = parser.parse_args()

    output_dir = Path(args.output_dir) / args.run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    status_path = output_dir / "status.json"
    trace_path = output_dir / "trace.jsonl"
    stop_path = output_dir / "STOP"
    if trace_path.exists():
        parser.error(f"Capture already exists: {trace_path}")
    _write_status(status_path, state="waiting", start_level=args.start_level, target_level=args.target_level)

    tracker = LiveRunTracker()
    started = False
    start_modifiers: dict[int, tuple[Any, ...]] = {}
    end_modifiers: dict[int, tuple[Any, ...]] = {}
    start_stats: dict[str, Any] = {}
    end_stats: dict[str, Any] = {}
    final_level = args.start_level
    samples = 0
    read_errors = 0
    settle_remaining = args.settle_samples
    start_tracked = []
    previous_objects = {}
    initial_owner = None
    deadline = time.monotonic() + args.duration_seconds if args.duration_seconds > 0 else None
    finish_reason = "target_level"

    try:
        with PlayerStatsClient(args.process) as client, trace_path.open("a", encoding="utf-8") as trace:
            while True:
                if stop_path.exists() or (deadline is not None and time.monotonic() >= deadline):
                    finish_reason = "stop_file" if stop_path.exists() else "duration"
                    break

                captured_at = time.time()
                read_started = time.perf_counter()
                try:
                    owner_stats = client.resolve_owner_stats()
                    if initial_owner is not None and owner_stats != initial_owner:
                        finish_reason = "owner_changed"
                        break
                    level = client.get_chaos_tome_level(owner_stats)
                    cached_level, cached_modifiers = client.get_chaos_tracking_state(owner_stats)
                    modifiers = client.get_permanent_stat_modifiers(owner_stats)
                    player_stats = client.get_player_stats(owner_stats)
                    passive = client.get_character_passive_reading(owner_stats, permanent_modifiers=cached_modifiers)
                    shrine = client.get_charge_shrine_tracking_state() if args.shared_sources else None
                    level_after = client.get_chaos_tome_level(owner_stats)
                except Exception as exc:
                    read_errors += 1
                    trace.write(json.dumps({"captured_at": captured_at, "error": repr(exc)}) + "\n")
                    trace.flush()
                    _write_status(status_path, state="read_error", error=repr(exc), read_errors=read_errors)
                    time.sleep(args.interval_ms / 1000)
                    continue

                if not started:
                    effective_level = 0 if level is None and args.start_level == 0 else level
                    if args.start_current:
                        if effective_level is None:
                            _write_status(status_path, state="waiting", observed_level=level, read_errors=read_errors)
                            time.sleep(args.interval_ms / 1000)
                            continue
                        args.start_level = int(effective_level)
                    elif effective_level != args.start_level:
                        _write_status(status_path, state="waiting", observed_level=level, read_errors=read_errors)
                        time.sleep(args.interval_ms / 1000)
                        continue
                    started = True
                    initial_owner = owner_stats
                    start_modifiers = modifiers
                    start_stats = player_stats
                    if args.shared_sources:
                        tracker.update_charge_shrines(shrine, wrench_stacks=None)
                        tracker.update_permanent_sources(passive, chaos_level=cached_level, permanent_modifiers=cached_modifiers)
                    else:
                        tracker.update_chaos_tome(chaos_level=effective_level, permanent_modifiers=modifiers)
                    start_tracked = _snapshot_records(tracker)
                    _write_status(status_path, state="tracking", observed_level=effective_level, samples=0)
                else:
                    if args.shared_sources:
                        tracker.update_charge_shrines(shrine, wrench_stacks=None)
                        tracker.update_permanent_sources(passive, chaos_level=cached_level, permanent_modifiers=cached_modifiers)
                    else:
                        tracker.update_chaos_tome(chaos_level=level, permanent_modifiers=modifiers)

                samples += 1
                end_modifiers = modifiers
                end_stats = player_stats
                if level is not None:
                    final_level = int(level)
                objects = {int(m.object_ptr): m for values in modifiers.values() for m in values if m.object_ptr}
                cached_objects = {int(m.object_ptr): m for values in cached_modifiers.values() for m in values if m.object_ptr}
                signature = lambda m: (m.stat_id, m.modify_type, m.value)
                new_objects = [_modifier_record(m) for ptr, m in objects.items() if ptr not in previous_objects]
                changed_objects = [
                    {"before": _modifier_record(previous_objects[ptr]), "after": _modifier_record(m)}
                    for ptr, m in objects.items()
                    if ptr in previous_objects and signature(m) != signature(previous_objects[ptr])
                ]
                cache_differences = [
                    ptr for ptr in objects.keys() | cached_objects.keys()
                    if ptr not in objects or ptr not in cached_objects or signature(objects[ptr]) != signature(cached_objects[ptr])
                ]
                dice = tracker.character_passive_snapshot()
                trace.write(
                    json.dumps(
                        {
                            "sample": samples,
                            "captured_at": captured_at,
                            "chaos_level": level,
                            "chaos_level_after_read": level_after,
                            "cached_chaos_level": cached_level,
                            "level_changed_during_read": level != level_after,
                            "process_identity": client.memory.process_identity(),
                            "owner_stats": owner_stats,
                            "character": passive.character_name,
                            "dice_budget": passive.gamba_current_level,
                            "dice_tracked": {str(e.stat_id): e.count for e in dice.effects} if dice else {},
                            "dice_ambiguous": dice.ambiguous if dice else None,
                            "read_elapsed_ms": (time.perf_counter() - read_started) * 1000,
                            "raw_object_count": len(objects),
                            "new_objects": new_objects,
                            "changed_objects": changed_objects,
                            "removed_objects": sorted(previous_objects.keys() - objects.keys()),
                            "cached_modifiers": _modifier_records(cached_modifiers),
                            "cache_difference_ptrs": cache_differences,
                            "baseline_sample": samples == 1,
                            "available_rolls": tracker._chaos_available_rolls,
                            "tracked": _snapshot_records(tracker),
                            "modifiers": _modifier_records(modifiers),
                            "player_stats": _player_stat_records(player_stats),
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
                trace.flush()
                previous_objects = objects

                if level is not None and level >= args.target_level:
                    settle_remaining -= 1
                    if settle_remaining <= 0:
                        break
                else:
                    settle_remaining = args.settle_samples

                _write_status(
                    status_path,
                    state="tracking",
                    observed_level=level,
                    samples=samples,
                    tracked_rolls=sum(record["rolls"] for record in _snapshot_records(tracker)),
                    available_rolls=tracker._chaos_available_rolls,
                    read_errors=read_errors,
                    new_objects=len(new_objects),
                    changed_objects=len(changed_objects),
                    raw_object_count=len(objects),
                    cache_difference_count=len(cache_differences),
                    character=passive.character_name,
                    dice_budget=passive.gamba_current_level,
                    read_elapsed_ms=(time.perf_counter() - read_started) * 1000,
                )
                time.sleep(args.interval_ms / 1000)
    except KeyboardInterrupt:
        _write_status(status_path, state="interrupted", samples=samples, read_errors=read_errors)
        return 130
    except Exception as exc:
        _write_status(status_path, state="failed", error=repr(exc), samples=samples, read_errors=read_errors)
        raise

    report = _build_report(
        run_id=args.run_id,
        start_level=args.start_level,
        end_level=final_level,
        start_modifiers=start_modifiers,
        end_modifiers=end_modifiers,
        start_stats=start_stats,
        end_stats=end_stats,
        tracker=tracker,
        samples=samples,
        read_errors=read_errors,
        start_tracked=start_tracked,
    )
    report["finish_reason"] = finish_reason
    report["shared_sources"] = args.shared_sources
    _write_json(output_dir / "report.json", report)
    (output_dir / "report.txt").write_text(_report_text(report), encoding="utf-8")
    _write_status(
        status_path,
        state="complete",
        observed_level=final_level,
        samples=samples,
        tracked_rolls=report["tracked_rolls"],
        expected_rolls=report["expected_rolls"],
        mismatch_count=report["mismatch_count"],
        read_errors=read_errors,
        finish_reason=finish_reason,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
