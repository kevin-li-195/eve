import requests as r
import shortest_path
import queue
import shutil
import pickle
from concurrent.futures import ThreadPoolExecutor
from requests_futures.sessions import FuturesSession
from pprint import pprint
import asyncio
import json
import sys

# Region override (i.e. take into account these regions).
# Set to None to get all regions.
'''
Heimatar : 10000030
Lonetrek : 10000016
Metropolis : 10000042
The Citadel : 10000033
The Forge : 10000002
'''

# REGION_OVERRIDE = [10000030,10000016,10000042,10000033,10000002]
REGION_OVERRIDE = None

TAX = 0.014

BROKERS_FEE = 0.027

# TODO: Take into account player position when looking for valuable hauls

# Minimum profit threshold
MIN_PROFIT_PERCENT = 0.28

# Min profit amount
# Currently 1mil
MIN_PROFIT_AMOUNT = 1000000

# Max volume for a haul
MAX_VOLUME = 20000

# Maximum number of jumps willing to go
MAX_JUMPS = 20

# Base URL
BASE = "https://esi.evetech.net/latest/"

# Limit number of trades shown per item per jump length
TRADE_NUM_LIMIT = 10

# def get_routemap_with_trades(route_filename="eve_routemap.pickle", region_override=None):
#     all_buys, all_sells = get_orders(region_override=region_override)
# 
#     # TODO: Save this map locally.
#     # Try load route map as pickle.
#     print("Loading route map")
#     try:
#         with open(route_filename, "rb") as f:
#             route_map = pickle.load(f)
#     except:
#         print("Creating route map for the first time")
#         route_map = {}
#     print("Finished loading route map")
#     # Keep track of futures when getting coordinates.
#     route_futures = {}
#     # Session to launch API queries.
#     session = FuturesSession(executor=ThreadPoolExecutor(max_workers=10))
#     # Get all items that have trades
#     N_items = len(list(set(all_buys.keys()) & set(all_sells.keys())))
#     item_count = 1
#     asked_routes = set()
#     for item_id in all_buys.keys():
#         # Check if there are sellers
#         if item_id not in all_sells:
#             continue
#         if item_count % 500 == 0:
#             print("Analyzing distances for item %d of %d" % (item_count, N_items))
#         item_count += 1
#         curr_item_buys = all_buys[item_id]
#         curr_item_sells = all_sells[item_id]
#         # Max bid first
#         max_buy = max(curr_item_buys, key=lambda x: x["price"])
#         min_sell = min(curr_item_sells, key=lambda x: x["price"])
#         # curr_item_buys.sort(reverse=True, key=lambda x: x["price"])
#         # curr_item_sells.sort(key=lambda x: x["price"])
#         # Only look for profitable at a certain threshold.
#         # Keep the bids and asks such that all within the collection
#         # permit a MIN_PROFIT_PERCENT.
#         # We consider bid/asks viable if it is possible, without considering volume,
#         # to sell at a min profit in a single order. This is basically a preprocessing step.
#         viable_asks = [a for a in curr_item_sells if max_buy["price"] / a["price"] - 1 > MIN_PROFIT_PERCENT]
#         viable_bids = [a for a in curr_item_buys if a["price"] / min_sell["price"] - 1 > MIN_PROFIT_PERCENT]
#         # For each order check distance from other orders.
#         # Use adjacency map (x, y) to distance.
#         # Note: API returns both origin and destination within list.
#         # If return 1 -> 0 jumps. If return 2 -> 1 jump. If return n, n > 3, then n-2 jumps.
# 
#         for ask in viable_asks:
#             # Profitable? Only check against profitable bids.
#             sub_viable_bids = [b for b in viable_bids if b["price"] / ask["price"] - 1 > MIN_PROFIT_PERCENT]
#             ask_station = ask["location_id"]
#             # Routes
#             for bid in sub_viable_bids:
#                 # Maybe hit API (if the thing isn't there) async and then wait.
#                 # (origin, dest) as key. use system id.
#                 # Does system of location id ever
#                 # not point to the system id?
#                 curr_route = (ask["system_id"], bid["system_id"])
#                 if curr_route not in route_map and curr_route not in asked_routes:
#                     fut = session.get(
#                             BASE + ("route/%d/%d/" % (ask["system_id"], bid["system_id"]))
#                             )
#                     asked_routes.add(curr_route)
#                     route_futures[curr_route] = fut
# 
#     # Wait for all API queries after all requests are done
#     N = len(route_futures)
#     futures_count = 1
#     for curr_route in route_futures.keys():
#         future = route_futures[curr_route]
#         if futures_count % 500 == 0:
#             print("Awaiting route request %d of %d" % (futures_count, N))
#         req = future.result()
#         try:
#             route_list = json.loads(req.text)
#             if isinstance(route_list, list):
#                 # Add
#                 route_map[curr_route] = route_list
#             else:
#                 # Error, skip
#                 print("Error: did not get route list back from route %r. Skipping" % curr_route)
#         except json.decoder.JSONDecodeError:
#             print("Failed to decode routelist: '%s'. Skipping" % req.text)
#         futures_count += 1
#     # Return the constructed map
#     try:
#         shutil.move(route_filename, route_filename + ".bak")
#     except FileNotFoundError:
#         pass
#     with open(route_filename, "wb") as f:
#         pickle.dump(route_map, f)
#     return(route_map, all_buys, all_sells)

# Given list of IDs, make name map.
# Note max items is 1000
def make_name_map(ids):
    url = BASE + "universe/names/?datasource=tranquility"
    chunks = [ids[x:x+1000] for x in range(0, len(ids), 1000)]
    # Objects returned
    returned = []
    final = {}
    for chunk in chunks:
        req = r.post(url, json=chunk)
        ret_obj = json.loads(req.text)
        if isinstance(ret_obj, list):
            returned.extend(json.loads(req.text))
        else:
            print("Weird fuckup in name map creation. Dumping JSON.", file=sys.stderr)
            print(req.text)
    for ret in returned:
        final[ret["id"]] = ret["name"]
    return(final)

# trade : triple of (jump length, ask, bid)
# Returns total return in ISK
def get_trade_value(trade):
    length = trade[0]
    ask = trade[1]
    bid = trade[2]
    cross_vol = min(ask["volume_remain"], bid["volume_remain"])
    return(cross_vol * (bid["price"] - ask["price"]))

def route_length(l):
    if len(l) <= 0:
        raise ValueError("Can't have route list with zero elem")
    if len(l) == 1:
        return(0)
    if len(l) == 2:
        return(1)
    if len(l) >= 3:
        return(len(l)-1)

# BFS
# def get_route(orig, dest, route_map, max_distance=None):
#     open_set = queue.Queue()
#     closed_set = set()
# 
#     parent_map = {orig : None}
#     open_set.put(orig)
#     dist = 0
#     while not open_set.empty():
#         if max_distance is not None and dist > max_distance:
#             return([])
#         neighbour = int(open_set.get())
#         if neighbour == dest:
#             return(construct_path(neighbour, parent_map))
# 
#         children = route_map[str(neighbour)]
# 
#         for child in children:
#             if child in closed_set:
#                 continue
#             parent_map[child] = neighbour
#             open_set.put(child)
#         closed_set.add(neighbour)
#         dist += 1
# 
# def construct_path(n, parent_map):
#     path = [n]
#     curr = n
#     while parent_map[curr] != None:
#         path.append(parent_map[curr])
#         curr = parent_map[curr]
#     path.reverse()
#     return(path)

# Get all orders in New Eden
def get_orders(region_override=None):
    
    # Get all market data
    regions = json.loads(r.get(BASE + "universe/regions/?datasource=tranquility").text)

    region_orderbook = {}

    total = len(regions)
    region_progress = 1

    # Override regions?
    if region_override is not None:
        regions = region_override

    for region in regions:

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
            print("Fucked up on region %d, skipping" % region, file=sys.stderr)
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
            session = FuturesSession(executor=ThreadPoolExecutor(max_workers=10))

            pages_todo = list(range(2, page_total + 1))
            send_reqs = lambda i: session.get(MARKET_BASE + str(i), hooks={"response" : resp_hook})
            futures = list(map(send_reqs, pages_todo))
            for future in futures:
                print("Finished response %d of %d" % (page_count, page_total), file=sys.stderr)
                future.result()
                page_count += 1

        region_progress += 1

    # Look for bid/ask cross and % amount. Example of order:
    # {'duration': 90, 'is_buy_order': False, 'issued': '2018-12-23T13:26:33Z', 'location_id': 60012133, 'min_volume': 1, 'order_id': 5323620377, 'price': 599999.99, 'range': 'region', 'system_id': 30000107, 'type_id': 30488, 'volume_remain': 43, 'volume_total': 51}
    total_buys = {}
    total_sells = {}

    # Eliminate trades with duplicate IDs
    all_order_ids = set()

    for region in regions:
        # For each order list, collect items.
        for order_list in region_orderbook[region]:
            for order in order_list:
                if order["order_id"] in all_order_ids:
                    continue
                all_order_ids.add(order["order_id"])
                if order["is_buy_order"]:
                    if order["type_id"] in total_buys:
                        total_buys[order["type_id"]].append(order)
                    else:
                        total_buys[order["type_id"]] = [order]
                else:
                    if order["type_id"] in total_sells:
                        total_sells[order["type_id"]].append(order)
                    else:
                        total_sells[order["type_id"]] = [order]
    print("done", file=sys.stderr)
    return(total_buys, total_sells)

# Now that route map is creatable, we can check for profitable short hauls
# TODO: volume constraint
if __name__ == "__main__":
    print("Getting route map...", file=sys.stderr)
    ################
    ### OVERRIDE ###
    ################
    all_buys, all_sells = get_orders(region_override=REGION_OVERRIDE)
    with open("star_map.json", "r") as f:
        route_map = json.load(f)
    with open("better_map.json", "r") as f:
        better_map = json.load(f)
    hauls_to_best_trade_map = {}
    item_count = 1
    N_items = len(list(set(all_buys.keys()) & set(all_sells.keys())))
    for item_id in all_buys.keys():
        # Check if there are sellers
        if item_id not in all_sells:
            continue
        if item_count % 1 == 0:
            print("Analyzing trades for item %d of %d" % (item_count, N_items), file=sys.stderr)
        item_count += 1
        curr_item_buys = all_buys[item_id]
        curr_item_sells = all_sells[item_id]
        # Max bid first
        max_buy = max(curr_item_buys, key=lambda x: x["price"])
        min_sell = min(curr_item_sells, key=lambda x: x["price"])
        # curr_item_buys.sort(reverse=True, key=lambda x: x["price"])
        # curr_item_sells.sort(key=lambda x: x["price"])
        # Only look for profitable at a certain threshold.
        # Keep the bids and asks such that all within the collection
        # permit a MIN_PROFIT_PERCENT.
        # We consider bid/asks viable if it is possible, without considering volume,
        # to sell at a min profit in a single order. This is basically a preprocessing step.
        viable_asks = [a for a in curr_item_sells if max_buy["price"] / a["price"] - 1 > MIN_PROFIT_PERCENT]
        viable_bids = [a for a in curr_item_buys if a["price"] / min_sell["price"] - 1 > MIN_PROFIT_PERCENT]
        # For each order check distance from other orders.
        # Use adjacency map (x, y) to distance.
        # Note: API returns both origin and destination within list.
        # If return 1 -> 0 jumps. If return 2 -> 1 jump. If return n, n > 3, then n-2 jumps.

        # Collect trades, sort by jump length.
        # Trade is triple of jump length, ask order, and bid order.
        possible_trades = []

        for ask in viable_asks:
            # Profitable? Only check against profitable bids.
            sub_viable_bids = [b for b in viable_bids if b["price"] / ask["price"] - 1 > MIN_PROFIT_PERCENT \
                    and min(b["volume_remain"], ask["volume_remain"]) * (b["price"] - ask["price"]) > MIN_PROFIT_AMOUNT]
            # Routes
            for bid in sub_viable_bids:
                try:
                    print("hi", file=sys.stderr)
                    route = shortest_path.get_route(ask["system_id"], bid["system_id"], better_map, route_map, max_distance=MAX_JUMPS)
                    print("bye", file=sys.stderr)
                except KeyError:
                    continue
                if route == []:
                    continue
                length = route_length(route)
                possible_trades.append((length, ask, bid))
        # Sort ascending by jump length
        possible_trades.sort(key=lambda x: x[0])
        # Track best by jump length
        best_trade_by_jump = dict.fromkeys(range(MAX_JUMPS+1))
        for trade in possible_trades:
            # TODO: Take into account distance from player!
            curr_length = trade[0]

            # Only take trades that are less than min length.
            if curr_length > MAX_JUMPS:
                continue
            ask_order = trade[1]
            bid_order = trade[2]
            if best_trade_by_jump[curr_length] is None:
                best_trade_by_jump[curr_length] = [trade]
            else:
                best_trade_by_jump[curr_length].append(trade)
        for length in best_trade_by_jump.keys():
            if best_trade_by_jump[length] is not None:
                best_trade_by_jump[length].sort(reverse=True, key=get_trade_value)
        hauls_to_best_trade_map[item_id] = best_trade_by_jump
    # Now we have all the best hauls indexed by item id, and then by jump length
    # Just present these in a decent way
    print("Presenting trades now...", file=sys.stderr)
    tradeable_item_ids = list(hauls_to_best_trade_map.keys())
    # TODO: Save item id name map
    item_name_map = make_name_map(tradeable_item_ids)
    # Now get region/system map
    # system_ids = set()
    # for l in route_map.values():
    #     for j in l:
    #         system_ids.add(j)
    # system_ids = list(system_ids)

    # system_names_map = make_name_map(system_ids)
    get_system_name = lambda sys_id: route_map["nodes"][str(sys_id)]["name"]
    for item_id in hauls_to_best_trade_map.keys():
        item_name = item_name_map[item_id]
        length_to_trades_map = hauls_to_best_trade_map[item_id]
        # If all are None, don't print the item name
        none_trades = map(lambda x: x is None, length_to_trades_map.values())
        if all(none_trades):
            continue
        print(">>>>>>>>>>>>>>")
        print("Trades for item: '%s'" % item_name)
        for length in length_to_trades_map.keys():
            if length_to_trades_map[length] is None:
                continue
            print("Item: '%s' : Length: %d" % (item_name, length))
            count = 1
            for trade in length_to_trades_map[length]:
                if count > TRADE_NUM_LIMIT:
                    break
                count += 1
                value = get_trade_value(trade)
                ask = trade[1]
                bid = trade[2]
                cross_vol = min(ask["volume_remain"], bid["volume_remain"])
                print("| %s units of %s | Buy @ %s, Sell @ %s | %s ISK (gross) | %s ISK (net) | %0.2f%% gross return | %0.2f%% net return | %d jumps | %s, %s (%0.2f sec) -> %s, %s (%0.2f sec) | '%s' pickup range | '%s' dropoff range |" % (
                    "{:,.2f}".format(cross_vol),
                    item_name,
                    "{:,.2f}".format(ask["price"]),
                    "{:,.2f}".format(bid["price"]),
                    "{:,.2f}".format(value),
                    "{:,.2f}".format(cross_vol * (bid["price"] * (1-TAX-BROKERS_FEE) - ask["price"])),
                    (bid["price"] / ask["price"] - 1) * 100,
                    (bid["price"] * (1-TAX-BROKERS_FEE) / ask["price"] - 1) * 100,
                    length,
                    get_system_name(ask["system_id"]),
                    route_map["nodes"][str(ask["system_id"])]["region"],
                    route_map["nodes"][str(ask["system_id"])]["security"],
                    get_system_name(bid["system_id"]),
                    route_map["nodes"][str(bid["system_id"])]["region"],
                    route_map["nodes"][str(bid["system_id"])]["security"],
                    ask["range"],
                    bid["range"]
                    )
                    )
                path = shortest_path.get_route(ask["system_id"], bid["system_id"], better_map, route_map, max_distance=MAX_JUMPS)
                print("Route: %r" % 
                        list(zip(
                            map(get_system_name, path),
                            map(lambda x: route_map["nodes"][str(x)]["region"], path),
                            map(lambda x: route_map["nodes"][str(x)]["security"], path)
                            )
                            )
                        )
            print()
        print(">>>>>>>>>>>>>>")
        print()

    # Example order
    # {'duration': 90, 'is_buy_order': False, 'issued': '2018-12-23T13:26:33Z', 'location_id': 60012133, 'min_volume': 1, 'order_id': 5323620377, 'price': 599999.99, 'range': 'region', 'system_id': 30000107, 'type_id': 30488, 'volume_remain': 43, 'volume_total': 51}

    # Report 
    # - required capital
    # - volume 
    # - profit (% and ISK) per trade
    # - route and security of each system

    # Then, given current system, find the distance for each one of those.
    # Estimate time per jump/distance, and then get the most time-efficient haul
