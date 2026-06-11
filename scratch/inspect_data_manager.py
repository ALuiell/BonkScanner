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
    if not class_ptr:
        print("DataManager class_ptr not found")
        return
        
    static_fields = client.memory.read_ptr(class_ptr + client.CLASS_STATIC_FIELDS_OFFSET)
    if not static_fields:
        print("DataManager static_fields not found")
        return
        
    print(f"DataManager static_fields base: {hex(static_fields)}")
    
    # Let's read 16 pointers starting from static_fields
    for offset in range(0, 128, 8):
        val = client.memory.read_ptr(static_fields + offset)
        print(f"  + {hex(offset)}: {hex(val)}")
        
        if val:
            try:
                klass = client.memory.read_ptr(val + 0x0)
                if klass:
                    name_ptr = client.memory.read_ptr(klass + 0x10)
                    if name_ptr:
                        class_name = client.memory.read_ascii_string(name_ptr)
                        print(f"    -> Class: {class_name}")
            except Exception:
                pass

if __name__ == "__main__":
    inspect()
