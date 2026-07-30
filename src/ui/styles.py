from __future__ import annotations

from pathlib import Path

# COLOR_MAP now belongs to core/item_metadata.py, whose lowest consumer it is;
# the Qt helpers below still build stylesheets out of it, which is a legal
# downward import.
from core.item_metadata import COLOR_MAP
# ITEM_SORT_LABELS below is keyed by the sort modes, which projections/ owns.
from projections.item_sort import (
    ITEM_SORT_DEFAULT,
    ITEM_SORT_RARITY_ASC,
    ITEM_SORT_RARITY_DESC,
)
from ui.shared import resource_path

PLAYER_STATS_ACTIVE_BUTTON_COLOR = "#B91C1C"
PLAYER_STATS_ACTIVE_BUTTON_HOVER_COLOR = "#CC2626"
PLAYER_STATS_INACTIVE_BUTTON_COLOR = "#2F6FB0"
PLAYER_STATS_INACTIVE_BUTTON_HOVER_COLOR = "#3781CE"
PLAYER_STATS_VALUE_WIDTH = 72
ITEM_SORT_LABELS = {
    ITEM_SORT_DEFAULT: "Default item order",
    ITEM_SORT_RARITY_DESC: "Rarity — highest first",
    ITEM_SORT_RARITY_ASC: "Rarity — lowest first",
}

def _template_checkbox_stylesheet(color_hex: str) -> str:
    # `color_hex` shapes the row only -- the left accent bar and the label
    # colour when checked, which is what tells templates apart at a glance.
    # The checkbox glyph itself is deliberately left undefined here: it falls
    # through to the app-wide indicator rule (`build_qt_app_stylesheet`), so
    # every checkbox in the app, not just this row, looks the same one way.
    return f"""
    QCheckBox {{
        color: #8A94A3;
        background: #0B0F14;
        border: 1px solid #1B222B;
        border-left: 4px solid {color_hex};
        border-radius: 10px;
        padding: 10px 12px;
        min-height: 38px;
        font-weight: 600;
    }}
    QCheckBox:checked {{
        color: {color_hex};
        background: #141A22;
        border-color: #2E3A48;
        border-left-color: {color_hex};
        font-weight: 700;
    }}
    QCheckBox:hover {{
        background: #141A22;
        border-color: #38495E;
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


def _set_widget_style_role(widget, object_name: str, *, state: str | None = None) -> None:
    """Switch a live widget to a QSS role and force Qt to re-evaluate it."""
    if widget is None:
        return
    set_stylesheet = getattr(widget, "setStyleSheet", None)
    if callable(set_stylesheet):
        set_stylesheet("")
    set_object_name = getattr(widget, "setObjectName", None)
    if callable(set_object_name):
        set_object_name(object_name)
    set_property = getattr(widget, "setProperty", None)
    if callable(set_property) and state is not None:
        set_property("state", state)
    style_getter = getattr(widget, "style", None)
    if not callable(style_getter):
        return
    style = style_getter()
    if style is None:
        return
    unpolish = getattr(style, "unpolish", None)
    polish = getattr(style, "polish", None)
    if callable(unpolish):
        unpolish(widget)
    if callable(polish):
        polish(widget)

def _session_stats_label_stylesheet(accent: bool = False) -> str:
    color = "#F3F4F6" if accent else "#D7DEE8"
    weight = "700" if accent else "600"
    return f"color: {color}; font-size: 17px; font-weight: {weight}; background: transparent;"

def _tier_color(tier: str) -> str:
    return {
        "Light": COLOR_MAP["WHITE"],
        "Good": COLOR_MAP["GREEN"],
        "Perfect": COLOR_MAP["YELLOW"],
        "Perfect+": COLOR_MAP["LIGHTRED_EX"],
    }.get(tier, COLOR_MAP["DEFAULT"])


def build_qt_app_stylesheet(checkmark_path: str) -> str:
    legacy_stylesheet = (
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
                /* A StatCard already inside a QGroupBox: same surface, no
                   second border. The background is not decoration -- the
                   generic `QWidget` rule above paints every QLabel #10141B,
                   so it is this lighter fill behind them that makes the rows
                   read as stripes. Drop it and the card goes flat. */
                QFrame#StatCardInner {
                    background: #131A23;
                    border: none;
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

    redesign_path = Path(resource_path("redisign_ui/bonkscanner_redesign.qss"))
    try:
        redesign_stylesheet = redesign_path.read_text(encoding="utf-8")
    except OSError:
        # Keep source runs and partially upgraded installations usable even if
        # the optional redesign asset was not copied alongside the executable.
        redesign_stylesheet = ""

    compatibility_stylesheet = """
        /* Existing BonkScanner widgets mapped onto the redesign system. */
        QMainWindow, QDialog, QWidget {
            background-color: #0E1217;
        }
        QFrame#headerBar {
            background-color: #0E1217;
            border: none;
            border-bottom: 1px solid #1B222B;
        }
        QLabel, QCheckBox, QRadioButton {
            background: transparent;
        }
        QWidget#LiveStatsPage,
        QWidget#LiveStatsMain,
        QWidget#LiveStatsCardGrid,
        QWidget#LiveStatsCompactRows {
            background: transparent;
        }
        QWidget#LiveStatsCompactStat {
            background: transparent;
            border: none;
        }
        QLabel#LiveStatsCompactStatName {
            color: #D7DEE8;
            font-size: 14px;
            font-weight: 400;
        }
        QLabel#LiveStatsCompactStatValue {
            color: #F3F4F6;
            font-size: 15px;
            font-weight: 700;
        }
        QLabel#LiveStatsExpandedStatName {
            color: #D7DEE8;
            font-size: 14px;
        }
        QLabel#LiveStatsExpandedStatValue {
            color: #F3F4F6;
            font-size: 15px;
            font-weight: 700;
        }
        QLabel#LiveStatsLootStatName {
            color: #D7DEE8;
            font-size: 13px;
        }
        QLabel#LiveStatsLootStatValue {
            color: #F3F4F6;
            font-size: 14px;
            font-weight: 700;
        }
        QLabel#LiveStatsMetaText {
            color: #98A7BA;
            font-size: 12px;
        }
        QGroupBox#LiveStatsRunSummary QLabel,
        QGroupBox#LiveStatsPowerups QLabel,
        QGroupBox#LiveStatsStageSummary QLabel {
            font-size: 14px;
        }
        QWidget#LiveStatsBanishes {
            background: transparent;
            border: 1px solid rgba(248, 113, 113, 0.42);
            border-radius: 7px;
        }
        QScrollArea#LiveStatsItemsScroll {
            background: transparent;
            border: none;
        }
        QScrollArea#LiveStatsItemsScroll > QWidget > QWidget {
            background: transparent;
        }
        QFrame#LiveStatsItemsDivider {
            background-color: #1B222B;
            border: none;
            min-height: 1px;
            max-height: 1px;
        }
        QLabel#LiveStatsBanishesTitle {
            color: #FCA5A5;
            font-size: 10px;
            font-weight: 700;
        }
        QLabel#LiveStatsBanishesText {
            color: #98A7BA;
        }
        QWidget#BanishesChips {
            background: transparent;
        }
        QToolTip {
            background-color: #161C24;
            color: #EDF1F5;
            border: 1px solid #38495E;
            padding: 5px 7px;
        }
        QGroupBox {
            background-color: #101419;
            border: 1px solid #1B222B;
            border-radius: 12px;
            margin-top: 10px;
            padding-top: 12px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 12px;
            padding: 0 5px;
            color: #B9C2CE;
            font-weight: 700;
        }
        QFrame#StatCard {
            background-color: #0B0F14;
            border: 1px solid #1B222B;
            border-radius: 12px;
            padding: 8px;
        }
        QFrame#StatCardInner {
            background-color: #0B0F14;
            border: none;
        }
        /* Stage chapters: the four cards that replaced the Stage Summary
           table. `hasData=false` is a stage this run never reached -- dimmed
           rather than hidden, so the run's shape stays readable at a glance;
           `current=true` is the stage the playhead is inside. */
        QFrame#StageChapterCard {
            background-color: #0B0F14;
            border: 1px solid #1B222B;
            border-radius: 11px;
        }
        QFrame#StageChapterCard:hover {
            border-color: #2E3A48;
        }
        QFrame#StageChapterCard[current="true"] {
            border-color: #3E82C6;
            background-color: #10161F;
        }
        QFrame#StageChapterCard[rangeAnchor="true"] {
            border-color: #FACC15;
            background-color: #17160B;
        }
        QFrame#StageChapterCard[hasData="false"] {
            border-color: #151B23;
        }
        QFrame#StageChapterCard QLabel {
            background: transparent;
            border: none;
        }
        QLabel#StageChapterTitle {
            color: #EDF1F5;
            font-weight: 800;
            font-size: 12px;
        }
        QLabel#StageChapterTime {
            color: #5C6675;
            font-weight: 700;
            font-size: 11px;
        }
        QLabel#StageChapterKills {
            color: #F8FAFC;
            font-size: 12px;
        }
        QLabel#StageChapterItems {
            font-size: 12px;
        }
        QFrame#StageChapterCard[hasData="false"] QLabel {
            color: #3D4756;
        }
        QLabel#RecordingScrubberPosition {
            color: #EDF1F5;
            font-weight: 700;
            background-color: #141A22;
            border: 1px solid #2E3A48;
            border-radius: 9px;
            padding: 4px 11px;
        }
        QLabel#RecordingScrubberLegend,
        QLabel#RecordingScrubberMeta,
        QLabel#RecordingScrubberCompareHint {
            background: transparent;
        }
        QLabel#RecordingScrubberMeta {
            color: #5C6675;
            font-size: 11.5px;
        }
        /* The recordings library: search, rows, and the auto-filter footer. */
        QListWidget#RecordingsList::item {
            border-bottom: 1px solid #1B222B;
            padding: 0;
        }
        QListWidget#RecordingsList::item:selected {
            background-color: rgba(47, 111, 176, 0.18);
            border-left: 2px solid #3E82C6;
        }
        QWidget#RecordingRow {
            background: transparent;
        }
        QLabel#RecordingRowName {
            color: #EDF1F5;
            font-size: 12.5px;
            font-weight: 700;
            background: transparent;
        }
        QLabel#RecordingRowMeta {
            color: #5C6675;
            font-size: 11px;
            background: transparent;
        }
        QProgressBar#RecordingRowBar {
            background: #151B23;
            border: 0;
            border-radius: 2px;
        }
        QProgressBar#RecordingRowBar::chunk {
            background: #2E3A48;
            border-radius: 2px;
        }
        QFrame#RecordingsLibraryFooter {
            border-top: 1px solid #1B222B;
        }
        QFrame#RecordingsLibraryFooter QLabel {
            background: transparent;
            color: #8A94A3;
            font-size: 11.5px;
        }
        QLabel#RecordingsLibrarySummary {
            color: #EDF1F5;
            font-weight: 700;
        }
        QLabel#RecordingsLibraryHint {
            color: #5C6675;
            font-size: 11px;
        }
        QLabel#ItemsRaritySummary {
            color: #E5E7EB;
            font-size: 12px;
            background: transparent;
        }
        /* The items list is the one place a scrollbar has to announce itself:
           it holds ~40 chips in a viewport that shows five or six, so whether
           it scrolls is the first question you have. The global handle is
           #2A3542 on a transparent track, which against this background is
           near-invisible -- readable as "the list is cut off". */
        QScrollArea#LiveStatsItemsScroll QScrollBar:vertical {
            background: #0B0F14;
            width: 10px;
            border-radius: 5px;
        }
        QScrollArea#LiveStatsItemsScroll QScrollBar::handle:vertical {
            background: #46586F;
            border-radius: 5px;
            min-height: 28px;
        }
        QScrollArea#LiveStatsItemsScroll QScrollBar::handle:vertical:hover {
            background: #5E7490;
        }
        QWidget#CompareDetailsRows,
        QWidget#CompareRarityRow,
        QWidget#CompareSegmentHeader {
            background: transparent;
        }
        QLabel#CompareSegmentHeadline {
            font-size: 12.5px;
        }
        /* On the `#38BDF8` accent the A/B letters wear rather than the muted
           ghost palette: this button exists only while a pin is down, and it
           is the only way out of the segment that does not need the Esc key.
           Same pair as `#RecordingPlaqueLibrary:checked`, which is the sheet's
           other "this is switched on" control. */
        QPushButton#CompareSegmentClear {
            background: #173352;
            border: 1px solid #3E82C6;
            border-radius: 7px;
            color: #DDEEFF;
            font-size: 12px;
            font-weight: 700;
            padding: 4px 11px;
        }
        QPushButton#CompareSegmentClear:hover {
            background: #1E4368;
            border-color: #5B9BDD;
            color: #FFFFFF;
        }
        QPushButton#CompareSegmentClear:pressed {
            background: #12283F;
        }
        /* One size below the headline: the item runs are a list to scan, not
           the line that says what the segment is. */
        QLabel#CompareRarityBadge,
        QLabel#CompareRarityItems {
            font-size: 12px;
        }
        /* The icon-only sort control, on the `#iconBtn` palette rather than a
           blue one. `#3E82C6` means *primary* in this design -- it is the
           active `go` segment and the pressed `primary` button -- and sorting
           is the least consequential thing on the panel. Idle it out-shouted
           `Rec`, which is the one control on the strip that actually does
           something. Accent now appears on hover and while the menu is open,
           which is where `#iconBtn` puts it too.

           Geometry stays 38x22 (set in `CompactItemsSortComboBox`): `#iconBtn`
           is 36x36 for the 40px header bar, and a square that tall would not
           fit a panel header sized to a 12px label. Radius joins the 8px
           control tier. */
        /* The glyph is painted, so it arrives by property, not by `color`. */
        QComboBox#ItemsSortCombo {
            qproperty-glyphColor: #EDF1F5;
            qproperty-glyphActiveColor: #FACC15;
            background-color: #1C2530;
            border: 1px solid #33414F;
            border-radius: 8px;
            padding: 0;
        }
        QComboBox#ItemsSortCombo:hover {
            background-color: #243040;
            border-color: #3E82C6;
        }
        QComboBox#ItemsSortCombo:on {
            background-color: #243040;
            border-color: #4E93D7;
        }
        QComboBox#ItemsSortCombo:disabled {
            background-color: #12161C;
            border-color: #1B222B;
        }
        QComboBox#ItemsSortCombo::drop-down {
            width: 0;
            border: none;
        }
        QComboBox#ItemsSortCombo::down-arrow {
            image: none;
            width: 0;
            height: 0;
        }
        QComboBox#ItemsSortCombo QAbstractItemView {
            min-width: 190px;
            background-color: #141A22;
            border: 1px solid #38495E;
            color: #D7DEE8;
            padding: 4px;
            selection-background-color: #1F4E79;
            selection-color: #FFFFFF;
        }
        QFrame#RecordingPlaque {
            background: transparent;
        }
        QLabel#RecordingPlaqueTitle {
            color: #EDF1F5;
            font-size: 16px;
            font-weight: 700;
            background: transparent;
        }
        QLabel#RecordingPlaqueStatus {
            color: #5C6675;
            font-size: 11.5px;
            background: transparent;
        }
        QLineEdit#RecordingPlaqueNameEdit {
            font-size: 15px;
            font-weight: 700;
            padding: 2px 7px;
        }
        QPushButton#RecordingPlaqueLibrary {
            background: transparent;
            border: 1px solid #2A3542;
            border-radius: 6px;
            color: #9AA4B2;
            font-size: 14px;
            font-weight: 700;
            padding: 3px 9px;
        }
        QPushButton#RecordingPlaqueLibrary:hover {
            background: #161C24;
            border-color: #38495E;
            color: #EDF1F5;
        }
        QPushButton#RecordingPlaqueLibrary:checked {
            background: #173352;
            border-color: #3E82C6;
            color: #DDEEFF;
        }
        QPushButton#RecordingPlaqueRename {
            background-color: #161C24;
            border: 1px solid #2A3542;
            border-radius: 9px;
            color: #EDF1F5;
            font-size: 12.5px;
            font-weight: 700;
            padding: 6px 12px;
        }
        QPushButton#RecordingPlaqueRename:hover {
            background-color: #1B222D;
            border-color: #37424F;
        }
        QPushButton#RecordingPlaqueRename:pressed {
            background-color: #0B0F14;
        }
        QPushButton#RecordingPlaqueDelete {
            background: transparent;
            border: 1px solid #4A2226;
            border-radius: 6px;
            color: #F0787E;
            font-size: 12px;
            font-weight: 600;
            padding: 3px 10px;
        }
        QPushButton#RecordingPlaqueDelete:hover {
            background: #8F1D22;
            border-color: #B91C1C;
            color: #FFFFFF;
        }
        QPushButton#RecordingPlaqueRename:disabled {
            background-color: #12161C;
            border-color: #1B222B;
            color: #4A5462;
        }
        QPushButton#RecordingPlaqueDelete:disabled {
            color: #2A323D;
            border-color: #1B222B;
            background: transparent;
        }
        QTextEdit, QPlainTextEdit, QListWidget, QTreeWidget, QTableWidget {
            background-color: #0E1217;
            border: 1px solid #2A3542;
            border-radius: 7px;
            color: #EDF1F5;
            selection-background-color: #1B62A8;
            selection-color: #FFFFFF;
        }
        QComboBox QAbstractItemView {
            background-color: #101419;
            color: #EDF1F5;
            border: 1px solid #2A3542;
            selection-background-color: #1B62A8;
        }
        QTextEdit#logView, QPlainTextEdit#logView {
            font-family: "JetBrains Mono", Consolas, monospace;
            font-size: 12px;
            color: #8A94A3;
        }
        QPushButton:disabled {
            background-color: #101419;
            border-color: #1B222B;
            color: #5C6675;
        }
        QPushButton#DangerButton {
            background-color: transparent;
            border: 1px solid #4A2226;
            color: #F0787E;
        }
        QPushButton#DangerButton:hover {
            background-color: #B91C1C;
            border-color: #B91C1C;
            color: #FFFFFF;
        }
        QPushButton#SuccessButton {
            background-color: #166534;
            border: 1px solid #238B49;
            color: #FFFFFF;
        }
        QPushButton#SuccessButton:hover {
            background-color: #1D7A3E;
        }
        QPushButton#ToggleButton {
            min-width: 138px;
            background-color: #1B62A8;
            border: 1px solid #2472C4;
            color: #FFFFFF;
            font-weight: 800;
            letter-spacing: 0.5px;
        }
        QPushButton#ToggleButton:hover {
            background-color: #2472C4;
            border-color: #3585D2;
        }
        QPushButton#SettingsButton, QPushButton#HelpButton {
            min-width: 40px;
            max-width: 40px;
            min-height: 36px;
            max-height: 36px;
            padding: 0;
            background-color: #161C24;
            border: 1px solid #2A3542;
            border-radius: 8px;
        }
        QPushButton#SettingsButton:hover, QPushButton#HelpButton:hover {
            background-color: #1B222B;
            border-color: #38495E;
        }
        QPushButton[class="SupportPlatformButton"] {
            min-height: 26px;
            max-height: 26px;
            padding: 2px 8px;
            font-size: 12px;
        }
        QPushButton[class="SmallGhostButton"] {
            background-color: transparent;
            color: #9AA4B2;
            border: 1px solid transparent;
            border-radius: 8px;
            min-height: 22px;
            max-height: 22px;
            padding: 3px 8px;
        }
        QPushButton[class="SmallGhostButton"]:hover {
            background-color: #141A22;
            border-color: transparent;
            color: #EDF1F5;
        }
        QTabWidget::pane {
            border: none;
            background: transparent;
            top: 0;
        }
        QTabWidget#mainTabs::pane {
            background-color: #101419;
            border: 1px solid #1B222B;
            border-radius: 16px;
            top: 8px;
            padding: 8px;
        }
        QTabBar {
            background-color: #0B0F14;
            border: 1px solid #1B222B;
            border-radius: 12px;
        }
        QTabBar::tab {
            background: transparent;
            color: #6F7A89;
            font-weight: 700;
            font-size: 12px;
            padding: 8px 13px;
            border-radius: 8px;
            margin: 4px 2px;
            min-width: 0;
        }
        QTabBar::tab:selected {
            background-color: #1B62A8;
            color: #FFFFFF;
            font-weight: 800;
        }
        QTabBar::tab:hover:!selected {
            background-color: #141A22;
            color: #B9C2CE;
        }
        QLabel#SectionHeader {
            color: #EDF1F5;
            font-size: 18px;
            font-weight: 800;
            letter-spacing: 0.3px;
        }
        QLabel#StatusLabel, QLabel#statusText {
            color: #8A94A3;
            font-family: "JetBrains Mono", Consolas, monospace;
            font-size: 12px;
            font-weight: 600;
            padding-left: 10px;
        }
        QCheckBox::indicator:checked {
            image: url(__CHECKMARK_ICON__);
        }
        QSplitter::handle {
            background: #1B222B;
            margin: 0 6px;
            border-radius: 2px;
        }
    """.replace("__CHECKMARK_ICON__", checkmark_path)

    base_stylesheet = redesign_stylesheet or legacy_stylesheet

    # One indicator rule, applied last so it beats both the legacy sheet and
    # the redesign asset's `image: none` -- every checkbox in the app, in
    # every tab and dialog, ends up the same colour with the same visible
    # checkmark instead of each screen inheriting whatever the two base
    # sheets happened to leave unset for this selector.
    checkbox_uniform_stylesheet = f"""
        QCheckBox::indicator {{
            width: 16px; height: 16px;
            border: 1px solid #2A3542;
            border-radius: 4px;
            background-color: #0E1217;
        }}
        QCheckBox::indicator:hover {{
            border-color: #38495E;
        }}
        QCheckBox::indicator:checked {{
            background-color: #2F6FB0;
            border-color: #3E82C6;
            image: url({checkmark_path});
        }}
        QCheckBox::indicator:checked:hover {{
            background-color: #3781CE;
        }}
    """

    # The border-drawn triangle Qt stylesheets normally use for spin-box and
    # combo-box arrows (border-left/right transparent, border-top/bottom
    # solid) does not render as a triangle under this Qt build -- it paints
    # as a flat grey block instead, which is the "arrows are broken" the
    # redesign QSS shipped with. Real icons sidestep the quirk entirely.
    spin_up_path = resource_path("media/spin_up.svg").replace("\\", "/")
    spin_down_path = resource_path("media/spin_down.svg").replace("\\", "/")
    spinner_uniform_stylesheet = f"""
        QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
            width: 12px; height: 8px;
            border: none;
            image: url({spin_up_path});
        }}
        QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
            width: 12px; height: 8px;
            border: none;
            image: url({spin_down_path});
        }}
        QComboBox::down-arrow {{
            width: 12px; height: 8px;
            border: none;
            image: url({spin_down_path});
        }}
    """

    # Minimal mirror of the canonical Compare Runs rules above. This is only
    # the source-run/partial-install fallback when the external QSS asset is
    # unavailable; visual changes belong in bonkscanner_redesign.qss first.
    compare_runs_compatibility_stylesheet = """
        QWidget#CompareRunsPage, QWidget#CompareRunsTabPage,
        QWidget#CompareRunsWorkspacePage, QWidget#CompareRunsChooserPage,
        QStackedWidget#CompareRunsWorkspaceStack,
        QScrollArea#CompareRunsPageScroll,
        QScrollArea#CompareRunsPageScroll > QWidget > QWidget {
            background: transparent;
            border: none;
        }
        QFrame#CompareRunsRunPlaque, QFrame#CompareRunsTimelineCard {
            background-color: #0B0F14;
            border: 1px solid #1B222B;
            border-radius: 11px;
        }
        QFrame#CompareRunsRunPlaque[side="A"] { border-left: 3px solid #38BDF8; }
        QFrame#CompareRunsRunPlaque[side="B"] { border-left: 3px solid #C084FC; }
        QLabel#CompareRunsRunBadge[side="A"],
        QLabel#CompareRunsChooserTitle[side="A"] { color: #38BDF8; font-weight: 800; }
        QLabel#CompareRunsRunBadge[side="B"],
        QLabel#CompareRunsChooserTitle[side="B"] { color: #C084FC; font-weight: 800; }
        QPushButton#CompareRunsChangeButton,
        QPushButton#CompareRunsSwapButton,
        QPushButton#CompareRunsChooseStats,
        QPushButton#CompareRunsItemDetails,
        QPushButton#CompareRunsInventoryToggle,
        QPushButton#CompareRunsSeriesSlot,
        QPushButton#CompareRunsAxisMode {
            background-color: #141A22;
            color: #B9C2CE;
            border: 1px solid #2A3542;
            border-radius: 7px;
            padding: 5px 9px;
        }
        QPushButton#CompareRunsAxisMode:checked {
            color: #FFFFFF;
            background-color: #2F6FB0;
            border-color: #3E82C6;
        }
        QListWidget#CompareRunsRecordingList[side="A"]::item:selected {
            background-color: rgba(56, 189, 248, 0.12);
            border-left: 2px solid #38BDF8;
        }
        QListWidget#CompareRunsRecordingList[side="B"]::item:selected {
            background-color: rgba(192, 132, 252, 0.12);
            border-left: 2px solid #C084FC;
        }
        QListWidget#CompareRunsRecordingList::item {
            border-bottom: 1px solid #1B222B;
            padding: 0;
        }
        QListWidget#CompareRunsRecordingList::item:disabled {
            color: #5C6675;
            padding: 8px 9px;
        }
        QFrame#CompareRunsComparisonCard {
            background-color: #0B0F14;
            border: 1px solid #1B222B;
            border-radius: 10px;
        }
        QFrame#CompareRunsComparisonCardHeader {
            background: transparent;
            border: none;
            border-bottom: 1px solid #1B222B;
        }
        QLabel#CompareRunsComparisonCardBadge {
            color: #A9D9FF;
            background-color: #152231;
            border: none;
            border-radius: 6px;
            min-width: 22px;
            min-height: 22px;
            max-width: 22px;
            max-height: 22px;
            font-size: 13px;
            font-weight: 800;
        }
        QLabel#CompareRunsComparisonCardTitle {
            color: #EDF1F5;
            background: transparent;
            font-size: 15px;
            font-weight: 800;
        }
        QLabel#CompareRunsComparisonCardMeta {
            color: #8A94A3;
            background: transparent;
            font-size: 12px;
        }
        QLabel#CompareRunsMetricLabel {
            color: #8A94A3;
            background: transparent;
            font-size: 13px;
            font-weight: 700;
        }
        QLabel#CompareRunsCompactMetricEmpty {
            color: #8A94A3;
            background: transparent;
        }
        QWidget#CompareRunsStageCards,
        QWidget#CompareRunsCompactMetricCards {
            background: transparent;
            border: none;
        }
        QWidget#CompareRunsComparisonMetrics {
            background-color: #1B222B;
            border: none;
        }
        QFrame#CompareRunsMetricCell {
            background-color: #0B0F14;
            border: none;
        }
        QLabel#CompareRunsMetricRunLabel {
            background: transparent;
            font-size: 12px;
            font-weight: 900;
        }
        QLabel#CompareRunsMetricRunLabel[side="A"] {
            color: #38BDF8;
        }
        QLabel#CompareRunsMetricRunLabel[side="B"] {
            color: #C084FC;
        }
        QLabel#CompareRunsMetricValue {
            color: #EDF1F5;
            background: transparent;
            font-size: 15px;
        }
        QLabel#CompareRunsMetricDelta {
            color: #EDF1F5;
            background: transparent;
            font-size: 13px;
            font-weight: 800;
        }
    """

    # `compatibility_stylesheet` declares `QLabel, QCheckBox, QRadioButton
    # { background: transparent; }` near its top, but Qt's cascade treats
    # every bare type selector as equal specificity and lets *declaration
    # order* break the tie -- so the redesign sheet's later, unrelated
    # `QWidget { background-color: ...; }` silently wins for every QLabel in
    # the app, transparent-by-design or not. That was the real "seam" bug:
    # not individual widgets missing a local override, but this rule losing
    # the cascade for all of them at once. Restating it last, after both base
    # sheets, is what makes it actually win.
    transparency_stylesheet = """
        QLabel, QCheckBox, QRadioButton {
            background: transparent;
        }
    """

    # Compatibility fills selectors that the existing widgets still need;
    # the design asset comes last so every v3 rule remains authoritative,
    # and the uniform checkbox/spinner/transparency rules come last of all
    # so nothing upstream of them can leave a tab's controls looking
    # different from the rest.
    return "\n".join(
        (
            compatibility_stylesheet,
            base_stylesheet,
            checkbox_uniform_stylesheet,
            spinner_uniform_stylesheet,
            compare_runs_compatibility_stylesheet,
            transparency_stylesheet,
        )
    )
