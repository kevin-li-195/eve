import argparse
import requests as r
import time
import multiprocessing as mp
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

# Skip the system id 31000005 because it's Thera

parser = argparse.ArgumentParser(description="Evaluate trades in New Eden for best hauls.")
parser.add_argument("current_system")
parser.add_argument("-a", "--avoid_null", action="store_true")
args = parser.parse_args()

print(args)
# Need current system
CURRENT_SYSTEM = args.current_system
AVOID_NULL_SEC = args.avoid_null

# Drop regions instead (blacklist not whitelist)
REGION_BLACKLIST = ["G-R00031"]

# Drop items that we don't want to see (they may take a long time)
# such as Pyerite or Tritanium, where if we have a small ship then
# it's not worth it to spend the time to check.
# ITEM_BLACKLIST = []
ITEM_BLACKLIST = set([
          "Heavy Water"
        , "Pyerite"
        , "Strontium Clathrates"
        , "Liquid Ozone"
        , "Tritanium"
        , "Water"
        , "Oxygen Isotopes"
        , "Coolant"
        , "Hydrogen Isotopes"
        , "Isogen"
        , "Oxygen"
        , "Robotics"
        , "Spirits"
        , "Raysere's Modified Large Armor Repairer"
        , "Brokara's Modified Kinetic Plating"
        ])

TAX = 0.014

BROKERS_FEE = 0.024

# TODO: Take into account player position when looking for valuable hauls

# Minimum profit threshold
MIN_PROFIT_PERCENT = 0.05

# Min profit amount
MIN_PROFIT_AMOUNT = 10000000

# Number of trades displayed
TRADE_NUM_LIMIT = 3

# Max volume total trade
MAX_VOLUME_PER_HAUL = 1170.4

# Maximum number of jumps willing to go
MAX_JUMPS = 35

# TODO: min profit per jump per haul
PROFIT_PER_JUMP = 800000

# Base URL
BASE = "https://esi.evetech.net/latest/"

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
    return(len(l)-1)

# Get all orders in New Eden
def get_orders(region_blacklist=[]):
    # Load a shit ton of stuff into memory.
    with open("region_list.json", "r") as f:
        regions = json.load(f)
    with open("inv_region_map.json", "r") as f:
        inv_region_map = json.load(f)
    regions = list(map(lambda x: x["id"], regions))
    # Blacklist regions
    for bl in region_blacklist:
        regions.remove(int(inv_region_map[bl]))

    region_orderbook = {}

    total = len(regions)
    region_progress = 0

    #### OVERRIDE #### (for testing)
    # regions = [10000002, 10000016]

    for region in regions:

        region_orderbook[region] = []
        page_count = 1
        region_progress += 1

        # Get regional prices, check for price difference intra-region and cross region.
        MARKET_BASE = BASE + "markets/" + str(region) + "/orders/?datasource=tranquility&order_type=all&page="
        req = r.get(MARKET_BASE + str(page_count))
        # Total pages for region orders
        try:
            page_total = int(req.headers["X-Pages"])
        except:
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
            session = FuturesSession(executor=ThreadPoolExecutor(max_workers=40))

            pages_todo = list(range(2, page_total + 1))
            send_reqs = lambda i: session.get(MARKET_BASE + str(i), hooks={"response" : resp_hook})
            futures = list(map(send_reqs, pages_todo))
            for future in futures:
                print("Finished response %d of %d" % (page_count, page_total), file=sys.stderr)
                future.result()
                page_count += 1


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
    return(total_buys, total_sells)

# Now that route map is creatable, we can check for profitable short hauls
# TODO: volume constraint
if __name__ == "__main__":
    print("Getting all orders...", file=sys.stderr)
    start_time = time.time()
    all_buys, all_sells = get_orders(region_blacklist=REGION_BLACKLIST)

    # Load required resources
    with open("star_map.json", "r") as f:
        star_map = json.load(f)
    with open("neighbour_map.json", "r") as f:
        neighbour_map = json.load(f)
    with open("item_map.json", "r") as f:
        item_map = json.load(f)

    # Get current system ID.
    CURRENT_SYSTEM_ID = None
    for node in star_map["nodes"].keys():
        if star_map["nodes"][node]["name"] == CURRENT_SYSTEM:
            CURRENT_SYSTEM_ID = int(node)
    if CURRENT_SYSTEM_ID is None:
        print("%s is not a system." % CURRENT_SYSTEM)
        sys.exit(1)

    N_items = len(list(set(all_buys.keys()) & set(all_sells.keys())))

    def extract_profitable_orders(item_id, all_buys, all_sells, extracted_orders_dict, count_so_far, lock):
        # Check if there are sellers
        if item_id not in all_sells:
            return()
        item_name = item_map[str(item_id)]["name"]
        if item_name in ITEM_BLACKLIST:
            return()
        lock.acquire()
        count_so_far.value += 1
        print("%d of %d. Analyzing trades for item '%s'." % (count_so_far.value, N_items, item_name))
        lock.release()

        item_volume = item_map[str(item_id)]["packaged_volume"]
        # We can take partial trades, which means that we
        # only filter these out if we can't even carry a single unit
        if item_volume > MAX_VOLUME_PER_HAUL:
            return()

        curr_item_buys = all_buys[item_id]
        curr_item_sells = all_sells[item_id]
        # Sort buys by highest first, sells by lowest first
        # curr_item_buys.sort(key=lambda x: x["price"], reverse=True)
        # curr_item_sells.sort(key=lambda x: x["price"])
        # Max bid first
        # max_buy = curr_item_buys[0]
        max_buy = max(curr_item_buys, key=lambda x: x["price"])
        # Min ask first
        # min_sell = curr_item_sells[0]
        min_sell = min(curr_item_sells, key=lambda x: x["price"])

        # Collect trades, sort by jump length.
        # Trade is triple of jump length, ask order, and bid order.
        possible_trades = []

        order_analysis_start = time.time()
        for ask in curr_item_sells:
            # Thera
            if ask["system_id"] == 31000005:
                continue
            
            # Profitable? Only check against profitable bids.
            # TODO: Make faster

            # If even the highest bid doesn't make this ask profitable,
            # then skip it
            if AVOID_NULL_SEC and star_map["nodes"][str(ask["system_id"])]["security"] <= 0:
                continue

            if max_buy["price"] / ask["price"] - 1 < MIN_PROFIT_PERCENT:
                continue
            for bid in curr_item_buys:
                # Thera
                if bid["system_id"] == 31000005:
                    continue
                # Filter out the trades that don't fit our requirements

                if AVOID_NULL_SEC and star_map["nodes"][str(bid["system_id"])]["security"] <= 0:
                    continue

                if bid["price"] / ask["price"] - 1 < MIN_PROFIT_PERCENT:
                    continue

                cross_vol = min(bid["volume_remain"], ask["volume_remain"])
                gross_profit = cross_vol * (bid["price"] - ask["price"])
                if gross_profit < MIN_PROFIT_AMOUNT:
                    continue

                try:
                    curr_system_to_pickup_route = shortest_path.get_route(CURRENT_SYSTEM_ID, ask["system_id"], neighbour_map, star_map, max_distance=MAX_JUMPS)
                    if curr_system_to_pickup_route == []:
                        continue
                    rem_length = route_length(curr_system_to_pickup_route)
                    route = shortest_path.get_route(ask["system_id"], bid["system_id"], neighbour_map, star_map, max_distance=(MAX_JUMPS - rem_length))
                except KeyError:
                    continue
                if route == []:
                    continue
                length = route_length(route) + route_length(curr_system_to_pickup_route)
                units_per_haul = int(MAX_VOLUME_PER_HAUL / item_volume)
                # Check for profit per jump. Note that we need to
                # take into account constraints on volume (i.e. this is the
                # actual profit per jump using the given ship volume, not the
                # total profit per jump for the entire order)
                if length == 0:
                    profit_per_jump = min(units_per_haul, cross_vol) * (bid["price"] * (1-TAX) - ask["price"])
                else:
                    profit_per_jump = min(units_per_haul, cross_vol) * (bid["price"] * (1-TAX) - ask["price"]) / length
                if profit_per_jump < PROFIT_PER_JUMP:
                    continue
                possible_trades.append((length, ask, bid))
        # Track best by jump length
        best_trade_by_jump = dict.fromkeys(range(MAX_JUMPS+1), list())
        for trade in possible_trades:
            curr_length = trade[0]

            # Only take trades that are less than min length.
            if curr_length > MAX_JUMPS:
                continue
            ask_order = trade[1]
            bid_order = trade[2]
            best_trade_by_jump[curr_length].append(trade)
        for length in best_trade_by_jump.keys():
            if best_trade_by_jump[length] is not None:
                best_trade_by_jump[length].sort(reverse=True, key=get_trade_value)
        extracted_orders_dict[item_id] = best_trade_by_jump

    # Multithread
    manager = mp.Manager()
    hauls_to_best_trade_map = manager.dict()
    counter = manager.Value('i', 0)
    lock = manager.Lock()

    def f(x):
        extract_profitable_orders(x, all_buys, all_sells, hauls_to_best_trade_map, counter, lock)

    analysis_start_time = time.time()

    with mp.Pool() as p:
        p.map(f, list(all_buys.keys()))

    # Transform all best hauls to list of hauls, then sort by ISK/jump
    all_hauls_list = [t 
            for length_dict in hauls_to_best_trade_map.values()
            for trade_list in length_dict.values()
            for t in trade_list]

    # ISK per jump for a single haul subject to capacity and number available to trade constraint
    def isk_per_jump(trade):
        length = trade[0]
        ask = trade[1]
        bid = trade[2]
        item_id = ask["type_id"]
        packaged_volume = item_map[str(item_id)]["packaged_volume"]
        cross_vol = min(ask["volume_remain"], bid["volume_remain"])
        max_number_per_haul = int(MAX_VOLUME_PER_HAUL / packaged_volume)
        units_per_haul = min(cross_vol, max_number_per_haul)
        after_tax = (units_per_haul * ((1-TAX) * bid["price"] - ask["price"]))
        return(after_tax / length)

    get_system_name = lambda sys_id: star_map["nodes"][str(sys_id)]["name"]

    all_hauls_list.sort(
            reverse=True,
            key=isk_per_jump
            )

    # For each item, print only TRADE_NUM_LIMIT trades
    trades_printed = {}

    print("Presenting trades now...", file=sys.stderr)
    all_trades_file = open("all_trades_report.txt", "w")
    for trade in all_hauls_list:
        total_length = trade[0]
        ask = trade[1]
        bid = trade[2]
        item_id = ask["type_id"]
        item_name = item_map[str(item_id)]["name"]
        if item_name not in trades_printed:
            trades_printed[item_name] = 0
        else:
            trades_printed[item_name] += 1
        if trades_printed[item_name] >= TRADE_NUM_LIMIT:
            continue
        cross_vol = min(ask["volume_remain"], bid["volume_remain"])
        # Path from current sys to pickup sys
        path_to_pickup = shortest_path.get_route(CURRENT_SYSTEM_ID, ask["system_id"], neighbour_map, star_map, max_distance=MAX_JUMPS)
        # Number of jumps from curr sys to pickup sys
        length_to_pickup = route_length(path_to_pickup)
        # m3 per unit
        packaged_vol = item_map[str(item_id)]["packaged_volume"]
        units_per_haul = int(MAX_VOLUME_PER_HAUL / packaged_vol)
        print("--------------------------", file=all_trades_file)
        print("| Total %s units of %s | %s m3 per unit | %s total m3 | %s units per max haul |" % 
                (
                "{:,.2f}".format(cross_vol),
                item_name,
                "{:,.2f}".format(packaged_vol),
                "{:,.2f}".format(cross_vol * packaged_vol),
                "{:,}".format(min(units_per_haul, cross_vol))
            ),
            file=all_trades_file
        )
        print("| Buy @ %s, Sell @ %s | %s ISK (gross total) | %s ISK (net total) |" % (
                "{:,.2f}".format(ask["price"]),
                "{:,.2f}".format(bid["price"]),
                "{:,.2f}".format(cross_vol * (bid["price"] * (1-TAX) - ask["price"])),
                "{:,.2f}".format(cross_vol * (bid["price"] * (1-TAX-BROKERS_FEE) - ask["price"]))),
            file=all_trades_file)
        print("| %0.2f%% total gross return | %0.2f%% total net return |" % (
                (bid["price"] / ask["price"] - 1) * 100,
                (bid["price"] * (1-TAX-BROKERS_FEE) / ask["price"] - 1) * 100),
            file=all_trades_file)
        print("| %s gross per max haul | %s net per max haul |" % (
                "{:,.2f}".format(min(units_per_haul, cross_vol) * (bid["price"] * (1-TAX) - ask["price"])),
                "{:,.2f}".format(min(units_per_haul, cross_vol) * (bid["price"] * (1-TAX-BROKERS_FEE) - ask["price"]))
                ),
            file=all_trades_file)
        print("| %d + %d jumps | %s, %s (%0.2f sec) -> %s, %s (%0.2f sec) | '%s' pickup range | '%s' dropoff range |" % (
            length_to_pickup,
            total_length-length_to_pickup,
            get_system_name(ask["system_id"]),
            star_map["nodes"][str(ask["system_id"])]["region"],
            star_map["nodes"][str(ask["system_id"])]["security"],
            get_system_name(bid["system_id"]),
            star_map["nodes"][str(bid["system_id"])]["region"],
            star_map["nodes"][str(bid["system_id"])]["security"],
            ask["range"],
            bid["range"]
            ),
            file=all_trades_file)
        print("| %s gross/max haul/jump | %s net/max haul/jump |" % (
                "{:,.2f}".format(min(units_per_haul, cross_vol) * (bid["price"] * (1-TAX) - ask["price"]) / total_length),
                "{:,.2f}".format(min(units_per_haul, cross_vol) * (bid["price"] * (1-TAX-BROKERS_FEE) - ask["price"]) / total_length)
                ),
            file=all_trades_file)
        print("--------------------------", file=all_trades_file)
        print(file=all_trades_file)
    end_time = time.time()
    diff_time = end_time - start_time
    analysis_diff_time = end_time - analysis_start_time
    print("Total time taken: %d:%0.2f" % (int(diff_time / 60), diff_time % 60))
    print("Trade analysis time taken: %d:%d" % (int(analysis_diff_time / 60), int(analysis_diff_time % 60)))

    # Now we have all the best hauls indexed by item id, and then by jump length
    # Just present these in a decent way

    # # TODO: Keep track of safe routes (i.e. map with all systems with <4.5 sec removed)
    # # and use to build min-length highsec hauls.
    # # TODO: Low-sec hauls can be done with low volume (fast align)
    # # TODO: Rank by ISK/jump
    # for item_id in hauls_to_best_trade_map.keys():
    #     item_name = item_map[str(item_id)]["name"]
    #     length_to_trades_map = hauls_to_best_trade_map[item_id]
    #     # If all are None, don't print the item name
    #     none_trades = map(lambda x: x is None, length_to_trades_map.values())
    #     if all(none_trades):
    #         continue
    #     print(">>>>>>>>>>>>>>", file=all_trades_file)
    #     print("Trades for item: '%s'" % item_name, file=all_trades_file)
    #     for total_length in length_to_trades_map.keys():
    #         if length_to_trades_map[total_length] is None:
    #             continue
    #         print("Item: '%s' : Length: %d" % (item_name, total_length), file=all_trades_file)
    #         count = 1
    #         for trade in length_to_trades_map[total_length]:
    #             if count > TRADE_NUM_LIMIT:
    #                 break
    #             count += 1
    #             ask = trade[1]
    #             bid = trade[2]
    #             # TODO: rename because volume means diff things
    #             # Num of units traded
    #             cross_vol = min(ask["volume_remain"], bid["volume_remain"])
    #             # Path from current sys to pickup sys
    #             path_to_pickup = shortest_path.get_route(CURRENT_SYSTEM_ID, ask["system_id"], neighbour_map, star_map, max_distance=MAX_JUMPS)
    #             # Number of jumps from curr sys to pickup sys
    #             length_to_pickup = route_length(path_to_pickup)
    #             # m3 per unit
    #             packaged_vol = item_map[str(item_id)]["packaged_volume"]
    #             units_per_haul = int(MAX_VOLUME_PER_HAUL / packaged_vol)
    #             print("| Total %s units of %s | %s m3 per unit | %s total m3 | %s units per max haul |" % 
    #                     (
    #                     "{:,.2f}".format(cross_vol),
    #                     item_name,
    #                     "{:,.2f}".format(packaged_vol),
    #                     "{:,.2f}".format(cross_vol * packaged_vol),
    #                     "{:,}".format(min(units_per_haul, cross_vol))
    #                 ),
    #                 file=all_trades_file
    #             )
    #             print("| Buy @ %s, Sell @ %s | %s ISK (gross total) | %s ISK (net total) |" % (
    #                     "{:,.2f}".format(ask["price"]),
    #                     "{:,.2f}".format(bid["price"]),
    #                     "{:,.2f}".format(cross_vol * (bid["price"] * (1-TAX) - ask["price"])),
    #                     "{:,.2f}".format(cross_vol * (bid["price"] * (1-TAX-BROKERS_FEE) - ask["price"]))),
    #                 file=all_trades_file)
    #             print("| %0.2f%% total gross return | %0.2f%% total net return |" % (
    #                     (bid["price"] / ask["price"] - 1) * 100,
    #                     (bid["price"] * (1-TAX-BROKERS_FEE) / ask["price"] - 1) * 100),
    #                 file=all_trades_file)
    #             print("| %s gross per max haul | %s net per max haul |" % (
    #                     "{:,.2f}".format(min(units_per_haul, cross_vol) * (bid["price"] * (1-TAX) - ask["price"])),
    #                     "{:,.2f}".format(min(units_per_haul, cross_vol) * (bid["price"] * (1-TAX-BROKERS_FEE) - ask["price"]))
    #                     ),
    #                 file=all_trades_file)
    #             print("| %d + %d jumps | %s, %s (%0.2f sec) -> %s, %s (%0.2f sec) | '%s' pickup range | '%s' dropoff range |" % (
    #                 length_to_pickup,
    #                 total_length-length_to_pickup,
    #                 get_system_name(ask["system_id"]),
    #                 star_map["nodes"][str(ask["system_id"])]["region"],
    #                 star_map["nodes"][str(ask["system_id"])]["security"],
    #                 get_system_name(bid["system_id"]),
    #                 star_map["nodes"][str(bid["system_id"])]["region"],
    #                 star_map["nodes"][str(bid["system_id"])]["security"],
    #                 ask["range"],
    #                 bid["range"]
    #                 ),
    #                 file=all_trades_file)
    #             print("| %s gross/max haul/jump | %s net/max haul/jump |" % (
    #                     "{:,.2f}".format(min(units_per_haul, cross_vol) * (bid["price"] * (1-TAX) - ask["price"]) / total_length),
    #                     "{:,.2f}".format(min(units_per_haul, cross_vol) * (bid["price"] * (1-TAX-BROKERS_FEE) - ask["price"]) / total_length)
    #                     ),
    #                 file=all_trades_file)
    #             path_to_pickup = shortest_path.get_route(CURRENT_SYSTEM_ID, ask["system_id"], neighbour_map, star_map, max_distance=MAX_JUMPS)
    #             # rem_path = shortest_path.get_route(ask["system_id"], bid["system_id"], neighbour_map, star_map, max_distance=MAX_JUMPS)
    #             # print("Route: %r" % 
    #             #         list(zip(
    #             #             map(get_system_name, path),
    #             #             map(lambda x: star_map["nodes"][str(x)]["region"], rem_path),
    #             #             map(lambda x: star_map["nodes"][str(x)]["security"], rem_path)
    #             #             )
    #             #             ),
    #             #         file=all_trades_file)
    #             print(file=all_trades_file)
    #         print(file=all_trades_file)
    # end_time = time.time()
    # diff_time = end_time - start_time
    # analysis_diff_time = end_time - analysis_start_time
    # print("Total time taken: %d:%0.2f" % (int(diff_time / 60), diff_time % 60))
    # print("Trade analysis time taken: %d:%d" % (int(analysis_diff_time / 60), int(analysis_diff_time % 60)))

    # # Example order
    # # {'duration': 90, 'is_buy_order': False, 'issued': '2018-12-23T13:26:33Z', 'location_id': 60012133, 'min_volume': 1, 'order_id': 5323620377, 'price': 599999.99, 'range': 'region', 'system_id': 30000107, 'type_id': 30488, 'volume_remain': 43, 'volume_total': 51}

    # # Report 
    # # - required capital
    # # - volume 
    # # - profit (% and ISK) per trade
    # # - route and security of each system

    # # Then, given current system, find the distance for each one of those.
    # # Estimate time per jump/distance, and then get the most time-efficient haul
    # '''
    # shape of thing you get from item_map
    # {
    #   "capacity": 0,
    #   "description": "This SKIN only applies to Medium Caldari dropsuit frames!",
    #   "group_id": 368726,
    #   "mass": 0,
    #   "name": "Medium Caldari SKIN - Red",
    #   "packaged_volume": 0,
    #   "portion_size": 1,
    #   "published": false,
    #   "radius": 1,
    #   "type_id": 368725,
    #   "volume": 0
    # }
    # '''
