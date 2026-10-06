"""Recorded observations of timed effects, independent of the live card/PM."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


POWERUPS_SERIES = "@powerups"
# id, name, asset, color, normalized plot height
POWERUPS = (
    (1, "Rage", "rage", "#A558E7", .79),
    (2, "Shield", "shield", "#5CCD7F", .60),
    (3, "Stonks", "stonks", "#E7C758", .41),
    (4, "Clock", "clock", "#0096FF", .22),
)
MAX_OBSERVATION_GAP = 1.5


@dataclass(frozen=True)
class RecordedEffect:
    effect_id: int
    added: float
    expires: float


@dataclass(frozen=True)
class PowerupObservation:
    captured_at: float
    my_time: float | None
    axis_time: float | None
    run_id: str | None
    valid: bool
    effects: tuple[RecordedEffect, ...] = ()

    def to_record(self) -> dict:
        return dict(type="powerup_sample", captured_at=self.captured_at,
                    my_time=self.my_time, axis_time=self.axis_time,
                    run_id=self.run_id, valid=self.valid,
                    effects=[[e.effect_id, e.added, e.expires] for e in self.effects])

    @classmethod
    def from_record(cls, record: dict) -> "PowerupObservation":
        captured = float(record["captured_at"])
        if not isfinite(captured):
            raise ValueError("Invalid power-up capture time")
        my_time, axis_time = record.get("my_time"), record.get("axis_time")
        valid = record.get("valid") is True
        for value in (my_time, axis_time):
            if value is not None and (not isinstance(value, (int, float)) or not isfinite(value)):
                raise ValueError("Invalid power-up clock")
        effects = []
        for effect_id, added, expires in record.get("effects", ()):
            if effect_id not in (1, 2, 3, 4) or not all(isfinite(float(v)) for v in (added, expires)):
                raise ValueError("Invalid recorded power-up")
            if float(expires) < float(added):
                raise ValueError("Invalid recorded power-up interval")
            effects.append(RecordedEffect(effect_id, float(added), float(expires)))
        if valid and (my_time is None or axis_time is None):
            raise ValueError("Missing power-up clocks")
        return cls(captured, my_time, axis_time, record.get("run_id"), valid, tuple(effects))


@dataclass(frozen=True)
class PowerupHistory:
    observations: tuple[PowerupObservation, ...] = ()
    finalized: bool = False


def observation_from_snapshot(snapshot, run_id, *, captured_at: float) -> PowerupObservation:
    if snapshot is None:
        return PowerupObservation(captured_at, None, None, run_id, False)
    my_time = snapshot.my_time_seconds
    axis_time = snapshot.run_timer_seconds
    valid = all(h.available and h.complete for h in
                (snapshot.status_effects_health, snapshot.timing_health))
    valid = valid and all(v is not None and isfinite(float(v)) for v in (my_time, axis_time))
    effects = []
    if valid:
        for effect in snapshot.effects:
            if effect.effect_id not in (1, 2, 3, 4):
                continue
            if (not all(isfinite(float(v)) for v in (effect.added_time, effect.expiration_time))
                    or effect.expiration_time < effect.added_time or effect.added_time > my_time):
                valid = False
                break
            effects.append(RecordedEffect(effect.effect_id, effect.added_time, effect.expiration_time))
    return PowerupObservation(captured_at, my_time if valid else None,
                             axis_time if valid else None, run_id, bool(valid), tuple(effects) if valid else ())
