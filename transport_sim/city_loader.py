import folium
import numpy as np
from pathlib import Path
import json
import re
from folium.plugins import MarkerCluster
from geopy.geocoders import Nominatim
from typing import Optional

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
    """
    Load city using lightweight graph format.

    This replaces the old osmnx-based loader with a lightweight
    version that reads preprocessed JSON files.
    """
    from .lightweight_graph import load_city_graph

    # Map city names to graph file names
    city_name_map = {
        "Bournemouth, UK": "bournemouth",
        "London, UK": "london_central",
        "Birmingham, UK": "birmingham_central",
        "Manchester, UK": "manchester_central",
        "City of Westminster, Greater London, UK": "london_central",
        "Westminster, Greater London, UK": "london_central"
    }

    # Try exact match first
    graph_name = city_name_map.get(city_name)

    if graph_name is None:
        # Fallback to normalized name
        normalized = city_name.lower().replace(", uk", "").replace(" ", "_").replace("city_of_", "").replace("greater_london", "central")
        graph_name = normalized

    # Try to load lightweight graph
    graph = load_city_graph(graph_name)
    if graph is None:
        # If still not found, try common variations
        variations = [
            "london_central",
            "bournemouth",
            "birmingham_central",
            "manchester_central"
        ]
        for variation in variations:
            graph = load_city_graph(variation)
            if graph is not None:
                break

        if graph is None:
            raise ValueError(f"Could not load lightweight graph for {city_name} (graph: {graph_name})")

    return graph

def export_access_map(G, hub, distances, out_path, tramline_nodes=None, tramline_names=None):
    """
    Render an accessibility map centered on the hub and (optionally) a tramline polyline.
    Draws markers for nodes in `distances` and auto-fits the map bounds to plotted points.

    Args:
        G: LightweightGraph instance
        hub: Hub node ID
        distances: Dict of node_id -> distance
        out_path: Output HTML file path
        tramline_nodes: List of node IDs for tramline (optional)
        tramline_names: Not used in lightweight version (optional)
    """
    from folium.plugins import MarkerCluster

    def node_latlon(node_id):
        """Get (lat, lon) for a node ID."""
        return G.get_node_coordinates(node_id)

    # Center map on hub (fallback to any node from distances, then graph centroid, then London-ish)
    center = node_latlon(hub)
    if center is None:
        for node_id in distances.keys():
            ll = node_latlon(node_id)
            if ll:
                center = ll
                break
    if center is None:
        # Calculate centroid from all nodes
        lats = [node['lat'] for node in G.nodes.values()]
        lons = [node['lon'] for node in G.nodes.values()]
        center = ((sum(lats) / len(lats), sum(lons) / len(lons)) if lats and lons else (51.5, -0.12))

    m = folium.Map(location=[center[0], center[1]], zoom_start=13)
    mc = MarkerCluster().add_to(m)

    # Plot accessibility markers
    for node_id, dist in distances.items():
        ll = node_latlon(node_id)
        if not ll:
            continue
        folium.CircleMarker(
            location=[ll[0], ll[1]],
            radius=4,
            color="blue",
            fill=True,
            fill_opacity=0.6,
            popup=f"Node {node_id}, Dist: {dist:.0f}m",
        ).add_to(mc)

    # Draw tramline from node IDs if provided
    if tramline_nodes:
        coords = [node_latlon(node_id) for node_id in tramline_nodes]
        coords = [(lat, lon) for lat, lon in coords if lat is not None and lon is not None]
        if len(coords) >= 2:
            folium.PolyLine(coords, color="red", weight=3, opacity=0.8).add_to(m)

    # Fit bounds to all plotted points (markers + tramline)
    bounds_pts = []
    bounds_pts.extend([node_latlon(node_id) for node_id in distances.keys()])
    if tramline_nodes:
        bounds_pts.extend([node_latlon(node_id) for node_id in tramline_nodes])
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
    """
    Find the nearest node to a named location using geocoding.

    Args:
        G: LightweightGraph instance
        location_name: Name of the location to geocode

    Returns:
        Node ID of nearest node to the geocoded location
    """
    try:
        # Use geopy for geocoding instead of osmnx
        geolocator = Nominatim(user_agent="cityflow_transport_sim")
        location = geolocator.geocode(location_name)

        if location:
            # location.longitude, location.latitude
            nearest_node = G.nearest_node(location.longitude, location.latitude)
            return nearest_node
        else:
            raise ValueError(f"Could not geocode location: {location_name}")

    except Exception as e:
        print(f"Warning: Geocoding failed for {location_name}: {e}")
        # Fallback: return a random node if geocoding fails
        if hasattr(G, 'node_ids') and G.node_ids:
            import random
            return random.choice(G.node_ids)
        raise ValueError(f"Could not find hub node for {location_name}")

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