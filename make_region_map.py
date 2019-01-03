import json

with open("region_list.json", "r") as f:
    region_list = json.load(f)

d = {}

for region in region_list:
    r_id = region["id"]
    name = region["name"]
    d[r_id] = name

with open("region_map.json", "w") as f:
    json.dump(d, f)
