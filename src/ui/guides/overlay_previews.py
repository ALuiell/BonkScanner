"""Miniatures captured from the real native and browser overlay widgets."""
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from core.map_markers import MapMarkerSnapshot, MapViewport, WorldMapMarker
from core.stage_rules import stage_duration_seconds
from core.stats.types import PLAYER_STAT_GROUPS, PlayerStatValue
from projections.in_game_html import build_powerups_overlay_html, build_stats_overlay_html
from ui.shared import resource_path
from ui import i18n as l10n
from ui.localization import localization

from .guide_locale import bind, message, ui

_ASSETS = Path(resource_path("media/guides"))
_MAP_SCENE = _ASSETS / "map-scene.jpg"
_BACKGROUND = "#101925"
_PROBABILITIES = {"LEGENDARY": 4, "RARE": 16, "UNCOMMON": 30, "COMMON": 50}


@dataclass(frozen=True)
class OverlayPreviewWidgets:
    """Factories for the real overlay widgets rendered in guide examples."""
    draggable: Callable
    luck_rarity: Callable
    map_markers: Callable


def _caption(text, role):
    label = bind(QLabel(), text)
    label.setObjectName(role)
    label.setWordWrap(True)
    return label


def _canvas(owner: QWidget) -> QFrame:
    canvas = QFrame(owner)
    canvas.setObjectName("WidgetCapture")
    canvas.setAttribute(Qt.WA_StyledBackground)
    canvas.setStyleSheet(f"QFrame#WidgetCapture {{background:{_BACKGROUND}; border:none;}}")
    canvas.hide()
    return canvas


def _grab(canvas: QWidget) -> QPixmap:
    shot = canvas.grab()
    canvas.deleteLater()
    return shot


def _native_shot(owner: QWidget, make_widget: Callable[[QWidget], QWidget]) -> QPixmap:
    canvas = _canvas(owner)
    layout = QVBoxLayout(canvas)
    layout.setContentsMargins(10, 8, 10, 8)
    sample = make_widget(canvas)
    layout.addWidget(sample, 0, Qt.AlignLeft)
    sample.show()
    canvas.ensurePolished()
    canvas.resize(layout.sizeHint())
    layout.activate()
    return _grab(canvas)


def _powerups(parent: QWidget, widgets: OverlayPreviewWidgets) -> QWidget:
    widget = widgets.draggable("powerups", parent)
    widget.set_edit_mode(False)
    widget.update_scale(1.0)
    snapshot = SimpleNamespace(
        powerup_multiplier_display="1.8",
        active=(
            SimpleNamespace(name="Rage", remaining_seconds=18),
            SimpleNamespace(name="Shield", remaining_seconds=9),
            SimpleNamespace(name="Clock", remaining_seconds=4),
        ),
    )
    widget.set_text(build_powerups_overlay_html(snapshot, translator=localization().translator))
    return widget


def _stats(parent: QWidget, widgets: OverlayPreviewWidgets) -> QWidget:
    widget = widgets.draggable("stats", parent)
    widget.set_edit_mode(False)
    widget.update_scale(1.0)
    values = {"Powerup Multiplier": 2.4, "Powerup Drop Chance": 1.6, "Difficulty": 4.16, "XP Gain": 8.5}
    stats = {
        spec.label: PlayerStatValue(spec, values[spec.label])
        for group in PLAYER_STAT_GROUPS
        for spec in group
        if spec.label in values
    }
    stage = 1
    widget.set_text(build_stats_overlay_html(
        SimpleNamespace(stats=stats),
        list(values),
        stage_index=stage,
        stage_timer_seconds=675,
        stage_time_seconds=stage_duration_seconds(stage, is_graveyard=False),
        is_graveyard=False,
        translator=localization().translator,
    ))
    return widget


def _luck(parent: QWidget, widgets: OverlayPreviewWidgets) -> QWidget:
    widget = widgets.luck_rarity("luck_rarity", parent)
    widget.set_edit_mode(False)
    widget.update_scale(1.0)
    widget.set_probabilities(_PROBABILITIES, show_bar=True)
    widget.set_expected(
        {"LEGENDARY": 2, "RARE": 8, "UNCOMMON": 13, "COMMON": 24},
        {"LEGENDARY": 1.8, "RARE": 7.6, "UNCOMMON": 14.1, "COMMON": 23.5},
        show_expected=True,
    )
    return widget


def _map_shot(owner: QWidget, widgets: OverlayPreviewWidgets) -> QPixmap:
    canvas = _canvas(owner)
    image = QPixmap(str(_MAP_SCENE))
    # Use the center of the Full Map excerpt for the small thumbnail.
    region = image.copy(
        int(image.width() * .12), 0,
        int(image.width() * .76), int(image.height() * .91),
    )
    backdrop = QLabel(canvas)
    backdrop.setPixmap(region.scaled(QSize(368, 160), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
    backdrop.setGeometry(0, 0, 368, 160)
    canvas.resize(backdrop.size())
    layer = widgets.map_markers(canvas)
    layer.setGeometry(canvas.rect())
    layer.set_snapshot(
        MapMarkerSnapshot(
            map_id=1, map_open=True, world_size=600, viewport=MapViewport(0, 0, 368, 160),
            markers=(
                WorldMapMarker("shop", "shady_guy_gold", -145, -70),
                WorldMapMarker("microwave", "microwave_purple", 35, 80, uses_remaining=2),
                WorldMapMarker("magnet", "magnet_shrine", 145, -45),
            ),
        ),
        scale=1.0,
        style="modern",
    )
    backdrop.show()
    layer.raise_()
    return _grab(canvas)


class WidgetThumbnail(QWidget):
    """A static picture of a widget shown in the guide."""

    def __init__(self, name, capture, *, height: int = 99):
        super().__init__()
        self._snapshot = QPixmap()
        self.setObjectName("GuideWidgetShot")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setFixedHeight(height)
        bind(self, name, method="setAccessibleName")

        def refresh():
            self._snapshot = capture(self)
            self.update()

        l10n.RefreshBinding(self, refresh)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._snapshot.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        size = self._snapshot.size().scaled(self.size() - QSize(12, 10), Qt.KeepAspectRatio)
        target = QRectF((self.width() - size.width()) / 2, (self.height() - size.height()) / 2,
                        size.width(), size.height())
        painter.drawPixmap(target, self._snapshot, QRectF(self._snapshot.rect()))
        painter.end()


def _tile(name, note, capture):
    tile = QFrame()
    tile.setObjectName("GuideWidgetTile")
    layout = QVBoxLayout(tile)
    layout.setContentsMargins(9, 8, 9, 8)
    layout.setSpacing(5)
    layout.addWidget(_caption(name, "GuideWidgetName"))
    layout.addWidget(WidgetThumbnail(name, capture))
    layout.addWidget(_caption(lambda: message(note), "GuideWidgetNote"), 1, Qt.AlignTop)
    return tile


def _editor_example() -> QFrame:
    panel = QFrame()
    panel.setObjectName("GuideWidgetTile")
    row = QHBoxLayout(panel)
    row.setContentsMargins(9, 8, 9, 8)
    row.setSpacing(12)
    title = lambda: ui("Overlay Layout Editor")
    editor = WidgetThumbnail(title, lambda _: QPixmap(str(_ASSETS / "obs-editor-strip.png")), height=117)
    row.addWidget(editor, 3)
    details = QVBoxLayout()
    details.setSpacing(5)
    details.addStretch(1)
    details.addWidget(_caption(title, "GuideWidgetName"))
    details.addWidget(_caption(lambda: message("overlay.obs.workflow"), "GuideWidgetNote"))
    details.addStretch(1)
    row.addLayout(details, 2)
    return panel


def build_overlay_previews(topic: str, widgets: OverlayPreviewWidgets) -> QWidget:
    panel = QFrame()
    panel.setObjectName("overlayGuidePreview")
    panel.setStyleSheet("""
        QFrame#overlayGuidePreview {background:#111b29; border:1px solid #2b3c50; border-radius:10px;}
        QFrame#GuideWidgetTile {background:#152131; border:1px solid #2b3c50; border-radius:8px;}
        QLabel#GuideWidgetName {color:#e6eff9; font-size:13px; font-weight:700; background:transparent;}
        QLabel#GuideWidgetNote {color:#adc0d1; font-size:12px; background:transparent;}
        QWidget#GuideWidgetShot {background:#101925; border:1px solid #304358; border-radius:5px;}
    """)
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(11, 9, 11, 10)
    layout.setSpacing(8)
    layout.addWidget(_caption(lambda: message("overlay.example_data"), "GuideWidgetNote"))
    if topic == "obs":
        samples = (
            (lambda: ui("KPS"), "overlay.kps.note", "obs-kps.png"),
            (lambda: ui("Luck"), "overlay.luck_expected.note", "obs-luck.png"),
            (lambda: ui("Stage Summary"), "overlay.stage.note", "obs-stage-summary.png"),
        )
        entries = [(name, note, lambda _owner, file=filename: QPixmap(str(_ASSETS / file)))
                   for name, note, filename in samples]
        columns = 3
    elif topic == "game_overlay":
        entries = (
            (lambda: localization().text("igo.powerups"), "overlay.powerups.note", lambda owner: _native_shot(owner, lambda parent: _powerups(parent, widgets))),
            (lambda: localization().text("igo.stats"), "overlay.stats.note", lambda owner: _native_shot(owner, lambda parent: _stats(parent, widgets))),
            (lambda: message("overlay.luck_expected.title", luck=ui("Luck")), "overlay.luck_expected.note",
             lambda owner: _native_shot(owner, lambda parent: _luck(parent, widgets))),
            (lambda: localization().text("igo.map_activity_markers"), "overlay.map.note", lambda owner: _map_shot(owner, widgets)),
        )
        columns = 2
    else:
        raise ValueError(f"Unknown overlay topic: {topic}")

    grid = QGridLayout()
    grid.setSpacing(8)
    for index, entry in enumerate(entries):
        grid.addWidget(_tile(*entry), index // columns, index % columns)
        grid.setColumnStretch(index % columns, 1)
    layout.addLayout(grid)
    if topic == "obs":
        layout.addWidget(_editor_example())
    else:
        layout.addWidget(_caption(
            lambda: message("overlay.game.layout", scale=localization().text("igo.scale")),
            "GuideWidgetNote",
        ))
    layout.addStretch(1)
    return panel
