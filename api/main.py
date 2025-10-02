# api/main.py
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .globals import ROOT_DIR, DATA_ROOT, WEB_DIR, add_request_id_middleware, _warm_start
from .routes import cities, health, submit, insights, status, chat

log = logging.getLogger("cityflow.api")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ----- startup -----
    try:
        await _warm_start() 
    except Exception as e:
        log.warning(f"Warm start skipped: {e}")
    yield
    # ----- shutdown -----
    # e.g., await client.aclose() if open clients/resources
    # (leave empty if not needed)

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

# Files + web last
app.mount("/files", StaticFiles(directory=str(DATA_ROOT)), name="files")
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=False), name="web")