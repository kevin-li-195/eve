import json

# MAKE THE SAFE NEIGHBOUR MAP

with open("star_map.json", "r") as f:
    star_map = json.load(f)

node_map = {}
# Make a map of just the ids.
# Just a dict of id to neighbours
N = len(star_map["nodes"])
i = 1
for node_id in star_map["nodes"].keys():
    print("%d of %d" % (i, N))
    i += 1
    node_id_int = int(node_id)
    if star_map["nodes"][node_id]["security"] < 0.45:
        continue
    # Get neighbours
    ns = set()
    for edge_obj in star_map["edges"]:
        v1 = edge_obj["from"]
        v2 = edge_obj["to"]
        if star_map["nodes"][str(v1)]["security"] < 0.45 or \
                star_map["nodes"][str(v2)]["security"] < 0.45:
            continue
        if v1 == node_id_int:
            ns.add(v2)
        if v2 == node_id_int:
            ns.add(v1)
    node_map[node_id_int] = list(ns)

with open("high_sec_neighbour_map.json", "w") as f:
    json.dump(node_map, f)
