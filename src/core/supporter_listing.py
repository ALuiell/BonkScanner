"""Public supporter data shared by network loading and Qt presentation."""
from dataclasses import dataclass


@dataclass(frozen=True)
class FounderSlots:
    used: int
    limit: int
    remaining: int

    @classmethod
    def parse(cls, value):
        if not isinstance(value, dict):
            return None
        numbers = [value.get(key) for key in ("used", "limit", "remaining")]
        if any(type(number) is not int for number in numbers):
            return None
        used, limit, remaining = numbers
        if used < 0 or limit < 1 or used > limit or remaining != limit - used:
            return None
        return cls(used, limit, remaining)


@dataclass(frozen=True)
class SupporterDirectory:
    # None means a failed refresh; an empty tuple is a successful empty list.
    supporters: tuple | None
    founder_slots: FounderSlots | None = None
