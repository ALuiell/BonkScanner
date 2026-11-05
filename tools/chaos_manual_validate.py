from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys
from typing import Any


# Application imports and writable diagnostic output have separate roots.
REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT = REPO_ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import config
from core.tracker.chaos import looks_like_chaos_value
from core.stats.formats import PlayerStatFormat
from core.stats.types import format_chaos_tome_stat_delta, format_player_stat_delta
from infra.memory.player_stats_client import PlayerStatsClient


OUTPUT_DIR = REPO_ROOT / "runtime" / "diagnostics" / "chaos"
CURRENT_BASELINE_PATH = OUTPUT_DIR / "current_chaos_baseline.json"
CURRENT_FINAL_PATH = OUTPUT_DIR / "current_chaos_final.json"

BOT_LABEL_TO_STAT_LABEL = {
    "HP": "Max HP",
    "Regen": "HP Regen",
    "Shield": "Shield",
    "Armor": "Armor",
    "Evasion": "Evasion",
    "Lifesteal": "Lifesteal",
    "Thorns": "Thorns",
    "DMG": "Damage",
    "Crit": "Crit Chance",
    "CritDMG": "Crit Damage",
    "AS": "Attack Speed",
    "Proj": "Projectile Count",
    "Size": "Size",
    "ProjSpeed": "Projectile Speed",
    "Dur": "Duration",
    "EliteDMG": "Damage to Elites",
    "KB": "Knockback",
    "MS": "Movement Speed",
    "Jumps": "Extra Jumps",
    "Luck": "Luck",
    "Diff": "Difficulty",
    "Pickup": "Pickup Range",
    "XP": "XP Gain",
    "Gold": "Gold Gain",
    "ESI": "Elite Spawn Increase",
    "PM": "Powerup Multiplier",
    "PDC": "Powerup Drop Chance",
}
STAT_LABEL_TO_BOT_LABEL = {value: key for key, value in BOT_LABEL_TO_STAT_LABEL.items()}
BOT_PART_RE = re.compile(r"^\s*(?P<abbr>[A-Za-z]+)\s+(?P<display>[+-].+?)\s*$")


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _modifier_record(modifier: Any) -> dict[str, Any]:
    value_format = getattr(modifier, "value_format", PlayerStatFormat.FLAT)
    return {
        "label": str(getattr(modifier, "label", "")),
        "value": float(getattr(modifier, "value", 0.0) or 0.0),
        "format": value_format.value,
        "display": getattr(modifier, "display_delta", "--"),
    }


def _modifier_records(modifiers: dict[int, tuple[Any, ...]]) -> dict[str, list[dict[str, Any]]]:
    return {
        str(int(stat_id)): [_modifier_record(modifier) for modifier in values]
        for stat_id, values in sorted((modifiers or {}).items())
    }


def _player_stat_records(stats: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for label, stat in stats.items():
        spec = getattr(stat, "spec", None)
        value_format = getattr(spec, "value_format", PlayerStatFormat.FLAT)
        stat_id = getattr(spec, "stat_id", None)
        records[label] = {
            "value": getattr(stat, "value", None),
            "display": getattr(stat, "display_value", "--"),
            "format": value_format.value,
            "stat_id": stat_id,
        }
    return records


def capture_snapshot(*, phase: str, process_name: str, bot_output: str | None) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{phase}_{_now_stamp()}.json"
    path = OUTPUT_DIR / filename

    with PlayerStatsClient(process_name) as client:
        owner_stats = client.resolve_owner_stats()
        stats = client.get_player_stats(owner_stats)
        chaos_level, permanent_modifiers = client.get_chaos_tracking_state(owner_stats)

    payload = {
        "captured_at": _now_iso(),
        "phase": phase,
        "owner_stats_hex": hex(owner_stats),
        "chaos_level": chaos_level,
        "stats": _player_stat_records(stats),
        "permanent_modifiers": _modifier_records(permanent_modifiers),
        "CHAOS_TOME_TRACKER_INTERVAL_MS": int(
            getattr(config, "CHAOS_TOME_TRACKER_INTERVAL_MS", 500)
        ),
    }
    if bot_output is not None:
        payload["bot_output"] = bot_output

    _write_json(path, payload)
    if phase == "baseline":
        _write_json(CURRENT_BASELINE_PATH, payload)
    elif phase == "final":
        _write_json(CURRENT_FINAL_PATH, payload)
    return path


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _modifiers_by_stat(snapshot: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    raw = snapshot.get("permanent_modifiers", {}) or {}
    return {
        int(stat_id): list(values or [])
        for stat_id, values in raw.items()
    }


def _stats_by_label(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return dict(snapshot.get("stats", {}) or {})


def _parse_bot_output(bot_output: str | None) -> dict[str, dict[str, Any]]:
    if not bot_output:
        return {}

    text = bot_output.strip()
    chaos_marker = re.search(r"Chaos Tome Lv\d+\s*:\s*", text)
    if chaos_marker:
        text = text[chaos_marker.end():].strip()
    elif ":" in text:
        text = text.rsplit(":", 1)[1].strip()
    if not text or text.lower() == "no rolls tracked yet.":
        return {}

    parsed: dict[str, dict[str, Any]] = {}
    for raw_part in text.split("|"):
        part = raw_part.strip()
        match = BOT_PART_RE.match(part)
        if not match:
            continue
        abbr = match.group("abbr")
        label = BOT_LABEL_TO_STAT_LABEL.get(abbr)
        if not label:
            continue
        parsed[label] = {
            "abbr": abbr,
            "label": label,
            "display": match.group("display").strip(),
            "raw_part": part,
        }
    return parsed


def _memory_delta_rows(
    baseline: dict[str, Any],
    final: dict[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    baseline_mods = _modifiers_by_stat(baseline)
    final_mods = _modifiers_by_stat(final)
    stat_ids = sorted(set(baseline_mods) | set(final_mods))
    rows: list[dict[str, Any]] = []
    total_rolls = 0

    for stat_id in stat_ids:
        label, value_format = PlayerStatsClient._resolve_stat_display(stat_id)
        old_values = [float(item.get("value", 0.0) or 0.0) for item in baseline_mods.get(stat_id, [])]
        new_values = [float(item.get("value", 0.0) or 0.0) for item in final_mods.get(stat_id, [])]
        recognized_values: list[float] = []
        matched_rolls = 0

        for index in range(min(len(old_values), len(new_values))):
            delta = new_values[index] - old_values[index]
            if abs(delta) <= 0.001:
                continue
            rolls = looks_like_chaos_value(stat_id, delta)
            if rolls > 0:
                matched_rolls += rolls
                recognized_values.append(delta)

        if len(new_values) > len(old_values):
            for index in range(len(old_values), len(new_values)):
                value = new_values[index]
                rolls = looks_like_chaos_value(stat_id, value)
                if rolls > 0:
                    matched_rolls += rolls
                    recognized_values.append(value)

        if matched_rolls <= 0:
            continue

        delta_value = sum(recognized_values)
        total_rolls += matched_rolls
        rows.append(
            {
                "stat_id": stat_id,
                "label": label,
                "abbr": STAT_LABEL_TO_BOT_LABEL.get(label, label),
                "matched_rolls": matched_rolls,
                "memory_delta_value": delta_value,
                "memory_delta_display": format_player_stat_delta(delta_value, value_format),
                "value_format": value_format.value,
            }
        )

    return rows, total_rolls


def _live_stat_rows(
    baseline: dict[str, Any],
    final: dict[str, Any],
    memory_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    baseline_stats = _stats_by_label(baseline)
    final_stats = _stats_by_label(final)
    memory_by_label = {row["label"]: row for row in memory_rows}
    mismatches: list[dict[str, Any]] = []

    for label, memory_row in memory_by_label.items():
        start_value = baseline_stats.get(label, {}).get("value")
        end_value = final_stats.get(label, {}).get("value")
        if start_value is None or end_value is None:
            continue
        live_delta = float(end_value) - float(start_value)
        memory_delta = float(memory_row["memory_delta_value"])
        if abs(live_delta - memory_delta) <= 0.01:
            continue
        mismatches.append(
            {
                "label": label,
                "live_delta": live_delta,
                "memory_delta": memory_delta,
                "live_display": final_stats.get(label, {}).get("display", "--"),
                "memory_display": memory_row["memory_delta_display"],
            }
        )
    return mismatches


def _parse_signed_display(display: str) -> tuple[float | None, str | None]:
    text = (display or "").strip()
    match = re.match(r"^(?P<sign>[+-]?)(?P<num>\d+(?:\.\d+)?)(?P<suffix>%?)$", text)
    if not match:
        return None, None
    value = float(match.group("num"))
    if match.group("sign") == "-":
        value = -value
    return value, match.group("suffix")


def _format_delta_for_bot_compare(label: str, value: float, value_format: PlayerStatFormat) -> str:
    return format_chaos_tome_stat_delta(label, value, value_format).lstrip("+")


def _bot_display_matches_memory(label: str, memory_display: str, bot_display: str | None) -> bool:
    if bot_display is None:
        return False
    memory_num, memory_suffix = _parse_signed_display(memory_display)
    bot_num, bot_suffix = _parse_signed_display(bot_display)
    if memory_num is None or bot_num is None or memory_suffix != bot_suffix:
        return memory_display == bot_display
    tolerance = 0.051 if label == "Pickup Range" else 0.51
    return abs(memory_num - bot_num) <= tolerance


def _absolute_bot_vs_memory_rows(
    final: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    final_mods = _modifiers_by_stat(final)
    bot_output = final.get("bot_output")
    parsed_bot = _parse_bot_output(bot_output)
    rows: list[dict[str, Any]] = []
    memory_labels: list[str] = []

    for stat_id, values in sorted(final_mods.items()):
        label, value_format = PlayerStatsClient._resolve_stat_display(stat_id)
        total = 0.0
        matched_rolls = 0
        for item in values:
            val = float(item.get("value", 0.0) or 0.0)
            rolls = looks_like_chaos_value(stat_id, val)
            if rolls > 0:
                total += val
                matched_rolls += rolls
        if matched_rolls <= 0:
            continue

        bot_entry = parsed_bot.get(label)
        memory_display = _format_delta_for_bot_compare(label, total, value_format)
        bot_display = bot_entry.get("display", "").lstrip("+") if bot_entry else None
        display_matches = _bot_display_matches_memory(label, memory_display, bot_display)
        rows.append(
            {
                "stat_id": stat_id,
                "label": label,
                "abbr": STAT_LABEL_TO_BOT_LABEL.get(label, label),
                "memory_total_value": total,
                "memory_display": memory_display,
                "bot_display": bot_display,
                "matched_rolls": matched_rolls,
                "display_matches": display_matches,
            }
        )
        memory_labels.append(label)

    missing_from_bot = sorted(label for label in memory_labels if label not in parsed_bot)
    extra_in_bot = sorted(label for label in parsed_bot if label not in set(memory_labels))
    return rows, missing_from_bot, extra_in_bot


def _baseline_plus_bot_vs_current_rows(
    baseline: dict[str, Any],
    final: dict[str, Any],
) -> list[dict[str, Any]]:
    baseline_stats = _stats_by_label(baseline)
    final_stats = _stats_by_label(final)
    parsed_bot = _parse_bot_output(final.get("bot_output"))
    rows: list[dict[str, Any]] = []

    for label, bot_entry in parsed_bot.items():
        start = baseline_stats.get(label)
        end = final_stats.get(label)
        if not start or not end:
            continue
        start_value = start.get("value")
        end_value = end.get("value")
        stat_format = start.get("format") or end.get("format") or PlayerStatFormat.FLAT.value
        if start_value is None or end_value is None:
            continue

        bot_number, bot_suffix = _parse_signed_display(str(bot_entry.get("display", "")))
        if bot_number is None:
            continue

        delta_raw = bot_number
        if label == "Pickup Range":
            delta_raw = bot_number / 9.0
        elif bot_suffix == "%":
            delta_raw = bot_number / 100.0
            if label == "Crit Damage":
                delta_raw = delta_raw / 2.0

        expected_final = float(start_value) + delta_raw
        actual_final = float(end_value)
        difference = actual_final - expected_final
        tolerance = 0.051 if label == "Pickup Range" else 0.011
        matches = abs(difference) <= tolerance
        rows.append(
            {
                "label": label,
                "baseline_value": float(start_value),
                "bot_display": bot_entry.get("display"),
                "expected_final_value": expected_final,
                "actual_final_value": actual_final,
                "difference": difference,
                "matches": matches,
                "format": stat_format,
            }
        )

    return rows


def build_comparison(
    *,
    baseline_path: Path,
    final_path: Path,
    comparison_path: Path | None = None,
) -> dict[str, Any]:
    baseline = _load_json(baseline_path)
    final = _load_json(final_path)
    bot_output = final.get("bot_output")
    parsed_bot = _parse_bot_output(bot_output)
    memory_rows, matched_rolls = _memory_delta_rows(baseline, final)
    absolute_rows, missing_labels_absolute, extra_labels_absolute = _absolute_bot_vs_memory_rows(final)
    level_delta = max(
        int(final.get("chaos_level") or 0) - int(baseline.get("chaos_level") or 0),
        0,
    )

    memory_labels = {row["label"] for row in memory_rows}
    missing_labels = sorted(label for label in memory_labels if label not in parsed_bot)
    live_stat_mismatches = _live_stat_rows(baseline, final, memory_rows)
    baseline_plus_bot_rows = _baseline_plus_bot_vs_current_rows(baseline, final)
    baseline_plus_bot_mismatches = [row for row in baseline_plus_bot_rows if not row["matches"]]
    bot_display_mismatches = [
        row["label"] for row in absolute_rows
        if row["bot_display"] is not None and not row["display_matches"]
    ]

    problem_types: list[str] = []
    if missing_labels:
        problem_types.append("missing stat ids in !chaos")
    if matched_rolls != level_delta:
        problem_types.append("matched rolls in memory != level delta")
    if missing_labels_absolute or extra_labels_absolute or bot_display_mismatches:
        problem_types.append("bot output does not match current memory totals")
    if live_stat_mismatches:
        problem_types.append("UI/live stats do not match memory modifiers")
    if baseline_plus_bot_mismatches:
        problem_types.append("baseline stats + bot output do not explain current stats")

    if (
        missing_labels
        or matched_rolls != level_delta
        or missing_labels_absolute
        or extra_labels_absolute
        or bot_display_mismatches
        or baseline_plus_bot_mismatches
    ):
        verdict = "tracker issue"
    elif live_stat_mismatches:
        verdict = "ui/game stat issue"
    else:
        verdict = "ok"

    result = {
        "generated_at": _now_iso(),
        "baseline_path": str(baseline_path),
        "final_path": str(final_path),
        "baseline_captured_at": baseline.get("captured_at"),
        "final_captured_at": final.get("captured_at"),
        "baseline_chaos_level": baseline.get("chaos_level"),
        "final_chaos_level": final.get("chaos_level"),
        "level_delta": level_delta,
        "matched_rolls_from_memory_delta": matched_rolls,
        "missing_from_bot_but_present_in_memory": missing_labels,
        "absolute_missing_from_bot_but_present_in_memory": missing_labels_absolute,
        "absolute_extra_in_bot_but_not_in_memory": extra_labels_absolute,
        "bot_display_mismatches_vs_memory": bot_display_mismatches,
        "bot_output": bot_output,
        "problem_types": problem_types,
        "verdict": verdict,
        "memory_rows": memory_rows,
        "absolute_bot_vs_memory_rows": absolute_rows,
        "bot_rows": list(parsed_bot.values()),
        "live_stat_mismatches": live_stat_mismatches,
        "baseline_plus_bot_vs_current_rows": baseline_plus_bot_rows,
        "baseline_plus_bot_mismatches": baseline_plus_bot_mismatches,
        "note": (
            "похоже на UI/game stat refresh bug, не обязательно проблема chaos tracker"
            if live_stat_mismatches
            else None
        ),
    }

    if comparison_path is not None:
        _write_json(comparison_path, result)

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Manual Chaos Tome validation helper.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture_parser = subparsers.add_parser("capture")
    capture_parser.add_argument("--phase", choices=("baseline", "final"), required=True)
    capture_parser.add_argument("--process", default="Megabonk.exe")
    capture_parser.add_argument("--bot-output")

    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("--baseline", default=str(CURRENT_BASELINE_PATH))
    compare_parser.add_argument("--final", default=str(CURRENT_FINAL_PATH))
    compare_parser.add_argument("--output")

    args = parser.parse_args()

    if args.command == "capture":
        path = capture_snapshot(
            phase=args.phase,
            process_name=args.process,
            bot_output=args.bot_output,
        )
        print(str(path))
        return 0

    comparison_path = Path(args.output) if args.output else None
    result = build_comparison(
        baseline_path=Path(args.baseline),
        final_path=Path(args.final),
        comparison_path=comparison_path,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
