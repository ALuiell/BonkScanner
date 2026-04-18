import os
import sys
import requests
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox
import config

CURRENT_VERSION = "1.0.4"  # Current version of your program

GITHUB_REPO = "ALuiell/BonkScanner"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

def parse_version(v):
    return tuple(map(int, v.split('.')))

def check_and_update(app_instance=None, force_check=False):
    """Checks for updates and initiates the update process if a new version is available.
    Optionally takes the main GUI instance to handle message boxes correctly.
    force_check ignores the SKIPPED_UPDATE_VERSION config.
    """
    if getattr(sys, 'frozen', False):
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

        # Check if version was skipped, unless forced
        if not force_check and config.SKIPPED_UPDATE_VERSION == latest_version:
            print(f"Update to {latest_version} was skipped by user.")
            return

        if parse_version(latest_version) > parse_version(CURRENT_VERSION):
            if exe_download_url:
                # Prompt user for update
                def prompt_user():
                    root = app_instance if app_instance else tk.Tk()
                    if not app_instance:
                        root.withdraw()

                    # Create a custom dialog to show release notes
                    dialog = tk.Toplevel(root)
                    dialog.title("Update Available")
                    dialog.geometry("500x400")
                    dialog.resizable(False, False)
                    dialog.configure(bg="#2b2b2b")
                    dialog.transient(root)
                    dialog.grab_set()

                    # Center the dialog
                    dialog.update_idletasks()
                    x = root.winfo_x() + (root.winfo_width() // 2) - (500 // 2)
                    y = root.winfo_y() + (root.winfo_height() // 2) - (400 // 2)
                    dialog.geometry(f"+{x}+{y}")

                    # Header
                    header = tk.Label(dialog, text=f"A new version (v{latest_version}) is available!", 
                                      font=("Arial", 14, "bold"), bg="#2b2b2b", fg="white")
                    header.pack(pady=(20, 10))

                    # Release Notes Text Area
                    text_frame = tk.Frame(dialog, bg="#2b2b2b")
                    text_frame.pack(fill="both", expand=True, padx=20, pady=5)
                    
                    scrollbar = tk.Scrollbar(text_frame)
                    scrollbar.pack(side="right", fill="y")
                    
                    text_area = tk.Text(text_frame, wrap="word", yscrollcommand=scrollbar.set, 
                                        bg="#1e1e1e", fg="#d4d4d4", font=("Consolas", 10), 
                                        height=10, padx=10, pady=10)
                    text_area.insert("1.0", release_notes)
                    text_area.config(state="disabled") # Make read-only
                    text_area.pack(side="left", fill="both", expand=True)
                    scrollbar.config(command=text_area.yview)

                    question = tk.Label(dialog, text="Would you like to download and install it now?", 
                                        font=("Arial", 11), bg="#2b2b2b", fg="white")
                    question.pack(pady=(10, 20))

                    # Buttons
                    btn_frame = tk.Frame(dialog, bg="#2b2b2b")
                    btn_frame.pack(pady=(0, 20))

                    result = [None] # None=Ignore, True=Update, False=Skip

                    def on_yes():
                        result[0] = True
                        dialog.destroy()

                    def on_no():
                        result[0] = False # Mark as skip
                        dialog.destroy()

                    yes_btn = tk.Button(btn_frame, text="Yes, Update", width=15, bg="#2FA572", fg="white", 
                                        font=("Arial", 10, "bold"), relief="flat", cursor="hand2", command=on_yes)
                    yes_btn.pack(side="left", padx=10)
                    
                    no_btn = tk.Button(btn_frame, text="Skip for now", width=15, bg="#444444", fg="white", 
                                       font=("Arial", 10), relief="flat", cursor="hand2", command=on_no)
                    no_btn.pack(side="left", padx=10)

                    dialog.wait_window()

                    if result[0] is True:
                        if app_instance:
                            if hasattr(app_instance, 'log'):
                                app_instance.log(f"[*] Downloading update v{latest_version}... Please wait.", tag="warning")
                            threading.Thread(target=_download_and_apply_update, args=(exe_path, exe_download_url), daemon=True).start()
                        else:
                            _download_and_apply_update(exe_path, exe_download_url)
                    elif result[0] is False:
                        # User wants to skip this version
                        config.SKIPPED_UPDATE_VERSION = latest_version
                        config.user_config["SKIPPED_UPDATE_VERSION"] = latest_version
                        config.save_config(config.user_config)
                        
                        if app_instance and hasattr(app_instance, 'log'):
                            app_instance.log(f"[*] Update to v{latest_version} skipped. You can update manually in settings.", tag="warning")

                    if not app_instance:
                        root.destroy()
                        
                if app_instance:
                    app_instance.after(0, prompt_user)
                else:
                    prompt_user()
            else:
                print("Error: No .exe file found in the GitHub release.")
        else:
            if force_check and app_instance and hasattr(app_instance, 'log'):
                app_instance.log(f"[*] You already have the latest version (v{CURRENT_VERSION}).", tag="success")
            print("You have the latest version installed.")
    except Exception as e:
        print(f"Failed to check for updates: {e}")

def _download_and_apply_update(exe_path, download_url):
    """Downloads the new exe and runs the replacement script."""
    new_exe_path = exe_path + ".new"
    exe_dir = os.path.dirname(exe_path)
    exe_name = os.path.basename(exe_path)
    new_exe_name = exe_name + ".new"
    bat_path = os.path.join(exe_dir, "update.bat")

    try:
        r = requests.get(download_url, stream=True, timeout=10)
        r.raise_for_status()
        with open(new_exe_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    except Exception as e:
        print(f"Error downloading update: {e}")
        if os.path.exists(new_exe_path):
            os.remove(new_exe_path)
        return

    # CRITICAL FIX: "timeout" command fails in batch files if there is no console window!
    # It instantly aborts the script. We must use "ping 127.0.0.1" as a sleep mechanism instead.
    bat_content = f"""@echo off
chcp 65001 > nul
cd /d "%~dp0"

:wait_loop
ping 127.0.0.1 -n 2 > nul
del "{exe_name}" > nul 2>&1
if exist "{exe_name}" goto wait_loop

move /y "{new_exe_name}" "{exe_name}" > nul 2>&1
start "" "{exe_name}"
(goto) 2>nul & del "%~f0"
"""
    with open(bat_path, "w", encoding="utf-8") as bat_file:
        bat_file.write(bat_content)

    print("Update downloaded. The program will be restarted...")
    
    # We must rigorously clean the environment for the bat file so it doesn't pass it to the new exe
    env = os.environ.copy()
    
    # Remove all PyInstaller specific variables
    keys_to_remove = []
    for key in env.keys():
        if key.startswith('_MEI') or key.startswith('_PYI'):
            keys_to_remove.append(key)
            
    for key in keys_to_remove:
        env.pop(key, None)
            
    env.pop('TCL_LIBRARY', None)
    env.pop('TK_LIBRARY', None)
    env.pop('_PYVENV_LAUNCHER_', None)
    
    # Rigorous PATH cleanup: Remove ALL paths that contain "_MEI"
    if 'PATH' in env:
        paths = env['PATH'].split(os.pathsep)
        clean_paths = [p for p in paths if "_MEI" not in p.upper()]
        env['PATH'] = os.pathsep.join(clean_paths)
    
    # Use STARTUPINFO to hide the console window completely
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    
    subprocess.Popen(
        ["cmd.exe", "/c", bat_path],
        creationflags=subprocess.CREATE_NO_WINDOW,
        env=env,
        startupinfo=startupinfo,
        close_fds=True
    )
    
    os._exit(0)
