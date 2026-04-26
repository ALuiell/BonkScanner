import os
import sys
import ctypes
from ctypes import wintypes
import threading
import time
import datetime
import subprocess
import customtkinter as ctk
from PIL import Image

import updater
import config
import logic
from game_data import EItem, GameDataClient
from hook_loader import HookLoadError, HookProcessNotFoundError, HookProcessNotReadyError, NativeHookLoader
from memory import MemoryReadError, ModuleNotFoundError, ProcessNotFoundError
from run_control import HookRunControlProvider, KeyboardRunControlProvider, RunControlError
from runtime_stats import adapt_map_stats

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

ctk.set_appearance_mode("dark")

# Helper function to get correct path for bundled files in PyInstaller
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    base_path = getattr(sys, '_MEIPASS', os.path.abspath("."))
    return os.path.join(base_path, relative_path)

# Map text color names to hex colors for CustomTkinter
COLOR_MAP = {
    "WHITE": "#FFFFFF",
    "CYAN": "#00FFFF",
    "GREEN": "#55FF55",
    "YELLOW": "#FFFF55",
    "LIGHTRED_EX": "#FF6666",
    "RED": "#FF4444",
    "MAGENTA": "#FF55FF",
    "BLUE": "#5DADE2",
    "LIGHTBLUE_EX": "#85C1E9",
    "DEFAULT": "#FFFFFF"
}

#[GlovePower, SoulHarvester, SpicyMeatball, CursedDoll, MoldyCheese, Oats]

REQUIRED_SHADY_GUY_ITEMS = frozenset(
    {
        EItem.SoulHarvester.name
    }
)


def center_toplevel(window, parent, width: int, height: int) -> None:
    """Center a modal dialog relative to its parent when possible."""
    window.update_idletasks()

    if parent is not None and parent.winfo_exists():
        parent_x = parent.winfo_x()
        parent_y = parent.winfo_y()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()
        x = parent_x + max((parent_width - width) // 2, 0)
        y = parent_y + max((parent_height - height) // 2, 0)
    else:
        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()
        x = max((screen_width - width) // 2, 0)
        y = max((screen_height - height) // 2, 0)

    window.geometry(f"{width}x{height}+{x}+{y}")

class TemplateDialog(ctk.CTkToplevel):
    def __init__(self, parent, edit_template=None):
        super().__init__(parent)
        self.title("Edit Template" if edit_template else "New Template")
        self.geometry("340x420")
        self.resizable(False, False)
        self.result = None
        self.edit_template = edit_template
        
        # Set icon if available
        icon_path = resource_path("media/bonkscanner_icon.ico")
        if os.path.exists(icon_path):
            self.after(200, lambda p=icon_path: self.iconbitmap(p))
        
        self.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(self, text="Template Name:").grid(row=0, column=0, padx=10, pady=(15, 5), sticky="w")
        self.name_entry = ctk.CTkEntry(self)
        self.name_entry.grid(row=0, column=1, padx=10, pady=(15, 5), sticky="ew")
        
        self.sm_var = ctk.StringVar(value="0")
        self.shady_var = ctk.StringVar(value="0")
        self.moai_var = ctk.StringVar(value="0")
        
        # Auto-calculate S+M Total when Shady or Moai changes
        self.shady_var.trace_add("write", self.update_sm_total)
        self.moai_var.trace_add("write", self.update_sm_total)
        
        ctk.CTkLabel(self, text="S+M Total (optional):").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.sm_entry = ctk.CTkEntry(self, textvariable=self.sm_var)
        self.sm_entry.grid(row=1, column=1, padx=10, pady=5, sticky="ew")
        
        ctk.CTkLabel(self, text="Shady Guy (min):").grid(row=2, column=0, padx=10, pady=5, sticky="w")
        self.shady_entry = ctk.CTkEntry(self, textvariable=self.shady_var)
        self.shady_entry.grid(row=2, column=1, padx=10, pady=5, sticky="ew")
        
        ctk.CTkLabel(self, text="Moais (min):").grid(row=3, column=0, padx=10, pady=5, sticky="w")
        self.moai_entry = ctk.CTkEntry(self, textvariable=self.moai_var)
        self.moai_entry.grid(row=3, column=1, padx=10, pady=5, sticky="ew")
        
        ctk.CTkLabel(self, text="Microwaves (min):").grid(row=4, column=0, padx=10, pady=5, sticky="w")
        self.micro_entry = ctk.CTkEntry(self)
        self.micro_entry.grid(row=4, column=1, padx=10, pady=5, sticky="ew")
        
        ctk.CTkLabel(self, text="Boss Curses (min):").grid(row=5, column=0, padx=10, pady=5, sticky="w")
        self.boss_entry = ctk.CTkEntry(self)
        self.boss_entry.grid(row=5, column=1, padx=10, pady=5, sticky="ew")
        
        # Populate if editing
        if edit_template:
            self.name_entry.insert(0, edit_template.get("name", ""))
            # If default template, protect name change
            if edit_template.get("id", 100) <= 7:
                self.name_entry.configure(state="disabled")
                
            self.sm_var.set(str(edit_template.get("sm_total", 0)))
            self.shady_var.set(str(edit_template.get("shady", 0)))
            self.moai_var.set(str(edit_template.get("moai", 0)))
            
            self.micro_entry.insert(0, str(edit_template.get("micro", 0)))
            self.boss_entry.insert(0, str(edit_template.get("boss", 0)))
        else:
            self.sm_var.set("0")
            self.shady_var.set("0")
            self.moai_var.set("0")
            
            self.micro_entry.insert(0, "0")
            self.boss_entry.insert(0, "0")
        
        self.save_btn = ctk.CTkButton(self, text="Save Template", command=self.save, fg_color="#2FA572", hover_color="#106A43")
        self.save_btn.grid(row=6, column=0, columnspan=2, pady=20)
        
        # Make modal
        self.transient(parent)
        self.grab_set()

    def update_sm_total(self, *_):
        try:
            s_val = self.shady_var.get().strip()
            m_val = self.moai_var.get().strip()
            s = int(s_val) if s_val.isdigit() else 0
            m = int(m_val) if m_val.isdigit() else 0
            
            # If user explicitly entered a shady or moai value, automatically update S+M total
            if s > 0 or m > 0:
                self.sm_var.set(str(s + m))
        except ValueError:
            pass
        
    def save(self):
        name = self.name_entry.get().strip()
        if not name:
            return
            
        def get_int(entry):
            val = entry.get().strip()
            return int(val) if val.isdigit() else 0
            
        self.result = {
            "name": name,
            "sm_total": get_int(self.sm_entry),
            "shady": get_int(self.shady_entry),
            "moai": get_int(self.moai_entry),
            "micro": get_int(self.micro_entry),
            "boss": get_int(self.boss_entry)
        }
        
        # Drop sm_total if 0 or if individual values are defined so logic handles explicit shady/moai cleanly
        s = self.result["shady"]
        m = self.result["moai"]
        if self.result["sm_total"] <= 0 or (s > 0 or m > 0):
            if "sm_total" in self.result:
                del self.result["sm_total"]
        
        if self.edit_template:
            # Preserve properties like color, id when editing
            for k, v in self.edit_template.items():
                if k not in self.result and k not in ["sm_total", "shady", "moai", "micro", "boss"]:
                    self.result[k] = v
            
        self.destroy()

class ScoresSettingsDialog(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Scores Settings")
        self.geometry("420x650")
        self.resizable(False, False)
        
        icon_path = resource_path("media/bonkscanner_icon.ico")
        if os.path.exists(icon_path):
            self.after(200, lambda p=icon_path: self.iconbitmap(p))
            
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        # Create a scrollable frame for the entire window
        self.scroll_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll_frame.grid(row=0, column=0, sticky="nsew")
        self.scroll_frame.grid_columnconfigure(1, weight=1)

        self.row_idx = 0
        
        # ACTIVE TIERS
        ctk.CTkLabel(self.scroll_frame, text="Active Tiers:", font=ctk.CTkFont(weight="bold")).grid(row=self.row_idx, column=0, columnspan=2, pady=(10, 5), sticky="w", padx=10)
        self.row_idx += 1
        
        self.tier_vars = {}
        for tier in ["Light", "Good", "Perfect", "Perfect+"]:
            var = ctk.BooleanVar(value=tier in config.SCORES_SYSTEM.get("active_tiers", []))
            cb = ctk.CTkCheckBox(self.scroll_frame, text=tier, variable=var)
            cb.grid(row=self.row_idx, column=0, columnspan=2, padx=20, pady=2, sticky="w")
            self.tier_vars[tier] = var
            self.row_idx += 1

        # THRESHOLDS CONFIGURATION
        ctk.CTkLabel(self.scroll_frame, text="Thresholds:", font=ctk.CTkFont(weight="bold")).grid(row=self.row_idx, column=0, columnspan=2, pady=(15, 5), sticky="w", padx=10)
        self.row_idx += 1
        
        # Mode Switch
        self.manual_thresholds_var = ctk.BooleanVar(value=config.SCORES_SYSTEM.get("manual_thresholds", False))
        self.manual_cb = ctk.CTkCheckBox(self.scroll_frame, text="Manual Thresholds", variable=self.manual_thresholds_var, command=self.toggle_thresholds_mode)
        self.manual_cb.grid(row=self.row_idx, column=0, columnspan=2, padx=20, pady=5, sticky="w")
        self.row_idx += 1

        self.threshold_entries = {}
        thresholds = config.SCORES_SYSTEM.get("thresholds", {})
        for tier in ["Light", "Good", "Perfect", "Perfect+"]:
            lbl = ctk.CTkLabel(self.scroll_frame, text=f"{tier}:")
            lbl.grid(row=self.row_idx, column=0, padx=30, pady=2, sticky="w")
            entry = ctk.CTkEntry(self.scroll_frame, width=100)
            entry.insert(0, str(thresholds.get(tier, 0)))
            entry.grid(row=self.row_idx, column=1, padx=10, pady=2, sticky="w")
            self.threshold_entries[tier] = entry
            self.row_idx += 1
            
        # WEIGHTS
        ctk.CTkLabel(self.scroll_frame, text="Weights:", font=ctk.CTkFont(weight="bold")).grid(row=self.row_idx, column=0, columnspan=2, pady=(15, 5), sticky="w", padx=10)
        self.row_idx += 1
        
        self.weight_entries = {}
        self.weight_vars = {}
        weights = config.SCORES_SYSTEM.get("weights", {})
        for key in ["moais", "shady", "boss", "magnet"]:
            ctk.CTkLabel(self.scroll_frame, text=f"{key.capitalize()}:").grid(row=self.row_idx, column=0, padx=20, pady=2, sticky="w")
            entry = ctk.CTkEntry(self.scroll_frame, width=100)
            entry.insert(0, str(weights.get(key, 0)))
            entry.grid(row=self.row_idx, column=1, padx=10, pady=2, sticky="w")
            
            var = ctk.StringVar(value=entry.get())
            entry.configure(textvariable=var)
            var.trace_add("write", self.auto_update_thresholds)
            self.weight_vars[key] = var
            self.weight_entries[key] = entry
            self.row_idx += 1
            
        # MULTIPLIERS
        ctk.CTkLabel(self.scroll_frame, text="Microwave Multipliers:", font=ctk.CTkFont(weight="bold")).grid(row=self.row_idx, column=0, columnspan=2, pady=(15, 5), sticky="w", padx=10)
        self.row_idx += 1
        
        self.mult_entries = {}
        self.mult_vars = {}
        multipliers = config.SCORES_SYSTEM.get("multipliers", {}).get("microwave", {})
        for key in ["1", "2"]:
            ctk.CTkLabel(self.scroll_frame, text=f"{key} Microwave(s):").grid(row=self.row_idx, column=0, padx=20, pady=2, sticky="w")
            entry = ctk.CTkEntry(self.scroll_frame, width=100)
            entry.insert(0, str(multipliers.get(key, 1.0)))
            entry.grid(row=self.row_idx, column=1, padx=10, pady=2, sticky="w")
            
            var = ctk.StringVar(value=entry.get())
            entry.configure(textvariable=var)
            var.trace_add("write", self.auto_update_thresholds)
            self.mult_vars[key] = var
            self.mult_entries[key] = entry
            self.row_idx += 1

        # BUTTONS
        self.buttons_frame = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
        self.buttons_frame.grid(row=self.row_idx, column=0, columnspan=2, pady=20)
        
        self.reset_btn = ctk.CTkButton(self.buttons_frame, text="Reset to Defaults", command=self.reset_to_defaults, fg_color="#b30000", hover_color="#800000", width=140)
        self.reset_btn.grid(row=0, column=0, padx=10)

        self.save_btn = ctk.CTkButton(self.buttons_frame, text="Save Settings", command=self.save, fg_color="#2FA572", hover_color="#106A43", width=140)
        self.save_btn.grid(row=0, column=1, padx=10)
        
        self.toggle_thresholds_mode() # Initialize state
        
        self.transient(parent)
        self.grab_set()

    def reset_to_defaults(self):
        default_sys = config.DEFAULT_SCORES_SYSTEM
            
        # Reset Manual mode
        self.manual_thresholds_var.set(default_sys["manual_thresholds"])
        
        # Reset Weights
        for key in ["moais", "shady", "boss", "magnet"]:
            self.weight_vars[key].set(str(default_sys["weights"].get(key, 0)))
            
        # Reset Multipliers
        for key in ["1", "2"]:
            self.mult_vars[key].set(str(default_sys["multipliers"]["microwave"].get(key, 1.0)))
            
        # Reset Thresholds
        self.toggle_thresholds_mode() # this will re-enable manual threshold entries if needed
        for tier in ["Light", "Good", "Perfect", "Perfect+"]:
            if self.manual_thresholds_var.get():
                 self.threshold_entries[tier].configure(state="normal")
            self.threshold_entries[tier].delete(0, 'end')
            self.threshold_entries[tier].insert(0, str(default_sys["thresholds"].get(tier, 0)))
            
        # Ensure auto update logic finishes state sync
        self.toggle_thresholds_mode() 
        
    def auto_update_thresholds(self, *_):
        if self.manual_thresholds_var.get():
            return
            
        try:
            current_weights = {}
            for key, var in self.weight_vars.items():
                val = var.get().strip()
                if val: current_weights[key] = float(val)
                else: current_weights[key] = 0.0

            current_mults = {"microwave": {}}
            for key, var in self.mult_vars.items():
                val = var.get().strip()
                if val: current_mults["microwave"][key] = float(val)
                else: current_mults["microwave"][key] = 1.0

            scaled = config.calculate_auto_thresholds(current_weights, current_mults)
            
            for tier, entry in self.threshold_entries.items():
                entry.configure(state="normal")
                entry.delete(0, 'end')
                entry.insert(0, str(scaled.get(tier, 0)))
                entry.configure(state="disabled")
        except ValueError:
            pass

    def toggle_thresholds_mode(self):
        is_manual = self.manual_thresholds_var.get()
        if is_manual:
            for entry in self.threshold_entries.values():
                entry.configure(state="normal")
        else:
            for entry in self.threshold_entries.values():
                entry.configure(state="disabled")
            self.auto_update_thresholds()
        
    def save(self):
        is_manual = self.manual_thresholds_var.get()
            
        thresholds = {}
        for tier, entry in self.threshold_entries.items():
            # If in auto mode, temporarily enable to read the value correctly just in case
            if not is_manual:
                entry.configure(state="normal")
            try: thresholds[tier] = float(entry.get())
            except ValueError: thresholds[tier] = config.SCORES_SYSTEM["thresholds"].get(tier, 0)
            if not is_manual:
                entry.configure(state="disabled")
            
        weights = {}
        for key, entry in self.weight_entries.items():
            try: weights[key] = float(entry.get())
            except ValueError: weights[key] = config.SCORES_SYSTEM["weights"].get(key, 0)
            
        multipliers = {}
        for key, entry in self.mult_entries.items():
            try: multipliers[key] = float(entry.get())
            except ValueError: multipliers[key] = config.SCORES_SYSTEM["multipliers"]["microwave"].get(key, 1.0)
            
        config.SCORES_SYSTEM["manual_thresholds"] = is_manual
        config.SCORES_SYSTEM["thresholds"] = thresholds
        config.SCORES_SYSTEM["weights"] = weights
        config.SCORES_SYSTEM["multipliers"]["microwave"] = multipliers
        
        config.user_config["SCORES_SYSTEM"] = config.SCORES_SYSTEM
        config.save_config(config.user_config)
        
        if hasattr(self.master, 'log'):
            self.master.log("[*] Scores settings saved!", tag="success")
            
        # If active mode is scores, refresh the checkbox active states in case they changed
        if config.EVALUATION_MODE == "scores":
            if hasattr(self.master, 'refresh_scores_templates_list'):
                self.master.refresh_scores_templates_list()
        
        self.destroy()

class DeleteDialog(ctk.CTkToplevel):
    def __init__(self, parent, custom_templates):
        super().__init__(parent)
        self.title("Delete Template")
        self.geometry("280x160")
        self.resizable(False, False)
        self.result = None
        
        # Set icon if available
        icon_path = resource_path("media/bonkscanner_icon.ico")
        if os.path.exists(icon_path):
            self.after(200, lambda p=icon_path: self.iconbitmap(p))
        
        self.combo = ctk.CTkComboBox(self, values=[t['name'] for t in custom_templates])
        self.combo.pack(pady=(30, 10), padx=20, fill="x")
        
        self.btn = ctk.CTkButton(self, text="Delete", fg_color="#b30000", hover_color="#800000", command=self.delete)
        self.btn.pack(pady=10)
        
        self.transient(parent)
        self.grab_set()
        
    def delete(self):
        self.result = self.combo.get()
        self.destroy()


class NativeHookWarningDialog(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.result = False
        self.title("Native Hook Warning")
        self.resizable(False, False)

        icon_path = resource_path("media/bonkscanner_icon.ico")
        if os.path.exists(icon_path):
            self.after(200, lambda p=icon_path: self.iconbitmap(p))

        center_toplevel(self, parent, 440, 260)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.protocol("WM_DELETE_WINDOW", self.cancel)

        header = ctk.CTkFrame(self, fg_color="#3B2A18", corner_radius=10)
        header.grid(row=0, column=0, padx=18, pady=(18, 10), sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Enable Native Hook Restart?",
            font=ctk.CTkFont(size=17, weight="bold"),
            text_color="#F6C56F",
        ).grid(row=0, column=0, padx=14, pady=(12, 4), sticky="w")

        ctk.CTkLabel(
            header,
            text="This enables a lower-level memory restart path. Using this mode may not be considered entirely fair and could have consequences.",
            justify="left",
            wraplength=380,
            text_color="#E8E8E8",
        ).grid(row=1, column=0, padx=14, pady=(0, 12), sticky="w")

        ctk.CTkLabel(
            self,
            text="You can safely switch back to standard keyboard restart at any time from Settings.\n\nThis dialog will appear whenever the native hook option is turned on.",
            justify="left",
            wraplength=396,
            text_color="#CFCFCF",
        ).grid(row=1, column=0, padx=22, pady=(0, 16), sticky="nw")

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=2, column=0, padx=18, pady=(0, 18), sticky="sew")
        for column in range(2):
            buttons.grid_columnconfigure(column, weight=1)

        self.cancel_btn = ctk.CTkButton(
            buttons,
            text="Cancel",
            fg_color="#b30000",
            hover_color="#800000",
            command=self.cancel,
        )
        self.cancel_btn.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        self.continue_btn = ctk.CTkButton(
            buttons,
            text="Continue",
            fg_color="#2FA572",
            hover_color="#106A43",
            command=self.confirm,
        )
        self.continue_btn.grid(row=0, column=1, padx=(8, 0), sticky="ew")

        self.transient(parent)
        self.grab_set()

    def confirm(self):
        self.result = True
        self.destroy()

    def cancel(self):
        self.result = False
        self.destroy()


class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Settings")
        self.geometry("400x390")
        self.resizable(False, False)
        self._native_hook_toggle_guard = False
        
        # Set icon if available
        icon_path = resource_path("media/bonkscanner_icon.ico")
        if os.path.exists(icon_path):
            self.after(200, lambda p=icon_path: self.iconbitmap(p))
            
        self.grid_columnconfigure(1, weight=1)
        
        # HOTKEY
        ctk.CTkLabel(self, text="Scan Hotkey:").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        self.hotkey_entry = ctk.CTkEntry(self)
        self.hotkey_entry.insert(0, config.HOTKEY)
        self.hotkey_entry.grid(row=0, column=1, padx=10, pady=10, sticky="ew")
        
        # RESET_HOTKEY
        ctk.CTkLabel(self, text="Reset Hotkey:").grid(row=1, column=0, padx=10, pady=10, sticky="w")
        self.reset_hotkey_entry = ctk.CTkEntry(self)
        self.reset_hotkey_entry.insert(0, config.RESET_HOTKEY)
        self.reset_hotkey_entry.grid(row=1, column=1, padx=10, pady=10, sticky="ew")
        
        # MIN_DELAY
        ctk.CTkLabel(self, text="Min Reroll Delay (s):").grid(row=2, column=0, padx=10, pady=10, sticky="w")
        self.min_delay_entry = ctk.CTkEntry(self)
        self.min_delay_entry.insert(0, str(config.MIN_DELAY))
        self.min_delay_entry.grid(row=2, column=1, padx=10, pady=10, sticky="ew")
        self.map_load_delay_entry = self.min_delay_entry
        
        # RESET_HOLD_DURATION
        ctk.CTkLabel(self, text="Reset Hold Duration (s):").grid(row=3, column=0, padx=10, pady=10, sticky="w")
        self.reset_hold_duration_entry = ctk.CTkEntry(self)
        self.reset_hold_duration_entry.insert(0, str(config.RESET_HOLD_DURATION))
        self.reset_hold_duration_entry.grid(row=3, column=1, padx=10, pady=10, sticky="ew")

        self.native_hook_enabled_var = ctk.BooleanVar(value=getattr(config, "NATIVE_HOOK_ENABLED", True))
        self.native_hook_enabled_check = ctk.CTkCheckBox(
            self,
            text="Use native hook restart",
            variable=self.native_hook_enabled_var,
            command=self.on_native_hook_toggle,
        )
        self.native_hook_enabled_check.grid(row=4, column=0, columnspan=2, padx=10, pady=10, sticky="w")
        
        # Check for updates button
        self.update_btn = ctk.CTkButton(self, text="Check for Updates", fg_color="#1f538d", hover_color="#14375e", command=self.check_update)
        self.update_btn.grid(row=5, column=0, columnspan=2, pady=10)

        # SAVE BUTTON
        self.save_btn = ctk.CTkButton(self, text="Save", fg_color="#2FA572", hover_color="#106A43", command=self.save)
        self.save_btn.grid(row=6, column=0, columnspan=2, pady=10)
        
        self.transient(parent)
        self.grab_set()

    def _set_native_hook_checkbox_value(self, enabled: bool):
        self._native_hook_toggle_guard = True
        try:
            self.native_hook_enabled_var.set(enabled)
        finally:
            self._native_hook_toggle_guard = False

    def prompt_native_hook_enable_confirmation(self) -> bool:
        dialog = NativeHookWarningDialog(self)
        self.wait_window(dialog)
        return bool(dialog.result)

    def on_native_hook_toggle(self):
        if getattr(self, "_native_hook_toggle_guard", False):
            return

        if not bool(self.native_hook_enabled_var.get()):
            return

        if not SettingsDialog.prompt_native_hook_enable_confirmation(self):
            SettingsDialog._set_native_hook_checkbox_value(self, False)
        
    def check_update(self):
        # Force check updates, ignoring SKIPPED version
        threading.Thread(target=updater.check_and_update, args=(self.master, True), daemon=True).start()
        self.destroy()

    def save(self):
        new_hotkey = self.hotkey_entry.get().strip()
        new_reset_hotkey = self.reset_hotkey_entry.get().strip()
        native_hook_enabled = bool(self.native_hook_enabled_var.get())
        
        # Update values in user_config
        config.user_config["HOTKEY"] = new_hotkey
        config.user_config["RESET_HOTKEY"] = new_reset_hotkey
        config.user_config["NATIVE_HOOK_ENABLED"] = native_hook_enabled
        
        # Update module-level variables in config.py
        config.HOTKEY = new_hotkey
        config.RESET_HOTKEY = new_reset_hotkey
        config.NATIVE_HOOK_ENABLED = native_hook_enabled
        
        delay_entry = getattr(self, "min_delay_entry", None) or getattr(self, "map_load_delay_entry", None)
        try:
            new_delay = float(delay_entry.get())
            config.user_config["MIN_DELAY"] = new_delay
            config.MIN_DELAY = new_delay
            config.MAP_LOAD_DELAY = new_delay
        except ValueError:
            pass # Keep old value if new one is invalid
            
        try:
            new_duration = float(self.reset_hold_duration_entry.get())
            if new_duration < 0.01:
                new_duration = 0.01
            config.user_config["RESET_HOLD_DURATION"] = new_duration
            config.RESET_HOLD_DURATION = new_duration
            
            # Attempt to automatically update the game config to match, minus 0.05 seconds
            game_val = round(new_duration - 0.05, 2)
            if game_val < 0.01:
                game_val = 0.01
            config.update_game_reset_time(game_val)

        except ValueError:
            pass # Keep old value if new one is invalid
            
        # Save to file
        config.save_config(config.user_config)
        
        # Apply hotkey changes immediately without restart
        if hasattr(self.master, 'setup_hotkeys'):
            self.master.setup_hotkeys()
            self.master.update_status_ui()
            if hasattr(self.master, 'apply_run_control_mode'):
                self.master.apply_run_control_mode()
            self.master.log("[*] Settings saved and applied successfully!", tag="success")
            
        self.destroy()


class MegabonkApp(ctk.CTk):
    @staticmethod
    def item_name(item: object) -> str:
        return str(getattr(item, "name", item))

    @classmethod
    def has_required_shady_guy_item(cls, items: list[object]) -> bool:
        return any(cls.item_name(item) in REQUIRED_SHADY_GUY_ITEMS for item in items)

    def __init__(self):
        super().__init__()
        
        self.title(f"BonkScanner v{updater.CURRENT_VERSION}")
        self.geometry("1150x550")
        self.minsize(1050, 500)
        
        # Initialize attributes that might be flagged as defined outside __init__
        self.top_frame = None
        self.logo_label = None
        
        self.left_frame = None
        self.left_tabview = None
        self.tab_templates = None
        self.tab_scores = None
        
        self.scrollable_templates = None
        self.template_btns_frame = None
        self.add_btn = None
        self.edit_btn = None
        self.del_btn = None
        
        self.scores_templates_frame = None
        self.scores_scroll_desc = None
        self.scores_desc_label = None
        self.scores_btns_frame = None
        self.edit_scores_btn = None
        self.scores_separator = None
        
        self.right_frame = None
        self.tabview = None
        self.tab_logs = None
        self.tab_stats = None
        self.log_box = None
        self.stats_scroll = None
        self.stats_time_label = None
        self.stats_rerolls_label = None
        self.stats_rpm_label = None
        self.stats_best_label = None
        self.stats_worst_label = None
        self.stats_avg_frame = None
        self.controls_frame = None
        self.settings_btn = None
        self.status_label = None
        self.toggle_btn = None
        
        icon_path = resource_path("media/bonkscanner_icon.ico")
        if os.path.exists(icon_path):
            self.iconbitmap(icon_path)
        
        self.is_running = False
        self.is_ready_to_start = False
        self.active_templates = []
        self.scanner_thread = None
        self.client = None
        self.native_hook_loader = None
        self.native_hook_thread = None
        self.native_hook_generation = 0
        self.run_control_provider = None
        self._native_hook_admin_warning_logged = False
        self.checkboxes = {}
        self.scores_checkboxes = {}
        
        self.animation_active = False
        self.animation_frame = 0
        
        # Threading events for efficient control
        self.stop_event = threading.Event()
        self.scan_event = threading.Event()
        
        # Session Stats
        self.session_start_time = None
        self.total_rerolls = 0
        self.best_map_stats = None
        self.best_map_score = -1
        self.worst_map_stats = None
        self.worst_map_score = float('inf')
        # Detailed stats per template: { 'Template Name': {'rerolls_since_last': 0, 'history': []} }
        self.template_stats = {}
        
        self.setup_ui()
        self.refresh_templates()
        self.refresh_scores_templates_list()
        self.refresh_scores_ui()
        self.setup_hotkeys()
        
        # Timer for updating elapsed time
        self.update_timer()
        
        self.check_admin_rights()
        self.log(f"[*] Welcome to BonkScanner v{updater.CURRENT_VERSION}!", tag="success")
        self.log(f"[*] Target Process: {config.PROCESS_NAME}")
        self.log(f"[*] Ready! Select templates and start the main process loop.")
        self.apply_run_control_mode(detach_hooks=False)

        # Check for updates AFTER the GUI has fully initialized and drawn
        # 1500 ms (1.5 seconds) delay ensures the user sees the window instantly
        self.after(1500, self.deferred_update_check)

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
                    result = previous_loader.uninitialize()
                    self.log(f"[+] Native hooks detached for PID {result.pid}.", tag="success")
                except HookProcessNotFoundError as exc:
                    self.log(f"[WAIT] Native hook detach skipped: {exc}", tag="warning")
                except HookLoadError as exc:
                    self.log(f"[WAIT] Native hook detach failed; switching to keyboard restart: {exc}", tag="warning")

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
        self.log("[*] Native hook restart control enabled.")

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
                    self.log(f"[*] Native hook already injected for PID {result.pid}.")
                else:
                    self.log(f"[+] Native hook injected into PID {result.pid}.", tag="success")
                return
            except HookProcessNotFoundError:
                if not logged_waiting:
                    self.log(f"[WAIT] Waiting for process '{config.PROCESS_NAME}' before native hook injection.")
                    logged_waiting = True
                self.stop_event.wait(1.0)
            except HookProcessNotReadyError as exc:
                if not logged_waiting:
                    self.log(f"[WAIT] {exc}")
                    logged_waiting = True
                self.stop_event.wait(1.0)
            except HookLoadError as exc:
                self.log(f"[-] Native hook injection failed: {exc}", tag="error")
                return
            except Exception as exc:
                self.log(f"[-] Unexpected native hook loader error: {exc}", tag="error")
                return

    def deferred_update_check(self):
        """Checks for updates after the main window is already visible."""
        threading.Thread(target=updater.check_and_update, args=(self, False), daemon=True).start()

    def check_admin_rights(self):
        if os.name != 'nt':
            return

        if not self.is_running_as_admin():
            if getattr(config, "NATIVE_HOOK_ENABLED", True):
                self.warn_if_native_hook_needs_admin()
                return

            self.log("⚠️ WARNING: Script is not running as Administrator!", tag="warning")
            self.log("⚠️ Hotkeys may not work while the game window is active.", tag="warning")

    def is_running_as_admin(self) -> bool:
        if os.name != 'nt':
            return True

        import ctypes
        try:
            return os.getuid() == 0
        except AttributeError:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0

    def warn_if_native_hook_needs_admin(self):
        if (
            getattr(config, "NATIVE_HOOK_ENABLED", True)
            and not getattr(self, "_native_hook_admin_warning_logged", False)
            and not self.is_running_as_admin()
        ):
            self.log("[*] Native hook may not inject without Administrator privileges; attempting anyway.", tag="warning")
            self._native_hook_admin_warning_logged = True

    def setup_ui(self):
        # Configure layout grid. Equal weight for left and right panels
        self.grid_columnconfigure(0, weight=1) 
        self.grid_columnconfigure(1, weight=1) 
        self.grid_rowconfigure(1, weight=1)
        
        # Load shared settings image
        self.settings_image = None
        settings_icon_path = resource_path("media/settings_icon.png")
        if os.path.exists(settings_icon_path):
            self.settings_image = ctk.CTkImage(light_image=Image.open(settings_icon_path),
                                               dark_image=Image.open(settings_icon_path),
                                               size=(20, 20))
                                               
        # --- Top Bar (Logo) ---
        self.top_frame = ctk.CTkFrame(self, height=80, fg_color="transparent")
        self.top_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.top_frame.grid_columnconfigure(0, weight=1)
        
        try:
            icon_path = resource_path("media/bonkscanner_icon.ico")
            if os.path.exists(icon_path):
                logo_image = ctk.CTkImage(light_image=Image.open(icon_path),
                                          dark_image=Image.open(icon_path),
                                          size=(40, 40))
                self.logo_label = ctk.CTkLabel(self.top_frame, image=logo_image, text=" BonkScanner", 
                                               font=ctk.CTkFont(size=24, weight="bold"))
                self.logo_label.grid(row=0, column=0, pady=5)
            else:
                self.logo_label = ctk.CTkLabel(self.top_frame, text="BonkScanner", 
                                               font=ctk.CTkFont(size=24, weight="bold"))
                self.logo_label.grid(row=0, column=0, pady=5)
        except Exception:
            self.logo_label = ctk.CTkLabel(self.top_frame, text="BonkScanner", 
                                           font=ctk.CTkFont(size=24, weight="bold"))
            self.logo_label.grid(row=0, column=0, pady=5)

        # --- Left Panel ---
        self.left_frame = ctk.CTkFrame(self)
        self.left_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        self.left_frame.grid_rowconfigure(0, weight=1)
        self.left_frame.grid_columnconfigure(0, weight=1)

        self.left_tabview = ctk.CTkTabview(self.left_frame, command=self.on_left_tab_changed)
        self.left_tabview.grid(row=0, column=0, padx=10, pady=(0, 10), sticky="nsew")
        
        self.tab_templates = self.left_tabview.add("Templates")
        self.tab_scores = self.left_tabview.add("Scores")
        
        # Select active tab based on config
        if config.EVALUATION_MODE == "scores":
            self.left_tabview.set("Scores")
        else:
            self.left_tabview.set("Templates")
            
        # -- Templates Tab Setup --
        self.tab_templates.grid_rowconfigure(0, weight=1)
        self.tab_templates.grid_columnconfigure(0, weight=1)
        
        self.scrollable_templates = ctk.CTkScrollableFrame(self.tab_templates, fg_color="transparent")
        self.scrollable_templates.grid(row=0, column=0, sticky="nsew")
        
        # Buttons frame (moved inside tab_templates)
        self.template_btns_frame = ctk.CTkFrame(self.tab_templates, fg_color="transparent")
        self.template_btns_frame.grid(row=1, column=0, padx=0, pady=(10, 0), sticky="ew")
        self.template_btns_frame.grid_columnconfigure((0, 4), weight=1)
        
        self.add_btn = ctk.CTkButton(self.template_btns_frame, text="+ Add", width=60, command=self.add_template_dialog)
        self.add_btn.grid(row=0, column=1, padx=5)
        
        self.edit_btn = ctk.CTkButton(self.template_btns_frame, text="✎ Edit", width=60, command=self.edit_template_dialog)
        self.edit_btn.grid(row=0, column=2, padx=5)
        
        self.del_btn = ctk.CTkButton(self.template_btns_frame, text="- Delete", width=60, fg_color="#b30000", hover_color="#800000", command=self.del_template_dialog)
        self.del_btn.grid(row=0, column=3, padx=5)
        
        # -- Scores Tab Setup --
        self.tab_scores.grid_rowconfigure(2, weight=1) # Row 2 is the scrollable desc frame
        self.tab_scores.grid_columnconfigure(0, weight=1)
        
        self.scores_templates_frame = ctk.CTkFrame(self.tab_scores, fg_color="transparent")
        self.scores_templates_frame.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        
        self.scores_separator = ctk.CTkFrame(self.tab_scores, height=2, fg_color=("gray70", "gray30"))
        self.scores_separator.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 5))
        
        self.scores_scroll_desc = ctk.CTkScrollableFrame(self.tab_scores, fg_color="transparent")
        self.scores_scroll_desc.grid(row=2, column=0, sticky="nsew")
        self.scores_scroll_desc.grid_columnconfigure(0, weight=1)
        
        self.scores_desc_label = ctk.CTkLabel(self.scores_scroll_desc, text="", justify="left", font=ctk.CTkFont(size=13))
        self.scores_desc_label.grid(row=0, column=0, sticky="nw", padx=10, pady=10)
        
        # Scores buttons frame (moved inside tab_scores)
        self.scores_btns_frame = ctk.CTkFrame(self.tab_scores, fg_color="transparent")
        self.scores_btns_frame.grid(row=3, column=0, padx=0, pady=(10, 0), sticky="ew")
        self.scores_btns_frame.grid_columnconfigure((0, 2), weight=1)
        
        if self.settings_image:
            self.edit_scores_btn = ctk.CTkButton(self.scores_btns_frame, text=" Edit Settings", image=self.settings_image, compound="left", command=self.open_scores_settings_dialog)
        else:
            self.edit_scores_btn = ctk.CTkButton(self.scores_btns_frame, text="⚙ Edit Settings", command=self.open_scores_settings_dialog)
            
        self.edit_scores_btn.grid(row=0, column=1)

        # --- Right Panel: Logs, Stats & Controls ---
        self.right_frame = ctk.CTkFrame(self)
        self.right_frame.grid(row=1, column=1, padx=(0, 10), pady=10, sticky="nsew")
        self.right_frame.grid_rowconfigure(0, weight=1) # Give row 0 (TabView) the most weight
        self.right_frame.grid_columnconfigure(0, weight=1)
        
        # TabView for Logs and Stats
        self.tabview = ctk.CTkTabview(self.right_frame)
        self.tabview.grid(row=0, column=0, padx=10, pady=(0, 10), sticky="nsew")
        
        self.tab_logs = self.tabview.add("Logs")
        self.tab_stats = self.tabview.add("Session Stats")
        
        self.tab_logs.grid_rowconfigure(0, weight=1)
        self.tab_logs.grid_columnconfigure(0, weight=1)
        self.tab_stats.grid_rowconfigure(0, weight=1)
        self.tab_stats.grid_columnconfigure(0, weight=1)
        
        # Log Textbox
        self.log_box = ctk.CTkTextbox(self.tab_logs, state="disabled", font=ctk.CTkFont(family="Consolas", size=13), wrap="none")
        self.log_box.grid(row=0, column=0, sticky="nsew")
        
        # Log tags config for colors
        self.log_box.tag_config("warning", foreground="#FFA500")
        self.log_box.tag_config("error", foreground="#FF4444")
        self.log_box.tag_config("success", foreground="#00FF00")
        
        # Add tags for specific profile colors
        for color_name, hex_code in COLOR_MAP.items():
            self.log_box.tag_config(color_name, foreground=hex_code)
            
        # Stats Elements
        self.stats_scroll = ctk.CTkScrollableFrame(self.tab_stats, fg_color="transparent")
        self.stats_scroll.grid(row=0, column=0, sticky="nsew")
        
        self.stats_time_label = ctk.CTkLabel(self.stats_scroll, text="Session Time: 00:00:00", font=ctk.CTkFont(size=15))
        self.stats_time_label.pack(anchor="w", pady=5)
        
        self.stats_rerolls_label = ctk.CTkLabel(self.stats_scroll, text="Total Rerolls: 0", font=ctk.CTkFont(size=15))
        self.stats_rerolls_label.pack(anchor="w", pady=5)
        
        self.stats_rpm_label = ctk.CTkLabel(self.stats_scroll, text="Rerolls per Minute (RPM): 0.0", font=ctk.CTkFont(size=15))
        self.stats_rpm_label.pack(anchor="w", pady=5)
        
        self.stats_best_label = ctk.CTkLabel(self.stats_scroll, text="Best Map Found: None", font=ctk.CTkFont(size=15))
        self.stats_best_label.pack(anchor="w", pady=5)
        
        self.stats_worst_label = ctk.CTkLabel(self.stats_scroll, text="Worst Map Found: None", font=ctk.CTkFont(size=15))
        self.stats_worst_label.pack(anchor="w", pady=5)
        
        ctk.CTkLabel(self.stats_scroll, text="\nAverage Rerolls per Target:", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", pady=5)
        self.stats_avg_frame = ctk.CTkFrame(self.stats_scroll, fg_color="transparent")
        self.stats_avg_frame.pack(fill="x", anchor="w")
        
        # Controls Setup
        self.controls_frame = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        self.controls_frame.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="ew")
        
        self.controls_frame.grid_columnconfigure(1, weight=1)
        
        if self.settings_image:
            self.settings_btn = ctk.CTkButton(self.controls_frame, text="", image=self.settings_image, width=35, height=35, command=self.open_settings_dialog)
        else:
            self.settings_btn = ctk.CTkButton(self.controls_frame, text="⚙", width=35, height=35, command=self.open_settings_dialog, font=ctk.CTkFont(size=18))

        self.settings_btn.grid(row=0, column=0, sticky="w")
        
        self.status_label = ctk.CTkLabel(self.controls_frame, text="Status: IDLE", font=ctk.CTkFont(family="Consolas", size=14, weight="bold"), text_color="#CCCCCC", width=250, anchor="w")
        self.status_label.grid(row=0, column=1, sticky="w", padx=20)
        
        self.toggle_btn = ctk.CTkButton(
            self.controls_frame, 
            text="START", 
            font=ctk.CTkFont(weight="bold"), 
            command=self.toggle_main_loop,
            height=35,
            width=120
        )
        self.toggle_btn.grid(row=0, column=2, sticky="e")

    def on_left_tab_changed(self):
        tab_name = self.left_tabview.get()
        config.EVALUATION_MODE = "scores" if tab_name == "Scores" else "templates"
        config.user_config["EVALUATION_MODE"] = config.EVALUATION_MODE
        config.save_config(config.user_config)
        self.log(f"[*] Switched to {config.EVALUATION_MODE} mode.")

    def refresh_scores_templates_list(self):
        for widget in self.scores_templates_frame.winfo_children():
            widget.destroy()
            
        self.scores_checkboxes.clear()
        
        active_tiers = config.SCORES_SYSTEM.get("active_tiers", [])
        colors = {
            "Light": "WHITE",
            "Good": "GREEN",
            "Perfect": "YELLOW",
            "Perfect+": "LIGHTRED_EX"
        }
        
        for tier in ["Light", "Good", "Perfect", "Perfect+"]:
            is_checked = tier in active_tiers
            cb_var = ctk.BooleanVar(value=is_checked)
            
            # Using partial to correctly capture current 'tier' variable
            from functools import partial
            def save_scores_active(t, *_):
                var = self.scores_checkboxes[t]
                active = config.SCORES_SYSTEM.get("active_tiers", [])
                if var.get() and t not in active:
                    active.append(t)
                elif not var.get() and t in active:
                    active.remove(t)
                config.SCORES_SYSTEM["active_tiers"] = active
                config.user_config["SCORES_SYSTEM"] = config.SCORES_SYSTEM
                config.save_config(config.user_config)
                self.refresh_scores_ui()
                
            cb_var.trace_add("write", partial(save_scores_active, tier))
            
            color_name = colors.get(tier, "WHITE")
            hex_color = COLOR_MAP.get(color_name, COLOR_MAP["DEFAULT"])
            
            cb = ctk.CTkCheckBox(
                self.scores_templates_frame,
                text=tier,
                variable=cb_var,
                font=ctk.CTkFont(size=13),
                text_color=hex_color
            )
            cb.pack(anchor="w", padx=10, pady=6)
            self.scores_checkboxes[tier] = cb_var

    def refresh_scores_ui(self):
        s = config.SCORES_SYSTEM
        desc = "Current Scores Settings:\n\n"
        
        desc += "Thresholds:\n"
        
        mode_text = "(Manual)" if s.get("manual_thresholds") else "(Auto-scaled)"
        desc += f"Mode: {mode_text}\n"
        
        for k, v in s.get("thresholds", {}).items():
            if k in s.get("active_tiers", []):
                desc += f"  • {k}: {v}+\n"
            
        desc += "\nWeights:\n"
        for k, v in s.get("weights", {}).items():
            desc += f"  • {k.capitalize()}: {v}\n"
            
        desc += "\nMicrowave Multiplier:\n"
        desc += f"  • 1 Microwave: x{s.get('multipliers', {}).get('microwave', {}).get('1', 1.0)}\n"
        desc += f"  • 2 Microwaves: x{s.get('multipliers', {}).get('microwave', {}).get('2', 1.25)}\n"
        
        desc += "\nSpecial Rules:\n"
        desc += "  • Perfect+ requires 2+ Microwaves.\n"
        desc += "  • Perfect requires either 2+ Microwaves,\n    OR 1 Microwave + S+M≥8 + Boss≥2."
            
        self.scores_desc_label.configure(text=desc)

    def open_scores_settings_dialog(self):
        dialog = ScoresSettingsDialog(self)
        self.wait_window(dialog)
        self.refresh_scores_templates_list()
        self.refresh_scores_ui()

    def save_checkbox_state(self, *_):
        # Called when any checkbox is toggled
        active = [name for name, var in self.checkboxes.items() if var.get()]
        config.ACTIVE_TEMPLATES = active
        config.user_config["ACTIVE_TEMPLATES"] = config.ACTIVE_TEMPLATES
        config.save_config(config.user_config)

    def refresh_templates(self):
        for widget in self.scrollable_templates.winfo_children():
            widget.destroy()
        
        self.checkboxes.clear()
        for t in config.TEMPLATES:
            # Assembly of stats description
            parts = []
            sm_total = t.get("sm_total", 0)
            shady = t.get("shady", 0)
            moai = t.get("moai", 0)
            micro = t.get("micro", 0)
            boss = t.get("boss", 0)
            
            if sm_total > 0:
                parts.append(f"S+M: {sm_total}")
                
            if shady > 0: parts.append(f"S:{shady}")
            if moai > 0: parts.append(f"M:{moai}")
            if micro > 0: parts.append(f"Mic:{micro}")
            if boss > 0: parts.append(f"B:{boss}")
            
            desc = ", ".join(parts) if parts else "Any"
            
            # Ensure text is colored appropriately
            color_name = t.get("color", "BLUE").upper()
            hex_color = COLOR_MAP.get(color_name, COLOR_MAP["DEFAULT"])
            
            # Restore state if it exists in ACTIVE_TEMPLATES, otherwise unchecked (if not first run)
            is_checked = t['name'] in config.ACTIVE_TEMPLATES
            cb_var = ctk.BooleanVar(value=is_checked)
            # Add trace to automatically save on toggle
            cb_var.trace_add("write", self.save_checkbox_state)
            
            cb = ctk.CTkCheckBox(
                self.scrollable_templates, 
                text=f"{t['name']} ({desc})",
                variable=cb_var,
                font=ctk.CTkFont(size=13),
                text_color=hex_color
            )
            cb.pack(anchor="w", padx=10, pady=6)
            self.checkboxes[t['name']] = cb_var

    def add_template_dialog(self):
        dialog = TemplateDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            new_id = max([t.get("id", 0) for t in config.TEMPLATES] + [0]) + 1
            dialog.result["id"] = new_id
            dialog.result["color"] = "BLUE" # user requested blue for custom profiles
            
            config.TEMPLATES.append(dialog.result)
            config.user_config["TEMPLATES"] = config.TEMPLATES
            
            # Ensure new template is added to active
            if dialog.result['name'] not in config.ACTIVE_TEMPLATES:
                config.ACTIVE_TEMPLATES.append(dialog.result['name'])
                config.user_config["ACTIVE_TEMPLATES"] = config.ACTIVE_TEMPLATES
                
            config.save_config(config.user_config)
            
            self.refresh_templates()
            self.log(f"[+] Created new template: {dialog.result['name']}", tag="success")
            
    def edit_template_dialog(self):
        select_dialog = DeleteDialog(self, config.TEMPLATES)
        select_dialog.title("Select Template to Edit")
        select_dialog.btn.configure(text="Edit", fg_color="#1f538d", hover_color="#14375e")
        self.wait_window(select_dialog)
        
        target_name = select_dialog.result
        if not target_name:
            return
            
        target_template = next((t for t in config.TEMPLATES if t["name"] == target_name), None)
        if not target_template:
            return
            
        dialog = TemplateDialog(self, edit_template=target_template)
        self.wait_window(dialog)
        
        if dialog.result:
            # Replace old template
            for i, t in enumerate(config.TEMPLATES):
                if t["name"] == target_name:
                    config.TEMPLATES[i] = dialog.result
                    break
                    
            config.user_config["TEMPLATES"] = config.TEMPLATES
            
            # Update check state mapping if name changed
            if target_name != dialog.result["name"]:
                if target_name in config.ACTIVE_TEMPLATES:
                    config.ACTIVE_TEMPLATES.remove(target_name)
                    config.ACTIVE_TEMPLATES.append(dialog.result["name"])
                    config.user_config["ACTIVE_TEMPLATES"] = config.ACTIVE_TEMPLATES
                    
            config.save_config(config.user_config)
                
            self.refresh_templates()
            self.log(f"[*] Edited template: {dialog.result['name']}", tag="success")

    def del_template_dialog(self):
        custom_templates = [t for t in config.TEMPLATES if t.get("id", 0) > 7]
        if not custom_templates:
            self.log("[-] No custom templates to delete. Built-in profiles are protected.", tag="warning")
            return
            
        dialog = DeleteDialog(self, custom_templates)
        self.wait_window(dialog)
        if dialog.result:
            config.TEMPLATES = [t for t in config.TEMPLATES if t['name'] != dialog.result]
            config.user_config["TEMPLATES"] = config.TEMPLATES
            
            if dialog.result in config.ACTIVE_TEMPLATES:
                config.ACTIVE_TEMPLATES.remove(dialog.result)
                config.user_config["ACTIVE_TEMPLATES"] = config.ACTIVE_TEMPLATES
                
            config.save_config(config.user_config)

            self.refresh_templates()
            self.log(f"[-] Deleted template: {dialog.result}", tag="warning")

    def open_settings_dialog(self):
        dialog = SettingsDialog(self)
        self.wait_window(dialog)

    def setup_hotkeys(self):
        if keyboard:
            try:
                # Always remove existing hotkeys before adding a new one
                keyboard.unhook_all()
                keyboard.add_hotkey(config.HOTKEY, self.hotkey_toggle_scanning)
            except Exception as e:
                self.log(f"Error binding hotkey {config.HOTKEY}: {e}", tag="error")
                
    def hotkey_toggle_scanning(self):
        if not self.is_ready_to_start:
            self.log(f"[WAIT] Scanner is not ready yet. Please wait for the game.", tag="warning")
            return
            
        self.is_running = not self.is_running
        if self.is_running:
            self.scan_event.set()
        else:
            self.scan_event.clear()
            
        status = "STARTED" if self.is_running else "STOPPED"
        self.log(f"\n[!!!] Script {status} via Hotkey", tag="success" if self.is_running else "warning")
        self.update_status_ui()
        
    def update_status_ui(self):
        if self.is_running:
            self.animation_active = True
            self.animate_scanner_indicator()
        else:
            self.animation_active = False
            if self.is_ready_to_start:
                self.status_label.configure(text=f"Status: GAME READY (Press {config.HOTKEY})")
                self.toggle_btn.configure(text="STOP", fg_color="#b30000", hover_color="#800000")
            else:
                self.status_label.configure(text="Status: WAITING FOR GAME...")
                if self.scanner_thread and self.scanner_thread.is_alive():
                    self.toggle_btn.configure(text="STOP", fg_color="#b30000", hover_color="#800000")
                else:
                    self.toggle_btn.configure(text="START", fg_color="#1f538d", hover_color="#14375e")
    
    def animate_scanner_indicator(self):
        if not self.animation_active:
            return
            
        frames = ["|", "/", "-", "\\"]
        char = frames[self.animation_frame]
        self.status_label.configure(text=f"Status: SCANNING {char}", text_color="#00FF00")
        self.toggle_btn.configure(text="PAUSE", fg_color="#b30000", hover_color="#800000")
        
        self.animation_frame = (self.animation_frame + 1) % len(frames)
        self.after(150, self.animate_scanner_indicator)

    def log(self, message, tag=None):
        self.log_box.configure(state="normal")
        
        # Split message if it's a mixed tag line (e.g. for colored template outputs)
        if isinstance(tag, list):
            for part, sub_tag in zip(message, tag):
                if sub_tag:
                    self.log_box.insert("end", part, sub_tag)
                else:
                    self.log_box.insert("end", part)
            self.log_box.insert("end", "\n")
        elif tag:
            self.log_box.insert("end", f"{message}\n", tag)
        else:
            self.log_box.insert("end", f"{message}\n")
            
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def toggle_main_loop(self):
        if self.scanner_thread is None or not self.scanner_thread.is_alive():
            self.log(f"\n[*] Starting monitor hook in {config.EVALUATION_MODE.upper()} mode...")
            
            if config.EVALUATION_MODE == "templates":
                # Start background process
                self.active_templates = [name for name, var in self.checkboxes.items() if var.get()]
                if not self.active_templates:
                    self.log("[-] Error: You must select at least one template!", tag="error")
                    return
                    
                # Format the active profiles with colors
                colored_parts = ["[*] Active profiles: "]
                colored_tags = [None]
                
                for i, name in enumerate(self.active_templates):
                    # Find color for this template
                    color_tag = "BLUE"
                    for t in config.TEMPLATES:
                        if t["name"] == name:
                            color_tag = t.get("color", "BLUE").upper()
                            break
                            
                    colored_parts.append(name)
                    colored_tags.append(color_tag)
                    
                    if i < len(self.active_templates) - 1:
                        colored_parts.append(", ")
                        colored_tags.append(None)
                
                self.log(colored_parts, tag=colored_tags)
                
                # Setup template stats for tracking
                self.template_stats = {name: {'rerolls_since_last': 0, 'history': []} for name in self.active_templates}
            else:
                # Scores mode
                active_tiers = config.SCORES_SYSTEM.get("active_tiers", [])
                if not active_tiers:
                    self.log("[-] Error: No active tiers selected in Scores mode!", tag="error")
                    return
                    
                self.log(f"[*] Active Tiers: {', '.join(active_tiers)}")
                self.template_stats = {name: {'rerolls_since_last': 0, 'history': []} for name in active_tiers}
            
            # Init Session Stats
            self.session_start_time = time.time()
            self.total_rerolls = 0
            self.best_map_stats = None
            self.best_map_score = -1
            self.worst_map_stats = None
            self.worst_map_score = float('inf')
            self.refresh_stats_ui()
            
            self.is_running = False
            self.is_ready_to_start = False
            self.scan_event.clear()
            self.stop_event.clear()
            self.scanner_thread = threading.Thread(target=self.background_loop, daemon=True)
            self.scanner_thread.start()
            self.update_status_ui()
        else:
            # Stop background process
            self.stop_event.set()
            self.scan_event.set() # Wake up the thread so it can exit
            self.is_running = False
            self.is_ready_to_start = False
            self.log("\n[*] Stopping monitor hook...")
            self.after(500, self.update_status_ui)

    @staticmethod
    def format_stats(stats: dict) -> str:
        shady = stats.get("Shady Guy", 0)
        moai = stats.get("Moais", 0)
        microwaves = logic.normalize_microwaves(stats.get("Microwaves"))
        boss = stats.get("Boss Curses", 0)
        magnet = stats.get("Magnet Shrines", 0)
        return f"Shady: {shady}, Moai: {moai}, Microwaves: {microwaves}, Boss: {boss}, Magnet: {magnet}, Score: {logic.calculate_score(stats, config.SCORES_SYSTEM):.1f}"
        
    @staticmethod
    def calculate_map_score(stats: dict) -> float:
        # Use the logic module's function which now uses the configured multipliers and weights
        return logic.calculate_score(stats, config.SCORES_SYSTEM)

    def evaluate_candidate(self, stats: dict) -> dict | None:
        if config.EVALUATION_MODE == "templates":
            return logic.find_matching_template(stats, self.active_templates, config.TEMPLATES)
        return logic.evaluate_map_by_scores(stats, config.SCORES_SYSTEM)

    def update_timer(self):
        if self.scanner_thread and self.scanner_thread.is_alive() and self.session_start_time:
            elapsed = int(time.time() - self.session_start_time)
            td = datetime.timedelta(seconds=elapsed)
            self.stats_time_label.configure(text=f"Session Time: {td}")
            
            if elapsed > 0 and self.total_rerolls > 0:
                rpm = (self.total_rerolls / elapsed) * 60
                self.stats_rpm_label.configure(text=f"Rerolls per Minute (RPM): {rpm:.1f}")
                
        # Schedule next update
        self.after(1000, self.update_timer)

    def refresh_stats_ui(self):
        self.stats_rerolls_label.configure(text=f"Total Rerolls: {self.total_rerolls}")
        
        if self.best_map_stats:
            self.stats_best_label.configure(text=f"Best Map Found: {self.format_stats(self.best_map_stats)}")
        else:
            self.stats_best_label.configure(text=f"Best Map Found: None")
            
        if self.worst_map_stats:
            self.stats_worst_label.configure(text=f"Worst Map Found: {self.format_stats(self.worst_map_stats)}")
        else:
            self.stats_worst_label.configure(text=f"Worst Map Found: None")
            
        # Update Average Rerolls List
        for widget in self.stats_avg_frame.winfo_children():
            widget.destroy()
            
        for name, data in self.template_stats.items():
            color_tag = "BLUE"
            if config.EVALUATION_MODE == "templates":
                for t in config.TEMPLATES:
                    if t["name"] == name:
                        color_tag = t.get("color", "BLUE").upper()
                        break
            else:
                colors = {
                    "Light": "WHITE",
                    "Good": "GREEN",
                    "Perfect": "YELLOW",
                    "Perfect+": "LIGHTRED_EX"
                }
                color_tag = colors.get(name, "BLUE")
                
            hex_color = COLOR_MAP.get(color_tag, COLOR_MAP["DEFAULT"])
            
            history = data['history']
            if len(history) > 0:
                avg = sum(history) / len(history)
                avg_text = f"{avg:.1f} ({len(history)} found)"
            else:
                avg_text = "N/A"
                
            label = ctk.CTkLabel(self.stats_avg_frame, text=f"  - {name}: {avg_text}", font=ctk.CTkFont(size=14), text_color=hex_color)
            label.pack(anchor="w")

    def log_reroll_stats(self):
        self.total_rerolls += 1
        for name in self.template_stats:
            self.template_stats[name]['rerolls_since_last'] += 1
            
        # Update UI less frequently to prevent lag (e.g., every 5 rerolls)
        if self.total_rerolls % 5 == 0:
            self.after(0, self.refresh_stats_ui)

    def log_target_found(self, template_name: str):
        if template_name in self.template_stats:
            data = self.template_stats[template_name]
            # If the current counter is 0, it means it was found on the very first try, record as 1 attempt
            attempts = data['rerolls_since_last'] if data['rerolls_since_last'] > 0 else 1
            data['history'].append(attempts)
            data['rerolls_since_last'] = 0
            
        self.after(0, self.refresh_stats_ui)

    def check_best_map(self, stats: dict):
        score = self.calculate_map_score(stats)
        if score > self.best_map_score:
            self.best_map_score = score
            self.best_map_stats = stats
            # Update UI immediately if a new best is found
            self.after(0, self.refresh_stats_ui)
            
    def check_worst_map(self, stats: dict):
        score = self.calculate_map_score(stats)
        if score < self.worst_map_score:
            self.worst_map_score = score
            self.worst_map_stats = stats
            # Update UI immediately if a new worst is found
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

        while (
            not self.stop_event.is_set()
            and self.scan_event.is_set()
            and not self.is_game_window_active(process_name)
        ):
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
                    f"[WAIT] Cannot bring game window to front: {direct_exc}; "
                    f"ALT attach fallback failed: {fallback_exc}",
                    tag="warning",
                )
                return False

    @staticmethod
    def show_game_window(window: int) -> None:
        if hasattr(win32gui, "IsIconic") and win32gui.IsIconic(window):
            win32gui.ShowWindow(window, 9)  # SW_RESTORE
        elif hasattr(win32gui, "ShowWindow"):
            win32gui.ShowWindow(window, 5)  # SW_SHOW

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
            self.log(f"[WAIT] Failed to enumerate game windows by PID: {exc}", tag="warning")

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
            self.log(f"[WAIT] Failed to enumerate game windows by title: {exc}", tag="warning")

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
            # 1. Wait for client
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
                        self.log(f"[WAIT] Process found. Waiting for GameAssembly.dll...", tag="warning")
                        wait_state = "module"
                        self.after(0, self.update_status_ui)
                    time.sleep(1)
                    continue

            # 2. Main scanner logic
            was_waiting = not self.scan_event.is_set()
            self.scan_event.wait() # Wait here until hotkey is pressed
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
                        timeout=10.0
                    )
                except InterruptedError:
                    # User paused while waiting for map
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

                    t_name = candidate.get('name')
                    t_color = candidate.get('color', 'BLUE').upper()
                    score_text = (
                        f" (Score: {candidate.get('score', 0):.1f})"
                        if config.EVALUATION_MODE == "scores"
                        else ""
                    )

                    try:
                        shady_guy_items = self.client.get_shady_guy_items()
                    except MemoryReadError as exc:
                        self.log(
                            f"[WAIT] Candidate '{t_name}{score_text}' rejected: failed to read Shady Guy items ({exc}).",
                            tag="warning",
                        )
                        candidate = None
                    else:
                        if not shady_guy_items:
                            self.log(
                                f"[WAIT] Candidate '{t_name}{score_text}' rejected: Shady Guy items are empty.",
                                tag="warning",
                            )
                            candidate = None
                        elif not self.has_required_shady_guy_item(shady_guy_items):
                            required_items_text = ", ".join(sorted(REQUIRED_SHADY_GUY_ITEMS))
                            self.log(
                                f"[WAIT] Candidate '{t_name}{score_text}' rejected: none of the required "
                                f"Shady Guy items were found ({required_items_text}).",
                                tag="warning",
                            )
                            candidate = None

                    if candidate is None:
                        pass
                    else:
                        shady_guy_items_text = ", ".join(self.item_name(item) for item in shady_guy_items)
                        self.log([f"\n[$$$] TARGET MAP FOUND! Profile: ", f"{t_name}{score_text}"], tag=["success", t_color])
                        self.log(f"Map Stats: {self.format_stats(stats)}", tag="success")
                        self.log(
                            f"Shady Guy items: [{shady_guy_items_text}]",
                            tag="success",
                        )

                        self.log_target_found(t_name)

                        if not self.handle_confirmed_target_window(process_name):
                            continue

                        self.is_running = False
                        self.scan_event.clear()
                        self.after(0, self.update_status_ui)
                        continue

                if candidate is None:
                    self.log(f"Stats: {self.format_stats(stats)}")

                if not self.wait_for_game_window_focus(process_name):
                    continue

                # Sleep to enforce MIN_DELAY for user comfort, but check for abort continuously
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
                self.log(f"[-] Map loading timeout: {exc}", tag="warning")
                self.log(f"[*] Forcing reroll to unstick...", tag="warning")
                self.reroll_map()
                last_reroll_time = time.monotonic()
                last_state = None
                last_stats = None
            except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError) as exc:
                self.is_running = False
                self.is_ready_to_start = False
                self.scan_event.clear()
                self.close_client()
                self.log(f"[-] Lost connection to the game: {exc}", tag="error")
                wait_state = None
                last_state = None
                last_stats = None
                self.after(0, self.update_status_ui)
                time.sleep(1)
            except Exception as e:
                self.log(f"[-] Error during execution: {e}", tag="error")
                time.sleep(1)

        # Cleanup when stopping loop
        self.close_client()
        self.is_running = False
        self.is_ready_to_start = False
        self.scan_event.clear()
        self.after(0, self.update_status_ui)

    def on_closing(self):
        self.stop_event.set()
        self.scan_event.set() # Ensure thread wakes up to exit
        self.close_client()
        hook_loader = self.native_hook_loader
        if hook_loader is not None:
            self.native_hook_generation += 1
            self.native_hook_loader = None
            self.native_hook_thread = None
            try:
                result = hook_loader.uninitialize()
                self.log(f"[+] Native hooks detached for PID {result.pid}.", tag="success")
            except HookProcessNotFoundError as exc:
                self.log(f"[WAIT] Native hook detach skipped during shutdown: {exc}", tag="warning")
            except HookLoadError as exc:
                self.log(f"[WAIT] Native hook detach failed during shutdown: {exc}", tag="warning")
            except Exception as exc:
                self.log(f"[WAIT] Unexpected native hook detach error during shutdown: {exc}", tag="warning")
        if keyboard:
            keyboard.unhook_all()
        self.destroy()
