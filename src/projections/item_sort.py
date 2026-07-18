"""Item sort modes and the rarity order they sort by.

Moved out of gui_styles.py in step 17a. The lowest actual consumer is
projections/ -- projections/formatting.py's sort_items_by_mode reads all four --
so they land here and ui/ imports them downward, which is the direction §2
allows.

Kept as their own module rather than folded into projections/formatting.py:
five modules across projections/, ui/ and the remaining top-level files import
these names, and they are a self-contained vocabulary rather than a slice of
formatting. That is the opposite of the case against a core/thresholds.py in the
previous commit, where the candidate module would have had a single importer.

Nothing in core/ consumes these, which is why they are not core/ data despite
being keyed by the rarities core/ owns -- placement follows the consumer graph,
not the subject matter.
"""

from __future__ import annotations

ITEM_SORT_DEFAULT = "default"
ITEM_SORT_RARITY_DESC = "rarity_desc"
ITEM_SORT_RARITY_ASC = "rarity_asc"
ITEM_RARITY_SORT_ORDER = {
    "COMMON": 0,
    "UNCOMMON": 1,
    "RARE": 2,
    "LEGENDARY": 3,
}
