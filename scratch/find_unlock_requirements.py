import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from player_stats import PlayerStatsClient

def inspect():
    client = PlayerStatsClient(config.PROCESS_NAME)
    
    type_info_address = client.memory.module_offset(
        client.module_name,
        client.DATA_MANAGER_TYPE_INFO_OFFSET,
    )
    class_ptr = client.memory.read_ptr(type_info_address)
    static_fields = client.memory.read_ptr(class_ptr + client.CLASS_STATIC_FIELDS_OFFSET)
    instance = client.memory.read_ptr(static_fields + 0x8)
    
    unsorted_items_list = client.memory.read_ptr(instance + 0x60)
    items_array = client.memory.read_ptr(unsorted_items_list + client.LIST_ITEMS_OFFSET)
    size = client.memory.read_i32(unsorted_items_list + client.LIST_SIZE_OFFSET)
    
    from item_metadata import ITEM_ENUM_NAMES_BY_ID
    
    print("Items with unlockRequirement != 0:")
    for index in range(size):
        item_data_ptr = client.memory.read_ptr(
            items_array + client.ARRAY_DATA_OFFSET + (index * client.OBJECT_POINTER_SIZE)
        )
        if not item_data_ptr:
            continue
        item_id = client.memory.read_i32(item_data_ptr + client.ITEM_DATA_ENUM_OFFSET)
        enum_name = ITEM_ENUM_NAMES_BY_ID.get(item_id, f"Unknown ID {item_id}")
        
        unlock_req = client.memory.read_ptr(item_data_ptr + 0x68)
        if unlock_req != 0:
            print(f"  - ID {item_id:2d} | {enum_name:<25} | unlockRequirement: {hex(unlock_req)}")

if __name__ == "__main__":
    inspect()
