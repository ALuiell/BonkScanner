from __future__ import annotations

import ctypes
import datetime
import html
import os
import sys
import threading
import time
import webbrowser
from ctypes import wintypes
from functools import partial
from pathlib import Path


def enable_windows_dpi_awareness() -> None:
    if os.name != "nt":
        return

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass

    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


enable_windows_dpi_awareness()

from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QCloseEvent, QFont, QIcon, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QComboBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSlider,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import config
import logic
import updater
from game_data import GameDataClient
from hook_loader import HookLoadError, HookProcessNotFoundError, HookProcessNotReadyError, NativeHookLoader
from memory import MemoryReadError, ModuleNotFoundError, ProcessNotFoundError
from player_stats import PLAYER_STAT_GROUPS, PlayerStatsClient, WeaponSnapshot, calculate_chests_per_minute
from run_control import HookRunControlProvider, KeyboardRunControlProvider, RunControlError
from runtime_stats import adapt_map_stats
from vod_storage import VodRecorder, delete_vod, delete_vods_below_snapshot_count, list_vods, load_vod, rename_vod

try:
    import win32gui
    import win32process
except ImportError:
    win32gui = None
    win32process = None

try:
    import keyboard
except ImportError:
    keyboard = None


PATREON_SUPPORT_URL = "https://www.patreon.com/posts/bonkscanner-158115804?source=storefront"
KOFI_SUPPORT_URL = "https://ko-fi.com/s/34dc062a82"
PATREON_ICON_PATH = "media/patreon_logo.svg"
KOFI_ICON_PATH = "media/kofi_logo.svg"
PLAYER_STATS_REFRESH_MS = 10_000
PLAYER_STATS_RECORDING_SEED_GRACE_SECONDS = 20
PLAYER_STATS_RUN_TIMER_RESET_TOLERANCE_SECONDS = 3.0
PLAYER_STATS_STAGE_TRANSITION_BOUNDARY_SECONDS = 5.0
PLAYER_STATS_STAGE4_TIMER_JUMP_SECONDS = 300.0
PLAYER_STATS_ACTIVE_BUTTON_COLOR = "#b30000"
PLAYER_STATS_ACTIVE_BUTTON_HOVER_COLOR = "#800000"
PLAYER_STATS_INACTIVE_BUTTON_COLOR = "#1f538d"
PLAYER_STATS_INACTIVE_BUTTON_HOVER_COLOR = "#14375e"
PLAYER_STATS_LABEL_FONT_SIZE = 13
PLAYER_STATS_VALUE_FONT_SIZE = 13
PLAYER_STATS_VALUE_WIDTH = 72
PLAYER_STATS_ITEMS_WRAP_LENGTH = 360
ITEM_SORT_DEFAULT = "default"
ITEM_SORT_RARITY_DESC = "rarity_desc"
ITEM_SORT_RARITY_ASC = "rarity_asc"
ITEM_SORT_LABELS = {
    ITEM_SORT_DEFAULT: "Default",
    ITEM_SORT_RARITY_DESC: "Rarity ↓",
    ITEM_SORT_RARITY_ASC: "Rarity ↑",
}
ITEM_RARITY_SORT_ORDER = {
    "COMMON": 0,
    "UNCOMMON": 1,
    "RARE": 2,
    "LEGENDARY": 3,
}

COLOR_MAP = {
    "WHITE": "#F8FAFC",
    "CYAN": "#22D3EE",
    "GREEN": "#22C55E",
    "YELLOW": "#FACC15",
    "LIGHTRED_EX": "#FB7185",
    "RED": "#EF4444",
    "MAGENTA": "#E879F9",
    "BLUE": "#60A5FA",
    "LIGHTBLUE_EX": "#93C5FD",
    "DEFAULT": "#E5E7EB",
}

ITEM_RARITY_COLOR_MAP = {
    "COMMON": COLOR_MAP["GREEN"],
    "UNCOMMON": COLOR_MAP["BLUE"],
    "RARE": COLOR_MAP["MAGENTA"],
    "LEGENDARY": COLOR_MAP["YELLOW"],
}

ITEM_RARITY_BY_NAME = {
    "Key": "COMMON",
    "Slippery Ring": "COMMON",
    "Gym Sauce": "COMMON",
    "Battery": "COMMON",
    "Forbidden Juice": "COMMON",
    "Moldy Cheese": "COMMON",
    "Golden Glove": "COMMON",
    "Ghost": "COMMON",
    "Turbo Socks": "COMMON",
    "Clover": "COMMON",
    "Skuleg": "COMMON",
    "Oats": "COMMON",
    "Cursed Doll": "COMMON",
    "Borgar": "COMMON",
    "Medkit": "COMMON",
    "Boss Buster": "COMMON",
    "Tactical Glasses": "COMMON",
    "Cactus": "COMMON",
    "Ice Crystal": "COMMON",
    "Time Bracelet": "COMMON",
    "Wrench": "COMMON",
    "Old Mask": "COMMON",
    "Beer": "UNCOMMON",
    "Cowards Cloak": "UNCOMMON",
    "Phantom Shroud": "UNCOMMON",
    "Demon Blade": "UNCOMMON",
    "Golden Sneakers": "UNCOMMON",
    "Demonic Blood": "UNCOMMON",
    "Golden Shield": "UNCOMMON",
    "Feathers": "UNCOMMON",
    "Echo Shard": "UNCOMMON",
    "Backpack": "UNCOMMON",
    "Campfire": "UNCOMMON",
    "Electric Plug": "UNCOMMON",
    "Brass Knuckles": "UNCOMMON",
    "Idle Juice": "UNCOMMON",
    "Unstable Transfusion": "UNCOMMON",
    "Credit Card Red": "UNCOMMON",
    "Leeching Crystal": "UNCOMMON",
    "Glove Lightning": "UNCOMMON",
    "Glove Poison": "UNCOMMON",
    "Beacon": "UNCOMMON",
    "Pumpkin": "UNCOMMON",
    "Spiky Shield": "RARE",
    "Grandmas Secret Tonic": "RARE",
    "Demonic Soul": "RARE",
    "Beefy Ring": "RARE",
    "Slutty Cannon": "RARE",
    "Shattered Wisdom": "RARE",
    "Rollerblades": "RARE",
    "Eagle Claw": "RARE",
    "Scarf": "RARE",
    "Bob Dead": "RARE",
    "Mirror": "RARE",
    "Gasmask": "RARE",
    "Toxic Barrel": "RARE",
    "Kevin": "RARE",
    "Gamer Goggles": "RARE",
    "Credit Card Green": "RARE",
    "Glove Blood": "RARE",
    "Glove Curse": "RARE",
    "Quins Mask": "RARE",
    "Bobs Lantern": "RARE",
    "Bonker": "LEGENDARY",
    "Giant Fork": "LEGENDARY",
    "Spicy Meatball": "LEGENDARY",
    "Chonkplate": "LEGENDARY",
    "Lightning Orb": "LEGENDARY",
    "Ice Cube": "LEGENDARY",
    "Dragonfire": "LEGENDARY",
    "Za Warudo": "LEGENDARY",
    "Overpowered Lamp": "LEGENDARY",
    "Sucky Magnet": "LEGENDARY",
    "Anvil": "LEGENDARY",
    "Energy Core": "LEGENDARY",
    "Soul Harvester": "LEGENDARY",
    "Joes Dagger": "LEGENDARY",
    "Speed Boi": "LEGENDARY",
    "Holy Book": "LEGENDARY",
    "Bloody Cleaver": "LEGENDARY",
    "Glove Power": "LEGENDARY",
    "Golden Ring": "LEGENDARY",
    "Snek": "LEGENDARY",
    "Pot": "LEGENDARY",
    "Wizards Hat": "LEGENDARY",
}

ITEM_RARITY_NAME_ALIASES = {
    "Flappy Feathers": "Feathers",
    "No Implementation": "Golden Ring",
}


ITEM_RARITY_FOLDED_NAME_ALIASES = {
    "boblantern": "bobslantern",
    "borgor": "borgar",
    "flappyfeathers": "feathers",
    "glovecursed": "glovecurse",
    "glovescursed": "glovecurse",
    "noimplementation": "goldenring",
    "potsteel": "pot",
    "suckyhoof": "suckymagnet",
}


ITEM_DISPLAY_NAME_ALIASES = {
    "No Implementation": "Golden Ring",
}


def _fold_item_name_for_rarity(item_name: str) -> str:
    return "".join(char.lower() for char in item_name if char.isalnum())


ITEM_RARITY_NAME_BY_FOLDED_NAME = {
    _fold_item_name_for_rarity(name): name
    for name in ITEM_RARITY_BY_NAME
}


def resource_path(relative_path: str) -> str:
    base_path = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base_path, relative_path)


def _read_text(widget) -> str:
    if widget is None:
        return ""
    if hasattr(widget, "text"):
        text_attr = getattr(widget, "text")
        return text_attr() if callable(text_attr) else str(text_attr)
    if hasattr(widget, "get"):
        return str(widget.get())
    return ""


def _set_text(widget, text: str) -> None:
    if widget is None:
        return
    if hasattr(widget, "setText"):
        widget.setText(text)
        return
    if hasattr(widget, "configure"):
        widget.configure(text=text)
        return


def _set_items_text(widget, items=(), *, items_text: str | None = None) -> None:
    text = items_text if items_text is not None else MegabonkApp.format_items(items)
    if widget is None:
        return
    if hasattr(widget, "setTextFormat"):
        widget.setText(MegabonkApp.format_items_rich_text(items) if items_text is None else text)
        return
    _set_text(widget, text)


def _clear_text_input(widget) -> None:
    if widget is None:
        return
    if hasattr(widget, "clear"):
        widget.clear()
        return
    if hasattr(widget, "delete"):
        widget.delete(0, "end")


def _set_text_input(widget, text: str) -> None:
    if widget is None:
        return
    if hasattr(widget, "setText"):
        widget.setText(text)
        return
    if hasattr(widget, "insert"):
        widget.insert(0, text)


def _read_bool(widget) -> bool:
    if widget is None:
        return False
    if hasattr(widget, "isChecked"):
        return bool(widget.isChecked())
    if hasattr(widget, "get"):
        return bool(widget.get())
    return False


def _set_bool(widget, value: bool) -> None:
    if widget is None:
        return
    if hasattr(widget, "setChecked"):
        widget.setChecked(value)
        return
    if hasattr(widget, "set"):
        widget.set(value)


def _safe_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.deleteLater()
        elif child_layout is not None:
            _clear_layout(child_layout)


def _template_checkbox_stylesheet(color_hex: str) -> str:
    return f"""
    QCheckBox {{
        color: {color_hex};
        background: #121A27;
        border: 1px solid #2B3648;
        border-left: 4px solid {color_hex};
        border-radius: 8px;
        padding: 10px 12px;
        font-weight: 700;
    }}
    QCheckBox:hover {{
        background: #162133;
        border-color: {color_hex};
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
    }}
    """


def _template_color_hex(template: dict) -> str:
    color_tag = template.get("color", "LIGHTBLUE_EX").upper()
    return COLOR_MAP.get(color_tag, COLOR_MAP["DEFAULT"])


def _template_manager_card_stylesheet(color_hex: str, expanded: bool) -> str:
    border_color = color_hex if expanded else "#3A4558"
    background = "#151D2A" if expanded else "#121821"
    return f"""
    QFrame#TemplateManagerCard {{
        background: {background};
        border: 1px solid {border_color};
        border-left: 4px solid {color_hex};
        border-radius: 12px;
    }}
    """


def _template_manager_header_stylesheet(color_hex: str) -> str:
    return f"""
    QPushButton {{
        background: transparent;
        border: none;
        padding: 0;
        color: {color_hex};
        font-size: 15px;
        font-weight: 800;
        text-align: left;
    }}
    QPushButton:hover {{
        background: transparent;
        color: {color_hex};
    }}
    """


def _apply_button_icon(button: QPushButton, relative_path: str, size: int = 22) -> None:
    icon_path = resource_path(relative_path)
    if not os.path.exists(icon_path):
        return
    button.setIcon(QIcon(icon_path))
    button.setIconSize(QSize(size, size))


def _button_state_stylesheet(background: str, hover: str) -> str:
    return f"""
    QPushButton {{
        background: {background};
        color: white;
        border: none;
        border-radius: 8px;
        padding: 8px 14px;
        font-weight: 700;
    }}
    QPushButton:hover {{
        background: {hover};
    }}
    """


def _session_stats_label_stylesheet(accent: bool = False) -> str:
    color = "#F3F4F6" if accent else "#D7DEE8"
    weight = "700" if accent else "600"
    return f"color: {color}; font-size: 17px; font-weight: {weight};"


def _tier_color(tier: str) -> str:
    return {
        "Light": COLOR_MAP["WHITE"],
        "Good": COLOR_MAP["GREEN"],
        "Perfect": COLOR_MAP["YELLOW"],
        "Perfect+": COLOR_MAP["LIGHTRED_EX"],
    }.get(tier, COLOR_MAP["DEFAULT"])


def _make_scroll_section() -> tuple[QScrollArea, QWidget, QVBoxLayout]:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(8)
    scroll.setWidget(content)
    return scroll, content, layout


def format_template_conditions(template: dict) -> str:
    parts = []
    sm_total = template.get("sm_total", 0)
    shady = template.get("shady", 0)
    moai = template.get("moai", 0)
    micro = template.get("micro", 0)
    boss = template.get("boss", 0)

    if sm_total > 0:
        parts.append(f"S+M: {sm_total}")
    if shady > 0:
        parts.append(f"S:{shady}")
    if moai > 0:
        parts.append(f"M:{moai}")
    if micro > 0:
        parts.append(f"Mic:{micro}")
    if boss > 0:
        parts.append(f"B:{boss}")

    return ", ".join(parts) if parts else "Any"


def build_template_payload(
    name: str,
    sm_total: str,
    shady: str,
    moai: str,
    micro: str,
    boss: str,
    source_template=None,
):
    name = name.strip()
    if not name:
        return None

    def parse_int(value: str) -> int:
        value = value.strip()
        return int(value) if value.isdigit() else 0

    result = {
        "name": name,
        "sm_total": parse_int(sm_total),
        "shady": parse_int(shady),
        "moai": parse_int(moai),
        "micro": parse_int(micro),
        "boss": parse_int(boss),
    }

    if result["sm_total"] <= 0 or result["shady"] > 0 or result["moai"] > 0:
        result.pop("sm_total", None)

    if source_template:
        for key, value in source_template.items():
            if key not in result and key not in ["sm_total", "shady", "moai", "micro", "boss"]:
                result[key] = value

    return result


class UiInvoker(QObject):
    call_now = Signal(object)
    call_later = Signal(int, object)

    def __init__(self) -> None:
        super().__init__()
        self.call_now.connect(self._execute_now)
        self.call_later.connect(self._execute_later)

    @Slot(object)
    def _execute_now(self, callback) -> None:
        callback()

    @Slot(int, object)
    def _execute_later(self, delay_ms: int, callback) -> None:
        QTimer.singleShot(max(0, int(delay_ms)), callback)


class _AppWindow(QMainWindow):
    def __init__(self, owner) -> None:
        super().__init__()
        self.owner = owner

    def closeEvent(self, event: QCloseEvent) -> None:
        self.owner._handle_window_close(event)


class TemplateFormFrame(QWidget):
    def __init__(self, parent=None, template_data=None):
        super().__init__(parent)
        self.template_data = template_data or {}
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.name_entry = QLineEdit()
        layout.addRow("Template Name:", self.name_entry)

        self.sm_entry = QLineEdit()
        self.shady_entry = QLineEdit()
        self.moai_entry = QLineEdit()
        self.micro_entry = QLineEdit()
        self.boss_entry = QLineEdit()

        layout.addRow("S+M Total (optional):", self.sm_entry)
        layout.addRow("Shady Guy (min):", self.shady_entry)
        layout.addRow("Moais (min):", self.moai_entry)
        layout.addRow("Microwaves (min):", self.micro_entry)
        layout.addRow("Boss Curses (min):", self.boss_entry)

        self.shady_entry.textChanged.connect(self.update_sm_total)
        self.moai_entry.textChanged.connect(self.update_sm_total)
        self.load_template(self.template_data)

    def load_template(self, template_data=None):
        self.template_data = template_data or {}
        self.name_entry.setText(self.template_data.get("name", ""))
        self.name_entry.setEnabled(self.template_data.get("id", 100) > 7)
        self.sm_entry.setText(str(self.template_data.get("sm_total", 0)))
        self.shady_entry.setText(str(self.template_data.get("shady", 0)))
        self.moai_entry.setText(str(self.template_data.get("moai", 0)))
        self.micro_entry.setText(str(self.template_data.get("micro", 0)))
        self.boss_entry.setText(str(self.template_data.get("boss", 0)))
        self.update_sm_total()

    def update_sm_total(self) -> None:
        shady = self.shady_entry.text().strip()
        moai = self.moai_entry.text().strip()
        if shady.isdigit() and moai.isdigit() and (int(shady) > 0 or int(moai) > 0):
            self.sm_entry.setPlaceholderText("Disabled while individual S/M values are set")
        else:
            self.sm_entry.setPlaceholderText("")

    def get_payload(self):
        return build_template_payload(
            self.name_entry.text(),
            self.sm_entry.text(),
            self.shady_entry.text(),
            self.moai_entry.text(),
            self.micro_entry.text(),
            self.boss_entry.text(),
            source_template=self.template_data,
        )


class TemplateDialog(QDialog):
    def __init__(self, parent=None, edit_template=None):
        super().__init__(parent)
        self.result_payload = None
        self.setWindowTitle("Edit Template" if edit_template else "Add Template")
        self.setModal(True)
        self.resize(420, 260)
        self.form = TemplateFormFrame(self, edit_template)
        layout = QVBoxLayout(self)
        layout.addWidget(self.form)
        self.save_btn = QPushButton("Save Template")
        self.save_btn.clicked.connect(self.save)
        layout.addWidget(self.save_btn)

    def save(self):
        payload = self.form.get_payload()
        if payload is None:
            QMessageBox.warning(self, "Invalid Template", "Template name cannot be empty.")
            return
        self.result_payload = payload
        self.accept()


class TemplateManagerDialog(QDialog):
    def __init__(self, parent, templates, on_save):
        super().__init__(parent)
        self.templates = [dict(template) for template in templates]
        self.on_save = on_save
        self.setWindowTitle("Manage Templates")
        self.resize(760, 760)
        self.setMinimumSize(640, 560)
        self.expanded_template_id: int | None = None
        self.card_widgets: dict[int, dict[str, object]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        header = QLabel("Templates")
        header.setObjectName("SectionHeader")
        layout.addWidget(header)

        subtitle = QLabel("Select a template from the list, and its settings will appear directly below the card.")
        subtitle.setStyleSheet("color: #AAB4C4;")
        layout.addWidget(subtitle)

        self.scroll, self.scroll_content, self.scroll_layout = _make_scroll_section()
        layout.addWidget(self.scroll, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        self.build_cards()

    def build_cards(self):
        _clear_layout(self.scroll_layout)
        self.card_widgets.clear()
        for template in self.templates:
            template_id = int(template.get("id", 0))
            color_hex = _template_color_hex(template)
            card = QFrame()
            card.setObjectName("TemplateManagerCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 14, 16, 14)
            card_layout.setSpacing(10)

            header_btn = QPushButton(f"▶ {template['name']}")
            header_btn.setCursor(Qt.PointingHandCursor)
            header_btn.setStyleSheet(_template_manager_header_stylesheet(color_hex))
            header_btn.clicked.connect(partial(self.toggle_template, template_id))
            card_layout.addWidget(header_btn)

            meta_text = format_template_conditions(template)
            if template.get("id", 100) <= 7:
                meta_text += "  •  Built-in"
            meta_label = QLabel(meta_text)
            meta_label.setStyleSheet("color: #C5CEDB;")
            card_layout.addWidget(meta_label)

            details = QFrame()
            details_layout = QVBoxLayout(details)
            details_layout.setContentsMargins(0, 8, 0, 0)
            details_layout.setSpacing(12)
            form = TemplateFormFrame(details, template)
            details_layout.addWidget(form)

            save_row = QHBoxLayout()
            save_row.addStretch(1)
            save_btn = QPushButton("Save")
            save_btn.setObjectName("SuccessButton")
            save_btn.clicked.connect(partial(self.save_template, template_id, form))
            save_row.addWidget(save_btn)
            details_layout.addLayout(save_row)
            details.setVisible(False)
            card_layout.addWidget(details)

            self.card_widgets[template_id] = {
                "card": card,
                "header_btn": header_btn,
                "details": details,
                "template": template,
                "form": form,
                "color_hex": color_hex,
            }
            self._apply_card_state(template_id, expanded=template_id == self.expanded_template_id)
            self.scroll_layout.addWidget(card)
        self.scroll_layout.addStretch(1)

    def _apply_card_state(self, template_id: int, *, expanded: bool) -> None:
        widgets = self.card_widgets.get(template_id)
        if widgets is None:
            return

        template = widgets["template"]
        header_btn = widgets["header_btn"]
        details = widgets["details"]
        color_hex = str(widgets["color_hex"])
        header_btn.setText(f"{'▼' if expanded else '▶'} {template['name']}")
        details.setVisible(expanded)
        widgets["card"].setStyleSheet(_template_manager_card_stylesheet(color_hex, expanded))

    def toggle_template(self, template_id: int) -> None:
        if self.expanded_template_id == template_id:
            self._apply_card_state(template_id, expanded=False)
            self.expanded_template_id = None
            return

        if self.expanded_template_id is not None:
            self._apply_card_state(self.expanded_template_id, expanded=False)

        self.expanded_template_id = template_id
        self._apply_card_state(template_id, expanded=True)

    def save_template(self, template_id: int, form: TemplateFormFrame):
        payload = form.get_payload()
        if payload is None:
            QMessageBox.warning(self, "Invalid Template", "Template name cannot be empty.")
            return

        template = next((item for item in self.templates if int(item.get("id", 0)) == template_id), None)
        if template is None:
            return

        payload["id"] = template.get("id")
        original_name = template.get("name")
        if callable(self.on_save) and not self.on_save(template, payload):
            return

        for index, existing in enumerate(self.templates):
            if int(existing.get("id", 0)) == template_id:
                self.templates[index] = payload
                break

        self.expanded_template_id = None
        self.build_cards()


class ScoresSettingsDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Scores Settings")
        self.resize(460, 560)
        self.setModal(True)
        self.active_tier_checks: dict[str, QCheckBox] = {}
        self.threshold_entries: dict[str, QLineEdit] = {}
        self.weight_entries: dict[str, QLineEdit] = {}
        self.multiplier_entries: dict[str, QLineEdit] = {}

        outer = QVBoxLayout(self)
        scroll, scroll_content, scroll_layout = _make_scroll_section()
        outer.addWidget(scroll, 1)

        active_group = QGroupBox("Active Tiers")
        active_layout = QVBoxLayout(active_group)
        for tier in ("Light", "Good", "Perfect", "Perfect+"):
            cb = QCheckBox(tier)
            cb.setChecked(tier in config.SCORES_SYSTEM.get("active_tiers", []))
            cb.setStyleSheet(f"color: {_tier_color(tier)}; font-weight: 700;")
            self.active_tier_checks[tier] = cb
            active_layout.addWidget(cb)
        scroll_layout.addWidget(active_group)

        threshold_group = QGroupBox("Thresholds")
        threshold_layout = QGridLayout(threshold_group)
        self.manual_thresholds_var = QCheckBox("Manual Thresholds")
        self.manual_thresholds_var.setChecked(bool(config.SCORES_SYSTEM.get("manual_thresholds", False)))
        self.manual_thresholds_var.toggled.connect(self.toggle_thresholds_mode)
        threshold_layout.addWidget(self.manual_thresholds_var, 0, 0, 1, 2)
        for row, tier in enumerate(("Light", "Good", "Perfect", "Perfect+"), start=1):
            threshold_layout.addWidget(QLabel(f"{tier}:"), row, 0)
            entry = QLineEdit(str(config.SCORES_SYSTEM.get("thresholds", {}).get(tier, 0)))
            self.threshold_entries[tier] = entry
            threshold_layout.addWidget(entry, row, 1)
        scroll_layout.addWidget(threshold_group)

        weight_group = QGroupBox("Weights")
        weight_layout = QFormLayout(weight_group)
        for key in ("moais", "shady", "boss", "magnet"):
            entry = QLineEdit(str(config.SCORES_SYSTEM.get("weights", {}).get(key, 0)))
            self.weight_entries[key] = entry
            weight_layout.addRow(f"{key.capitalize()}:", entry)
        scroll_layout.addWidget(weight_group)

        multiplier_group = QGroupBox("Microwave Multipliers")
        multiplier_layout = QFormLayout(multiplier_group)
        for key in ("1", "2"):
            entry = QLineEdit(str(config.SCORES_SYSTEM.get("multipliers", {}).get("microwave", {}).get(key, 1.0)))
            self.multiplier_entries[key] = entry
            multiplier_layout.addRow(f"{key} Microwave(s):", entry)
        scroll_layout.addWidget(multiplier_group)

        button_row = QHBoxLayout()
        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.setObjectName("DangerButton")
        reset_btn.clicked.connect(self.reset_to_defaults)
        save_btn = QPushButton("Save Settings")
        save_btn.setObjectName("SuccessButton")
        save_btn.clicked.connect(self.save)
        button_row.addWidget(reset_btn)
        button_row.addStretch(1)
        button_row.addWidget(save_btn)
        scroll_layout.addLayout(button_row)
        scroll_layout.addStretch(1)
        self.toggle_thresholds_mode()

    def reset_to_defaults(self):
        defaults = config.DEFAULT_SCORES_SYSTEM
        self.manual_thresholds_var.setChecked(bool(defaults.get("manual_thresholds", False)))
        for tier, cb in self.active_tier_checks.items():
            cb.setChecked(tier in defaults.get("active_tiers", []))
        for tier, entry in self.threshold_entries.items():
            entry.setText(str(defaults.get("thresholds", {}).get(tier, 0.0)))
        for key, entry in self.weight_entries.items():
            entry.setText(str(defaults.get("weights", {}).get(key, 0.0)))
        for key, entry in self.multiplier_entries.items():
            entry.setText(str(defaults.get("multipliers", {}).get("microwave", {}).get(key, 1.0)))
        self.toggle_thresholds_mode()

    def auto_update_thresholds(self):
        thresholds = config.calculate_auto_thresholds(
            {key: _safe_float(entry.text(), 0.0) for key, entry in self.weight_entries.items()},
            {"microwave": {key: _safe_float(entry.text(), 1.0) for key, entry in self.multiplier_entries.items()}},
        )
        for tier, entry in self.threshold_entries.items():
            entry.setText(str(thresholds.get(tier, 0.0)))

    def toggle_thresholds_mode(self):
        manual = self.manual_thresholds_var.isChecked()
        if not manual:
            self.auto_update_thresholds()
        for entry in self.threshold_entries.values():
            entry.setEnabled(manual)

    def save(self):
        active_tiers = [tier for tier, cb in self.active_tier_checks.items() if cb.isChecked()]
        if not active_tiers:
            QMessageBox.warning(self, "Invalid Settings", "At least one score tier must stay active.")
            return

        scores_system = {
            "manual_thresholds": self.manual_thresholds_var.isChecked(),
            "base_target_score": config.SCORES_SYSTEM.get("base_target_score", 30.0),
            "weights": {key: _safe_float(entry.text(), 0.0) for key, entry in self.weight_entries.items()},
            "multipliers": {
                "microwave": {key: _safe_float(entry.text(), 1.0) for key, entry in self.multiplier_entries.items()},
            },
            "thresholds": {tier: _safe_float(entry.text(), 0.0) for tier, entry in self.threshold_entries.items()},
            "active_tiers": active_tiers,
        }

        if not scores_system["manual_thresholds"]:
            scores_system["thresholds"] = config.calculate_auto_thresholds(
                scores_system["weights"],
                scores_system["multipliers"],
            )

        config.SCORES_SYSTEM = scores_system
        config.user_config["SCORES_SYSTEM"] = scores_system
        config.save_config(config.user_config)
        self.accept()


class DeleteDialog(QDialog):
    def __init__(self, parent, custom_templates):
        super().__init__(parent)
        self.custom_templates = custom_templates
        self.checks: dict[int, QCheckBox] = {}
        self.setWindowTitle("Delete Templates")
        self.resize(320, 280)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select templates to delete:"))
        scroll, _content, scroll_layout = _make_scroll_section()
        layout.addWidget(scroll, 1)
        for template in custom_templates:
            cb = QCheckBox(template["name"])
            self.checks[template["id"]] = cb
            scroll_layout.addWidget(cb)
        scroll_layout.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        delete_btn = QPushButton("Delete Selected")
        delete_btn.setObjectName("DangerButton")
        buttons.addButton(delete_btn, QDialogButtonBox.AcceptRole)
        buttons.rejected.connect(self.reject)
        delete_btn.clicked.connect(self.delete)
        layout.addWidget(buttons)

    def delete(self):
        to_delete = {template_id for template_id, cb in self.checks.items() if cb.isChecked()}
        if not to_delete:
            self.reject()
            return
        config.TEMPLATES = [t for t in config.TEMPLATES if t.get("id") not in to_delete]
        config.user_config["TEMPLATES"] = config.TEMPLATES
        config.ACTIVE_TEMPLATES = [
            name for name in config.ACTIVE_TEMPLATES
            if name in {template["name"] for template in config.TEMPLATES}
        ]
        config.user_config["ACTIVE_TEMPLATES"] = config.ACTIVE_TEMPLATES
        config.save_config(config.user_config)
        self.accept()


class ConfirmDeleteRecordingDialog(QDialog):
    def __init__(self, parent, recording_name: str):
        super().__init__(parent)
        self.result = False
        self.setWindowTitle("Delete Recording")
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Delete recording '{recording_name}'?"))
        buttons = QDialogButtonBox()
        cancel_btn = buttons.addButton("Cancel", QDialogButtonBox.RejectRole)
        confirm_btn = buttons.addButton("Delete", QDialogButtonBox.AcceptRole)
        confirm_btn.setObjectName("DangerButton")
        cancel_btn.clicked.connect(self.cancel)
        confirm_btn.clicked.connect(self.confirm)
        layout.addWidget(buttons)

    def confirm(self):
        self.result = True
        self.accept()

    def cancel(self):
        self.result = False
        self.reject()


class CleanupRecordingsDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.threshold: int | None = None
        self.setWindowTitle("Clean Recordings")
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Remove all recordings where snapshot count is less than:"))
        self.threshold_entry = QLineEdit("2")
        layout.addWidget(self.threshold_entry)
        buttons = QDialogButtonBox()
        cancel_btn = buttons.addButton("Cancel", QDialogButtonBox.RejectRole)
        confirm_btn = buttons.addButton("Remove", QDialogButtonBox.AcceptRole)
        confirm_btn.setObjectName("DangerButton")
        cancel_btn.clicked.connect(self.reject)
        confirm_btn.clicked.connect(self.confirm)
        layout.addWidget(buttons)

    def confirm(self):
        try:
            threshold = int(float(_read_text(self.threshold_entry)))
        except ValueError:
            QMessageBox.warning(self, "Invalid Count", "Please enter a valid snapshot count.")
            return
        if threshold < 0:
            QMessageBox.warning(self, "Invalid Count", "Snapshot count cannot be negative.")
            return
        self.threshold = threshold
        self.accept()


class NativeHookWarningDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.result = False
        self.setWindowTitle("Native Hook Warning")
        self.setModal(True)
        self.resize(525, 355)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 20, 18, 18)
        layout.setSpacing(16)

        card = QFrame()
        card.setObjectName("WarningCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 14)
        card_layout.setSpacing(8)

        title = QLabel("Enable Native Hook Restart?")
        title.setObjectName("WarningTitle")
        card_layout.addWidget(title)

        summary = QLabel(
            "This enables a lower-level memory restart path. Using this mode\n"
            "may not be considered entirely fair and could have consequences."
        )
        summary.setWordWrap(True)
        summary.setStyleSheet("background: transparent; font-size: 15px;")
        card_layout.addWidget(summary)
        layout.addWidget(card)

        switch_note = QLabel(
            "You can safely switch back to standard keyboard restart at any time\n"
            "from Settings."
        )
        switch_note.setWordWrap(True)
        switch_note.setStyleSheet("font-size: 15px;")
        layout.addWidget(switch_note)

        repeat_note = QLabel("This dialog will appear whenever the native hook option is turned on.")
        repeat_note.setWordWrap(True)
        repeat_note.setStyleSheet("font-size: 15px;")
        layout.addWidget(repeat_note)
        layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(20)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("DangerButton")
        cancel_btn.setProperty("class", "WideDialogButton")
        cancel_btn.setMinimumHeight(34)
        continue_btn = QPushButton("Continue")
        continue_btn.setObjectName("SuccessButton")
        continue_btn.setProperty("class", "WideDialogButton")
        continue_btn.setMinimumHeight(34)
        cancel_btn.clicked.connect(self.cancel)
        continue_btn.clicked.connect(self.confirm)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(continue_btn)
        layout.addLayout(buttons)

    def confirm(self):
        self.result = True
        self.accept()

    def cancel(self):
        self.result = False
        self.reject()


class SettingsDialog(QDialog):
    def __init__(self, parent, master=None):
        super().__init__(parent)
        self.master = master or parent
        self._native_hook_toggle_guard = False
        self.setWindowTitle("Settings")
        self.resize(440, 380)
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 14, 12, 14)
        layout.setSpacing(14)

        form_layout = QFormLayout()
        form_layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form_layout.setFormAlignment(Qt.AlignTop)
        form_layout.setHorizontalSpacing(18)
        form_layout.setVerticalSpacing(14)
        layout.addLayout(form_layout)

        self.hotkey_entry = QLineEdit(config.HOTKEY)
        form_layout.addRow("Scan Hotkey:", self.hotkey_entry)

        self.reset_hotkey_entry = QLineEdit(config.RESET_HOTKEY)
        form_layout.addRow("Reset Hotkey:", self.reset_hotkey_entry)

        self.record_hotkey_entry = QLineEdit(getattr(config, "PLAYER_STATS_RECORD_HOTKEY", "f8"))
        form_layout.addRow("Record Hotkey:", self.record_hotkey_entry)

        self.toggle_skip_chest_animation_hotkey_entry = QLineEdit(
            getattr(config, "TOGGLE_SKIP_CHEST_ANIMATION_HOTKEY", "f11")
        )
        self.toggle_auto_select_upgrades_hotkey_entry = QLineEdit(
            getattr(config, "TOGGLE_AUTO_SELECT_UPGRADES_HOTKEY", "f10")
        )
        self.toggle_particles_opacity_hotkey_entry = QLineEdit(
            getattr(config, "TOGGLE_PARTICLES_OPACITY_HOTKEY", "f7")
        )
        form_layout.addRow("Toggle Chest Skip Hotkey:", self.toggle_skip_chest_animation_hotkey_entry)
        form_layout.addRow("Toggle Auto Level-Up Hotkey:", self.toggle_auto_select_upgrades_hotkey_entry)
        form_layout.addRow("Toggle Particles Opacity Hotkey:", self.toggle_particles_opacity_hotkey_entry)

        self.min_delay_entry = QLineEdit(str(config.MIN_DELAY))
        self.map_load_delay_entry = self.min_delay_entry
        form_layout.addRow("Min Reroll Delay (s):", self.min_delay_entry)

        self.reset_hold_duration_entry = QLineEdit(str(config.RESET_HOLD_DURATION))
        form_layout.addRow("Reset Hold Duration (s):", self.reset_hold_duration_entry)

        self.record_interval_entry = QLineEdit(str(getattr(config, "PLAYER_STATS_RECORD_INTERVAL_SECONDS", 30)))
        form_layout.addRow("Snapshot Interval (s):", self.record_interval_entry)

        self.native_hook_enabled_var = QCheckBox("Use native hook restart")
        self.native_hook_enabled_var.setChecked(bool(getattr(config, "NATIVE_HOOK_ENABLED", True)))
        self.native_hook_enabled_var.toggled.connect(self.on_native_hook_toggle)
        layout.addWidget(self.native_hook_enabled_var)

        button_row = QVBoxLayout()
        button_row.setSpacing(10)
        self.update_btn = QPushButton("Check for Updates")
        self.update_btn.clicked.connect(self.check_update)
        self.save_btn = QPushButton("Save")
        self.save_btn.setObjectName("SuccessButton")
        self.save_btn.clicked.connect(self.save)
        button_row.addWidget(self.update_btn)
        button_row.addWidget(self.save_btn)
        layout.addLayout(button_row)

        layout.addSpacing(6)

        support_divider = QFrame()
        support_divider.setObjectName("SupportDivider")
        support_divider.setFrameShape(QFrame.HLine)
        support_divider.setFrameShadow(QFrame.Plain)
        layout.addWidget(support_divider)

        support_label = QLabel("Support")
        support_label.setObjectName("SupportSectionLabel")
        support_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(support_label)

        support_note = QLabel(
            "BonkScanner is free to download here. "
            "If you want, you can also support the project."
        )
        support_note.setObjectName("SupportSectionNote")
        support_note.setAlignment(Qt.AlignCenter)
        support_note.setWordWrap(True)
        layout.addWidget(support_note)

        support_button_row = QHBoxLayout()
        support_button_row.setSpacing(10)
        support_button_row.setAlignment(Qt.AlignHCenter)
        self.patreon_btn = QPushButton("Patreon")
        self.patreon_btn.setObjectName("PatreonButton")
        self.patreon_btn.setIcon(QIcon(resource_path(PATREON_ICON_PATH)))
        self.patreon_btn.setIconSize(QSize(18, 18))
        self.patreon_btn.clicked.connect(self.open_patreon_support_page)
        self.patreon_btn.setProperty("class", "SupportPlatformButton")
        self.kofi_btn = QPushButton("Ko-fi")
        self.kofi_btn.setObjectName("KofiButton")
        self.kofi_btn.setIcon(QIcon(resource_path(KOFI_ICON_PATH)))
        self.kofi_btn.setIconSize(QSize(18, 18))
        self.kofi_btn.clicked.connect(self.open_kofi_support_page)
        self.kofi_btn.setProperty("class", "SupportPlatformButton")
        self._sync_support_button_sizes()
        support_button_row.addWidget(self.patreon_btn)
        support_button_row.addWidget(self.kofi_btn)
        layout.addLayout(support_button_row)

    def _set_native_hook_checkbox_value(self, enabled: bool):
        self._native_hook_toggle_guard = True
        try:
            _set_bool(self.native_hook_enabled_var, enabled)
        finally:
            self._native_hook_toggle_guard = False

    def _sync_support_button_sizes(self):
        buttons = [self.patreon_btn, self.kofi_btn]
        target_width = max(button.sizeHint().width() for button in buttons)
        for button in buttons:
            button.setFixedWidth(target_width)
            button.setFixedHeight(26)

    def prompt_native_hook_enable_confirmation(self) -> bool:
        dialog = NativeHookWarningDialog(self)
        dialog.exec()
        return bool(dialog.result)

    def on_native_hook_toggle(self):
        if getattr(self, "_native_hook_toggle_guard", False):
            return
        if not _read_bool(self.native_hook_enabled_var):
            return
        if not SettingsDialog.prompt_native_hook_enable_confirmation(self):
            SettingsDialog._set_native_hook_checkbox_value(self, False)

    def check_update(self):
        threading.Thread(target=updater.check_and_update, args=(self.master, True), daemon=True).start()
        if hasattr(self, "close"):
            self.close()

    def open_patreon_support_page(self):
        webbrowser.open(PATREON_SUPPORT_URL)

    def open_kofi_support_page(self):
        webbrowser.open(KOFI_SUPPORT_URL)

    def save(self):
        new_hotkey = _read_text(self.hotkey_entry).strip()
        new_reset_hotkey = _read_text(self.reset_hotkey_entry).strip()
        new_record_hotkey = _read_text(self.record_hotkey_entry).strip()
        new_toggle_skip_chest_animation_hotkey = _read_text(self.toggle_skip_chest_animation_hotkey_entry).strip()
        new_toggle_auto_select_upgrades_hotkey = _read_text(self.toggle_auto_select_upgrades_hotkey_entry).strip()
        new_toggle_particles_opacity_hotkey = _read_text(self.toggle_particles_opacity_hotkey_entry).strip()
        native_hook_enabled = _read_bool(self.native_hook_enabled_var)

        config.user_config["HOTKEY"] = new_hotkey
        config.user_config["RESET_HOTKEY"] = new_reset_hotkey
        config.user_config["PLAYER_STATS_RECORD_HOTKEY"] = new_record_hotkey
        config.user_config["TOGGLE_SKIP_CHEST_ANIMATION_HOTKEY"] = new_toggle_skip_chest_animation_hotkey
        config.user_config["TOGGLE_AUTO_SELECT_UPGRADES_HOTKEY"] = new_toggle_auto_select_upgrades_hotkey
        config.user_config["TOGGLE_PARTICLES_OPACITY_HOTKEY"] = new_toggle_particles_opacity_hotkey
        config.user_config["NATIVE_HOOK_ENABLED"] = native_hook_enabled

        config.HOTKEY = new_hotkey
        config.RESET_HOTKEY = new_reset_hotkey
        config.PLAYER_STATS_RECORD_HOTKEY = new_record_hotkey
        config.TOGGLE_SKIP_CHEST_ANIMATION_HOTKEY = new_toggle_skip_chest_animation_hotkey
        config.TOGGLE_AUTO_SELECT_UPGRADES_HOTKEY = new_toggle_auto_select_upgrades_hotkey
        config.TOGGLE_PARTICLES_OPACITY_HOTKEY = new_toggle_particles_opacity_hotkey
        config.NATIVE_HOOK_ENABLED = native_hook_enabled

        delay_entry = getattr(self, "min_delay_entry", None) or getattr(self, "map_load_delay_entry", None)
        try:
            new_delay = float(_read_text(delay_entry))
            config.user_config["MIN_DELAY"] = new_delay
            config.MIN_DELAY = new_delay
            config.MAP_LOAD_DELAY = new_delay
        except ValueError:
            pass

        try:
            new_duration = float(_read_text(self.reset_hold_duration_entry))
            if new_duration < 0.01:
                new_duration = 0.01
            config.user_config["RESET_HOLD_DURATION"] = new_duration
            config.RESET_HOLD_DURATION = new_duration
            game_val = round(new_duration - 0.05, 2)
            if game_val < 0.01:
                game_val = 0.01
            config.update_game_reset_time(game_val)
        except ValueError:
            pass

        try:
            new_interval = max(1, int(float(_read_text(self.record_interval_entry))))
            config.user_config["PLAYER_STATS_RECORD_INTERVAL_SECONDS"] = new_interval
            config.PLAYER_STATS_RECORD_INTERVAL_SECONDS = new_interval
            if hasattr(self.master, "player_stats_vod_recorder") and self.master.player_stats_vod_recorder is not None:
                self.master.player_stats_vod_recorder.interval_seconds = new_interval
        except ValueError:
            pass

        config.save_config(config.user_config)

        if hasattr(self.master, "setup_hotkeys"):
            self.master.setup_hotkeys()
            if hasattr(self.master, "refresh_player_stats_timeline_ui"):
                self.master.refresh_player_stats_timeline_ui(update_slider=False)
            self.master.update_status_ui()
            if hasattr(self.master, "apply_run_control_mode"):
                self.master.apply_run_control_mode()
            self.master.log("[*] Settings saved and applied successfully!", tag="success")

        if hasattr(self, "accept"):
            self.accept()
        elif hasattr(self, "destroy"):
            self.destroy()


class MegabonkApp:
    _qt_app: QApplication | None = None

    @classmethod
    def _ensure_qt_application(cls) -> QApplication:
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
            cls._qt_app = app
            app.setApplicationName("BonkScanner")
            checkmark_path = resource_path("media/checkmark.svg").replace("\\", "/")
            app.setStyleSheet(
                """
                QWidget {
                    background: #10141B;
                    color: #E5E7EB;
                    font-size: 13px;
                }
                QDialog {
                    background: #10141B;
                }
                QGroupBox {
                    border: 1px solid #263241;
                    border-radius: 8px;
                    margin-top: 8px;
                    padding-top: 10px;
                    background: #131A23;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 4px;
                }
                QFrame#StatCard {
                    background: #131A23;
                    border: 1px solid #263241;
                    border-radius: 8px;
                    padding: 8px;
                }
                QFrame#WarningCard {
                    background: #312114;
                    border: 1px solid #5E3417;
                    border-radius: 12px;
                }
                QLineEdit, QTextEdit, QPlainTextEdit, QListWidget {
                    background: #0B1220;
                    border: 1px solid #2B3648;
                    border-radius: 6px;
                    padding: 6px;
                    selection-background-color: #1F6AA5;
                }
                QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QListWidget:focus {
                    border-color: #3B82F6;
                }
                QPushButton {
                    background: #1F6AA5;
                    border: none;
                    border-radius: 8px;
                    padding: 8px 12px;
                    color: white;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background: #2A80C0;
                }
                QPushButton#DangerButton {
                    background: #B91C1C;
                }
                QPushButton#DangerButton:hover {
                    background: #DC2626;
                }
                QPushButton#SuccessButton {
                    background: #2F9E6D;
                    color: white;
                    font-weight: 800;
                }
                QPushButton#SuccessButton:hover {
                    background: #39B77F;
                }
                QFrame#SupportDivider {
                    background: #243244;
                    color: #243244;
                    min-height: 1px;
                    max-height: 1px;
                }
                QLabel#SupportSectionLabel {
                    color: #D7BF72;
                    font-size: 15px;
                    font-weight: 700;
                    padding-top: 2px;
                    padding-bottom: 0px;
                }
                QLabel#SupportSectionNote {
                    color: #98A7BA;
                    font-size: 14px;
                    padding-left: 28px;
                    padding-right: 28px;
                    padding-top: 0px;
                    padding-bottom: 2px;
                }
                QPushButton#PatreonButton {
                    background: #22181A;
                    color: #FF6F61;
                    font-weight: 700;
                    text-align: center;
                    padding: 4px 10px;
                    border: 1px solid #4B2B2F;
                    border-radius: 10px;
                }
                QPushButton#PatreonButton:hover {
                    background: #2B1D20;
                    border: 1px solid #6A393F;
                }
                QPushButton#KofiButton {
                    background: #181F24;
                    color: #29ABE0;
                    font-weight: 700;
                    text-align: center;
                    padding: 4px 10px;
                    border: 1px solid #264555;
                    border-radius: 10px;
                }
                QPushButton#KofiButton:hover {
                    background: #1D262D;
                    border: 1px solid #2F5F77;
                }
                QPushButton[class="SupportPlatformButton"] {
                    min-height: 26px;
                    max-height: 26px;
                    font-size: 13px;
                }
                QPushButton[class="SmallGhostButton"] {
                    background: #18212E;
                    color: #BBD0E5;
                    font-size: 12px;
                    font-weight: 600;
                    padding: 3px 8px;
                    border: 1px solid #2B3648;
                    border-radius: 6px;
                    min-height: 22px;
                    max-height: 22px;
                }
                QPushButton[class="SmallGhostButton"]:hover {
                    background: #1E2A39;
                    border-color: #3A4D66;
                    color: #E5E7EB;
                }
                QPushButton[class="WideDialogButton"] {
                    min-height: 34px;
                    font-size: 14px;
                }
                QPushButton#SettingsButton {
                    min-width: 44px;
                    max-width: 44px;
                    min-height: 40px;
                    max-height: 40px;
                    padding: 0;
                    background: #2B3A4F;
                    border: 1px solid #41556F;
                }
                QPushButton#SettingsButton:hover {
                    background: #3A4D66;
                    border-color: #58708D;
                }
                QPushButton#ToggleButton {
                    min-width: 138px;
                    font-weight: 800;
                    letter-spacing: 0.5px;
                    background: #1F6AA5;
                    border: none;
                    color: white;
                }
                QPushButton#ToggleButton:hover {
                    background: #2A80C0;
                }
                QTabWidget::pane {
                    border: 1px solid #263241;
                    border-radius: 8px;
                    top: -1px;
                    background: #131A23;
                }
                QTabBar::tab {
                    background: #1F2937;
                    padding: 8px 12px;
                    margin-right: 4px;
                    border-top-left-radius: 6px;
                    border-top-right-radius: 6px;
                    min-width: 92px;
                }
                QTabBar::tab:selected {
                    background: #1F6AA5;
                    color: white;
                    font-weight: 700;
                }
                QTabBar::tab:hover:!selected {
                    background: #273449;
                }
                QLabel#SectionHeader {
                    font-size: 20px;
                    font-weight: 700;
                }
                QLabel#WarningTitle {
                    color: #F59E0B;
                    background: transparent;
                    font-size: 20px;
                    font-weight: 800;
                }
                QLabel#StatusLabel {
                    color: #D1D5DB;
                    font-family: Consolas;
                    font-weight: 700;
                    padding-left: 14px;
                }
                QCheckBox {
                    spacing: 8px;
                }
                QCheckBox::indicator {
                    width: 20px;
                    height: 20px;
                    border-radius: 5px;
                    border: 2px solid #6B7280;
                    background: #111827;
                }
                QCheckBox::indicator:hover {
                    border-color: #93C5FD;
                }
                QCheckBox::indicator:checked {
                    background: #1F6AA5;
                    border-color: #3B82F6;
                    image: url(__CHECKMARK_ICON__);
                }
                QCheckBox::indicator:checked:disabled {
                    background: #34445E;
                }
                QScrollBar:vertical {
                    background: #111827;
                    width: 12px;
                    margin: 2px;
                    border-radius: 6px;
                }
                QScrollBar::handle:vertical {
                    background: #7DD3FC;
                    min-height: 32px;
                    border-radius: 6px;
                    border: 1px solid #BAE6FD;
                }
                QScrollBar::handle:vertical:hover {
                    background: #A5E3FF;
                }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                    height: 0;
                }
                QScrollBar:horizontal {
                    background: #111827;
                    height: 12px;
                    margin: 2px;
                    border-radius: 6px;
                }
                QScrollBar::handle:horizontal {
                    background: #7DD3FC;
                    min-width: 32px;
                    border-radius: 6px;
                    border: 1px solid #BAE6FD;
                }
                QScrollBar::handle:horizontal:hover {
                    background: #A5E3FF;
                }
                QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                    width: 0;
                }
                QSlider::groove:horizontal {
                    height: 7px;
                    background: #243042;
                    border-radius: 4px;
                }
                QSlider::handle:horizontal {
                    background: #38BDF8;
                    border: 2px solid #0F172A;
                    width: 16px;
                    margin: -6px 0;
                    border-radius: 8px;
                }
                QSplitter::handle {
                    background: #1B2433;
                    margin: 0 6px;
                    border-radius: 2px;
                }
                """
                .replace("__CHECKMARK_ICON__", checkmark_path)
            )
        cls._qt_app = app
        return app

    def __init__(self):
        self._ensure_qt_application()
        self.window = _AppWindow(self)
        self._invoker = UiInvoker()
        self._close_protocol_handler = None
        self._is_shutting_down = False
        self._close_in_progress = False

        self.setWindowTitle(f"BonkScanner v{updater.CURRENT_VERSION}")
        self.resize(1280, 760)
        self.setMinimumSize(1080, 640)
        icon_path = resource_path("media/bonkscanner_icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.left_tabview = None
        self.tab_templates = None
        self.tab_scores = None
        self.scrollable_templates = None
        self.template_layout = None
        self.scores_templates_frame = None
        self.scores_templates_layout = None
        self.scores_desc_label = None
        self.tabview = None
        self.tab_logs = None
        self.tab_stats = None
        self.tab_player_stats = None
        self.tab_vods = None
        self.log_box = None
        self.stats_time_label = None
        self.stats_rerolls_label = None
        self.stats_rpm_label = None
        self.stats_best_label = None
        self.stats_worst_label = None
        self.stats_avg_frame = None
        self.stats_avg_layout = None
        self.stats_avg_labels = {}
        self.player_stats_status_label = None
        self.player_stats_record_btn = None
        self.player_stats_slider = None
        self.player_stats_slider_time_label = None
        self.player_stats_timeline_label = None
        self.player_stats_detail_tabs = None
        self.player_stats_rows = {}
        self.player_stats_items_group = None
        self.player_stats_items_label = None
        self.player_stats_items_toggle_btn = None
        self.player_stats_items_sort_combo = None
        self.player_stats_items_sort_mode = ITEM_SORT_DEFAULT
        self.player_stats_items_expanded = False
        self.player_stats_items_current = ()
        self.player_stats_items_text_current = None
        self.player_stats_in_game_time_label = None
        self.player_stats_chests_per_minute_label = None
        self.player_stats_mob_kills_label = None
        self.player_stats_level_label = None
        self.player_stats_new_items_label = None
        self.player_stats_stage_summary_labels = []
        self.player_stats_weapons_status_label = None
        self.player_stats_weapons_layout = None
        self.player_stats_weapon_cards = []
        self.player_stats_weapon_signature = None
        self.vods_list_frame = None
        self.vods_status_label = None
        self.vods_name_entry = None
        self.vods_rename_btn = None
        self.vods_delete_btn = None
        self.vods_slider = None
        self.vods_slider_time_label = None
        self.vods_detail_tabs = None
        self.vods_rows = {}
        self.vods_items_group = None
        self.vods_items_label = None
        self.vods_items_toggle_btn = None
        self.vods_items_sort_combo = None
        self.vods_items_sort_mode = ITEM_SORT_DEFAULT
        self.vods_items_expanded = False
        self.vods_items_current = ()
        self.vods_items_text_current = None
        self.vods_in_game_time_label = None
        self.vods_chests_per_minute_label = None
        self.vods_mob_kills_label = None
        self.vods_level_label = None
        self.vods_new_items_label = None
        self.vods_stage_summary_labels = []
        self.vods_weapons_status_label = None
        self.vods_weapons_layout = None
        self.vods_weapon_cards = []
        self.vods_weapon_signature = None
        self.status_label = None
        self.toggle_btn = None
        self.logo_label = None

        self.is_running = False
        self.is_ready_to_start = False
        self.active_templates = []
        self.scanner_thread = None
        self.client = None
        self.player_stats_client = None
        self.player_stats_game_data_client = None
        self.player_stats_vod_recorder = VodRecorder(
            interval_seconds=getattr(config, "PLAYER_STATS_RECORD_INTERVAL_SECONDS", 30),
        )
        self.player_stats_vod_snapshots = []
        self.player_stats_selected_snapshot_index = None
        self.player_stats_recording_seed = None
        self.player_stats_recording_stage_ptr = 0
        self.player_stats_recording_seed_missing_since = None
        self.player_stats_recording_run_time_seconds = None
        self.loaded_vod = None
        self.loaded_vod_snapshot_index = None
        self.native_hook_loader = None
        self.native_hook_thread = None
        self.native_hook_generation = 0
        self.run_control_provider = None
        self._native_hook_admin_warning_logged = False
        self.checkboxes = {}
        self.scores_checkboxes = {}
        self.animation_active = False
        self.animation_frame = 0
        self.stop_event = threading.Event()
        self.scan_event = threading.Event()
        self.session_start_time = None
        self.session_rerolls = 0
        self.best_map_stats = None
        self.best_map_score = -1
        self.worst_map_stats = None
        self.worst_map_score = float("inf")
        self.template_stats = {}
        self.vods_list_signature = None

        self.setup_ui()
        self.refresh_templates()
        self.refresh_scores_templates_list()
        self.refresh_scores_ui()
        self.setup_hotkeys()
        self.update_timer()
        self.update_player_stats_timer()
        self.check_admin_rights()
        self.log(f"[*] Welcome to BonkScanner v{updater.CURRENT_VERSION}!", tag="success")
        self.log(f"[*] Target Process: {config.PROCESS_NAME}")
        self.log("[*] Ready! Select templates and start the main process loop.")
        self.apply_run_control_mode(detach_hooks=False)
        self.after(1500, self.deferred_update_check)

    def __getattr__(self, name: str):
        window = self.__dict__.get("window")
        if window is not None and hasattr(window, name):
            return getattr(window, name)
        raise AttributeError(name)

    @staticmethod
    def _scope_prefix(scope: str) -> str:
        scope_prefixes = {
            "live": "player_stats",
            "vod": "vods",
        }
        try:
            return scope_prefixes[scope]
        except KeyError as exc:
            raise ValueError(f"Unknown UI scope: {scope}") from exc

    @property
    def qt_app(self) -> QApplication:
        return self._ensure_qt_application()

    def protocol(self, name: str, callback: object) -> None:
        if name == "WM_DELETE_WINDOW":
            self._close_protocol_handler = callback

    def mainloop(self) -> int:
        self.window.show()
        return self.qt_app.exec()

    def destroy(self):
        self._close_in_progress = True
        self.window.close()

    def _handle_window_close(self, event: QCloseEvent) -> None:
        if self._close_in_progress or self._is_shutting_down:
            event.accept()
            return
        handler = self._close_protocol_handler or getattr(self, "on_closing", None)
        if callable(handler):
            event.ignore()
            handler()
            return
        event.accept()

    def after(self, delay_ms: int, callback):
        self._invoker.call_later.emit(int(delay_ms), callback)
        return None

    def after_idle(self, callback):
        self._invoker.call_now.emit(callback)
        return None

    def winfo_exists(self) -> bool:
        return not self._is_shutting_down

    def initialize_run_control(self):
        if not getattr(config, "NATIVE_HOOK_ENABLED", True):
            self.enable_keyboard_run_control()
            return
        self.enable_hook_run_control()

    def apply_run_control_mode(self, *, detach_hooks: bool = True):
        if getattr(config, "NATIVE_HOOK_ENABLED", True):
            self.enable_hook_run_control()
        else:
            previous_loader = self.native_hook_loader
            self.native_hook_generation += 1
            self.native_hook_loader = None
            self.native_hook_thread = None

            if detach_hooks and previous_loader is not None:
                try:
                    previous_loader.uninitialize()
                    self.log("[+] Game restart helper disconnected.", tag="success")
                except HookProcessNotFoundError:
                    self.log("[WAIT] Game is already closed; restart helper disconnected.", tag="warning")
                except HookLoadError as exc:
                    self.log(
                        f"[WAIT] Could not disconnect game restart helper; switching to keyboard restart. Details: {exc}",
                        tag="warning",
                    )

            self.enable_keyboard_run_control()

    def enable_keyboard_run_control(self):
        self._native_hook_admin_warning_logged = False
        self.run_control_provider = KeyboardRunControlProvider(
            keyboard,
            reset_hotkey=lambda: config.RESET_HOTKEY,
            reset_hold_duration=lambda: config.RESET_HOLD_DURATION,
            map_load_delay=lambda: config.MIN_DELAY,
        )

    def enable_hook_run_control(self):
        if isinstance(self.run_control_provider, HookRunControlProvider):
            return

        self.warn_if_native_hook_needs_admin()

        dll_path = getattr(config, "NATIVE_HOOK_DLL_PATH", "") or None
        self.native_hook_loader = NativeHookLoader(
            config.PROCESS_NAME,
            dll_path=dll_path,
            base_path=config.application_path,
        )
        self.run_control_provider = HookRunControlProvider(
            self.native_hook_loader,
            map_load_delay=lambda: config.MIN_DELAY,
        )
        self.native_hook_generation += 1
        generation = self.native_hook_generation
        self.native_hook_thread = threading.Thread(
            target=self.native_hook_loop,
            args=(self.native_hook_loader, generation),
            daemon=True,
        )
        self.native_hook_thread.start()
        self.log("[*] Game restart helper enabled.")

    def native_hook_loop(self, loader: NativeHookLoader, generation: int):
        if loader is None:
            return

        logged_waiting = False
        while not self.stop_event.is_set() and generation == self.native_hook_generation:
            try:
                result = loader.inject_once()
                if generation != self.native_hook_generation:
                    return
                if result.skipped:
                    self.log("[*] Game restart helper is already connected.")
                else:
                    self.log("[+] Game restart helper connected successfully.", tag="success")
                return
            except HookProcessNotFoundError:
                if not logged_waiting:
                    self.log("[WAIT] Waiting for the game before connecting restart helper.")
                    logged_waiting = True
                self.stop_event.wait(1.0)
            except HookProcessNotReadyError:
                if not logged_waiting:
                    self.log("[WAIT] Game is starting up. Restart helper will connect automatically.")
                    logged_waiting = True
                self.stop_event.wait(1.0)
            except HookLoadError as exc:
                self.log(f"[-] Could not connect game restart helper. Details: {exc}", tag="error")
                return
            except Exception as exc:
                self.log(f"[-] Unexpected restart helper error. Details: {exc}", tag="error")
                return

    def deferred_update_check(self):
        threading.Thread(target=updater.check_and_update, args=(self, False), daemon=True).start()

    def check_admin_rights(self):
        if os.name != "nt":
            return
        if not self.is_running_as_admin():
            if getattr(config, "NATIVE_HOOK_ENABLED", True):
                self.warn_if_native_hook_needs_admin()
                return
            self.log("\u26a0\ufe0f WARNING: Script is not running as Administrator!", tag="warning")
            self.log("\u26a0\ufe0f Hotkeys may not work while the game window is active.", tag="warning")

    def is_running_as_admin(self) -> bool:
        if os.name != "nt":
            return True
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    def warn_if_native_hook_needs_admin(self):
        if self._native_hook_admin_warning_logged:
            return
        if not self.is_running_as_admin():
            self.log("[*] Game restart helper may need Administrator privileges; trying anyway.", tag="warning")
        self._native_hook_admin_warning_logged = True

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(10)

        header_wrap = QWidget()
        header = QVBoxLayout(header_wrap)
        header.setContentsMargins(0, 4, 0, 8)
        header.setSpacing(6)
        header.setAlignment(Qt.AlignHCenter)

        title = QLabel("BonkScanner")
        title.setObjectName("SectionHeader")
        title.setAlignment(Qt.AlignHCenter)
        header.addWidget(title, 0, Qt.AlignHCenter)

        logo_label = QLabel()
        self.logo_label = logo_label
        logo_label.setAlignment(Qt.AlignHCenter)
        logo_path = resource_path("media/bonkscanner_icon2.png")
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path)
            if not pixmap.isNull():
                logo_label.setPixmap(
                    pixmap.scaled(72, 50, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
            else:
                logo_label.setText("BONK")
        else:
            logo_label.setText("BONK")
        header.addWidget(logo_label, 0, Qt.AlignHCenter)
        root_layout.addWidget(header_wrap)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        root_layout.addWidget(splitter, 1)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        splitter.addWidget(left_panel)

        self.left_tabview = QTabWidget()
        self.left_tabview.currentChanged.connect(self.on_left_tab_changed)
        left_layout.addWidget(self.left_tabview)

        self.tab_templates = QWidget()
        templates_layout = QVBoxLayout(self.tab_templates)
        self.scrollable_templates, _templates_content, self.template_layout = _make_scroll_section()
        templates_layout.addWidget(self.scrollable_templates, 1)
        template_buttons = QHBoxLayout()
        self.add_btn = QPushButton("+ Add")
        self.add_btn.clicked.connect(self.add_template_dialog)
        self.edit_btn = QPushButton("Edit")
        self.edit_btn.clicked.connect(self.edit_template_dialog)
        self.del_btn = QPushButton("Delete")
        self.del_btn.setObjectName("DangerButton")
        self.del_btn.clicked.connect(self.del_template_dialog)
        template_buttons.addWidget(self.add_btn)
        template_buttons.addWidget(self.edit_btn)
        template_buttons.addWidget(self.del_btn)
        template_buttons.addStretch(1)
        templates_layout.addLayout(template_buttons)
        self.left_tabview.addTab(self.tab_templates, "Templates")

        self.tab_scores = QWidget()
        scores_layout = QVBoxLayout(self.tab_scores)
        scores_group = QGroupBox("Active Tiers")
        self.scores_templates_layout = QVBoxLayout(scores_group)
        scores_layout.addWidget(scores_group)
        self.scores_desc_label = QTextEdit()
        self.scores_desc_label.setReadOnly(True)
        scores_layout.addWidget(self.scores_desc_label, 1)
        scores_buttons = QHBoxLayout()
        self.edit_scores_btn = QPushButton("Edit Settings")
        _apply_button_icon(self.edit_scores_btn, "media/settings_icon.png", 18)
        self.edit_scores_btn.clicked.connect(self.open_scores_settings_dialog)
        scores_buttons.addWidget(self.edit_scores_btn)
        scores_buttons.addStretch(1)
        scores_layout.addLayout(scores_buttons)
        self.left_tabview.addTab(self.tab_scores, "Scores")
        self.left_tabview.setCurrentIndex(1 if config.EVALUATION_MODE == "scores" else 0)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        splitter.addWidget(right_panel)
        splitter.setSizes([360, 900])

        self.tabview = QTabWidget()
        self.tabview.currentChanged.connect(self.on_right_tab_changed)
        right_layout.addWidget(self.tabview, 1)

        self.tab_logs = QWidget()
        logs_layout = QVBoxLayout(self.tab_logs)
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setFont(QFont("Consolas", 11))
        logs_layout.addWidget(self.log_box)
        self.tabview.addTab(self.tab_logs, "Logs")

        self.tab_stats = QWidget()
        stats_layout = QVBoxLayout(self.tab_stats)
        stats_scroll, _stats_content, stats_content_layout = _make_scroll_section()
        stats_layout.addWidget(stats_scroll)
        self.stats_time_label = QLabel("Session Time: 00:00:00")
        self.stats_rerolls_label = QLabel("Session Rerolls: 0")
        self.stats_rpm_label = QLabel("Rerolls per Minute (RPM): 0.0")
        self.stats_best_label = QLabel("Best Map Found: None")
        self.stats_worst_label = QLabel("Worst Map Found: None")

        overview_group = QGroupBox("Session Overview")
        overview_layout = QVBoxLayout(overview_group)
        overview_layout.setContentsMargins(12, 12, 12, 12)
        overview_layout.setSpacing(8)
        for widget in (
            self.stats_time_label,
            self.stats_rerolls_label,
            self.stats_rpm_label,
        ):
            widget.setWordWrap(True)
            widget.setStyleSheet(_session_stats_label_stylesheet(accent=True))
            overview_layout.addWidget(widget)
        stats_content_layout.addWidget(overview_group)

        maps_group = QGroupBox("Map Highlights")
        maps_layout = QVBoxLayout(maps_group)
        maps_layout.setContentsMargins(12, 12, 12, 12)
        maps_layout.setSpacing(10)
        for widget in (
            self.stats_best_label,
            self.stats_worst_label,
        ):
            widget.setWordWrap(True)
            widget.setStyleSheet(_session_stats_label_stylesheet())
            maps_layout.addWidget(widget)
        stats_content_layout.addWidget(maps_group)

        average_group = QGroupBox("Average Rerolls per Target")
        average_layout = QVBoxLayout(average_group)
        average_layout.setContentsMargins(12, 12, 12, 12)
        average_layout.setSpacing(8)
        self.stats_avg_frame = QWidget()
        self.stats_avg_layout = QVBoxLayout(self.stats_avg_frame)
        self.stats_avg_layout.setContentsMargins(0, 0, 0, 0)
        self.stats_avg_layout.setSpacing(6)
        average_layout.addWidget(self.stats_avg_frame)
        stats_content_layout.addWidget(average_group)
        stats_content_layout.addStretch(1)
        self.tabview.addTab(self.tab_stats, "Session Stats")

        self.tab_player_stats = QWidget()
        player_layout = QVBoxLayout(self.tab_player_stats)
        player_scroll, _player_content, player_content_layout = _make_scroll_section()
        player_layout.addWidget(player_scroll)
        self.player_stats_status_label = QLabel("Waiting for game...")
        player_content_layout.addWidget(self.player_stats_status_label)
        player_controls = QHBoxLayout()
        self.player_stats_record_btn = QPushButton(f"Start Recording ({config.PLAYER_STATS_RECORD_HOTKEY.upper()})")
        self.player_stats_record_btn.clicked.connect(self.toggle_player_stats_recording)
        self.player_stats_timeline_label = QLabel("Live stats")
        player_controls.addWidget(self.player_stats_record_btn)
        player_controls.addStretch(1)
        player_controls.addWidget(self.player_stats_timeline_label)
        player_content_layout.addLayout(player_controls)
        self.player_stats_slider = QSlider(Qt.Horizontal)
        self.player_stats_slider.setEnabled(False)
        self.player_stats_slider.valueChanged.connect(self.on_player_stats_slider_changed)
        player_content_layout.addWidget(self.player_stats_slider)
        self.player_stats_slider_time_label = QLabel("Timeline: live stats")
        player_content_layout.addWidget(self.player_stats_slider_time_label)
        items_group = QGroupBox("Items")
        self.player_stats_items_group = items_group
        items_layout = QVBoxLayout(items_group)
        self.player_stats_items_label = QLabel("--")
        self.player_stats_items_label.setTextFormat(Qt.RichText)
        self.player_stats_items_label.setWordWrap(True)
        items_layout.addWidget(self.player_stats_items_label)
        self.player_stats_items_toggle_btn = QPushButton("Show all")
        self.player_stats_items_toggle_btn.clicked.connect(self.toggle_player_items_expanded)
        self.player_stats_items_toggle_btn.setProperty("class", "SmallGhostButton")
        self.player_stats_items_toggle_btn.setVisible(False)
        items_actions = QHBoxLayout()
        self.player_stats_items_sort_combo = QComboBox()
        for mode, label in ITEM_SORT_LABELS.items():
            self.player_stats_items_sort_combo.addItem(label, mode)
        self.player_stats_items_sort_combo.currentIndexChanged.connect(
            lambda _index: self.on_items_sort_changed("live")
        )
        items_actions.addWidget(self.player_stats_items_toggle_btn, 0, Qt.AlignLeft)
        items_actions.addStretch(1)
        items_actions.addWidget(QLabel("Sort:"))
        items_actions.addWidget(self.player_stats_items_sort_combo)
        items_layout.addLayout(items_actions)
        player_content_layout.addWidget(items_group)
        live_summary_grid = QGridLayout()
        live_summary_grid.setContentsMargins(0, 0, 0, 0)
        live_summary_grid.setHorizontalSpacing(8)
        live_summary_grid.setVerticalSpacing(8)
        chest_rate_group = QGroupBox("Run Summary")
        chest_rate_layout = QVBoxLayout(chest_rate_group)
        self.player_stats_chests_per_minute_label = QLabel("Average chests/min: --")
        chest_rate_layout.addWidget(self.player_stats_chests_per_minute_label)
        self.player_stats_in_game_time_label = QLabel("In-Game Time: --")
        chest_rate_layout.addWidget(self.player_stats_in_game_time_label)
        self.player_stats_mob_kills_label = QLabel("Mob Kills: --")
        chest_rate_layout.addWidget(self.player_stats_mob_kills_label)
        self.player_stats_level_label = QLabel("Level: --")
        chest_rate_layout.addWidget(self.player_stats_level_label)
        live_summary_grid.addWidget(chest_rate_group, 0, 0)
        live_stage_summary_group = QGroupBox("Stage Summary")
        live_stage_summary_layout = QGridLayout(live_stage_summary_group)
        live_stage_summary_layout.setContentsMargins(10, 10, 10, 10)
        live_stage_summary_layout.setHorizontalSpacing(10)
        live_stage_summary_layout.setVerticalSpacing(4)
        for column, header in enumerate(("Stage", "Time", "Kills", "Items")):
            label = QLabel(header)
            label.setStyleSheet("font-weight: 700; color: #F3F4F6;")
            label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            live_stage_summary_layout.addWidget(label, 0, column)
        self.player_stats_stage_summary_labels = []
        for index in range(4):
            stage_label = QLabel(str(index + 1))
            time_label = QLabel("--")
            kills_label = QLabel("--")
            items_label = QLabel("--")
            stage_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            for value_label in (time_label, kills_label, items_label):
                value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            live_stage_summary_layout.addWidget(stage_label, index + 1, 0)
            live_stage_summary_layout.addWidget(time_label, index + 1, 1)
            live_stage_summary_layout.addWidget(kills_label, index + 1, 2)
            live_stage_summary_layout.addWidget(items_label, index + 1, 3)
            self.player_stats_stage_summary_labels.append(
                {
                    "stage": stage_label,
                    "time": time_label,
                    "kills": kills_label,
                    "items": items_label,
                }
            )
        live_stage_summary_layout.setColumnStretch(0, 1)
        live_stage_summary_layout.setColumnStretch(1, 2)
        live_stage_summary_layout.setColumnStretch(2, 1)
        live_stage_summary_layout.setColumnStretch(3, 1)
        live_summary_grid.addWidget(live_stage_summary_group, 0, 1)
        live_new_items_group = QGroupBox("New Items")
        live_new_items_layout = QVBoxLayout(live_new_items_group)
        self.player_stats_new_items_label = QLabel("Live snapshot")
        self.player_stats_new_items_label.setTextFormat(Qt.RichText)
        self.player_stats_new_items_label.setWordWrap(True)
        live_new_items_layout.addWidget(self.player_stats_new_items_label)
        live_summary_grid.addWidget(live_new_items_group, 0, 2, 1, 2)
        for column in range(4):
            live_summary_grid.setColumnStretch(column, 1)
        player_content_layout.addLayout(live_summary_grid)
        self.player_stats_detail_tabs = QTabWidget()
        player_stats_tab = QWidget()
        player_stats_tab_layout = QVBoxLayout(player_stats_tab)
        player_stats_scroll, _player_stats_scroll_content, player_stats_scroll_layout = _make_scroll_section()
        player_stats_tab_layout.addWidget(player_stats_scroll)
        player_stats_grid = QGridLayout()
        player_stats_grid.setContentsMargins(0, 0, 0, 0)
        player_stats_grid.setHorizontalSpacing(8)
        player_stats_grid.setVerticalSpacing(8)
        for index, group in enumerate(PLAYER_STAT_GROUPS):
            stat_group = QFrame()
            stat_group.setObjectName("StatCard")
            group_layout = QFormLayout(stat_group)
            group_layout.setContentsMargins(10, 10, 10, 10)
            group_layout.setVerticalSpacing(6)
            for spec in group:
                value_label = QLabel("--")
                value_label.setMinimumWidth(PLAYER_STATS_VALUE_WIDTH)
                value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.player_stats_rows[spec.label] = value_label
                group_layout.addRow(spec.label, value_label)
            player_stats_grid.addWidget(stat_group, index // 2, index % 2)
        player_stats_grid.setColumnStretch(0, 1)
        player_stats_grid.setColumnStretch(1, 1)
        player_stats_scroll_layout.addLayout(player_stats_grid)
        player_stats_scroll_layout.addStretch(1)
        weapons_tab = QWidget()
        weapons_tab_layout = QVBoxLayout(weapons_tab)
        self.player_stats_weapons_status_label = QLabel("Waiting for weapon data...")
        self.player_stats_weapons_status_label.setWordWrap(True)
        weapons_tab_layout.addWidget(self.player_stats_weapons_status_label)
        player_weapons_scroll, _player_weapons_scroll_content, player_weapons_scroll_layout = _make_scroll_section()
        player_weapons_scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.player_stats_weapons_layout = player_weapons_scroll_layout
        weapons_tab_layout.addWidget(player_weapons_scroll)
        self.player_stats_detail_tabs.addTab(player_stats_tab, "Stats")
        self.player_stats_detail_tabs.addTab(weapons_tab, "Weapons")
        player_content_layout.addWidget(self.player_stats_detail_tabs)
        player_stats_tab_layout.setContentsMargins(0, 0, 0, 0)
        weapons_tab_layout.setContentsMargins(0, 0, 0, 0)
        self.tabview.addTab(self.tab_player_stats, "Live Stats")

        self.tab_vods = QWidget()
        vods_layout = QHBoxLayout(self.tab_vods)
        self.vods_list_frame = QListWidget()
        self.vods_list_frame.currentItemChanged.connect(self._on_vod_selection_changed)
        vods_layout.addWidget(self.vods_list_frame, 1)
        vods_detail = QWidget()
        vods_detail_layout = QVBoxLayout(vods_detail)
        self.vods_status_label = QLabel("Select a recording")
        vods_detail_layout.addWidget(self.vods_status_label)
        name_row = QHBoxLayout()
        self.vods_name_entry = QLineEdit()
        self.vods_rename_btn = QPushButton("Rename")
        self.vods_rename_btn.clicked.connect(self.rename_selected_vod)
        self.vods_cleanup_btn = QPushButton("Clean Short")
        self.vods_cleanup_btn.clicked.connect(self.cleanup_recordings_by_snapshot_count)
        self.vods_delete_btn = QPushButton("Delete")
        self.vods_delete_btn.setObjectName("DangerButton")
        self.vods_delete_btn.clicked.connect(self.delete_selected_vod)
        name_row.addWidget(self.vods_name_entry, 1)
        name_row.addWidget(self.vods_rename_btn)
        name_row.addWidget(self.vods_cleanup_btn)
        name_row.addWidget(self.vods_delete_btn)
        vods_detail_layout.addLayout(name_row)
        self.vods_slider = QSlider(Qt.Horizontal)
        self.vods_slider.setEnabled(False)
        self.vods_slider.valueChanged.connect(self.on_vods_slider_changed)
        vods_detail_layout.addWidget(self.vods_slider)
        self.vods_slider_time_label = QLabel("Timeline: --")
        vods_detail_layout.addWidget(self.vods_slider_time_label)
        vod_items_group = QGroupBox("Items")
        self.vods_items_group = vod_items_group
        vod_items_layout = QVBoxLayout(vod_items_group)
        self.vods_items_label = QLabel("--")
        self.vods_items_label.setTextFormat(Qt.RichText)
        self.vods_items_label.setWordWrap(True)
        vod_items_layout.addWidget(self.vods_items_label)
        self.vods_items_toggle_btn = QPushButton("Show all")
        self.vods_items_toggle_btn.clicked.connect(self.toggle_vod_items_expanded)
        self.vods_items_toggle_btn.setProperty("class", "SmallGhostButton")
        self.vods_items_toggle_btn.setVisible(False)
        vod_items_actions = QHBoxLayout()
        self.vods_items_sort_combo = QComboBox()
        for mode, label in ITEM_SORT_LABELS.items():
            self.vods_items_sort_combo.addItem(label, mode)
        self.vods_items_sort_combo.currentIndexChanged.connect(
            lambda _index: self.on_items_sort_changed("vod")
        )
        vod_items_actions.addWidget(self.vods_items_toggle_btn, 0, Qt.AlignLeft)
        vod_items_actions.addStretch(1)
        vod_items_actions.addWidget(QLabel("Sort:"))
        vod_items_actions.addWidget(self.vods_items_sort_combo)
        vod_items_layout.addLayout(vod_items_actions)
        vods_detail_layout.addWidget(vod_items_group)
        vod_summary_grid = QGridLayout()
        vod_summary_grid.setContentsMargins(0, 0, 0, 0)
        vod_summary_grid.setHorizontalSpacing(8)
        vod_summary_grid.setVerticalSpacing(8)
        vod_chest_rate_group = QGroupBox("Run Summary")
        vod_chest_rate_layout = QVBoxLayout(vod_chest_rate_group)
        self.vods_chests_per_minute_label = QLabel("Average chests/min: --")
        vod_chest_rate_layout.addWidget(self.vods_chests_per_minute_label)
        self.vods_in_game_time_label = QLabel("In-Game Time: --")
        vod_chest_rate_layout.addWidget(self.vods_in_game_time_label)
        self.vods_mob_kills_label = QLabel("Mob Kills: --")
        vod_chest_rate_layout.addWidget(self.vods_mob_kills_label)
        self.vods_level_label = QLabel("Level: --")
        vod_chest_rate_layout.addWidget(self.vods_level_label)
        vod_summary_grid.addWidget(vod_chest_rate_group, 0, 0)
        vod_stage_summary_group = QGroupBox("Stage Summary")
        vod_stage_summary_layout = QGridLayout(vod_stage_summary_group)
        vod_stage_summary_layout.setContentsMargins(10, 10, 10, 10)
        vod_stage_summary_layout.setHorizontalSpacing(10)
        vod_stage_summary_layout.setVerticalSpacing(4)
        for column, header in enumerate(("Stage", "Time", "Kills", "Items")):
            label = QLabel(header)
            label.setStyleSheet("font-weight: 700; color: #F3F4F6;")
            label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            vod_stage_summary_layout.addWidget(label, 0, column)
        self.vods_stage_summary_labels = []
        for index in range(4):
            stage_label = QLabel(str(index + 1))
            time_label = QLabel("--")
            kills_label = QLabel("--")
            items_label = QLabel("--")
            stage_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            for value_label in (time_label, kills_label, items_label):
                value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            vod_stage_summary_layout.addWidget(stage_label, index + 1, 0)
            vod_stage_summary_layout.addWidget(time_label, index + 1, 1)
            vod_stage_summary_layout.addWidget(kills_label, index + 1, 2)
            vod_stage_summary_layout.addWidget(items_label, index + 1, 3)
            self.vods_stage_summary_labels.append(
                {
                    "stage": stage_label,
                    "time": time_label,
                    "kills": kills_label,
                    "items": items_label,
                }
            )
        vod_stage_summary_layout.setColumnStretch(0, 1)
        vod_stage_summary_layout.setColumnStretch(1, 2)
        vod_stage_summary_layout.setColumnStretch(2, 1)
        vod_stage_summary_layout.setColumnStretch(3, 1)
        vod_summary_grid.addWidget(vod_stage_summary_group, 0, 1)
        vod_new_items_group = QGroupBox("New Items")
        vod_new_items_layout = QVBoxLayout(vod_new_items_group)
        self.vods_new_items_label = QLabel("No previous snapshot")
        self.vods_new_items_label.setTextFormat(Qt.RichText)
        self.vods_new_items_label.setWordWrap(True)
        vod_new_items_layout.addWidget(self.vods_new_items_label)
        vod_summary_grid.addWidget(vod_new_items_group, 0, 2, 1, 2)
        for column in range(4):
            vod_summary_grid.setColumnStretch(column, 1)
        vods_detail_layout.addLayout(vod_summary_grid)
        self.vods_detail_tabs = QTabWidget()
        vod_stats_tab = QWidget()
        vod_stats_tab_layout = QVBoxLayout(vod_stats_tab)
        vods_scroll, _vods_scroll_content, vods_scroll_layout = _make_scroll_section()
        vod_stats_tab_layout.addWidget(vods_scroll)
        vods_stats_grid = QGridLayout()
        vods_stats_grid.setContentsMargins(0, 0, 0, 0)
        vods_stats_grid.setHorizontalSpacing(8)
        vods_stats_grid.setVerticalSpacing(8)
        for index, group in enumerate(PLAYER_STAT_GROUPS):
            stat_group = QFrame()
            stat_group.setObjectName("StatCard")
            group_layout = QFormLayout(stat_group)
            group_layout.setContentsMargins(10, 10, 10, 10)
            group_layout.setVerticalSpacing(6)
            for spec in group:
                value_label = QLabel("--")
                value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.vods_rows[spec.label] = value_label
                group_layout.addRow(spec.label, value_label)
            vods_stats_grid.addWidget(stat_group, index // 2, index % 2)
        vods_stats_grid.setColumnStretch(0, 1)
        vods_stats_grid.setColumnStretch(1, 1)
        vods_scroll_layout.addLayout(vods_stats_grid)
        vods_scroll_layout.addStretch(1)
        vod_weapons_tab = QWidget()
        vod_weapons_tab_layout = QVBoxLayout(vod_weapons_tab)
        self.vods_weapons_status_label = QLabel("Select a recording")
        self.vods_weapons_status_label.setWordWrap(True)
        vod_weapons_tab_layout.addWidget(self.vods_weapons_status_label)
        vod_weapons_scroll, _vod_weapons_scroll_content, vod_weapons_scroll_layout = _make_scroll_section()
        vod_weapons_scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.vods_weapons_layout = vod_weapons_scroll_layout
        vod_weapons_tab_layout.addWidget(vod_weapons_scroll)
        self.vods_detail_tabs.addTab(vod_stats_tab, "Stats")
        self.vods_detail_tabs.addTab(vod_weapons_tab, "Weapons")
        vod_stats_tab_layout.setContentsMargins(0, 0, 0, 0)
        vod_weapons_tab_layout.setContentsMargins(0, 0, 0, 0)
        vods_detail_layout.addWidget(self.vods_detail_tabs, 1)
        vods_layout.addWidget(vods_detail, 2)
        self.tabview.addTab(self.tab_vods, "Recordings")

        controls = QHBoxLayout()
        self.settings_btn = QPushButton("")
        self.settings_btn.setObjectName("SettingsButton")
        _apply_button_icon(self.settings_btn, "media/settings_icon.png", 20)
        self.settings_btn.setToolTip("Settings")
        self.settings_btn.clicked.connect(self.open_settings_dialog)
        self.status_label = QLabel("Status: IDLE")
        self.status_label.setObjectName("StatusLabel")
        self.toggle_btn = QPushButton(f"Start")
        self.toggle_btn.setObjectName("ToggleButton")
        self.toggle_btn.clicked.connect(self.toggle_main_loop)
        controls.addWidget(self.settings_btn)
        controls.addWidget(self.status_label, 1)
        controls.addWidget(self.toggle_btn)
        right_layout.addLayout(controls)

    def on_left_tab_changed(self):
        if self.left_tabview is None:
            return
        tab_name = self.left_tabview.tabText(self.left_tabview.currentIndex())
        config.EVALUATION_MODE = "scores" if tab_name == "Scores" else "templates"
        config.user_config["EVALUATION_MODE"] = config.EVALUATION_MODE
        config.save_config(config.user_config)
        self.refresh_scores_ui()
        self._sync_runtime_filters(announce=True)
        self.update_status_ui()

    def on_right_tab_changed(self):
        self._show_right_tab_transition_cover()
        if self._is_recordings_tab_active():
            self.refresh_vods_list()
        self.after_idle(self._refresh_right_tab_after_switch)

    def _refresh_right_tab_after_switch(self):
        if self._is_recordings_tab_active():
            self.refresh_vods_list()
        if self._is_live_stats_tab_active():
            self.refresh_live_player_stats_now()

    def _show_right_tab_transition_cover(self):
        return None

    def _hide_right_tab_transition_cover(self):
        return None

    def _cancel_right_tab_transition(self):
        return None

    def _is_live_stats_tab_active(self) -> bool:
        return self.tabview.tabText(self.tabview.currentIndex()) == "Live Stats"

    def _is_recordings_tab_active(self) -> bool:
        return self.tabview.tabText(self.tabview.currentIndex()) == "Recordings"

    def _refresh_vods_list_if_visible(self):
        if self._is_recordings_tab_active():
            self.refresh_vods_list()

    def refresh_scores_templates_list(self):
        _clear_layout(self.scores_templates_layout)
        self.scores_checkboxes.clear()
        for tier in ("Light", "Good", "Perfect", "Perfect+"):
            cb = QCheckBox(tier)
            cb.setChecked(tier in config.SCORES_SYSTEM.get("active_tiers", []))
            cb.setStyleSheet(f"color: {_tier_color(tier)}; font-weight: 700;")
            cb.toggled.connect(self.refresh_scores_ui)
            self.scores_templates_layout.addWidget(cb)
            self.scores_checkboxes[tier] = cb
        self.scores_templates_layout.addStretch(1)

    def refresh_scores_ui(self):
        if self.scores_desc_label is None:
            return
        active_tiers = [tier for tier, cb in self.scores_checkboxes.items() if cb.isChecked()]
        if active_tiers and active_tiers != config.SCORES_SYSTEM.get("active_tiers", []):
            config.SCORES_SYSTEM["active_tiers"] = active_tiers
            config.user_config["SCORES_SYSTEM"] = config.SCORES_SYSTEM
            config.save_config(config.user_config)
            self._sync_runtime_filters(announce=True)

        weights = config.SCORES_SYSTEM.get("weights", {})
        thresholds = config.SCORES_SYSTEM.get("thresholds", {})
        multipliers = config.SCORES_SYSTEM.get("multipliers", {}).get("microwave", {})
        lines = [
            "<b>Score system</b>",
            "",
            f"Active tiers: {', '.join(config.SCORES_SYSTEM.get('active_tiers', [])) or 'None'}",
            "",
            "<b>Thresholds</b>",
        ]
        for tier in ("Light", "Good", "Perfect", "Perfect+"):
            lines.append(f"{tier}: {thresholds.get(tier, 0.0)}")
        lines.extend(
            [
                "",
                "<b>Weights</b>",
                f"Moais: {weights.get('moais', 0.0)}",
                f"Shady: {weights.get('shady', 0.0)}",
                f"Boss: {weights.get('boss', 0.0)}",
                f"Magnet: {weights.get('magnet', 0.0)}",
                "",
                "<b>Microwave Multipliers</b>",
                f"1 Microwave: {multipliers.get('1', 1.0)}",
                f"2 Microwaves: {multipliers.get('2', 1.25)}",
            ]
        )
        self.scores_desc_label.setHtml("<br>".join(lines))

    def open_scores_settings_dialog(self):
        dialog = ScoresSettingsDialog(self.window)
        if dialog.exec() == QDialog.Accepted:
            self.refresh_scores_templates_list()
            self.refresh_scores_ui()

    def save_checkbox_state(self, *_args):
        selected = [name for name, cb in self.checkboxes.items() if _read_bool(cb)]
        config.ACTIVE_TEMPLATES = selected
        config.user_config["ACTIVE_TEMPLATES"] = selected
        config.save_config(config.user_config)

        self._sync_runtime_filters(announce=True)

    def _is_main_loop_active(self) -> bool:
        scanner_thread = getattr(self, "scanner_thread", None)
        return scanner_thread is not None and scanner_thread.is_alive()

    def _get_selected_template_names(self) -> list[str]:
        checkboxes = getattr(self, "checkboxes", {})
        return [name for name, cb in checkboxes.items() if _read_bool(cb)]

    def _get_active_profile_names(self) -> list[str]:
        if config.EVALUATION_MODE == "templates":
            return self._get_selected_template_names()
        return list(config.SCORES_SYSTEM.get("active_tiers", []))

    def _sync_runtime_filters(self, *, announce: bool = False) -> None:
        active_names = self._get_active_profile_names()
        previous_names = list(getattr(self, "template_stats", {}).keys())

        if config.EVALUATION_MODE == "templates":
            self.active_templates = list(active_names)

        existing_stats = getattr(self, "template_stats", {})
        for name in active_names:
            existing_stats.setdefault(name, {"rerolls_since_last": 0, "history": []})
        self.template_stats = existing_stats

        if hasattr(self, "stats_avg_labels") and hasattr(self, "stats_avg_layout"):
            self.refresh_stats_ui()

        if not announce or not self._is_main_loop_active():
            return

        if active_names == previous_names:
            return

        mode_label = "tiers" if config.EVALUATION_MODE == "scores" else "templates"
        names_text = ", ".join(active_names) if active_names else "none"
        self.log(f"[*] Active {mode_label} updated live: {names_text}")

    def refresh_templates(self):
        _clear_layout(self.template_layout)
        self.checkboxes.clear()
        for template in config.TEMPLATES:
            color_tag = template.get("color", "LIGHTBLUE_EX").upper()
            color_hex = COLOR_MAP.get(color_tag, COLOR_MAP["DEFAULT"])
            cb = QCheckBox(f"{template['name']} ({format_template_conditions(template)})")
            cb.setChecked(template["name"] in config.ACTIVE_TEMPLATES)
            cb.toggled.connect(self.save_checkbox_state)
            cb.setStyleSheet(_template_checkbox_stylesheet(color_hex))
            self.template_layout.addWidget(cb)
            self.checkboxes[template["name"]] = cb
        self.template_layout.addStretch(1)
        self._sync_runtime_filters(announce=True)

    def add_template_dialog(self):
        dialog = TemplateDialog(self.window)
        if dialog.exec() != QDialog.Accepted or dialog.result_payload is None:
            return
        payload = dialog.result_payload
        next_id = max([t.get("id", 0) for t in config.TEMPLATES] + [0]) + 1
        payload["id"] = next_id
        config.TEMPLATES = list(config.TEMPLATES) + [payload]
        config.user_config["TEMPLATES"] = config.TEMPLATES
        config.save_config(config.user_config)
        self.refresh_templates()

    def apply_template_edit(self, original_template: dict, updated_template: dict):
        for index, template in enumerate(config.TEMPLATES):
            if template.get("id") == original_template.get("id"):
                updated_template["id"] = original_template.get("id")
                config.TEMPLATES[index] = updated_template
                config.user_config["TEMPLATES"] = config.TEMPLATES
                config.ACTIVE_TEMPLATES = [
                    updated_template["name"] if name == original_template["name"] else name
                    for name in config.ACTIVE_TEMPLATES
                ]
                config.user_config["ACTIVE_TEMPLATES"] = config.ACTIVE_TEMPLATES
                config.save_config(config.user_config)
                self.refresh_templates()
                return True
        return False

    def edit_template_dialog(self):
        dialog = TemplateManagerDialog(self.window, config.TEMPLATES, self.apply_template_edit)
        dialog.exec()

    def del_template_dialog(self):
        custom_templates = [template for template in config.TEMPLATES if template.get("id", 0) > 7]
        if not custom_templates:
            QMessageBox.information(self.window, "No Custom Templates", "There are no custom templates to delete.")
            return
        dialog = DeleteDialog(self.window, custom_templates)
        if dialog.exec() == QDialog.Accepted:
            self.refresh_templates()

    def open_settings_dialog(self):
        dialog = SettingsDialog(self.window, master=self)
        dialog.exec()

    def toggle_game_setting(self, setting_key: str, label: str) -> bool:
        loader = getattr(self, "native_hook_loader", None)
        if loader is None:
            dll_path = getattr(config, "NATIVE_HOOK_DLL_PATH", "") or None
            loader = NativeHookLoader(
                config.PROCESS_NAME,
                dll_path=dll_path,
                base_path=config.application_path,
            )

        try:
            if setting_key == "skip_chest_animation":
                toggled = loader.toggle_skip_chest_animation()
            elif setting_key == "auto_select_upgrades":
                toggled = loader.toggle_auto_select_upgrades()
            elif setting_key == "particle_opacity":
                toggled = loader.toggle_particles_opacity()
            else:
                self.log(f"[WAIT] Unsupported game setting toggle: {label}", tag="warning")
                return False
        except HookLoadError as exc:
            self.log(f"[WAIT] Could not toggle '{label}' live in the game. Details: {exc}", tag="warning")
            return False

        state_text = "ON" if toggled else "OFF"
        self.log(f"[+] {label}: {state_text}", tag="success")
        return True

    def setup_hotkeys(self):
        if keyboard:
            try:
                keyboard.unhook_all()
                keyboard.add_hotkey(config.HOTKEY, self.hotkey_toggle_scanning)
                keyboard.add_hotkey(config.PLAYER_STATS_RECORD_HOTKEY, self.hotkey_toggle_player_stats_recording)
                keyboard.add_hotkey(
                    config.TOGGLE_SKIP_CHEST_ANIMATION_HOTKEY,
                    self.hotkey_toggle_skip_chest_animation,
                )
                keyboard.add_hotkey(
                    config.TOGGLE_AUTO_SELECT_UPGRADES_HOTKEY,
                    self.hotkey_toggle_auto_select_upgrades,
                )
                keyboard.add_hotkey(
                    config.TOGGLE_PARTICLES_OPACITY_HOTKEY,
                    self.hotkey_toggle_particles_opacity,
                )
            except Exception as exc:
                self.log(f"[WAIT] Could not register hotkeys: {exc}", tag="warning")

    def hotkey_toggle_scanning(self):
        self.after(0, self.toggle_scan_event)

    def toggle_scan_event(self):
        if self.scanner_thread is None or not self.scanner_thread.is_alive():
            self.log(f"[WAIT] Press Start first, then press {config.HOTKEY.upper()} in game to begin scanning.", tag="warning")
            self.update_status_ui()
            return

        if not self.is_ready_to_start:
            self.log("[WAIT] Scanner is still connecting to the game. Try the hotkey again once it is ARMED.", tag="warning")
            self.update_status_ui()
            return

        if self.is_running:
            self.is_running = False
            self.scan_event.clear()
            self.log("[*] Scan paused. Press the scan hotkey again to resume.")
        else:
            self.is_running = True
            self.scan_event.set()
            self.log("[*] Scan started. Looking for selected target...")
        self.update_status_ui()

    def hotkey_toggle_player_stats_recording(self):
        self.after(0, self.toggle_player_stats_recording)

    def hotkey_toggle_skip_chest_animation(self):
        self.after(0, partial(self.toggle_game_setting, "skip_chest_animation", "Skip Chest Animation"))

    def hotkey_toggle_auto_select_upgrades(self):
        self.after(0, partial(self.toggle_game_setting, "auto_select_upgrades", "Auto Level-Up"))

    def hotkey_toggle_particles_opacity(self):
        self.after(0, partial(self.toggle_game_setting, "particle_opacity", "Particles Opacity"))

    def update_status_ui(self):
        if self.status_label is None or self.toggle_btn is None:
            return

        if self.scanner_thread and self.scanner_thread.is_alive():
            if self.is_running:
                status = "RUNNING"
            elif self.is_ready_to_start:
                status = "ARMED"
            else:
                status = "WAITING FOR GAME"
            self.status_label.setText(f"Status: {status}")
            self.toggle_btn.setText("Stop")
            self.toggle_btn.setStyleSheet(_button_state_stylesheet("#B91C1C", "#DC2626"))
        else:
            self.status_label.setText("Status: IDLE")
            self.toggle_btn.setText(f"Start")
            self.toggle_btn.setStyleSheet("")

    def animate_scanner_indicator(self):
        return None

    def _append_log(self, message, tag=None):
        if self.log_box is None:
            return

        def colored_html(part: str, color_tag: str | None) -> str:
            if color_tag:
                color = COLOR_MAP.get(str(color_tag).upper(), COLOR_MAP["DEFAULT"])
                return f'<span style="color:{color}">{html.escape(str(part))}</span>'
            return html.escape(str(part))

        if isinstance(tag, list):
            line = "".join(colored_html(part, sub_tag) for part, sub_tag in zip(message, tag))
        elif tag:
            line = colored_html(message, tag)
        else:
            line = html.escape(str(message))

        self.log_box.moveCursor(QTextCursor.End)
        self.log_box.insertHtml(line + "<br>")
        self.log_box.moveCursor(QTextCursor.End)

    def log(self, message, tag=None):
        if not hasattr(self, "_invoker"):
            return
        self.after(0, lambda m=message, t=tag: self._append_log(m, t))

    def toggle_main_loop(self):
        if self.scanner_thread is None or not self.scanner_thread.is_alive():
            self.log(f"\n[*] Starting auto-reroll monitor in {config.EVALUATION_MODE.upper()} mode...")

            if config.EVALUATION_MODE == "templates":
                self.active_templates = self._get_selected_template_names()
                if not self.active_templates:
                    self.log("[-] Error: You must select at least one template!", tag="error")
                    return
                colored_parts = ["[*] Active profiles: "]
                colored_tags = [None]
                for index, name in enumerate(self.active_templates):
                    color_tag = "BLUE"
                    for template in config.TEMPLATES:
                        if template["name"] == name:
                            color_tag = template.get("color", "BLUE").upper()
                            break
                    colored_parts.append(name)
                    colored_tags.append(color_tag)
                    if index < len(self.active_templates) - 1:
                        colored_parts.append(", ")
                        colored_tags.append(None)
                self.log(colored_parts, tag=colored_tags)
                self.template_stats = {name: {"rerolls_since_last": 0, "history": []} for name in self.active_templates}
            else:
                active_tiers = config.SCORES_SYSTEM.get("active_tiers", [])
                if not active_tiers:
                    self.log("[-] Error: No active tiers selected in Scores mode!", tag="error")
                    return
                self.log(f"[*] Active Tiers: {', '.join(active_tiers)}")
                self.template_stats = {name: {"rerolls_since_last": 0, "history": []} for name in active_tiers}

            self.session_start_time = time.time()
            self.session_rerolls = 0
            self.best_map_stats = None
            self.best_map_score = -1
            self.worst_map_stats = None
            self.worst_map_score = float("inf")
            self.refresh_stats_ui()

            self.is_running = False
            self.is_ready_to_start = False
            self.scan_event.clear()
            self.stop_event.clear()
            self.scanner_thread = threading.Thread(target=self.background_loop, daemon=True)
            self.scanner_thread.start()
            self._sync_runtime_filters()
            self.update_status_ui()
        else:
            self.stop_event.set()
            self.scan_event.set()
            self.is_running = False
            self.is_ready_to_start = False
            self.log("\n[*] Stopping auto-reroll monitor...")
            self.after(500, self.update_status_ui)

    @staticmethod
    def format_stats(stats: dict) -> str:
        shady = stats.get("Shady Guy", 0)
        moai = stats.get("Moais", 0)
        microwaves = logic.normalize_microwaves(stats.get("Microwaves"))
        boss = stats.get("Boss Curses", 0)
        magnet = stats.get("Magnet Shrines", 0)
        return (
            f"Shady: {shady}, Moai: {moai}, Microwaves: {microwaves}, "
            f"Boss: {boss}, Magnet: {magnet}, "
            f"Score: {logic.calculate_score(stats, config.SCORES_SYSTEM):.1f}"
        )

    @staticmethod
    def calculate_map_score(stats: dict) -> float:
        return logic.calculate_score(stats, config.SCORES_SYSTEM)

    def evaluate_candidate(self, stats: dict) -> dict | None:
        if config.EVALUATION_MODE == "templates":
            return logic.find_matching_template(stats, self.active_templates, config.TEMPLATES)
        return logic.evaluate_map_by_scores(stats, config.SCORES_SYSTEM)

    def update_timer(self):
        if self._is_shutting_down:
            return

        if self.scanner_thread and self.scanner_thread.is_alive() and self.session_start_time:
            elapsed = int(time.time() - self.session_start_time)
            td = datetime.timedelta(seconds=elapsed)
            self.stats_time_label.setText(f"Session Time: {td}")
            if elapsed > 0 and self.session_rerolls > 0:
                rpm = (self.session_rerolls / elapsed) * 60
                self.stats_rpm_label.setText(f"Rerolls per Minute (RPM): {rpm:.1f}")

        if self.player_stats_vod_recorder.is_recording:
            self.refresh_player_stats_timeline_ui(update_slider=False)

        self.after(1000, self.update_timer)

    def update_player_stats_timer(self):
        if self._is_shutting_down:
            return

        recording_state_action = self._sync_player_stats_recording_run_state()
        should_refresh = self._is_live_stats_tab_active() or self.player_stats_vod_recorder.is_recording
        if should_refresh:
            status_text = (
                "Live player stats"
                if recording_state_action != "stopped"
                else "Live player stats (recording auto-stopped after run end)"
            )
            self.refresh_live_player_stats_now(status_text=status_text)

        self.after(PLAYER_STATS_REFRESH_MS, self.update_player_stats_timer)

    def _get_player_stats_client(self) -> PlayerStatsClient:
        if self.player_stats_client is None:
            self.player_stats_client = PlayerStatsClient(config.PROCESS_NAME)
        return self.player_stats_client

    def read_player_stats_only(self):
        client = self._get_player_stats_client()
        owner_stats = client.resolve_owner_stats()
        return client.get_player_stats(owner_stats), owner_stats

    def read_passive_items_only(self, owner_stats: int | None = None):
        client = self._get_player_stats_client()
        return client.get_passive_items(owner_stats)

    def read_player_stats(self):
        stats, owner_stats = self.read_player_stats_only()
        return stats, self.read_passive_items_only(owner_stats)

    def read_player_stats_recording_state(self):
        if self.player_stats_game_data_client is None:
            self.player_stats_game_data_client = GameDataClient(config.PROCESS_NAME)
        return self.player_stats_game_data_client.get_map_generation_state()

    def read_player_stats_recording_seed(self) -> int | None:
        return self.read_player_stats_recording_state().map_seed

    def _reset_live_player_stats_ui(self, status_text: str, *, items_text: str = "--") -> None:
        _set_text(self.player_stats_status_label, status_text)
        for label in self.player_stats_rows.values():
            _set_text(label, "--")
        self.player_stats_items_expanded = False
        self._update_items_section("live", items_text=items_text)
        _set_text(self.player_stats_chests_per_minute_label, "Average chests/min: --")
        _set_text(self.player_stats_in_game_time_label, "In-Game Time: --")
        _set_text(self.player_stats_mob_kills_label, "Mob Kills: --")
        _set_text(self.player_stats_level_label, "Level: --")
        _set_text(self.player_stats_new_items_label, "Live snapshot")
        self._set_stage_summary_labels(self.player_stats_stage_summary_labels, None)
        self.player_stats_weapon_signature = None
        self.display_weapon_cards(
            (),
            scope="live",
            status_text="Waiting for weapon data...",
        )

    def _read_live_player_stats_data(self):
        stats, owner_stats = self.read_player_stats_only()
        items = ()
        items_available = True
        weapons: tuple[WeaponSnapshot, ...] = ()
        weapons_available = False
        run_timer_seconds = None
        stage_timer_seconds = None
        mob_kills = None
        player_level = None
        map_seed = None
        stage_ptr = 0
        try:
            items = self.read_passive_items_only(owner_stats)
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            items_available = False
        except Exception:
            items_available = False
        if self.player_stats_vod_recorder.is_recording or self._is_live_stats_tab_active():
            try:
                client = self._get_player_stats_client()
                weapons = client.get_live_weapons(owner_stats)
                weapons_available = True
            except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
                weapons = ()
                weapons_available = False
            except Exception:
                weapons = ()
                weapons_available = False
        try:
            client = self._get_player_stats_client()
            run_timer_seconds = client.get_run_timer()
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            run_timer_seconds = None
        except Exception:
            run_timer_seconds = None
        try:
            client = self._get_player_stats_client()
            stage_timer_seconds = client.get_stage_timer()
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            stage_timer_seconds = None
        except Exception:
            stage_timer_seconds = None
        try:
            client = self._get_player_stats_client()
            mob_kills = client.get_killed_mobs()
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            mob_kills = None
        except Exception:
            mob_kills = None
        try:
            client = self._get_player_stats_client()
            player_level = client.get_player_level(owner_stats)
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            player_level = None
        except Exception:
            player_level = None
        try:
            recording_state = self.read_player_stats_recording_state()
            map_seed = recording_state.map_seed
            stage_ptr = recording_state.current_stage_ptr
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            self.close_player_stats_game_data_client()
            map_seed = None
            stage_ptr = 0
        except Exception:
            self.close_player_stats_game_data_client()
            map_seed = None
            stage_ptr = 0
        return (
            stats,
            items,
            items_available,
            weapons,
            weapons_available,
            run_timer_seconds,
            stage_timer_seconds,
            mob_kills,
            player_level,
            map_seed,
            stage_ptr,
        )

    def refresh_live_player_stats_now(
        self,
        *,
        status_text: str = "Live player stats",
        waiting_status_text: str = "Waiting for game/player stats...",
        unavailable_status_prefix: str = "Player stats unavailable",
    ) -> bool:
        try:
            (
                stats,
                items,
                items_available,
                weapons,
                weapons_available,
                run_timer_seconds,
                stage_timer_seconds,
                mob_kills,
                player_level,
                map_seed,
                stage_ptr,
            ) = self._read_live_player_stats_data()
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            self.close_player_stats_client()
            self._reset_live_player_stats_ui(waiting_status_text)
            return False
        except Exception as exc:
            self.close_player_stats_client()
            self._reset_live_player_stats_ui(f"{unavailable_status_prefix}: {exc}")
            return False

        chests_per_minute = self.calculate_player_chests_per_minute(stats)
        items_text = None if items_available else "Items unavailable"
        is_live_tab_active = self._is_live_stats_tab_active()

        if self.player_stats_vod_recorder.should_capture():
            snapshot = self.player_stats_vod_recorder.capture(
                stats,
                items if items_available else (),
                weapons if weapons_available else (),
                chests_per_minute=chests_per_minute,
                game_time_seconds=run_timer_seconds,
                mob_kills=mob_kills,
                player_level=player_level,
                map_seed=map_seed,
                stage_ptr=stage_ptr,
                stage_time_seconds=stage_timer_seconds,
            )
            self.player_stats_vod_snapshots.append(snapshot)
            self.player_stats_selected_snapshot_index = len(self.player_stats_vod_snapshots) - 1
            self.refresh_player_stats_timeline_ui()
            self._refresh_vods_list_if_visible()
            if is_live_tab_active:
                self.display_player_stats_snapshot(snapshot, items_text=items_text)
            return True

        if is_live_tab_active:
            if self.player_stats_vod_recorder.is_recording:
                self.display_player_stats(
                    stats,
                    items,
                    weapons=weapons if weapons_available else (),
                    weapons_available=weapons_available,
                    status_text="Live player stats (recording)",
                    chests_per_minute=chests_per_minute,
                    items_text=items_text,
                    game_time_seconds=run_timer_seconds,
                    mob_kills=mob_kills,
                    player_level=player_level,
                    stage_summary_rows=self.build_stage_summary(self.player_stats_vod_snapshots),
                )
                return True

            self.player_stats_selected_snapshot_index = None
            self.display_player_stats(
                stats,
                items,
                weapons=weapons if weapons_available else (),
                weapons_available=weapons_available,
                status_text=status_text,
                chests_per_minute=chests_per_minute,
                items_text=items_text,
                game_time_seconds=run_timer_seconds,
                mob_kills=mob_kills,
                player_level=player_level,
                stage_summary_rows=None,
            )
        return True

    def display_player_stats(
        self,
        stats,
        items=(),
        *,
        weapons=(),
        weapons_available: bool = True,
        status_text: str | None = None,
        chests_per_minute: float | None = None,
        items_text: str | None = None,
        game_time_seconds: float | None = None,
        mob_kills: int | None = None,
        player_level: int | None = None,
        new_items_text: str | None = None,
        stage_summary_rows: list[dict[str, str]] | None = None,
    ):
        if status_text:
            _set_text(self.player_stats_status_label, status_text)
        for label, stat in stats.items():
            value_label = self.player_stats_rows.get(label)
            if value_label is not None:
                _set_text(value_label, stat.display_value)
        self._update_items_section("live", items, items_text=items_text)
        if chests_per_minute is None:
            chests_per_minute = self.calculate_player_chests_per_minute(stats)
        _set_text(
            self.player_stats_chests_per_minute_label,
            self.format_chests_per_minute(chests_per_minute),
        )
        _set_text(
            self.player_stats_in_game_time_label,
            self.format_in_game_time(game_time_seconds),
        )
        _set_text(
            self.player_stats_mob_kills_label,
            self.format_mob_kills(mob_kills),
        )
        _set_text(
            self.player_stats_level_label,
            self.format_player_level(player_level),
        )
        if new_items_text is not None:
            _set_text(self.player_stats_new_items_label, new_items_text)
        else:
            _set_text(self.player_stats_new_items_label, "Live snapshot")
        self._set_stage_summary_labels(self.player_stats_stage_summary_labels, stage_summary_rows)
        self.display_weapon_cards(
            weapons if weapons_available else (),
            scope="live",
            status_text=None if weapons_available else "Weapons unavailable",
        )

    def display_player_stats_snapshot(self, snapshot, *, items_text: str | None = None):
        index = self.player_stats_vod_snapshots.index(snapshot) + 1
        total = len(self.player_stats_vod_snapshots)
        self.display_player_stats(
            snapshot.stats,
            snapshot.items,
            weapons=getattr(snapshot, "weapons", ()),
            status_text=(
                f"Recorded snapshot {index}/{total} at {snapshot.time_label}"
                f" | {self.format_in_game_time(snapshot.game_time_seconds)}"
            ),
            chests_per_minute=self.resolve_snapshot_chests_per_minute(snapshot),
            items_text=items_text,
            game_time_seconds=snapshot.game_time_seconds,
            mob_kills=getattr(snapshot, "mob_kills", None),
            player_level=getattr(snapshot, "player_level", None),
            new_items_text=self.format_snapshot_new_items(
                self._previous_player_stats_snapshot(snapshot),
                snapshot,
            ),
            stage_summary_rows=self.build_stage_summary(
                self.player_stats_vod_snapshots[:index]
            ),
        )

    def _previous_player_stats_snapshot(self, snapshot):
        try:
            index = self.player_stats_vod_snapshots.index(snapshot)
        except ValueError:
            return None
        if index <= 0:
            return None
        return self.player_stats_vod_snapshots[index - 1]

    def toggle_player_stats_recording(self):
        if self.player_stats_vod_recorder.is_recording:
            self._stop_player_stats_recording(log_message="[*] Player stats recording stopped.")
        else:
            state = self._read_player_stats_recording_state_safe()
            seed = state.map_seed if state is not None else None
            stage_ptr = state.current_stage_ptr if state is not None else 0
            run_time_seconds = self._read_player_stats_recording_run_timer_safe()
            vod_path = self._start_player_stats_recording(
                seed=seed,
                stage_ptr=stage_ptr,
                run_time_seconds=run_time_seconds,
            )
            self.log(f"[*] Player stats recording started: {vod_path.name}", tag="success")
            self.refresh_live_player_stats_now(
                waiting_status_text="Recording stats; waiting for game/player stats...",
                unavailable_status_prefix="Recording stats; player stats unavailable",
            )
            self._refresh_vods_list_if_visible()

        self.refresh_player_stats_timeline_ui()

    def _read_player_stats_recording_seed_safe(self) -> int | None:
        try:
            return self.read_player_stats_recording_seed()
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            self.close_player_stats_game_data_client()
            return None
        except Exception:
            self.close_player_stats_game_data_client()
            return None

    def _read_player_stats_recording_state_safe(self):
        try:
            return self.read_player_stats_recording_state()
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            self.close_player_stats_game_data_client()
            return None
        except Exception:
            self.close_player_stats_game_data_client()
            return None

    def _read_player_stats_recording_run_timer_safe(self) -> float | None:
        try:
            return self._get_player_stats_client().get_run_timer()
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            self.close_player_stats_client()
            return None
        except Exception:
            self.close_player_stats_client()
            return None

    @staticmethod
    def _seed_change_looks_like_same_run(
        previous_run_time_seconds: float | None,
        current_run_time_seconds: float | None,
    ) -> bool:
        if previous_run_time_seconds is None or current_run_time_seconds is None:
            return False
        return (
            current_run_time_seconds + PLAYER_STATS_RUN_TIMER_RESET_TOLERANCE_SECONDS
            >= previous_run_time_seconds
        )

    @staticmethod
    def _stage_change_looks_like_same_run(
        previous_stage_ptr: int,
        current_stage_ptr: int,
        previous_run_time_seconds: float | None,
        current_run_time_seconds: float | None,
    ) -> bool:
        if (
            not previous_stage_ptr
            or not current_stage_ptr
            or previous_stage_ptr == current_stage_ptr
        ):
            return False
        return MegabonkApp._seed_change_looks_like_same_run(
            previous_run_time_seconds,
            current_run_time_seconds,
        )

    def _start_player_stats_recording(
        self,
        *,
        seed: int | None = None,
        stage_ptr: int = 0,
        run_time_seconds: float | None = None,
    ):
        vod_path = self.player_stats_vod_recorder.start(seed=seed)
        self.player_stats_vod_snapshots = []
        self.player_stats_selected_snapshot_index = None
        self.player_stats_recording_seed = seed
        self.player_stats_recording_stage_ptr = stage_ptr
        self.player_stats_recording_seed_missing_since = None
        self.player_stats_recording_run_time_seconds = run_time_seconds
        return vod_path

    def _stop_player_stats_recording(
        self,
        *,
        log_message: str | None = None,
        log_tag: str | None = None,
        refresh_live_stats: bool = True,
    ) -> None:
        self.player_stats_vod_recorder.stop()
        self.player_stats_vod_snapshots = []
        self.player_stats_selected_snapshot_index = None
        self.player_stats_recording_seed = None
        self.player_stats_recording_stage_ptr = 0
        self.player_stats_recording_seed_missing_since = None
        self.player_stats_recording_run_time_seconds = None
        self.close_player_stats_game_data_client()
        if log_message:
            self.log(log_message, tag=log_tag)
        if refresh_live_stats:
            self.refresh_live_player_stats_now()
        self._refresh_vods_list_if_visible()

    def _sync_player_stats_recording_run_state(self) -> str | None:
        if not self.player_stats_vod_recorder.is_recording:
            return None

        now = time.monotonic()
        current_state = self._read_player_stats_recording_state_safe()
        current_seed = current_state.map_seed if current_state is not None else None
        current_stage_ptr = (
            current_state.current_stage_ptr if current_state is not None else 0
        )
        current_run_time_seconds = self._read_player_stats_recording_run_timer_safe()
        if current_seed is None:
            if self.player_stats_recording_seed_missing_since is None:
                self.player_stats_recording_seed_missing_since = now
                return None
            if now - self.player_stats_recording_seed_missing_since < PLAYER_STATS_RECORDING_SEED_GRACE_SECONDS:
                return None
            self._stop_player_stats_recording(
                log_message="[*] Player stats recording auto-stopped: run seed disappeared.",
                log_tag="warning",
                refresh_live_stats=False,
            )
            self.refresh_player_stats_timeline_ui()
            return "stopped"

        self.player_stats_recording_seed_missing_since = None
        if self.player_stats_recording_seed is None:
            self.player_stats_recording_seed = current_seed
            self.player_stats_recording_stage_ptr = current_stage_ptr
            self.player_stats_recording_run_time_seconds = current_run_time_seconds
            return None
        if (
            current_seed == self.player_stats_recording_seed
            and current_stage_ptr == self.player_stats_recording_stage_ptr
        ):
            self.player_stats_recording_run_time_seconds = current_run_time_seconds
            return None

        previous_seed = self.player_stats_recording_seed
        previous_stage_ptr = self.player_stats_recording_stage_ptr
        previous_run_time_seconds = self.player_stats_recording_run_time_seconds
        if self._stage_change_looks_like_same_run(
            previous_stage_ptr,
            current_stage_ptr,
            previous_run_time_seconds,
            current_run_time_seconds,
        ):
            self.player_stats_recording_seed = current_seed
            self.player_stats_recording_stage_ptr = current_stage_ptr
            self.player_stats_recording_run_time_seconds = current_run_time_seconds
            return None
        if self._seed_change_looks_like_same_run(
            previous_run_time_seconds,
            current_run_time_seconds,
        ):
            self.player_stats_recording_seed = current_seed
            self.player_stats_recording_stage_ptr = current_stage_ptr
            self.player_stats_recording_run_time_seconds = current_run_time_seconds
            return None

        self._stop_player_stats_recording(refresh_live_stats=False)
        vod_path = self._start_player_stats_recording(
            seed=current_seed,
            stage_ptr=current_stage_ptr,
            run_time_seconds=current_run_time_seconds,
        )
        self.log(
            f"[*] Player stats recording auto-split: seed {previous_seed} -> {current_seed}; new file {vod_path.name}",
            tag="success",
        )
        self.refresh_player_stats_timeline_ui()
        return "split"

    def on_player_stats_slider_changed(self, value):
        snapshot_count = len(self.player_stats_vod_snapshots)
        if snapshot_count == 0:
            return
        index = min(max(int(round(float(value))), 0), snapshot_count - 1)
        if self.player_stats_selected_snapshot_index == index:
            return
        self.player_stats_selected_snapshot_index = index
        self.display_player_stats_snapshot(self.player_stats_vod_snapshots[index])
        self.refresh_player_stats_timeline_ui(update_slider=False)

    def refresh_player_stats_timeline_ui(self, *, update_slider: bool = True):
        snapshot_count = len(self.player_stats_vod_snapshots)

        if self.player_stats_vod_recorder.is_recording:
            self.player_stats_record_btn.setText("Stop Recording")
            self.player_stats_record_btn.setStyleSheet(
                _button_state_stylesheet(
                    PLAYER_STATS_ACTIVE_BUTTON_COLOR,
                    PLAYER_STATS_ACTIVE_BUTTON_HOVER_COLOR,
                )
            )
        else:
            self.player_stats_record_btn.setText(f"Start Recording ({config.PLAYER_STATS_RECORD_HOTKEY.upper()})")
            self.player_stats_record_btn.setStyleSheet(
                _button_state_stylesheet(
                    PLAYER_STATS_INACTIVE_BUTTON_COLOR,
                    PLAYER_STATS_INACTIVE_BUTTON_HOVER_COLOR,
                )
            )

        if self.player_stats_vod_recorder.is_recording and snapshot_count:
            self.player_stats_slider.setEnabled(True)
            self.player_stats_slider.setMaximum(max(snapshot_count - 1, 1))
            if update_slider:
                index = self.player_stats_selected_snapshot_index
                self.player_stats_slider.setValue(index if index is not None else snapshot_count - 1)
        else:
            self.player_stats_slider.setEnabled(False)
            self.player_stats_slider.setMaximum(1)
            self.player_stats_slider.setValue(0)

        if self.player_stats_vod_recorder.is_recording:
            prefix = f"Recording {self.player_stats_vod_recorder.elapsed_label()} | "
            if snapshot_count:
                selected = self.player_stats_selected_snapshot_index
                mode = self.player_stats_vod_snapshots[selected].time_label if selected is not None else "--"
                self.player_stats_timeline_label.setText(f"{prefix}{snapshot_count} snapshots | {mode}")
            else:
                self.player_stats_timeline_label.setText(f"{prefix}No snapshots")
        else:
            self.player_stats_timeline_label.setText("Live stats")

        if self.player_stats_vod_recorder.is_recording and snapshot_count:
            first = self.player_stats_vod_snapshots[0].time_label
            last = self.player_stats_vod_snapshots[-1].time_label
            selected = self.player_stats_selected_snapshot_index
            current = self.player_stats_vod_snapshots[selected].time_label if selected is not None else "--"
            self.player_stats_slider_time_label.setText(f"Timeline: {first} - {last} | Selected: {current}")
        elif self.player_stats_vod_recorder.is_recording:
            self.player_stats_slider_time_label.setText(
                f"Timeline: recording {self.player_stats_vod_recorder.elapsed_label()} | waiting for first snapshot"
            )
        else:
            self.player_stats_slider_time_label.setText("Timeline: live stats")

    def refresh_vods_list(self):
        if self.vods_list_frame is None:
            return

        vods = list_vods()
        selected_path = self.loaded_vod.metadata.path if self.loaded_vod is not None else None
        signature = (
            str(selected_path) if selected_path is not None else "",
            tuple((str(vod.path), vod.name, vod.snapshot_count, vod.duration_seconds) for vod in vods),
        )
        if self.vods_list_signature == signature:
            return

        self.vods_list_frame.blockSignals(True)
        self.vods_list_frame.clear()
        if not vods:
            item = QListWidgetItem("No saved recordings")
            item.setFlags(Qt.NoItemFlags)
            self.vods_list_frame.addItem(item)
            self.vods_list_frame.blockSignals(False)
            self.vods_list_signature = signature
            return

        selected_row = None
        for row, vod in enumerate(vods):
            duration = self.format_duration(vod.duration_seconds)
            item = QListWidgetItem(f"{vod.name}\n{vod.snapshot_count} snapshots | {duration}")
            item.setData(Qt.UserRole, str(vod.path))
            self.vods_list_frame.addItem(item)
            if selected_path == vod.path:
                selected_row = row
        if selected_row is not None:
            self.vods_list_frame.setCurrentRow(selected_row)
        self.vods_list_frame.blockSignals(False)
        self.vods_list_signature = signature

    def _on_vod_selection_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None):
        if current is None:
            return
        path_str = current.data(Qt.UserRole)
        if path_str:
            self.load_selected_vod(path_str)

    def load_selected_vod(self, path):
        path = Path(path)
        try:
            self.loaded_vod = load_vod(path)
        except Exception as exc:
            self.loaded_vod = None
            self.loaded_vod_snapshot_index = None
            _set_text(self.vods_status_label, f"Could not load recording: {exc}")
            return

        self.loaded_vod_snapshot_index = 0 if self.loaded_vod.snapshots else None
        _clear_text_input(self.vods_name_entry)
        _set_text_input(self.vods_name_entry, self.loaded_vod.metadata.name)
        self.refresh_loaded_vod_ui()
        self.refresh_vods_list()

    def refresh_loaded_vod_ui(self, *, update_slider: bool = True):
        if self.loaded_vod is None:
            return

        snapshot_count = len(self.loaded_vod.snapshots)
        metadata = self.loaded_vod.metadata
        duration = self.format_duration(metadata.duration_seconds)
        _set_text(self.vods_status_label, f"{metadata.created_label} | {snapshot_count} snapshots | {duration}")

        if snapshot_count:
            self.vods_slider.setEnabled(True)
            self.vods_slider.setMaximum(max(snapshot_count - 1, 1))
            if update_slider:
                self.vods_slider.setValue(self.loaded_vod_snapshot_index or 0)
            self.display_loaded_vod_snapshot(self.loaded_vod_snapshot_index or 0)
        else:
            self.vods_slider.setEnabled(False)
            self.vods_slider.setMaximum(1)
            self.vods_slider.setValue(0)
            for label in self.vods_rows.values():
                _set_text(label, "--")
            _set_text(self.vods_slider_time_label, "Timeline: --")
            self.vods_items_expanded = False
            self._update_items_section("vod", items_text="--")
            _set_text(self.vods_chests_per_minute_label, "Average chests/min: --")
            _set_text(self.vods_in_game_time_label, "In-Game Time: --")
            _set_text(self.vods_mob_kills_label, "Mob Kills: --")
            _set_text(self.vods_level_label, "Level: --")
            _set_text(self.vods_new_items_label, "No previous snapshot")
            self._set_stage_summary_labels(self.vods_stage_summary_labels, None)
            self.vods_weapon_signature = None
            self.display_weapon_cards((), scope="vod", status_text="No weapon data in this recording")

    def display_loaded_vod_snapshot(self, index: int):
        if self.loaded_vod is None or not self.loaded_vod.snapshots:
            return
        index = min(max(index, 0), len(self.loaded_vod.snapshots) - 1)
        self.loaded_vod_snapshot_index = index
        snapshot = self.loaded_vod.snapshots[index]
        _set_text(
            self.vods_status_label,
            (
                f"{self.loaded_vod.metadata.name} | {index + 1}/{len(self.loaded_vod.snapshots)}"
                f" at {snapshot.time_label} | {self.format_in_game_time(snapshot.game_time_seconds)}"
            ),
        )
        first = self.loaded_vod.snapshots[0].time_label
        last = self.loaded_vod.snapshots[-1].time_label
        _set_text(self.vods_slider_time_label, f"Timeline: {first} - {last} | Selected: {snapshot.time_label}")
        for spec_group in PLAYER_STAT_GROUPS:
            for spec in spec_group:
                value_label = self.vods_rows.get(spec.label)
                if value_label is not None:
                    stat = snapshot.stats.get(spec.label)
                    _set_text(value_label, stat.display_value if stat is not None else "--")
        self._update_items_section("vod", snapshot.items)
        _set_text(
            self.vods_chests_per_minute_label,
            self.format_chests_per_minute(self.resolve_snapshot_chests_per_minute(snapshot)),
        )
        _set_text(
            self.vods_in_game_time_label,
            self.format_in_game_time(snapshot.game_time_seconds),
        )
        _set_text(
            self.vods_mob_kills_label,
            self.format_mob_kills(getattr(snapshot, "mob_kills", None)),
        )
        _set_text(
            self.vods_level_label,
            self.format_player_level(getattr(snapshot, "player_level", None)),
        )
        self._set_stage_summary_labels(
            self.vods_stage_summary_labels,
            self.build_stage_summary(self.loaded_vod.snapshots[: index + 1]),
        )
        previous_snapshot = self.loaded_vod.snapshots[index - 1] if index > 0 else None
        _set_text(
            self.vods_new_items_label,
            self.format_snapshot_new_items(previous_snapshot, snapshot),
        )
        self.display_weapon_cards(getattr(snapshot, "weapons", ()), scope="vod")

    def on_vods_slider_changed(self, value):
        if self.loaded_vod is None or not self.loaded_vod.snapshots:
            return
        index = min(max(int(round(float(value))), 0), len(self.loaded_vod.snapshots) - 1)
        if self.loaded_vod_snapshot_index == index:
            return
        self.display_loaded_vod_snapshot(index)

    def rename_selected_vod(self):
        if self.loaded_vod is None or self.vods_name_entry is None:
            return
        new_name = _read_text(self.vods_name_entry).strip()
        try:
            metadata = rename_vod(self.loaded_vod.metadata.path, new_name)
            self.loaded_vod = load_vod(metadata.path)
        except Exception as exc:
            _set_text(self.vods_status_label, f"Could not rename recording: {exc}")
            return
        self.refresh_loaded_vod_ui(update_slider=False)
        self.refresh_vods_list()

    def _clear_loaded_vod_selection(self) -> None:
        self.loaded_vod = None
        self.loaded_vod_snapshot_index = None
        _clear_text_input(self.vods_name_entry)
        _set_text(self.vods_status_label, "Select a recording")
        self.vods_slider.setEnabled(False)
        self.vods_slider.setMaximum(1)
        self.vods_slider.setValue(0)
        _set_text(self.vods_slider_time_label, "Timeline: --")
        for label in self.vods_rows.values():
            _set_text(label, "--")
        self.vods_items_expanded = False
        self._update_items_section("vod", items_text="--")
        _set_text(self.vods_chests_per_minute_label, "Average chests/min: --")
        _set_text(self.vods_in_game_time_label, "In-Game Time: --")
        _set_text(self.vods_mob_kills_label, "Mob Kills: --")
        _set_text(self.vods_level_label, "Level: --")
        _set_text(self.vods_new_items_label, "No previous snapshot")
        self._set_stage_summary_labels(self.vods_stage_summary_labels, None)
        self.vods_weapon_signature = None
        self.display_weapon_cards((), scope="vod", status_text="Select a recording")

    def cleanup_recordings_by_snapshot_count(self):
        dialog = CleanupRecordingsDialog(self.window)
        if dialog.exec() != QDialog.Accepted or dialog.threshold is None:
            return

        selected_path = self.loaded_vod.metadata.path if self.loaded_vod is not None else None
        try:
            removed = delete_vods_below_snapshot_count(dialog.threshold)
        except Exception as exc:
            _set_text(self.vods_status_label, f"Could not clean recordings: {exc}")
            return

        if selected_path is not None and not selected_path.exists():
            self._clear_loaded_vod_selection()

        self.refresh_vods_list()
        self.log(f"[*] Removed {removed} recordings with snapshot count below {dialog.threshold}.", tag="success")

    def delete_selected_vod(self):
        if self.loaded_vod is None:
            return
        dialog = ConfirmDeleteRecordingDialog(self.window, self.loaded_vod.metadata.name)
        dialog.exec()
        if not dialog.result:
            return
        path = self.loaded_vod.metadata.path
        try:
            delete_vod(path)
        except Exception as exc:
            _set_text(self.vods_status_label, f"Could not delete recording: {exc}")
            return
        self._clear_loaded_vod_selection()
        self.refresh_vods_list()

    def toggle_player_items_expanded(self) -> None:
        self.player_stats_items_expanded = not self.player_stats_items_expanded
        self._update_items_section(
            "live",
            self.player_stats_items_current,
            items_text=self.player_stats_items_text_current,
        )

    def toggle_vod_items_expanded(self) -> None:
        self.vods_items_expanded = not self.vods_items_expanded
        self._update_items_section(
            "vod",
            self.vods_items_current,
            items_text=self.vods_items_text_current,
        )

    def on_items_sort_changed(self, scope: str) -> None:
        prefix = self._scope_prefix(scope)
        combo = self.__dict__.get(f"{prefix}_items_sort_combo")
        mode = ITEM_SORT_DEFAULT
        if combo is not None and hasattr(combo, "currentData"):
            mode = combo.currentData() or ITEM_SORT_DEFAULT
        setattr(self, f"{prefix}_items_sort_mode", mode)
        self._update_items_section(
            scope,
            self.__dict__.get(f"{prefix}_items_current", ()),
            items_text=self.__dict__.get(f"{prefix}_items_text_current"),
        )

    def _update_items_section(self, scope: str, items=(), *, items_text: str | None = None) -> None:
        prefix = self._scope_prefix(scope)
        group = self.__dict__.get(f"{prefix}_items_group")
        label = self.__dict__.get(f"{prefix}_items_label")
        button = self.__dict__.get(f"{prefix}_items_toggle_btn")
        sort_combo = self.__dict__.get(f"{prefix}_items_sort_combo")
        expanded = bool(self.__dict__.get(f"{prefix}_items_expanded", False))
        setattr(self, f"{prefix}_items_current", tuple(items or ()))
        setattr(self, f"{prefix}_items_text_current", items_text)

        if label is None:
            return

        if items_text is not None:
            self._set_items_group_title(group, None)
            _set_items_text(label, items_text=items_text)
            if button is not None:
                button.setVisible(False)
            if sort_combo is not None:
                sort_combo.setEnabled(False)
            return

        items = tuple(items or ())
        self._set_items_group_title(group, self._item_total_count(items))
        sorted_items = self.sort_items_for_display(
            items,
            self.__dict__.get(f"{prefix}_items_sort_mode", ITEM_SORT_DEFAULT),
        )
        preview_items, has_more = self._items_preview(sorted_items)
        visible_items = sorted_items if expanded or not has_more else preview_items
        if sort_combo is not None:
            sort_combo.setEnabled(bool(items))
        if hasattr(label, "setTextFormat"):
            text = self.format_items_rich_text(visible_items)
            if has_more and not expanded:
                text = f'{text} <span style="color:#98A7BA;">...</span>'
            label.setText(text)
        else:
            text = self.format_items(visible_items)
            if has_more and not expanded:
                text = f"{text} ..."
            _set_text(label, text)

        if button is not None:
            button.setVisible(has_more)
            button.setText("Show less" if expanded and has_more else "Show all")

    @classmethod
    def _item_total_count(cls, items) -> int:
        return sum(cls._item_counts(items).values())

    @staticmethod
    def _set_items_group_title(group, total_count: int | None) -> None:
        if group is None or not hasattr(group, "setTitle"):
            return
        title = "Items" if total_count is None else f"Items ({total_count} total)"
        group.setTitle(title)

    @classmethod
    def sort_items_for_display(cls, items, mode: str | None) -> tuple[str, ...]:
        items = tuple(items or ())
        if mode == ITEM_SORT_DEFAULT or not items:
            return items
        reverse = mode == ITEM_SORT_RARITY_DESC
        if mode not in (ITEM_SORT_RARITY_ASC, ITEM_SORT_RARITY_DESC):
            return items

        def sort_key(entry) -> tuple[int, int]:
            index, item = entry
            rarity_rank = cls._item_rarity_rank(str(item))
            return (-rarity_rank if reverse else rarity_rank, index)

        return tuple(item for _index, item in sorted(enumerate(items), key=sort_key))

    @classmethod
    def _item_rarity_rank(cls, item_text: str) -> int:
        item_name, _suffix = cls._split_item_stack_suffix(item_text)
        display_name = cls._normalize_item_name_for_display(item_name)
        rarity_name = cls._normalize_item_name_for_rarity(display_name)
        rarity = ITEM_RARITY_BY_NAME.get(rarity_name)
        return ITEM_RARITY_SORT_ORDER.get(rarity, -1)

    @staticmethod
    def _items_preview(items) -> tuple[tuple[str, ...], bool]:
        items = tuple(items or ())
        if len(items) <= 1:
            return items, False

        preview: list[str] = []
        max_chars = 90
        current_length = 0
        for item in items:
            separator_length = 2 if preview else 0
            projected_length = current_length + separator_length + len(item)
            if preview and projected_length > max_chars:
                break
            preview.append(item)
            current_length = projected_length

        if not preview:
            preview.append(items[0])
        return tuple(preview), len(preview) < len(items)

    def display_weapon_cards(self, weapons, *, scope: str, status_text: str | None = None) -> None:
        prefix = self._scope_prefix(scope)
        layout_attr = f"{prefix}_weapons_layout"
        status_attr = f"{prefix}_weapons_status_label"
        cards_attr = f"{prefix}_weapon_cards"
        signature_attr = f"{prefix}_weapon_signature"

        layout = getattr(self, layout_attr, None)
        status_label = getattr(self, status_attr, None)
        if layout is None or status_label is None:
            return

        weapons = tuple(weapons or ())
        signature = self._weapon_signature(weapons)
        if getattr(self, signature_attr, None) == signature and status_text is None:
            return

        setattr(self, signature_attr, signature)
        _clear_layout(layout)
        setattr(self, cards_attr, [])

        if status_text is not None:
            _set_text(status_label, status_text)
        else:
            _set_text(status_label, "" if weapons else "No weapons available")

        if not weapons:
            return

        cards = []
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        for index, weapon in enumerate(weapons):
            card = self._build_weapon_card(weapon)
            grid.addWidget(card, index // 2, index % 2)
            cards.append(card)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        layout.addStretch(1)
        setattr(self, cards_attr, cards)

    def _build_weapon_card(self, weapon: WeaponSnapshot) -> QFrame:
        card = QFrame()
        card.setObjectName("StatCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        weapon_name_label = QLabel(weapon.name)
        weapon_name_label.setStyleSheet("font-size: 14px; font-weight: 700;")
        weapon_level_label = QLabel(f"Lv. {weapon.level}")
        weapon_level_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        weapon_level_label.setStyleSheet("font-size: 14px; font-weight: 700;")
        header_layout.addWidget(weapon_name_label, 1)
        header_layout.addWidget(weapon_level_label)
        layout.addLayout(header_layout)

        rows = QFormLayout()
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setVerticalSpacing(6)
        has_rows = False
        for stat_id in weapon.upgrade_stat_ids:
            stat = weapon.upgraded_stats.get(stat_id)
            if stat is None:
                continue
            value_label = QLabel(stat.display_value)
            value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            rows.addRow(stat.label, value_label)
            has_rows = True
        if has_rows:
            layout.addLayout(rows)
        else:
            layout.addWidget(QLabel("No upgraded stats decoded"))
        return card

    @staticmethod
    def _weapon_signature(weapons) -> tuple:
        return tuple(
            (
                weapon.weapon_id,
                weapon.level,
                tuple(
                    (stat_id, weapon.upgraded_stats[stat_id].display_value)
                    for stat_id in weapon.upgrade_stat_ids
                    if stat_id in weapon.upgraded_stats
                ),
            )
            for weapon in weapons
        )

    @staticmethod
    def format_duration(seconds: int) -> str:
        return MegabonkApp.format_elapsed_time(seconds)

    @staticmethod
    def format_elapsed_time(seconds: float | int) -> str:
        minutes, seconds = divmod(max(int(seconds), 0), 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    @classmethod
    def format_in_game_time(cls, seconds: float | None) -> str:
        if seconds is None:
            return "In-Game Time: --"
        return f"In-Game Time: {cls.format_elapsed_time(seconds)}"

    @staticmethod
    def format_mob_kills(value: int | None) -> str:
        if value is None:
            return "Mob Kills: --"
        return f"Mob Kills: {MegabonkApp.format_count(value)}"

    @staticmethod
    def format_count(value: int | float) -> str:
        return f"{max(0, int(value)):,}"

    @staticmethod
    def format_player_level(value: int | None) -> str:
        if value is None:
            return "Level: --"
        return f"Level: {max(0, int(value))}"

    @staticmethod
    def format_items(items) -> str:
        if not items:
            return "--"
        return ", ".join(items)

    @classmethod
    def format_snapshot_new_items(cls, previous_snapshot, snapshot) -> str:
        if previous_snapshot is None:
            return "No previous snapshot"
        new_items = cls.diff_new_items(getattr(previous_snapshot, "items", ()), getattr(snapshot, "items", ()))
        if not new_items:
            return "No new items since previous snapshot"
        return cls.format_new_items_rich_text(new_items)

    @classmethod
    def diff_new_items(cls, previous_items, current_items) -> tuple[str, ...]:
        previous_counts = cls._item_counts(previous_items)
        current_counts = cls._item_counts(current_items)
        new_items: list[str] = []
        for name, current_count in current_counts.items():
            delta = current_count - previous_counts.get(name, 0)
            if delta > 0:
                new_items.append(f"{name} x{delta}")
        return tuple(new_items)

    @classmethod
    def format_new_items_rich_text(cls, items) -> str:
        if not items:
            return "No new items since previous snapshot"
        return ", ".join(f"+ {cls._format_single_item_rich_text(item)}" for item in items)

    @classmethod
    def _item_counts(cls, items) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in items or ():
            name, suffix = cls._split_item_stack_suffix(str(item))
            name = cls._normalize_item_name_for_display(name)
            count = 1
            if suffix.startswith(" x") and suffix[2:].isdigit():
                count = int(suffix[2:])
            counts[name] = counts.get(name, 0) + max(1, count)
        return counts

    @classmethod
    def build_stage_summary(cls, snapshots) -> list[dict[str, str]]:
        rows = [
            {
                "label": f"Stage {index}",
                "kills": "--",
                "time": "--",
                "items": "--",
            }
            for index in range(1, 5)
        ]
        if not snapshots:
            return rows

        stage_buckets: dict[int, list[object]] = {index: [] for index in range(1, 5)}
        stage_item_gains: dict[int, int] = {index: 0 for index in range(1, 5)}
        current_stage_index = 1
        previous_snapshot = None
        for snapshot in snapshots:
            if previous_snapshot is not None:
                previous_stage_index = current_stage_index
                next_stage_index = cls._resolve_next_stage_index(
                    current_stage_index,
                    previous_snapshot,
                    snapshot,
                )
                current_stage_index = min(max(next_stage_index, current_stage_index), 4)
                if (
                    current_stage_index > previous_stage_index
                    and cls._is_stage_transition_boundary_snapshot(snapshot)
                ):
                    stage_buckets[previous_stage_index].append(snapshot)
                stage_item_gains[current_stage_index] += cls._item_gain_between_snapshots(
                    previous_snapshot,
                    snapshot,
                )
            stage_buckets[current_stage_index].append(snapshot)
            previous_snapshot = snapshot

        for stage_index, bucket in stage_buckets.items():
            if not bucket:
                continue
            first_snapshot = bucket[0]
            last_snapshot = bucket[-1]
            start_run_time = getattr(first_snapshot, "game_time_seconds", None)
            if stage_index == 1 and start_run_time is not None:
                start_run_time = 0.0
            end_run_time = getattr(last_snapshot, "game_time_seconds", None)
            duration_text = "--"
            if start_run_time is not None and end_run_time is not None:
                duration_text = cls.format_elapsed_time(max(0.0, end_run_time - start_run_time))

            kills_text = "--"
            first_kills = getattr(first_snapshot, "mob_kills", None)
            last_kills = getattr(last_snapshot, "mob_kills", None)
            if first_kills is not None and last_kills is not None:
                kills_text = cls.format_count(int(last_kills) - int(first_kills))

            items_text = str(stage_item_gains[stage_index])
            rows[stage_index - 1] = {
                "label": f"Stage {stage_index}",
                "kills": kills_text,
                "time": duration_text,
                "items": items_text,
            }

        return rows

    @classmethod
    def _resolve_next_stage_index(cls, current_stage_index: int, previous_snapshot, snapshot) -> int:
        previous_stage_ptr = int(getattr(previous_snapshot, "stage_ptr", 0) or 0)
        current_stage_ptr = int(getattr(snapshot, "stage_ptr", 0) or 0)
        previous_seed = getattr(previous_snapshot, "map_seed", None)
        current_seed = getattr(snapshot, "map_seed", None)
        if (
            current_stage_index < 3
            and (
                (
                    previous_stage_ptr
                    and current_stage_ptr
                    and current_stage_ptr != previous_stage_ptr
                )
                or (
                    previous_stage_ptr == 0
                    and current_stage_ptr == 0
                    and previous_seed is not None
                    and current_seed is not None
                    and current_seed != previous_seed
                )
            )
        ):
            return current_stage_index + 1

        if current_stage_index == 3 and cls._looks_like_stage_four_transition(previous_snapshot, snapshot):
            return 4
        return current_stage_index

    @staticmethod
    def _is_stage_transition_boundary_snapshot(snapshot) -> bool:
        stage_time = getattr(snapshot, "stage_time_seconds", None)
        if stage_time is None:
            return False
        return 0.0 <= float(stage_time) <= PLAYER_STATS_STAGE_TRANSITION_BOUNDARY_SECONDS

    @classmethod
    def _looks_like_stage_four_transition(cls, previous_snapshot, snapshot) -> bool:
        previous_stage_ptr = int(getattr(previous_snapshot, "stage_ptr", 0) or 0)
        current_stage_ptr = int(getattr(snapshot, "stage_ptr", 0) or 0)
        previous_seed = getattr(previous_snapshot, "map_seed", None)
        current_seed = getattr(snapshot, "map_seed", None)
        previous_stage_time = getattr(previous_snapshot, "stage_time_seconds", None)
        current_stage_time = getattr(snapshot, "stage_time_seconds", None)
        previous_run_time = getattr(previous_snapshot, "game_time_seconds", None)
        current_run_time = getattr(snapshot, "game_time_seconds", None)
        if (
            not previous_stage_ptr
            or not current_stage_ptr
            or previous_stage_ptr != current_stage_ptr
            or previous_seed != current_seed
            or previous_stage_time is None
            or current_stage_time is None
            or previous_run_time is None
            or current_run_time is None
        ):
            return False
        if current_run_time <= previous_run_time:
            return False
        if current_stage_time < 10.0 and current_stage_time + PLAYER_STATS_RUN_TIMER_RESET_TOLERANCE_SECONDS < previous_stage_time:
            return True
        return (
            previous_stage_time < 60.0
            and current_stage_time - previous_stage_time >= PLAYER_STATS_STAGE4_TIMER_JUMP_SECONDS
        )

    @classmethod
    def _item_gain_between_snapshots(cls, first_snapshot, last_snapshot) -> int:
        first_counts = cls._item_counts(getattr(first_snapshot, "items", ()))
        last_counts = cls._item_counts(getattr(last_snapshot, "items", ()))
        total_gain = 0
        for name, current_count in last_counts.items():
            total_gain += max(0, current_count - first_counts.get(name, 0))
        return total_gain

    @staticmethod
    def _set_stage_summary_labels(labels, rows) -> None:
        default_rows = [
            {
                "label": f"Stage {index}",
                "kills": "--",
                "time": "--",
                "items": "--",
            }
            for index in range(1, 5)
        ]
        rows = rows or default_rows
        for labels_by_column, row in zip(labels, rows):
            if isinstance(labels_by_column, dict):
                labels_by_column["stage"].setText(str(row["label"]).replace("Stage ", ""))
                labels_by_column["time"].setText(row["time"])
                labels_by_column["kills"].setText(row["kills"])
                labels_by_column["items"].setText(row["items"])
            else:
                labels_by_column.setText(
                    f"{row['label']}: Kills {row['kills']} | Time {row['time']} | Items {row['items']}"
                )

    @classmethod
    def format_items_rich_text(cls, items) -> str:
        if not items:
            return "--"
        return ", ".join(cls._format_single_item_rich_text(item) for item in items)

    @classmethod
    def _format_single_item_rich_text(cls, item_text: str) -> str:
        item_name, suffix = cls._split_item_stack_suffix(item_text)
        display_name = cls._normalize_item_name_for_display(item_name)
        rarity_name = cls._normalize_item_name_for_rarity(display_name)
        rarity = ITEM_RARITY_BY_NAME.get(rarity_name)
        color = ITEM_RARITY_COLOR_MAP.get(rarity)
        escaped_name = html.escape(display_name)
        if color:
            escaped_name = f'<span style="color: {color}; font-weight: 700;">{escaped_name}</span>'
        escaped_suffix = html.escape(suffix)
        return f"{escaped_name}{escaped_suffix}"

    @staticmethod
    def _split_item_stack_suffix(item_text: str) -> tuple[str, str]:
        if not item_text:
            return "", ""
        name, separator, suffix = item_text.rpartition(" x")
        if separator and suffix.isdigit():
            return name, f"{separator}{suffix}"
        return item_text, ""

    @staticmethod
    def _normalize_item_name_for_rarity(item_name: str) -> str:
        normalized = " ".join(item_name.split())
        if normalized in ITEM_RARITY_NAME_ALIASES:
            return ITEM_RARITY_NAME_ALIASES[normalized]
        if normalized.startswith("Gloves "):
            normalized = f"Glove {normalized[len('Gloves '):]}"

        folded = _fold_item_name_for_rarity(normalized)
        folded = ITEM_RARITY_FOLDED_NAME_ALIASES.get(folded, folded)
        return ITEM_RARITY_NAME_BY_FOLDED_NAME.get(folded, normalized)

    @staticmethod
    def _normalize_item_name_for_display(item_name: str) -> str:
        normalized = " ".join(item_name.split())
        return ITEM_DISPLAY_NAME_ALIASES.get(normalized, normalized)

    @staticmethod
    def calculate_player_chests_per_minute(stats) -> float | None:
        elite_stat = stats.get("Elite Spawn Increase")
        powerup_stat = stats.get("Powerup Drop Chance")
        elite_spawn_increase = getattr(elite_stat, "value", None)
        powerup_drop_chance = getattr(powerup_stat, "value", None)
        if elite_spawn_increase is None or powerup_drop_chance is None:
            return None
        return calculate_chests_per_minute(elite_spawn_increase, powerup_drop_chance)

    @classmethod
    def resolve_snapshot_chests_per_minute(cls, snapshot) -> float | None:
        stored_value = getattr(snapshot, "chests_per_minute", None)
        if stored_value is not None:
            return stored_value
        return cls.calculate_player_chests_per_minute(snapshot.stats)

    @staticmethod
    def format_chests_per_minute(value: float | None) -> str:
        if value is None:
            return "Average chests/min: --"
        return f"Average chests/min: {value:.2f}"

    def refresh_stats_ui(self):
        _set_text(self.stats_rerolls_label, f"Session Rerolls: {self.session_rerolls}")

        if self.best_map_stats:
            _set_text(self.stats_best_label, f"Best Map Found: {self.format_stats(self.best_map_stats)}")
        else:
            _set_text(self.stats_best_label, "Best Map Found: None")

        if self.worst_map_stats:
            _set_text(self.stats_worst_label, f"Worst Map Found: {self.format_stats(self.worst_map_stats)}")
        else:
            _set_text(self.stats_worst_label, "Worst Map Found: None")

        active_names = set()
        for name, data in self.template_stats.items():
            active_names.add(name)
            color_tag = "BLUE"
            if config.EVALUATION_MODE == "templates":
                for template in config.TEMPLATES:
                    if template["name"] == name:
                        color_tag = template.get("color", "BLUE").upper()
                        break
            else:
                colors = {"Light": "WHITE", "Good": "GREEN", "Perfect": "YELLOW", "Perfect+": "LIGHTRED_EX"}
                color_tag = colors.get(name, "BLUE")
            hex_color = COLOR_MAP.get(color_tag, COLOR_MAP["DEFAULT"])
            history = data["history"]
            avg_text = f"{sum(history) / len(history):.1f} ({len(history)} found)" if history else "N/A"

            label = self.stats_avg_labels.get(name)
            if label is None:
                label = QLabel()
                label.setWordWrap(True)
                self.stats_avg_layout.addWidget(label)
                self.stats_avg_labels[name] = label
            label.setText(f"{name}: {avg_text}")
            label.setStyleSheet(f"color: {hex_color}; font-size: 16px; font-weight: 600;")

        stale_names = [name for name in self.stats_avg_labels if name not in active_names]
        for name in stale_names:
            label = self.stats_avg_labels.pop(name)
            self.stats_avg_layout.removeWidget(label)
            label.deleteLater()

    def log_reroll_stats(self):
        self.session_rerolls += 1
        config.TOTAL_REROLLS += 1
        config.user_config["TOTAL_REROLLS"] = config.TOTAL_REROLLS
        try:
            config.save_config(config.user_config)
        except Exception as exc:
            self.log(f"[-] Could not save Total Rerolls: {exc}", tag="warning")

        for name in list(self.template_stats):
            self.template_stats[name]["rerolls_since_last"] += 1

        if self.session_rerolls % 5 == 0:
            self.after(0, self.refresh_stats_ui)

    def log_target_found(self, template_name: str):
        if template_name in self.template_stats:
            data = self.template_stats[template_name]
            attempts = data["rerolls_since_last"] if data["rerolls_since_last"] > 0 else 1
            data["history"].append(attempts)
            data["rerolls_since_last"] = 0
        self.after(0, self.refresh_stats_ui)

    def check_best_map(self, stats: dict):
        score = self.calculate_map_score(stats)
        if score > self.best_map_score:
            self.best_map_score = score
            self.best_map_stats = stats
            self.after(0, self.refresh_stats_ui)

    def check_worst_map(self, stats: dict):
        score = self.calculate_map_score(stats)
        if score < self.worst_map_score:
            self.worst_map_score = score
            self.worst_map_stats = stats
            self.after(0, self.refresh_stats_ui)

    def reroll_map(self):
        if self.run_control_provider is None:
            self.log("[-] Run control provider is not available; cannot restart run.", tag="error")
            return

        previous_state = None
        previous_stats = None
        if self.client is not None:
            try:
                previous_state = self.client.get_map_generation_state()
                previous_stats = self.client.get_map_stats()
            except MemoryReadError as exc:
                self.log(f"[WAIT] Could not read current map state before restart: {exc}", tag="warning")

        try:
            self.run_control_provider.restart_run()
        except RunControlError as exc:
            self.log(f"[-] {exc}", tag="error")
            return

        self.run_control_provider.wait_for_next_run(
            client=self.client,
            previous_state=previous_state,
            previous_stats=previous_stats,
            warn=lambda message: self.log(f"[WAIT] {message}", tag="warning"),
        )
        self.log_reroll_stats()

    def close_client(self):
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None

    def close_player_stats_client(self):
        player_stats_client = self.__dict__.get("player_stats_client")
        if player_stats_client:
            try:
                player_stats_client.close()
            except Exception:
                pass
            self.player_stats_client = None

    def close_player_stats_game_data_client(self):
        game_data_client = self.__dict__.get("player_stats_game_data_client")
        if game_data_client:
            try:
                game_data_client.close()
            except Exception:
                pass
            self.player_stats_game_data_client = None

    def get_game_process_id(self) -> int | None:
        if self.client is None:
            return None
        memory = getattr(self.client, "memory", None)
        pymem_client = getattr(memory, "_pm", None)
        process_id = getattr(pymem_client, "process_id", None)
        try:
            return int(process_id) if process_id else None
        except (TypeError, ValueError):
            return None

    def is_hook_run_control_active(self) -> bool:
        return isinstance(self.run_control_provider, HookRunControlProvider)

    def is_keyboard_run_control_active(self) -> bool:
        return isinstance(self.run_control_provider, KeyboardRunControlProvider)

    def is_game_window_active(self, process_name: str) -> bool:
        if win32gui is None or win32process is None:
            return True
        foreground_window = win32gui.GetForegroundWindow()
        if not foreground_window:
            return False
        game_process_id = self.get_game_process_id()
        if game_process_id is not None:
            try:
                _, foreground_process_id = win32process.GetWindowThreadProcessId(foreground_window)
                return int(foreground_process_id) == game_process_id
            except Exception:
                return False
        try:
            foreground_title = win32gui.GetWindowText(foreground_window) or ""
        except Exception:
            return False
        expected_title = os.path.splitext(process_name)[0]
        return bool(expected_title and expected_title.lower() in foreground_title.lower())

    def wait_for_game_window_focus(self, process_name: str) -> bool:
        if self.is_hook_run_control_active():
            return True
        if self.is_game_window_active(process_name):
            return True
        self.log("[WAIT] Game window is not active. Auto-reroll paused...", tag="warning")
        while not self.stop_event.is_set() and self.scan_event.is_set() and not self.is_game_window_active(process_name):
            time.sleep(0.3)
        if self.stop_event.is_set() or not self.scan_event.is_set():
            return False
        self.log("[+] Game window active again. Auto-reroll resumed.", tag="success")
        return True

    def bring_game_window_to_front(self, process_name: str) -> bool:
        if win32gui is None or win32process is None:
            self.log("[WAIT] Cannot bring game window to front: pywin32 is unavailable.", tag="warning")
            return False
        window = self.find_game_window(process_name)
        if not window:
            self.log("[WAIT] Cannot bring game window to front: game window was not found.", tag="warning")
            return False
        try:
            self.show_game_window(window)
            win32gui.SetForegroundWindow(window)
            return True
        except Exception as direct_exc:
            try:
                self.try_attach_foreground_window(window)
                return True
            except Exception as fallback_exc:
                self.log(
                    f"[WAIT] Cannot bring game window to front: {direct_exc}; ALT attach fallback failed: {fallback_exc}",
                    tag="warning",
                )
                return False

    @staticmethod
    def show_game_window(window: int) -> None:
        if hasattr(win32gui, "IsIconic") and win32gui.IsIconic(window):
            win32gui.ShowWindow(window, 9)
        elif hasattr(win32gui, "ShowWindow"):
            win32gui.ShowWindow(window, 5)

    def try_attach_foreground_window(self, window: int) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
        user32.AttachThreadInput.restype = wintypes.BOOL
        kernel32.GetCurrentThreadId.argtypes = []
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD

        current_thread = int(kernel32.GetCurrentThreadId())
        target_thread, _ = win32process.GetWindowThreadProcessId(window)
        foreground_window = win32gui.GetForegroundWindow()
        foreground_thread = None
        if foreground_window:
            foreground_thread, _ = win32process.GetWindowThreadProcessId(foreground_window)

        attached_threads = []
        seen_threads = set()
        for thread_id in (target_thread, foreground_thread):
            thread_id = int(thread_id) if thread_id else 0
            if not thread_id or thread_id == current_thread or thread_id in seen_threads:
                continue
            seen_threads.add(thread_id)
            if user32.AttachThreadInput(current_thread, thread_id, True):
                attached_threads.append(thread_id)

        try:
            self.send_alt_keypress(user32)
            if hasattr(win32gui, "BringWindowToTop"):
                win32gui.BringWindowToTop(window)
            win32gui.SetForegroundWindow(window)
        finally:
            for thread_id in attached_threads:
                user32.AttachThreadInput(current_thread, thread_id, False)

    @staticmethod
    def send_alt_keypress(user32) -> None:
        vk_menu = 0x12
        keyeventf_keyup = 0x0002
        user32.keybd_event(vk_menu, 0, 0, 0)
        user32.keybd_event(vk_menu, 0, keyeventf_keyup, 0)

    @staticmethod
    def is_visible_window(window: int) -> bool:
        try:
            return bool(window and (not hasattr(win32gui, "IsWindowVisible") or win32gui.IsWindowVisible(window)))
        except Exception:
            return False

    def find_game_window(self, process_name: str) -> int | None:
        game_process_id = self.get_game_process_id()
        if game_process_id is not None:
            window = self.find_game_window_by_pid(game_process_id)
            if window:
                return window
        return self.find_game_window_by_title(process_name)

    def find_game_window_by_pid(self, process_id: int) -> int | None:
        found_window = None

        def enum_callback(window, _extra):
            nonlocal found_window
            if found_window is not None or not self.is_visible_window(window):
                return
            try:
                _, window_process_id = win32process.GetWindowThreadProcessId(window)
            except Exception:
                return
            if int(window_process_id) == process_id:
                found_window = window

        try:
            win32gui.EnumWindows(enum_callback, None)
        except Exception as exc:
            self.log(f"[WAIT] Could not check the game window yet. Details: {exc}", tag="warning")
        return found_window

    def find_game_window_by_title(self, process_name: str) -> int | None:
        expected_title = os.path.splitext(process_name)[0]
        if not expected_title:
            return None

        found_window = None

        def enum_callback(window, _extra):
            nonlocal found_window
            if found_window is not None or not self.is_visible_window(window):
                return
            try:
                window_title = win32gui.GetWindowText(window) or ""
            except Exception:
                return
            if expected_title.lower() in window_title.lower():
                found_window = window

        try:
            win32gui.EnumWindows(enum_callback, None)
        except Exception as exc:
            self.log(f"[WAIT] Could not check the game window yet. Details: {exc}", tag="warning")
        return found_window

    def handle_confirmed_target_window(self, process_name: str) -> bool:
        if self.is_hook_run_control_active():
            self.bring_game_window_to_front(process_name)
            if keyboard:
                time.sleep(0.15)
                keyboard.press_and_release("esc")
            return True

        if keyboard:
            if not self.wait_for_game_window_focus(process_name):
                return False
            keyboard.press_and_release("esc")

        return True

    def background_loop(self):
        process_name = config.PROCESS_NAME.strip()
        wait_state = None
        last_state = None
        last_stats = None
        last_reroll_time = time.monotonic()
        is_first_scan = True

        while not self.stop_event.is_set():
            if self.client is None:
                try:
                    self.client = GameDataClient(process_name=process_name)
                    self.log(f"[+] Game connected! Press '{config.HOTKEY}' to start auto-reroll.", tag="success")
                    self.is_ready_to_start = True
                    self.after(0, self.update_status_ui)
                except ProcessNotFoundError:
                    if wait_state != "process":
                        self.log(f"[WAIT] Waiting for process '{process_name}'...", tag="warning")
                        wait_state = "process"
                        self.after(0, self.update_status_ui)
                    time.sleep(1)
                    continue
                except ModuleNotFoundError:
                    if wait_state != "module":
                        self.log("[WAIT] Game found. Waiting for it to finish loading...", tag="warning")
                        wait_state = "module"
                        self.after(0, self.update_status_ui)
                    time.sleep(1)
                    continue

            was_waiting = not self.scan_event.is_set()
            self.scan_event.wait()
            if was_waiting:
                is_first_scan = True
                last_state = None
                last_stats = None

            if self.stop_event.is_set():
                break

            try:
                if not self.wait_for_game_window_focus(process_name):
                    continue

                try:
                    raw_stats = self.client.wait_for_map_ready(
                        previous_state=last_state,
                        previous_stats=last_stats,
                        require_change=not is_first_scan,
                        abort_condition=lambda: self.stop_event.is_set() or not self.scan_event.is_set(),
                        timeout=10.0,
                    )
                except InterruptedError:
                    continue

                is_first_scan = False
                last_state = self.client.get_map_generation_state()
                last_stats = raw_stats
                stats = adapt_map_stats(raw_stats)

                self.check_best_map(stats)
                self.check_worst_map(stats)
                candidate = self.evaluate_candidate(stats)

                if candidate is not None:
                    if not self.wait_for_game_window_focus(process_name):
                        continue

                    t_name = candidate.get("name")
                    t_color = candidate.get("color", "BLUE").upper()
                    score_text = (
                        f" (Score: {candidate.get('score', 0):.1f})"
                        if config.EVALUATION_MODE == "scores"
                        else ""
                    )
                    self.log([f"\n[$$$] TARGET MAP FOUND! Profile: ", f"{t_name}{score_text}"], tag=["success", t_color])
                    self.log(f"Map Stats: {self.format_stats(stats)}", tag="success")
                    self.log_target_found(t_name)

                    if not self.handle_confirmed_target_window(process_name):
                        continue

                    self.is_running = False
                    self.scan_event.clear()
                    self.after(0, self.update_status_ui)
                    continue
                else:
                    self.log(f"Stats: {self.format_stats(stats)}")

                if not self.wait_for_game_window_focus(process_name):
                    continue

                elapsed = time.monotonic() - last_reroll_time
                while elapsed < config.MIN_DELAY:
                    if self.stop_event.is_set() or not self.scan_event.is_set():
                        break
                    time.sleep(0.05)
                    elapsed = time.monotonic() - last_reroll_time

                if self.stop_event.is_set() or not self.scan_event.is_set():
                    continue

                self.reroll_map()
                last_reroll_time = time.monotonic()

            except TimeoutError as exc:
                self.log(f"[-] Map took too long to load: {exc}", tag="warning")
                self.log("[*] Restarting run to recover...", tag="warning")
                self.reroll_map()
                last_reroll_time = time.monotonic()
                last_state = None
                last_stats = None
            except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError) as exc:
                self.is_running = False
                self.is_ready_to_start = False
                self.scan_event.clear()
                self.close_client()
                self.log(f"[-] Lost connection to the game. Details: {exc}", tag="error")
                wait_state = None
                last_state = None
                last_stats = None
                self.after(0, self.update_status_ui)
                time.sleep(1)
            except Exception as exc:
                self.log(f"[-] Error during execution: {exc}", tag="error")
                time.sleep(1)

        self.close_client()
        self.is_running = False
        self.is_ready_to_start = False
        self.scan_event.clear()
        self.after(0, self.update_status_ui)

    def on_closing(self):
        if getattr(self, "_is_shutting_down", False):
            return
        self._is_shutting_down = True
        self._cancel_right_tab_transition()
        self.stop_event.set()
        self.scan_event.set()
        self.close_client()
        self.close_player_stats_client()
        self.close_player_stats_game_data_client()
        player_stats_vod_recorder = self.__dict__.get("player_stats_vod_recorder")
        if player_stats_vod_recorder is not None:
            if player_stats_vod_recorder.is_recording:
                player_stats_vod_recorder.stop()
            else:
                player_stats_vod_recorder.close()
        hook_loader = self.native_hook_loader
        if hook_loader is not None:
            self.native_hook_generation += 1
            self.native_hook_loader = None
            self.native_hook_thread = None
            try:
                hook_loader.uninitialize()
                self.log("[+] Game restart helper disconnected.", tag="success")
            except HookProcessNotFoundError:
                self.log("[WAIT] Game is already closed; restart helper shutdown skipped.", tag="warning")
            except HookLoadError as exc:
                self.log(f"[WAIT] Could not disconnect restart helper during shutdown. Details: {exc}", tag="warning")
            except Exception as exc:
                self.log(f"[WAIT] Unexpected restart helper shutdown error. Details: {exc}", tag="warning")
            finally:
                try:
                    hook_loader.cleanup_cached_dll()
                except Exception as exc:
                    self.log(f"[WAIT] Could not clean up cached restart helper DLL. Details: {exc}", tag="warning")
        if keyboard:
            try:
                keyboard.unhook_all()
            except Exception:
                pass
        self.destroy()
