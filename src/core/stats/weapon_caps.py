"""Verified cap registry; see docs/mechanics/weapon_tracker_caps.md.

Projectile Count remains the underlying stat, even for hard spawn limits.
The cap describes its gameplay efficiency, not a replacement stat value.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from math import isfinite


@dataclass(frozen=True, slots=True)
class WeaponCap:
    kind: str = "none"
    value: float | None = None
    reached: bool = False
    note: str = ""


# (burstTime, minBurstInterval), from the verified current WeaponData assets.
PROJECTILE_BURSTS = {
    0: (1.0, .15), 1: (1.0, .10), 2: (.5, .10), 3: (1.1, .02),
    9: (.3, .04), 10: (1.0, .10), 11: (1.0, .10), 12: (.9, .10),
    13: (1.0, .10), 14: (.8, .04), 15: (1.0, .30),
    20: (1.0, .25), 21: (1.0, .20), 22: (1.5, .50), 23: (.5, .02),
    24: (.02, .02), 25: (1.1, .02), 26: (1.0, .15),
    27: (.75, .15), 28: (.75, .15), 30: (1.5, .10),
}
PROJECTILE_HARD_CAPS = {5: 80, 6: 80, 19: 49}


def projectile_cap(weapon_id: int, value: float, attack_speed: float | None) -> WeaponCap:
    if weapon_id in PROJECTILE_HARD_CAPS:
        cap = PROJECTILE_HARD_CAPS[weapon_id]
        return WeaponCap("hard", cap, value >= cap)
    if weapon_id == 29:
        return WeaponCap("special_soft", 18, value >= 18,
                         "Pellets saturated; damage still scales")
    if weapon_id == 7:
        return WeaponCap(note="No confirmed gameplay cap; renderer limit excluded")
    if weapon_id not in PROJECTILE_BURSTS:
        return WeaponCap("unavailable")
    if attack_speed is None or not isfinite(attack_speed) or attack_speed <= 0:
        return WeaponCap("dynamic_soft", note="Attack Speed unavailable")
    burst, minimum = PROJECTILE_BURSTS[weapon_id]
    # Decimal preserves exact registry boundaries (e.g. 0.9 / 0.1 = 9).
    interval = max(Decimal(str(minimum)), Decimal("0.02") * Decimal(str(attack_speed)))
    cap = max(1, int((Decimal(str(burst)) / interval).to_integral_value(rounding=ROUND_FLOOR)))
    return WeaponCap("dynamic_soft", cap, value >= cap)


def clamped_stat_cap(cap: float | bool | None, value: float, *, minimum: float) -> WeaponCap:
    if cap is None or cap is False:
        return WeaponCap("unavailable")
    if cap > minimum:
        return WeaponCap("hard", cap, value >= cap)
    return WeaponCap()
