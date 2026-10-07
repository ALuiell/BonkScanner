from __future__ import annotations

import src  # noqa: F401
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.roll_analytics import RollAnalyticsService
from core.character_passives import (
    CHARACTER_PASSIVE_SPECS, CharacterPassiveReading, CharacterPassiveStatus,
)
from core.roll_analytics import confirmed_roll_counts, stable_roll_scope
from core.stats.types import ChaosTomeSnapshot, ChaosTomeStatSnapshot, PlayerStatModifierSnapshot
from core.stats.formats import PlayerStatFormat
from core.tracker.live_run import LiveRunTracker
from core.tracker.passives import gamba_roll_value
from core.tracker.shrines import SHRINE_STAT_RULES
from infra.roll_history_store import RollHistoryStore


class RollAttributionTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "history.json"
        self.service = RollAnalyticsService(RollHistoryStore(self.path))
        self.addCleanup(self.service.close)

    def mixed_sources(self, dice_level=1):
        spec = next(spec for spec in CHARACTER_PASSIVE_SPECS if spec.is_gamba)
        rule = SHRINE_STAT_RULES[5]
        modifiers = tuple(
            PlayerStatModifierSnapshot(
                stat_id=5, label=rule.label, value=value,
                value_format=rule.value_format, object_ptr=ptr, modify_type=rule.modify_type,
            )
            for ptr, value in ((0xB000, gamba_roll_value(5, 1.4, 0)), (0xB100, 0.07))
        )
        reading = CharacterPassiveReading(
            character_id=spec.character_id, character_name=spec.character_name,
            passive_id=spec.passive_id, passive_name=spec.passive_name,
            runtime_class=spec.runtime_class, passive_object_ptr=200, level=dice_level,
            gamba_current_level=dice_level, gamba_upgrade_multiplier=0.75,
            gamba_min_multiplier=0.06, gamba_max_multiplier=1.0,
            permanent_modifiers=modifiers,
        )
        tracker = LiveRunTracker()
        tracker.update_permanent_sources(
            reading, chaos_level=1, permanent_modifiers={5: modifiers},
        )
        return tracker.chaos_tome_snapshot(), tracker.character_passive_snapshot()

    def observe(self, chaos, passive=None):
        self.service.observe(
            process_identity="123:456", owner_stats=100, passive_ptr=200,
            chaos=chaos, passive=passive,
        )
        self.service.flush()

    def test_complete_dice_with_other_source_candidates_is_saved_once(self):
        chaos, passive = self.mixed_sources()
        self.assertEqual(passive.status, CharacterPassiveStatus.SUPPORTED)
        self.assertEqual(passive.coverage, "complete")
        self.assertEqual(passive.ambiguous, 0)
        self.assertGreater(passive.pending, 0)
        self.assertEqual(confirmed_roll_counts(chaos, passive),
                         {"chaos": {5: 1}, "dice": {5: 1}})
        self.service.set_collection_active(True)
        self.observe(chaos, passive)
        self.observe(chaos, passive)
        self.assertEqual(self.service.snapshot("dice").total, 1)
        self.assertEqual(self.service.snapshot("chaos").total, 1)

    def test_missing_dice_roll_still_withholds_dice_without_blocking_chaos(self):
        chaos, passive = self.mixed_sources(dice_level=2)
        self.assertEqual(passive.status, CharacterPassiveStatus.PARTIAL)
        self.assertGreater(passive.ambiguous, 0)
        self.assertEqual(confirmed_roll_counts(chaos, passive), {"chaos": {5: 1}})
        self.service.set_collection_active(True)
        self.observe(chaos, passive)
        self.assertEqual(self.service.snapshot("dice").total, 0)
        self.assertEqual(self.service.snapshot("chaos").total, 1)

    def test_ambiguous_or_recovering_dice_is_not_collected(self):
        _, passive = self.mixed_sources()
        for unconfirmed in (
            replace(passive, ambiguous=1),
            replace(passive, status=CharacterPassiveStatus.UPDATING),
            replace(passive, status=CharacterPassiveStatus.UNAVAILABLE),
        ):
            with self.subTest(status=unconfirmed.status, ambiguous=unconfirmed.ambiguous):
                self.assertEqual(confirmed_roll_counts(None, unconfirmed), {})

    def test_chaos_enabled_after_first_roll_saves_530_of_531(self):
        def snapshot(counts):
            return ChaosTomeSnapshot(sum(counts.values()), tuple(
                ChaosTomeStatSnapshot(stat, str(stat), 1, PlayerStatFormat.FLAT, count)
                for stat, count in counts.items()
            ))

        self.service.set_collection_active(False)
        self.observe(snapshot({38: 1}))
        self.service.set_collection_active(True)
        self.observe(snapshot({38: 1}))
        self.observe(snapshot({38: 27, 12: 504}))
        self.observe(snapshot({38: 27, 12: 504}))
        self.assertEqual(self.service.snapshot("chaos").total, 530)
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        scope = stable_roll_scope("123:456", 100, 200)
        self.assertEqual(sum(payload["checkpoints"][scope]["chaos"].values()), 531)
        self.assertEqual(payload["totals"]["chaos"]["38"], 26)


if __name__ == "__main__":
    unittest.main()
