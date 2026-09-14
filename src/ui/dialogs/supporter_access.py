"""Settings page for the shared supporter-access controller.

The widget deliberately knows nothing about HTTP, credentials or cache files.
It renders the controller's published state and forwards the three user actions
the access contract exposes: activate, check now and remove the saved key.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.shared import resource_path


def _format_timestamp(value: datetime | None, *, date_only: bool = False) -> str:
    if not isinstance(value, datetime):
        return "—"
    try:
        local_value = value.astimezone()
    except (OSError, ValueError):
        local_value = value
    return local_value.strftime("%d %b %Y" if date_only else "%d %b %Y, %H:%M")


def _repolish(widget: QWidget) -> None:
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()


def _is_controller(controller) -> bool:
    if controller is None:
        return False
    state = getattr(controller, "state", None)
    if not isinstance(getattr(state, "status", None), str):
        return False
    return all(
        callable(getattr(controller, name, None))
        for name in ("activate", "check_now", "remove_key", "add_listener")
    )


class SupporterAccessPage(QWidget):
    """One compact, state-driven page inside the Settings dialog."""

    def __init__(
        self,
        *,
        controller,
        open_patreon,
        open_crypto,
        open_github,
        open_discord,
        crypto_enabled: bool,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("SupporterAccessPage")
        self._controller = controller if _is_controller(controller) else None
        self._state = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setObjectName("SupporterAccessScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root.addWidget(scroll)

        content = QWidget(scroll)
        content.setObjectName("SupporterAccessContent")
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(10)

        access_eyebrow = QLabel("YOUR ACCESS", content)
        access_eyebrow.setObjectName("sectionEyebrow")
        layout.addWidget(access_eyebrow)

        self.access_card = QFrame(content)
        self.access_card.setObjectName("SupporterAccessCard")
        card_layout = QVBoxLayout(self.access_card)
        card_layout.setContentsMargins(14, 14, 14, 14)
        card_layout.setSpacing(11)
        layout.addWidget(self.access_card)

        state_row = QHBoxLayout()
        state_row.setContentsMargins(0, 0, 0, 0)
        state_row.setSpacing(10)

        self.access_icon = QLabel(self.access_card)
        self.access_icon.setObjectName("SupportAccessIcon")
        self.access_icon.setAlignment(Qt.AlignCenter)
        self.access_icon.setFixedSize(34, 34)
        icon = QIcon(resource_path("media/premium_access_icon.svg"))
        self.access_icon.setPixmap(icon.pixmap(QSize(18, 18)))
        state_row.addWidget(self.access_icon, 0, Qt.AlignTop)

        state_copy = QVBoxLayout()
        state_copy.setContentsMargins(0, 0, 0, 0)
        state_copy.setSpacing(2)
        self.access_title = QLabel(self.access_card)
        self.access_title.setObjectName("SupportAccessTitle")
        self.access_message = QLabel(self.access_card)
        self.access_message.setObjectName("SupportAccessMessage")
        self.access_message.setWordWrap(True)
        state_copy.addWidget(self.access_title)
        state_copy.addWidget(self.access_message)
        state_row.addLayout(state_copy, 1)

        self.status_badge = QLabel(self.access_card)
        self.status_badge.setObjectName("SupportAccessStatus")
        self.status_badge.setAlignment(Qt.AlignCenter)
        state_row.addWidget(self.status_badge, 0, Qt.AlignTop)
        card_layout.addLayout(state_row)

        self.key_entry_panel = QWidget(self.access_card)
        self.key_entry_panel.setObjectName("SupportKeyEntryPanel")
        entry_layout = QVBoxLayout(self.key_entry_panel)
        entry_layout.setContentsMargins(0, 0, 0, 0)
        entry_layout.setSpacing(7)
        entry_label = QLabel("SUPPORTER KEY", self.key_entry_panel)
        entry_label.setObjectName("SupportAccessFieldLabel")
        entry_layout.addWidget(entry_label)
        entry_row = QHBoxLayout()
        entry_row.setContentsMargins(0, 0, 0, 0)
        entry_row.setSpacing(8)
        self.key_entry = QLineEdit(self.key_entry_panel)
        self.key_entry.setObjectName("SupporterKeyEntry")
        self.key_entry.setEchoMode(QLineEdit.Password)
        self.key_entry.setPlaceholderText("Paste your BSK_ supporter key")
        self.key_entry.setClearButtonEnabled(True)
        self.key_entry.setAccessibleName("Supporter key")
        entry_row.addWidget(self.key_entry, 1)
        self.activate_button = QPushButton("Activate", self.key_entry_panel)
        self.activate_button.setObjectName("SupportActivateButton")
        entry_row.addWidget(self.activate_button)
        entry_layout.addLayout(entry_row)
        storage_note = QLabel(
            "The complete key is stored securely and is not shown again.",
            self.key_entry_panel,
        )
        storage_note.setObjectName("SupportAccessHint")
        storage_note.setWordWrap(True)
        entry_layout.addWidget(storage_note)
        card_layout.addWidget(self.key_entry_panel)

        self.saved_key_panel = QWidget(self.access_card)
        self.saved_key_panel.setObjectName("SupportSavedKeyPanel")
        saved_layout = QVBoxLayout(self.saved_key_panel)
        saved_layout.setContentsMargins(0, 0, 0, 0)
        saved_layout.setSpacing(10)

        key_display = QFrame(self.saved_key_panel)
        key_display.setObjectName("SupportKeyDisplay")
        key_display_layout = QHBoxLayout(key_display)
        key_display_layout.setContentsMargins(10, 7, 10, 7)
        key_display_layout.setSpacing(8)
        key_caption = QLabel("KEY", key_display)
        key_caption.setObjectName("SupportKeyCaption")
        self.key_hint = QLabel(key_display)
        self.key_hint.setObjectName("SupportKeyHint")
        self.key_hint.setTextInteractionFlags(Qt.TextSelectableByMouse)
        key_display_layout.addWidget(key_caption)
        key_display_layout.addWidget(self.key_hint, 1)
        saved_layout.addWidget(key_display)

        metadata_row = QHBoxLayout()
        metadata_row.setContentsMargins(0, 0, 0, 0)
        metadata_row.setSpacing(8)
        checked_box, self.checked_value = self._metadata_box(
            "LAST CHECKED", self.saved_key_panel
        )
        expiry_box, self.expiry_value = self._metadata_box(
            "ACCESS UNTIL", self.saved_key_panel
        )
        metadata_row.addWidget(checked_box, 1)
        metadata_row.addWidget(expiry_box, 1)
        saved_layout.addLayout(metadata_row)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        self.check_button = QPushButton("Check now", self.saved_key_panel)
        self.check_button.setObjectName("SupportCheckButton")
        action_row.addWidget(self.check_button)
        action_row.addStretch(1)
        self.remove_button = QPushButton("", self.saved_key_panel)
        self.remove_button.setObjectName("SupportRemoveButton")
        self.remove_button.setIcon(QIcon(resource_path("media/delete_icon.svg")))
        self.remove_button.setIconSize(QSize(16, 16))
        self.remove_button.setFixedSize(34, 34)
        self.remove_button.setToolTip("Remove saved supporter key")
        self.remove_button.setAccessibleName("Remove saved supporter key")
        action_row.addWidget(self.remove_button)
        saved_layout.addLayout(action_row)
        card_layout.addWidget(self.saved_key_panel)

        self.access_guide_section = QWidget(content)
        self.access_guide_section.setObjectName("SupportAccessGuideSection")
        guide_section_layout = QVBoxLayout(self.access_guide_section)
        guide_section_layout.setContentsMargins(0, 0, 0, 0)
        guide_section_layout.setSpacing(8)

        guide_eyebrow = QLabel("HOW TO GET ACCESS", self.access_guide_section)
        guide_eyebrow.setObjectName("sectionEyebrow")
        guide_section_layout.addWidget(guide_eyebrow)

        self.access_guide = QFrame(self.access_guide_section)
        self.access_guide.setObjectName("SupportAccessGuide")
        guide_layout = QVBoxLayout(self.access_guide)
        guide_layout.setContentsMargins(10, 8, 10, 8)
        guide_layout.setSpacing(4)
        for number, text in (
            ("1", "Support BonkScanner via Patreon or Crypto."),
            ("2", "Receive your personal BSK_ supporter key."),
            ("3", "Paste it above and press Activate."),
        ):
            guide_layout.addWidget(
                self._guide_step(number, text, self.access_guide),
            )
        guide_section_layout.addWidget(self.access_guide)
        layout.addWidget(self.access_guide_section)

        support_eyebrow = QLabel("GET A SUPPORTER KEY", content)
        support_eyebrow.setObjectName("sectionEyebrow")
        layout.addWidget(support_eyebrow)

        support_note = QLabel(
            "BonkScanner remains free. Choose a support method to receive a "
            "personal key for optional supporter features.",
            content,
        )
        support_note.setObjectName("SupportSectionNote")
        support_note.setWordWrap(True)
        layout.addWidget(support_note)

        support_method_row = QHBoxLayout()
        support_method_row.setContentsMargins(0, 0, 0, 0)
        support_method_row.setSpacing(10)
        patreon_card, self.patreon_btn = self._support_method_card(
            platform="patreon",
            title="Patreon",
            description="Monthly supporter membership.",
            button_text="Open Patreon",
            icon_path="media/patreon_logo.svg",
            callback=open_patreon,
        )
        crypto_card, self.crypto_btn = self._support_method_card(
            platform="crypto",
            title="Crypto",
            description="One-time direct support.",
            button_text="Open Crypto",
            icon_path="media/crypto_coins.svg",
            callback=open_crypto,
        )
        support_method_row.addWidget(patreon_card, 1)
        support_method_row.addWidget(crypto_card, 1)
        layout.addLayout(support_method_row)

        self.crypto_btn.setEnabled(bool(crypto_enabled))
        if not crypto_enabled:
            self.crypto_btn.setToolTip("Crypto support page is coming soon.")

        links_label = QLabel("PROJECT LINKS", content)
        links_label.setObjectName("SupportLinksLabel")
        layout.addWidget(links_label)

        links_row = QHBoxLayout()
        links_row.setContentsMargins(0, 0, 0, 0)
        links_row.setSpacing(8)
        self.github_btn = self._secondary_link_button(
            "GitHub", "media/github_logo.svg", open_github
        )
        self.discord_btn = self._secondary_link_button(
            "Discord", "media/discord_logo.svg", open_discord
        )
        links_row.addWidget(self.github_btn, 1)
        links_row.addWidget(self.discord_btn, 1)
        layout.addLayout(links_row)
        layout.addStretch(1)

        self.key_entry.textChanged.connect(self._sync_action_states)
        self.key_entry.returnPressed.connect(self.activate_key)
        self.activate_button.clicked.connect(self.activate_key)
        self.check_button.clicked.connect(self.check_now)
        self.remove_button.clicked.connect(self.remove_key)

        if self._controller is None:
            self._render_state(None)
        else:
            listener = self._on_state_changed
            self._controller.add_listener(listener)
            remove_listener = getattr(self._controller, "remove_listener", None)
            if callable(remove_listener):
                self.destroyed.connect(
                    lambda *_args, owner=self._controller, callback=listener: (
                        owner.remove_listener(callback)
                    )
                )
            self._render_state(self._controller.state)

    @staticmethod
    def _metadata_box(caption: str, parent: QWidget) -> tuple[QFrame, QLabel]:
        box = QFrame(parent)
        box.setObjectName("SupportMetaBox")
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(9, 7, 9, 7)
        box_layout.setSpacing(3)
        label = QLabel(caption, box)
        label.setObjectName("SupportMetaLabel")
        value = QLabel("—", box)
        value.setObjectName("SupportMetaValue")
        box_layout.addWidget(label)
        box_layout.addWidget(value)
        return box, value

    @staticmethod
    def _guide_step(
        number: str,
        text: str,
        parent: QWidget,
    ) -> QWidget:
        step = QWidget(parent)
        step.setObjectName("SupportGuideStep")
        step_layout = QHBoxLayout(step)
        step_layout.setContentsMargins(0, 0, 0, 0)
        step_layout.setSpacing(7)

        number_label = QLabel(number, step)
        number_label.setObjectName("SupportGuideNumber")
        number_label.setAlignment(Qt.AlignCenter)
        number_label.setFixedSize(18, 18)
        step_layout.addWidget(number_label, 0, Qt.AlignTop)

        text_label = QLabel(text, step)
        text_label.setObjectName("SupportGuideStepText")
        text_label.setWordWrap(True)
        step_layout.addWidget(text_label, 1)
        return step

    @staticmethod
    def _support_method_card(
        *,
        platform: str,
        title: str,
        description: str,
        button_text: str,
        icon_path: str,
        callback,
    ) -> tuple[QFrame, QPushButton]:
        card = QFrame()
        card.setObjectName("SupportMethodCard")
        card.setProperty("platform", platform)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 11, 12, 12)
        card_layout.setSpacing(5)

        title_label = QLabel(title, card)
        title_label.setObjectName("SupportMethodTitle")
        description_label = QLabel(description, card)
        description_label.setObjectName("SupportMethodDescription")
        description_label.setWordWrap(True)
        card_layout.addWidget(title_label)
        card_layout.addWidget(description_label)
        card_layout.addStretch(1)

        button = QPushButton(button_text, card)
        button.setObjectName(
            "SupportPatreonPrimary"
            if platform == "patreon"
            else "SupportCryptoPrimary"
        )
        button.setIcon(QIcon(resource_path(icon_path)))
        button.setIconSize(QSize(16, 16))
        button.clicked.connect(callback)
        card_layout.addWidget(button)
        return card, button

    @staticmethod
    def _secondary_link_button(
        text: str,
        icon_path: str,
        callback,
    ) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("SupportSecondaryLink")
        button.setIcon(QIcon(resource_path(icon_path)))
        button.setIconSize(QSize(15, 15))
        button.setFixedHeight(34)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        button.clicked.connect(callback)
        return button

    def reload(self) -> None:
        """Clear an unsubmitted key and repaint the controller's current state."""
        self.key_entry.clear()
        self._render_state(
            self._controller.state if self._controller is not None else None
        )

    def focus_primary_action(self) -> None:
        if self._state is None or not bool(getattr(self._state, "has_key", False)):
            self.key_entry.setFocus(Qt.OtherFocusReason)

    def activate_key(self) -> None:
        if self._controller is None:
            return
        raw_key = self.key_entry.text()
        if not raw_key.strip():
            self._sync_action_states()
            return
        self._controller.activate(raw_key)

    def check_now(self) -> None:
        if self._controller is not None:
            self._controller.check_now()

    def remove_key(self) -> None:
        if self._controller is None or self._state is None:
            return
        confirmed = QMessageBox.question(
            self,
            "Remove Supporter Key",
            "Remove the saved supporter key from this PC?\n\n"
            "Premium features will be disabled immediately.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirmed == QMessageBox.Yes:
            self._controller.remove_key()

    def _on_state_changed(self, state) -> None:
        self._render_state(state)

    def _render_state(self, state) -> None:
        self._state = state
        presentation = self._presentation(state)
        self.access_title.setText(presentation[0])
        self.status_badge.setText(presentation[1])
        self.status_badge.setProperty("tone", presentation[2])
        _repolish(self.status_badge)

        if state is None:
            self.access_message.setText(
                "Supporter access is unavailable in this application context."
            )
            has_key = False
            checking = False
            active = False
        else:
            self.access_message.setText(
                str(getattr(state, "message", "") or presentation[3])
            )
            has_key = bool(getattr(state, "has_key", False))
            checking = bool(getattr(state, "checking", False))
            active = bool(getattr(state, "active", False))

        self.key_entry_panel.setVisible(not has_key)
        self.saved_key_panel.setVisible(has_key)
        if has_key:
            self.key_hint.setText(str(getattr(state, "key_hint", "") or "Saved key"))
            self.checked_value.setText(
                _format_timestamp(getattr(state, "checked_at", None))
            )
            expiry = getattr(state, "expires_at", None)
            self.expiry_value.setText(
                _format_timestamp(expiry, date_only=True) if expiry else "No expiry"
            )
        if has_key and not checking:
            self.key_entry.clear()

        self.check_button.setEnabled(has_key and not checking)
        self.remove_button.setEnabled(has_key)
        self.access_guide_section.setVisible(not active)
        self._sync_action_states()

    def _sync_action_states(self) -> None:
        checking = bool(getattr(self._state, "checking", False))
        self.key_entry.setEnabled(self._controller is not None and not checking)
        self.activate_button.setEnabled(
            self._controller is not None
            and not checking
            and bool(self.key_entry.text().strip())
        )

    @staticmethod
    def _presentation(state) -> tuple[str, str, str, str]:
        if state is None:
            return (
                "Supporter access unavailable",
                "UNAVAILABLE",
                "neutral",
                "Supporter access is unavailable.",
            )
        if bool(getattr(state, "checking", False)):
            return (
                "Checking supporter access",
                "CHECKING",
                "checking",
                "Contacting the supporter service…",
            )
        status = str(getattr(state, "status", "") or "")
        presentations = {
            "no_key": (
                "Add your supporter key",
                "NO KEY",
                "neutral",
                "Enter the personal key you received after supporting BonkScanner.",
            ),
            "unchecked": (
                "Saved supporter key",
                "NOT CHECKED",
                "neutral",
                "The saved key has not been checked yet.",
            ),
            "active_subscription": (
                "Premium subscription",
                "ACTIVE",
                "active",
                "Premium subscription is active.",
            ),
            "active_supporter": (
                "Supporter access",
                "ACTIVE",
                "active",
                "Supporter privileges are active.",
            ),
            "cached_valid": (
                "Premium access",
                "OFFLINE READY",
                "cached",
                "Using recently verified access while the service is unavailable.",
            ),
            "expired": (
                "Access expired",
                "EXPIRED",
                "warning",
                "This access period has expired.",
            ),
            "invalid": (
                "Key not recognized",
                "INVALID",
                "danger",
                "This supporter key was not recognized.",
            ),
            "inactive": (
                "Plan inactive",
                "INACTIVE",
                "warning",
                "The assigned plan is currently inactive.",
            ),
            "no_access": (
                "No access plan",
                "NO ACCESS",
                "warning",
                "This key has no active access plan.",
            ),
            "pending": (
                "Access pending",
                "PENDING",
                "neutral",
                "This access period has not started yet.",
            ),
            "revoked": (
                "Access revoked",
                "REVOKED",
                "danger",
                "This supporter key has been revoked.",
            ),
            "suspended": (
                "Access suspended",
                "SUSPENDED",
                "danger",
                "Supporter access is suspended.",
            ),
            "offline_unknown": (
                "Could not verify access",
                "OFFLINE",
                "warning",
                "The supporter service could not be reached.",
            ),
        }
        return presentations.get(
            status,
            (
                "Supporter access",
                "UNKNOWN",
                "neutral",
                "Supporter access has not been checked.",
            ),
        )
