import os
import json

recordings_dir = "f:/Python/MegabonkReroll/stats_recordings"
for filename in os.listdir(recordings_dir):
    if filename.endswith(".jsonl"):
        path = os.path.join(recordings_dir, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    data = json.loads(line)
                    if data.get("type") == "snapshot" and data.get("elapsed_seconds") == 0:
                        stats = data.get("stats", {})
                        diff = stats.get("Difficulty", {}).get("display")
                        xp = stats.get("XP Gain", {}).get("display")
                        print(f"{filename}: initial_diff={diff}, initial_xp={xp}")
                        break
        except Exception:
            pass
