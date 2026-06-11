import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from player_stats import PlayerStatsClient

def inspect_dict(client, dict_address, name):
    if not dict_address:
        print(f"{name} is null")
        return
        
    count = client.memory.read_i32(dict_address + client.DICT_COUNT_OFFSET)
    entries = client.memory.read_ptr(dict_address + client.DICT_ENTRIES_OFFSET)
    capacity = client.memory.read_i32(entries + 0x18) if entries else 0
    print(f"\n==========================================")
    print(f"Dictionary {name}: count={count}, capacity={capacity}")
    
    from item_metadata import ITEM_ENUM_NAMES_BY_ID
    
    for index in range(capacity):
        entry = entries + client.DICT_ENTRY_START_OFFSET + (index * client.DICT_ENTRY_SIZE)
        hash_code = client.memory.read_i32(entry + client.DICT_ENTRY_HASH_CODE_OFFSET)
        if hash_code < 0:
            continue
            
        key = client.memory.read_i32(entry + client.DICT_ENTRY_KEY_OFFSET)
        value = client.memory.read_ptr(entry + client.DICT_ENTRY_VALUE_OFFSET)
        if not value:
            continue
            
        # Let's check if the value is a list of items
        try:
            klass = client.memory.read_ptr(value + 0x0)
            class_name = ""
            if klass:
                name_ptr = client.memory.read_ptr(klass + 0x10)
                if name_ptr:
                    class_name = client.memory.read_ascii_string(name_ptr)
            
            print(f"  Entry {index}: Key = {key}, Value Class = {class_name}")
            
            if "List" in class_name:
                sub_array = client.memory.read_ptr(value + client.LIST_ITEMS_OFFSET)
                sub_size = client.memory.read_i32(value + client.LIST_SIZE_OFFSET)
                print(f"    List size = {sub_size}")
                for sub_index in range(sub_size):
                    item_data_ptr = client.memory.read_ptr(
                        sub_array + client.ARRAY_DATA_OFFSET + (sub_index * client.OBJECT_POINTER_SIZE)
                    )
                    if not item_data_ptr:
                        continue
                    item_id = client.memory.read_i32(item_data_ptr + client.ITEM_DATA_ENUM_OFFSET)
                    raw_name = ITEM_ENUM_NAMES_BY_ID.get(item_id, f"Unknown ID {item_id}")
                    print(f"      - Item [{item_id}]: {raw_name}")
            else:
                # Just print the value address
                print(f"    Value address = {hex(value)}")
        except Exception as e:
            print(f"    Error reading entry value: {e}")

def main():
    client = PlayerStatsClient(config.PROCESS_NAME)
    type_info_address = client.memory.module_offset(
        client.module_name,
        client.RUN_UNLOCKABLES_TYPE_INFO_OFFSET,
    )
    class_ptr = client.memory.read_ptr(type_info_address)
    static_fields = client.memory.read_ptr(class_ptr + client.CLASS_STATIC_FIELDS_OFFSET)
    
    inspect_dict(client, client.memory.read_ptr(static_fields + 0x10), "availableItems (+0x10)")
    inspect_dict(client, client.memory.read_ptr(static_fields + 0x18), "availableUpgradables (+0x18)")

if __name__ == "__main__":
    main()
