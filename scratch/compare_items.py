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
    
    anvil_ptr = 0
    zawarudo_ptr = 0
    
    for index in range(size):
        item_data_ptr = client.memory.read_ptr(
            items_array + client.ARRAY_DATA_OFFSET + (index * client.OBJECT_POINTER_SIZE)
        )
        if not item_data_ptr:
            continue
        item_id = client.memory.read_i32(item_data_ptr + client.ITEM_DATA_ENUM_OFFSET)
        if item_id == 41:
            anvil_ptr = item_data_ptr
        elif item_id == 25:
            zawarudo_ptr = item_data_ptr
            
    def dump_fields(name, ptr):
        print(f"\nItemData of {name} ({hex(ptr)}):")
        # Let's dump all fields from 0x10 to 0x90
        for offset in range(0x10, 0x90, 8):
            val = client.memory.read_ptr(ptr + offset)
            val32 = client.memory.read_i32(ptr + offset)
            val8 = client.memory.read_u8(ptr + offset)
            print(f"  + {hex(offset)}: {hex(val)} (i32: {val32}, u8: {val8})")
            
    if anvil_ptr:
        dump_fields("Anvil", anvil_ptr)
    if zawarudo_ptr:
        dump_fields("ZaWarudo", zawarudo_ptr)

if __name__ == "__main__":
    inspect()
