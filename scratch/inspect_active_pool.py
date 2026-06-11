import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from player_stats import PlayerStatsClient

def inspect():
    client = PlayerStatsClient(config.PROCESS_NAME)
    
    # Let's get the static fields of RunUnlockables
    type_info_address = client.memory.module_offset(
        client.module_name,
        client.RUN_UNLOCKABLES_TYPE_INFO_OFFSET,
    )
    class_ptr = client.memory.read_ptr(type_info_address)
    if not class_ptr:
        print("RunUnlockables class_ptr not found")
        return
        
    static_fields = client.memory.read_ptr(class_ptr + client.CLASS_STATIC_FIELDS_OFFSET)
    if not static_fields:
        print("RunUnlockables static_fields not found")
        return
        
    available_items_dict = client.memory.read_ptr(static_fields + 0x10)
    if not available_items_dict:
        print("availableItems dictionary is null")
        return
        
    count = client.memory.read_i32(available_items_dict + client.DICT_COUNT_OFFSET)
    entries = client.memory.read_ptr(available_items_dict + client.DICT_ENTRIES_OFFSET)
    
    # C# Array size (capacity) at entries + 0x18
    capacity = client.memory.read_i32(entries + 0x18) if entries else 0
    print(f"availableItems Dictionary: count={count}, capacity={capacity}")
    
    from item_metadata import ITEM_ENUM_NAMES_BY_ID, ITEMS
    
    # Let's read all entries in the array up to capacity, not just count!
    for index in range(capacity):
        entry = entries + client.DICT_ENTRY_START_OFFSET + (index * client.DICT_ENTRY_SIZE)
        hash_code = client.memory.read_i32(entry + client.DICT_ENTRY_HASH_CODE_OFFSET)
        if hash_code < 0:
            continue
            
        rarity_key = client.memory.read_i32(entry + client.DICT_ENTRY_KEY_OFFSET)
        list_address = client.memory.read_ptr(entry + client.DICT_ENTRY_VALUE_OFFSET)
        if not list_address:
            continue
            
        sub_array = client.memory.read_ptr(list_address + client.LIST_ITEMS_OFFSET)
        sub_size = client.memory.read_i32(list_address + client.LIST_SIZE_OFFSET)
        
        print(f"\nEntry {index}: Rarity Key = {rarity_key}, Items List Size = {sub_size}")
        
        for sub_index in range(sub_size):
            item_data_ptr = client.memory.read_ptr(
                sub_array + client.ARRAY_DATA_OFFSET + (sub_index * client.OBJECT_POINTER_SIZE)
            )
            if not item_data_ptr:
                continue
            item_id = client.memory.read_i32(item_data_ptr + client.ITEM_DATA_ENUM_OFFSET)
            raw_name = ITEM_ENUM_NAMES_BY_ID.get(item_id, f"Unknown ID {item_id}")
            
            # Let's also read the rarity string/enum from the ItemData if we can find it
            # eItemRarity is usually at some offset in ItemData
            # Let's check item_data_ptr fields
            # We know ItemData has name/display name in some fields, let's just print ID and raw_name
            print(f"  - Item [{item_id}]: {raw_name}")

if __name__ == "__main__":
    inspect()
