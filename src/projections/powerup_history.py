"""Prepared effect intervals and historical queries on recorded game clocks."""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass

from core.powerup_history import MAX_OBSERVATION_GAP, POWERUPS, PowerupHistory


def time_label(seconds: float) -> str:
    minutes, seconds = divmod(max(0, int(seconds)), 60)
    return f"{minutes:02d}:{seconds:02d}"


def duration_label(seconds: float) -> str:
    minutes, seconds = divmod(max(0, int(seconds + 1e-6)), 60)
    return f"{minutes}m {seconds:02d}s"


@dataclass(frozen=True, slots=True)
class EffectSpan:
    effect_id: int
    start_capture: float
    end_capture: float
    start_axis: float
    end_axis: float
    seconds: float


@dataclass(frozen=True)
class EffectAtCursor:
    effect_id: int
    start_axis: float
    end_axis: float


class PowerupProjection:
    def __init__(self, history: PowerupHistory | None = None, *, previous=None):
        self.history = history
        self.observations = history.observations if history is not None else ()
        if (previous is not None and (not previous.observations
                or len(self.observations) < len(previous.observations)
                or self.observations[:len(previous.observations)] != previous.observations)):
            previous = None
        offset = len(previous.observations) if previous is not None else 0
        self.capture_times = ((previous.capture_times if previous is not None else ())
                              + tuple(o.captured_at for o in self.observations[offset:]))
        spans = []
        coverage = []
        tail = self.observations[max(0, offset - 1):]
        for prior, current in zip(tail, tail[1:]):
            if not self._continuous(prior, current):
                continue
            coverage.append((prior.captured_at, current.captured_at))
            delta = current.my_time - prior.my_time
            if delta <= 0:
                continue
            effects = {e.effect_id: [e] for e in prior.effects}
            # A new pickup between two healthy polls carries its exact start.
            for effect in current.effects:
                candidates = effects.setdefault(effect.effect_id, [])
                extension = any(e.added == effect.added and e.expires > prior.my_time
                                and effect.expires > e.expires for e in candidates)
                if extension or (effect.added >= prior.my_time
                                 and not any(e.added == effect.added for e in candidates)):
                    candidates.append(effect)
            for effect_id, candidates in effects.items():
                intervals = []
                for start, end in sorted((max(prior.my_time, e.added), min(current.my_time, e.expires))
                                         for e in candidates):
                    if end <= start:
                        continue
                    if intervals and start <= intervals[-1][1]:
                        old_start, old_end = intervals.pop()
                        start, end = old_start, max(old_end, end)
                    intervals.append((start, end))
                for start, end in intervals:
                    low, high = (start - prior.my_time) / delta, (end - prior.my_time) / delta
                    def mix(a, b, fraction):
                        return a + (b - a) * fraction
                    spans.append(EffectSpan(
                        effect_id,
                        mix(prior.captured_at, current.captured_at, low),
                        mix(prior.captured_at, current.captured_at, high),
                        mix(prior.axis_time, current.axis_time, low),
                        mix(prior.axis_time, current.axis_time, high), end - start))
        merged_coverage = list(previous.coverage) if previous is not None else []
        for start, end in coverage:
            if merged_coverage and abs(merged_coverage[-1][1] - start) < 1e-6:
                start = merged_coverage.pop()[0]
            merged_coverage.append((start, end))
        self.coverage = tuple(merged_coverage)
        self.spans = (previous.spans if previous is not None else ()) + tuple(spans)
        self._effects = {}
        for effect_id, *_ in POWERUPS:
            added_parts = tuple(s for s in spans if s.effect_id == effect_id)
            old_parts, old_starts, old_prefix = (previous._effects[effect_id] if previous is not None
                                                else ((), (), (0.0,)))
            parts = old_parts + added_parts
            prefix = []
            total = old_prefix[-1]
            for span in added_parts:
                total += span.seconds
                prefix.append(total)
            self._effects[effect_id] = (parts, old_starts + tuple(s.start_capture for s in added_parts),
                                       old_prefix + tuple(prefix))
        # Merge touching pieces for paint geometry/tooltips, retaining gaps.
        merged = []
        for effect_id, *_ in POWERUPS:
            effect_parts = [s for s in previous.intervals if s.effect_id == effect_id] if previous is not None else []
            for span in (s for s in spans if s.effect_id == effect_id):
                if (effect_parts and abs(effect_parts[-1].end_capture - span.start_capture) < 1e-6):
                    old = effect_parts.pop()
                    span = EffectSpan(effect_id, old.start_capture, span.end_capture,
                                      old.start_axis, span.end_axis, old.seconds + span.seconds)
                effect_parts.append(span)
            merged.extend(effect_parts)
        self.intervals = tuple(merged)
        added_valid = tuple(o for o in self.observations[offset:] if o.valid)
        self._valid_observations = ((previous._valid_observations if previous is not None else ()) + added_valid)
        self._my_times = (previous._my_times if previous is not None else ()) + tuple(o.my_time for o in added_valid)
        self._prepare_pickups(offset, previous)

    def _prepare_pickups(self, offset, previous):
        # Use the same raw fields as the live widget: a new added time or an
        # increased expiry is evidence of a pickup, even while already active.
        # Retain signatures across missing reads so reconnecting does not count
        # an unchanged buff twice. Copy all state: live revisions are immutable.
        signatures = dict(previous._pickup_signatures) if previous is not None else {}
        last_valid = previous._pickup_last_valid if previous is not None else None
        added = {effect_id: [] for effect_id, *_ in POWERUPS}
        pending = list(previous._clock_pending) if previous is not None else []
        unknown = []
        warudo = []
        for index in range(offset, len(self.observations)):
            current = self.observations[index]
            # A second healthy inventory poll confirms a decrement or stable
            # stock. Never subtract one loss from every later Clock extension.
            for capture, before, observed in pending:
                source = self._clock_source(before, observed, current)
                if source == "clock":
                    added[4].append(capture)
                elif source == "za_warudo":
                    warudo.append(capture)
                else:
                    unknown.append(capture)
            pending = []
            if not current.valid:
                continue
            if last_valid is not None and (
                    current.my_time < last_valid.my_time
                    or (current.run_id is not None and last_valid.run_id is not None
                        and current.run_id != last_valid.run_id)):
                signatures.clear()
            prior = self.observations[index - 1] if index else None
            for effect in current.effects:
                if effect.effect_id not in added:
                    continue
                old = signatures.get(effect.effect_id)
                if old is None or effect.added != old.added or effect.expires > old.expires:
                    capture = current.captured_at
                    if (prior is not None and self._continuous(prior, current)
                            and current.my_time > prior.my_time
                            and (old is None or effect.added != old.added)
                            and prior.my_time <= effect.added <= current.my_time):
                        fraction = (effect.added - prior.my_time) / (current.my_time - prior.my_time)
                        capture = prior.captured_at + fraction * (current.captured_at - prior.captured_at)
                    # Extension timing is only known at the poll that saw it.
                    # Late-start and recovered effects are counted there too;
                    # do not invent a pickup time in an unobserved section.
                    if effect.effect_id != 4:
                        added[effect.effect_id].append(capture)
                    elif (prior is not None and self._continuous(prior, current)
                          and self._has_pickup_sources(prior) and self._has_pickup_sources(current)):
                        pending.append((capture, prior, current))
                    else:
                        # Legacy recordings and late attachment have no source
                        # evidence. TimeFreeze alone is not a Clock pickup.
                        unknown.append(capture)
                signatures[effect.effect_id] = effect
            last_valid = current
        self._pickup_signatures = signatures
        self._pickup_last_valid = last_valid
        self._pickup_times = {
            effect_id: (previous._pickup_times[effect_id] if previous is not None else ()) + tuple(times)
            for effect_id, times in added.items()
        }
        self._clock_pending = tuple(pending)
        self._clock_unknown = (previous._clock_unknown if previous is not None else ()) + tuple(unknown)
        self._warudo_times = (previous._warudo_times if previous is not None else ()) + tuple(warudo)

    @staticmethod
    def _has_pickup_sources(observation):
        return all(type(value) is int and 0 <= value <= 2**24
                   for value in (observation.za_warudo_count, observation.powerups_used))

    @classmethod
    def _clock_source(cls, before, observed, confirmation):
        if (not cls._continuous(observed, confirmation)
                or not cls._has_pickup_sources(confirmation)
                or confirmation.za_warudo_count != observed.za_warudo_count
                or confirmation.powerups_used < observed.powerups_used):
            return "unknown"
        lost = before.za_warudo_count - observed.za_warudo_count
        pickups = observed.powerups_used - before.powerups_used
        if lost == 1 and pickups == 0:
            return "za_warudo"
        if lost == 0 and pickups > 0:
            return "clock"
        # Loss + pickup can include Clock, Rage, or instant pickups in one
        # polling interval. Counter resets/gains and failed reads are unknown.
        return "unknown"

    def _unclassified_clock_count(self, low, high):
        return (bisect_right(self._clock_unknown, high) - bisect_right(self._clock_unknown, low)
                + sum(low < capture <= high for capture, *_ in self._clock_pending))

    def counts(self, capture_a, capture_b=None):
        """Confirmed observed pickups through A, or in (low, high] for A–B."""
        low, high = (float("-inf"), capture_a) if capture_b is None else sorted((capture_a, capture_b))
        return {effect_id: bisect_right(times, high) - bisect_right(times, low)
                for effect_id, times in self._pickup_times.items()}

    def unattributed_clock_events(self, capture_a, capture_b=None):
        """Pending/ambiguous freeze events, separate from confirmed pickups."""
        low, high = (float("-inf"), capture_a) if capture_b is None else sorted((capture_a, capture_b))
        return self._unclassified_clock_count(low, high)

    @staticmethod
    def _continuous(previous, current):
        return (previous.valid and current.valid
                and (previous.run_id == current.run_id or previous.run_id is None or current.run_id is None)
                and current.captured_at >= previous.captured_at
                and (current.captured_at - previous.captured_at <= MAX_OBSERVATION_GAP
                     or (current.my_time == previous.my_time and current.axis_time == previous.axis_time))
                and current.my_time >= previous.my_time
                # Boss entry can rewind runTimer by ~0.086 s while the effect
                # clock keeps advancing (mechanics/map_details_report.md).
                and current.axis_time + .1 >= previous.axis_time)

    @property
    def latest_capture(self):
        return self.capture_times[-1] if self.capture_times else 0.0

    @property
    def latest_axis(self):
        return next((o.axis_time for o in reversed(self.observations) if o.valid), 0.0)

    def _cumulative(self, effect_id, capture):
        parts, starts, prefix = self._effects[effect_id]
        at = bisect_right(starts, capture) - 1
        if at < 0:
            return 0.0
        span = parts[at]
        fraction = min(1.0, max(0.0, (capture - span.start_capture) /
                                max(span.end_capture - span.start_capture, 1e-12)))
        return prefix[at] + span.seconds * fraction

    def totals(self, capture_a, capture_b=None):
        low, high = (float("-inf"), capture_a) if capture_b is None else sorted((capture_a, capture_b))
        return {effect_id: max(0.0, self._cumulative(effect_id, high) - self._cumulative(effect_id, low))
                for effect_id, *_ in POWERUPS}

    def observed_at(self, capture):
        at = bisect_right(self.capture_times, capture) - 1
        if at < 0 or not self.observations[at].valid:
            return False
        observation = self.observations[at]
        if at + 1 < len(self.observations) and capture > observation.captured_at:
            return self._continuous(observation, self.observations[at + 1])
        return capture - observation.captured_at <= MAX_OBSERVATION_GAP

    def active(self, capture):
        at = bisect_right(self.capture_times, capture) - 1
        if not self.observed_at(capture):
            return ()
        observation = self.observations[at]
        if not observation.valid:
            return ()
        my_time, axis_time = observation.my_time, observation.axis_time
        if at + 1 < len(self.observations) and capture > observation.captured_at:
            following = self.observations[at + 1]
            if not self._continuous(observation, following):
                return ()
            fraction = (capture - observation.captured_at) / max(following.captured_at - observation.captured_at, 1e-12)
            my_time += (following.my_time - my_time) * fraction
            axis_time += (following.axis_time - axis_time) * fraction
        elif capture - observation.captured_at > MAX_OBSERVATION_GAP:
            return ()
        result = []
        for effect in observation.effects:
            if effect.added <= my_time < effect.expires:
                end = axis_time + effect.expires - my_time
                start = self._axis_at_my_time(effect.added, at)
                for span in self.intervals:
                    if span.effect_id == effect.effect_id and span.start_capture <= capture <= span.end_capture:
                        start = min(start, span.start_axis)
                        break
                result.append(EffectAtCursor(effect.effect_id, max(0.0, start), max(start, end)))
        return tuple(result)

    def _axis_at_my_time(self, target, until):
        from bisect import bisect_left
        at = bisect_left(self._my_times, target)
        if at >= len(self._valid_observations):
            return self.observations[until].axis_time
        observation = self._valid_observations[at]
        if observation.captured_at > self.capture_times[until]:
            return self.observations[until].axis_time
        previous = self._valid_observations[at - 1] if at else None
        if previous is not None and self._continuous(previous, observation):
            fraction = max(0.0, min(1.0, (target - previous.my_time) /
                                  max(observation.my_time - previous.my_time, 1e-12)))
            return previous.axis_time + fraction * (observation.axis_time - previous.axis_time)
        return observation.axis_time

    def complete(self, capture_a, capture_b=None):
        if not self.observations:
            return False
        low, high = (self.capture_times[0], capture_a) if capture_b is None else sorted((capture_a, capture_b))
        if capture_b is None and (not self.observations[0].valid or self.observations[0].axis_time > 1.5):
            return False
        cursor = low
        for start, end in self.coverage:
            if end < cursor:
                continue
            if start > cursor + 1e-6:
                return False
            cursor = max(cursor, end)
            if cursor >= high:
                return True
        return low == high and any(o.valid and o.captured_at == low for o in self.observations)

    def tooltip(self, effect_id, capture_a, capture_b=None):
        name = next(p[1] for p in POWERUPS if p[0] == effect_id)
        total = self.totals(capture_a, capture_b)[effect_id]
        low, high = (float("-inf"), capture_a) if capture_b is None else sorted((capture_a, capture_b))
        count = self.counts(capture_a, capture_b)[effect_id]
        unattributed = self.unattributed_clock_events(capture_a, capture_b) if effect_id == 4 else 0
        lines = [f"{name} · {duration_label(total)}",
                 f"Observed pickups: {count}{'+' if unattributed else ''}"]
        if effect_id == 4:
            excluded = bisect_right(self._warudo_times, high) - bisect_right(self._warudo_times, low)
            lines.append(f"Confirmed Clock pickups: {count}; excluded Za Warudo activations: {excluded}.")
            if unattributed:
                lines.append(f"Unattributed TimeFreeze events: {unattributed}. "
                             "'+' marks a confirmed minimum; actual Clock pickups may be higher.")
                lines.append("Clock attribution is pending, unavailable or ambiguous; TimeFreeze alone is not a pickup.")
            lines.append("Uptime includes all observed TimeFreeze, including Za Warudo.")
        lines.append("Repeat pickups count when expiry increases; several pickups between polls may count as one.")
        lines.append("Pickups with unknown timing count at first observation; A–B excludes its earlier endpoint.")
        for span in self.intervals:
            if span.effect_id == effect_id and span.end_capture > low and span.start_capture < high:
                first = self.axis_at_capture(max(low, span.start_capture))
                last = self.axis_at_capture(min(high, span.end_capture))
                lines.append(f"{time_label(first)} → {time_label(last)}")
        if not self.complete(capture_a, capture_b):
            lines.append("Partial observations; unobserved time is not counted.")
            observed = [(max(start, low), min(end, high)) for start, end in self.coverage
                        if end >= low and start <= high]
            for start, end in observed[:12]:
                lines.append(f"Observed: {time_label(self.axis_at_capture(start))} → "
                             f"{time_label(self.axis_at_capture(end))}")
            if len(observed) > 12:
                lines.append(f"… {len(observed) - 12} further observed sections")
        return "\n".join(lines)

    def axis_at_capture(self, capture):
        at = bisect_right(self.capture_times, capture) - 1
        if at < 0:
            return 0.0
        observation = self.observations[at]
        if not observation.valid:
            return 0.0
        if at + 1 < len(self.observations):
            following = self.observations[at + 1]
            if self._continuous(observation, following):
                fraction = (capture - observation.captured_at) / max(following.captured_at - observation.captured_at, 1e-12)
                return observation.axis_time + fraction * (following.axis_time - observation.axis_time)
        return observation.axis_time
