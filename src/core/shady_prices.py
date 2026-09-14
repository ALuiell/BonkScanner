"""Shady Guy economy, matching the game's float32 operations and rounding.

Validated against GetItemPriceShadyGuy/UpdatePrices and live 0/1/2-chest
samples. Slot multipliers belong to a visited merchant, not the item catalog.
"""
from dataclasses import dataclass
import math
import struct


def _f32(value: float) -> float:
    return struct.unpack('<f', struct.pack('<f', value))[0]


@dataclass(frozen=True, slots=True)
class ShadyEconomy:
    purchased: int
    stage_index: int
    price_multiplier: float
    base_price: int = 30
    increase: float = 1.22

    def valid(self) -> bool:
        return (
            0 <= self.purchased <= 10000 and 0 <= self.stage_index <= 100
            and 0 < self.base_price <= 1000000
            and math.isfinite(self.price_multiplier) and 0 <= self.price_multiplier <= 10000
            and math.isfinite(self.increase) and 1 <= self.increase <= 10
        )


def shady_price(economy: ShadyEconomy, rarity: str, slot_multiplier: float) -> int | None:
    factor = {'COMMON': 1, 'UNCOMMON': 2, 'RARE': 4, 'LEGENDARY': 8}.get(rarity)
    if not economy.valid() or factor is None or not math.isfinite(slot_multiplier) or not .5 <= slot_multiplier <= 1.5:
        return None
    try:
        exponent = _f32(_f32(economy.purchased) * _f32(.65))
        growth = _f32(math.pow(_f32(economy.increase), exponent))
        base = _f32(_f32(economy.base_price) * growth)
        base = _f32(base * _f32(economy.stage_index + 1))
        base = round(_f32(_f32(economy.price_multiplier) * base))
        tier = round(_f32(_f32(base) * factor))
        price = round(_f32(_f32(tier) * _f32(slot_multiplier)))
        return price if 0 <= price <= 2147483647 else None
    except (OverflowError, ValueError):
        return None


def format_shady_price(price: int | None) -> str:
    if price is None or price < 0:
        return '—'
    if price < 1000:
        return str(price)
    if price < 10000:
        whole, fraction = divmod(price // 100, 10)
        return f'{whole}.{fraction}k' if fraction else f'{whole}k'
    if price < 1000000:
        return f'{price // 1000}k'
    whole, fraction = divmod(price // 100000, 10)
    return f'{whole}.{fraction}m' if fraction else f'{whole}m'
