# CityFlow — Data Pipeline

## Inputs
- **Cities metadata**: static JSON/CSV in repo (sample networks and stops).
- **Simulation parameters**: user inputs from `simulate.html` (trips, modes, seed, time, etc.).

## Processing
1. Validate inputs.
2. Spin up a lightweight simulation run (single process).
3. Generate outputs:
   - `summary.json`: top‑level figures (counts, runtimes, mode shares).
   - `routes.csv`: per‑agent or aggregated flows.
   - `chart.png` or `*.html`: quick visuals for the UI.
4. Persist under `DATA_ROOT/jobs/{{job_id}}/`.

## Outputs
- Served via `/files/jobs/{{job_id}}/...` static mount.
- Listed by `/v1/status/{{job_id}}` with both artifact names and `href`s.

## Observability (optional)
- Basic logging (request id middleware) with per‑job timing.
- Add Cloud Logging labels (job_id) for easier filtering.
- If using LLM features, redact PII from prompts before logging.
