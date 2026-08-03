"""The item-cooldown overlay: projection, render, and the lifecycle gate.

The gate is the test that matters. On the death screen the game clock freezes
bit-exact and every memory read keeps succeeding -- measured, 256 consecutive
successful reads over 26 s -- so neither a TTL nor a read failure will ever
clear the display. Pause produces a byte-identical freeze where holding the
value is *correct*. Only `RunLifecycle` separates them.
"""
from __future__ import annotations

import src  # noqa: F401  -- puts `src/` on sys.path regardless of collection order

import re
import unittest
from dataclasses import dataclass
from html import unescape

from core.stats.types import ItemCooldownReading, ItemCooldownSnapshot
from core.tracker.snapshots import RunLifecycle
from projections.in_game_html import build_item_cooldowns_overlay_html


@dataclass
class FakeProjection:
    item_cooldowns: object | None = None
    run_completed: bool = False


def snapshot(*readings: ItemCooldownReading, my_time: float = 100.0) -> ItemCooldownSnapshot:
    return ItemCooldownSnapshot(my_time_seconds=my_time, readings=readings)


def visible_text(html: str) -> str:
    """What the player actually reads, with the markup taken away."""
    return unescape(re.sub(r"<[^>]*>", " ", html))


def lantern(*, next_trigger: float, stacks: int = 1, name: str = "Bob's Light"):
    return ItemCooldownReading(
        item_id=85,
        name=name,
        stack_count=stacks,
        cooldown_seconds=max(5.0, 45.0 - 3.0 * stacks),
        next_trigger_time=next_trigger,
    )


class CountdownRenderTests(unittest.TestCase):
    def test_the_countdown_is_the_mark_minus_the_carried_clock(self) -> None:
        html = build_item_cooldowns_overlay_html(
            FakeProjection(item_cooldowns=snapshot(lantern(next_trigger=126.5), my_time=100.0))
        )
        # Truncated, never rounded up: a countdown must not claim more time
        # than remains. 26.5 s left reads as 26.
        self.assertIn("26s", html)

    def test_a_negative_remaining_clamps_to_zero(self) -> None:
        """The mark goes past the clock between a trigger and the pass that
        sees the re-arm. `-0.01 s` was measured at 250 ms; on the 1 s lane the
        window is a whole second wide, so the value can reach `-1.x`.

        **Exercised at -1.5, not at -0.01.** Truncation alone renders `-0.01` as
        `0s`, so a test at that value passes with the clamp deleted -- proved by
        a tamper run. Only a magnitude above one second distinguishes the two.
        """
        html = build_item_cooldowns_overlay_html(
            FakeProjection(item_cooldowns=snapshot(lantern(next_trigger=98.5), my_time=100.0))
        )
        self.assertIn(": 0s", html)
        # Against the rendered *text*, not the markup: the text shadow's CSS is
        # full of `-1px`, so scanning the raw HTML for a minus proves nothing.
        self.assertNotIn("-", visible_text(html))

    def test_a_barely_negative_remaining_also_reads_as_zero(self) -> None:
        """The measured case, kept beside the one that has teeth."""
        html = build_item_cooldowns_overlay_html(
            FakeProjection(item_cooldowns=snapshot(lantern(next_trigger=99.99), my_time=100.0))
        )
        self.assertIn(": 0s", html)

    def test_the_stack_count_is_not_rendered(self) -> None:
        """One row per item, name and countdown only.

        A late inventory can hold a lot of timed items, and a stack suffix on
        every row buys width that the countdown needs -- the effective cooldown
        already reflects the stack, so the number was saying it twice.
        """
        html = visible_text(
            build_item_cooldowns_overlay_html(
                FakeProjection(item_cooldowns=snapshot(lantern(next_trigger=130.0, stacks=4)))
            )
        )
        self.assertIn("Bob's Light: 30s", html)
        self.assertNotIn("x4", html)

    def test_a_row_under_five_seconds_turns_critical(self) -> None:
        from projections.in_game_html import CRITICAL_COLOR

        near = build_item_cooldowns_overlay_html(
            FakeProjection(item_cooldowns=snapshot(lantern(next_trigger=103.0), my_time=100.0))
        )
        far = build_item_cooldowns_overlay_html(
            FakeProjection(item_cooldowns=snapshot(lantern(next_trigger=130.0), my_time=100.0))
        )
        self.assertIn(CRITICAL_COLOR, near)
        self.assertNotIn(CRITICAL_COLOR, far)

    def test_every_row_carries_the_text_shadow(self) -> None:
        from projections.in_game_html import TEXT_SHADOW

        html = build_item_cooldowns_overlay_html(
            FakeProjection(item_cooldowns=snapshot(lantern(next_trigger=130.0)))
        )
        self.assertEqual(html.count(TEXT_SHADOW), html.count("<span"))

    def test_a_row_is_coloured_by_the_item_s_rarity(self) -> None:
        from core.item_metadata import ITEM_RARITY_COLOR_MAP

        html = build_item_cooldowns_overlay_html(
            FakeProjection(item_cooldowns=snapshot(lantern(next_trigger=130.0)))
        )
        self.assertIn(ITEM_RARITY_COLOR_MAP["RARE"], html)

    def test_two_items_of_different_rarity_get_different_colours(self) -> None:
        from core.item_metadata import ITEM_RARITY_COLOR_MAP

        legendary = ItemCooldownReading(
            item_id=54, name="Holy Book", stack_count=1,
            cooldown_seconds=8.0, next_trigger_time=130.0,
        )
        html = build_item_cooldowns_overlay_html(
            FakeProjection(
                item_cooldowns=snapshot(lantern(next_trigger=130.0), legendary)
            )
        )
        self.assertIn(ITEM_RARITY_COLOR_MAP["RARE"], html)
        self.assertIn(ITEM_RARITY_COLOR_MAP["LEGENDARY"], html)

    def test_an_unknown_item_falls_back_rather_than_failing(self) -> None:
        from projections.in_game_html import FALLBACK_COLOR

        unknown = ItemCooldownReading(
            item_id=9999, name="Mystery Item", stack_count=1,
            cooldown_seconds=10.0, next_trigger_time=130.0,
        )
        html = build_item_cooldowns_overlay_html(
            FakeProjection(item_cooldowns=snapshot(unknown))
        )
        self.assertIn(FALLBACK_COLOR, html)
        self.assertIn("Mystery Item", visible_text(html))

    def test_no_powerup_colour_equals_a_rarity_colour(self) -> None:
        """The two blocks share a screen; a shared colour implies a shared meaning.

        `POWERUP_COLORS["Rage"]` used to be `#e879f9`, byte-identical to the
        rare tier. That was harmless until cooldown rows started colouring by
        rarity -- then a Rage row and a rare item's countdown could land one
        line apart in the same colour. The guard lives here rather than beside
        the palette because the collision only becomes meaningful once this
        widget exists.
        """
        from core.item_metadata import ITEM_RARITY_COLOR_MAP
        from projections.in_game_html import POWERUP_COLORS

        rarity = {c.lower() for c in ITEM_RARITY_COLOR_MAP.values()}
        clash = {name: c for name, c in POWERUP_COLORS.items() if c.lower() in rarity}
        self.assertEqual(clash, {}, f"powerup colours colliding with a rarity tier: {clash}")

    def test_no_powerup_row_is_dimmer_than_the_block_it_is_scanned_with(self) -> None:
        """The Powerups block is read as a group, so one dark row is a defect.

        Rage shipped at `#a855f7`, relative luminance 0.215, while Shield,
        Stonks, Clock and Timestomp ran 0.53-0.75. Over grass and water it was
        the only row that went muddy, and it was reported from a live stream
        rather than by any test here -- every existing guard checked *which*
        colour, never whether it could be seen.

        The floor is stated as an absolute rather than as a spread around the
        block's mean, so adding a fifth dim colour cannot drag the bar down to
        meet itself. 0.45 sits below Timestomp, the darkest of the four that
        were never in question.
        """
        from projections.in_game_html import POWERUP_COLORS

        def relative_luminance(hex_colour: str) -> float:
            channels = []
            for offset in (1, 3, 5):
                value = int(hex_colour[offset:offset + 2], 16) / 255
                channels.append(
                    value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
                )
            red, green, blue = channels
            return 0.2126 * red + 0.7152 * green + 0.0722 * blue

        dim = {
            name: (colour, round(relative_luminance(colour), 3))
            for name, colour in POWERUP_COLORS.items()
            if relative_luminance(colour) < 0.45
        }
        self.assertEqual(dim, {}, f"powerup colours too dark to scan with the block: {dim}")

    def test_every_layout_entry_has_a_known_rarity(self) -> None:
        """The guard the per-item colour table used to provide.

        Rarity replaces that table, so the drift risk moves: an item can now be
        added to the layout table while the rarity catalog has never heard of
        it, and the row would ship in the fallback colour. Checked here rather
        than discovered on stream. `ITEM_RARITY_BY_NAME` covers all three of the
        classes still queued for this widget, so this is a low bar that only
        fails on a genuinely new name.
        """
        from core.item_metadata import (
            ITEM_ENUM_NAMES_BY_ID,
            ITEM_RARITY_BY_NAME,
            normalize_item_name_for_rarity,
        )
        from infra.memory.player_stats_client import (
            ITEM_COOLDOWN_LAYOUTS,
            PlayerStatsClient,
        )

        missing = []
        for item_id in ITEM_COOLDOWN_LAYOUTS:
            enum_name = ITEM_ENUM_NAMES_BY_ID.get(item_id)
            # Through the client's own formatter, because that is what fills
            # `ItemCooldownReading.name` and therefore what the renderer looks
            # the rarity up by. Normalising the raw `Item<Enum>` instead is a
            # different string -- `ItemBobsLantern` does not fold to
            # `Bobs Lantern` -- and a test built on it reports a failure the
            # renderer does not have.
            display_name = PlayerStatsClient._format_item_name(f"Item{enum_name}")
            canonical = normalize_item_name_for_rarity(display_name or "")
            if canonical not in ITEM_RARITY_BY_NAME:
                missing.append((item_id, enum_name, display_name, canonical))
        self.assertEqual(missing, [], f"cooldown items with no known rarity: {missing}")


class HiddenWhenNothingToSayTests(unittest.TestCase):
    def test_no_reading_renders_nothing(self) -> None:
        self.assertEqual(build_item_cooldowns_overlay_html(FakeProjection()), "")

    def test_an_empty_reading_renders_nothing(self) -> None:
        """No timed item held is not a state worth a caption."""
        self.assertEqual(
            build_item_cooldowns_overlay_html(FakeProjection(item_cooldowns=snapshot())), ""
        )

    def test_a_missing_clock_renders_nothing(self) -> None:
        """Without the clock there is no countdown, only a mark nobody can read."""
        broken = ItemCooldownSnapshot(my_time_seconds=None, readings=(lantern(next_trigger=1.0),))
        self.assertEqual(
            build_item_cooldowns_overlay_html(FakeProjection(item_cooldowns=broken)), ""
        )

    def test_edit_mode_draws_a_placeholder_so_the_widget_can_be_grabbed(self) -> None:
        html = build_item_cooldowns_overlay_html(FakeProjection(), edit_mode=True)
        self.assertIn("preview", html.lower())


class LifecycleGateTests(unittest.TestCase):
    def test_a_completed_run_renders_nothing_even_with_a_fresh_reading(self) -> None:
        """The death-screen case, which nothing else can catch.

        The reading is valid, fresh, and will stay both forever: the clock is
        frozen and every read succeeds. A TTL sees no failure to retire.
        """
        live = snapshot(lantern(next_trigger=3596.12), my_time=3581.54)
        self.assertIn("14s", build_item_cooldowns_overlay_html(FakeProjection(item_cooldowns=live)))
        self.assertEqual(
            build_item_cooldowns_overlay_html(
                FakeProjection(item_cooldowns=live, run_completed=True)
            ),
            "",
            "a finished run still rendered a countdown",
        )

    def test_a_frozen_clock_alone_does_not_hide_the_widget(self) -> None:
        """Pause freezes the clock identically and must keep showing the value.

        This is the other half of the gate: if the renderer tried to detect the
        death screen from the reading itself, it would blank the widget every
        time the player opened a menu.
        """
        frozen = snapshot(lantern(next_trigger=130.0), my_time=100.0)
        first = build_item_cooldowns_overlay_html(FakeProjection(item_cooldowns=frozen))
        again = build_item_cooldowns_overlay_html(FakeProjection(item_cooldowns=frozen))
        self.assertEqual(first, again)
        self.assertIn("30s", first)

    def test_edit_mode_still_shows_the_widget_after_a_completed_run(self) -> None:
        """Otherwise the widget cannot be positioned except during a live run."""
        html = build_item_cooldowns_overlay_html(
            FakeProjection(item_cooldowns=snapshot(), run_completed=True), edit_mode=True
        )
        self.assertNotEqual(html, "")


class ProjectionTests(unittest.TestCase):
    def test_the_reading_and_the_lifecycle_reach_the_projection(self) -> None:
        """Anything not carried here is invisible to the widgets.

        That is documented on the dataclass and has already shipped as a bug
        once, which is why it is asserted rather than assumed.
        """
        from projections.in_game import project_in_game_overlay

        reading = snapshot(lantern(next_trigger=130.0))

        class FakeRuntime:
            latest_snapshot = None
            kps: dict = {}
            powerups = None
            powerup_map_context = None
            fast_stage_timer = None
            graveyard_main_map_events_active = False
            luck = None
            loot_stats = None
            item_cooldowns = reading
            lifecycle = RunLifecycle.ACTIVE

        projection = project_in_game_overlay(FakeRuntime())
        self.assertIs(projection.item_cooldowns, reading)
        self.assertFalse(projection.run_completed)

        FakeRuntime.lifecycle = RunLifecycle.COMPLETED
        self.assertTrue(project_in_game_overlay(FakeRuntime()).run_completed)

    def test_a_waiting_run_is_not_treated_as_completed(self) -> None:
        from projections.in_game import project_in_game_overlay

        class FakeRuntime:
            latest_snapshot = None
            kps: dict = {}
            powerups = None
            powerup_map_context = None
            fast_stage_timer = None
            graveyard_main_map_events_active = False
            luck = None
            loot_stats = None
            item_cooldowns = None
            lifecycle = RunLifecycle.WAITING

        self.assertFalse(project_in_game_overlay(FakeRuntime()).run_completed)


class TrackerPublishTests(unittest.TestCase):
    def _tracker(self):
        from core.tracker.live_run import LiveRunTracker

        return LiveRunTracker()

    def test_a_published_reading_comes_back(self) -> None:
        tracker = self._tracker()
        reading = snapshot(lantern(next_trigger=130.0))
        tracker.update_item_cooldowns(reading)
        self.assertIs(tracker.item_cooldowns(), reading)

    def test_none_clears_rather_than_storing_a_blank(self) -> None:
        """A failed pass and an inventory with no timed item are different facts.

        Only the second may render as "nothing to show"; the first has to let
        the TTL retire the last good value instead of overwriting it.
        """
        tracker = self._tracker()
        tracker.update_item_cooldowns(snapshot(lantern(next_trigger=130.0)))
        tracker.update_item_cooldowns(None)
        self.assertIsNone(tracker.item_cooldowns())

    def test_a_stale_reading_expires(self) -> None:
        from core.tracker.live_run import FAST_ITEM_COOLDOWNS_TTL_SECONDS

        now = [1000.0]
        tracker = self._tracker()
        tracker.clock = lambda: now[0]
        tracker.update_item_cooldowns(snapshot(lantern(next_trigger=130.0)))

        now[0] += FAST_ITEM_COOLDOWNS_TTL_SECONDS - 0.1
        self.assertIsNotNone(tracker.item_cooldowns())
        now[0] += 0.2
        self.assertIsNone(tracker.item_cooldowns())

    def test_the_gate_closes_through_the_real_mark_run_completed_path(self) -> None:
        """End to end: tracker -> runtime snapshot -> projection -> render.

        The projection tests above set `lifecycle` on a fake runtime, which
        proves the mapping and nothing about the wiring. A smoke run through
        the real chain found what they could not: `mark_run_completed` is a
        **no-op while the run has produced no snapshots**, so the gate has a
        precondition, and a run ending before its first 10 s snapshot would
        leave the countdown frozen on screen. Unreachable in practice -- the
        player has to pick the item up first -- but it is a precondition, not
        an invariant, and it is asserted here rather than assumed.
        """
        from core.tracker.snapshots import LiveRunSnapshot
        from projections.in_game import project_in_game_overlay

        tracker = self._tracker()
        tracker.update_item_cooldowns(snapshot(lantern(next_trigger=3596.12), my_time=3581.54))

        tracker.mark_run_completed()
        self.assertFalse(
            project_in_game_overlay(tracker.runtime_snapshot()).run_completed,
            "mark_run_completed is documented as requiring a stored snapshot",
        )

        tracker.snapshots.append(
            LiveRunSnapshot(
                captured_at=0.0, stats={}, game_time_seconds=1.0, mob_kills=0, stage_index=0
            )
        )
        tracker.mark_run_completed()

        projection = project_in_game_overlay(tracker.runtime_snapshot())
        self.assertTrue(projection.run_completed)
        self.assertEqual(
            build_item_cooldowns_overlay_html(projection),
            "",
            "the countdown survived the end of the run",
        )

    def test_a_new_run_clears_the_previous_run_s_reading(self) -> None:
        """`MyTime.time` survives a run boundary -- measured, 2231 -> 2739 with
        no reset -- so a mark left from the previous run would subtract into a
        perfectly plausible countdown in the next one.
        """
        tracker = self._tracker()
        tracker.update_item_cooldowns(snapshot(lantern(next_trigger=130.0)))
        tracker._reset_for_new_run()
        self.assertIsNone(tracker.item_cooldowns())


if __name__ == "__main__":
    unittest.main()
