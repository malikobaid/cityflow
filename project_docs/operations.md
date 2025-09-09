Operations & Cost
=================

Defaults for a portfolio demo:
- Small agent counts by default.
- Precomputed datasets (no OSM at runtime).
- S3 lifecycle: expire `jobs/*` after 7–14 days.
- CloudWatch logs retention: 7–14 days.

Runbooks
--------
- Job fails with geocoder error → verify city `name` is a polygon place; try a safer variant (e.g., “Bournemouth, UK”).
- Missing artifacts → check worker task logs; ensure S3 permissions.
- UI not loading assets → verify CloudFront behavior and web/ as site root.

