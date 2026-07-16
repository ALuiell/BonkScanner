"""Value-format enums and the base scales stat values are rendered against.

Leaf of ``core.stats``: imports nothing local, so ``formatters`` and ``types``
can both depend on it without a cycle.
"""

from __future__ import annotations

from enum import Enum


class PlayerStatFormat(Enum):
    FLAT = "flat"
    PERCENT = "percent"
    MULTIPLIER = "multiplier"


class WeaponStatFormat(Enum):
    FLAT = "flat"
    PERCENT = "percent"
    MULTIPLIER = "multiplier"


PICKUP_RANGE_BASE_METERS = 9.0


CRIT_DAMAGE_BASE_MULTIPLIER = 2.0
