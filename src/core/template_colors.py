"""The palette a *template* is drawn in, which is not the item palette.

Templates store a colour by name -- `MAGENTA`, `RED`, `BLUE` -- and every site
that drew one resolved that name through `COLOR_MAP` in `item_metadata`. That
table is the item palette: `ITEM_RARITY_COLOR_MAP` derives `UNCOMMON` from its
`BLUE` and `RARE` from its `MAGENTA`, and those colours reach the item chips on
Live Stats and Compare Runs, the OBS overlay and the in-game widgets.

So the two were one table by accident, not by design, and the accident only
shows when someone wants to move one of them: repainting `MAGENTA` for the
BOSS RUSH+ template would have turned every rare item in the application pure
magenta, including on a live stream.

This is the template half, split out. It is deliberately **sparse** -- it holds
only the names whose template colour differs from the item one, and
`template_color_hex` falls through to `COLOR_MAP` for the rest. A name that
should look the same in both places therefore stays defined in exactly one
place, and cannot drift.

It lives in `core/` because `core/logic.py` names these colours when it builds
a score result, and `core` may not import from `app` or `ui`.

One default, not two
====================

A template with no colour at all used to resolve two different blues: the
panel, the rail and the manager dialog defaulted to `LIGHTBLUE_EX` (#93C5FD),
while the scanner, the filters and the score path defaulted to `BLUE`
(#60A5FA). The same custom template was drawn in one blue on the left panel and
another in the log. `DEFAULT_TEMPLATE_COLOR` is that decision made once.
"""
from __future__ import annotations

import re

from core.item_metadata import COLOR_MAP

#: What a template with no colour of its own is drawn in. Every caller now
#: takes this default from here rather than spelling one of two blues inline.
DEFAULT_TEMPLATE_COLOR = "BLUE"

#: Only the names that differ from `COLOR_MAP`. Anything absent falls through,
#: so `WHITE`, `CYAN`, `GREEN` and `YELLOW` are still the item palette's and are
#: not restated here.
TEMPLATE_COLOR_MAP = {
    # BOSS RUSH. #EF4444 in the item palette, where it is not a rarity.
    "RED": "#FF2500",
    # BOSS RUSH+. #E879F9 in the item palette, where it *is* RARE -- the whole
    # reason this table exists.
    "MAGENTA": "#FF00FF",
    # The default above, and any template a user paints blue. #60A5FA in the
    # item palette, where it is UNCOMMON.
    #
    # Asked for as pure #0000FF, lightened along the same hue because the colour
    # is not only the 4px bar -- it is also the *label* of a checked row, on
    # #141A22. Pure blue there measures 2.04:1, against 4.5 for body text: the
    # row was legible only by its unchecked state. #7878FF is 4.94:1, which puts
    # it between BOSS RUSH (4.59) and BOSS RUSH+ (5.58) rather than out on its
    # own. #7070FF was the smallest step that clears the threshold at all, and
    # is not used: 4.54 leaves nothing for a theme tweak later.
    "BLUE": "#7878FF",
    # PERFECT+. A name of its own rather than a repaint: `LIGHTRED_EX` is also
    # the Perfect+ *score tier*, and the tier was not part of the request.
    "ORANGE": "#FF6F00",
}

_HEX_COLOR_RE = re.compile(r"^#[0-9A-F]{6}$")


def _custom_hex(color_tag) -> str | None:
    """Return a normalized saved custom colour, if ``color_tag`` is one."""
    tag = str(color_tag or "").strip().upper()
    return tag if _HEX_COLOR_RE.fullmatch(tag) else None


def template_color_hex(color_tag: str | None) -> str:
    """The colour a template tagged `color_tag` is drawn in.

    Falls through to the item palette for every name this module does not
    override, and to `COLOR_MAP["DEFAULT"]` for a name neither table knows --
    which is what the call sites this replaces already did, so an unrecognised
    tag still degrades to readable grey rather than to nothing.
    """
    custom = _custom_hex(color_tag)
    if custom is not None:
        return custom
    tag = str(color_tag or DEFAULT_TEMPLATE_COLOR).upper()
    return TEMPLATE_COLOR_MAP.get(tag) or COLOR_MAP.get(tag, COLOR_MAP["DEFAULT"])


def template_color_hex_or_none(color_tag) -> str | None:
    """The template colour for `color_tag`, or `None` if neither table knows it.

    The log's per-segment tag vocabulary mixes colour names with severities --
    `["success", "MAGENTA"]` is an ordinary call -- so an unrecognised tag there
    must stay *uncoloured* rather than fall back to grey. That is the one thing
    `template_color_hex` cannot do, and the reason this exists beside it.
    """
    custom = _custom_hex(color_tag)
    if custom is not None:
        return custom
    tag = str(color_tag or "").upper()
    if not tag:
        return None
    return TEMPLATE_COLOR_MAP.get(tag) or COLOR_MAP.get(tag)


def template_color_tag(template) -> str:
    """The colour name stored on `template`, or the shared default."""
    if not isinstance(template, dict):
        return DEFAULT_TEMPLATE_COLOR
    return str(template.get("color") or DEFAULT_TEMPLATE_COLOR).upper()
