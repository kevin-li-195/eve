import json
import requests as r

base = "https://esi.evetech.net/latest/universe/types/?datasource=tranquility&page="

type_ids = []

for num in range(1,37):
    url = base + str(num)
    req = r.get(url)
    type_ids.extend(json.loads(req.text))

with open("type_list.json", "w") as f:
    json.dump(type_ids, f)
