import json

with open("star_map.json", "r") as f:
    star_map = json.load(f)

safe_node_map = {}
for node_id_str in star_map["nodes"].keys():
    node_obj = star_map["nodes"][node_id_str]
    if node_obj["security"] > 0.45:
        safe_node_map[node_id_str] = node_obj

with open("safe_star_map.json", "w") as f:
    json.dump(safe_node_map, f)
