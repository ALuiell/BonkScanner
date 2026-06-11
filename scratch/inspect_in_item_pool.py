import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from player_stats import PlayerStatsClient

def inspect_catalog():
    client = PlayerStatsClient(config.PROCESS_NAME)
    
    # Let's get DataManager.Instance
    type_info_address = client.memory.module_offset(
        client.module_name,
        client.DATA_MANAGER_TYPE_INFO_OFFSET,
    )
    class_ptr = client.memory.read_ptr(type_info_address)
    if not class_ptr:
        print("DataManager class_ptr not found")
        return
        
    static_fields = client.memory.read_ptr(class_ptr + client.CLASS_STATIC_FIELDS_OFFSET)
    if not static_fields:
        print("DataManager static_fields not found")
        return
        
    instance = client.memory.read_ptr(static_fields + 0x8)
    if not instance:
        print("DataManager instance not found")
        return
        
    unsorted_items_list = client.memory.read_ptr(instance + 0x60)
    if not unsorted_items_list:
        print("unsortedItems list is null")
        return
        
    items_array = client.memory.read_ptr(unsorted_items_list + client.LIST_ITEMS_OFFSET)
    size = client.memory.read_i32(unsorted_items_list + client.LIST_SIZE_OFFSET)
    
    print(f"unsortedItems List size={size}")
    
    from item_metadata import ITEM_ENUM_NAMES_BY_ID
    
    for index in range(size):
        item_data_ptr = client.memory.read_ptr(
            items_array + client.ARRAY_DATA_OFFSET + (index * client.OBJECT_POINTER_SIZE)
        )
        if not item_data_ptr:
            continue
            
        item_id = client.memory.read_i32(item_data_ptr + client.ITEM_DATA_ENUM_OFFSET)
        enum_name = ITEM_ENUM_NAMES_BY_ID.get(item_id, f"Unknown ID {item_id}")
        
        # Read inItemPool (bool at +0x50)
        in_item_pool = client.memory.read_u8(item_data_ptr + 0x50)
        
        print(f"Index {index:2d} | ID {item_id:2d} | Enum: {enum_name:<25} | inItemPool: {in_item_pool}")

if __name__ == "__main__":
    inspect_catalog()
