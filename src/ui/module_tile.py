"""One toggle from the streaming tabs' module grids, as a tinted tile.

Replaces the three checkbox grids: the OBS overlay's visible widgets, the Twitch
bot's chat commands, and the in-game overlay's widgets. What a tile buys over a
checkbox is not decoration -- it is that *enabled* is a filled shape rather than
a 13px tick. The Twitch grid carries sixteen of these, and sixteen ticks have to
be read one at a time, while sixteen tiles read as a block of colour.

The mock this comes from (`ui_mockups/streaming_tools/streaming_tools_proposal.html`) also gave
each tile an icon badge and a description line. Both are dropped: the badge was
a literal "!" on every Twitch tile, and the descriptions did not exist anywhere
in the app -- they would have had to be invented, and the tile is three times
shorter without them. Descriptions live in `docs/help/` and belong to a `?`
affordance if that is ever built.

Shaped like a checkbox on purpose
=================================

`isChecked`, `setChecked` and `stateChanged` are forwarded, because the three
call sites already speak that vocabulary -- `read_settings` asks every command
`cb.isChecked()`, and both overlays connect `stateChanged` to a save. Keeping
the shape means the grids change and their handlers do not.

The whole tile is the click target
==================================

The switch inside is `WA_TransparentForMouseEvents`, and that is load-bearing.
A clickable switch inside a clickable tile toggles twice for one press and lands
back where it started -- which reads as "the control is broken", not as a
double-toggle, so it is the kind of bug that gets diagnosed slowly. One event
source, always the tile.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout

from ui.shared import LabeledSwitch


class ModuleTile(QFrame):
    """A framed toggle: name on the left, switch on the right, tinted when on."""

    #: Forwarded from the inner switch, so existing `stateChanged.connect(...)`
    #: call sites keep working when a checkbox becomes a tile.
    stateChanged = Signal(int)

    #: The plain-boolean form, for new call sites that do not need Qt's int.
    toggled = Signal(bool)

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("moduleTile")
        # Selected by property rather than objectName in the QSS, for the same
        # reason `SegmentedToggle` is: a role swap assigns objectName, and a
        # tile that ever passes through `_set_widget_style_role` would lose its
        # frame. Properties survive that.
        self.setProperty("moduleTile", "true")
        self.setProperty("on", "false")
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(8)

        self._switch = LabeledSwitch(text, self)
        self._switch.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._switch.setFocusPolicy(Qt.NoFocus)
        self._switch.stateChanged.connect(self._on_switch_changed)
        layout.addWidget(self._switch)

    # -- the checkbox-shaped surface -----------------------------------------

    def isChecked(self) -> bool:
        return self._switch.isChecked()

    def setChecked(self, checked: bool) -> None:
        self._switch.setChecked(bool(checked))

    def text(self) -> str:
        return self._switch.text()

    def setText(self, text: str) -> None:
        self._switch.setText(str(text))

    def switch(self) -> LabeledSwitch:
        """The inner control. For tests, and for callers needing its geometry."""
        return self._switch

    # -- interaction ----------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.setChecked(not self.isChecked())
            event.accept()
            return
        super().mousePressEvent(event)

    def _on_switch_changed(self, state: int) -> None:
        checked = self._switch.isChecked()
        _set_tile_state(self, "true" if checked else "false")
        self.stateChanged.emit(int(state))
        self.toggled.emit(checked)


def _set_tile_state(tile: ModuleTile, value: str) -> None:
    """Assign the `on` property and make Qt re-match the stylesheet on it.

    Property-driven selectors are not re-evaluated on assignment, so without the
    repolish a tile keeps whichever colours it was built with. Skipped when
    nothing changed, because a repolish is not free and a grid of sixteen of
    these is rebuilt whenever the tab reloads its config.
    """
    if tile.property("on") == value:
        return
    tile.setProperty("on", value)
    style = tile.style()
    if style is None:
        return
    style.unpolish(tile)
    style.polish(tile)
    tile.update()
