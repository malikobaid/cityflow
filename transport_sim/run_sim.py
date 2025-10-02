
#!/usr/bin/env python3
import sys
import os
import json
import argparse
from pathlib import Path

# Ensure transport_sim package imports work when called from elsewhere
BASE_DIR = Path(__file__).resolve().parent                  # .../transport_sim
ROOT_DIR = BASE_DIR.parent                                   # project root
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

# Import simulation + city helpers
from city_loader import get_tram_lookup_for_city
from transport_sim.city_loader import load_city, get_hub_node, export_access_map
from transport_sim.simulation import load_config, apply_scenario, run_abm, adjust_for_traffic
from transport_sim.lightweight_graph import LightweightGraph

# -----------------------
# Utilities
# -----------------------

def parse_args():
    p = argparse.ArgumentParser(description="Run transport simulation (baseline + tramline).")
    p.add_argument("--config", help="Path to config.json")
    p.add_argument("--outdir", help="Directory to write outputs (maps + stats)")
    p.add_argument("positional_config", nargs="?", help="Optional positional config path (back-compat)")
    return p.parse_args()

def read_cities_json():
    path = BASE_DIR / "data" / "cities.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def tram_lookup_from_cities(city_name: str) -> dict:
    cities = read_cities_json()
    for c in cities:
        if c.get("name") == city_name or c.get("slug") == slugify(city_name):
            stops = c.get("stops", [])
            try:
                return { s["name"]: (float(s["lat"]), float(s["lon"])) for s in stops if "name" in s }
            except Exception:
                # tolerate bad rows
                out = {}
                for s in stops:
                    try:
                        out[s["name"]] = (float(s["lat"]), float(s["lon"]))
                    except Exception:
                        pass
                return out
    return {}

def slugify(name: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")

def ensure_outdir(path: Path):
    path.mkdir(parents=True, exist_ok=True)

def group_stats_by_mode(agents):
    from collections import defaultdict
    mode_stats = defaultdict(list)
    for a in agents:
        if getattr(a, "status", None) == "active":
            mode_stats[a.mode].append(a.total_distance)
    result = {}
    for mode, dists in mode_stats.items():
        if dists:
            result[mode] = {
                "avg": sum(dists) / len(dists),
                "max": max(dists),
                "count": len(dists),
            }
    return result

# -----------------------
# Main
# -----------------------

def main():
    args = parse_args()

    # Resolve config path (priority: --config, positional, default)
    if args.config:
        config_path = Path(args.config)
    elif args.positional_config:
        config_path = Path(args.positional_config)
    else:
        config_path = BASE_DIR / "config.json"

    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    # Resolve output directory (priority: --outdir, default to ./results under script dir)
    if args.outdir:
        outdir = Path(args.outdir)
    else:
        outdir = BASE_DIR / "results"
    ensure_outdir(outdir)

    # Load config and normalize keys
    print(f"Using config: {config_path}")
    print(f"Writing outputs to: {outdir}")

    config_raw = load_config(str(config_path))
    # Normalize traffic key
    traffic_level = config_raw.get("traffic", config_raw.get("traffic_level", "off-peak"))

    # Build a derived config that always has scenario + hub if possible
    city_name = config_raw.get("city")
    tram_start = config_raw.get("tram_start")
    tram_end = config_raw.get("tram_end")
    num_agents = int(config_raw.get("num_agents", 300))
    agent_distribution = config_raw.get("agent_distribution", {"drive":60, "cycle":10, "tram":30})

    print(f"City: {city_name}")
    print(f"Traffic level: {traffic_level}")
    print(f"Num agents: {num_agents}")
    print(f"Agent distribution: {agent_distribution}")
    print(f"Tramline: {tram_start} - {tram_end}")

    # Scenario: if not provided, derive from start/end
    if "scenarios" in config_raw and "tramline_extension" in config_raw["scenarios"]:
        scenario = config_raw["scenarios"]["tramline_extension"]
        tram_stops = scenario.get("tram_stops", [tram_start, tram_end])
        length = scenario.get("length", 300)
    else:
        tram_stops = [tram_start, tram_end] if (tram_start and tram_end) else []
        length = 300
        scenario = {"tram_stops": tram_stops, "length": length}

    print(f"Scenario tram stops: {tram_stops}")
    print(f"Scenario length: {length}m")    
    # Tram coords lookup: prefer helper in city_loader if present; fallback to cities.json
    try:
        tram_coords_lookup = get_tram_lookup_for_city(city_name)
    except Exception:
        tram_coords_lookup = tram_lookup_from_cities(city_name)

    print(f"Tram stops with coords: { {n: tram_coords_lookup.get(n) for n in tram_stops} }")
    # Load graph and adjust for traffic
    G_base = load_city(city_name)

    print(f"Loaded city graph with {len(G_base.nodes) if hasattr(G_base, 'nodes') else len(G_base.node_ids)} nodes")
    print(f" - Approx {G_base.num_edges()} edges")
    # Get traffic-adjusted matrix for LightweightGraph
    adj_matrix = None
    if isinstance(G_base, LightweightGraph):
        adj_matrix = G_base.get_traffic_adjusted_matrix(traffic_level)

    G_base = adjust_for_traffic(G_base, traffic_level)
    print(f"Adjusted graph for traffic level '{traffic_level}'")
    # Pick hub: prefer config, else cities.json's hub, else tram_start
    hub_name = config_raw.get("hub")
    if not hub_name:
        cities = read_cities_json()
        for c in cities:
            if c.get("name") == city_name or c.get("slug") == slugify(city_name):
                hub_name = c.get("hub") or hub_name
                break
    if not hub_name:
        hub_name = tram_start or tram_end

    print(f"Using hub: {hub_name}")

    hub = get_hub_node(G_base, hub_name)

    print(f"Hub node ID: {hub}")
    # Check if hub exists in graph (works for both LightweightGraph and NetworkX)
    if hasattr(G_base, 'nodes') and hub not in G_base.nodes:
        raise ValueError("Hub node not in undirected graph.")
    elif hasattr(G_base, 'node_ids') and hub not in G_base.node_ids:
        raise ValueError("Hub node not in lightweight graph.")

    print("Running baseline…")
    baseline_stats, baseline_agents = run_abm(
        G_base, hub, num_agents, agent_distribution, adj_matrix=adj_matrix
    )

    # Tramline scenario
    if hasattr(G_base, 'copy'):
        G_scenario = G_base.copy()  # NetworkX graph
    else:
        G_scenario = G_base  # LightweightGraph (immutable)

    # Try new-style apply_scenario(city-aware); fallback to legacy signature
    tram_nodes = None
    try:
        tram_nodes = apply_scenario(G_scenario, scenario, city_name=city_name)
    except TypeError:
        # Legacy: relies on a global lookup in module; call once
        try:
            tram_nodes = apply_scenario(G_scenario, scenario)
        except Exception:
            tram_nodes = None

    # If still no tram_nodes, map the first two named stops via our lookup
    if (not tram_nodes) and len(tram_stops) >= 2:
        names = tram_stops[:2]
        coords = [tram_coords_lookup.get(n) for n in names]
        if all(coords):
            try:
                # Use lightweight graph's nearest_node method
                n1 = G_scenario.nearest_node(coords[0][1], coords[0][0])
                n2 = G_scenario.nearest_node(coords[1][1], coords[1][0])
                # Note: LightweightGraph doesn't support adding edges
                # For now, just return the nodes that would be connected
                tram_nodes = [n1, n2] if n1 is not None and n2 is not None else None
            except Exception:
                tram_nodes = None

    # Debug prints if we have at least two nodes
    if tram_nodes and len(tram_nodes) >= 2:
        n1_id, n2_id = tram_nodes[0], tram_nodes[1]
        print(f"Tramline edge planned/added: {n1_id} - {n2_id}")
        try:
            # Use lightweight graph's has_path method
            if isinstance(G_scenario, LightweightGraph):
                path_exists = G_scenario.has_path(n1_id, hub)
            else:
                import networkx as nx
                path_exists = nx.has_path(G_scenario, n1_id, hub)
            print(f"Path exists to hub: {path_exists}")
        except Exception:
            pass

    print("Running tramline extension…")
    tramline_stats, tramline_agents = run_abm(
        G_scenario, hub, num_agents, agent_distribution, tram_nodes=tram_nodes, adj_matrix=adj_matrix
    )

    # Per-mode summaries
    baseline_stats["by_mode"] = group_stats_by_mode(baseline_agents)
    tramline_stats["by_mode"] = group_stats_by_mode(tramline_agents)

    # Distances for maps
    baseline_distances = {
        a.home_node: a.total_distance for a in baseline_agents if getattr(a, "status", None) == "active"
    }
    tramline_distances = {
        a.home_node: a.total_distance for a in tramline_agents if getattr(a, "status", None) == "active"
    }

    # Compute tramline nodes for colored map if names provided
    tramline_nodes = None
    if len(tram_stops) >= 2:
        latlon1 = tram_coords_lookup.get(tram_stops[0])
        latlon2 = tram_coords_lookup.get(tram_stops[1])
        if latlon1 and latlon2:
            try:
                # Use lightweight graph's nearest_node method
                n1 = G_scenario.nearest_node(latlon1[1], latlon1[0])
                n2 = G_scenario.nearest_node(latlon2[1], latlon2[0])
                tramline_nodes = [n1, n2] if n1 is not None and n2 is not None else None
            except Exception:
                tramline_nodes = None

    # Export maps into outdir
    baseline_map = outdir / "baseline_access.html"
    export_access_map(G_base, hub, baseline_distances, out_path=str(baseline_map))
    print(f"Saved baseline map to {baseline_map}")

    tramline_map = outdir / "tramline_access_colored.html"
    export_access_map(
        G_scenario,
        hub,
        tramline_distances,
        out_path=str(tramline_map),
        tramline_nodes=tramline_nodes,
        tramline_names=tram_stops,
    )
    print(f"Saved tramline map to {tramline_map}")

    # Write stats (unsuffixed + suffixed for compatibility)
    suffix = str(traffic_level).replace("-", "").lower()  # "offpeak" or "peak"
    baseline_unsuff = outdir / "baseline_stats.json"
    tramline_unsuff = outdir / "tramline_stats.json"
    baseline_suff = outdir / f"baseline_stats_{suffix}.json"
    tramline_suff = outdir / f"tramline_stats_{suffix}.json"

    with open(baseline_unsuff, "w") as f:
        json.dump(baseline_stats, f)
    with open(tramline_unsuff, "w") as f:
        json.dump(tramline_stats, f)
    with open(baseline_suff, "w") as f:
        json.dump(baseline_stats, f)
    with open(tramline_suff, "w") as f:
        json.dump(tramline_stats, f)

    print("Wrote stats:")
    print(f"   - {baseline_unsuff.name}, {tramline_unsuff.name}")
    print(f"   - {baseline_suff.name}, {tramline_suff.name}")

if __name__ == "__main__":
    main()