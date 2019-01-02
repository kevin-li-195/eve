import json
import queue
import sys

def construct_path(n, parent_map):
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

def get_route(orig, dest, route_map, star_map, max_distance=2000):
    open_set = queue.Queue()
    closed_set = set()

    parent_map = {orig : None}
    open_set.put(orig)
    dist = 0
    while dist < max_distance:
        next_neighbours = queue.Queue()
        while not open_set.empty():
            neighbour = int(open_set.get())
            if neighbour == dest:
                return(construct_path(neighbour, parent_map))

            children = route_map[str(neighbour)]

            for child in children:
                if child in closed_set:
                    continue
                if child not in parent_map:
                    parent_map[child] = neighbour
                next_neighbours.put(child)
            closed_set.add(neighbour)
        while not next_neighbours.empty():
            n = next_neighbours.get()
            open_set.put(n)

        dist += 1
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
    print("Shortest path: %r" % list(zip(list(map(lambda x: get_system_name(x, star_map), path)), list(map(lambda x: star_map["nodes"][str(x)]["security"], path)))))

