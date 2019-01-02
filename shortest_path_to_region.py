import shortest_path as s
import json
import sys

with open("star_map.json", "r") as f:
    star_map = json.load(f)
with open("better_map.json", "r") as f:
    better_map = json.load(f)

orig_sys = sys.argv[1]
dest_region = sys.argv[2]

orig_sys_code = None

for node in star_map["nodes"].keys():
    if star_map["nodes"][node]["name"] == orig_sys:
        orig_sys_code = int(node)
        break
if orig_sys_code is None:
    print("Wrong origin system.")
    sys.exit(1)

systems = []

for node_str in star_map["nodes"].keys():
    node = star_map["nodes"][node_str]
    if node["region"] == dest_region:
        systems.append(int(node_str))
print("Need to check systems:")
print(systems)

shortest_length = None
shortest_path = None

N = len(systems)
i = 1

for system in systems:
    print("Checking %d of %d systems." % (i, N))
    i += 1
    path = s.get_route(orig_sys_code, system, better_map, star_map)
    if path == []:
        continue
    if shortest_length == None or shortest_path == None:
        shortest_length = len(path) - 1
        shortest_path = path
    if len(path) - 1 < shortest_length:
        shortest_path = path
        shortest_length = len(path) - 1
if shortest_length == None or shortest_path == None:
    print("No path exists.")
else:
    print(list(map(lambda x: s.get_system_name(x, star_map), shortest_path)))
