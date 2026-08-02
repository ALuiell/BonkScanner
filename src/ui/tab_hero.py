"""The header strip shared by the OBS, Twitch and In-game tabs.

Each of the three tabs opened with the same group box under a different name --
`Overlay Server`, `Bot Control`, `General Settings` -- holding the same four
things in the same order: a status label, an auto-start checkbox, a
caption-swapping Start/Stop button, and (on two of them) one stray control that
belonged elsewhere. This is that group, built once.

The status badge has four states, not two
=========================================

The mock drew `Running` and `Stopped`. The code has more, and the extra ones are
the ones worth seeing: OBS reports a port error with the OS message attached,
and Twitch walks a whole lifecycle -- authorizing, validating, connecting -- any
step of which can stall. So the badge takes a `state` from
`ok | warn | danger | off`, which is what the stylesheet keys on, and a short
caption.

Long text does not go in the badge. `set_status` takes an optional `detail`
which **replaces the subtitle** while it is set: a port error's message is a
sentence, and a sentence in a 10.5px uppercase pill is unreadable. Clearing the
detail restores the tab's own subtitle, so a recovered error does not leave the
hero explaining a problem that is over.

Why the badge stays visible when the run toggle already shows state
==================================================================

Because they answer different questions. The toggle says what you can do now;
the badge says what is happening -- and only the badge can say `PORT ERROR` or
`CONNECTING`. Hiding it in the plain cases would make the hero's height jump on
every connect, which is worse than a moment of redundancy.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.run_toggle import RunToggle
from ui.shared import LabeledSwitch, resource_path

#: The four badge states, as the stylesheet spells them. Named because both
#: sides of a property selector are strings, and a typo in either silently
#: leaves the badge with its previous colours.
STATE_OK = "ok"
STATE_WARN = "warn"
STATE_DANGER = "danger"
STATE_OFF = "off"

ICON_SIZE = 24
ICON_BOX = 48


class TabHero(QFrame):
    """Icon, title, status badge, subtitle, auto-switch and a run toggle."""

    def __init__(
        self,
        *,
        title: str,
        subtitle: str,
        icon_path: str,
        auto_text: str,
        run_captions: tuple[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("tabHero")
        self.setProperty("tabHero", "true")

        self._subtitle_text = str(subtitle)
        self._detail_text = ""

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(16)

        layout.addWidget(self._build_icon(icon_path))

        copy_column = QVBoxLayout()
        copy_column.setContentsMargins(0, 0, 0, 0)
        copy_column.setSpacing(3)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(9)
        self._title = QLabel(str(title))
        self._title.setObjectName("heroTitle")
        title_row.addWidget(self._title)

        self._badge = QLabel("")
        self._badge.setObjectName("heroBadge")
        self._badge.setProperty("state", STATE_OFF)
        title_row.addWidget(self._badge)
        title_row.addStretch(1)
        copy_column.addLayout(title_row)

        self._subtitle = QLabel(self._subtitle_text)
        self._subtitle.setObjectName("heroSubtitle")
        self._subtitle.setWordWrap(True)
        self._subtitle.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        copy_column.addWidget(self._subtitle)

        layout.addLayout(copy_column, 1)

        self._auto_switch = LabeledSwitch(str(auto_text))
        layout.addWidget(self._auto_switch, 0, Qt.AlignVCenter)

        self._run_toggle = RunToggle(*run_captions)
        layout.addWidget(self._run_toggle, 0, Qt.AlignVCenter)

    def _build_icon(self, icon_path: str) -> QLabel:
        holder = QLabel()
        holder.setObjectName("heroIcon")
        holder.setFixedSize(ICON_BOX, ICON_BOX)
        holder.setAlignment(Qt.AlignCenter)
        # Rendered through QIcon rather than QPixmap(path) so the SVG is scaled
        # by the renderer instead of by the pixmap, which is what keeps the
        # 1.8px stroke from turning to mush at 24px.
        pixmap = QIcon(resource_path(icon_path)).pixmap(ICON_SIZE, ICON_SIZE)
        if not pixmap.isNull():
            holder.setPixmap(pixmap)
        else:
            # A missing asset must not leave an unexplained empty square.
            holder.setPixmap(QPixmap())
            holder.setText("?")
        return holder

    # -- the parts the tab wires ---------------------------------------------

    @property
    def auto_switch(self) -> LabeledSwitch:
        return self._auto_switch

    @property
    def run_toggle(self) -> RunToggle:
        return self._run_toggle

    # -- state ----------------------------------------------------------------

    def set_status(self, caption: str, state: str, *, detail: str = "") -> None:
        """Paint the badge, and put `detail` where a sentence can be read.

        `detail` replaces the subtitle for as long as it is non-empty; passing
        `""` puts the tab's own subtitle back, so an error that clears does not
        leave its explanation behind.
        """
        self._badge.setText(str(caption))
        _set_badge_state(self._badge, str(state))
        self._detail_text = str(detail or "")
        self._subtitle.setText(self._detail_text or self._subtitle_text)

    def set_subtitle(self, subtitle: str) -> None:
        """Change the resting subtitle. Visible immediately unless a detail is up."""
        self._subtitle_text = str(subtitle)
        if not self._detail_text:
            self._subtitle.setText(self._subtitle_text)

    def status_text(self) -> str:
        return self._badge.text()

    def status_state(self) -> str:
        return str(self._badge.property("state") or "")


def _set_badge_state(badge: QLabel, state: str) -> None:
    """Assign the `state` property and make Qt re-match the stylesheet on it.

    Property selectors are not re-evaluated on assignment, so without the
    repolish the badge keeps the colours it was built with -- a stopped server
    would stay green. Skipped when nothing changed: this runs on every overlay
    refresh tick.
    """
    if badge.property("state") == state:
        return
    badge.setProperty("state", state)
    style = badge.style()
    if style is None:
        return
    style.unpolish(badge)
    style.polish(badge)
    badge.update()
