from __future__ import annotations

import os
import re
import subprocess
import sys
import threading

import requests

import config

try:
    from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPushButton, QTextEdit, QVBoxLayout
except Exception:
    QDialog = None
    QDialogButtonBox = None
    QLabel = None
    QPushButton = None
    QTextEdit = None
    QVBoxLayout = None


CURRENT_VERSION = "2.0.5"
GITHUB_REPO = "ALuiell/BonkScanner"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def parse_version(v):
    return tuple(map(int, v.split(".")))


def check_and_update(app_instance=None, force_check=False):
    if getattr(sys, "frozen", False):
        exe_path = sys.executable
    else:
        print("Running from source code. Auto-update disabled.")
        return

    try:
        response = requests.get(GITHUB_API_URL, timeout=5)
        response.raise_for_status()
        release_data = response.json()

        latest_version = release_data.get("tag_name", "").lstrip("v")
        release_notes = release_data.get("body", "No release notes provided.")

        exe_download_url = None
        for asset in release_data.get("assets", []):
            if asset["name"].endswith(".exe"):
                exe_download_url = asset["browser_download_url"]
                break

        if not force_check and config.SKIPPED_UPDATE_VERSION == latest_version:
            print(f"Update to {latest_version} was skipped by user.")
            return

        if parse_version(latest_version) > parse_version(CURRENT_VERSION):
            if exe_download_url:
                def prompt_user():
                    accepted = _show_update_dialog(app_instance, latest_version, release_notes)
                    if accepted is True:
                        if app_instance and hasattr(app_instance, "log"):
                            app_instance.log(f"[*] Downloading update v{latest_version}... Please wait.", tag="warning")
                            threading.Thread(
                                target=_download_and_apply_update,
                                args=(exe_path, exe_download_url),
                                daemon=True,
                            ).start()
                        else:
                            _download_and_apply_update(exe_path, exe_download_url)
                    elif accepted is False:
                        config.SKIPPED_UPDATE_VERSION = latest_version
                        config.user_config["SKIPPED_UPDATE_VERSION"] = latest_version
                        config.save_config(config.user_config)
                        if app_instance and hasattr(app_instance, "log"):
                            app_instance.log(
                                f"[*] Update to v{latest_version} skipped. You can update manually in settings.",
                                tag="warning",
                            )

                if app_instance and hasattr(app_instance, "after"):
                    app_instance.after(0, prompt_user)
                else:
                    prompt_user()
            else:
                print("Error: No .exe file found in the GitHub release.")
        else:
            if force_check and app_instance and hasattr(app_instance, "log"):
                app_instance.log(f"[*] You already have the latest version (v{CURRENT_VERSION}).", tag="success")
            print("You have the latest version installed.")
    except Exception as e:
        print(f"Failed to check for updates: {e}")


def _show_update_dialog(app_instance, latest_version: str, release_notes: str) -> bool | None:
    if QDialog is None:
        print(f"Update available: v{latest_version}")
        print(release_notes)
        return None

    parent = getattr(app_instance, "window", app_instance)
    dialog = QDialog(parent)
    dialog.setWindowTitle("Update Available")
    dialog.resize(560, 420)

    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(f"A new version (v{latest_version}) is available!"))

    notes = QTextEdit()
    notes.setReadOnly(True)
    _set_release_notes_content(notes, release_notes)
    layout.addWidget(notes, 1)

    layout.addWidget(QLabel("Would you like to download and install it now?"))

    buttons = QDialogButtonBox()
    yes_btn = QPushButton("Yes, Update")
    skip_btn = QPushButton("Skip for now")
    buttons.addButton(yes_btn, QDialogButtonBox.AcceptRole)
    buttons.addButton(skip_btn, QDialogButtonBox.RejectRole)
    accepted = {"value": None}

    def on_yes():
        accepted["value"] = True
        dialog.accept()

    def on_skip():
        accepted["value"] = False
        dialog.reject()

    yes_btn.clicked.connect(on_yes)
    skip_btn.clicked.connect(on_skip)
    layout.addWidget(buttons)
    dialog.exec()
    return accepted["value"]


def _set_release_notes_content(notes: QTextEdit, release_notes: str) -> None:
    if _looks_like_html(release_notes):
        set_html = getattr(notes, "setHtml", None)
        if callable(set_html):
            try:
                set_html(_format_release_notes_html(release_notes))
                return
            except Exception:
                pass

    set_markdown = getattr(notes, "setMarkdown", None)
    if callable(set_markdown):
        try:
            set_markdown(release_notes)
            return
        except Exception:
            pass

    notes.setPlainText(release_notes)


def _looks_like_html(text: str) -> bool:
    if not isinstance(text, str):
        return False
    return re.search(r"<[A-Za-z][^>]*>", text) is not None


def _format_release_notes_html(release_notes: str) -> str:
    if not isinstance(release_notes, str):
        return ""

    formatted = release_notes.strip()
    styled_tags = {
        "h2": "margin:0 0 14px 0; padding-bottom:10px; color:#0f172a; "
        "font-size:22px; font-weight:700; border-bottom:1px solid #dbe4f0;",
        "h3": "margin:18px 0 8px 0; color:#1d4ed8; font-size:15px; "
        "font-weight:700; letter-spacing:0.6px; text-transform:uppercase;",
        "p": "margin:0 0 10px 0;",
        "ul": "margin:0 0 8px 0; padding-left:20px;",
        "li": "margin:0 0 8px 0;",
        "code": "font-family:'Consolas','Courier New',monospace; font-size:12px; "
        "background-color:#e8eefc; color:#1e3a8a; padding:2px 6px; border-radius:4px;",
    }
    for tag, style in styled_tags.items():
        formatted = re.sub(
            rf"<{tag}\b[^>]*>",
            f'<{tag} style="{style}">',
            formatted,
            flags=re.IGNORECASE,
        )

    return (
        "<div style=\"font-family:'Segoe UI',sans-serif; font-size:13px; "
        "line-height:1.5; color:#1f2937; background-color:#f8fafc; "
        "padding:16px 18px;\">"
        f"{formatted}"
        "</div>"
    )


def _download_and_apply_update(exe_path, download_url):
    new_exe_path = exe_path + ".new"
    exe_dir = os.path.dirname(exe_path)
    exe_name = os.path.basename(exe_path)
    new_exe_name = exe_name + ".new"
    backup_exe_name = exe_name + ".old"
    bat_path = os.path.join(exe_dir, "update.bat")

    try:
        r = requests.get(download_url, stream=True, timeout=10)
        r.raise_for_status()
        expected_size = int(r.headers.get("content-length", "0") or "0")
        downloaded_size = 0
        with open(new_exe_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                downloaded_size += len(chunk)
                f.write(chunk)
        if downloaded_size == 0 or (expected_size and downloaded_size != expected_size):
            raise RuntimeError("Downloaded update is empty or incomplete.")
    except Exception as e:
        print(f"Error downloading update: {e}")
        if os.path.exists(new_exe_path):
            os.remove(new_exe_path)
        return

    bat_content = f"""@echo off
chcp 65001 > nul
cd /d "%~dp0"

:wait_loop
ping 127.0.0.1 -n 2 > nul
if exist "{backup_exe_name}" del "{backup_exe_name}" > nul 2>&1
ren "{exe_name}" "{backup_exe_name}" > nul 2>&1
if errorlevel 1 goto wait_loop

move /y "{new_exe_name}" "{exe_name}" > nul 2>&1
if errorlevel 1 goto restore_old
if not exist "{exe_name}" goto restore_old

del "{backup_exe_name}" > nul 2>&1
start "" "{exe_name}"
(goto) 2>nul & del "%~f0"

:restore_old
if not exist "{exe_name}" if exist "{backup_exe_name}" ren "{backup_exe_name}" "{exe_name}" > nul 2>&1
start "" "{exe_name}"
(goto) 2>nul & del "%~f0"
"""
    with open(bat_path, "w", encoding="utf-8") as bat_file:
        bat_file.write(bat_content)

    print("Update downloaded. The program will be restarted...")

    env = os.environ.copy()
    keys_to_remove = [key for key in env.keys() if key.startswith("_MEI") or key.startswith("_PYI")]
    for key in keys_to_remove:
        env.pop(key, None)

    env.pop("TCL_LIBRARY", None)
    env.pop("TK_LIBRARY", None)
    env.pop("_PYVENV_LAUNCHER_", None)

    if "PATH" in env:
        paths = env["PATH"].split(os.pathsep)
        env["PATH"] = os.pathsep.join(path for path in paths if "_MEI" not in path.upper())

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE

    subprocess.Popen(
        ["cmd.exe", "/c", bat_path],
        creationflags=subprocess.CREATE_NO_WINDOW,
        env=env,
        startupinfo=startupinfo,
        close_fds=True,
    )

    os._exit(0)
