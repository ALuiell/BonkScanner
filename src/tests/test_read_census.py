from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


def _load_census():
    path = Path(__file__).resolve().parents[2] / "tools" / "read_census.py"
    spec = importlib.util.spec_from_file_location("read_census", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load census from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReadCensusRatchetTests(unittest.TestCase):
    def test_current_on_tick_source_set_is_exact_and_has_no_bypasses(self) -> None:
        census = _load_census()

        self.assertEqual(
            census.enrolled_on_tick_source_names(),
            set(census.ENROLLABLE_ON_TICK_SOURCE_NAMES),
        )
        self.assertEqual(census.direct_on_tick_client_reads(), [])

    def test_boundary_populations_are_derived_from_the_tree(self) -> None:
        census = _load_census()

        # 33 with verifier telemetry: one new enrolled component-frame read,
        # plus cached PASSIVE_ITEMS and RUN_TIMER consumers in its checkpoint.
        # The latter two add call sites but not physical reads because the
        # Shrine and recording-lifecycle tasks resolve them earlier in the
        # same pass. Before that, 30 arrived with Charge Shrine tracking. It reuses the shared
        # passive-item sample for Wrench and does not need a stage-context read.
        # The previous 29 followed
        # the `passive_items` task becoming the whole loot sample. Three
        # of those twenty-nine arrived through that expansion and mean different
        # things:
        #
        # `get_map_activity_values` is a *second* call site for an already
        # enrolled source, which is what this count is supposed to move for --
        # the 10 s snapshot reads the same key, so the pass cache shares the one
        # physical walk. `get_luck` is genuinely new, and it is a new *source*
        # too (`LUCK`). The latest site is the fast consumer of the already
        # enrolled `LIVE_BANISHES` source; it shares the full snapshot's read.
        # Both keys are declared in the census beside the rest;
        # `test_current_on_tick_source_set_is_exact_and_has_no_bypasses` is what
        # proves it went in through the pass rather than around it.
        self.assertEqual(
            census.boundary_site_count([census.SRC / rel for rel in census.ON_TICK_FILES]),
            33,
        )
        # 4 since `reroll_map` stopped reading the map state and stats itself:
        # `wait_for_map_ready` hands the scan loop the stats it waited for, so
        # the pair that used to bracket the restart is gone. See
        # `OFF_TICK_SITE_LIMIT`, which came down with it.
        self.assertEqual(
            census.boundary_site_count([census.SRC / rel for rel in census.OFF_TICK_FILES]),
            4,
        )

    def test_missing_one_enrolment_fails_the_guard(self) -> None:
        census = _load_census()
        declared = len(census.ENROLLABLE_ON_TICK_SOURCE_NAMES)
        payload = {
            "on_tick_sites": 25,
            "off_tick_sites": 4,
            "enrolled_on_tick_sources": declared - 1,
            "missing_enrolled_sources": ["RUNTIME_ACTIVITY_STATE"],
            "direct_on_tick_client_reads": [],
        }

        failures = census._vacuity_failures(payload)

        self.assertTrue(any("missing" in failure for failure in failures))


if __name__ == "__main__":
    unittest.main()
