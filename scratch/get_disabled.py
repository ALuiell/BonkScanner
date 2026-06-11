import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from player_stats import PlayerStatsClient

def main():
    print(f"Connecting to process: {config.PROCESS_NAME}")
    try:
        client = PlayerStatsClient(config.PROCESS_NAME)
        disabled_items = client.get_disabled_items()
        print(f"Successfully retrieved. Count: {len(disabled_items)}")
        for idx, item in enumerate(disabled_items, 1):
            print(f"{idx}. {item}")
    except Exception as e:
        print(f"Error reading disabled items: {e}")

if __name__ == "__main__":
    main()
