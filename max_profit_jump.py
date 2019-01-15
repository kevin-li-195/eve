import argparse
import requests as r
import time
import multiprocessing as mp
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
# Need current system to calculate total number of jumps for a given trade
parser.add_argument("current_system", help="Current system of pilot")
# Avoid null sec systems for buy-sell
parser.add_argument(
        "-n"
        , "--avoid_null"
        , action="store_true"
        , help="Set to avoid null sec systems' buy/sell orders"
        )
# Use only paths in hi-sec
parser.add_argument(
        "-l"
        , "--avoid_low"
        , action="store_true"
        , help="Set to avoid low sec systems' pathing"
        )
# Min profit percent
parser.add_argument(
        "--min_profit_percent"
        , type=float
        , help="Filter for minimum profit percentage (default 5%%)"
        , default=0.05
        )
# Min profit amount
parser.add_argument(
        "--min_profit_amount"
        , type=float
        , help="Filter for total minimum ISK profit amount after tax for a given trade (default 10mil ISK)"
        , default=10000000
        )
# Trade num limit
parser.add_argument(
        "--trade_num_limit"
        , type=int
        , help="Restrict number of trades shown for each given item (default 3)"
        , default=3
        )
# Max volume per haul
parser.add_argument(
        "--capacity"
        , type=float
        , help="Capacity of ship to count number of ships required for hauling (default 1170.4 m3)"
        , default=1170.4 # Sunesis fast warp + cargo fit
        )
# Max jumps
parser.add_argument(
        "--max_jumps"
        , type=int
        , help="Filter for maximum number of jumps for the full trade (default 30 jumps)"
        , default=30
        )
# Min profit per jump
parser.add_argument(
        "--profit_per_jump"
        , type=float
        , help="Filter for minimum profit per jump, taking into account distance and ship capacity (default 800k ISK)"
        , default=800000
        )
parser.add_argument(
        "--tax"
        , type=float
        , help="Tax rate (effective on sale) (default 2%%)"
        , default=0.02
        )
parser.add_argument(
        "--broker_fee"
        , type=float
        , help="Broker fee (effective only if setting limit sell order) (default 3%%)"
        , default=0.03
        )

args = parser.parse_args()

print(args)

TAX = args.tax
BROKERS_FEE = args.broker_fee

# Minimum profit threshold
MIN_PROFIT_PERCENT = args.min_profit_percent

# Min profit amount
MIN_PROFIT_AMOUNT = args.min_profit_amount

# Number of trades displayed
TRADE_NUM_LIMIT = args.trade_num_limit

# Max volume total trade
MAX_VOLUME_PER_HAUL = args.capacity

# Maximum number of jumps willing to go
MAX_JUMPS = args.max_jumps

# min profit per jump per haul
PROFIT_PER_JUMP = args.profit_per_jump

# Need current system
CURRENT_SYSTEM = args.current_system
# When avoiding null sec we only avoid null sec buy/sell stations.
# We don't really care about the routes because generally, if you avoid
# the buy sell points then there's no reason to end up in nullsec.
AVOID_NULL_SEC = args.avoid_null
# When avoid low sec, we have to use the safe map (the high-sec star
# and neighbour map)
AVOID_LOW_SEC = args.avoid_low

if AVOID_LOW_SEC:
    import high_sec_shortest_path as shortest_path
else:
    import shortest_path

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
if __name__ == "__main__":
    print("Getting all orders...", file=sys.stderr)
    start_time = time.time()
    all_buys, all_sells = get_orders(region_blacklist=REGION_BLACKLIST)

    # Load required resources
    with open("star_map.json", "r") as f:
        star_map = json.load(f)
    if AVOID_LOW_SEC:
        with open("high_sec_neighbour_map.json", "r") as f:
            neighbour_map = json.load(f)
    else:
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

            # If even the highest bid doesn't make this ask profitable,
            # then skip it
            if AVOID_NULL_SEC and star_map["nodes"][str(ask["system_id"])]["security"] <= 0:
                continue
            if AVOID_LOW_SEC and star_map["nodes"][str(ask["system_id"])]["security"] < 0.45:
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
                if AVOID_LOW_SEC and star_map["nodes"][str(bid["system_id"])]["security"] < 0.45:
                    continue

                if bid["price"] / ask["price"] - 1 < MIN_PROFIT_PERCENT:
                    continue

                cross_vol = min(bid["volume_remain"], ask["volume_remain"])
                after_tax_profit = cross_vol * ((1-TAX) * bid["price"] - ask["price"])
                if after_tax_profit < MIN_PROFIT_AMOUNT:
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
    if AVOID_LOW_SEC:
        target_filename = "high_sec_trades_report.txt"
    else:
        target_filename = "all_trades_report.txt"

    print("Presenting trades now...", file=sys.stderr)
    all_trades_file = open(target_filename, "w")

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
        print("| Buy @ %s, Sell @ %s | %s ISK (after-tax total) | %s ISK (after-tax+broker total) |" % (
                "{:,.2f}".format(ask["price"]),
                "{:,.2f}".format(bid["price"]),
                "{:,.2f}".format(cross_vol * (bid["price"] * (1-TAX) - ask["price"])),
                "{:,.2f}".format(cross_vol * (bid["price"] * (1-TAX-BROKERS_FEE) - ask["price"]))),
            file=all_trades_file)
        print("| %0.2f%% total after-tax return | %0.2f%% total after-tax+broker return |" % (
                (bid["price"] * (1-TAX) / ask["price"] - 1) * 100,
                (bid["price"] * (1-TAX-BROKERS_FEE) / ask["price"] - 1) * 100),
            file=all_trades_file)
        print("| %s after-tax per max haul | %s after-tax+broker per max haul |" % (
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
        print("| %s after-tax/max haul/jump | %s after-tax+broker/max haul/jump |" % (
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
    print("Output file: %s" % target_filename)
