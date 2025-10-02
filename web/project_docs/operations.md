# CityFlow — Operations & Cost

## Deployment
- **Platform**: Google Cloud Run
- **Image**: pushed to Artifact Registry (region: europe‑west2)
- **Service**: one container for API + static site, port 8080
- **Domain**: optional custom domain mapping, Google‑managed TLS

## Recommended Settings
- CPU: 1 vCPU, Memory: 1 GiB
- Timeout: 300 s
- Concurrency: 1–2 (simulation can be CPU‑bound)
- Min instances: 0 (scale to zero)
- Ingress: all; Auth: allow unauthenticated (for public demo)

## CI/CD
- Cloud Build trigger on `main`, build with Dockerfile, push to Artifact Registry, then `gcloud run deploy`.
- Image tag: commit SHA (plus `latest` convenience tag).
- Retention policy: keep last N images; prune daily.

## Secrets
- `OPENAI_API_KEY` in Secret Manager; grant `secretAccessor` to runtime service account.
- Attach to service via `--set-secrets OPENAI_API_KEY=openai-api-key:latest`.

## Costs (ballpark)
- **Scale to zero**: ~$0 at idle.
- **Per sim** (a few minutes, 1 vCPU/1Gi): fractions of a cent.
- **Always warm (min=1)**: ~ $18–20/month in europe‑west2.
- **Artifact Registry**: minimal for a few images; set retention.
- **Egress**: negligible for small artifacts.

## Monitoring & Logs
- Cloud Run logs (stdout/stderr) → Cloud Logging.
- Add a simple `/v1/health` with version + uptime.
- Track job runtimes and error counts; alert on spike or 5xx rate.

## Rollback
- Keep at least one previous revision with 0% traffic.
- Roll traffic back instantly if a bad deploy ships.
