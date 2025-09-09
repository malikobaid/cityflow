CityFlow — Transport Simulation + AI Insights
============================================

CityFlow is a small, cost‑first demo that:

- Runs a lightweight transport simulation (baseline vs tramline) on prebuilt city graphs.
- Exposes a FastAPI backend for cities, submit/status, and AI “Insights”.
- Serves a static web UI (S3/CloudFront friendly) with a results view and an insights chat.

The repo is designed to deploy cheaply on AWS using S3 + CloudFront for the web, API Gateway + Lambda for the API, and on‑demand ECS Fargate tasks (triggered via SQS) for simulations.

Quick Links
----------

- Deployment plan: `project_docs/deployment_plan.md`
- Frontend entry: `web/index.html`
- API entry: `api/main.py`
- Simulation engine: `transport_sim/`

Local Quick Start
-----------------

1) Create a virtualenv and install deps

```
python3 -m venv venv-cityflow
source venv-cityflow/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

2) (Optional) Enable AI Insights

```
export OPENAI_API_KEY=sk-...
```

3) Start the API (FastAPI)

```
uvicorn api.main:app --reload
# Verify health and cities
# http://127.0.0.1:8000/v1/health
# http://127.0.0.1:8000/v1/cities
```

4) Serve the web (static)

```
python -m http.server 8080
# Open http://localhost:8080/web/index.html
```

5) Point the UI to your API

- The UI reads `web/config/site.json` for `apiBaseUrl`. For local dev it falls back to `http://127.0.0.1:8000`.
- You can also set it once in your browser console: `localStorage.API_BASE = "http://127.0.0.1:8000"`.

Project Layout
--------------

- `api/` — FastAPI app
  - `main.py` — endpoints: `/v1/cities`, `/v1/submit`, `/v1/status/{job_id}`, `/v1/insights/{job_id}`, `/v1/insights/{job_id}/chat`, `/v1/chat`
  - `models.py`, `store.py` — request/response models and in‑memory store
- `transport_sim/` — simulation engine and dataset
  - `run_sim.py`, `simulation.py`, `city_loader.py`, `data/`
- `web/` — static site
  - `index.html`, `simulate.html`, `sim_results.html`, `assets/` (css/js/img)
  - `config/site.json` — UI config consumed by `assets/js/app.js`
- `project_docs/` — docs for recruiters/infra
  - `deployment_plan.md` — AWS architecture and phased rollout
- `scripts/` — helpers (e.g., `setup_venv_cityflow.sh`)

Key Endpoints
-------------

- `GET /v1/cities` — list of demo cities (from `transport_sim/data/cities.json`)
- `POST /v1/submit` — create a job; writes config and spawns a run (local now, S3/ECS in cloud)
- `GET /v1/status/{job_id}` — job status + artifacts
- `POST /v1/insights/{job_id}` — AI summary (cached); falls back to rule‑based when no API key
- `POST /v1/insights/{job_id}/chat` — follow‑up Q&A about the job
- `POST /v1/chat` — project Q&A (RAG when enabled)

Deployment (AWS)
----------------

The target architecture (see `project_docs/deployment_plan.md`) is:

- Web: S3 bucket (private) + CloudFront (OAC) at `cityflow.obaidmalik.co.uk`.
- API: API Gateway HTTP API → Lambda (FastAPI via Mangum) at `api.cityflow.obaidmalik.co.uk`.
- Jobs: SQS → ECS Fargate task per job; artifacts to S3 and served via CloudFront `/files/*`.
- Observability: CloudWatch RUM (unique users, avg session time), CloudWatch dashboard, CloudFront logs.

Notes & Gotchas
---------------

- Virtualenv shebangs embed absolute paths. If you rename/move the repo, recreate the venv (`rm -rf venv-cityflow && python -m venv venv-cityflow`).
- Large graphs live under `transport_sim/data/graphs/*.gpickle` and are below GitHub’s 100MB/file limit; consider Git LFS if you plan to add bigger datasets.
- LlamaIndex (RAG) requires a Pydantic v2 stack. This repo is already configured for Pydantic v2 in `requirements.txt`. If you prefer Pydantic v1, remove the LlamaIndex deps and pin FastAPI accordingly.

License
-------

MIT — see `LICENSE`.

Contact
-------

- Maintainer: Obaid Malik
- Website: https://obaidmalik.co.uk
- LinkedIn: https://linkedin.com/in/malikobaid1
- Contact: malikobaid@gmail.com
- Issues: please use GitHub Issues for bugs and feature requests
