"""Read-only AFK acceptance monitor. Never resumes, restarts, or changes a game.

Requires a live game and explicit worker identity. Stops its OWN measurement on
worker loss, game end, identity change or expiry; never credits absent workers.
Reuses the native process-counter probe already inspected in this workspace.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import time

ACCEPTANCE = Path(__file__).resolve().parent.parent
NATIVE_SOURCE = ACCEPTANCE / 'live-game-20261117-recoveryprobe' / 'native_sampler.py'
GAME_LAB = Path(r'F:\Python\BonkScanner_experiments')


def game_state(expected_identity: str) -> dict:
    completed = subprocess.run(
        ['py', '-3.12', 'lab.py', 'game', 'time', 'phase'], cwd=GAME_LAB,
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=12)
    data = json.loads(completed.stdout)
    if completed.returncode != 0 or not data.get('ok'):
        raise RuntimeError('GameLab read-only state unavailable')
    result = data['result']
    if result.get('process') != expected_identity:
        raise RuntimeError('Game process identity changed')
    return {
        'process': result['process'], 'phase': result.get('phase'),
        'stageIndex': result.get('stage_index'),
        'gameOver': result.get('is_game_over'), 'playing': result.get('is_playing'),
        'paused': result.get('clocks', {}).get('paused'),
        'runSeconds': result.get('clocks', {}).get('run'),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker-pid', required=True, type=int)
    parser.add_argument('--worker-created', required=True, type=int)
    parser.add_argument('--game-identity', required=True, help='PID:creation-FILETIME')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=1500)
    parser.add_argument('--interval', type=float, default=5)
    args = parser.parse_args()
    if not 10 <= args.seconds <= 1800 or not 1 <= args.interval <= 15:
        parser.error('Duration must be 10..1800s and sample interval 1..15s')
    if args.output.exists() and any(args.output.iterdir()):
        parser.error('Output must be a new/empty directory; previous evidence is never overwritten')
    args.output.mkdir(parents=True, exist_ok=True)

    spec = importlib.util.spec_from_file_location('owned_native_probe', NATIVE_SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError('Native counter probe unavailable')
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    status, reason = 'PARTIAL', 'monitor_not_started'
    count, missing, paused_checks = 0, 0, 0
    previous: dict[tuple[int, int | None], tuple[float, float]] = {}
    started = time.monotonic()
    next_game_check = started
    last_game = None
    summary = {
        'startedUtc': datetime.now(timezone.utc).isoformat(),
        'workerPid': args.worker_pid, 'workerCreated': args.worker_created,
        'gameIdentity': args.game_identity, 'requestedSeconds': args.seconds,
        'scope': 'Read-only counters; GameLab phase read once per minute; no game control',
    }
    try:
        last_game = game_state(args.game_identity)
        if last_game['gameOver'] is not False or last_game['playing'] is not True:
            reason = 'game_not_active_at_preflight'
            return 2
        if last_game['paused'] is not False:
            reason = 'game_paused_at_preflight'
            return 2
        started = time.monotonic()
        with (args.output / 'samples.jsonl').open('x', encoding='utf-8') as output:
            while True:
                now = time.monotonic()
                rows, error = native.snapshot()
                worker = next((row for row in rows if row['pid'] == args.worker_pid), None)
                if error:
                    status, reason = 'FAIL', 'process_snapshot_failed'
                    break
                if worker is None:
                    missing += 1
                elif worker['createdFiletime'] != args.worker_created:
                    status, reason = 'FAIL', 'worker_identity_changed'
                    break
                else:
                    missing = 0
                if missing >= 2:
                    status, reason = 'FAIL', 'worker_disappeared'
                    break
                for row in rows:
                    key = row['pid'], row['createdFiletime']
                    cpu = row.get('cpuSeconds')
                    prior = previous.get(key)
                    row['cpuPercentOneCore'] = (
                        round(100 * max(0, cpu - prior[1]) / max(.001, now - prior[0]), 2)
                        if prior and cpu is not None else None)
                    if cpu is not None:
                        previous[key] = (now, cpu)
                record = {
                    'utc': datetime.now(timezone.utc).isoformat(),
                    'elapsedSeconds': round(now - started, 3),
                    'processes': rows, 'workerPresent': worker is not None,
                }
                if now >= next_game_check:
                    last_game = game_state(args.game_identity)
                    record['game'] = last_game
                    next_game_check = now + 60
                    if last_game['paused']:
                        paused_checks += 1
                    if last_game['gameOver'] is not False or last_game['playing'] is not True:
                        reason = 'game_ended_during_capture'
                        output.write(json.dumps(record) + '\n')
                        output.flush()
                        count += 1
                        break
                output.write(json.dumps(record) + '\n')
                output.flush()
                count += 1
                if now - started >= args.seconds:
                    if missing or paused_checks:
                        reason = 'paused_or_missing_interval'
                    else:
                        status, reason = 'PASS', 'configured_read_only_window_completed'
                    break
                time.sleep(max(0, min(args.interval, args.seconds - (time.monotonic() - started))))
    except BaseException as exc:
        status, reason = 'FAIL', type(exc).__name__
        raise
    finally:
        summary.update(status=status, reason=reason, samples=count,
                       elapsedSeconds=round(time.monotonic() - started, 3),
                       pausedGameChecks=paused_checks, lastGameState=last_game,
                       finishedUtc=datetime.now(timezone.utc).isoformat(),
                       limitations='PASS applies only to this window, not final ACK/restoration or full release acceptance')
        (args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(summary, indent=2))
    return 0 if status == 'PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
