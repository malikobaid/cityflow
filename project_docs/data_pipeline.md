Data Pipeline (Offline)
=======================

Purpose: build reproducible city datasets offline so runtime stays fast and cheap.

Inputs
------
- `tools/offline/cities_seed.yml` — cities with OSM place strings, hubs, optional preferred stops.

Outputs
-------
- `transport_sim/data/cities.json` — canonical list consumed by UI/API.
- `transport_sim/data/stops/<slug>.json` — optional overrides for stop coords.
- `transport_sim/data/graphs/<slug>.gpickle` — optional precomputed graphs.

Usage
-----
```
api/venv-cityflow/bin/python tools/offline/build_cities.py \
  --seed tools/offline/cities_seed.yml \
  --out-web transport_sim/data/cities.json \
  --out-graphs transport_sim/data/graphs \
  --out-stops transport_sim/data/stops \
  --num-stops 12 --network walk
```

Tips
----
- Ensure city `name` fields are OSM‑geocodable (we prefer the seed `place`).
- Build single cities to a temp folder and merge to avoid touching others.
