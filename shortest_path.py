import json
import shutil
import math
import queue
import sys
import time

try:
    with open("route_maps/route_map.json", "r") as f:
        CACHED_ROUTE_MAP = json.load(f)
except:
    CACHED_ROUTE_MAP = {}

# Also saves path
def construct_path(n, parent_map, save_path=False):
    path = [n]
    curr = n
    while parent_map[curr] != None:
        path.append(parent_map[curr])
        curr = parent_map[curr]
    path.reverse()
    if save_path:
        if path[0] in CACHED_ROUTE_MAP:
            CACHED_ROUTE_MAP[path[0]][path[-1]] = path
        else:
            CACHED_ROUTE_MAP[path[0]] = {path[-1] : path}
        target_name = ("route_maps/route_map_%0.4f.json" % (time.time()))
        try:
            shutil.move("route_maps/route_map.json", target_name)
        except:
            pass
        with open("route_maps/route_map.json", "w") as f:
            json.dump(CACHED_ROUTE_MAP, f)
    return(path)

def get_system_id(name, star_map):
    for node_str in star_map["nodes"].keys():
        node_id = int(node_str)
        if star_map["nodes"][node_str]["name"] == name:
            return(node_id)
    raise KeyError("The system %s was not found in the star map." % name)

def get_system_name(sys_id, star_map):
    for node_str in star_map["nodes"]:
        node_id = int(node_str)
        if node_id == sys_id:
            return(star_map["nodes"][node_str]["name"])

def get_route(orig, dest, route_map, star_map, max_distance=math.inf):
    # Always try to lookup first
    if str(orig) in CACHED_ROUTE_MAP and str(dest) in CACHED_ROUTE_MAP[str(orig)]:
        cached_route = CACHED_ROUTE_MAP[str(orig)][str(dest)]
        if len(cached_route) > max_distance:
            return([])
        return(cached_route)
    if str(dest) in CACHED_ROUTE_MAP and str(orig) in CACHED_ROUTE_MAP[str(dest)]:
        cached_route = CACHED_ROUTE_MAP[str(dest)][str(orig)]
        if len(cached_route) > max_distance:
            return([])
        return(list(reversed(cached_route)))
    open_set = queue.Queue()
    closed_set = set()

    parent_map = {orig : None}
    open_set.put(orig)
    dist = 0
    distance_map = {orig : 0}
    while not open_set.empty():
        neighbour = int(open_set.get())
        dist = distance_map[neighbour]
        if dist > max_distance:
            return([])
        if neighbour == dest:
            return(construct_path(neighbour, parent_map, save_path=True))

        children = route_map[str(neighbour)]

        for child in children:
            if child in closed_set:
                continue
            if child not in parent_map:
                parent_map[child] = neighbour
            open_set.put(child)
            distance_map[child] = distance_map[neighbour] + 1
        closed_set.add(neighbour)
    return([])

if __name__ == "__main__":
    with open("star_map.json", "r") as f:
        star_map = json.load(f)

    with open("better_map.json", "r") as f:
        neighbour_map = json.load(f)

    orig = get_system_id(sys.argv[1], star_map)
    dest = get_system_id(sys.argv[2], star_map)

    path = get_route(orig, dest, neighbour_map, star_map)
    print("Length: %d" % (len(path)-1))
    print("Shortest path:")
    for triple in zip(
            list(map(lambda x: get_system_name(x, star_map), path)),
            list(map(lambda x: star_map["nodes"][str(x)]["region"], path)),
            list(map(lambda x: star_map["nodes"][str(x)]["security"], path))
            ):
        print("    -> %s, %s (%0.4f sec)" % triple)
