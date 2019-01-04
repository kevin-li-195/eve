import json
import requests as r
from requests_futures.sessions import FuturesSession
from concurrent.futures import ThreadPoolExecutor

with open("type_list.json", "r") as f:
    type_list = json.load(f)

with open("item_map.json", "r") as f:
    old_item_map = json.load(f)

item_map = {}
n = len(type_list)

i = 1
j = 1

session = FuturesSession(executor=ThreadPoolExecutor(max_workers=50))

futs = []

for tid in type_list:
    if str(tid) in old_item_map:
        i += 1
        continue
    print("%d not found" % tid)
    print("%d of %d req" % (i, n))
    url = "https://esi.evetech.net/latest/universe/types/%d/?datasource=tranquility&language=en-us" % tid
    fut = session.get(url)
    futs.append((tid, fut))
n = len(futs)

for tid, fut in futs:
    print("%d of %d resp" % (j, n))
    j += 1
    req = fut.result()
    try:
        obj = json.loads(req.text)
    except:
        print("Couldn't parse %d req" % tid)
        print("Dumping")
        print(req.text)
        continue
    item_map[tid] = obj
