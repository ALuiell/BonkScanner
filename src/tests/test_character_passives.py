from __future__ import annotations

import unittest

from core.character_passives import (
    CHARACTER_PASSIVE_SPECS,
    CharacterPassiveReading,
    CharacterPassiveStatus,
)
from core.stats.formats import PlayerStatFormat
from core.stats.types import PlayerStatModifierSnapshot
from core.tracker import passives
from core.tracker.passives import _CharacterPassiveState, gamba_decay, gamba_roll_value
from core.tracker.shrines import SHRINE_STAT_RULES
from infra.memory.player_stats_client import PlayerStatsClient
from infra.memory.reader import MemoryReadError
from src.tests.test_player_stats import FakeMemory


def _modifier(
    ptr: int,
    stat_id: int,
    value: float,
) -> PlayerStatModifierSnapshot:
    rule = SHRINE_STAT_RULES[stat_id]
    return PlayerStatModifierSnapshot(
        stat_id=stat_id,
        label=rule.label,
        value=value,
        value_format=rule.value_format,
        object_ptr=ptr,
        modify_type=rule.modify_type,
    )


def _reading(character_id: int, **changes) -> CharacterPassiveReading:
    spec = next(spec for spec in CHARACTER_PASSIVE_SPECS if spec.character_id == character_id)
    values = dict(
        character_id=spec.character_id,
        character_name=spec.character_name,
        passive_id=spec.passive_id,
        passive_name=spec.passive_name,
        runtime_class=spec.runtime_class,
        passive_object_ptr=0x5000 + character_id,
        level=0,
    )
    values.update(changes)
    return CharacterPassiveReading(**values)


class CharacterPassiveCatalogTests(unittest.TestCase):
    def test_catalog_covers_all_21_characters_and_uses_dice_name(self) -> None:
        self.assertEqual([spec.character_id for spec in CHARACTER_PASSIVE_SPECS], list(range(21)))
        dice = CHARACTER_PASSIVE_SPECS[18]
        self.assertEqual(dice.character_name, "Dice")
        self.assertEqual(dice.passive_name, "Gamba")

    def test_approved_mvp_has_nine_linear_adapters_plus_gamba(self) -> None:
        self.assertEqual(sum(spec.linear is not None for spec in CHARACTER_PASSIVE_SPECS), 9)
        self.assertEqual(sum(spec.is_gamba for spec in CHARACTER_PASSIVE_SPECS), 1)


class LinearPassiveAdapterTests(unittest.TestCase):
    def test_fox_uses_runtime_modifier_as_authoritative_value(self) -> None:
        state = _CharacterPassiveState()
        modifier = PlayerStatModifierSnapshot(
            stat_id=30,
            label="Luck",
            value=2.5950000286102295,
            value_format=PlayerStatFormat.PERCENT,
            object_ptr=0x7000,
            modify_type=2,
        )
        passives.update(
            state,
            _reading(
                0,
                level=173,
                per_level=0.014999999664723873,
                passive_modifiers=(modifier,),
            ),
        )
        result = passives.snapshot(state)
        self.assertEqual(result.status, CharacterPassiveStatus.SUPPORTED)
        self.assertEqual(result.effects[0].value, modifier.value)
        self.assertEqual(result.effects[0].display_delta, "+259.5%")

    def test_linear_writer_window_is_published_as_updating(self) -> None:
        state = _CharacterPassiveState()
        modifier = PlayerStatModifierSnapshot(
            stat_id=0,
            label="Max HP",
            value=96.0,
            value_format=PlayerStatFormat.FLAT,
            object_ptr=0x7100,
            modify_type=2,
        )
        passives.update(
            state,
            _reading(11, level=49, per_level=2.0, passive_modifiers=(modifier,)),
        )
        result = passives.snapshot(state)
        self.assertEqual(result.status, CharacterPassiveStatus.UPDATING)
        self.assertEqual(result.effects[0].value, 96.0)
        self.assertEqual(result.effects[0].display_delta, "+96")

    def test_unsupported_character_keeps_identity_without_effects(self) -> None:
        state = _CharacterPassiveState()
        passives.update(state, _reading(1, level=100))
        result = passives.snapshot(state)
        self.assertEqual(result.character_name, "Calcium")
        self.assertEqual(result.passive_name, "Speed Demon")
        self.assertEqual(result.status, CharacterPassiveStatus.UNSUPPORTED)
        self.assertEqual(result.effects, ())


class GambaAdapterTests(unittest.TestCase):
    def test_decay_reference_and_clamp_boundary(self) -> None:
        self.assertEqual(gamba_decay(0), 0.75)
        self.assertAlmostEqual(gamba_decay(50), 0.375)
        self.assertAlmostEqual(gamba_decay(254), 0.06024222820997238)
        self.assertEqual(gamba_decay(255), gamba_decay(1000))
        self.assertAlmostEqual(gamba_roll_value(5, 1.4, 0), 0.05250000208616257)

    def test_delayed_counter_consumes_retained_candidate_once(self) -> None:
        state = _CharacterPassiveState()
        roll = _modifier(0x8000, 5, gamba_roll_value(5, 1.4, 0))
        common = dict(
            gamba_upgrade_multiplier=0.75,
            gamba_min_multiplier=0.06,
            gamba_max_multiplier=1.0,
        )
        passives.update(
            state,
            _reading(18, level=1, gamba_current_level=0, permanent_modifiers=(roll,), **common),
        )
        self.assertEqual(passives.snapshot(state).pending, 1)
        passives.update(
            state,
            _reading(18, level=1, gamba_current_level=1, permanent_modifiers=(roll,), **common),
        )
        result = passives.snapshot(state)
        self.assertEqual(result.status, CharacterPassiveStatus.SUPPORTED)
        self.assertEqual(result.effects[0].count, 1)
        self.assertAlmostEqual(result.effects[0].value, roll.value)
        self.assertEqual(result.pending, 0)

    def test_multiple_levels_and_repeated_stat_rolls_are_aggregated(self) -> None:
        state = _CharacterPassiveState()
        rolls = tuple(
            _modifier(0x9000 + index, 12, gamba_roll_value(12, 1.0, index))
            for index in range(4)
        )
        passives.update(
            state,
            _reading(
                18,
                level=4,
                gamba_current_level=4,
                gamba_upgrade_multiplier=0.75,
                gamba_min_multiplier=0.06,
                gamba_max_multiplier=1.0,
                permanent_modifiers=rolls,
            ),
        )
        result = passives.snapshot(state)
        self.assertEqual(result.status, CharacterPassiveStatus.SUPPORTED)
        self.assertEqual(result.effects[0].count, 4)
        self.assertAlmostEqual(result.effects[0].value, sum(roll.value for roll in rolls))

    def test_shrine_reserved_pointer_cannot_be_claimed(self) -> None:
        state = _CharacterPassiveState()
        roll = _modifier(0xA000, 5, gamba_roll_value(5, 1.2, 0))
        passives.update(
            state,
            _reading(
                18,
                level=1,
                gamba_current_level=1,
                gamba_upgrade_multiplier=0.75,
                gamba_min_multiplier=0.06,
                gamba_max_multiplier=1.0,
                permanent_modifiers=(roll,),
            ),
            reserved_modifier_ptrs=frozenset({roll.object_ptr}),
        )
        result = passives.snapshot(state)
        self.assertEqual(result.status, CharacterPassiveStatus.PARTIAL)
        self.assertEqual(result.effects, ())
        self.assertEqual(result.ambiguous, 1)


class CharacterPassiveMemoryReaderTests(unittest.TestCase):
    def _fox_memory(self, *, passive_id: int = 1) -> tuple[FakeMemory, int]:
        owner = 0x1000
        inventory = 0x2000
        character_data = 0x3000
        passive_data = 0x3100
        passive_object = 0x4000
        class_meta = 0x4100
        class_name = 0x4200
        player_xp = 0x5000
        outer = 0x6000
        outer_entries = 0x6100
        container = 0x6200
        inner = 0x6300
        inner_entries = 0x6400
        modifier = 0x6500
        outer_entry = outer_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET
        inner_entry = inner_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET
        memory = FakeMemory(
            pointers={
                owner + PlayerStatsClient.PLAYER_INVENTORY_OFFSET: inventory,
                inventory + PlayerStatsClient.CHARACTER_DATA_OFFSET: character_data,
                character_data + PlayerStatsClient.CHARACTER_DATA_PASSIVE_DATA_OFFSET: passive_data,
                inventory + PlayerStatsClient.PASSIVE_ABILITY_OFFSET: passive_object,
                passive_object + PlayerStatsClient.OBJECT_KLASS_OFFSET: class_meta,
                class_meta + PlayerStatsClient.KLASS_NAME_PTR_OFFSET: class_name,
                inventory + PlayerStatsClient.PLAYER_XP_OFFSET: player_xp,
                passive_object + PlayerStatsClient.PASSIVE_ABILITY_STAT_MODIFIERS_OFFSET: outer,
                outer + PlayerStatsClient.DICT_ENTRIES_OFFSET: outer_entries,
                outer_entry + PlayerStatsClient.DICT_ENTRY_VALUE_OFFSET: container,
                container + PlayerStatsClient.PASSIVE_STAT_MODIFIERS_CONTAINER_DICT_OFFSET: inner,
                inner + PlayerStatsClient.DICT_ENTRIES_OFFSET: inner_entries,
                inner_entry + PlayerStatsClient.DICT_ENTRY_VALUE_OFFSET: modifier,
            },
            ints={
                character_data + PlayerStatsClient.CHARACTER_DATA_CHARACTER_ID_OFFSET: 0,
                passive_data + PlayerStatsClient.PASSIVE_DATA_PASSIVE_ID_OFFSET: passive_id,
                player_xp + PlayerStatsClient.PLAYER_XP_LEVEL_OFFSET: 35,
                outer + PlayerStatsClient.DICT_COUNT_OFFSET: 1,
                outer_entry + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET: 1,
                outer_entry + PlayerStatsClient.DICT_ENTRY_KEY_OFFSET: 30,
                inner + PlayerStatsClient.DICT_COUNT_OFFSET: 1,
                inner_entry + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET: 1,
                inner_entry + PlayerStatsClient.DICT_ENTRY_KEY_OFFSET: 2,
                modifier + PlayerStatsClient.STAT_MODIFIER_STAT_OFFSET: 30,
            },
            floats={
                passive_object + PlayerStatsClient.PASSIVE_LINEAR_PER_LEVEL_OFFSET: 0.015,
                modifier + PlayerStatsClient.STAT_MODIFIER_VALUE_OFFSET: 0.5249999761581421,
            },
            ascii_strings={class_name: "PassiveAbilityRngBlessing"},
        )
        return memory, owner

    def test_reads_validated_fox_identity_runtime_field_and_owned_modifier(self) -> None:
        memory, owner = self._fox_memory()
        reading = PlayerStatsClient(memory=memory).get_character_passive_reading(owner)
        self.assertEqual(reading.character_name, "Fox")
        self.assertEqual(reading.passive_name, "RNG Blessing")
        self.assertEqual(reading.level, 35)
        self.assertAlmostEqual(reading.per_level, 0.015)
        self.assertEqual(len(reading.passive_modifiers), 1)
        self.assertEqual(reading.passive_modifiers[0].object_ptr, 0x6500)
        self.assertEqual(reading.passive_modifiers[0].modify_type, 2)

    def test_known_enum_mismatch_fails_closed(self) -> None:
        memory, owner = self._fox_memory(passive_id=15)
        with self.assertRaisesRegex(MemoryReadError, "enum mismatch"):
            PlayerStatsClient(memory=memory).get_character_passive_reading(owner)


if __name__ == "__main__":
    unittest.main()
