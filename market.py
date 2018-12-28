import requests as r
from concurrent.futures import ThreadPoolExecutor
from requests_futures.sessions import FuturesSession
import asyncio
import json
import sys

BASE = "https://esi.evetech.net/latest/"

# Need bid-ask cross of at least this much
PROFIT_THRESHOLD = 0.10

# Get all market data
regions = json.loads(r.get(BASE + "universe/regions/?datasource=tranquility").text)

region_orderbook = {}

total = len(regions)
region_progress = 1

# OVERRIDE REGIONS
regions = [10000016]

# TODO: Async
for region in regions:
    print("Getting orders for %d out of % d regions..." % (region_progress, total))

    # TODO: use x-pages to create queue size
    region_orderbook[region] = []
    page_count = 1

    # Get regional prices, check for price difference intra-region and cross region.
    MARKET_BASE = BASE + "markets/" + str(region) + "/orders/?datasource=tranquility&order_type=all&page="
    req = r.get(MARKET_BASE + str(page_count))
    # Total pages for region orders
    try:
        page_total = int(req.headers["X-Pages"])
    except:
        region_progress += 1
        print("Fucked up on region %d, skipping" % region)
        continue
    # First set of orders, need to init the region orderbook 
    # since we get 1 page even if it's empty (not 0 pages)
    orders = json.loads(req.text)
    region_orderbook[region].append(orders)
    # Now check if there are more
    if page_total > 1:
        # Define region-specific hook for putting in async orderbook
        def resp_hook(resp, *args, **kwargs):
            try:
                o = json.loads(resp.text)
            except json.decoder.JSONDecodeError:
                return
            region_orderbook[region].append(o)
        # Do all the pages
        # TODO: Clean up?
        session = FuturesSession(executor=ThreadPoolExecutor(max_workers=5))

        pages_todo = list(range(2, page_total + 1))
        send_reqs = lambda i: session.get(MARKET_BASE + str(i), hooks={"response" : resp_hook})
        futures = list(map(send_reqs, pages_todo))
        for future in futures:
            future.result()
            page_count += 1
            print("Finished response %d of %d" % (page_count, page_total))

    region_progress += 1

# Look for bid/ask cross and % amount. Example of order:
# {'duration': 90, 'is_buy_order': False, 'issued': '2018-12-23T13:26:33Z', 'location_id': 60012133, 'min_volume': 1, 'order_id': 5323620377, 'price': 599999.99, 'range': 'region', 'system_id': 30000107, 'type_id': 30488, 'volume_remain': 43, 'volume_total': 51}
total_buys = {}
total_sells = {}

region_tradeable_items = {}

for region in regions:
    # For each order list, collect items.
    # We only accept trades if there's 10% or more of profit.
    regional_buys = {}
    regional_sells = {}
    for order_list in region_orderbook[region]:
        for order in order_list:
            if order["is_buy_order"]:
                if order["type_id"] in regional_buys:
                    regional_buys[order["type_id"]].append(order)
                else:
                    regional_buys[order["type_id"]] = [order]
                if order["type_id"] in total_buys:
                    total_buys[order["type_id"]].append(order)
                else:
                    total_buys[order["type_id"]] = [order]
            else:
                if order["type_id"] in regional_sells:
                    regional_sells[order["type_id"]].append(order)
                else:
                    regional_sells[order["type_id"]] = [order]
                if order["type_id"] in total_sells:
                    total_sells[order["type_id"]].append(order)
                else:
                    total_sells[order["type_id"]] = [order]
    # For each item (type) that is purchasable, check whether it can be sold for a profit.
    # If so, then check the capacity of that trade.
    tradeable_items = []
    for item_id in regional_buys.keys():
        best_bid = max(regional_buys[item_id], key=lambda b: b["price"])
        try:
            best_offer = max(regional_sells[item_id], key=lambda b: b["price"])
        except KeyError:
            continue
        if best_bid["price"] / best_offer["price"] - 1 > PROFIT_THRESHOLD:
            tradeable_items.append(best_bid["type_id"])
    region_tradeable_items[region] = tradeable_items
    print("Done tradeable items for region %d" % region)

# Report item name
for region in region_tradeable_items.keys():
    tradeable = region_tradeable_items[region]
    req = r.post(BASE + "universe/names/?datasource=tranquility",
            json=tradeable)
    region_req = r.post(BASE + "universe/names/?datasource=tranquility",
            json=[region])
    tradeable_names = json.loads(req.text)
    print("Region: %s " % region_req.text)
    print(tradeable_names)
