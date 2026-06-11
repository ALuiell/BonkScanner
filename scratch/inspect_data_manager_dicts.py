import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from player_stats import PlayerStatsClient

def inspect_dict(client, dict_address, name):
    if not dict_address:
        return
        
    try:
        count = client.memory.read_i32(dict_address + client.DICT_COUNT_OFFSET)
        entries = client.memory.read_ptr(dict_address + client.DICT_ENTRIES_OFFSET)
        capacity = client.memory.read_i32(entries + 0x18) if entries else 0
        
        # Read a few entries to see what it contains
        print(f"Dict {name} ({hex(dict_address)}): count={count}, capacity={capacity}")
        
        from item_metadata import ITEM_ENUM_NAMES_BY_ID
        
        limit = min(capacity, 100)
        found_items = []
        for index in range(limit):
            entry = entries + client.DICT_ENTRY_START_OFFSET + (index * client.DICT_ENTRY_SIZE)
            hash_code = client.memory.read_i32(entry + client.DICT_ENTRY_HASH_CODE_OFFSET)
            if hash_code < 0:
                continue
                
            key = client.memory.read_i32(entry + client.DICT_ENTRY_KEY_OFFSET)
            value = client.memory.read_ptr(entry + client.DICT_ENTRY_VALUE_OFFSET)
            
            # Check if key is in item IDs
            if key in ITEM_ENUM_NAMES_BY_ID:
                found_items.append((key, ITEM_ENUM_NAMES_BY_ID[key], hex(value)))
                
        if found_items:
            print(f"  -> Found {len(found_items)} item keys in this dict:")
            for item_id, name, val_ptr in found_items[:10]:
                print(f"    - ID {item_id}: {name} -> {val_ptr}")
    except Exception as e:
        print(f"Error reading dict {name}: {e}")

def main():
    client = PlayerStatsClient(config.PROCESS_NAME)
    type_info_address = client.memory.module_offset(
        client.module_name,
        client.DATA_MANAGER_TYPE_INFO_OFFSET,
    )
    class_ptr = client.memory.read_ptr(type_info_address)
    static_fields = client.memory.read_ptr(class_ptr + client.CLASS_STATIC_FIELDS_OFFSET)
    instance = client.memory.read_ptr(static_fields + 0x8)
    
    # Let's check dictionaries from +0x88 to +0xd0
    for offset in range(0x88, 0xd8, 8):
        dict_addr = client.memory.read_ptr(instance + offset)
        inspect_dict(client, dict_addr, f"Offset {hex(offset)}")

if __name__ == "__main__":
    main()
