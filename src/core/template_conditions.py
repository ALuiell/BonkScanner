"""Shared schema, validation, and presentation for template conditions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TemplateCounter:
    key: str
    stat_name: str
    label: str

    @property
    def maximum_key(self) -> str:
        return f"{self.key}_max"


TEMPLATE_COUNTERS = (
    TemplateCounter("shady", "Shady Guy", "S"),
    TemplateCounter("moai", "Moais", "M"),
    TemplateCounter("micro", "Microwaves", "Mic"),
    TemplateCounter("boss", "Boss Curses", "B"),
    TemplateCounter("magnet", "Magnet Shrines", "Mag"),
    TemplateCounter("challenges", "Challenges", "Ch"),
    TemplateCounter("bald_heads", "Bald Heads", "BH"),
)

TEMPLATE_CONDITION_KEYS = {
    "sm_total",
    "magnet_shrines",
    *(counter.key for counter in TEMPLATE_COUNTERS),
    *(counter.maximum_key for counter in TEMPLATE_COUNTERS),
}


def condition_minimum(template: dict, key: str) -> int:
    """Return a non-negative minimum, including the legacy Magnet spelling."""
    value = (
        template.get("magnet", template.get("magnet_shrines", 0))
        if key == "magnet"
        else template.get(key, 0)
    )
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def condition_maximum(template: dict, key: str) -> int | None:
    """Return an inclusive maximum; a missing/blank key means no upper limit."""
    maximum_key = f"{key}_max"
    if maximum_key not in template or template.get(maximum_key) in (None, ""):
        return None
    try:
        return max(0, int(template[maximum_key]))
    except (TypeError, ValueError):
        return None


def validate_template_ranges(template: dict) -> str | None:
    """Describe the first invalid min/max pair, or return ``None``."""
    for counter in TEMPLATE_COUNTERS:
        minimum = condition_minimum(template, counter.key)
        maximum = condition_maximum(template, counter.key)
        if maximum is not None and minimum > maximum:
            return (
                f"{counter.stat_name}: minimum {minimum} cannot be greater "
                f"than maximum {maximum}."
            )
    return None


def format_template_conditions(template: dict) -> str:
    """Render every configured bound for cards, logs, and chat output."""
    parts: list[str] = []
    try:
        sm_total = max(0, int(template.get("sm_total", 0)))
    except (TypeError, ValueError):
        sm_total = 0
    if sm_total > 0:
        parts.append(f"S+M≥{sm_total}")

    for counter in TEMPLATE_COUNTERS:
        minimum = condition_minimum(template, counter.key)
        maximum = condition_maximum(template, counter.key)
        if minimum > 0:
            parts.append(f"{counter.label}≥{minimum}")
        if maximum is not None:
            parts.append(f"{counter.label}≤{maximum}")

    return ", ".join(parts) if parts else "Any"
