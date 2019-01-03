import json
import shutil
import math
import queue
import sys
import time

# Also saves path
def construct_path_to_region(n, parent_map):
    path = [n]
    curr = n
    while parent_map[curr] != None:
        path.append(parent_map[curr])
        curr = parent_map[curr]
    path.reverse()
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

def get_route_to_region(orig, dest_reg_name, route_map, star_map, max_distance=math.inf):
    # Always try to lookup first
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
        if star_map["nodes"][str(neighbour)]["region"] == dest_reg_name:
            return(construct_path_to_region(neighbour, parent_map))

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
    dest_region_name = sys.argv[2]

    path = get_route_to_region(orig, dest_region_name, neighbour_map, star_map)
    print("Length: %d" % (len(path)-1))
    print("Shortest path: %r" % list(zip(list(map(lambda x: get_system_name(x, star_map), path)), list(map(lambda x: star_map["nodes"][str(x)]["security"], path)))))

