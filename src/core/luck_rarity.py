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
