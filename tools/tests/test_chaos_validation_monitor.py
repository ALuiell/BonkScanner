from __future__ import annotations

import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chaos_validation as monitor
from core.character_passives import CHARACTER_PASSIVE_SPECS, CharacterPassiveReading
from core.stats.types import ChargeShrineReading, PlayerStatModifierSnapshot
from core.tracker.shrines import SHRINE_STAT_RULES


def modifier(ptr, value):
    rule = SHRINE_STAT_RULES[12]
    return PlayerStatModifierSnapshot(
        stat_id=12, label=rule.label, value=value, value_format=rule.value_format,
        object_ptr=ptr, modify_type=rule.modify_type,
    )


class FakeClient:
    stop_path = None
    _resolve_stat_display = staticmethod(monitor.PlayerStatsClient._resolve_stat_display)

    def __init__(self, _process):
        self.index = -1
        self.memory = self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def process_identity(self):
        return "1:100"

    def resolve_owner_stats(self):
        self.index += 1
        return 1000

    def get_chaos_tome_level(self, _owner):
        return min(self.index, 2)

    def get_permanent_stat_modifiers(self, _owner):
        return {12: tuple(modifier(100 + n, 0.168) for n in range(min(self.index, 2)))}

    def get_chaos_tracking_state(self, owner):
        return self.get_chaos_tome_level(owner), self.get_permanent_stat_modifiers(owner)

    def get_player_stats(self, _owner):
        if self.stop_path:
            self.stop_path.touch()
        return {}

    def get_character_passive_reading(self, _owner, *, permanent_modifiers):
        spec = next(spec for spec in CHARACTER_PASSIVE_SPECS if spec.is_gamba)
        return CharacterPassiveReading(
            character_id=spec.character_id, character_name=spec.character_name,
            passive_id=spec.passive_id, passive_name=spec.passive_name,
            runtime_class=spec.runtime_class, passive_object_ptr=5000, level=0,
            gamba_current_level=0, gamba_upgrade_multiplier=0.75,
            gamba_min_multiplier=0.06, gamba_max_multiplier=1.0,
            permanent_modifiers=tuple(m for values in permanent_modifiers.values() for m in values),
        )

    def get_charge_shrine_tracking_state(self):
        return ChargeShrineReading(charged_total=0, shown_log=())


class MonitorTests(unittest.TestCase):
    def test_serialized_modifier_keeps_identity_and_float32_bits(self):
        entry = monitor._modifier_record(modifier(12345, 0.168))
        self.assertEqual(entry["object_ptr"], 12345)
        self.assertEqual(entry["stat_id"], 12)
        self.assertEqual(entry["modify_type"], 0)
        self.assertEqual(entry["value_f32_hex"], struct.pack("<f", 0.168).hex())

    def test_report_subtracts_existing_history_at_nonzero_start(self):
        tracker = monitor.LiveRunTracker()
        start = {12: (modifier(100, 0.168),)}
        tracker.update_chaos_tome(chaos_level=1, permanent_modifiers=start)
        baseline = monitor._snapshot_records(tracker)
        end = {12: (modifier(100, 0.168), modifier(200, 0.168))}
        tracker.update_chaos_tome(chaos_level=2, permanent_modifiers=end)
        report = monitor._build_report(
            run_id="test", start_level=1, end_level=2, start_modifiers=start,
            end_modifiers=end, start_stats={}, end_stats={}, tracker=tracker,
            samples=2, read_errors=0, start_tracked=baseline,
        )
        self.assertEqual(report["tracked_rolls"], 1)
        self.assertEqual(report["expected_rolls"], 1)
        self.assertEqual(report["mismatch_count"], 0)

    def run_monitor(self, root, *, stop=False):
        output = Path(root) / "sample"
        output.mkdir()
        argv = ["chaos_validation.py", "--run-id", "sample", "--output-dir", str(root),
                "--start-current", "--target-level", "2", "--settle-samples", "2", "--shared-sources"]
        with patch.object(sys, "argv", argv), patch.object(monitor, "PlayerStatsClient", FakeClient), \
             patch.object(FakeClient, "stop_path", output / "STOP" if stop else None), \
             patch.object(monitor.time, "sleep"):
            self.assertEqual(monitor.main(), 0)
        return output

    def test_shared_capture_records_new_objects_and_settled_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            output = self.run_monitor(directory)
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertEqual((report["expected_rolls"], report["tracked_rolls"]), (2, 2))
            samples = [json.loads(line) for line in (output / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([len(row["new_objects"]) for row in samples], [0, 1, 1, 0])
            self.assertTrue(all(row["cache_difference_ptrs"] == [] for row in samples))

    def test_stop_file_finishes_with_report(self):
        with tempfile.TemporaryDirectory() as directory:
            output = self.run_monitor(directory, stop=True)
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["finish_reason"], "stop_file")
            self.assertEqual(report["expected_rolls"], 0)


if __name__ == "__main__":
    unittest.main()
