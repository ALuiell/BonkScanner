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

        # 26 since the `passive_items` fast-lane task: a *second* call site for
        # an already-enrolled source, which is what the site count is supposed
        # to move for. The source *set* is unchanged -- `PASSIVE_ITEMS` was
        # already enrolled by the full snapshot -- and
        # `test_current_on_tick_source_set_is_exact_and_has_no_bypasses` is what
        # guards that, so this number rising alone means a shared read, not a
        # new fact and not a bypass.
        self.assertEqual(
            census.boundary_site_count([census.SRC / rel for rel in census.ON_TICK_FILES]),
            26,
        )
        self.assertEqual(
            census.boundary_site_count([census.SRC / rel for rel in census.OFF_TICK_FILES]),
            6,
        )

    def test_missing_one_enrolment_fails_the_guard(self) -> None:
        census = _load_census()
        declared = len(census.ENROLLABLE_ON_TICK_SOURCE_NAMES)
        payload = {
            "on_tick_sites": 25,
            "off_tick_sites": 6,
            "enrolled_on_tick_sources": declared - 1,
            "missing_enrolled_sources": ["RUNTIME_ACTIVITY_STATE"],
            "direct_on_tick_client_reads": [],
        }

        failures = census._vacuity_failures(payload)

        self.assertTrue(any("missing" in failure for failure in failures))


if __name__ == "__main__":
    unittest.main()
