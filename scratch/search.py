import json

with open(r'F:\Python\CA_mpc_bridge\Dump\script.json', 'r') as f:
    data = json.load(f)

print("Searching methods around 0x2fe020:")
for m in data.get('ScriptMethod', []):
    addr = m.get('Address', 0)
    # let's check relative addresses in that range
    if 0x2fbf00 <= addr <= 0x2ff000 or 0x1802fbf00 <= addr <= 0x1802ff000:
        print(f"Address: {hex(addr)}, Name: {m.get('Name')}")
