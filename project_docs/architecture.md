# CityFlow — Architecture

## Components
- **FastAPI app (`api/main.py`)**  
  Registers middleware, includes routers under `/v1`, mounts `/files` and the `/` static site from `web/`.
- **Routers (`api/routes/`)**
  - `health.py`: liveness & basic metadata
  - `cities.py`: available demo cities & stops
  - `submit.py`: enqueue/start a simulation job
  - `status.py`: poll job status & list artifacts
  - `insights.py`: summarize simulation output, optionally LLM‑assisted
  - `chat.py`: free‑form Q&A about results/artifacts
- **Globals (`api/globals.py`)**
  Declares `ROOT_DIR`, `DATA_ROOT`, `WEB_DIR`, request‑id middleware, and `_warm_start` hook.
- **Simulation engine (`transport_sim/`)**
  Minimal, pluggable compute that produces predictable outputs (CSV/JSON/PNG, etc.).
- **Frontend (`web/`)**
  Multi‑page site (`index.html`, `simulate.html`, `sim_results.html`, docs under `web/docs/`, shared assets in `web/assets/`).

## Request Flow
```text
[Browser] --(POST /v1/submit JSON)--> [FastAPI] --(run simulation)--> [Artifacts in DATA_ROOT]
[Browser] --(GET  /v1/status/{{job}})--> [FastAPI] --(reads job state)--> JSON {status, files}
[Browser] --(GET      /files/...)--> [Static mount]
```

## Mount & Routing Order (Important)
- Include **API routers first** with `prefix="/v1"`.
- Mount `/files` to `DATA_ROOT`.
- Mount `/` to `WEB_DIR` **last**. For MPA, `html=True` serves `index.html` at `/`.

## Lifespan vs on_event
Use a `lifespan` context instead of deprecated `@app.on_event("startup")` for warm‑start logic.

## Secrets & Config
- `OPENAI_API_KEY` via Secret Manager → env var.
- Optional `web/config/site.json` to point to a different API domain. Defaults are same‑origin `/v1`.
