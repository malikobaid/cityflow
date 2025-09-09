API Surface
==========

Base URL: configurable via `web/config/site.json` or `localStorage.API_BASE`.

Endpoints
---------
- `GET /v1/cities` → list of cities (transport_sim/data/cities.json)
- `POST /v1/submit` → create job; writes config and launches worker
- `GET /v1/status/{job_id}` → job status + artifacts list
- `POST /v1/insights/{job_id}` → markdown summary of baseline vs tramline
- `POST /v1/insights/{job_id}/chat` → optional Q&A (uses LLM if configured)

Job Config Example
------------------
```
{
  "city": "City of Westminster, Greater London, UK",
  "tram_start": "Dorset Street",
  "tram_end": "Portman Street / Marble Arch Station",
  "num_agents": 300,
  "agent_distribution": {"drive":60, "cycle":10, "tram":30},
  "traffic_level": "off-peak",
  "sim_date": "2025-09-07",
  "sim_time": "08:00"
}
```

Status Response Shape
---------------------
Returns `status`, `artifacts`, optional `message`, `partial`, `missing`, and echoes `config`.

