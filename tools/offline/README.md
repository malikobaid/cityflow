Offline City Dataset Builder (dev-only)
======================================

Purpose
-------
This folder contains local-only tools to (re)generate the demo datasets used by the app:

- tools/offline/build_cities.py — builds:
  - transport_sim/data/cities.json (shared canonical list of cities + stops + facts)
  - transport_sim/data/stops/<slug>.json (optional per‑city overrides)
  - transport_sim/data/graphs/<slug>.gpickle (optional precomputed graphs)
- tools/offline/cities_seed.yml — seed configuration with cities, place polygons, hubs, and optional preferred stops.

These scripts are not used at runtime or in deployment. They exist to make the data pipeline reproducible during development and for portfolio transparency.

Requirements
------------
- Python environment with OSMnx + geospatial stack (e.g., your local venv at api/venv-cityflow/)
- Network access to Nominatim/Overpass (OSMnx) for geocoding and features

Quick start
-----------
Example command (adjust paths as needed):

  api/venv-cityflow/bin/python tools/offline/build_cities.py \
    --seed tools/offline/cities_seed.yml \
    --out-web transport_sim/data/cities.json \
    --out-graphs transport_sim/data/graphs \
    --out-stops transport_sim/data/stops \
    --num-stops 12 \
    --network walk

Notes
-----
- The app reads cities from transport_sim/data/cities.json via the API endpoint /v1/cities.
- For runtime stability, ensure each city name in the output is an OSM‑geocodable polygon string (we prefer the seed's `place` for `name`).
- If you only need to update a single city (to avoid touching others), build it into a temp folder and then surgically merge that city into the existing cities.json and stops.

Deployment
----------
Do not deploy this folder or its dependencies. The production/API path does not require OSMnx.
