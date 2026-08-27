"""Owner of the two names the scan loop and the templates UI both write.

``active_templates`` and ``template_stats`` have been in
``PRE_EXISTING_COLLISIONS`` since that register was written, described as
"template state, co-owned by Scanner and Templates". Step 22 is the step that
has to answer the ownership question rather than let it disappear.

The measurement, taken before the conversion (production writers of each name):

* ``active_templates`` -- ``gui_app.__init__``, ``gui_scanner``, ``gui_templates``
* ``template_stats``   -- ``gui_app.__init__``, ``gui_scanner`` (x2), ``gui_templates``

Which is why the obvious move would have been a **false** discharge. Taking
``TemplatesMixin`` off the MRO removes it from the collision scan -- the scan
only reads ``MegabonkApp``'s declared bases -- so the staleness test would have
deleted both register entries while the scanner and the app were still writing
the same two attributes on the same shared object. The register would have
recorded a debt as paid on the strength of a class disappearing from a list.

So the state moved for real. This object holds both names; ``MegabonkApp``
exposes them as delegating properties. ``gui_scanner`` is unchanged -- its
``self.active_templates = ...`` still reads as an assignment, and still is one,
but it now lands in this object's field rather than in a slot on the shared
namespace that anyone may claim. One home, reachable two ways, instead of one
name owned by nobody.

The delegating-property-with-``__dict__``-fallback is not invented here: it is
exactly ``ScannerMixin.client``, which delegates to ``AppCoordinator`` and falls
back for app doubles built with ``object.__new__``. The fallback is a test
affordance and production never takes it; ``test_template_filters.py`` pins
that.

Ports, kept to the four things ``_sync_runtime_filters`` actually reached for
through ``self`` -- measured from its body, not designed up front:

``selected_template_names``
    The checked template names. The templates panel owns the checkboxes; this
    object never sees a widget.
``refresh_stats``
    Repaint the session-stats panel. Called only when it exists; the composition
    root carries that guard, because "are the stats widgets built yet" is a
    question about the app's construction order, not about filters.
``log``
    The live-update announcement.
``is_scanning``
    Whether the scan loop is running, which is what makes the announcement
    worth making.

Not a UI component and deliberately not in ``ui/``: ``gui_scanner`` calls into
this (through two one-line app delegators), and a scanner-to-UI edge is the one
this step exists to avoid.
"""

from __future__ import annotations

import threading
from typing import Callable

from app import config
from core.template_colors import template_color_tag


class TemplateRuntimeFilters:
    """The active profile names and their per-name reroll statistics."""

    def __init__(
        self,
        *,
        selected_template_names: Callable[[], list[str]],
        refresh_stats: Callable[[], None],
        log: Callable[..., None],
        is_scanning: Callable[[], bool],
    ) -> None:
        self._selected_template_names = selected_template_names
        self._refresh_stats = refresh_stats
        self._log = log
        self._is_scanning = is_scanning
        self.active_templates: list[str] = []
        self.template_stats: dict[str, dict] = {}
        self._active_mode: str | None = None
        # Scanner writes reroll histories in its worker while the templates UI
        # may synchronize the active profiles.  Session Stats consumes copies
        # made under this same boundary instead of iterating live dictionaries.
        self._state_lock = threading.RLock()

    @property
    def state_lock(self) -> threading.RLock:
        return self._state_lock

    def snapshot(self) -> tuple[list[str], dict[str, dict]]:
        """Return detached active names and per-profile history state."""
        with self._state_lock:
            copied_stats: dict[str, dict] = {}
            for name, raw in self.template_stats.items():
                if not isinstance(raw, dict):
                    continue
                copied = dict(raw)
                history = raw.get("history")
                if isinstance(history, (list, tuple)):
                    copied["history"] = list(history)
                copied_stats[str(name)] = copied
            return list(self.active_templates), copied_stats

    def selected_template_names(self) -> list[str]:
        """The checked templates, whichever mode is active."""
        return list(self._selected_template_names())

    def active_profile_names(self) -> list[str]:
        """Templates in templates mode, tiers in scores mode."""
        if config.EVALUATION_MODE == "templates":
            return self.selected_template_names()
        return list(config.SCORES_SYSTEM.get("active_tiers", []))

    def sync(self, *, announce: bool = False) -> None:
        """Bring runtime filters in line with the current selection.

        Behaviour preserved exactly from `TemplatesMixin._sync_runtime_filters`,
        including the two early returns and the order of the three writes. The
        `previous_names` snapshot is taken from `template_stats` *before* the
        `setdefault` loop mutates it, which is what makes the "did anything
        change" comparison below mean anything -- reordering those two is the
        kind of silent rewrite step 21's notes warn about.
        """
        active_names = self.active_profile_names()
        active_mode = str(config.EVALUATION_MODE)
        with self._state_lock:
            previous_mode = self._active_mode
            previous_names = list(self.template_stats.keys())

            if config.EVALUATION_MODE == "templates":
                self.active_templates = list(active_names)

            existing_stats = self.template_stats
            for name in active_names:
                existing_stats.setdefault(
                    name, {"rerolls_since_last": 0, "history": []}
                )
            self.template_stats = existing_stats
            self._active_mode = active_mode

        self._refresh_stats()

        if not announce or not self._is_scanning():
            return

        if active_names == previous_names and (
            previous_mode is None or active_mode == previous_mode
        ):
            return

        mode_label = "tiers" if active_mode == "scores" else "templates"
        if not active_names:
            names_text = ", ".join(active_names) if active_names else "none"
            self._log(f"[*] Active {mode_label} updated live: {names_text}")
            return

        if active_mode == "scores":
            color_by_name = {
                "Light": "WHITE",
                "Good": "GREEN",
                "Perfect": "YELLOW",
                "Perfect+": "LIGHTRED_EX",
            }
        else:
            color_by_name = {
                str(template.get("name") or ""): template_color_tag(template)
                for template in config.TEMPLATES
                if isinstance(template, dict)
            }

        parts: list[str] = [f"[*] Active {mode_label} updated live: "]
        tags: list[str | None] = [None]
        for index, name in enumerate(active_names):
            parts.append(name)
            tags.append(color_by_name.get(name, "BLUE"))
            if index < len(active_names) - 1:
                parts.append(", ")
                tags.append(None)
        self._log(parts, tag=tags)
