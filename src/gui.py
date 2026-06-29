from __future__ import annotations

import sys
import types

import gui_app as _gui_app
import gui_dialogs as _gui_dialogs
import gui_layout as _gui_layout
import gui_overlay as _gui_overlay
import gui_player_stats as _gui_player_stats
import gui_run_control as _gui_run_control
import gui_scanner as _gui_scanner
import gui_shared as _gui_shared
import gui_styles as _gui_styles
import gui_templates as _gui_templates

from gui_app import MegabonkApp
from gui_dialogs import *
from gui_layout import GuiLayoutMixin
from gui_overlay import OverlayMixin
from gui_player_stats import PlayerStatsMixin, _set_items_text
from gui_run_control import RunControlMixin
from gui_scanner import ScannerMixin
from gui_shared import *
from gui_shared import (
    _AppWindow,
    _apply_button_icon,
    _clear_layout,
    _clear_text_input,
    _make_scroll_section,
    _read_bool,
    _read_text,
    _safe_float,
    _set_bool,
    _set_text,
    _set_text_input,
)
from gui_styles import *
from gui_styles import (
    _button_state_stylesheet,
    _fold_item_name_for_rarity,
    _session_stats_label_stylesheet,
    _template_checkbox_stylesheet,
    _template_color_hex,
    _template_manager_card_stylesheet,
    _template_manager_header_stylesheet,
    _tier_color,
)
from gui_templates import TemplatesMixin

# Compatibility exports for tests and existing extension points that patched gui.py globals.
import config
import ctypes
import os
import threading
import time
from memory import MemoryReadError, ModuleNotFoundError, ProcessNotFoundError
from runtime_stats import adapt_map_stats
from vod_storage import delete_vod, delete_vods_below_snapshot_count, list_vods, load_vod, rename_vod

keyboard = _gui_run_control.keyboard
win32gui = _gui_run_control.win32gui
win32process = _gui_run_control.win32process

_PATCH_COMPAT_MODULES = (
    _gui_app,
    _gui_dialogs,
    _gui_layout,
    _gui_overlay,
    _gui_player_stats,
    _gui_run_control,
    _gui_scanner,
    _gui_shared,
    _gui_styles,
    _gui_templates,
)


class _GuiFacadeModule(types.ModuleType):
    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        for module in _PATCH_COMPAT_MODULES:
            if hasattr(module, name):
                setattr(module, name, value)


sys.modules[__name__].__class__ = _GuiFacadeModule

__all__ = [
    "MegabonkApp",
    "GuiLayoutMixin",
    "OverlayMixin",
    "RunControlMixin",
    "TemplatesMixin",
    "PlayerStatsMixin",
    "ScannerMixin",
    "TemplateFormFrame",
    "TemplateDialog",
    "TemplateManagerDialog",
    "ScoresSettingsDialog",
    "DeleteDialog",
    "ConfirmDeleteRecordingDialog",
    "CleanupRecordingsDialog",
    "HelpDialog",
    "SettingsDialog",
    "UiInvoker",
    "_AppWindow",
    "enable_windows_dpi_awareness",
    "resource_path",
    "_read_text",
    "_set_text",
    "_set_items_text",
    "_clear_text_input",
    "_set_text_input",
    "_read_bool",
    "_set_bool",
    "_safe_float",
    "_clear_layout",
    "_apply_button_icon",
    "_make_scroll_section",
    "format_template_conditions",
    "build_template_payload",
    "build_qt_app_stylesheet",
    "COLOR_MAP",
    "ITEM_DISPLAY_NAME_ALIASES",
    "ITEM_RARITY_BY_NAME",
    "ITEM_RARITY_COLOR_MAP",
    "ITEM_RARITY_FOLDED_NAME_ALIASES",
    "ITEM_RARITY_NAME_ALIASES",
    "ITEM_RARITY_NAME_BY_FOLDED_NAME",
    "ITEM_RARITY_SORT_ORDER",
    "ITEM_SORT_DEFAULT",
    "ITEM_SORT_LABELS",
    "ITEM_SORT_RARITY_ASC",
    "ITEM_SORT_RARITY_DESC",
    "PLAYER_STATS_ACTIVE_BUTTON_COLOR",
    "PLAYER_STATS_ACTIVE_BUTTON_HOVER_COLOR",
    "PLAYER_STATS_INACTIVE_BUTTON_COLOR",
    "PLAYER_STATS_INACTIVE_BUTTON_HOVER_COLOR",
    "PLAYER_STATS_ITEM_DROP_CONFIRMATION_SNAPSHOTS",
    "PLAYER_STATS_ITEMS_WRAP_LENGTH",
    "PLAYER_STATS_LABEL_FONT_SIZE",
    "PLAYER_STATS_RECORDING_SEED_GRACE_SECONDS",
    "PLAYER_STATS_REFRESH_MS",
    "PLAYER_STATS_RUN_TIMER_RESET_TOLERANCE_SECONDS",
    "PLAYER_STATS_STAGE4_TIMER_JUMP_SECONDS",
    "PLAYER_STATS_STAGE_TRANSITION_BOUNDARY_SECONDS",
    "PLAYER_STATS_VALUE_FONT_SIZE",
    "PLAYER_STATS_VALUE_WIDTH",
    "_button_state_stylesheet",
    "_fold_item_name_for_rarity",
    "_session_stats_label_stylesheet",
    "_template_checkbox_stylesheet",
    "_template_color_hex",
    "_template_manager_card_stylesheet",
    "_template_manager_header_stylesheet",
    "_tier_color",
    "config",
    "ctypes",
    "keyboard",
    "os",
    "threading",
    "time",
    "win32gui",
    "win32process",
    "MemoryReadError",
    "ModuleNotFoundError",
    "ProcessNotFoundError",
    "adapt_map_stats",
    "delete_vod",
    "delete_vods_below_snapshot_count",
    "list_vods",
    "load_vod",
    "rename_vod",
]