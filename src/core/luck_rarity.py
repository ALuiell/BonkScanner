"""The game's item-rarity roll, reimplemented from its own disassembly.

``Rarity.CalculateRarityWeights(float[], float)`` (RVA ``0x42D1B0``) computes
``S = ln(luck + 1.0) * 1.5`` and then ``W_i = Base_i * 1.5^(-k_i * S)``, where
``k_i = length - 1 - i`` over an array of exactly four base weights --
``70 / 15 / 6 / 1.5`` -- and normalizes by their sum.  Luck arrives as a
*fraction*: ``0.5`` means "+50%".

Lived in ``projections/in_game_html.py`` until the loot tracker needed it.
``core/`` may not import ``projections/`` (the §2 layer table), and the model
is not a rendering concern in the first place -- the overlay's percentage row
and the tracker's expectation accumulator are two consumers of one game rule.
``in_game_html`` re-exports these names, so nothing that imported them from
there had to move.
"""
from __future__ import annotations

from math import isfinite, log

LUCK_RARITY_BASE_WEIGHTS: dict[str, float] = {
    "COMMON": 70.0,
    "UNCOMMON": 15.0,
    "RARE": 6.0,
    "LEGENDARY": 1.5,
}
LUCK_RARITY_ORDER: tuple[str, ...] = ("LEGENDARY", "RARE", "UNCOMMON", "COMMON")
_LUCK_RARITY_EXPONENTS: dict[str, int] = {
    "COMMON": 3,
    "UNCOMMON": 2,
    "RARE": 1,
    "LEGENDARY": 0,
}


# Our four tier keys spelled the way the *game* spells them. The two schemes
# are offset by one tier in the middle: `EItemRarity` runs
# ``Common / Rare / Epic / Legendary`` over the same four droppable tiers our
# ``ITEMS`` table labels ``COMMON / UNCOMMON / RARE / LEGENDARY``, so our
# ``UNCOMMON`` is the game's ``Rare`` and our ``RARE`` is its ``Epic``.
#
# Invisible on every surface that carries colour instead of words, and actively
# wrong on the one that does not: a viewer reading "Rare" in chat pictures the
# blue tier while we mean the purple one. Chat is the only surface with words,
# so this table has exactly one consumer -- and it lives here, beside the order
# it is keyed by, rather than in the bot, so a second worded surface cannot
# invent its own.
GAME_RARITY_NAMES: dict[str, str] = {
    "LEGENDARY": "Legendary",
    "RARE": "Epic",
    "UNCOMMON": "Rare",
    "COMMON": "Common",
}


# Shown wherever the expected figures are configured or displayed. The numbers
# are a *stated model* -- the game's own roll, read out of its disassembly --
# rather than our claim about how lucky a run was, and a surface that does not
# say so invites the reading that we made them up.
LUCK_RARITY_MODEL_ATTRIBUTION = (
    "Expected counts come from the game's own rarity roll "
    "(Rarity.CalculateRarityWeights, base weights 70/15/6/1.5), accumulated "
    "against the Luck held at each item gain. Requires the app to have been "
    "running from the start of the run."
)


def format_expected_count(value: float | None, *, whole: bool = False) -> str:
    """An expectation as text: one decimal below 10, whole numbers above.

    Dropping the tenths outright turns ``1 (0.8)`` into ``1 (1)``, which reads
    as "exactly on expectation" when the player was in fact ahead, and
    ``0 (0.4)`` into ``0 (0)``, as if nothing had been expected at all. Above 10
    the tenth is noise beside a count that size, and it costs width every
    surface here is short of.

    ``whole`` forces the rounded form at every size, and has exactly one
    caller: the OBS overlay's ``row`` layout. That layout puts four groups on a
    single line inside a scene that is usually narrower than the game HUD, so
    the tenth is what gives first. The reading above is the cost, and it is the
    reason this is one surface's opt-in rather than a change to the rule.
    """
    if value is None:
        return "--"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"
    if not isfinite(number):
        return "--"
    number = max(0.0, number)
    if number < 10.0 and not whole:
        return f"{number:.1f}"
    return f"{number:.0f}"


# The expected frame's two failure states, worded so a player can tell them
# apart from a toggle left off or a widget dragged out of view. Resolved once,
# here, so the in-game Qt overlay and the browser/OBS overlay cannot drift onto
# different wording for the same state -- and so neither has to know the other
# exists.
#
# Kept to a few words each because these sit in the expected frame's place
# inside the Luck widget, and that widget is only as wide as its percentage
# row. A sentence has to wrap to two or three lines there, which is a lot of
# screen for "nothing to show yet"; the prefix it lost said only what the
# surrounding widget already says.
LUCK_EXPECTED_UNAVAILABLE_MESSAGE = "Missed run start"
LUCK_EXPECTED_PENDING_MESSAGE = "Waiting for first item"


def resolve_luck_expected_status_text(*, available: bool, availability_decided: bool) -> str:
    """The text that replaces the expected frame, or "" to draw the figures.

    Two distinct unmeasurable states, not one: before the loot tracker decides,
    the answer is still coming, and telling a player their run is spoiled while
    it is merely young would be the one error this message could make. Once
    decided-and-unavailable, the block cannot recover for the rest of the run.

    A caller must gate this on its own "show expected" toggle first -- when the
    toggle is off, nothing should be drawn, and this function has no way to
    know that; it only distinguishes the two reasons figures are missing once
    someone already wants them shown.
    """
    if available:
        return ""
    if availability_decided:
        return LUCK_EXPECTED_UNAVAILABLE_MESSAGE
    return LUCK_EXPECTED_PENDING_MESSAGE


def format_luck_rarity_percent(value: float | None) -> str:
    if value is None:
        return "--"
    return f"{float(value):.2f}%"


def calculate_luck_rarity_probabilities(luck_value: float | None) -> dict[str, float | None]:
    if luck_value is None:
        return {rarity: None for rarity in LUCK_RARITY_ORDER}
    try:
        luck_value = float(luck_value)
    except (TypeError, ValueError):
        return {rarity: None for rarity in LUCK_RARITY_ORDER}
    if not isfinite(luck_value):
        return {rarity: None for rarity in LUCK_RARITY_ORDER}

    adjusted_luck = max(luck_value, -0.999999999)
    strength = log(adjusted_luck + 1.0) * 1.5

    weights: dict[str, float] = {}
    for rarity, base_weight in LUCK_RARITY_BASE_WEIGHTS.items():
        exponent = _LUCK_RARITY_EXPONENTS[rarity] * strength
        weights[rarity] = base_weight * (1.5 ** (-exponent))

    total_weight = sum(weights.values())
    if total_weight <= 0 or not isfinite(total_weight):
        return {rarity: None for rarity in LUCK_RARITY_ORDER}

    return {
        rarity: (weights[rarity] / total_weight) * 100.0
        for rarity in LUCK_RARITY_ORDER
    }
