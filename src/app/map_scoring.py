"""Map evaluation: scoring a candidate map and rendering its stat line.

Extracted from ``TemplatesMixin`` by step 22a, because the call graph said this
was never template *UI* at all.

The measurement that moved it (production callers of each ``gui_templates``
method, counted before the conversion):

* ``format_stats`` -- 4 calls, **all** from ``gui_scanner``.
* ``calculate_map_score`` -- 2 calls, both from ``gui_scanner``.
* ``evaluate_candidate`` -- 1 call, from ``gui_scanner``.
* ``_active_templates_require_bald_heads`` -- 1 call, from ``format_stats``.

Seven scanner calls, and **zero** from any of the eleven template-UI methods in
the same file. The reverse direction was just as clean: nothing here touches a
layout, a checkbox, ``window`` or ``log``. It shared a file with the templates
UI and nothing else -- so leaving it there and converting the file whole would
have given ``gui_scanner`` a dependency on a UI component, which is the edge
steps 14-20 spent six steps removing.

``app/`` rather than ``core/``: every function here reads ``config``
(``EVALUATION_MODE``, ``TEMPLATES``, ``SCORES_SYSTEM``), and the layer table
gives ``core`` no imports at all. Making them core-pure would mean threading
three mutable config globals through seven scanner call sites -- more churn in
the module step 22 is explicitly not allowed to rewrite, to buy a purity that
``core.logic`` already provides underneath. The decision cost is recorded here
rather than argued: ``core.logic`` keeps the arithmetic, this keeps the
config-reading policy, and the split is the same one ``logic.calculate_score``
already assumes by taking ``SCORES_SYSTEM`` as a parameter.

Free functions, not a service. There is no state: ``active_templates`` is the
scanner's, and it is passed in. A function cannot be orphaned by its class
moving -- the failure mode step 14b hit and step 19 retired the same way.
"""

from __future__ import annotations

from app import config
from core import logic


def calculate_map_score(stats: dict) -> float:
    """The candidate's score under the configured weights."""
    return logic.calculate_score(stats, config.SCORES_SYSTEM)


def active_templates_require_bald_heads(active_templates) -> bool:
    """Whether any active template constrains bald heads.

    Scores mode has no templates, so it never does. Kept as a separate function
    rather than folded into `format_stats` because it is the one branch in that
    function with a behavioural mutation test on it.
    """
    if config.EVALUATION_MODE != "templates":
        return False
    active_names = set(active_templates or [])
    if not active_names:
        return False
    return any(
        template.get("name") in active_names
        and (
            int(template.get("bald_heads", 0) or 0) > 0
            or "bald_heads_max" in template
        )
        for template in config.TEMPLATES
    )


def map_highlight_rows(stats: dict, active_templates) -> tuple[list[tuple[str, int]], float]:
    """The same numbers `format_stats` renders, as rows and a score.

    Session Stats shows Best and Worst side by side, and a reader compares them
    row by row -- which a single comma-joined sentence per map does not let you
    do. Same source, same order, same bald-heads branch; the only difference is
    that the caller gets the parts instead of the prose.

    `format_stats` stays as it is: it has three other callers that log the line
    into the Logs panel, where one line is the right shape.
    """
    rows = [
        ("Shady Guy", int(stats.get("Shady Guy", 0) or 0)),
        ("Moais", int(stats.get("Moais", 0) or 0)),
        ("Microwaves", int(logic.template_microwaves(stats) or 0)),
        ("Boss Curses", int(stats.get("Boss Curses", 0) or 0)),
        ("Magnet Shrines", int(stats.get("Magnet Shrines", 0) or 0)),
        ("Challenges", int(stats.get("Challenges", 0) or 0)),
    ]
    if active_templates_require_bald_heads(active_templates):
        rows.append(("Bald Heads", int(stats.get("Bald Heads", 0) or 0)))
    return rows, float(logic.calculate_score(stats, config.SCORES_SYSTEM))


def format_stats(stats: dict, active_templates) -> str:
    """The one-line stat summary the scanner logs and the stats tab shows."""
    shady = stats.get("Shady Guy", 0)
    moai = stats.get("Moais", 0)
    microwaves = logic.template_microwaves(stats)
    boss = stats.get("Boss Curses", 0)
    magnet = stats.get("Magnet Shrines", 0)
    challenges = stats.get("Challenges", 0)
    parts = [
        f"Shady: {shady}, Moai: {moai}, Microwaves: {microwaves}, "
        f"Boss: {boss}, Magnet: {magnet}, Challenges: {challenges}"
    ]
    if active_templates_require_bald_heads(active_templates):
        parts.append(f", Bald Heads: {stats.get('Bald Heads', 0)}")
    parts.append(f", Score: {logic.calculate_score(stats, config.SCORES_SYSTEM):.1f}")
    return "".join(parts)


def evaluate_candidate(stats: dict, active_templates, *, context: dict | None = None) -> dict | None:
    """Match a candidate against the active templates, or score it by tier."""
    if config.EVALUATION_MODE == "templates":
        return logic.find_matching_template(
            stats,
            active_templates,
            config.TEMPLATES,
            context=context,
        )
    return logic.evaluate_map_by_scores(stats, config.SCORES_SYSTEM)
