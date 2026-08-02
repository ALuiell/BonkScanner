"""Shared series-slot menu and presentation for both recording timelines."""
from __future__ import annotations

from PySide6.QtWidgets import QMenu, QPushButton

from core.stat_labels import abbreviate_stat_label
from projections import scrubber as scrubber_model


TIMELINE_SERIES_GROUPS = (
    (
        "Dmg",
        (
            "Damage",
            "Crit Chance",
            "Crit Damage",
            "Attack Speed",
            "Projectile Count",
            "Projectile Bounces",
        ),
    ),
    (
        "Effects",
        (
            "Size",
            "Projectile Speed",
            "Duration",
            "Damage to Elites",
            "Knockback",
        ),
    ),
    (
        "Run",
        (
            "Max HP",
            "HP Regen",
            "Overheal",
            "Shield",
            "Armor",
            "Evasion",
            "Lifesteal",
            "Thorns",
            "Extra Jumps",
            "Jump Height",
            "Movement Speed",
        ),
    ),
    (
        "Rewards & spawns",
        (
            "Luck",
            "Difficulty",
            "Pickup Range",
            "XP Gain",
            "Gold Gain",
            "Elite Spawn Increase",
            "Powerup Multiplier",
            "Powerup Drop Chance",
        ),
    ),
)

POWERUP_PAIR = ("Powerup Multiplier", "Powerup Drop Chance")

_ACCENT_ROLES = {
    "#38bdf8": "blue",
    "#4ade80": "green",
    "#facc15": "yellow",
    "#f59e0b": "orange",
    "#f0787e": "red",
    "#c084fc": "purple",
    "#60a5fa": "sky",
}


def build_timeline_series_menu(
    button: QPushButton,
    slot_index: int,
    on_selected,
) -> QMenu:
    def select(keys):
        return lambda _checked=False: on_selected(slot_index, tuple(keys))

    menu = QMenu(button)
    menu.addAction("None").triggered.connect(select(scrubber_model.EMPTY_SLOT))
    menu.addSeparator()
    for key in (scrubber_model.KILLS_SERIES, scrubber_model.ITEMS_SERIES):
        menu.addAction(scrubber_model.series_label(key)).triggered.connect(select((key,)))
    menu.addAction("PM + PDC").triggered.connect(select(POWERUP_PAIR))
    menu.addSeparator()
    allowed = set(scrubber_model.available_series_keys())
    for title, labels in TIMELINE_SERIES_GROUPS:
        submenu = menu.addMenu(title)
        for key in labels:
            if key in allowed:
                submenu.addAction(key).triggered.connect(select((key,)))
    return menu


def slot_button_text(keys) -> str:
    keys = tuple(keys)
    if not keys:
        return "None"
    return " + ".join(
        abbreviate_stat_label(scrubber_model.series_label(key)) for key in keys
    )


def timeline_series_accent_role(keys) -> str:
    keys = tuple(keys)
    if not keys:
        return "none"
    color = scrubber_model.series_color(keys[0]).lower()
    return _ACCENT_ROLES.get(color, "neutral")


def refresh_timeline_slot_button(button: QPushButton, slot_index: int, keys) -> None:
    keys = tuple(keys)
    button.setText(slot_button_text(keys))
    button.setToolTip(f"Timeline series slot {slot_index + 1}")
    button.setAccessibleName(f"Timeline series slot {slot_index + 1}: {button.text()}")
    button.setProperty("timelineSlot", True)
    accent = timeline_series_accent_role(keys)
    if button.property("accentRole") != accent:
        button.setProperty("accentRole", accent)
        style = button.style()
        style.unpolish(button)
        style.polish(button)


# --------------------------------------------------------------------------
# Cap toggles
#
# The Difficulty and XP Gain ceilings are rules of the game, not readings of a
# run, so asking to see them is a different question from asking for the stat
# to be plotted. Both scrubbers used to answer only the second: their cap
# painters iterated the *selected series*, which meant a ceiling could only be
# seen by spending one of four slots on its stat.
#
# The vocabulary lives here, with the slot menu, because both timelines show
# the same two ceilings and neither tab may import the other -- a shared
# control with two copies of its key list is how the two drift apart.
# --------------------------------------------------------------------------

#: The only two stats `scrubber.build_cap_steps` returns anything for.
TIMELINE_CAP_KEYS: tuple[str, ...] = ("Difficulty", "XP Gain")

TIMELINE_CAP_LABELS = {
    "Difficulty": "Difficulty cap",
    "XP Gain": "XP cap",
}

TIMELINE_CAP_TOOLTIPS = {
    "Difficulty": "Draw the Difficulty ceiling, including its step two minutes into the ghosts",
    "XP Gain": "Draw the flat XP Gain ceiling",
}

TIMELINE_CAPS_CONFIG_KEY = "TIMELINE_CAPS"


def configured_timeline_caps() -> tuple[str, ...]:
    """Which ceilings were left switched on, in a fixed order.

    Off by default: they are reference lines, and a timeline that draws them
    unasked is busier for everyone who does not want them. An unreadable saved
    value falls back to "none" rather than raising -- this reads a config file.
    """
    from app import config

    saved = config.user_config.get(TIMELINE_CAPS_CONFIG_KEY)
    if not isinstance(saved, list):
        return ()
    wanted = {str(value) for value in saved}
    return tuple(key for key in TIMELINE_CAP_KEYS if key in wanted)


def save_timeline_caps(keys) -> None:
    from app import config

    wanted = {str(key) for key in keys}
    config.user_config[TIMELINE_CAPS_CONFIG_KEY] = [
        key for key in TIMELINE_CAP_KEYS if key in wanted
    ]
    config.save_config(config.user_config)


def build_timeline_cap_checkboxes(on_changed) -> dict:
    """One checkbox per ceiling, wired to `on_changed`, keyed by cap key.

    Returned rather than added to a layout: the two headers place them
    differently -- beside the slots in Compare Runs, beside the readout in
    Recordings -- but they must *be* the same control.
    """
    from PySide6.QtWidgets import QCheckBox

    saved = set(configured_timeline_caps())
    checkboxes = {}
    for key in TIMELINE_CAP_KEYS:
        checkbox = QCheckBox(TIMELINE_CAP_LABELS[key])
        checkbox.setObjectName("TimelineCapToggle")
        checkbox.setProperty("capKey", key)
        checkbox.setToolTip(TIMELINE_CAP_TOOLTIPS[key])
        checkbox.setChecked(key in saved)
        checkbox.stateChanged.connect(lambda _state: on_changed())
        checkboxes[key] = checkbox
    return checkboxes


def checked_timeline_caps(checkboxes: dict) -> tuple[str, ...]:
    """The enabled ceilings, in `TIMELINE_CAP_KEYS` order."""
    return tuple(
        key
        for key in TIMELINE_CAP_KEYS
        if checkboxes.get(key) is not None and checkboxes[key].isChecked()
    )
