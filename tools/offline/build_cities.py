#!/usr/bin/env python3
"""
build_cities.py — Offline builder for demo cities

Purpose
-------
One-time script to generate:
  1) Precomputed graphs per city: transport_sim/data/graphs/{slug}.gpickle
  2) UI dataset: web/assets/data/cities.json
  3) (Optional) Simulator stops lookup per city: transport_sim/data/stops/{slug}.json

It reads a seed file (YAML or JSON) listing cities and (optionally) preferred stop names.
All OSM/OSMnx work happens offline on your dev machine; runtime demo remains fully local.

Quick start
-----------
python build_cities.py \
  --seed cities_seed.yml \
  --out-web web/assets/data/cities.json \
  --out-graphs transport_sim/data/graphs \
  --out-stops transport_sim/data/stops \
  --num-stops 12 \
  --network drive

Seed file (YAML) example
------------------------
cities:
  - name: Bournemouth
    slug: bournemouth
    place: "Bournemouth, Dorset, UK"
    enable: true
    # Optional preferred stops to pin exact names (script will geocode or match OSM POIs)
    stops:
      - "Bournemouth Pier"
      - "Lansdowne"
      - "Bournemouth Station"
    population: 197700            # optional facts override
    area_km2: 46.2                # optional facts override
    buffer_km: 0                  # optional extra buffer around place boundary

  - name: London (Central)
    slug: london_central
    place: "City of London, UK"
    enable: true
    buffer_km: 5
    # stops: []                  # if omitted, auto-pick central stations

Notes
-----
• Requires: osmnx>=1.3, networkx, shapely, pyproj, geopandas, pandas, pyyaml (if using YAML seed)
• OSM data © OpenStreetMap contributors (ODbL). Include attribution in your README.
"""

import argparse, json, sys, os, pickle
from pathlib import Path

# Optional YAML support
try:
    import yaml
except Exception:
    yaml = None

import math
import pandas as pd
import networkx as nx
import osmnx as ox
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry


def write_graph_pickle(G, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        pickle.dump(G, fh, protocol=pickle.HIGHEST_PROTOCOL)

def read_graph_pickle(path):
    with open(path, "rb") as fh:
        return pickle.load(fh)

def load_seed(path: Path):
    text = Path(path).read_text(encoding="utf-8")
    if path.suffix.lower() in (".yml", ".yaml"):
        if yaml is None:
            raise RuntimeError("pyyaml is required to read YAML seeds. pip install pyyaml")
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict) or "cities" not in data:
        raise ValueError("Seed must be an object with a top-level 'cities' list")
    return data["cities"]

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def buffer_geom_m(polygon_gdf, buffer_km: float):
    if not buffer_km or buffer_km <= 0:
        return polygon_gdf
    gdf_proj = ox.projection.project_gdf(polygon_gdf)
    gdf_proj["geometry"] = gdf_proj.geometry.buffer(buffer_km * 1000.0)
    return gdf_proj.to_crs(polygon_gdf.crs)

def polygon_from_seed(city):
    # priority: 'polygon' (GeoJSON/path), else 'place' geocode
    if "polygon" in city and city["polygon"]:
        poly = city["polygon"]
        if isinstance(poly, str) and Path(poly).exists():
            gj = json.loads(Path(poly).read_text(encoding="utf-8"))
            geom = shape(gj["features"][0]["geometry"]) if "features" in gj else shape(gj["geometry"])
            gdf = ox.geocoder.geocode_to_gdf(geom.wkt)  # wrap into gdf with CRS
        elif isinstance(poly, (dict, list)):
            geom = shape(poly) if isinstance(poly, dict) else shape({"type": "Polygon", "coordinates": poly})
            gdf = ox.geocoder.geocode_to_gdf(geom.wkt)
        else:
            raise ValueError("Unsupported 'polygon' in seed for city: {}".format(city.get("name")))
    else:
        place = city.get("place")
        if not place:
            raise ValueError(f"City '{city.get('name')}' needs 'place' or 'polygon' in seed")
        gdf = ox.geocoder.geocode_to_gdf(place)
    buf_km = float(city.get("buffer_km", 0) or 0)
    gdf = buffer_geom_m(gdf, buf_km)
    return gdf

def graph_for_city(polygon_gdf, network: str):
    # Typical choices: 'drive', 'walk', 'bike'
    ox.settings.log_console = True
    G = ox.graph_from_polygon(polygon_gdf.geometry.iloc[0], network_type=network, simplify=True)
    return G

def geocode_name_in_poly(name: str, polygon_gdf):
    # Try to find a POI matching the name inside polygon (stations/tram/metro)
    tags_list = [
        {"railway": ["station", "halt", "stop", "tram_stop"]},
        {"public_transport": ["station", "stop_position", "stop_area"]},
        {"subway": True},
    ]
    geom = polygon_gdf.geometry.iloc[0]
    for tags in tags_list:
        try:
            gdf = ox.features.features_from_polygon(geom, tags)
            if gdf is not None and len(gdf):
                # fuzzy match by case-insensitive containment
                gdf["name_lower"] = gdf.get("name", "").astype(str).str.lower()
                target = name.strip().lower()
                hits = gdf[gdf["name_lower"].str.contains(target, na=False)]
                if len(hits):
                    row = hits.iloc[0]
                    pt = row.geometry.representative_point()
                    return float(pt.y), float(pt.x)
        except Exception:
            continue
    # fallback to geocode with Nominatim but constrained by 'name, city'
    try:
        q = f"{name}, {polygon_gdf.iloc[0].display_name}"
        loc = ox.geocoder.geocode(q)
        if isinstance(loc, (list, tuple)) and len(loc) == 2:
            return float(loc[0]), float(loc[1])
    except Exception:
        pass
    return None, None

def auto_pick_stops(polygon_gdf, n: int):
    # Pull candidate stations and pick n closest to centroid (diverse)
    tags = {
        "railway": ["station", "halt", "tram_stop"],
        "public_transport": ["station", "stop_position"],
    }
    geom = polygon_gdf.geometry.iloc[0]
    gdf = ox.features.features_from_polygon(geom, tags)
    if gdf is None or not len(gdf):
        return []
    # Keep rows with a name
    gdf = gdf[~gdf.get("name").isna()].copy()
    if not len(gdf):
        return []
    # Distance to centroid
    centroid = geom.centroid
    gdf["dist_c"] = gdf.geometry.centroid.distance(centroid)
    gdf = gdf.sort_values("dist_c").drop_duplicates(subset=["name"]).head(int(n * 2))
    # Build list
    out = []
    for _, r in gdf.iterrows():
        pt = r.geometry.representative_point()
        out.append({"name": str(r["name"]), "lat": float(pt.y), "lon": float(pt.x)})
        if len(out) >= n:
            break
    return out

def clean_name(s: str) -> str:
    return " ".join(str(s).strip().split())

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", required=True, help="Path to seed YAML/JSON")
    ap.add_argument("--out-web", required=True, help="Path to write web/assets/data/cities.json")
    ap.add_argument("--out-graphs", required=True, help="Dir for transport_sim/data/graphs")
    ap.add_argument("--out-stops", required=False, help="Dir for transport_sim/data/stops (optional)")
    ap.add_argument("--num-stops", type=int, default=12, help="Number of stops to auto-pick if not provided")
    ap.add_argument("--network", choices=["drive", "walk", "bike"], default="drive")
    args = ap.parse_args()

    seed_cities = load_seed(Path(args.seed))

    out_graphs = Path(args.out_graphs)
    ensure_dir(out_graphs)

    out_stops = Path(args.out_stops) if args.out_stops else None
    if out_stops:
        ensure_dir(out_stops)

    out_web = Path(args.out_web)
    ensure_dir(out_web.parent)

    cities_out = []

    for city in seed_cities:
        # Seed values
        display_name = city.get("name")
        place_name = city.get("place")
        # Output name MUST be geocodable to a polygon for OSMnx runtime
        name = place_name or display_name
        slug = city["slug"]
        enable = bool(city.get("enable", False))
        print(f"\n=== {name} ({slug}) ===")

        # Boundary & graph
        poly_gdf = polygon_from_seed(city)
        G = graph_for_city(poly_gdf, args.network)
        graph_path = out_graphs / f"{slug}.gpickle"

        write_graph_pickle(G, graph_path)
        print(f"  • Graph saved: {graph_path} (nodes={len(G)}, edges={G.size() if hasattr(G,'size') else 'n/a'})")

        # Facts
        area_km2 = float(city.get("area_km2", 0) or 0)
        if not area_km2:
            # compute area from polygon
            gdf_proj = ox.projection.project_gdf(poly_gdf)
            area_km2 = float(gdf_proj.geometry.area.iloc[0] / 1_000_000.0)
        population = city.get("population")
        density_km2 = None
        if population and area_km2:
            try:
                density_km2 = float(population) / float(area_km2)
            except Exception:
                density_km2 = None

        # Stops
        stops = []
        preferred = city.get("stops", []) or []
        if preferred:
            for raw in preferred:
                nm = clean_name(raw)
                lat, lon = geocode_name_in_poly(nm, poly_gdf)
                if lat and lon:
                    stops.append({"name": nm, "lat": lat, "lon": lon})
                else:
                    print(f"    ! WARN: could not geocode '{nm}' within polygon; skipping")
        # auto-pick if not enough
        if len(stops) < args.num_stops:
            needed = args.num_stops - len(stops)
            auto = auto_pick_stops(poly_gdf, needed)
            # avoid dup names
            have = {s["name"].lower() for s in stops}
            for a in auto:
                if a["name"].lower() not in have:
                    stops.append(a)
                    have.add(a["name"].lower())

        # optional per-city stops json for simulator
        if out_stops:
            stops_path = out_stops / f"{slug}.json"
            with open(stops_path, "w", encoding="utf-8") as f:
                # Expected shapes by transport_sim.city_loader.get_tram_lookup_for_city:
                #   either {"stops":[{"name","lat","lon"}, ...]} or a plain list of the same objects
                json.dump({"stops": stops}, f, indent=2)
            print(f"  • Stops saved: {stops_path} (n={len(stops)})")

        # Aggregate for cities.json
        city_out = {
            "name": name,
            "slug": slug,
            "enabled": enable,
            "facts": {
                "population": population,
                "area_km2": area_km2,
                "density_km2": density_km2,
                "source": "OSMnx geocoded (offline build)"
            },
            "stops": stops
        }
        # Preserve a friendly label if different from the geocodable name
        if display_name and place_name and display_name != place_name:
            city_out["display"] = display_name
        # Optional hub passthrough from seed
        if city.get("hub"):
            city_out["hub"] = city["hub"]

        cities_out.append(city_out)

    # Write cities.json
    with open(out_web, "w", encoding="utf-8") as f:
        json.dump(cities_out, f, indent=2)
    print(f"\n✅ Wrote {out_web} with {len(cities_out)} cities.")

if __name__ == "__main__":
    main()
