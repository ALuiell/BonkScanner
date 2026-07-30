from __future__ import annotations

import src  # noqa: F401  -- path bootstrap

from core.stats.types import PLAYER_STAT_SPEC_BY_LABEL
from ui.tabs.player_stats.recordings import SCRUBBER_STAT_GROUPS


def test_graph_menu_uses_the_requested_stat_groups() -> None:
    groups = dict(SCRUBBER_STAT_GROUPS)

    assert tuple(groups) == (
        "Survivability",
        "Dmg",
        "Effects",
        "Mobility",
        "Rewards & Spawns",
    )
    assert groups["Mobility"] == ("Extra Jumps", "Jump Height", "Movement Speed")
    assert "Movement Speed" not in groups["Effects"]
    assert {"Luck", "Difficulty"} <= set(groups["Rewards & Spawns"])


def test_graph_menu_contains_every_player_stat_once() -> None:
    grouped_labels = [
        stat_label
        for _group_label, stat_labels in SCRUBBER_STAT_GROUPS
        for stat_label in stat_labels
    ]

    assert len(grouped_labels) == len(set(grouped_labels))
    assert set(grouped_labels) == set(PLAYER_STAT_SPEC_BY_LABEL)
