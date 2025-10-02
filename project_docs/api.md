# CityFlow — API Reference

Base URL: `/v1`

## Health
**GET** `/v1/health` → 200
```json
{ "name": "cityflow", "version": "0.3.0", "uptime_s": 123.4 }
```

## Cities
**GET** `/v1/cities`
- **200** JSON body:
```json
{
  "cities": [
    { "id": "bournemouth", "name": "Bournemouth", "stops": [ {"id":"...","name":"..."}, ... ] },
    { "id": "london", "name": "London", "stops": [ ... ] }
  ]
}
```

## Submit Simulation
**POST** `/v1/submit`
- **Request** (JSON):
```json
{
  "city_id": "bournemouth",
  "trips": 2000,
  "modes": ["drive", "cycle", "tram"],
  "start_time": "2025-10-01T08:00:00Z",
  "seed": 123
}
```
- **Response** 202 Accepted:
```json
{ "job_id": "cf-20251001-8f3a2c", "status": "queued" }
```

## Status
**GET** `/v1/status/{{job_id}}`
- **Response**:
```json
{
  "job_id": "cf-20251001-8f3a2c",
  "status": "finished",
  "artifacts": [
    { "name": "baseline_stats.json", "href": "/files/jobs/cf-20251001-8f3a2c/baseline_stats.json" },
    { "name": "tramline_stats.json", "href": "/files/jobs/cf-20251001-8f3a2c/tramline_stats.json" },
    { "name": "baseline_access.html", "href": "/files/jobs/cf-20251001-8f3a2c/baseline_access.html" },
    { "name": "tramline_access.html", "href": "/files/jobs/cf-20251001-8f3a2c/tramline_access.html" }
  ],
  "metrics": { "runtime_s": 81.5, "agents": 2000 }
}
```

## Insights
**POST** `/v1/insights`
- **Request**:
```json
{
  "job_id": "cf-20251001-8f3a2c",
  "questions": ["What changed after the tramline?"],
  "llm": true
}
```
- **Response** (Markdown):
```json
{ "markdown": "### Summary\n- ..." }
```

## Chat
**POST** `/v1/chat`
- **Request**:
```json
{
  "job_id": "cf-20251001-8f3a2c",
  "message": "Explain the modal split changes",
  "context": ["summary.json"]
}
```
- **Response**:
```json
{ "reply": "The tramline increased ..." }
```
