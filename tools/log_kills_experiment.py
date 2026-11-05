from __future__ import annotations

import argparse
import csv
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
import sys
import time

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = REPO_ROOT / "runtime" / "diagnostics" / "kps" / "kills_experiment.csv"
sys.path.insert(0, str(REPO_ROOT / "src"))

from app import config
from core.tracker.live_run import LiveRunTracker
from infra.memory.reader import MemoryReadError, ModuleNotFoundError, ProcessNotFoundError
from infra.memory.player_stats_client import PlayerStatsClient


class UiKpsMonitor:
    def __init__(self) -> None:
        self.baseline: tuple[float, int] | None = None

    def observe(self, game_time_seconds: float | None, current_kills: int | None) -> dict[str, float | int | str | None]:
        if game_time_seconds is None or current_kills is None:
            return {
                "ui_time_delta_seconds": None,
                "ui_kills_delta": None,
                "ui_tick_action": "missing_sample",
            }

        game_time_seconds = float(game_time_seconds)
        current_kills = int(current_kills)
        baseline = self.baseline
        if baseline is None:
            self.baseline = (game_time_seconds, current_kills)
            return {
                "ui_time_delta_seconds": None,
                "ui_kills_delta": None,
                "ui_tick_action": "warmup_baseline",
            }

        baseline_time, baseline_kills = baseline
        time_delta = game_time_seconds - baseline_time
        kills_delta = current_kills - baseline_kills

        if kills_delta < 0 or time_delta < 0:
            self.baseline = (game_time_seconds, current_kills)
            return {
                "ui_time_delta_seconds": time_delta,
                "ui_kills_delta": kills_delta,
                "ui_tick_action": "reset_rebased",
            }
        if time_delta <= 0:
            return {
                "ui_time_delta_seconds": time_delta,
                "ui_kills_delta": kills_delta,
                "ui_tick_action": "paused_zero_delta",
            }
        if time_delta < 0.9:
            return {
                "ui_time_delta_seconds": time_delta,
                "ui_kills_delta": kills_delta,
                "ui_tick_action": "skipped_subsecond",
            }
        if time_delta > 1.2:
            self.baseline = (game_time_seconds, current_kills)
            return {
                "ui_time_delta_seconds": time_delta,
                "ui_kills_delta": kills_delta,
                "ui_tick_action": "skipped_overshoot_rebased",
            }

        self.baseline = (game_time_seconds, current_kills)
        return {
            "ui_time_delta_seconds": time_delta,
            "ui_kills_delta": kills_delta,
            "ui_tick_action": "accepted_tick",
        }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Log run timer and mob kills once per interval and also compute the "
            "same ~3s KPS metric used by the app."
        )
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Polling interval in seconds. Default: 1.0",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="Optional total runtime in seconds. 0 means run until Ctrl+C.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="CSV output path. Default: runtime/diagnostics/kps/kills_experiment.csv in this checkout",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Do not print per-sample output to the console.",
    )
    return parser


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def format_optional_int(value: int | None) -> str:
    return "" if value is None else str(value)


def format_optional_float(value: float | None) -> str:
    return "" if value is None else f"{value:.6f}"


def safe_print(message: str) -> None:
    try:
        print(message)
    except OSError:
        pass


def main() -> int:
    args = build_arg_parser().parse_args()
    interval = max(0.1, float(args.interval))
    duration = max(0.0, float(args.duration))
    output_path = Path(args.output)
    ensure_parent(output_path)

    tracker = LiveRunTracker()
    ui_monitor = UiKpsMonitor()
    one_second_history: deque[tuple[float, int]] = deque(maxlen=2)
    ui_tick_counts: dict[str, int] = {}

    safe_print(f"Attaching to {config.PROCESS_NAME}...")
    try:
        client = PlayerStatsClient(config.PROCESS_NAME)
    except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError) as exc:
        safe_print(f"Failed to attach: {exc}")
        return 1

    safe_print(f"Writing samples to {output_path}")
    safe_print("Press Ctrl+C to stop.")

    start_monotonic = time.monotonic()
    next_tick = start_monotonic

    fieldnames = [
        "utc_time",
        "wall_monotonic",
        "run_time_seconds",
        "mob_kills",
        "kills_delta",
        "time_delta_seconds",
        "kps_1s_delta",
        "window_kps_3s",
        "ui_kps",
        "ui_time_delta_seconds",
        "ui_kills_delta",
        "ui_tick_action",
        "status",
        "error",
    ]

    with client:
        with output_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()

            try:
                while True:
                    now = time.monotonic()
                    if now < next_tick:
                        time.sleep(next_tick - now)
                    sample_started = time.monotonic()
                    next_tick = sample_started + interval

                    run_time_seconds: float | None = None
                    mob_kills: int | None = None
                    kills_delta: int | None = None
                    time_delta_seconds: float | None = None
                    kps_1s_delta: float | None = None
                    window_kps_3s: int | None = None
                    ui_kps: int | None = None
                    ui_time_delta_seconds: float | None = None
                    ui_kills_delta: int | None = None
                    ui_tick_action = ""
                    status = "ok"
                    error_text = ""

                    try:
                        run_time_seconds = float(client.get_run_timer())
                        mob_kills = int(client.get_killed_mobs())
                        tracker.track_kills(run_time_seconds, mob_kills)
                        window_kps_3s = tracker.current_kps()
                        ui_kps = tracker.current_ui_kps()
                        ui_observation = ui_monitor.observe(run_time_seconds, mob_kills)
                        ui_time_delta_seconds = ui_observation["ui_time_delta_seconds"]
                        ui_kills_delta = ui_observation["ui_kills_delta"]
                        ui_tick_action = str(ui_observation["ui_tick_action"] or "")
                        ui_tick_counts[ui_tick_action] = ui_tick_counts.get(ui_tick_action, 0) + 1

                        one_second_history.append((run_time_seconds, mob_kills))
                        if len(one_second_history) >= 2:
                            prev_time, prev_kills = one_second_history[0]
                            curr_time, curr_kills = one_second_history[-1]
                            time_delta_seconds = curr_time - prev_time
                            kills_delta = curr_kills - prev_kills
                            if time_delta_seconds > 0:
                                kps_1s_delta = kills_delta / time_delta_seconds
                    except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError) as exc:
                        status = "read_error"
                        error_text = str(exc)
                    except Exception as exc:  # pragma: no cover - emergency logging path
                        status = "unexpected_error"
                        error_text = f"{type(exc).__name__}: {exc}"

                    row = {
                        "utc_time": utc_now_iso(),
                        "wall_monotonic": f"{sample_started:.6f}",
                        "run_time_seconds": format_optional_float(run_time_seconds),
                        "mob_kills": format_optional_int(mob_kills),
                        "kills_delta": format_optional_int(kills_delta),
                        "time_delta_seconds": format_optional_float(time_delta_seconds),
                        "kps_1s_delta": format_optional_float(kps_1s_delta),
                        "window_kps_3s": format_optional_int(window_kps_3s),
                        "ui_kps": format_optional_int(ui_kps),
                        "ui_time_delta_seconds": format_optional_float(ui_time_delta_seconds),
                        "ui_kills_delta": format_optional_int(ui_kills_delta),
                        "ui_tick_action": ui_tick_action,
                        "status": status,
                        "error": error_text,
                    }
                    writer.writerow(row)
                    handle.flush()

                    if not args.quiet:
                        if status == "ok":
                            safe_print(
                                f"t={run_time_seconds:8.3f}s | kills={mob_kills:8d} | "
                                f"dK={kills_delta if kills_delta is not None else '--':>4} | "
                                f"dT={f'{time_delta_seconds:.3f}' if time_delta_seconds is not None else '--':>6} | "
                                f"1s_kps={f'{kps_1s_delta:.2f}' if kps_1s_delta is not None else '--':>7} | "
                                f"3s_kps={window_kps_3s if window_kps_3s is not None else '--'} | "
                                f"ui_kps={ui_kps if ui_kps is not None else '--'} | "
                                f"ui_action={ui_tick_action or '--'}"
                            )
                        else:
                            safe_print(f"[{status}] {error_text}")

                    if duration > 0 and sample_started - start_monotonic >= duration:
                        break
            except KeyboardInterrupt:
                safe_print("Stopped by user.")

    accepted = ui_tick_counts.get("accepted_tick", 0)
    skipped = sum(
        count for action, count in ui_tick_counts.items() if action.startswith("skipped_")
    )
    paused = ui_tick_counts.get("paused_zero_delta", 0)
    warmup = ui_tick_counts.get("warmup_baseline", 0)
    safe_print(
        "UI KPS summary: "
        f"accepted={accepted}, skipped={skipped}, paused={paused}, warmup={warmup}, "
        f"by_action={ui_tick_counts}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
