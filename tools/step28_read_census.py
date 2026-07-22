"""Step 28 read census: name-level call sites, address-level duplicates,
on-tick/off-tick population, and the enrolled-source count.

Local-only (``tools/`` is gitignored) -- this is a measurement instrument, not
production code. See docs/updates/architecture_updates/step_28_plan.md
sections 3, 5 and 12.7 for the contract this enforces.

Baseline recorded 2026-07-22, before 28a landed:
    on-tick sites:  25
    off-tick sites:  6
    enrolled on-tick sources: 0
    address-level duplicate facts: 3 (stage_index, run_timer, stage_timer --
        all three read from 0x2f58e08/0x2f62398 by more than one code path)
    cross-boundary duplicates: 1 (get_disabled_items)

After 28b: enrolled on-tick sources 0 -> 2 (RUN_TIMER, MOB_KILLS). The
address-level duplicate count is unchanged by 28b -- enrolment makes
duplicates visible, it does not collapse them (that is 28c/§6's deferred
candidates).

Usage:
    python tools/step28_read_census.py
    python tools/step28_read_census.py --json
"""
from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = REPO / "src"
sys.path.insert(0, str(SRC))

PLAYER_STATS_CLIENT_METHODS = [
    "get_player_stats", "get_current_gold", "get_passive_items",
    "get_passive_item_count", "get_expected_chest_inputs", "get_live_weapons",
    "get_live_tomes", "get_chaos_tome_level", "get_chaos_tracking_state",
    "get_permanent_stat_modifiers", "get_live_banishes", "get_run_timer",
    "get_stage_timer", "get_my_time_seconds", "get_stage_timer_context",
    "get_powerup_tracking_snapshot", "get_active_status_effects",
    "get_run_stat_values", "get_killed_mobs", "get_chest_counters",
    "get_chests_bought", "get_live_damage_sources", "get_player_level",
    "resolve_owner_stats", "get_disabled_items",
]
GAME_DATA_CLIENT_METHODS = [
    "get_map_generation_state", "get_runtime_activity_state",
    "get_runtime_game_state", "wait_for_map_ready", "get_map_stats",
    "get_map_activity_values",
]
ALL_CLIENT_METHODS = sorted(set(PLAYER_STATS_CLIENT_METHODS) | set(GAME_DATA_CLIENT_METHODS))

# Static (type_info_offset, field_offset) facts, read by more than one path --
# from step_28_plan.md section 2.2. Verified against
# infra/memory/player_stats_client.py and infra/memory/game_data_client.py.
ADDRESS_FACTS = {
    "stage_index": {
        "address": (0x02F58E08, 0x08),
        "paths": [
            ("PlayerStatsClient", "_read_current_stage_time"),
            ("GameDataClient", "get_map_generation_state"),
            ("GameDataClient", "get_runtime_game_state"),
        ],
    },
    # 28c commit 2 collapsed the three app-level paths that each issued their
    # own physical `get_run_timer()` on one tick -- the combat task, the 10 s
    # full snapshot and the recording lifecycle -- down to one read resolved
    # through the pass. `src/tests/test_run_timer_sharing.py` asserts that
    # dynamically (3 -> 1 physical reads on one pass), because a static table
    # here can only record what someone believed, not what the code does.
    #
    # What remains is the *cross-client* duplicate: GameDataClient still reads
    # the same four bytes inside `get_runtime_game_state`. That is deferred
    # candidate L (plan section 6), not 28c's job.
    "run_timer": {
        "address": (0x02F62398, 0x20),
        "paths": [
            ("PlayerStatsClient", "get_run_timer"),
            ("GameDataClient", "get_runtime_game_state"),
        ],
        "on_tick_app_read_paths": 1,  # was 3 before 28c commit 2
    },
    "stage_timer": {
        "address": (0x02F62398, 0x1C),
        "paths": [
            ("PlayerStatsClient", "get_stage_timer_context"),
            ("GameDataClient", "get_runtime_game_state"),
        ],
    },
}

# On/off-tick boundaries are a design decision; the counts inside those
# boundaries are derived from the current AST so growth cannot hide behind a
# stale integer copied from the plan.
ON_TICK_FILES = [
    "app/player_stats_memory.py",
    "app/refresh_tasks.py",
    "app/player_stats_refresh.py",
]
OFF_TICK_FILES = [
    "gui_scanner.py",
    "gui_twitch.py",
    "ui/dialogs/__init__.py",
]
OFF_TICK_SITE_LIMIT = 6
# get_disabled_items is read on the tick (player_stats_memory.py) and from two
# off-tick sites -- see plan section 5.
CROSS_BOUNDARY_METHODS = ["get_disabled_items"]

# Every on-tick memory fact, as a named source. 28a declared four (two of them
# collaborator-cache keys), 28d enrolled the rest.
from app import read_sources  # noqa: E402

# Constant identifiers, not their string values -- a call site imports and uses
# the bare name (`RUN_TIMER`), it never spells out the namespaced string.
#
# PLAYER_STATS_CLIENT is excluded: it names the collaborator, not a memory
# fact, so it is not part of the enrolled-read population.
ENROLLABLE_ON_TICK_SOURCE_NAMES = {
    name: getattr(read_sources, name)
    for name in (
        # PlayerStatsClient
        "OWNER_STATS", "PLAYER_STATS", "PASSIVE_ITEMS", "RUN_TIMER",
        "STAGE_TIMER_CONTEXT", "MOB_KILLS", "PLAYER_LEVEL", "LIVE_WEAPONS",
        "LIVE_TOMES", "LIVE_BANISHES", "LIVE_DAMAGE_SOURCES", "DISABLED_ITEMS",
        "POWERUP_TRACKING_SNAPSHOT", "EXPECTED_CHEST_INPUTS",
        "CHAOS_TRACKING_STATE", "CHEST_COUNTERS",
        # GameDataClient
        "MAP_GENERATION_STATE", "RUNTIME_GAME_STATE", "RUNTIME_ACTIVITY_STATE",
        "MAP_ACTIVITY_VALUES",
    )
}

# The files an enrolled on-tick source may be used from -- the three on-tick
# files of the plan's section 5 table.
ENROLMENT_FILES = [
    SRC / "app" / "refresh_tasks.py",
    SRC / "app" / "player_stats_memory.py",
    SRC / "app" / "player_stats_refresh.py",
]


def _iter_source_files(exclude_dirs: tuple[str, ...]) -> list[pathlib.Path]:
    files = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if any(rel.startswith(prefix) for prefix in exclude_dirs):
            continue
        files.append(path)
    return files


def name_level_census() -> dict[str, int]:
    """Call sites per public client method, across src/ excluding src/tests/
    and src/infra/memory/ itself -- plan section 2.3's table."""
    counts = {name: 0 for name in ALL_CLIENT_METHODS}
    for path in _iter_source_files(("tests/", "infra/memory/")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            if func.attr in counts:
                counts[func.attr] += 1
    return counts


def address_level_duplicate_count() -> int:
    """Facts read by more than one path, i.e. the primary metric (section 3,
    target 1). Not the same as the name-level census: two differently-named
    methods can resolve one address."""
    return sum(1 for fact in ADDRESS_FACTS.values() if len(fact["paths"]) > 1)


SOURCE_READ_CALLS = {
    "read_source": 1,
    "read_memory_source": 1,
    "get_or_create": 0,
    "get_or_create_with_metadata": 0,
}


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def enrolled_on_tick_source_names() -> set[str]:
    """Identifiers actually supplied as source keys to the pass API.

    Imports and comments do not count. This is intentionally stricter than the
    old text search, where leaving an unused import behind made an unenrolled
    direct read look enrolled forever.
    """
    used: set[str] = set()
    for path in ENROLMENT_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)
            key_index = SOURCE_READ_CALLS.get(name or "")
            if key_index is None or len(node.args) <= key_index:
                continue
            key = node.args[key_index]
            if isinstance(key, ast.Name) and key.id in ENROLLABLE_ON_TICK_SOURCE_NAMES:
                used.add(key.id)
    return used


def _method_references(paths: list[pathlib.Path]) -> list[tuple[pathlib.Path, ast.Attribute]]:
    refs: list[tuple[pathlib.Path, ast.Attribute]] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        refs.extend(
            (path, node)
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in ALL_CLIENT_METHODS
        )
    return refs


def boundary_site_count(paths: list[pathlib.Path]) -> int:
    count = len(_method_references(paths))
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        count += sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and _call_name(node) == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in ALL_CLIENT_METHODS
        )
    return count


def direct_on_tick_client_reads() -> list[str]:
    """Client method references not enclosed by a pass source call."""
    failures: list[str] = []
    for path in ENROLMENT_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute) or node.attr not in ALL_CLIENT_METHODS:
                continue
            current: ast.AST | None = node
            protected = False
            while current in parents:
                current = parents[current]
                if isinstance(current, ast.Call) and _call_name(current) in SOURCE_READ_CALLS:
                    protected = True
                    break
                if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    break
            if not protected:
                failures.append(f"{path.relative_to(SRC).as_posix()}:{node.lineno}:{node.attr}")
    return sorted(failures)


def _vacuity_failures(payload: dict) -> list[str]:
    failures: list[str] = []
    if payload["on_tick_sites"] < 5:
        failures.append(f"implausibly few on-tick sites: {payload['on_tick_sites']}")
    if payload["enrolled_on_tick_sources"] != len(ENROLLABLE_ON_TICK_SOURCE_NAMES):
        failures.append(
            "enrolled source set differs from the census map: "
            f"missing={payload['missing_enrolled_sources']}"
        )
    if payload["direct_on_tick_client_reads"]:
        failures.append(
            "on-tick client reads bypass the pass: "
            + ", ".join(payload["direct_on_tick_client_reads"])
        )
    if payload["off_tick_sites"] > OFF_TICK_SITE_LIMIT:
        failures.append(
            f"off-tick population grew ({payload['off_tick_sites']} > {OFF_TICK_SITE_LIMIT}) "
            "without an explicit decision recorded in this file"
        )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    name_census = name_level_census()
    enrolled_names = enrolled_on_tick_source_names()
    on_tick_paths = [SRC / rel for rel in ON_TICK_FILES]
    off_tick_paths = [SRC / rel for rel in OFF_TICK_FILES]
    payload = {
        "name_level_census": name_census,
        "address_level_facts": {
            fact: {
                "address": f"0x{addr[0]:X}+0x{addr[1]:X}",
                "paths": [f"{cls}.{method}" for cls, method in info["paths"]],
            }
            for fact, (addr, info) in (
                (fact, (info["address"], info)) for fact, info in ADDRESS_FACTS.items()
            )
        },
        "address_level_duplicate_count": address_level_duplicate_count(),
        "on_tick_sites": boundary_site_count(on_tick_paths),
        "off_tick_sites": boundary_site_count(off_tick_paths),
        "cross_boundary_methods": CROSS_BOUNDARY_METHODS,
        "enrolled_on_tick_sources": len(enrolled_names),
        "missing_enrolled_sources": sorted(set(ENROLLABLE_ON_TICK_SOURCE_NAMES) - enrolled_names),
        "direct_on_tick_client_reads": direct_on_tick_client_reads(),
        "enrollable_on_tick_sources": sorted(ENROLLABLE_ON_TICK_SOURCE_NAMES),
    }

    failures = _vacuity_failures(payload)
    payload["vacuity_failures"] = failures

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Step 28 read census")
        print(f"  on-tick sites (declared):        {payload['on_tick_sites']}")
        print(f"  off-tick sites (declared):       {payload['off_tick_sites']}")
        print(f"  cross-boundary methods:          {payload['cross_boundary_methods']}")
        print(f"  address-level duplicate facts:   {payload['address_level_duplicate_count']}")
        print(f"  enrolled on-tick sources:        {payload['enrolled_on_tick_sources']}"
              f" / {len(ENROLLABLE_ON_TICK_SOURCE_NAMES)} enrollable this slice")
        print()
        print("  name-level call-site census (non-zero only):")
        for name, count in sorted(name_census.items()):
            if count:
                print(f"    {name:32s} {count:3d}")
        if failures:
            print()
            print("VACUITY GUARD FAILURES:")
            for failure in failures:
                print(f"  - {failure}")

    return 2 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
