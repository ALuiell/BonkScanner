import os
import sys
import requests
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox

CURRENT_VERSION = "1.0.2"  # Current version of your program

GITHUB_REPO = "ALuiell/BonkScanner"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

def parse_version(v):
    return tuple(map(int, v.split('.')))

def check_and_update(app_instance=None):
    """Checks for updates and initiates the update process if a new version is available.
    Optionally takes the main GUI instance to handle message boxes correctly.
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
        
        exe_download_url = None
        for asset in release_data.get("assets", []):
            if asset["name"].endswith(".exe"):
                exe_download_url = asset["browser_download_url"]
                break

        if parse_version(latest_version) > parse_version(CURRENT_VERSION):
            if exe_download_url:
                # Prompt user for update
                def prompt_user():
                    # If app_instance is passed, it means we are in the main GUI thread
                    # or we can use it as parent.
                    root = app_instance if app_instance else tk.Tk()
                    if not app_instance:
                        root.withdraw() # Hide the root window if it's standalone

                    result = messagebox.askyesno(
                        "Update Available", 
                        f"A new version (v{latest_version}) is available!\n\nWould you like to download and install it now?",
                        parent=root if app_instance else None
                    )
                    
                    if result:
                        if app_instance:
                            # If updating from within the app, let's notify the user
                            # that it's downloading
                            if hasattr(app_instance, 'log'):
                                app_instance.log(f"[*] Downloading update v{latest_version}... Please wait.", tag="warning")
                            # Run download in background to not freeze GUI, 
                            # but we need to exit anyway.
                            threading.Thread(target=_download_and_apply_update, args=(exe_path, exe_download_url), daemon=True).start()
                        else:
                            _download_and_apply_update(exe_path, exe_download_url)
                    
                    if not app_instance:
                        root.destroy()
                        
                # Ensure the messagebox runs in the main thread if app_instance is passed
                if app_instance:
                    app_instance.after(0, prompt_user)
                else:
                    prompt_user()
            else:
                print("Error: No .exe file found in the GitHub release.")
        else:
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

    # We need to run the new executable completely disconnected from the current one.
    # To avoid the old PyInstaller MEIPASS PATH variables leaking, we construct a completely new environment.
    
    bat_content = f"""@echo off
chcp 65001 > nul
echo Updating the program, please wait...
cd /d "%~dp0"

:wait_loop
timeout /t 1 /nobreak > nul
del "{exe_name}" > nul 2>&1
if exist "{exe_name}" goto wait_loop

move /y "{new_exe_name}" "{exe_name}"
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
    
    # Create the process disconnected and detached
    # Use STARTUPINFO to hide the console window completely
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    
    # CREATE_NEW_PROCESS_GROUP and DETACHED_PROCESS to fully unbind it
    subprocess.Popen(
        ["cmd.exe", "/c", bat_path],
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        env=env,
        startupinfo=startupinfo,
        close_fds=True
    )
    
    os._exit(0)
