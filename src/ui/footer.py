"""The window's bottom strip: version, update status, and the links.

The main window had no footer at all -- ``build_layout`` put a header and a
splitter into the root layout and stopped -- so two things had nowhere to live.
The version was readable only in the title bar and in the log's welcome line,
which scrolls away; and the four support links existed only inside the settings
dialog, which nobody reopens after setting their hotkeys once.

Both go here, on one 28px line. The three links stay compact and backgroundless,
but no longer read like disabled metadata: GitHub and Discord carry quiet cool
colours, while Support carries the Patreon red. Hover draws one short line out
from the caption's centre. Support also owns the only ambient motion in the
strip -- a small double heartbeat after a long pause -- and replaces it with one
clear beat while the pointer is over the button.

The strip spans the whole window rather than sitting inside the 16px content
margins, which is why ``build_layout`` now nests its content in an inner widget:
a footer inset from the edges reads as a floating bar, not as the window's base.
"""
from __future__ import annotations

import math
import random
import time
import webbrowser

from PySide6.QtCore import (
    QAbstractAnimation,
    QEvent,
    Property,
    QEasingCurve,
    QLineF,
    QParallelAnimationGroup,
    QPoint,
    QRectF,
    QPropertyAnimation,
    QSequentialAnimationGroup,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app import config
from app.version import CURRENT_VERSION
from ui.dialogs.update_prompt import start_update_check
from ui.shared import _clear_layout, resource_path

FOOTER_HEIGHT = 28

PATREON_ICON_PATH = "media/patreon_logo.svg"
CRYPTO_ICON_PATH = "media/crypto_coins.svg"

# The selected HTML mock-up used 15 px badges.  Keep that exact logical size;
# scaling them down to 14 px made the fine 16-unit SVG strokes noticeably soft.
SUPPORT_BADGE_ICON_SIZE = 15
SUPPORT_BADGE_DEFINITIONS = (
    ("founder", "media/support_badge_founder.svg", "Founder"),
    ("extrasupport", "media/support_badge_extra.svg", "Extra support"),
    ("activesub", "media/support_badge_active.svg", "Active sub"),
)

FOOTER_HOVER_IN_MS = 180
FOOTER_HOVER_OUT_MS = 140
HEART_FONT_SCALE = 13.5 / 11.5
HEART_PASSIVE_PAUSE_MS = 3000
HEART_PASSIVE_FIRST_SCALE = 1.08
HEART_PASSIVE_SECOND_SCALE = 1.04
HEART_HOVER_SCALE = 1.09

SUPPORT_REMINDER_INTERVAL_MS = 60 * 60 * 1000
SUPPORT_REMINDER_RETRY_MS = 60 * 1000
SUPPORT_REMINDER_ACTIVATION_DELAY_MS = 900
SUPPORT_REMINDER_STARTUP_MIN_DELAY_MS = 4 * 1000
SUPPORT_REMINDER_STARTUP_MAX_DELAY_MS = 4 * 1000
SUPPORT_REMINDER_COOLDOWN_SECONDS = 30 * 60
SUPPORT_REMINDER_LONG_INACTIVE_SECONDS = 20 * 60
SUPPORT_REMINDER_SLIDE_IN_MS = 320
SUPPORT_REMINDER_SLIDE_OUT_MS = 260
SUPPORT_REMINDER_BEAT_LEAD_IN_MS = 260
SUPPORT_REMINDER_BETWEEN_BEATS_MS = 1550
# Four double-heartbeats still leave the complete sequence at eight seconds.
SUPPORT_REMINDER_BEAT_TAIL_MS = 990
SUPPORT_REMINDER_MAX_WIDTH = 520
SUPPORT_REMINDER_EDGE_MARGIN = 15
SUPPORT_REMINDER_GAP = 8
SUPPORT_REMINDER_FIRST_SCALE = 1.18
SUPPORT_REMINDER_SECOND_SCALE = 1.09
SUPPORT_REMINDER_FOOTER_FIRST_SCALE = 1.12
SUPPORT_REMINDER_FOOTER_SECOND_SCALE = 1.06
SUPPORT_REMINDER_FIRST_LIFT = 4.0
SUPPORT_REMINDER_SECOND_LIFT = 2.0
SUPPORT_REMINDER_STATE_CONFIG_KEY = "SUPPORT_REMINDER_STATE"


def _read_support_reminder_state() -> float:
    with config.config_lock:
        raw = config.user_config.get(SUPPORT_REMINDER_STATE_CONFIG_KEY)
        state = dict(raw) if isinstance(raw, dict) else {}

    try:
        last_shown_at = float(state.get("last_shown_at", 0.0))
    except (TypeError, ValueError, OverflowError):
        last_shown_at = 0.0
    if not math.isfinite(last_shown_at) or last_shown_at < 0.0:
        last_shown_at = 0.0
    now = time.time()
    if math.isfinite(now) and now >= 0.0 and last_shown_at > now:
        # A corrected system clock must not turn one reminder into an
        # indefinite sequence of fresh 30-minute waits.
        last_shown_at = now
    return last_shown_at


def _update_support_reminder_state(
    *,
    last_shown_at: float,
):
    """Persist the cooldown timestamp and discard the obsolete launch counter."""

    def mutate(candidate: dict) -> None:
        raw = candidate.get(SUPPORT_REMINDER_STATE_CONFIG_KEY)
        state = dict(raw) if isinstance(raw, dict) else {}
        state.pop("launch_count", None)
        shown_at = float(last_shown_at)
        state["last_shown_at"] = shown_at if math.isfinite(shown_at) else 0.0
        candidate[SUPPORT_REMINDER_STATE_CONFIG_KEY] = state

    return config.update_config(mutate)


def _mix_color(start: QColor, end: QColor, progress: float) -> QColor:
    """Interpolate two stylesheet-provided colours without changing geometry."""
    progress = max(0.0, min(1.0, float(progress)))
    return QColor.fromRgbF(
        start.redF() + (end.redF() - start.redF()) * progress,
        start.greenF() + (end.greenF() - start.greenF()) * progress,
        start.blueF() + (end.blueF() - start.blueF()) * progress,
        start.alphaF() + (end.alphaF() - start.alphaF()) * progress,
    )


class _AnimatedFooterLink(QPushButton):
    """A backgroundless footer link with a centre-out light trace on hover.

    QSS pseudo-states can switch colour and add a border, but they cannot
    interpolate either. Painting the two small pieces here keeps the visible
    contract in the stylesheet -- the three colours are qproperties -- while a
    single 0..1 property drives the colour lift, glow and underline together.
    """

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._rest_color = QColor("#B9C2CE")
        self._hover_color = QColor("#EDF1F5")
        self._line_color = QColor("#EDF1F5")
        self._hover_progress = 0.0

        self._hover_animation = QPropertyAnimation(self, b"hoverProgress", self)
        self._hover_animation.setEasingCurve(QEasingCurve.OutCubic)

    # -- stylesheet colours -------------------------------------------------

    def _get_rest_color(self) -> QColor:
        return QColor(self._rest_color)

    def _set_rest_color(self, color: QColor) -> None:
        self._rest_color = QColor(color)
        self.update()

    restColor = Property(QColor, _get_rest_color, _set_rest_color)

    def _get_hover_color(self) -> QColor:
        return QColor(self._hover_color)

    def _set_hover_color(self, color: QColor) -> None:
        self._hover_color = QColor(color)
        self.update()

    hoverColor = Property(QColor, _get_hover_color, _set_hover_color)

    def _get_line_color(self) -> QColor:
        return QColor(self._line_color)

    def _set_line_color(self, color: QColor) -> None:
        self._line_color = QColor(color)
        self.update()

    lineColor = Property(QColor, _get_line_color, _set_line_color)

    # -- hover progress ------------------------------------------------------

    def _get_hover_progress(self) -> float:
        return self._hover_progress

    def _set_hover_progress(self, value: float) -> None:
        self._hover_progress = max(0.0, min(1.0, float(value)))
        self.update()

    hoverProgress = Property(float, _get_hover_progress, _set_hover_progress)

    def _animate_hover(self, target: float) -> None:
        start = self._hover_progress
        target = max(0.0, min(1.0, float(target)))
        self._hover_animation.stop()
        if abs(target - start) < 0.001:
            self._hover_animation.setStartValue(start)
            self._hover_animation.setEndValue(target)
            self._set_hover_progress(target)
            return
        full_duration = FOOTER_HOVER_IN_MS if target > start else FOOTER_HOVER_OUT_MS
        self._hover_animation.setDuration(max(1, round(full_duration * abs(target - start))))
        self._hover_animation.setStartValue(start)
        self._hover_animation.setEndValue(target)
        self._hover_animation.start()

    def enterEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        self._animate_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        self._animate_hover(0.0)
        super().leaveEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        self._hover_animation.stop()
        self._set_hover_progress(0.0)
        super().hideEvent(event)

    # -- painting ------------------------------------------------------------

    @staticmethod
    def _draw_text(
        painter: QPainter,
        rect: QRectF,
        font: QFont,
        text: str,
        color: QColor,
        *,
        glow_alpha: int = 0,
    ) -> None:
        painter.setFont(font)
        flags = Qt.AlignCenter | Qt.TextSingleLine
        if glow_alpha > 0:
            glow = QColor(color)
            glow.setAlpha(max(0, min(255, glow_alpha)))
            painter.setPen(glow)
            for dx, dy in ((-1.0, 0.0), (1.0, 0.0), (0.0, -1.0), (0.0, 1.0)):
                painter.drawText(rect.translated(dx, dy), flags, text)
        painter.setPen(color)
        painter.drawText(rect, flags, text)

    def _content_width(self) -> float:
        return QFontMetricsF(self.font()).horizontalAdvance(self.text())

    def _paint_content(self, painter: QPainter, rect: QRectF, color: QColor) -> None:
        self._draw_text(
            painter,
            rect,
            self.font(),
            self.text(),
            color,
            glow_alpha=round(36 * self._hover_progress),
        )

    def paintEvent(self, _event) -> None:  # noqa: N802 -- Qt's name
        painter = QPainter(self)
        try:
            if not painter.isActive():
                return
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.TextAntialiasing, True)

            color = _mix_color(
                self._rest_color, self._hover_color, self._hover_progress
            )
            if self.isDown():
                color = color.darker(118)

            content = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -2.0)
            self._paint_content(painter, content, color)

            if self._hover_progress <= 0.001:
                return
            half_width = self._content_width() * self._hover_progress / 2.0
            centre_x = content.center().x()
            y = content.bottom() + 1.0
            line = QColor(self._line_color)

            halo = QColor(line)
            halo.setAlpha(round(42 * self._hover_progress))
            painter.setPen(QPen(halo, 3.0, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(
                QLineF(centre_x - half_width, y, centre_x + half_width, y)
            )

            line.setAlpha(round(220 * self._hover_progress))
            painter.setPen(QPen(line, 1.0, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(
                QLineF(centre_x - half_width, y, centre_x + half_width, y)
            )
        finally:
            if painter.isActive():
                painter.end()


class _SupportFooterLink(_AnimatedFooterLink):
    """The support link, with a separately painted and animated heart."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        self._caption = ""
        self._heart_scale = 1.0
        self._hovered = False
        self._heartbeat_suspended = False
        super().__init__("", parent)
        self.setText(text)

        self._ambient_heartbeat = QSequentialAnimationGroup(self)
        self._ambient_heartbeat.addPause(HEART_PASSIVE_PAUSE_MS)
        self._ambient_heartbeat.addAnimation(
            self._heart_step(1.0, HEART_PASSIVE_FIRST_SCALE, 80, QEasingCurve.OutCubic)
        )
        self._ambient_heartbeat.addAnimation(
            self._heart_step(HEART_PASSIVE_FIRST_SCALE, 1.0, 100, QEasingCurve.InCubic)
        )
        self._ambient_heartbeat.addPause(40)
        self._ambient_heartbeat.addAnimation(
            self._heart_step(1.0, HEART_PASSIVE_SECOND_SCALE, 70, QEasingCurve.OutCubic)
        )
        self._ambient_heartbeat.addAnimation(
            self._heart_step(HEART_PASSIVE_SECOND_SCALE, 1.0, 90, QEasingCurve.InCubic)
        )
        self._ambient_heartbeat.setLoopCount(-1)

        self._hover_heartbeat = QSequentialAnimationGroup(self)
        self._hover_heartbeat.addAnimation(
            self._heart_step(1.0, HEART_HOVER_SCALE, 90, QEasingCurve.OutCubic)
        )
        self._hover_heartbeat.addAnimation(
            self._heart_step(HEART_HOVER_SCALE, 1.0, 170, QEasingCurve.InCubic)
        )

    def _heart_step(
        self,
        start: float,
        end: float,
        duration: int,
        easing: QEasingCurve.Type,
    ) -> QPropertyAnimation:
        animation = QPropertyAnimation(self, b"heartScale")
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.setDuration(duration)
        animation.setEasingCurve(easing)
        return animation

    def _get_heart_scale(self) -> float:
        return self._heart_scale

    def _set_heart_scale(self, value: float) -> None:
        self._heart_scale = max(1.0, float(value))
        self.update()

    heartScale = Property(float, _get_heart_scale, _set_heart_scale)

    def setText(self, text: str) -> None:  # noqa: N802 -- Qt's name
        visible_text = str(text)
        self._caption = visible_text.replace("♥", "", 1).strip()
        super().setText(visible_text)
        self.updateGeometry()

    def caption(self) -> str:
        return self._caption

    def _heart_font(self) -> QFont:
        font = QFont(self.font())
        if font.pointSizeF() > 0:
            font.setPointSizeF(font.pointSizeF() * HEART_FONT_SCALE)
        elif font.pixelSize() > 0:
            font.setPixelSize(max(1, round(font.pixelSize() * HEART_FONT_SCALE)))
        return font

    def _content_metrics(self) -> tuple[QFont, float, float, float]:
        heart_font = self._heart_font()
        heart_width = QFontMetricsF(heart_font).horizontalAdvance("♥")
        caption_width = QFontMetricsF(self.font()).horizontalAdvance(self._caption)
        gap = 4.0
        return heart_font, heart_width, caption_width, gap

    def _content_width(self) -> float:
        _heart_font, heart_width, caption_width, gap = self._content_metrics()
        return heart_width + gap + caption_width

    def _paint_content(self, painter: QPainter, rect: QRectF, color: QColor) -> None:
        heart_font, heart_width, caption_width, gap = self._content_metrics()
        total_width = heart_width + gap + caption_width
        start_x = rect.center().x() - total_width / 2.0
        heart_rect = QRectF(start_x, rect.top(), heart_width, rect.height())
        caption_rect = QRectF(
            start_x + heart_width + gap,
            rect.top(),
            caption_width,
            rect.height(),
        )

        self._draw_text(
            painter,
            caption_rect,
            self.font(),
            self._caption,
            color,
            glow_alpha=round(36 * self._hover_progress),
        )

        pulse = max(
            0.0,
            min(1.0, (self._heart_scale - 1.0) / (HEART_HOVER_SCALE - 1.0)),
        )
        painter.save()
        centre = heart_rect.center()
        painter.translate(centre)
        painter.scale(self._heart_scale, self._heart_scale)
        painter.translate(-centre)
        self._draw_text(
            painter,
            heart_rect,
            heart_font,
            "♥",
            color,
            glow_alpha=round(max(48 * self._hover_progress, 86 * pulse)),
        )
        painter.restore()

    def sizeHint(self) -> QSize:  # noqa: N802 -- Qt's name
        hint = super().sizeHint()
        return QSize(hint.width() + 3, max(24, hint.height()))

    def minimumSizeHint(self) -> QSize:  # noqa: N802 -- Qt's name
        return self.sizeHint()

    def _restart_ambient_heartbeat(self) -> None:
        self._ambient_heartbeat.stop()
        self._set_heart_scale(1.0)
        if (
            self.isVisible()
            and not self._hovered
            and not self._heartbeat_suspended
        ):
            # The pause is the first animation, so every restart waits before
            # drawing the next passive beat instead of answering a hover twice.
            self._ambient_heartbeat.start()

    def suspend_heartbeat(self) -> None:
        """Let a larger support animation drive this heart temporarily."""
        self._heartbeat_suspended = True
        self._ambient_heartbeat.stop()
        self._hover_heartbeat.stop()
        self._set_heart_scale(1.0)

    def resume_heartbeat(self) -> None:
        """Return ownership to the usual hover/passive heartbeat."""
        self._heartbeat_suspended = False
        self._hover_heartbeat.stop()
        self._set_heart_scale(1.0)
        if self._hovered and self.isVisible():
            self._hover_heartbeat.start()
        else:
            self._restart_ambient_heartbeat()

    def enterEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        self._hovered = True
        self._ambient_heartbeat.stop()
        self._hover_heartbeat.stop()
        self._set_heart_scale(1.0)
        if not self._heartbeat_suspended:
            self._hover_heartbeat.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        self._hovered = False
        self._hover_heartbeat.stop()
        self._set_heart_scale(1.0)
        super().leaveEvent(event)
        if not self._heartbeat_suspended:
            self._restart_ambient_heartbeat()

    def showEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        super().showEvent(event)
        self._restart_ambient_heartbeat()

    def hideEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        self._hovered = False
        self._ambient_heartbeat.stop()
        self._hover_heartbeat.stop()
        self._set_heart_scale(1.0)
        super().hideEvent(event)


class _SupportReminderHeart(QWidget):
    """A fixed-size heart that can pulse without reflowing the reminder."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._heart_scale = 1.0
        self._heart_color = QColor("#FF6F61")
        self.setObjectName("supportReminderHeart")

    def _get_heart_scale(self) -> float:
        return self._heart_scale

    def _set_heart_scale(self, value: float) -> None:
        self._heart_scale = max(1.0, float(value))
        self.update()

    heartScale = Property(float, _get_heart_scale, _set_heart_scale)

    def _get_heart_color(self) -> QColor:
        return QColor(self._heart_color)

    def _set_heart_color(self, color: QColor) -> None:
        self._heart_color = QColor(color)
        self.update()

    heartColor = Property(QColor, _get_heart_color, _set_heart_color)

    def sizeHint(self) -> QSize:  # noqa: N802 -- Qt's name
        metrics = QFontMetricsF(self.font())
        return QSize(
            max(20, round(metrics.horizontalAdvance("♥") * 1.35)),
            max(24, round(metrics.height() * 1.35)),
        )

    def minimumSizeHint(self) -> QSize:  # noqa: N802 -- Qt's name
        return self.sizeHint()

    def paintEvent(self, _event) -> None:  # noqa: N802 -- Qt's name
        painter = QPainter(self)
        try:
            if not painter.isActive():
                return
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.TextAntialiasing, True)
            rect = QRectF(self.rect())
            centre = rect.center()
            painter.translate(centre)
            painter.scale(self._heart_scale, self._heart_scale)
            painter.translate(-centre)
            painter.setFont(self.font())

            pulse = min(
                1.0,
                (self._heart_scale - 1.0) / (SUPPORT_REMINDER_FIRST_SCALE - 1.0),
            )
            if pulse > 0.0:
                glow = QColor(self._heart_color)
                glow.setAlpha(round(76 * pulse))
                painter.setPen(glow)
                for dx, dy in (
                    (-1.0, 0.0),
                    (1.0, 0.0),
                    (0.0, -1.0),
                    (0.0, 1.0),
                ):
                    painter.drawText(
                        rect.translated(dx, dy),
                        Qt.AlignCenter | Qt.TextSingleLine,
                        "♥",
                    )
            painter.setPen(self._heart_color)
            painter.drawText(rect, Qt.AlignCenter | Qt.TextSingleLine, "♥")
        finally:
            if painter.isActive():
                painter.end()


class _SupportReminder(QFrame):
    """A periodic support card that rises out of the footer and beats with it."""

    def __init__(
        self,
        *,
        parent: QWidget,
        footer_frame: QFrame,
        support_link: _SupportFooterLink,
        activate,
        can_show,
        last_shown_at: float,
        record_show,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("supportReminder")
        self.setAttribute(Qt.WA_StyledBackground, True)

        self._footer_frame = footer_frame
        self._support_link = support_link
        self._activate = activate
        self._can_show = can_show
        self._last_shown_at = max(0.0, float(last_shown_at))
        self._last_shown_monotonic: float | None = None
        if self._last_shown_at > 0.0:
            wall_elapsed = time.time() - self._last_shown_at
            if math.isfinite(wall_elapsed):
                self._last_shown_monotonic = time.monotonic() - max(
                    0.0,
                    wall_elapsed,
                )
        self._record_show = record_show
        self._host_window = parent.window()
        self._lift_progress = 0.0
        self._pulse_offset = 0.0
        self._playing = False
        self._due = False
        self._due_bypasses_cooldown = False
        self._last_interval_ms = 0
        self._last_startup_delay_ms = 0
        self._inactive_since: float | None = None

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 7, 9, 7)
        row.setSpacing(8)

        self._heart = _SupportReminderHeart(self)
        row.addWidget(self._heart, 0, Qt.AlignVCenter)

        self._message = QLabel(
            "Updates are fueled by BonkScanner supporters. Thank you!",
            self,
        )
        self._message.setObjectName("supportReminderText")
        self._message.setWordWrap(True)
        row.addWidget(self._message, 1, Qt.AlignVCenter)

        self._action = QPushButton("Support", self)
        self._action.setObjectName("supportReminderButton")
        self._action.setCursor(Qt.PointingHandCursor)
        self._action.setFocusPolicy(Qt.NoFocus)
        self._action.clicked.connect(self._activate_clicked)
        row.addWidget(self._action, 0, Qt.AlignVCenter)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._mark_due)

        self._startup_timer = QTimer(self)
        self._startup_timer.setSingleShot(True)
        self._startup_timer.setTimerType(Qt.PreciseTimer)
        self._startup_timer.timeout.connect(self._mark_startup_due)

        self._activation_timer = QTimer(self)
        self._activation_timer.setSingleShot(True)
        self._activation_timer.setTimerType(Qt.PreciseTimer)
        self._activation_timer.setInterval(SUPPORT_REMINDER_ACTIVATION_DELAY_MS)
        self._activation_timer.timeout.connect(self._play_if_due)

        self._animation = self._build_animation()
        self._animation.finished.connect(self._animation_finished)

        parent.installEventFilter(self)
        if self._host_window is not parent:
            self._host_window.installEventFilter(self)
        application = QApplication.instance()
        self._application = application
        if application is not None:
            application.applicationStateChanged.connect(
                self._application_state_changed
            )
            if application.applicationState() != Qt.ApplicationActive:
                self._inactive_since = time.monotonic()
        self.hide()

    @staticmethod
    def _animation_step(
        target,
        property_name: bytes,
        start,
        end,
        duration: int,
        easing: QEasingCurve.Type,
    ) -> QPropertyAnimation:
        animation = QPropertyAnimation(target, property_name)
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.setDuration(duration)
        animation.setEasingCurve(easing)
        return animation

    def _pulse_step(
        self,
        *,
        card_start: float,
        card_end: float,
        footer_start: float,
        footer_end: float,
        lift_start: float,
        lift_end: float,
        duration: int,
        easing: QEasingCurve.Type,
    ) -> QParallelAnimationGroup:
        group = QParallelAnimationGroup()
        group.addAnimation(
            self._animation_step(
                self._heart,
                b"heartScale",
                card_start,
                card_end,
                duration,
                easing,
            )
        )
        group.addAnimation(
            self._animation_step(
                self._support_link,
                b"heartScale",
                footer_start,
                footer_end,
                duration,
                easing,
            )
        )
        group.addAnimation(
            self._animation_step(
                self,
                b"pulseOffset",
                lift_start,
                lift_end,
                duration,
                easing,
            )
        )
        return group

    def _heartbeat(self) -> QSequentialAnimationGroup:
        heartbeat = QSequentialAnimationGroup()
        heartbeat.addAnimation(
            self._pulse_step(
                card_start=1.0,
                card_end=SUPPORT_REMINDER_FIRST_SCALE,
                footer_start=1.0,
                footer_end=SUPPORT_REMINDER_FOOTER_FIRST_SCALE,
                lift_start=0.0,
                lift_end=SUPPORT_REMINDER_FIRST_LIFT,
                duration=80,
                easing=QEasingCurve.OutCubic,
            )
        )
        heartbeat.addAnimation(
            self._pulse_step(
                card_start=SUPPORT_REMINDER_FIRST_SCALE,
                card_end=1.0,
                footer_start=SUPPORT_REMINDER_FOOTER_FIRST_SCALE,
                footer_end=1.0,
                lift_start=SUPPORT_REMINDER_FIRST_LIFT,
                lift_end=0.0,
                duration=100,
                easing=QEasingCurve.InCubic,
            )
        )
        heartbeat.addPause(40)
        heartbeat.addAnimation(
            self._pulse_step(
                card_start=1.0,
                card_end=SUPPORT_REMINDER_SECOND_SCALE,
                footer_start=1.0,
                footer_end=SUPPORT_REMINDER_FOOTER_SECOND_SCALE,
                lift_start=0.0,
                lift_end=SUPPORT_REMINDER_SECOND_LIFT,
                duration=70,
                easing=QEasingCurve.OutCubic,
            )
        )
        heartbeat.addAnimation(
            self._pulse_step(
                card_start=SUPPORT_REMINDER_SECOND_SCALE,
                card_end=1.0,
                footer_start=SUPPORT_REMINDER_FOOTER_SECOND_SCALE,
                footer_end=1.0,
                lift_start=SUPPORT_REMINDER_SECOND_LIFT,
                lift_end=0.0,
                duration=90,
                easing=QEasingCurve.InCubic,
            )
        )
        return heartbeat

    def _build_animation(self) -> QSequentialAnimationGroup:
        animation = QSequentialAnimationGroup(self)
        animation.addAnimation(
            self._animation_step(
                self,
                b"liftProgress",
                0.0,
                1.0,
                SUPPORT_REMINDER_SLIDE_IN_MS,
                QEasingCurve.OutCubic,
            )
        )
        animation.addPause(SUPPORT_REMINDER_BEAT_LEAD_IN_MS)
        animation.addAnimation(self._heartbeat())
        animation.addPause(SUPPORT_REMINDER_BETWEEN_BEATS_MS)
        animation.addAnimation(self._heartbeat())
        animation.addPause(SUPPORT_REMINDER_BETWEEN_BEATS_MS)
        animation.addAnimation(self._heartbeat())
        animation.addPause(SUPPORT_REMINDER_BETWEEN_BEATS_MS)
        animation.addAnimation(self._heartbeat())
        animation.addPause(SUPPORT_REMINDER_BEAT_TAIL_MS)
        animation.addAnimation(
            self._animation_step(
                self,
                b"liftProgress",
                1.0,
                0.0,
                SUPPORT_REMINDER_SLIDE_OUT_MS,
                QEasingCurve.InCubic,
            )
        )
        return animation

    def _get_lift_progress(self) -> float:
        return self._lift_progress

    def _set_lift_progress(self, value: float) -> None:
        self._lift_progress = max(0.0, min(1.0, float(value)))
        self._reposition()

    liftProgress = Property(float, _get_lift_progress, _set_lift_progress)

    def _get_pulse_offset(self) -> float:
        return self._pulse_offset

    def _set_pulse_offset(self, value: float) -> None:
        self._pulse_offset = max(0.0, float(value))
        self._reposition()

    pulseOffset = Property(float, _get_pulse_offset, _set_pulse_offset)

    def start(self) -> None:
        self._schedule_next()
        self._last_startup_delay_ms = random.randint(
            SUPPORT_REMINDER_STARTUP_MIN_DELAY_MS,
            SUPPORT_REMINDER_STARTUP_MAX_DELAY_MS,
        )
        self._startup_timer.start(self._last_startup_delay_ms)

    def _schedule_next(self) -> None:
        self._timer.stop()
        self._startup_timer.stop()
        self._activation_timer.stop()
        self._due = False
        self._due_bypasses_cooldown = False
        self._last_interval_ms = SUPPORT_REMINDER_INTERVAL_MS
        self._timer.start(self._last_interval_ms)

    def _mark_due(self, *, bypass_cooldown: bool = False) -> None:
        # Once a trigger wins, the other timer must no longer postpone retries
        # when the window is temporarily unavailable. A startup retry keeps its
        # cooldown exemption; periodic and inactivity triggers never acquire it.
        was_due = self._due
        self._timer.stop()
        self._startup_timer.stop()
        self._due = True
        if bypass_cooldown or not was_due:
            self._due_bypasses_cooldown = bypass_cooldown
        self._play_if_due()

    def _mark_startup_due(self) -> None:
        self._mark_due(bypass_cooldown=True)

    def _window_is_ready(self) -> bool:
        window = self._host_window
        return (
            window.isVisible()
            and window.isActiveWindow()
            and not bool(window.windowState() & Qt.WindowMinimized)
            and not self._support_link.underMouse()
            and self._can_show()
        )

    def _cooldown_remaining_ms(self) -> int:
        if self._last_shown_at <= 0.0:
            return 0
        if self._last_shown_monotonic is not None:
            elapsed = time.monotonic() - self._last_shown_monotonic
        else:
            now = time.time()
            elapsed = now - self._last_shown_at
            if math.isfinite(now) and elapsed < 0.0:
                self._last_shown_at = now
                self._last_shown_monotonic = time.monotonic()
                elapsed = 0.0
        if not math.isfinite(elapsed):
            elapsed = 0.0
        remaining = SUPPORT_REMINDER_COOLDOWN_SECONDS - max(0.0, elapsed)
        return max(0, math.ceil(remaining * 1000.0))

    def _play_if_due(self) -> bool:
        if not self._due:
            return False
        if not self._due_bypasses_cooldown:
            cooldown_remaining_ms = self._cooldown_remaining_ms()
            if cooldown_remaining_ms > 0:
                self._timer.start(cooldown_remaining_ms)
                return False
        if not self._window_is_ready():
            if not self._timer.isActive():
                self._timer.start(SUPPORT_REMINDER_RETRY_MS)
            return False
        return self.play()

    def play(self, *, force: bool = False) -> bool:
        if self._playing or self._animation.state() != QAbstractAnimation.Stopped:
            return False
        if not force:
            if not self._due or not self._window_is_ready():
                return False
            if (
                not self._due_bypasses_cooldown
                and self._cooldown_remaining_ms() > 0
            ):
                return False

        self._timer.stop()
        self._startup_timer.stop()
        self._activation_timer.stop()
        self._due = False
        self._due_bypasses_cooldown = False
        self._playing = True
        shown_at = time.time()
        self._last_shown_at = shown_at
        self._last_shown_monotonic = time.monotonic()
        self._record_show(shown_at)
        self._set_lift_progress(0.0)
        self._set_pulse_offset(0.0)
        self._heart._set_heart_scale(1.0)
        self._support_link.suspend_heartbeat()
        self._sync_geometry()
        self.show()
        self.raise_()
        self._animation.start()
        return True

    def dismiss(self) -> None:
        self._timer.stop()
        self._startup_timer.stop()
        self._activation_timer.stop()
        self._due = False
        self._due_bypasses_cooldown = False
        if self._animation.state() != QAbstractAnimation.Stopped:
            self._animation.stop()
        self._finish_playback(schedule_next=True)

    def _activate_clicked(self) -> None:
        self._activate()

    def _animation_finished(self) -> None:
        self._finish_playback(schedule_next=True)

    def _finish_playback(self, *, schedule_next: bool) -> None:
        self._playing = False
        self.hide()
        self._set_lift_progress(0.0)
        self._set_pulse_offset(0.0)
        self._heart._set_heart_scale(1.0)
        self._support_link.resume_heartbeat()
        if schedule_next:
            self._schedule_next()

    def _sync_geometry(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        available = max(1, parent.width() - 2 * SUPPORT_REMINDER_EDGE_MARGIN)
        self.setFixedWidth(min(SUPPORT_REMINDER_MAX_WIDTH, available))
        self.ensurePolished()
        if self.layout() is not None:
            self.layout().invalidate()
            self.layout().activate()
        self.adjustSize()
        self._reposition()

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None or self.width() <= 0 or self.height() <= 0:
            return
        try:
            footer_top = self._footer_frame.mapTo(parent, QPoint(0, 0)).y()
            anchor_right = self._support_link.mapTo(
                parent,
                QPoint(self._support_link.width(), 0),
            ).x()
        except RuntimeError:
            return

        min_x = SUPPORT_REMINDER_EDGE_MARGIN
        max_x = max(
            min_x,
            parent.width() - SUPPORT_REMINDER_EDGE_MARGIN - self.width(),
        )
        x = min(max(anchor_right - self.width(), min_x), max_x)
        visible_y = footer_top - self.height() - SUPPORT_REMINDER_GAP
        hidden_y = parent.height() + 1
        y = hidden_y + (visible_y - hidden_y) * self._lift_progress
        y -= self._pulse_offset
        self.move(round(x), round(y))

    def _schedule_activation_attempt(self) -> None:
        if not self._due:
            return
        self._timer.stop()
        self._startup_timer.stop()
        self._activation_timer.start()

    def _application_state_changed(self, state) -> None:
        if state != Qt.ApplicationActive:
            self._activation_timer.stop()
            if self._inactive_since is None:
                self._inactive_since = time.monotonic()
            return

        inactive_since = self._inactive_since
        self._inactive_since = None
        if inactive_since is not None:
            inactive_for = max(0.0, time.monotonic() - inactive_since)
            if inactive_for >= SUPPORT_REMINDER_LONG_INACTIVE_SECONDS:
                if not self._due:
                    self._due_bypasses_cooldown = False
                self._due = True
        self._schedule_activation_attempt()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 -- Qt's name
        event_type = event.type()
        if event_type in {QEvent.Resize, QEvent.LayoutRequest, QEvent.Show}:
            if self.isVisible():
                self._sync_geometry()
        if watched is self._host_window:
            if event_type == QEvent.WindowDeactivate:
                self._activation_timer.stop()
            elif event_type == QEvent.WindowActivate:
                self._schedule_activation_attempt()
        return super().eventFilter(watched, event)


def _separator() -> QFrame:
    """The hairline between two footer items.

    A `QFrame` with `VLine` draws Qt's own etched line, which is two colours and
    ignores the stylesheet. One pixel of background does what the design asks
    and stays reachable from the QSS -- the same trick `#dialogHeadRule` uses.
    """
    line = QFrame()
    line.setObjectName("footerSeparator")
    line.setFixedWidth(1)
    line.setFixedHeight(11)
    return line


def _link(
    text: str,
    object_name: str = "footerLink",
    *,
    link_role: str = "",
) -> QPushButton:
    if object_name == "footerSupportLink":
        button = _SupportFooterLink(text)
    elif object_name == "footerLink":
        button = _AnimatedFooterLink(text)
    else:
        button = QPushButton(text)
    button.setObjectName(object_name)
    if link_role:
        button.setProperty("linkRole", link_role)
    button.setFlat(True)
    button.setCursor(Qt.PointingHandCursor)
    # Without this a footer link steals the focus ring on click and keeps it,
    # which on a strip this thin reads as a stuck highlight.
    button.setFocusPolicy(Qt.NoFocus)
    return button


class _TintedSupportBadgeIcon(QLabel):
    """A monochrome SVG painted in the exact colour of another label."""

    def __init__(
        self,
        icon_path: str,
        color_source: QLabel,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self._svg_icon = QIcon(resource_path(icon_path))
        self._color_source = color_source
        self._rendered_color = QColor()
        self._rendered_dpr = 0.0
        self._tinted_pixmap = QPixmap()
        self.setFixedSize(SUPPORT_BADGE_ICON_SIZE, SUPPORT_BADGE_ICON_SIZE)

    def _refresh_tint(self) -> None:
        color = self._color_source.palette().color(
            self._color_source.foregroundRole()
        )
        dpr = self.devicePixelRatioF()
        if (
            not self._tinted_pixmap.isNull()
            and color.rgba() == self._rendered_color.rgba()
            and abs(dpr - self._rendered_dpr) < 0.001
        ):
            return

        size = QSize(SUPPORT_BADGE_ICON_SIZE, SUPPORT_BADGE_ICON_SIZE)
        # Request the SVG at the screen's physical resolution.  A plain
        # ``pixmap(size)`` is a 1x raster which Qt then stretches on common
        # 125%/150% Windows scaling, blurring these very small outlines.
        source = self._svg_icon.pixmap(size, dpr)
        tinted = QPixmap(source.size())
        tinted.setDevicePixelRatio(source.devicePixelRatio())
        tinted.fill(Qt.transparent)
        painter = QPainter(tinted)
        try:
            if painter.isActive():
                painter.drawPixmap(0, 0, source)
                painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
                painter.fillRect(tinted.rect(), color)
        finally:
            if painter.isActive():
                painter.end()
        self._tinted_pixmap = tinted
        self._rendered_color = QColor(color)
        self._rendered_dpr = dpr

    def paintEvent(self, _event) -> None:
        self._refresh_tint()
        painter = QPainter(self)
        try:
            if painter.isActive():
                painter.drawPixmap(0, 0, self._tinted_pixmap)
        finally:
            if painter.isActive():
                painter.end()


def _support_badge_icon(
    badge_key: str,
    icon_path: str,
    tooltip: str,
    color_source: QLabel,
    parent: QWidget,
    *,
    object_name: str = "supporterBadgeIcon",
) -> QLabel:
    """Build a badge that inherits the colour of its caption or supporter."""
    icon = _TintedSupportBadgeIcon(icon_path, color_source, parent)
    icon.setObjectName(object_name)
    icon.setProperty("badge", badge_key)
    icon.setToolTip(tooltip)
    return icon


class _SupporterNameRow(QWidget):
    """One supporter name with zero or more real icons, not font glyphs."""

    def __init__(
        self,
        name: str,
        name_object: str,
        badges: tuple[str, ...],
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("supporterNameRow")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.name_label = QLabel(name, self)
        self.name_label.setObjectName(name_object)
        self.name_label.setTextFormat(Qt.PlainText)
        self.name_label.setToolTip(name)

        badge_definitions = {
            key: (icon_path, caption)
            for key, icon_path, caption in SUPPORT_BADGE_DEFINITIONS
        }
        for badge_key in badges:
            icon_path, caption = badge_definitions[badge_key]
            layout.addWidget(
                _support_badge_icon(
                    badge_key,
                    icon_path,
                    caption,
                    self.name_label,
                    self,
                    object_name="supporterNameBadgeIcon",
                ),
                0,
                Qt.AlignVCenter,
            )
        layout.addWidget(self.name_label, 1, Qt.AlignVCenter)


class SupportPopup(QFrame):
    """The support route, with one line of context.

    A popup rather than a link straight to Patreon because it provides the
    brief context a bare link lacks, and the same shape grows into the
    supporters list later without moving.

    `Qt.Popup` gives the dismiss-on-outside-click behaviour for free. The
    translucent top level wrapping an inner card is what lets the card have
    rounded corners: a `Qt.Popup` frame paints its own square background
    underneath them otherwise.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        open_url=None,
    ) -> None:
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self._open_url = open_url or self._open_browser_page
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName("supportPopup")

        #: The widget this was last opened against, so the card can re-anchor
        #: itself if its contents change while it is on screen.
        self._anchor: QWidget | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame(self)
        card.setObjectName("supportPopupCard")
        # The wider card gives the support message room to breathe instead of
        # leaving it as a dense caption above the platform buttons.
        card.setFixedWidth(self.NARROW_WIDTH)
        outer.addWidget(card)

        body = QVBoxLayout(card)
        body.setContentsMargins(12, 11, 12, 12)
        body.setSpacing(3)

        title = QLabel("Support BonkScanner", card)
        title.setObjectName("supportPopupTitle")
        body.addWidget(title)

        note = QLabel(self.DEFAULT_NOTE, card)
        note.setObjectName("supportPopupNote")
        note.setWordWrap(True)
        body.addWidget(note)
        self._title = title
        self._note = note

        # Two deliberately separate signals: colour says where someone
        # supported, while the symbols say what they have done. Two compact
        # rows keep that distinction visible; a single line reads like one
        # mixed list of tiers.
        self._legend = QWidget(card)
        self._legend.setObjectName("supporterLegend")
        legend_layout = QVBoxLayout(self._legend)
        legend_layout.setContentsMargins(0, 2, 0, 2)
        legend_layout.setSpacing(5)

        source_row = QHBoxLayout()
        source_row.setSpacing(7)
        source_heading = QLabel("Source:", self._legend)
        source_heading.setObjectName("supporterLegendSourceHeading")
        source_heading.setTextFormat(Qt.PlainText)
        source_row.addWidget(source_heading, 0, Qt.AlignVCenter)
        for object_name, caption in (
            ("supporterLegendPatreon", "●  Patreon"),
            ("supporterLegendDirect", "●  Direct"),
        ):
            label = QLabel(caption, self._legend)
            label.setObjectName(object_name)
            label.setTextFormat(Qt.PlainText)
            source_row.addWidget(label, 0, Qt.AlignVCenter)
        source_row.addStretch(1)
        legend_layout.addLayout(source_row)

        badge_row = QHBoxLayout()
        badge_row.setSpacing(7)
        badge_heading = QLabel("Badges:", self._legend)
        badge_heading.setObjectName("supporterLegendBadgesHeading")
        badge_heading.setTextFormat(Qt.PlainText)
        badge_row.addWidget(badge_heading, 0, Qt.AlignVCenter)
        for object_name, (badge_key, icon_path, caption) in zip(
            (
                "supporterLegendFounder",
                "supporterLegendExtraSupport",
                "supporterLegendSub",
            ),
            SUPPORT_BADGE_DEFINITIONS,
        ):
            item = QWidget(self._legend)
            item.setObjectName(f"{object_name}Item")
            item_layout = QHBoxLayout(item)
            item_layout.setContentsMargins(0, 0, 0, 0)
            item_layout.setSpacing(4)
            label = QLabel(caption, item)
            label.setObjectName(object_name)
            label.setTextFormat(Qt.PlainText)
            item_layout.addWidget(
                _support_badge_icon(
                    badge_key,
                    icon_path,
                    caption,
                    label,
                    item,
                    object_name=f"{object_name}Icon",
                ),
                0,
                Qt.AlignVCenter,
            )
            item_layout.addWidget(label, 0, Qt.AlignVCenter)
            badge_row.addWidget(item, 0, Qt.AlignVCenter)
        badge_row.addStretch(1)
        legend_layout.addLayout(badge_row)
        self._legend.setVisible(False)
        body.addWidget(self._legend)

        # The names, when there are any. Built empty and hidden, so the popup
        # is exactly what it was until something calls `set_supporters` -- see
        # that method for why the empty case must look like this and not like a
        # heading over a blank space.
        self._names_host = QWidget(card)
        self._names_host.setObjectName("supporterList")
        self._names_grid = QGridLayout(self._names_host)
        # The body already adds 3px between groups. The extra top margin gives
        # the changing names list a clear 10px break after the legend, while
        # the hidden host keeps an empty card exactly as compact as before.
        self._names_grid.setContentsMargins(0, 7, 0, 4)
        self._names_grid.setHorizontalSpacing(16)
        self._names_grid.setVerticalSpacing(1)
        self._names_host.setVisible(False)
        body.addWidget(self._names_host)

        self._rule = QFrame(card)
        self._rule.setObjectName("supportPopupRule")
        self._rule.setFixedHeight(1)
        self._rule.setVisible(False)
        body.addWidget(self._rule)

        body.addSpacing(7)

        buttons = QHBoxLayout()
        buttons.setSpacing(7)
        # The same object names as the settings card's buttons keep both support
        # routes in one set of QSS rules instead of letting the two places drift.
        self.patreon_btn = QPushButton("Patreon", card)
        self.patreon_btn.setObjectName("PatreonButton")
        self.patreon_btn.setIcon(QIcon(resource_path(PATREON_ICON_PATH)))
        self.patreon_btn.setIconSize(QSize(18, 18))
        self.patreon_btn.clicked.connect(self._open_patreon)
        self.crypto_btn = QPushButton("Crypto", card)
        self.crypto_btn.setObjectName("CryptoButton")
        self.crypto_btn.setIcon(QIcon(resource_path(CRYPTO_ICON_PATH)))
        self.crypto_btn.setIconSize(QSize(18, 18))
        self.crypto_btn.clicked.connect(self._open_crypto)
        self.crypto_btn.setEnabled(bool(config.CRYPTO_SUPPORT_URL))
        if not config.CRYPTO_SUPPORT_URL:
            self.crypto_btn.setToolTip("Crypto support page is coming soon.")
        for button in (self.patreon_btn, self.crypto_btn):
            button.setCursor(Qt.PointingHandCursor)
            buttons.addWidget(button, 1)
        body.addLayout(buttons)
        self._card = card

    #: Card widths. The narrow one gives the support message a relaxed wrap; the
    #: wide one by two columns of display name, which are user-supplied text and
    #: can be any length -- they ellipsise rather than widen the card further.
    NARROW_WIDTH = 320
    WIDE_WIDTH = 560
    DEFAULT_NOTE = "If it helps your runs, you can throw a little fuel its way."
    #: Names past this are not listed; the count in the caption still includes
    #: them. A popup is not a page, and a scroll bar inside one is a worse
    #: answer than "and 40 others".
    MAX_LISTED = 24

    #: How a `source` value is drawn: `(object name, sort rank)`.
    #:
    #: The colour is deliberately only provenance, never amount or rank.
    #: Patreon keeps its brand accent. Direct uses the former support blue for
    #: crypto, transfers, gifts, or any later off-platform support.
    SOURCE_STYLES = {
        "patreon": ("supporterNamePatreon", 0),
        "direct": ("supporterNameDirect", 1),
    }
    #: Compatibility for the live `supporters.json` used by builds released
    #: before source and badges became independent.  The remote file can change
    #: between application releases, so a rollout must work in either order.
    LEGACY_TIER_MIGRATIONS = {
        "patreon": ("patreon", ("active_sub",)),
        "pack": ("patreon", ("extra_support",)),
    }
    BADGE_ALIASES = {"pack": "extrasupport"}
    #: Stackable acknowledgements. Tuple order is display order; input order in
    #: a hand-edited JSON file cannot make the icons jump. Founder and extra
    #: support are permanent; active-sub is the one live status.
    BADGE_DEFINITIONS = SUPPORT_BADGE_DEFINITIONS
    #: Unknown provenance stays neutral rather than borrowing Direct's colour.
    #: A source typo costs the platform colour, never badges supplied separately.
    UNKNOWN_SOURCE_STYLE = ("supporterName", 2)
    #: No source at all -- a bare `"Name"` string. Deliberately unmarked.
    PLAIN_STYLE = ("supporterName", 3)

    @staticmethod
    def _support_key(value) -> str:
        """Normalise hand-written source and badge keys."""
        return "".join(
            character
            for character in str(value or "").lower()
            if character.isalnum()
        )

    @classmethod
    def _supporter_badges(cls, badges) -> tuple[str, ...]:
        """Return known badge keys in one stable order, without duplicates."""
        badge_keys = set()
        if isinstance(badges, (list, tuple)):
            for badge in badges:
                key = cls._support_key(badge)
                badge_keys.add(cls.BADGE_ALIASES.get(key, key))
        return tuple(
            key
            for key, _icon_path, _caption in cls.BADGE_DEFINITIONS
            if key in badge_keys
        )

    def set_supporters(self, supporters=()) -> None:
        """Show these people, or go back to being the plain support card.

        **The empty case is the shipping case and must stay unremarkable.**
        The list is fetched, so every copy of the application starts here and a
        good number of them stay: no network, no names published yet, an older
        build. What the card looks like with no list is what those people see --
        a title, one line, support routes. No heading over a blank space, no
        "0 supporters", no rule with nothing above it. An empty card reads as a
        broken feature; a card that never mentions the list reads as nothing at
        all, which is correct.

        Accepts plain names or mappings, so `supporters.json` needs no shape
        negotiation: `"Nyxaria"` and
        `{"name": "Nyxaria", "source": "patreon"}` both work.
        """
        people = []
        for entry in supporters or ():
            if isinstance(entry, dict):
                name = str(entry.get("name") or "").strip()
                source_key = self._support_key(entry.get("source"))
                legacy_badges = ()
                if not source_key:
                    tier_key = self._support_key(entry.get("tier"))
                    migration = self.LEGACY_TIER_MIGRATIONS.get(tier_key)
                    if migration is not None:
                        source_key, legacy_badges = migration
                    elif tier_key:
                        source_key = tier_key
                if source_key in self.SOURCE_STYLES:
                    style = self.SOURCE_STYLES[source_key]
                elif source_key:
                    style = self.UNKNOWN_SOURCE_STYLE
                else:
                    style = self.PLAIN_STYLE
                badges = entry.get("badges")
                if legacy_badges:
                    supplied_badges = (
                        tuple(badges) if isinstance(badges, (list, tuple)) else ()
                    )
                    badges = (*supplied_badges, *legacy_badges)
            else:
                name = str(entry or "").strip()
                style = self.PLAIN_STYLE
                badges = ()
            if name:
                people.append((name, style, self._supporter_badges(badges)))

        _clear_layout(self._names_grid)
        self._legend.setVisible(bool(people))
        self._names_host.setVisible(bool(people))
        self._rule.setVisible(bool(people))
        self._card.setFixedWidth(self.WIDE_WIDTH if people else self.NARROW_WIDTH)

        if not people:
            self._title.setText("Support BonkScanner")
            self._note.setText(self.DEFAULT_NOTE)
            self._reanchor()
            return

        count = len(people)
        self._title.setText(
            "1 person supports BonkScanner"
            if count == 1
            else f"{count} people support BonkScanner"
        )
        # Grouped by source, and inside a group the order they arrived in. Not
        # alphabetical: a list someone maintains by hand has an order, and
        # re-sorting it throws away whatever they meant by it. `sort` is stable,
        # so the file's order survives within each group.
        people.sort(key=lambda person: person[1][1])
        listed = people[: self.MAX_LISTED]
        hidden = len(people) - len(listed)
        self._note.setText(
            "Thank you." if not hidden else f"Thank you, and {hidden} more."
        )

        rows = (len(listed) + 1) // 2
        for index, (name, (object_name, _rank), badges) in enumerate(
            listed
        ):
            row = _SupporterNameRow(
                name,
                object_name,
                badges,
                self._names_host,
            )
            # Elided rather than wrapped, and the grid column carries the width:
            # a display name is whatever its owner typed, and one long one must
            # not be allowed to widen the popup or reflow the column beside it.
            self._names_grid.addWidget(row, index % rows, index // rows)
        self._names_grid.setColumnStretch(0, 1)
        self._names_grid.setColumnStretch(1, 1)
        self._reanchor()

    def _reanchor(self) -> None:
        """Re-place the card if it is on screen and just changed size.

        The list arrives about a second after launch, so a click in that window
        lands on the narrow card and widens it while it is open. Every early
        return here is a case where there is nothing to correct: not visible, or
        never opened against anything.

        **Placed twice, and the second time is the one that gets the height
        right.** Rows added to the grid are not measurable yet at this point:
        the labels they replaced are only unparented on the next pass through
        the event loop, and the new ones have not been polished, so `sizeHint`
        still answers for the previous contents -- measured, 8 names reported
        the height of 2. Placing from that puts the bottom edge of the card
        below the button it is supposed to sit above. The immediate placement
        keeps the width honest without waiting a frame; `_settle` fixes the
        height once there is something true to measure.
        """
        if self.isVisible() and self._anchor is not None:
            try:
                self._place_above(self._anchor)
            except RuntimeError:
                self._anchor = None
                return
            QTimer.singleShot(0, self, self._settle)

    def _settle(self) -> None:
        """Second half of `_reanchor`, once the layout has caught up."""
        if self.isVisible() and self._anchor is not None:
            try:
                self._place_above(self._anchor)
            except RuntimeError:
                # The footer can disappear while this zero-delay placement is
                # queued. Do not retain or dereference its deleted anchor.
                self._anchor = None

    @staticmethod
    def _open_browser_page(url: str) -> bool:
        try:
            return bool(webbrowser.open(url))
        except Exception:
            return False

    def _open_patreon(self) -> None:
        if self._open_url(config.PATREON_SUPPORT_URL):
            self.close()

    def _open_crypto(self) -> None:
        if not config.CRYPTO_SUPPORT_URL:
            return
        if self._open_url(config.CRYPTO_SUPPORT_URL):
            self.close()

    def show_above(self, anchor: QWidget) -> None:
        """Open with the popup's bottom-right corner over `anchor`'s top-right."""
        self._anchor = anchor
        self._place_above(anchor)
        self.show()
        # The same one-pass lag applies to a popup built and filled in the click
        # that opens it: nothing has been polished yet. Idempotent when the
        # first placement was already right.
        QTimer.singleShot(0, self, self._settle)

    def _place_above(self, anchor: QWidget) -> None:
        """Put the bottom-right corner of the card over `anchor`'s top-right.

        **Re-run whenever the card changes size, not only when it opens.** The
        popup is anchored by a corner that moves when it grows: `move` fixes the
        top-left, so a card that goes from 268 to 400 wide grows *rightwards*,
        straight off the display. That is what the first open looked like -- not
        a mis-measurement, but a click that landed in the second or so between
        the window appearing and the supporters arriving. The card opened narrow
        and was widened underneath itself while it sat there.

        The clamp is the backstop for everything this arithmetic cannot know:
        the anchor lives at the right edge of the window and the window is
        usually at the right edge of the screen, so there is nothing to spare. A
        card nudged a few pixels out of line with its button is much better than
        one rendered half off the edge.
        """
        self.ensurePolished()
        # Invalidated innermost first, and this is not belt-and-braces. A layout
        # caches the size hint it computed for its parent, so activating only
        # the outer one answers from the *previous* contents: adding rows to the
        # grid re-placed the card at its height from one call ago, which put its
        # bottom edge below the button it is supposed to sit above. The width
        # never showed it -- the card's width is set outright.
        self._names_grid.invalidate()
        self._card.layout().invalidate()
        self.layout().invalidate()
        self.layout().activate()
        self.adjustSize()
        size = self.sizeHint()

        top_right = anchor.mapToGlobal(QPoint(anchor.width(), 0))
        x = top_right.x() - size.width()
        y = top_right.y() - size.height() - 8

        screen = self.screen() or anchor.screen()
        if screen is not None:
            available = screen.availableGeometry()
            x = min(max(x, available.left()), available.right() - size.width() + 1)
            y = min(max(y, available.top()), available.bottom() - size.height() + 1)

        self.setGeometry(x, y, size.width(), size.height())


class FooterView:
    """The strip, and the one thing anything outside here can tell it."""

    def __init__(
        self,
        *,
        app,
        frame: QFrame,
        update_btn: QPushButton,
        update_separator: QFrame,
        support_btn: QPushButton,
    ) -> None:
        self._app = app
        self.frame = frame
        self._update_btn = update_btn
        # Hidden and shown with the control it divides. A separator is a claim
        # that there is something on both sides of it; left standing over an
        # empty slot it is a stray tick in the corner.
        self._update_separator = update_separator
        self._support_btn = support_btn
        self._popup: SupportPopup | None = None
        self._supporters: tuple = ()
        self._reminder: _SupportReminder | None = None

    def _initialize_support_reminder(self) -> None:
        """Build the overlay once the footer has been parented by the root layout."""
        if self._reminder is not None:
            return
        parent = self.frame.parentWidget()
        if parent is None:
            return
        last_shown_at = _read_support_reminder_state()
        self._save_support_reminder_state(last_shown_at)
        self._reminder = _SupportReminder(
            parent=parent,
            footer_frame=self.frame,
            support_link=self._support_btn,
            activate=self.open_support_popup,
            can_show=self._support_reminder_can_show,
            last_shown_at=last_shown_at,
            record_show=self._record_support_reminder_shown,
        )
        self._reminder.start()

    def _save_support_reminder_state(
        self,
        last_shown_at: float,
    ) -> bool:
        try:
            result = _update_support_reminder_state(last_shown_at=last_shown_at)
        except Exception as exc:
            self._log_warning(
                "Support reminder state could not be saved: "
                f"{type(exc).__name__}: {exc}"
            )
            return False
        if not result.success:
            reason = result.reason or "the configuration file was not writable"
            self._log_warning(f"Support reminder state could not be saved: {reason}")
            return False
        return True

    def _record_support_reminder_shown(self, shown_at: float) -> None:
        self._save_support_reminder_state(shown_at)

    def _support_reminder_can_show(self) -> bool:
        popup = self._popup
        if popup is None:
            return True
        try:
            return not popup.isVisible()
        except RuntimeError:
            self._popup = None
            return True

    def set_update_status(self, state: str, version: str = "") -> None:
        """Say what the update check found, and stay pressable.

        A control rather than a caption, because "Up to date" as dead text is
        the least useful thing this slot could hold: it is a fact from whenever
        the app last launched, with no way to ask again. Re-checking lived only
        behind the settings dialog's *Check for Updates* button, which is two
        clicks and a modal away from the line that reports the answer.

        `"unavailable"` hides the slot outright. It is what a source run gets --
        `check_for_update` returns before it reaches the network there -- and a
        button that cannot do anything is worse than no button. `"unknown"`,
        by contrast, is a real invitation: nothing has been checked *yet*.
        """
        captions = {
            "checking": "Checking…",
            "current": "Up to date",
            "available": f"v{version} available  →",
            "downloading": "Downloading update…",
            "installing": "Restarting…",
            "unknown": "Check for updates",
        }
        visible = state != "unavailable"
        self._update_btn.setVisible(visible)
        self._update_separator.setVisible(visible)
        if not visible:
            return
        self._update_btn.setText(captions.get(state, captions["unknown"]))
        # The full update session is single-flight. Current/available/unknown
        # remain pressable; checking, downloading and installing cannot start a
        # second request beneath the active dialog.
        self._update_btn.setEnabled(
            state not in {"checking", "downloading", "installing"}
        )
        self._update_btn.setProperty("state", state)
        # A property a stylesheet selects on does not repaint on its own.
        self._update_btn.style().unpolish(self._update_btn)
        self._update_btn.style().polish(self._update_btn)

    def check_for_updates(self) -> None:
        # `force_check=True`, unlike the launch check: this one was asked for,
        # so a version the user once skipped should still be reported back.
        # The session owner sets the busy state only after it wins the
        # single-flight claim; a duplicate click cannot strand this button.
        start_update_check(self._app, force_check=True)

    def set_supporters(self, supporters=()) -> None:
        """Hand the strip a list of supporters, or take it away again.

        Called from `ui.dialogs.update_prompt.start_supporters_load`, on the GUI
        thread, after each successful background refresh and only when there is
        something to show --
        `app.supporters.load_supporters` stays silent on every failure and on
        the empty list, so this is not the path that decides what an absent list
        looks like. `SupportPopup.set_supporters` is.

        Deliberately the whole surface: one call sets the caption and the card
        together, so the two cannot disagree, and passing nothing puts the strip
        back exactly as it ships.
        """
        self._supporters = tuple(supporters or ())
        count = len(self._supporters)
        self._support_btn.setText(
            "♥  Support" if not count else f"♥  {count} supporters"
        )
        if self._popup is not None:
            try:
                self._popup.set_supporters(self._supporters)
            except Exception:
                self._popup = None

    def open_support_popup(self) -> None:
        # Built on the first click, not at launch: it is a dozen widgets nobody
        # has asked for yet, and the same discipline `LazyPage` applies to the
        # tabs. Kept afterwards, so clicking twice does not leak a second one.
        try:
            if self._reminder is not None:
                self._reminder.dismiss()
            if self._popup is None:
                self._popup = SupportPopup(
                    self.frame.window(),
                    open_url=self.open_external_page,
                )
                popup = self._popup
                popup.destroyed.connect(
                    lambda *_args, expected=popup: self._popup_destroyed(expected)
                )
                # Built late, so it has to be told what the view already knows.
                self._popup.set_supporters(self._supporters)
            self._popup.show_above(self._support_btn)
        except Exception as exc:
            # A stale wrapper can survive until DeferredDelete is processed.
            popup = self._popup
            self._popup = None
            if popup is not None:
                try:
                    popup.deleteLater()
                except RuntimeError:
                    pass
            self._log_warning(
                f"Support popup could not be opened: {type(exc).__name__}: {exc}"
            )

    def _popup_destroyed(self, expected=None) -> None:
        if expected is None or self._popup is expected:
            self._popup = None

    def open_external_page(self, url: str) -> bool:
        try:
            opened = bool(webbrowser.open(url))
        except Exception as exc:
            opened = False
            reason = f"{type(exc).__name__}: {exc}"
        else:
            reason = "Windows did not accept the browser request."
        if not opened:
            self._log_warning(f"Could not open browser link: {reason}")
        return opened

    def _log_warning(self, message: str) -> None:
        log = getattr(self._app, "log", None)
        if callable(log):
            try:
                log(f"[!] {message}", tag="warning")
            except Exception:
                pass


def build_footer(app) -> QFrame:
    """The strip itself. Returns the frame; the view lands on `app.footer`."""
    frame = QFrame()
    frame.setObjectName("appFooter")
    frame.setFixedHeight(FOOTER_HEIGHT)

    row = QHBoxLayout(frame)
    row.setContentsMargins(15, 0, 15, 0)
    row.setSpacing(10)

    # The version, and not the name beside it. "BonkScanner" is already on the
    # title bar and again in the header two lines up; a third copy down here
    # said nothing the other two had not, and pushed the one new fact -- which
    # build this is -- into second place on its own line.
    number = QLabel(f"v{CURRENT_VERSION}")
    number.setObjectName("footerVersionNumber")
    row.addWidget(number, 0, Qt.AlignVCenter)

    update_separator = _separator()
    row.addWidget(update_separator, 0, Qt.AlignVCenter)

    update_btn = _link("Check for updates", "footerUpdate")
    update_btn.setProperty("state", "unknown")
    row.addWidget(update_btn, 0, Qt.AlignVCenter)

    row.addStretch(1)

    github_btn = _link("GitHub", link_role="github")
    row.addWidget(github_btn, 0, Qt.AlignVCenter)
    row.addWidget(_separator(), 0, Qt.AlignVCenter)

    discord_btn = _link("Discord", link_role="discord")
    row.addWidget(discord_btn, 0, Qt.AlignVCenter)
    row.addWidget(_separator(), 0, Qt.AlignVCenter)

    # GitHub and Discord open the browser on the click; only Support opens the
    # chooser. Two destinations behind one word is the whole reason it differs.
    support_btn = _link("♥  Support", "footerSupportLink")
    row.addWidget(support_btn, 0, Qt.AlignVCenter)

    app.footer = FooterView(
        app=app,
        frame=frame,
        update_btn=update_btn,
        update_separator=update_separator,
        support_btn=support_btn,
    )
    github_btn.clicked.connect(
        lambda: app.footer.open_external_page(config.GITHUB_REPOSITORY_URL)
    )
    discord_btn.clicked.connect(
        lambda: app.footer.open_external_page(config.DISCORD_SUPPORT_URL)
    )
    support_btn.clicked.connect(app.footer.open_support_popup)
    update_btn.clicked.connect(app.footer.check_for_updates)
    QTimer.singleShot(0, frame, app.footer._initialize_support_reminder)
    return frame
