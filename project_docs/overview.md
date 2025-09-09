CityFlow — Transport Simulation Demo
===================================

CityFlow is a lightweight demo that simulates city mobility and visualizes the impact of adding a tramline segment. It’s optimized for a portfolio demo: a static web UI, small API surface, and an on‑demand worker for heavier runs.

Highlights
---------
- Configure city, traffic, and tramline endpoints from the browser.
- Fast baseline vs. scenario runs with interactive maps and stats.
- “AI Insights” summary (rule‑based; optional LLM if configured).
- Reproducible data pipeline (offline builder) for cities + stops.

Quickstart (local)
------------------
1) Open `web/index.html` in a static server (e.g., `python -m http.server`).
2) Optionally set `localStorage.API_BASE` to your API base (default mock).
3) Run a simulation; open the results page for maps, stats, and insights.

Screenshots
-----------
Add images of the simulate + results pages here for recruiters.

Docs index
----------
- Architecture: architecture.md
- API: api.md
- Data pipeline: data_pipeline.md
- Operations & cost: operations.md
- Changelog: changelog.md
