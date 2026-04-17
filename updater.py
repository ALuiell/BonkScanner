import os
import sys
import requests
import subprocess

CURRENT_VERSION = "1.0.0"  # Current version of your program

GITHUB_REPO = "ALuiell/BonkScanner"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

def check_and_update():
    """Checks for updates and initiates the update process if a new version is available."""
    if getattr(sys, 'frozen', False):
        exe_path = sys.executable
    else:
        print("Running from source code. Auto-update disabled.")
        return

    print("Checking for updates...")
    try:
        response = requests.get(GITHUB_API_URL, timeout=5)
        response.raise_for_status()
        release_data = response.json()
        
        # Extract version from tag (e.g., "v1.0.1" -> "1.0.1")
        latest_version = release_data.get("tag_name", "").lstrip("v")
        
        # Look for the .exe file download link among attached assets
        exe_download_url = None
        for asset in release_data.get("assets", []):
            if asset["name"].endswith(".exe"):
                exe_download_url = asset["browser_download_url"]
                break

        # Simple version comparison. (For complex logic, use the packaging.version module)
        if latest_version > CURRENT_VERSION:
            print(f"New version found: {latest_version}! Starting download...")
            if exe_download_url:
                _download_and_apply_update(exe_path, exe_download_url)
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
        # Download the file in chunks (useful for large files)
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

    # Create a batch file for replacement
    bat_content = f"""@echo off
chcp 65001 > nul
echo Updating the program, please wait...
cd /d "%~dp0"
timeout /t 2 /nobreak > nul
del "{exe_name}"
move /y "{new_exe_name}" "{exe_name}"
start "" "{exe_name}"
del "%~f0"
"""
    with open(bat_path, "w", encoding="utf-8") as bat_file:
        bat_file.write(bat_content)

    print("Update downloaded. The program will be restarted...")
    
    # Clean up PyInstaller environment variables before launching the batch file.
    # Otherwise, the new .exe will try to use the old (deleted) _MEI folder and crash!
    env = os.environ.copy()
    env.pop('_MEIPASS2', None)
    env.pop('TCL_LIBRARY', None)
    env.pop('TK_LIBRARY', None)
    
    # Run the batch file detached from the current process with clean environment
    subprocess.Popen([bat_path], creationflags=subprocess.CREATE_NEW_CONSOLE, env=env)
    
    # Immediately close the program so the batch file can delete the old exe
    sys.exit()