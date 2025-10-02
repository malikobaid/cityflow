# api/main.py
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse

from .globals import ROOT_DIR, DATA_ROOT, WEB_DIR, add_request_id_middleware, _warm_start
from .routes import cities, health, submit, insights, status, chat
from urllib.parse import quote
from inspect import iscoroutinefunction

log = logging.getLogger("cityflow.api")

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        if callable(_warm_start):
            if iscoroutinefunction(_warm_start):
                await _warm_start()
            else:
                _warm_start()
    except Exception as e:
        log.warning(f"Warm start skipped: {e}")
    yield

app = FastAPI(title="CityFlow API", version="0.3.0", lifespan=lifespan)

add_request_id_middleware(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# API routers first
app.include_router(health.router,  prefix="/v1", tags=["health"])
app.include_router(cities.router,  prefix="/v1", tags=["cities"])
app.include_router(submit.router,  prefix="/v1", tags=["submit"])
app.include_router(status.router,  prefix="/v1", tags=["status"])
app.include_router(insights.router, prefix="/v1", tags=["insights"])
app.include_router(chat.router,    prefix="/v1", tags=["chat"])

for r in app.router.routes:
    try:
        methods = ",".join(sorted(r.methods)) if hasattr(r, "methods") else ""
        print(f"ROUTE {methods:10s} {r.path}")
    except Exception:
        pass

@app.get("/sim_results.html")
def sim_results_page():
    # Always serve the results page; JS reads ?job_id=... from the query string
    return FileResponse(WEB_DIR / "sim_results.html")

@app.get("/sim_results.html/{job_id}")
def sim_results_pretty_redirect(job_id: str):
    return RedirectResponse(f"/sim_results.html?job_id={quote(job_id)}", status_code=307)

# Static mounts LAST
app.mount("/files", StaticFiles(directory=str(DATA_ROOT)), name="files")
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")