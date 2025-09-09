import osmnx as ox
import folium
import numpy as np
from pathlib import Path
import json
import re
from folium.plugins import MarkerCluster

# Canonical cities.json for backend (API + sim share this)
_CITIES_PATH = Path(__file__).resolve().parent / "data" / "cities.json"
_STOPS_DIR   = Path(__file__).resolve().parent / "data" / "stops"

def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

def _read_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def get_tram_lookup_for_city(city_name: str) -> dict:
    """
    Returns { stop_name: (lat, lon) } for the requested city.

    Priority:
      1) transport_sim/data/stops/<slug>.json  (optional per-city override)
      2) transport_sim/data/cities.json        (shared canonical list)
      3) {}                                    (fallback)
    """
    # 1) Optional per-city override file
    override = _STOPS_DIR / f"{_slugify(city_name)}.json"
    if override.exists():
        data = _read_json(override)
        stops = data["stops"] if isinstance(data, dict) and "stops" in data else data
        return { s["name"]: (float(s["lat"]), float(s["lon"])) for s in stops if "name" in s }

    # 2) Shared cities.json
    if _CITIES_PATH.exists():
        cities = _read_json(_CITIES_PATH)
        for c in cities:
            if c.get("name") == city_name or c.get("slug") == _slugify(city_name):
                stops = c.get("stops", [])
                return { s["name"]: (float(s["lat"]), float(s["lon"])) for s in stops if "name" in s }

    # 3) Nothing found
    return {}

def load_city(city_name="Bournemouth, UK"):
    # Step 1: Download and simplify graph
    G = ox.graph_from_place(city_name, network_type="walk", simplify=True)

    # Step 2: Project it to ensure lat/lon are assigned properly
    G_proj = ox.project_graph(G, to_crs="EPSG:4326")

    # Step 3: Convert to undirected *after* projection
    G_undirected = G_proj.to_undirected()

    # Step 4: Ensure all nodes have x/y (some nodes get stripped during simplification)
    for node, data in G_undirected.nodes(data=True):
        if "x" not in data or "y" not in data:
            geom = data.get("geometry", None)
            if geom:
                data["x"] = geom.x
                data["y"] = geom.y

    return G_undirected

def export_access_map(G, hub, distances, out_path, tramline_nodes=None, tramline_names=None):
    """
    Render an accessibility map centered on the hub and (optionally) a tramline polyline.
    Draws markers for nodes in `distances` and auto-fits the map bounds to plotted points.
    Note: prefers `tramline_nodes` (node IDs). Ignores `tramline_names` here.
    """
    import folium
    from folium.plugins import MarkerCluster

    def node_latlon(n):
        data = G.nodes.get(n)
        if not data:
            return None
        y = data.get("y")
        x = data.get("x")
        return (y, x) if (y is not None and x is not None) else None

    # Center map on hub (fallback to any node from distances, then graph centroid, then London-ish)
    center = node_latlon(hub)
    if center is None:
        for n in distances.keys():
            ll = node_latlon(n)
            if ll:
                center = ll
                break
    if center is None:
        ys = [d.get("y") for _, d in G.nodes(data=True) if "y" in d and "x" in d]
        xs = [d.get("x") for _, d in G.nodes(data=True) if "y" in d and "x" in d]
        center = ((sum(ys) / len(ys), sum(xs) / len(xs)) if ys and xs else (51.5, -0.12))

    m = folium.Map(location=[center[0], center[1]], zoom_start=13)
    mc = MarkerCluster().add_to(m)

    # Plot accessibility markers
    for node, dist in distances.items():
        ll = node_latlon(node)
        if not ll:
            continue
        folium.CircleMarker(
            location=[ll[0], ll[1]],
            radius=4,
            color="blue",
            fill=True,
            fill_opacity=0.6,
            popup=f"Node {node}, Dist: {dist:.0f}m",
        ).add_to(mc)

    # Draw tramline from node IDs if provided
    if tramline_nodes:
        coords = [node_latlon(n) for n in tramline_nodes]
        coords = [(lat, lon) for lat, lon in coords if lat is not None and lon is not None]
        if len(coords) >= 2:
            folium.PolyLine(coords, color="red", weight=3, opacity=0.8).add_to(m)

    # Fit bounds to all plotted points (markers + tramline)
    bounds_pts = []
    bounds_pts.extend([node_latlon(n) for n in distances.keys()])
    if tramline_nodes:
        bounds_pts.extend([node_latlon(n) for n in tramline_nodes])
    bounds_pts = [(lat, lon) for lat, lon in bounds_pts if lat is not None and lon is not None]

    if bounds_pts:
        min_lat = min(p[0] for p in bounds_pts)
        max_lat = max(p[0] for p in bounds_pts)
        min_lon = min(p[1] for p in bounds_pts)
        max_lon = max(p[1] for p in bounds_pts)
        if (max_lat - min_lat) > 1e-6 or (max_lon - min_lon) > 1e-6:
            m.fit_bounds([[min_lat, min_lon], [max_lat, max_lon]])

    m.save(out_path)


def get_hub_node(G, location_name="Bournemouth Station"):
    coords = ox.geocoder.geocode(location_name)
    node = ox.distance.nearest_nodes(G, coords[1], coords[0])
    return node

# def export_access_map(G, hub, distances, out_path, tramline_nodes=None, tramline_names=None):
#     m = folium.Map(location=[50.72, -1.88], zoom_start=13)
#     mc = MarkerCluster().add_to(m)
#
#     for node, dist in distances.items():
#         x, y = G.nodes[node]["x"], G.nodes[node]["y"]
#         folium.CircleMarker(location=[y, x], radius=4,
#                             color="blue", fill=True, fill_opacity=0.6,
#                             popup=f"Node {node}, Dist: {dist:.0f}m").add_to(mc)
#
#     # Add tramline by name
#     if tramline_names:
#         from city_loader import add_tramline_to_map
#         add_tramline_to_map(m, tramline_names[0], tramline_names[1])
#
#     m.save(out_path)
