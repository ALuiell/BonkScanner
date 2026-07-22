"""Step 28c: measure the RUN_TIMER/MOB_KILLS group span, normal path vs cold path.

step_28_plan.md section 12.4 forbids inventing a numerical span limit from the
task cadence: "Before 28c fixes the constant, the 28b harness and advised live
run must record the normal and cold-path distribution. The accepted limit is
then set above normal observed variation but below a window that would make the
pair misleading. If no stable separation can be established, stop condition 5
fires and the cold reader must be fixed first."

What this harness measures, and what it deliberately does not
------------------------------------------------------------

The group span is `max(member.finished_at) - min(member.started_at)` across
RUN_TIMER and MOB_KILLS. Both members are `ReadProcessMemory` sequences through
`infra.memory.reader`, so a span is

    (number of memory reads on the path) x (cost of one ReadProcessMemory)
    + a small, measurable amount of Python

The **read count** is exact, deterministic and hardware-independent: it is a
property of the code, and this harness counts it by instrumenting a fake
`MemoryReader` that answers a scripted RunStats dictionary. That is the real
measurement, and it is what establishes whether a separation exists at all.

The **wall-clock cost of one ReadProcessMemory** cannot be obtained without a
live game process, and this harness does not fabricate one. It is a parameter
(`--read-cost-us`), so the owner can run this against a measured value from a
real session and get a span in seconds. Picking a plausible-looking number here
and calling the result a measurement would be precisely the threshold-fitting
the plan forbids.

Usage:
    python tools/step28_span_measure.py
    python tools/step28_span_measure.py --read-cost-us 12.5
    python tools/step28_span_measure.py --entries 64 --json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = REPO / "src"
sys.path.insert(0, str(SRC))

from infra.memory.player_stats_client import PlayerStatsClient  # noqa: E402

# A real RunStats dictionary carries on the order of a few dozen stat entries.
# "kills" is created lazily on the first increment, so before that it is absent
# and the walk runs to completion -- the worst case for the cold path.
DEFAULT_ENTRIES = 40
CLASS_PTR = 0x1000
STATIC_FIELDS = 0x2000
STATS_DICT = 0x3000
ENTRIES_BASE = 0x4000
RUN_TIMER_CLASS_PTR = 0x8000
RUN_TIMER_STATIC = 0x9000

# Names long enough to be realistic; the walk reads one mono string per entry.
_STAT_NAMES = [
    "chestsBought", "chestsOpened", "keysUsed", "goldEarned", "goldSpent",
    "damageDealt", "damageTaken", "healingDone", "levelsGained", "itemsPicked",
    "banishesUsed", "rerollsUsed", "bossesKilled", "elitesKilled", "potsBroken",
    "gravestonesBroken", "pumpkinsBroken", "cryptChestsOpened", "anvilsUsed",
    "tomesCollected", "weaponsUpgraded", "passivesCollected", "powerupsTaken",
    "stagesCleared", "timeSurvived", "distanceMoved", "projectilesFired",
    "critsLanded", "shieldsBroken", "revivesUsed", "curseStacks", "blessings",
    "chaosRolls", "chaosLevel", "swarmsSurvived", "eventsCompleted",
    "portalsEntered", "secretsFound", "questsDone", "achievementsHit",
]


class CountingReader:
    """A scripted `MemoryReader` that counts every physical read.

    `read_cost_seconds` optionally busy-waits per read so the harness can also
    report a wall-clock span for a supplied per-read cost.
    """

    def __init__(self, *, entries: int, include_kills: bool, read_cost_seconds: float) -> None:
        self.reads = 0
        self._read_cost = read_cost_seconds
        self._entries = entries
        names = list(_STAT_NAMES[:entries])
        while len(names) < entries:
            names.append(f"filler{len(names)}")
        if include_kills:
            # Worst realistic position: the lazily-created entry lands last.
            names[-1] = "kills"
        self._names = names

    def _charge(self) -> None:
        self.reads += 1
        if self._read_cost > 0:
            end = time.perf_counter() + self._read_cost
            while time.perf_counter() < end:
                pass

    def module_offset(self, _module: str, offset: int) -> int:
        self._charge()
        return offset

    def read_ptr(self, address: int) -> int:
        self._charge()
        client = PlayerStatsClient
        if address == client.RUN_STATS_TYPE_INFO_OFFSET:
            return CLASS_PTR
        if address == CLASS_PTR + client.CLASS_STATIC_FIELDS_OFFSET:
            return STATIC_FIELDS
        if address == STATIC_FIELDS + client.RUN_STATS_DICT_OFFSET:
            return STATS_DICT
        if address == STATS_DICT + client.DICT_ENTRIES_OFFSET:
            return ENTRIES_BASE
        if address == client.RUN_TIMER_TYPE_INFO_OFFSET:
            return RUN_TIMER_CLASS_PTR
        if address == RUN_TIMER_CLASS_PTR + client.CLASS_STATIC_FIELDS_OFFSET:
            return RUN_TIMER_STATIC
        # A dictionary entry's key pointer.
        return address

    def read_i32(self, address: int) -> int:
        self._charge()
        client = PlayerStatsClient
        if address == STATS_DICT + client.DICT_COUNT_OFFSET:
            return self._entries
        if address == STATS_DICT + client.DICT_VERSION_OFFSET:
            return 1
        return 0  # every entry's hash code: non-negative, so none is skipped

    def read_float(self, _address: int) -> float:
        self._charge()
        return 12.0

    def read_mono_string(self, address: int) -> str | None:
        self._charge()
        client = PlayerStatsClient
        offset = address - (ENTRIES_BASE + client.DICT_ENTRY_START_OFFSET)
        index = offset // client.DICT_ENTRY_SIZE
        if 0 <= index < len(self._names):
            return self._names[index]
        return None


def _measure(*, entries: int, include_kills: bool, read_cost_seconds: float, repeats: int) -> dict:
    """One cold read (address-cache miss) then `repeats` warm reads."""
    reader = CountingReader(
        entries=entries, include_kills=include_kills, read_cost_seconds=read_cost_seconds
    )
    client = PlayerStatsClient(memory=reader)

    # Cold: the address cache is empty, so `_find_run_stat_value_address` walks
    # the whole dictionary with a `read_mono_string` per entry.
    before = reader.reads
    start = time.perf_counter()
    client.get_run_timer()
    client.get_killed_mobs()
    cold_span = time.perf_counter() - start
    cold_reads = reader.reads - before

    # Warm: the dictionary identity/version is unchanged, so the cached address
    # is reused and no walk happens.
    warm_reads: list[int] = []
    warm_spans: list[float] = []
    for _ in range(repeats):
        before = reader.reads
        start = time.perf_counter()
        client.get_run_timer()
        client.get_killed_mobs()
        warm_spans.append(time.perf_counter() - start)
        warm_reads.append(reader.reads - before)

    return {
        "cold_reads": cold_reads,
        "cold_span_seconds": cold_span,
        "warm_reads_min": min(warm_reads),
        "warm_reads_max": max(warm_reads),
        "warm_span_seconds_median": statistics.median(warm_spans),
        "warm_span_seconds_max": max(warm_spans),
    }


def measure_live(repeats: int) -> dict:
    """Time the real combat group against the running game.

    This is the end-to-end measurement the scripted mode above cannot do: it
    attaches to the actual process and times ``get_run_timer()`` followed by
    ``get_killed_mobs()`` -- the exact pair, in the exact order, that
    ``_refresh_combat_metrics_task`` reads -- so no per-read cost has to be
    supplied or derived.

    The cold path is forced by invalidating the kills address cache before each
    sample, which sends ``_get_cached_killed_mobs`` back through
    ``_find_run_stat_value_address``'s dictionary walk. That is the worst case
    the span bound exists to judge.

    Requires the game to be running and in a run.
    """
    from app import config

    client = PlayerStatsClient(config.PROCESS_NAME)

    def sample(force_cold: bool) -> float:
        if force_cold:
            # Any mismatch against the cached dictionary identity re-triggers
            # the linear walk; zeroing the remembered dict pointer is enough.
            client._cached_kills_dict = 0
            client._cached_kills_address = 0
        start = time.perf_counter()
        client.get_run_timer()
        client.get_killed_mobs()
        return time.perf_counter() - start

    # One throwaway pair so process attach / first page-in is not counted.
    sample(force_cold=True)

    warm = sorted(sample(force_cold=False) for _ in range(repeats))
    cold = sorted(sample(force_cold=True) for _ in range(repeats))

    def stats(samples):
        return {
            "median": statistics.median(samples),
            "p95": samples[min(len(samples) - 1, int(len(samples) * 0.95))],
            "max": max(samples),
        }

    return {"warm": stats(warm), "cold": stats(cold), "samples": repeats}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entries", type=int, default=DEFAULT_ENTRIES)
    parser.add_argument("--repeats", type=int, default=200)
    parser.add_argument(
        "--live",
        action="store_true",
        help="attach to the running game and time the real RUN_TIMER/MOB_KILLS "
             "pair, warm and cold. Needs the game running and in a run. This "
             "is the end-to-end measurement; --read-cost-us is not needed.",
    )
    parser.add_argument(
        "--read-cost-us",
        type=float,
        default=0.0,
        help="measured cost of one ReadProcessMemory, in microseconds. Only a "
             "live session can supply this; with the default 0 the harness "
             "reports read counts and Python overhead only.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.live:
        from app.read_sources import KPS_GROUP_SPAN_LIMIT_SECONDS

        try:
            live = measure_live(args.repeats)
        except Exception as exc:
            print(f"LIVE MEASUREMENT FAILED: {type(exc).__name__}: {exc}")
            print("The game must be running and in a run for this mode.")
            return 3

        if args.json:
            print(json.dumps(live, indent=2, sort_keys=True))
            return 0

        limit_ms = KPS_GROUP_SPAN_LIMIT_SECONDS * 1000
        print("Step 28c LIVE group-span measurement (RUN_TIMER + MOB_KILLS)")
        print(f"  samples per path:  {live['samples']}")
        print(f"  accepted limit:    {limit_ms:.1f} ms"
              "  (KPS_GROUP_SPAN_LIMIT_SECONDS)")
        for label in ("warm", "cold"):
            s = live[label]
            print(f"  {label:5s} median {s['median']*1000:8.4f} ms"
                  f"   p95 {s['p95']*1000:8.4f} ms"
                  f"   max {s['max']*1000:8.4f} ms")
        worst = live["cold"]["max"]
        headroom = KPS_GROUP_SPAN_LIMIT_SECONDS / worst if worst else float("inf")
        print()
        if worst >= KPS_GROUP_SPAN_LIMIT_SECONDS:
            print(f"  FAIL: the cold path's worst span ({worst*1000:.4f} ms) reaches "
                  f"the accepted limit. Plan stop condition 5: the answer is NOT a "
                  f"looser bound -- the cold reader needs its own fix first.")
            return 1
        print(f"  PASS: worst cold span is {headroom:.0f}x inside the limit.")
        return 0

    read_cost_seconds = args.read_cost_us / 1_000_000.0
    payload = {
        "entries": args.entries,
        "read_cost_us": args.read_cost_us,
        "with_kills_entry": _measure(
            entries=args.entries,
            include_kills=True,
            read_cost_seconds=read_cost_seconds,
            repeats=args.repeats,
        ),
        "without_kills_entry": _measure(
            entries=args.entries,
            include_kills=False,
            read_cost_seconds=read_cost_seconds,
            repeats=args.repeats,
        ),
    }
    ratio = (
        payload["with_kills_entry"]["cold_reads"]
        / max(1, payload["with_kills_entry"]["warm_reads_max"])
    )
    payload["cold_to_warm_read_ratio"] = ratio

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print("Step 28c group-span measurement (RUN_TIMER + MOB_KILLS)")
    print(f"  RunStats entries simulated: {args.entries}")
    print(f"  per-read cost supplied:     {args.read_cost_us} us"
          f"{'  (NOT SUPPLIED -- read counts only)' if not args.read_cost_us else ''}")
    for label in ("with_kills_entry", "without_kills_entry"):
        block = payload[label]
        print()
        print(f"  {label.replace('_', ' ')}:")
        print(f"    cold (cache miss) reads:  {block['cold_reads']}")
        print(f"    warm reads per pass:      {block['warm_reads_min']}"
              f"-{block['warm_reads_max']}")
        print(f"    cold span:                {block['cold_span_seconds']*1000:.4f} ms")
        print(f"    warm span median / max:   {block['warm_span_seconds_median']*1000:.4f}"
              f" / {block['warm_span_seconds_max']*1000:.4f} ms")
    print()
    print(f"  cold : warm read ratio      {ratio:.1f}x")
    print()
    print("  The read counts above are exact and hardware-independent. The")
    print("  span in seconds is NOT a measurement unless --read-cost-us was")
    print("  supplied from a live session: see this file's header.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
