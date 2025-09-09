import json
import random
import networkx as nx
import osmnx as ox
from dataclasses import dataclass
from transport_sim.agent import Agent
from transport_sim.city_loader import get_tram_lookup_for_city
from collections import defaultdict



def compute_stats(agents):
    stats = {
        "total_agents": len(agents),
        "unreachable": 0,
        "avg_distance": 0,
        "min_distance": float("inf"),
        "max_distance": 0,
        "modes": defaultdict(lambda: {
            "count": 0,
            "reachable_count": 0,
            "unreachable": 0,
            "total_distance": 0,
            "min_distance": float("inf"),
            "max_distance": 0,
            "avg_distance": None
        })
    }

    total_reachable = 0

    for agent in agents:
        mode = agent.mode
        mode_stats = stats["modes"][mode]
        mode_stats["count"] += 1

        if agent.status == 'unreachable':
            stats["unreachable"] += 1
            mode_stats["unreachable"] += 1
            continue

        # Reachable agent
        dist = agent.total_distance
        stats["avg_distance"] += dist
        stats["min_distance"] = min(stats["min_distance"], dist)
        stats["max_distance"] = max(stats["max_distance"], dist)
        total_reachable += 1

        mode_stats["reachable_count"] += 1
        mode_stats["total_distance"] += dist
        mode_stats["min_distance"] = min(mode_stats["min_distance"], dist)
        mode_stats["max_distance"] = max(mode_stats["max_distance"], dist)

    # Final averages
    if total_reachable > 0:
        stats["avg_distance"] /= total_reachable
    else:
        stats["avg_distance"] = None
        stats["min_distance"] = None
        stats["max_distance"] = None

    for mode, m in stats["modes"].items():
        if m["reachable_count"] > 0:
            m["avg_distance"] = m["total_distance"] / m["reachable_count"]
        else:
            m["avg_distance"] = None
            m["min_distance"] = None
            m["max_distance"] = None

    return stats

def load_config(path="transport_sim/config.json"):
    """Load simulation parameters from JSON config."""
    with open(path) as f:
        return json.load(f)

def apply_scenario(graph, scenario, *, city_name=None, tram_lookup=None):
    # derive lookup
    lookup = tram_lookup or (get_tram_lookup_for_city(city_name) if city_name else {})
    stops = scenario.get("tram_stops", [])
    length = scenario.get("length", 300)
    if len(stops) < 2:
        return []

    added = []
    for i in range(len(stops) - 1):
        s1, s2 = stops[i], stops[i+1]
        c1, c2 = lookup.get(s1), lookup.get(s2)
        if not (c1 and c2):
            continue
        lat1, lon1 = c1
        lat2, lon2 = c2
        n1 = ox.distance.nearest_nodes(graph, lon1, lat1)
        n2 = ox.distance.nearest_nodes(graph, lon2, lat2)
        graph.add_edge(n1, n2, length=length, tram=True)
        graph.add_edge(n2, n1, length=length, tram=True)
        added.extend([n1, n2])
    # unique, order-preserving
    return list(dict.fromkeys(added))


# def apply_scenario(graph, scenario):
#     stops = scenario.get("tram_stops", [])
#     length = scenario.get("length", 300)
#
#     if not stops or len(stops) < 2:
#         return None, None
#
#     for i in range(len(stops) - 1):
#         s1, s2 = stops[i], stops[i+1]
#
#         if s1 in tram_coords_lookup and s2 in tram_coords_lookup:
#             lat1, lon1 = tram_coords_lookup[s1]
#             lat2, lon2 = tram_coords_lookup[s2]
#             n1 = ox.distance.nearest_nodes(graph, lon1, lat1)
#             n2 = ox.distance.nearest_nodes(graph, lon2, lat2)
#
#             graph.add_edge(n1, n2, length=length, tram=True)
#             graph.add_edge(n2, n1, length=length, tram=True)
#
#     return None, None


def run_abm(graph, hub, num_agents, agent_distribution, tram_nodes=None):
    """
    Very lightweight ABM:
      - Samples an agent 'mode' using the provided percentage distribution.
      - Home node is random; if mode=='tram' and tram_nodes provided, choose from those.
      - Distance is the shortest-path length (by 'length') from home -> hub.
      - Returns (stats_dict, agents_list), where each agent has attributes:
          .home_node, .mode, .total_distance, .status
    """
    @dataclass
    class ABMAgent:
        home_node: int
        mode: str
        total_distance: float
        status: str  # 'active' if path found, otherwise 'inactive'

    # normalize distribution and build sampling weights
    dist = agent_distribution or {}
    drive_p = float(dist.get("drive", 0))
    cycle_p = float(dist.get("cycle", 0))
    tram_p  = float(dist.get("tram", 0))
    total_p = drive_p + cycle_p + tram_p
    if total_p <= 0:
        # fallback to equal weights if misconfigured
        drive_p = cycle_p = tram_p = 1.0
        total_p = 3.0
    weights = [drive_p / total_p, cycle_p / total_p, tram_p / total_p]
    modes = ["drive", "cycle", "tram"]

    # ensure we have a list of candidates for tram homes if provided
    tram_nodes = list(tram_nodes) if tram_nodes else None

    agents = []
    dists = []
    by_mode_count = {"drive": 0, "cycle": 0, "tram": 0}
    active_count = 0

    nodes_list = list(graph.nodes)
    if not nodes_list:
        return (
            {
                "count": 0,
                "active": 0,
                "avg_distance": 0.0,
                "max_distance": 0.0,
                "min_distance": 0.0,
                "modes": by_mode_count,
            },
            agents,
        )

    for _ in range(int(num_agents or 0)):
        mode = random.choices(modes, weights=weights, k=1)[0]
        # choose a home node
        if mode == "tram" and tram_nodes:
            home = random.choice(tram_nodes)
        else:
            home = random.choice(nodes_list)

        # compute shortest-path distance (meters if OSMnx 'length' present)
        try:
            dist = nx.shortest_path_length(graph, source=home, target=hub, weight="length")
            agents.append(ABMAgent(home_node=home, mode=mode, total_distance=float(dist), status="active"))
            dists.append(float(dist))
            by_mode_count[mode] += 1
            active_count += 1
        except (nx.NetworkXNoPath, nx.NodeNotFound, KeyError, ValueError):
            agents.append(ABMAgent(home_node=home, mode=mode, total_distance=0.0, status="inactive"))

    if dists:
        avg_d = sum(dists) / len(dists)
        max_d = max(dists)
        min_d = min(dists)
    else:
        avg_d = max_d = min_d = 0.0

    stats = {
        "count": int(num_agents or 0),
        "active": active_count,
        "avg_distance": avg_d,
        "max_distance": max_d,
        "min_distance": min_d,
        "modes": by_mode_count,
    }
    return stats, agents



def adjust_for_traffic(G, traffic_level):
    """
    Reset edge 'length' to its base value for off-peak,
    and scale to simulate congestion for peak/rush-hour.

    - Stores original length once in 'base_length' to avoid compounding.
    - Returns the same graph (mutated in-place) for convenience.
    """
    level = (traffic_level or "").strip().lower()
    is_peak = level in ("peak", "rush hour", "rush-hour", "rushhour")

    for u, v, data in G.edges(data=True):
        # remember the baseline once
        base_len = data.get("base_length", data.get("length", None))
        if base_len is None:
            # if no length present, skip gracefully
            continue
        data["base_length"] = base_len

        # apply/reset congestion factor
        if is_peak:
            data["length"] = float(base_len) * 1.5
        else:
            data["length"] = float(base_len)

    return G
