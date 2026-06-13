from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from live_run_tracker import LiveRunTracker
from player_stats import PlayerStatFormat, PlayerStatsClient, format_player_stat_delta


def _modifier_record(modifier: Any) -> dict[str, Any]:
    value_format = getattr(modifier, "value_format", PlayerStatFormat.FLAT)
    return {
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
) -> dict[str, Any]:
    start_totals = _modifier_totals(start_modifiers)
    end_totals = _modifier_totals(end_modifiers)
    tracked = {record["stat_id"]: record for record in _snapshot_records(tracker)}
    stat_ids = sorted(set(start_totals) | set(end_totals) | set(tracked))
    rows = []

    for stat_id in stat_ids:
        label, value_format = PlayerStatsClient._resolve_stat_display(stat_id)
        raw_delta = end_totals.get(stat_id, 0.0) - start_totals.get(stat_id, 0.0)
        tracked_record = tracked.get(stat_id)
        tracked_delta = float(tracked_record["value"]) if tracked_record else 0.0
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
                "tracked_rolls": int(tracked_record["rolls"]) if tracked_record else 0,
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

    tracked_rolls = sum(int(record["rolls"]) for record in tracked.values())
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
    parser.add_argument("--output-dir", default=str(ROOT / "chaos_validation_runs"))
    args = parser.parse_args()

    output_dir = Path(args.output_dir) / args.run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    status_path = output_dir / "status.json"
    trace_path = output_dir / "trace.jsonl"
    stop_path = output_dir / "STOP"
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

    try:
        with PlayerStatsClient(args.process) as client, trace_path.open("a", encoding="utf-8") as trace:
            while True:
                if stop_path.exists():
                    _write_status(status_path, state="stopped", samples=samples, read_errors=read_errors)
                    return 2

                captured_at = time.time()
                try:
                    owner_stats = client.resolve_owner_stats()
                    level = client.get_chaos_tome_level(owner_stats)
                    modifiers = client.get_permanent_stat_modifiers(owner_stats)
                    player_stats = client.get_player_stats(owner_stats)
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
                    start_modifiers = modifiers
                    start_stats = player_stats
                    tracker.update_chaos_tome(chaos_level=effective_level, permanent_modifiers=modifiers)
                    _write_status(status_path, state="tracking", observed_level=effective_level, samples=0)
                else:
                    tracker.update_chaos_tome(chaos_level=level, permanent_modifiers=modifiers)

                samples += 1
                end_modifiers = modifiers
                end_stats = player_stats
                if level is not None:
                    final_level = int(level)
                trace.write(
                    json.dumps(
                        {
                            "sample": samples,
                            "captured_at": captured_at,
                            "chaos_level": level,
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
    )
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
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
