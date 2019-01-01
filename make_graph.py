import json

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
    # Get neighbours
    ns = set()
    for edge_obj in star_map["edges"]:
        v1 = edge_obj["from"]
        v2 = edge_obj["to"]
        if v1 == node_id_int:
            ns.add(v2)
        if v2 == node_id_int:
            ns.add(v1)
    node_map[node_id_int] = list(ns)

with open("better_map.json", "w") as f:
    json.dump(node_map, f)
