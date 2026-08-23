import unittest
from types import SimpleNamespace

from app.refresh_coordinator import RefreshTickContext
from app.read_sources import SHRINE_TRACKING_STATE
from core.stats.formats import PlayerStatFormat
from core.stats.types import (
    ChargeShrineLogEntry,
    ChargeShrineReading,
    ChargeShrineSnapshot,
    ChargeShrineStatSnapshot,
)
from core.tracker.shrines import (
    SHRINE_STAT_RULES,
    _ShrineState,
    match_shrine_reward,
    snapshot,
    update,
)
from infra.memory.player_stats_client import PlayerStatsClient
from infra.vod_storage import VodSnapshot, _record_to_snapshot, _snapshot_to_record
from projections.formatting import build_compare_runs_shrines_table
from tests.support.refresh_tasks import build_refresh_tasks
from ui.tabs.player_stats.stat_cards import shrine_average_roll_quality


def _entry(pointer, stat_id, label, value, value_format, modify_type):
    return ChargeShrineLogEntry(
        object_ptr=pointer,
        stat_id=stat_id,
        label=label,
        value=value,
        value_format=value_format,
        modify_type=modify_type,
    )


GRITCH = _entry(1, 38, "Difficulty", 0.05, PlayerStatFormat.PERCENT, 2)
DAMAGE = _entry(2, 12, "Damage", 0.12, PlayerStatFormat.MULTIPLIER, 0)
LUCK_RARE = _entry(3, 30, "Luck", 0.07, PlayerStatFormat.PERCENT, 2)
MAX_HP_LEGENDARY = _entry(4, 0, "Max HP", 30.0, PlayerStatFormat.FLAT, 2)


class ChargeShrineTrackerTests(unittest.TestCase):
    def test_current_binary_fingerprint_contract_contains_all_28_stats(self):
        expected = {
            0: (15.0, 2), 1: (20.0, 2), 2: (5.0, 2), 3: (5.0, 2),
            4: (0.05, 2), 5: (0.05, 2), 9: (0.08, 0), 10: (0.08, 0),
            11: (0.10, 0), 12: (0.12, 0), 15: (0.06, 0), 16: (1.0, 2),
            17: (0.06, 2), 18: (0.05, 2), 19: (0.10, 0), 23: (0.10, 0),
            24: (0.10, 0), 25: (0.08, 0), 26: (0.10, 0), 29: (0.20, 0),
            30: (0.05, 2), 31: (0.075, 0), 32: (0.075, 0), 38: (0.08, 2),
            39: (0.15, 0), 40: (0.10, 0), 41: (0.05, 0), 46: (1.0, 2),
        }
        actual = {
            stat_id: (rule.base_value, rule.modify_type)
            for stat_id, rule in SHRINE_STAT_RULES.items()
        }
        self.assertEqual(actual, expected)

    def test_jump_height_reward_is_displayed_as_a_percentage(self):
        stat = ChargeShrineStatSnapshot(
            stat_id=26,
            label="Jump Height",
            value=0.1,
            value_format=PlayerStatFormat.MULTIPLIER,
            rolls=1,
        )
        self.assertEqual(stat.display_delta, "+10%")

    def test_shrine_card_quality_uses_inferred_rarity_breakdown(self):
        stat = ChargeShrineStatSnapshot(
            stat_id=12,
            label="Damage",
            value=0.288,
            value_format=PlayerStatFormat.MULTIPLIER,
            rolls=2,
            rarity_counts=(("Common", 1), ("Rare", 1)),
        )

        self.assertAlmostEqual(shrine_average_roll_quality(stat), 0.2)

    def test_shrine_card_quality_is_unknown_when_a_roll_has_no_unique_rarity(self):
        stat = ChargeShrineStatSnapshot(
            stat_id=12,
            label="Damage",
            value=0.24,
            value_format=PlayerStatFormat.MULTIPLIER,
            rolls=2,
            rarity_counts=(("Common", 1),),
        )

        self.assertIsNone(shrine_average_roll_quality(stat))

    def test_gritch_log_does_not_spend_charge_reward_budget(self):
        state = _ShrineState()
        update(
            state,
            ChargeShrineReading(charged_total=0, shown_log=()),
            wrench_stacks=0,
        )
        update(
            state,
            ChargeShrineReading(charged_total=1, shown_log=(GRITCH,)),
            wrench_stacks=0,
        )

        pending = snapshot(state)
        self.assertEqual(pending.pending, 1)
        self.assertEqual(pending.selected, 0)

        update(
            state,
            ChargeShrineReading(charged_total=1, shown_log=(GRITCH, DAMAGE)),
            wrench_stacks=0,
        )

        result = snapshot(state)
        self.assertEqual(result.charged, 1)
        self.assertEqual(result.selected, 1)
        self.assertEqual(result.pending, 0)
        self.assertEqual([stat.label for stat in result.stats], ["Damage"])
        rarities = {stat.label: dict(stat.rarity_counts) for stat in result.stats}
        self.assertEqual(rarities["Damage"], {"Common": 1})

    def test_first_sample_reconstructs_one_selected_reward_per_charged_shrine(self):
        state = _ShrineState()
        update(
            state,
            ChargeShrineReading(charged_total=1, shown_log=(GRITCH, DAMAGE)),
            wrench_stacks=0,
        )

        result = snapshot(state)
        self.assertEqual(result.selected, 1)
        self.assertEqual(result.pending, 0)

    def test_wrench_multiplier_is_part_of_fingerprint(self):
        entry = _entry(
            10,
            12,
            "Damage",
            0.1380000114440918,
            PlayerStatFormat.MULTIPLIER,
            0,
        )
        match = match_shrine_reward(entry, wrench_stacks=2)
        self.assertIsNotNone(match)
        self.assertEqual((match.rarity, match.wrench_stacks), ("Common", 2))
        self.assertIsNone(match_shrine_reward(entry, wrench_stacks=0))

    def test_late_attach_reconstructs_fingerprinted_rewards_without_map_requirements(self):
        state = _ShrineState()
        update(
            state,
            ChargeShrineReading(charged_total=1, shown_log=(GRITCH, DAMAGE)),
            wrench_stacks=0,
        )
        result = snapshot(state)
        self.assertEqual(result.charged, 1)
        self.assertEqual(result.selected, 1)
        self.assertEqual([stat.label for stat in result.stats], ["Damage"])

    def test_refresh_reuses_shared_passive_item_sample_without_stage_read(self):
        reading = ChargeShrineReading(charged_total=0, shown_log=())
        client = SimpleNamespace(
            get_charge_shrine_tracking_state=lambda: reading,
            resolve_owner_stats=lambda: 0x1234,
            get_passive_items=lambda _owner_stats: (),
        )
        service, world = build_refresh_tasks(stats_client=client)
        updates = []
        world.tracker.update_charge_shrines = (
            lambda current, **kwargs: updates.append((current, kwargs))
        )
        context = RefreshTickContext(pass_id=1, started_at=1.0)

        self.assertTrue(service._refresh_charge_shrines_task(context))

        self.assertEqual(updates[0][0], reading)
        self.assertEqual(updates[0][1]["wrench_stacks"], 0)
        self.assertIn(SHRINE_TRACKING_STATE, context.resolved_keys())

    def test_log_before_counter_race_is_consumed_on_next_sample(self):
        state = _ShrineState()
        update(
            state,
            ChargeShrineReading(charged_total=0, shown_log=()),
            wrench_stacks=0,
        )
        update(
            state,
            ChargeShrineReading(charged_total=0, shown_log=(DAMAGE,)),
            wrench_stacks=0,
        )
        self.assertEqual(snapshot(state).selected, 0)
        update(
            state,
            ChargeShrineReading(charged_total=1, shown_log=(DAMAGE,)),
            wrench_stacks=0,
        )

        result = snapshot(state)
        self.assertEqual(result.selected, 1)
        self.assertEqual(result.pending, 0)

    def test_valid_reward_falls_back_to_inferred_wrench_at_inventory_boundary(self):
        state = _ShrineState()
        update(
            state,
            ChargeShrineReading(charged_total=0, shown_log=()),
            wrench_stacks=1,
        )
        update(
            state,
            ChargeShrineReading(charged_total=1, shown_log=(DAMAGE,)),
            wrench_stacks=1,
        )

        result = snapshot(state)
        self.assertEqual(result.selected, 1)
        self.assertEqual(result.pending, 0)

    def test_terminal_lifecycle_folds_shrines_before_stopping_recording(self):
        events = []
        reading = ChargeShrineReading(charged_total=1, shown_log=())
        client = SimpleNamespace(
            get_charge_shrine_tracking_state=lambda: reading,
            resolve_owner_stats=lambda: 0x1234,
            get_passive_items=lambda _owner_stats: (),
        )
        lifecycle = SimpleNamespace(completed_run=True)
        capture = SimpleNamespace(
            sync_run_state=lambda _context=None: events.append("stop")
        )
        recorder = SimpleNamespace(is_recording=True)
        service, world = build_refresh_tasks(
            stats_client=client,
            lifecycle=lifecycle,
            capture=capture,
            vod_recorder=recorder,
        )
        world.tracker.update_charge_shrines = (
            lambda _reading, **_kwargs: events.append("shrines")
        )

        self.assertTrue(
            service._refresh_recording_lifecycle_task(
                RefreshTickContext(pass_id=1, started_at=1.0)
            )
        )

        self.assertEqual(events, ["shrines", "stop"])

    def test_memory_reader_samples_log_before_charged_counter(self):
        events = []

        class Memory:
            def read_ptr(self, address):
                events.append(("ptr", address))
                return 0x3000

            def read_i32(self, address):
                events.append(("i32", address))
                return 1

        client = PlayerStatsClient.__new__(PlayerStatsClient)
        client.memory = Memory()
        client._resolve_type_static_fields = lambda offset, label: (
            events.append(("resolve", label)) or (0x1000 if label == "ShrineLogs" else 0x2000)
        )
        client._read_shrine_log = lambda address: (
            events.append(("log", address)) or (DAMAGE,)
        )

        reading = client.get_charge_shrine_tracking_state()

        self.assertEqual(reading.charged_total, 1)
        self.assertEqual(reading.shown_log, (DAMAGE,))
        self.assertLess(events.index(("log", 0x3000)), events.index(("i32", 0x2058)))


class ChargeShrineRecordingTests(unittest.TestCase):
    def _shrines(self):
        stat = ChargeShrineStatSnapshot(
            stat_id=12,
            label="Damage",
            value=0.24,
            value_format=PlayerStatFormat.MULTIPLIER,
            rolls=2,
            rarity_counts=(("Common", 2),),
        )
        return ChargeShrineSnapshot(
            charged=4,
            selected=4,
            stats=(stat,),
        )

    def test_vod_round_trip_preserves_shrines(self):
        original = VodSnapshot(1, 2.0, {}, shrines=self._shrines())
        decoded = _record_to_snapshot(_snapshot_to_record(original))
        self.assertEqual(decoded.shrines, original.shrines)

    def test_old_vod_without_shrines_remains_readable(self):
        decoded = _record_to_snapshot(
            {"type": "snapshot", "elapsed_seconds": 1, "captured_at": 2.0, "stats": {}}
        )
        self.assertIsNone(decoded.shrines)

    def test_compare_table_contains_only_cumulative_stat_bonuses(self):
        snapshot_a = VodSnapshot(1, 2.0, {}, shrines=self._shrines())
        snapshot_b = VodSnapshot(1, 2.0, {}, shrines=None)
        table = build_compare_runs_shrines_table(snapshot_a, snapshot_b)

        self.assertEqual(len(table.sections), 1)
        self.assertEqual(table.sections[0].headers, ("Stat", "A", "B", "Diff"))
        self.assertEqual(len(table.sections[0].rows), 1)
        damage = table.sections[0].rows[0]
        self.assertEqual(damage.label, "Damage")
        self.assertEqual(
            (damage.value_a, damage.value_b, damage.delta),
            ("+24%", "--", "--"),
        )

    def test_compare_table_hides_counts_when_no_stat_bonus_was_recorded(self):
        empty_shrines = ChargeShrineSnapshot(charged=4, selected=4, stats=())
        snapshot_a = VodSnapshot(1, 2.0, {}, shrines=empty_shrines)
        snapshot_b = VodSnapshot(1, 2.0, {}, shrines=None)

        table = build_compare_runs_shrines_table(snapshot_a, snapshot_b)

        self.assertEqual(table.sections, ())
        self.assertEqual(table.empty_text, "No Charge Shrine data")


if __name__ == "__main__":
    unittest.main()
