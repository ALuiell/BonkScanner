from __future__ import annotations

from item_metadata import (
    ITEM_DISPLAY_NAME_ALIASES,
    ITEM_RARITY_BY_NAME,
    ITEM_RARITY_FOLDED_NAME_ALIASES,
    ITEM_RARITY_NAME_ALIASES,
    ITEM_RARITY_NAME_BY_FOLDED_NAME,
    _fold_item_name_for_rarity,
)

PLAYER_STATS_REFRESH_MS = 10_000
PLAYER_STATS_RECORDING_SEED_GRACE_SECONDS = 20
PLAYER_STATS_RUN_TIMER_RESET_TOLERANCE_SECONDS = 3.0
PLAYER_STATS_STAGE_TRANSITION_BOUNDARY_SECONDS = 5.0
PLAYER_STATS_STAGE4_RESET_WINDOW_SECONDS = 90.0
PLAYER_STATS_STAGE4_TIMER_JUMP_SECONDS = 300.0
PLAYER_STATS_STAGE4_GHOST_TIMER_SECONDS = 500.0
PLAYER_STATS_STAGE4_GHOST_ENTRY_MAX_SECONDS = 900.0
PLAYER_STATS_ITEM_DROP_CONFIRMATION_SNAPSHOTS = 2
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

def _template_checkbox_stylesheet(color_hex: str) -> str:
    return f"""
    QCheckBox {{
        color: {color_hex};
        background: #121A27;
        border: 1px solid #2B3648;
        border-left: 4px solid {color_hex};
        border-radius: 8px;
        padding: 8px 8px;
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


def build_qt_app_stylesheet(checkmark_path: str) -> str:
    return (
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
                QLineEdit, QTextEdit, QPlainTextEdit, QListWidget, QSpinBox, QDoubleSpinBox {
                    background: #0B1220;
                    border: 1px solid #2B3648;
                    border-radius: 6px;
                    padding: 6px;
                    selection-background-color: #1F6AA5;
                }
                QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QListWidget:focus, QSpinBox:focus, QDoubleSpinBox:focus {
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
                QPushButton:disabled {
                    background: #141A23;
                    color: #5F6A7A;
                    border: 1px solid #222E3E;
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
                QPushButton#GithubButton {
                    background: #151B23;
                    color: #F0F6FC;
                    font-weight: 700;
                    text-align: center;
                    padding: 4px 10px;
                    border: 1px solid #3D444D;
                    border-radius: 10px;
                }
                QPushButton#GithubButton:hover {
                    background: #1F2832;
                    border: 1px solid #586069;
                }
                QPushButton#DiscordButton {
                    background: #1C2142;
                    color: #AEBBFF;
                    font-weight: 700;
                    text-align: center;
                    padding: 4px 10px;
                    border: 1px solid #3B4383;
                    border-radius: 10px;
                }
                QPushButton#DiscordButton:hover {
                    background: #252B57;
                    border: 1px solid #5865F2;
                }
                QPushButton#TwitchConnectButton {
                    background: #9146FF;
                    color: white;
                    font-weight: 700;
                    border: none;
                    border-radius: 8px;
                    padding: 8px 12px;
                }
                QPushButton#TwitchConnectButton:hover {
                    background: #772CE8;
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
                QPushButton[class="CompareRunsGhostButton"] {
                    background: #21364D;
                    color: #F4F8FC;
                    font-size: 13px;
                    font-weight: 700;
                    padding: 5px 12px;
                    border: 1px solid #3F6487;
                    border-radius: 7px;
                    min-height: 26px;
                    max-height: 26px;
                }
                QPushButton[class="CompareRunsGhostButton"]:hover {
                    background: #2A4664;
                    border-color: #5B86AF;
                    color: #FFFFFF;
                }
                QPushButton[class="WideDialogButton"] {
                    min-height: 34px;
                    font-size: 14px;
                }
                QPushButton#SettingsButton, QPushButton#HelpButton {
                    min-width: 44px;
                    max-width: 44px;
                    min-height: 40px;
                    max-height: 40px;
                    padding: 0;
                    background: #2B3A4F;
                    border: 1px solid #41556F;
                    border-radius: 8px;
                }
                QPushButton#SettingsButton:hover, QPushButton#HelpButton:hover {
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