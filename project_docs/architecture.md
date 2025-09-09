Architecture (Cloud‑Friendly)
=============================

Goals: near‑zero idle cost, simple to deploy, credible demo.

Components
----------
- Web UI: S3 + CloudFront hosting the `web/` folder (static site).
- API (light): API Gateway HTTP API + Lambda for `/v1/cities`, `/v1/status`, `/v1/insights/*`.
- Worker (heavy): SQS → ECS Fargate task per job for simulation runs. Reads config from S3, writes artifacts to S3, no idle cost.
- Artifacts: S3 bucket (results/jobs), CloudFront distribution or pre‑signed URLs.

Flow
----
1) UI posts to `/v1/submit` → API writes job config to S3 and enqueues SQS.
2) SQS triggers ECS task → container runs sim → writes HTML/JSON stats to S3.
3) UI polls `/v1/status/{job_id}` → returns artifacts + messages.
4) Optional: `/v1/insights/*` reads stats and returns markdown summaries.

Cost Controls
-------------
- S3 lifecycle to expire old jobs; CloudWatch logs 7–14 days.
- Small default agent counts; prebuilt city datasets to avoid runtime OSM calls.
- Use HTTP API (not REST) for API Gateway.

