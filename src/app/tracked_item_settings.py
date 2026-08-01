"""The three tracked-item lists, and the one path a change takes to the tracker.

There is one concept here and there were three copies of it. Session Stats owns
a list; the OBS overlay and the Twitch ``!session`` response each either keep a
list of their own or mirror the Session one. That model was expressible before
-- it is what ``tracked_items_source`` means -- but each of the three surfaces
read and wrote its own config keys from its own dialog, and the three did not
agree on when a change reaches the tracker. Two things fell into that gap:

**The Twitch save never rebuilt the rule set.** ``TwitchCommandSettingsDialog``
guarded the rebuild with ``hasattr(master, "_combined_tracked_item_rules")``.
That method is ``gui_overlay.Overlay``'s; ``master`` is the application, whose
``__getattr__`` forwards to its window and nowhere else. The probe was false in
every build and true in the one test that covered it, because the test's double
was handed the attribute. A rule added only for ``!session`` was never
registered, and ``rows_for_rules`` reads ``tracked_counts.get(rule.id, 0)`` --
so it counted zero until an unrelated OBS or Session change rebuilt the rules.

**The Twitch list did not persist when it was edited.** ``Add Rule`` wrote
``config.TWITCH_BOT`` in memory; only ``Save Settings`` wrote the file. Closing
the dialog any other way left the rule live for the session and absent from
disk -- until some later, unrelated save wrote it out.

Both are gone by construction rather than by a fix: there is one writer, and it
always republishes. What a caller supplies is *which list* and *what rules*.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app import config
from projections.tracked_items import tracked_item_combo_display_name


@dataclass(frozen=True)
class TrackedItemTarget:
    """One of the three lists, described rather than branched on.

    ``config_key`` is read by name at call time and never captured: the config
    module rebinds these attributes wholesale (``config.OVERLAY = overlay``), so
    a captured dict goes stale the first time anything saves.
    """

    key: str
    caption: str
    config_key: str
    #: Prefixed onto a rule's id so the same item and condition can be tracked
    #: for two surfaces at once. `combined_tracked_item_rules` keys by id, so
    #: without the prefix the OBS and Twitch copies of one rule would collapse
    #: into a single counter shared by both.
    id_prefix: str
    #: Whether this list can be replaced by the Session Stats one. Session Stats
    #: itself cannot: it is what the other two mirror.
    can_mirror: bool


SESSION = TrackedItemTarget(
    key="session",
    caption="Session Stats",
    config_key="SESSION_TRACKED_ITEMS",
    id_prefix="session_",
    can_mirror=False,
)
OVERLAY = TrackedItemTarget(
    key="overlay",
    caption="OBS overlay",
    config_key="OVERLAY",
    # No prefix, and it cannot gain one: these ids are in every user's config
    # file already, and renaming them would reset the counters of every rule
    # anyone has ever added to the overlay.
    id_prefix="",
    can_mirror=True,
)
TWITCH = TrackedItemTarget(
    key="twitch",
    caption="!session",
    config_key="TWITCH_BOT",
    id_prefix="twitch_",
    can_mirror=True,
)

#: In the order the window shows them: the list the other two can mirror first.
TARGETS = (SESSION, OVERLAY, TWITCH)
TARGETS_BY_KEY = {target.key: target for target in TARGETS}

SOURCE_OWN = "custom"
SOURCE_SESSION = "session"


def combine_rules(rules_from_config: Callable[[dict], tuple]) -> tuple:
    """Every rule any of the three surfaces asks for, deduplicated by id.

    The tracker counts one set of rules for the whole application; which surface
    asked for a rule is not its business. Keyed by id so a rule configured twice
    for the same surface cannot be counted twice -- and so the per-target
    prefixes above are what keeps two surfaces' copies apart.

    Building a `TrackedItemRule` is passed in rather than imported: that lives
    in the top-level `tracked_item_rules` adapter, which nothing under `app/`
    may reach, and reaching for it is what the layer guard caught. The three
    config lists are this module's; turning one into tracker rules is not.
    """
    combined: dict[str, Any] = {}
    for target in TARGETS:
        for rule in rules_from_config(_config_dict(target)):
            combined[rule.id] = rule
    return tuple(combined.values())


def rule_id(target: TrackedItemTarget, item_names, mode: str) -> str:
    folded = "_".join(
        "".join(char.lower() for char in str(item_name) if char.isalnum())
        for item_name in item_names
    )
    return f"{target.id_prefix}{folded or 'item'}_{mode}"


class TrackedItemSettings:
    """Reads and writes the three lists; republishes on every write.

    The ports are the three things a change has to reach, and they are named
    rather than probed for. ``TwitchCommandSettingsDialog`` probed for one of
    them with ``hasattr`` and lost it silently -- see this module's docstring.
    """

    def __init__(
        self,
        *,
        tracker: Callable[[], Any],
        combined_rules: Callable[[], tuple],
        refresh_session_rows: Callable[[], None],
        refresh_snapshot: Callable[[], None],
        save: Callable[[], None] = None,
    ) -> None:
        self._tracker = tracker
        self._combined_rules = combined_rules
        self._refresh_session_rows = refresh_session_rows
        self._refresh_snapshot = refresh_snapshot
        self._save = save or (lambda: config.save_config(config.user_config))

    # -- reading ----------------------------------------------------------

    def rules(self, target: TrackedItemTarget) -> list[dict]:
        return [
            dict(rule)
            for rule in _config_dict(target).get("tracked_items") or ()
            if isinstance(rule, dict)
        ]

    def source(self, target: TrackedItemTarget) -> str:
        """`custom` or `session`; always `custom` for a target that cannot mirror."""
        if not target.can_mirror:
            return SOURCE_OWN
        return config.normalize_tracked_items_source(
            _config_dict(target).get("tracked_items_source"),
            default=SOURCE_OWN,
        )

    def effective_rules(self, target: TrackedItemTarget) -> list[dict]:
        """What this target actually counts -- its own list, or the mirrored one."""
        if self.source(target) == SOURCE_SESSION:
            return self.rules(SESSION)
        return self.rules(target)

    def make_rule(self, target: TrackedItemTarget, item_names, mode: str) -> dict:
        """Build a persisted rule. The label is derived, as it always was."""
        item_names = tuple(str(name) for name in item_names)
        display_name = tracked_item_combo_display_name(item_names)
        return {
            "id": rule_id(target, item_names, mode),
            "label": f"{display_name} Map 1" if mode == "map_1_only" else display_name,
            "item_names": list(item_names),
            "mode": mode,
        }

    # -- writing ----------------------------------------------------------

    def set_rules(self, target: TrackedItemTarget, rules) -> None:
        container = _config_dict(target)
        container["tracked_items"] = config.normalize_tracked_item_rules_config(
            [dict(rule) for rule in rules], []
        )
        self._persist(target)

    def set_source(self, target: TrackedItemTarget, source: str) -> None:
        if not target.can_mirror:
            return
        container = _config_dict(target)
        container["tracked_items_source"] = config.normalize_tracked_items_source(
            source, default=SOURCE_OWN
        )
        self._persist(target)

    def _persist(self, target: TrackedItemTarget) -> None:
        """Write the file, then tell everything that counts or renders rules.

        All four steps, every time, for every target. Doing three of them is how
        a rule ends up saved but uncounted, which is the shape of both bugs this
        module replaced.
        """
        container = _config_dict(target)
        setattr(config, target.config_key, container)
        config.user_config[target.config_key] = container
        self._save()

        tracker = self._tracker()
        if tracker is not None:
            tracker.set_tracked_item_rules(self._combined_rules())
        self._refresh_session_rows()
        self._refresh_snapshot()


def _config_dict(target: TrackedItemTarget) -> dict:
    container = getattr(config, target.config_key, None)
    if not isinstance(container, dict):
        container = {}
        setattr(config, target.config_key, container)
    return container
