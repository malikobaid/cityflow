# CityFlow – AWS Deployment Plan (Cost‑First, No Code Changes Yet)

This document outlines how to deploy CityFlow to AWS in a cost‑effective, maintainable way, using static hosting for the UI, serverless for the API, and on‑demand containers for simulation jobs. This plan is approved to land the scaffolding and CI/CD next; code changes for S3 job storage will be handled in later steps.

## Goals

- Rename repo to `cityflow` and push this local repo to GitHub with CI/CD tied to AWS via OIDC.
- Host the static web at `https://cityflow.obaidmalik.co.uk` via S3 + CloudFront.
- Expose the API at `https://api.cityflow.obaidmalik.co.uk` with near‑zero idle cost.
- Run simulations on demand using ECS Fargate tasks triggered from the API (via SQS).
- Remove/decommission `skyraldemo.obaidmalik.co.uk` (optionally redirect to CityFlow).
- Add a CloudWatch dashboard (and RUM) for unique visitors/day, average session time, and platform health.

## Current State (Given)

- GitHub repo: `malikobaid/skyral_sim` (CI/CD exists for AWS)
- AWS: ECS instance (t3.medium) running a Streamlit app
- DNS/ACM: `skyraldemo.obaidmalik.co.uk` with certificate; wildcard `*.obaidmalik.co.uk`

## Target Architecture (High Level)

- Frontend (static): S3 bucket (private), CloudFront distribution with OAC, custom domain `cityflow.obaidmalik.co.uk`.
- API (serverless): API Gateway HTTP API → Lambda running FastAPI (via Mangum). Custom domain `api.cityflow.obaidmalik.co.uk`.
- Jobs (compute): SQS queue → ECS Fargate task per job (no always‑on service). Task reads job config from S3, writes artifacts to S3.
- Artifacts: S3 prefix `jobs/<job_id>/…`, served to the web via CloudFront behavior `/files/*` that points to the artifacts bucket.
- Observability: CloudWatch Logs (API/Lambda, ECS), CloudFront metrics, CloudWatch RUM for frontend analytics.

Cost profile: no idle compute (API on Lambda; jobs on demand). S3+CloudFront costs are minimal.

## Phased Rollout Plan

### Phase 0 – Repository and CI/CD

1) Rename GitHub repo `skyral_sim` → `cityflow`. Add this local repo as `origin`, push main.
2) GitHub OIDC → AWS IAM role with least‑privilege for:
   - S3 sync to web bucket; CloudFront invalidation
   - Deploying stacks (Terraform or CDK); Lambda updates
   - ECR push; ECS task definition updates
   - SSM Parameter Store read
3) Workflows (split):
   - `web-deploy`: build/sync `web/` to S3; invalidate CloudFront
   - `api-deploy`: package FastAPI for Lambda (zip), deploy; smoke test `/v1/health`
   - `worker-deploy`: build+push ECR image for ECS worker; update TaskDefinition revision

### Phase 1 – Static Web (S3 + CloudFront)

1) Create S3 bucket `cityflow-web` (private, block public access). Upload `web/`.
2) CloudFront distribution:
   - Default origin: `cityflow-web` via OAC
   - Behaviors:
     - Default: cache assets long (`/assets/**`), Gzip/Brotli
     - `config/site.json` and HTML: shorter TTL (e.g., 60–300s)
   - Custom domain: `cityflow.obaidmalik.co.uk` with ACM cert (us‑east‑1)
3) Route 53: A/AAAA Alias records to CloudFront.

### Phase 2 – API (API Gateway + Lambda)

1) Package FastAPI app with Mangum (ASGI to Lambda). No code changes to behavior.
2) API Gateway HTTP API:
   - Lambda integration; stage `prod`
   - CORS allow `https://cityflow.obaidmalik.co.uk`
   - Custom domain `api.cityflow.obaidmalik.co.uk` (regional ACM in API region)
3) Lambda config:
   - Env: `OPENAI_API_KEY` from SSM Parameter Store
   - Memory/timeout tuned for insights work (e.g., 512MB/10s)
   - Logs to CloudWatch with basic alarms on 5xx

### Phase 3 – Sim Jobs (SQS + ECS Fargate)

1) SQS queue `cityflow-jobs`, with DLQ.
2) ECR repo `cityflow-worker`; build/push image.
3) ECS Fargate TaskDefinition `cityflow-worker`:
   - CPU/memory e.g., 1 vCPU / 2GB (adjust per runtime)
   - Env from SSM (API base, bucket names)
   - Task role: S3 read/write on artifacts prefix; SQS receive/delete; SSM read
4) Job flow (initially via API submit):
   - API writes the merged job config to S3 and enqueues SQS with job_id + S3 key
   - Fargate task reads config, runs sim, writes artifacts to `s3://…/jobs/<job_id>/…`
   - Status endpoint reads S3 to report progress/artifacts

Note: status/artifacts currently read local filesystem; a small code change will later switch to S3. We’ll land infra first.

### Phase 4 – DNS & Migration

1) Update `config/site.json` in the web bucket: `apiBaseUrl = https://api.cityflow.obaidmalik.co.uk`.
2) Point `cityflow.obaidmalik.co.uk` (CloudFront) and `api.cityflow.obaidmalik.co.uk` (API Gateway custom domain).
3) Remove/decommission `skyraldemo.obaidmalik.co.uk` or add a 301 redirect to CityFlow (CloudFront function).
4) Decommission the t3.medium instance after validation.

### Phase 5 – Observability & Analytics

1) CloudWatch RUM for `cityflow.obaidmalik.co.uk`:
   - Create RUM monitor; add snippet to the site to capture sessions, unique users, avg session duration, errors
2) CloudFront logging (standard logs) → S3; set up Athena for ad‑hoc analysis (top pages, geo, referrers)
3) CloudWatch Dashboard (single pane for CityFlow):
   - RUM: UniqueVisitors/Day, Sessions, AvgSessionDuration, JS errors
   - CloudFront: Requests, 4xx/5xx, Bytes, CacheHitRatio
   - API (Lambda): Invocations, Duration p90/p99, Errors
   - Jobs (ECS): Tasks started/day, Avg runtime, Task failures
4) Alarms: spikes in 5xx (API/CloudFront), ECS task failures, Lambda errors

### Phase 6 – CI/CD Wire‑up

- `web-deploy` on main push: sync to S3; CloudFront invalidation for `index.html`, `config/site.json` (and any non‑hashed assets)
- `api-deploy` on tags or main: build zip, update Lambda; run canary against `/v1/health`
- `worker-deploy` on tags: build/push ECR image; register TaskDefinition revision
- GitHub OIDC role limited to the stacks and buckets for CityFlow only

## AWS Resources (Summary)

- S3: web bucket; artifacts bucket (or single bucket with prefixes)
- CloudFront: distribution with OAC, default origin (web) + behavior `/files/*` (artifacts)
- ACM: us‑east‑1 cert for `cityflow.obaidmalik.co.uk`; regional cert for `api.cityflow.obaidmalik.co.uk`
- Route 53: A/AAAA alias for both domains
- API: API Gateway HTTP API, Lambda function, logs/alarms
- Jobs: SQS, DLQ, ECR repo, ECS Cluster (Fargate), TaskDefinition, IAM roles
- Observability: CloudWatch Logs, CloudWatch RUM, CloudFront logs (to S3), Athena, Dashboard

## Secrets & Config

- SSM Parameter Store (Region: same as API/ECS): `OPENAI_API_KEY`, optional knobs
- Site config in S3: `web/config/site.json` with `apiBaseUrl` set to the API domain

## Cost Notes

- S3 + CloudFront: low monthly cost; pay per GB and requests
- API on Lambda + API GW: ~$0 idle; pay per request and duration
- Jobs on ECS Fargate: pay per task runtime only; optional Fargate Spot for further savings
- Avoid NAT by running Fargate with public IP, or add S3 VPC endpoint if private subnets are preferred

## Acceptance & Smoke Tests

1) Web: `https://cityflow.obaidmalik.co.uk/web/index.html` renders; nav links work under CF
2) API: `GET /v1/health` 200; `GET /v1/cities` returns list
3) Submit/Status (initially local artifacts): round‑trip works; later S3‑backed status
4) Results page: loads artifacts from `/files/jobs/<job_id>/…`; insights endpoint responds
5) RUM data present; Dashboard shows visitors/day and avg session time

## Next Steps (Step‑by‑Step)

1) Confirm Terraform vs CDK preference and AWS regions (CF must use us‑east‑1 for cert)
2) Create GitHub OIDC role + minimal IAM policies
3) Stand up S3 + CloudFront + Route 53 + ACM; wire `cityflow.obaidmalik.co.uk`
4) Package/deploy API (Lambda + API GW) at `api.cityflow.obaidmalik.co.uk`
5) Create ECR/SQS/ECS resources (no code changes yet); validate a dry‑run task
6) Enable CloudWatch RUM and create the CityFlow dashboard
7) Migrate status/artifacts in the API to S3 (small code change); update UI if needed (or return absolute URLs)
8) Decommission old ECS instance/`skyraldemo` and set redirect (optional)

---

Prepared for incremental execution. After confirmation, we will implement Phase 0 (OIDC + IaC scaffold) and Phase 1 (static web) first, then proceed.

