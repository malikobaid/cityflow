# mock_api/main.py
import os
import logging
import uuid
import json, subprocess, sys
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from fastapi.responses import JSONResponse

# ----- Models (keep your existing models.py) -----
# Chat schemas (added earlier)
from .models import ChatRequest, ChatResponse, ChatMessage
# Existing simulation/job schemas (unchanged)
from .models import SubmitRequest, SubmitResponse, StatusResponse
from .store import InMemoryStore, Job, STORE

from fastapi.staticfiles import StaticFiles



# Job store (unchanged; we call through to your existing store.py)
# import store
job_store = STORE

# repo root; API package lives under /mock_api
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_ROOT = ROOT_DIR / "local_data"
JOBS_ROOT = DATA_ROOT / "jobs"
JOBS_ROOT.mkdir(parents=True, exist_ok=True)
TRANS_SIM_DIR = ROOT_DIR / "transport_sim"
CONFIG_ROOT = DATA_ROOT / "configs"
CITIES_PATH = TRANS_SIM_DIR / "data" / "cities.json"

# ----- OpenAI (new 1.x client) -----
from openai import OpenAI

# ----- LlamaIndex (RAG) -----
# If these imports fail we’ll degrade gracefully.
try:
    from llama_index.core import VectorStoreIndex, SimpleDirectoryReader
except Exception as _e:  # avoid import error during dev env setup
    VectorStoreIndex = None  # type: ignore
    SimpleDirectoryReader = None  # type: ignore

# -----------------------------------------------------------------------------
# App setup
# -----------------------------------------------------------------------------
log = logging.getLogger("cityflow.api")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="CityFlow API", version="0.3.0")

app.mount("/files", StaticFiles(directory=str(DATA_ROOT)), name="files")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080", "http://127.0.0.1:8080"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

FILES_PREFIX = "/files"  # already mounted to DATA_ROOT

# Load site-level config (preferred over env for CI/CD)
SITE_CONFIG_PATH = ROOT_DIR / "config" / "site.json"
def _load_site_max_wait() -> int:
    try:
        with open(SITE_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            v = int(cfg.get("maxStatusWaitSec", 180))
            return v
    except Exception:
        return 180

MAX_STATUS_WAIT_SEC = _load_site_max_wait()

def _list_artifacts(job_id: str) -> list[dict]:
    job_dir = JOBS_ROOT / job_id
    if not job_dir.exists():
        return []
    out = []
    for p in sorted(job_dir.iterdir()):
        if p.is_file():
            out.append({
                "name": p.name,
                "url": f"{FILES_PREFIX}/jobs/{job_id}/{p.name}",
            })
    return out

@app.get("/v1/cities")
def get_cities():
    with open(CITIES_PATH, "r", encoding="utf-8") as f:
        return JSONResponse(json.load(f))

# -----------------------------------------------------------------------------
# Insights helpers
# -----------------------------------------------------------------------------

def _job_dir(job_id: str) -> Path:
    return JOBS_ROOT / job_id

def _read_json_silent(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def _read_tail(path: Path, n: int = 50) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()[-n:]
        return "".join(lines).strip()
    except Exception:
        return ""

def _format_insights_markdown(cfg: dict, bstats: dict, tstats: dict) -> str:
    def km(v):
        try:
            return float(v) / 1000.0
        except Exception:
            return None
    def fmt_km(v):
        return f"{v:.2f} km" if v is not None else "—"

    city = cfg.get("city") or "(unknown city)"
    traffic = (cfg.get("traffic") or cfg.get("traffic_level") or "off-peak").strip().lower()
    agents = int(cfg.get("num_agents") or 0)

    b_avg = km((bstats or {}).get("avg_distance"))
    t_avg = km((tstats or {}).get("avg_distance"))
    delta = (t_avg - b_avg) if (b_avg is not None and t_avg is not None) else None
    pct = (100.0 * delta / b_avg) if (delta is not None and b_avg and b_avg > 0) else None

    lines = []
    lines.append(f"### Summary for {city}\n")
    lines.append(f"- Traffic: {traffic}")
    lines.append(f"- Agents: {agents}")
    if b_avg is not None and t_avg is not None:
        trend = "decrease" if delta < 0 else ("increase" if delta > 0 else "no change")
        pct_txt = (f" ({pct:+.1f}%)" if pct is not None else "")
        lines.append(f"- Average distance: {fmt_km(b_avg)} → {fmt_km(t_avg)} ({trend}{pct_txt})")

    # Mode-level changes: compute and show top 2 by absolute delta
    b_modes = (bstats or {}).get("by_mode", {})
    t_modes = (tstats or {}).get("by_mode", {})
    def mode_row(m):
        b = b_modes.get(m, {})
        t = t_modes.get(m, {})
        b_avg_m = km(b.get("avg"))
        t_avg_m = km(t.get("avg"))
        d = (t_avg_m - b_avg_m) if (b_avg_m is not None and t_avg_m is not None) else None
        b_cnt = b.get("count") or b.get("reachable_count")
        t_cnt = t.get("count") or t.get("reachable_count")
        return {
            "mode": m,
            "b_avg": b_avg_m,
            "t_avg": t_avg_m,
            "delta": d,
            "b_cnt": b_cnt,
            "t_cnt": t_cnt,
        }
    rows = [mode_row(m) for m in set(list(b_modes.keys()) + list(t_modes.keys()))]
    rows = [r for r in rows if r["b_avg"] is not None and r["t_avg"] is not None]
    rows.sort(key=lambda r: abs(r["delta"]) if r["delta"] is not None else 0, reverse=True)
    if rows:
        lines.append("")
        lines.append("#### By mode (top changes)")
        for r in rows[:2]:
            trend = ("improved" if (r["delta"] is not None and r["delta"] < 0) else ("worsened" if (r["delta"] is not None and r["delta"] > 0) else "–"))
            cnt_txt = ""
            if r["b_cnt"] is not None and r["t_cnt"] is not None and r["b_cnt"] != r["t_cnt"]:
                cnt_txt = f" (count: {r['b_cnt']} → {r['t_cnt']})"
            lines.append(f"- {r['mode'].title()}: {fmt_km(r['b_avg'])} → {fmt_km(r['t_avg'])} ({trend}){cnt_txt}")

    # Why (likely): concise reasons using simple heuristics
    why = []
    if delta is not None:
        if delta < 0:
            why.append("Tram segment shortens paths to the hub for some travelers.")
        elif delta > 0:
            why.append("Tram endpoints are far from demand clusters; few benefit from the link.")
        else:
            why.append("New link overlaps existing routes; impact is limited in this slice.")

    # Tram-specific heuristics
    tram_b = b_modes.get("tram", {})
    tram_t = t_modes.get("tram", {})
    tram_b_avg = km(tram_b.get("avg"))
    tram_t_avg = km(tram_t.get("avg"))
    tram_b_cnt = tram_b.get("count") or tram_b.get("reachable_count")
    tram_t_cnt = tram_t.get("count") or tram_t.get("reachable_count")
    if tram_b_avg is not None and tram_t_avg is not None:
        if tram_t_avg < (tram_b_avg or 0) * 0.7 or (tram_b_avg and (tram_b_avg - tram_t_avg) > 0.8):
            why.append("Tram trips are much shorter, indicating a direct shortcut was added.")
    if agents and tram_b_cnt is not None and tram_t_cnt is not None:
        if tram_t_cnt - tram_b_cnt >= max(3, int(0.05 * agents)):
            why.append("More users switched to tram, increasing usage where the link helps.")
        elif tram_b_cnt - tram_t_cnt >= max(3, int(0.05 * agents)):
            why.append("Fewer tram users suggest endpoints do not align with current demand.")

    # Traffic note
    if traffic in ("peak", "rush hour", "rush-hour", "rushhour"):
        why.append("Peak congestion inflates road lengths; tram has a relative advantage.")

    if why:
        lines.append("")
        lines.append("#### Why (likely)")
        # Keep 3–5 bullets
        for s in why[:5]:
            lines.append(f"- {s}")

    return "\n".join(lines).strip()


def _compact_stats_for_prompt(cfg: dict, bstats: dict, tstats: dict, stderr_tail: str) -> str:
    """Return a compact, human-readable context string for the LLM."""
    def num(x, d=2):
        try:
            return round(float(x), d)
        except Exception:
            return x

    parts = []
    city = cfg.get("city") or "(unknown city)"
    traffic = cfg.get("traffic") or cfg.get("traffic_level") or "off-peak"
    agents = cfg.get("num_agents") or 0
    parts.append(f"City: {city}; Traffic: {traffic}; Agents: {agents}")

    b_avg = (bstats or {}).get("avg_distance")
    t_avg = (tstats or {}).get("avg_distance")
    try:
        pct = (float(t_avg) - float(b_avg)) / float(b_avg) * 100.0 if b_avg else None
    except Exception:
        pct = None
    parts.append(
        f"Average distance (m): baseline {num(b_avg)} -> tramline {num(t_avg)}"
        + (f" ({num(pct,1)}%)" if pct is not None else "")
    )

    b_modes = (bstats or {}).get("by_mode", {})
    t_modes = (tstats or {}).get("by_mode", {})
    rows = []
    for m in set(list(b_modes.keys()) + list(t_modes.keys())):
        b = b_modes.get(m, {})
        t = t_modes.get(m, {})
        b_avg_m = b.get("avg")
        t_avg_m = t.get("avg")
        rows.append({
            "mode": m,
            "b_avg": b_avg_m,
            "t_avg": t_avg_m,
            "b_cnt": b.get("count") or b.get("reachable_count"),
            "t_cnt": t.get("count") or t.get("reachable_count"),
            "delta": (float(t_avg_m) - float(b_avg_m)) if (b_avg_m is not None and t_avg_m is not None) else None,
        })
    rows = [r for r in rows if r["delta"] is not None]
    rows.sort(key=lambda r: abs(r["delta"]), reverse=True)
    if rows:
        parts.append("Top mode changes (avg m and counts):")
        for r in rows[:2]:
            parts.append(
                f"  - {r['mode']}: {num(r['b_avg'])} -> {num(r['t_avg'])}; count {r['b_cnt']} -> {r['t_cnt']}"
            )

    if stderr_tail:
        parts.append("Recent stderr (last lines, if any):")
        parts.append(stderr_tail)

    return "\n".join(parts)

@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request.state.request_id = str(uuid4())
    response = await call_next(request)
    response.headers["x-request-id"] = request.state.request_id
    return response

# -----------------------------------------------------------------------------
# Health
# -----------------------------------------------------------------------------
@app.get("/v1/health")
def health():
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}

# -----------------------------------------------------------------------------
# Simulation endpoints (existing behavior preserved)
# -----------------------------------------------------------------------------
@app.post("/v1/submit", response_model=SubmitResponse)
def submit_job(request: SubmitRequest):

    # ----- 1) Load base template by traffic level -----
    base_cfg_name = "config_off-peak.json" if request.traffic_level == "off-peak" else "config_peak.json"
    base_cfg_path = CONFIG_ROOT / base_cfg_name
    with open(base_cfg_path, "r") as f:
        cfg = json.load(f)

    # ----- 2) Merge request into template (write all fields simulator needs) -----
    cfg["city"] = request.city
    # keep template "hub" unless you expose it in API
    cfg["num_agents"] = request.num_agents
    cfg["agent_distribution"] = request.agent_distribution
    cfg["traffic"] = request.traffic_level  # simulator reads "traffic"
    cfg["tramline"] = [request.tram_start, request.tram_end]
    cfg.setdefault("scenarios", {}).setdefault("tramline_extension", {})["tram_stops"] = [
        request.tram_start, request.tram_end
    ]
    # optional: record when the sim is intended to represent
    cfg["sim_date"] = request.sim_date
    cfg["sim_time"] = request.sim_time

    # ----- 3) Create job and job dir; write merged config -----
    job_id = str(uuid.uuid4())
    job = job_store.create_job(job_id=job_id, config=cfg)

    job_dir = JOBS_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    config_path = job_dir / "config.json"
    with open(config_path, "w") as f:
        json.dump(cfg, f, indent=2)

    # ----- 4) Launch simulation (non-blocking) -----
    print(f"[Job {job_id}] Launching simulation with {config_path} -> {job_dir}")
    subprocess.Popen(
        [
            sys.executable,
            str(TRANS_SIM_DIR / "run_sim.py"),
            "--config", str(config_path),
            "--outdir", str(job_dir),
        ],
        stdout=open(job_dir / "stdout.log", "wb"),
        stderr=open(job_dir / "stderr.log", "wb"),
    )

    # Mark running (polling will flip to complete on outputs)
    job.status = "running"
    job.started_at = datetime.now(timezone.utc)

    return SubmitResponse(
        job_id=job.job_id,
        status=job.status,
        submitted_at=job.submitted_at,
    )


# -----------------------------------------------------------------------------
# Insights (summary + chat)
# -----------------------------------------------------------------------------

@app.post("/v1/insights/{job_id}")
def get_insights(job_id: str):
    job = job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    jd = _job_dir(job_id)
    cfg = job.config or _read_json_silent(jd / "config.json") or {}
    bstats = _read_json_silent(jd / "baseline_stats.json")
    tstats = _read_json_silent(jd / "tramline_stats.json")
    if not (bstats and tstats):
        raise HTTPException(status_code=400, detail="Required artifacts missing: baseline_stats.json and/or tramline_stats.json")
    # If cached, return
    cache_md = jd / "insights.md"
    if cache_md.exists():
        try:
            text = cache_md.read_text(encoding="utf-8")
            if text.strip():
                return {"summary_md": text, "job_id": job_id, "cached": True}
        except Exception:
            pass

    # Try OpenAI for the first summary, else fallback to rule-based
    stderr_tail = _read_tail(jd / "stderr.log", n=30)
    prompt_ctx = _compact_stats_for_prompt(cfg, bstats, tstats, stderr_tail)

    global client
    client = client or _init_openai()
    used_model = None
    token_usage = None
    if client is not None:
        try:
            used_model = "gpt-4o-mini"
            resp = client.chat.completions.create(
                model=used_model,
                messages=[
                    {"role": "system", "content": (
                        "You are a transport analyst. Be concise and explanatory. "
                        "Return 4–6 short bullets (<=14 words each). "
                        "Explain reasons behind changes, not just metrics."
                    )},
                    {"role": "user", "content": (
                        "Context (compact):\n" + prompt_ctx + "\n\n"
                        "Write bullets: Outcome, Why, Modes, Traffic, Risks, Action."
                    )},
                ],
                max_tokens=220,
                temperature=0.2,
            )
            msg = resp.choices[0].message
            content = getattr(msg, "content", None)
            if isinstance(content, list):
                content = "".join((getattr(p, "text", "") or "") for p in content)
            md = (content or "").strip()
            # Cache and return; if empty, fall back below
            if md:
                try:
                    cache_md.write_text(md, encoding="utf-8")
                    meta = {
                        "model": used_model,
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "usage": getattr(resp, "usage", None) and resp.usage.__dict__,
                    }
                    (jd / "insights.meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
                except Exception:
                    pass
                return {"summary_md": md, "job_id": job_id}
        except Exception as e:
            log.warning("LLM insights failed: %s", e)

    # Fallback: rule-based summary
    md = _format_insights_markdown(cfg, bstats, tstats)
    try:
        cache_md.write_text(md, encoding="utf-8")
    except Exception:
        pass
    return {"summary_md": md, "job_id": job_id, "cached": False}


from pydantic import BaseModel

class InsightsChatRequest(BaseModel):
    query: str

@app.post("/v1/insights/{job_id}/chat")
def insights_chat(job_id: str, req: InsightsChatRequest):
    job = job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    jd = _job_dir(job_id)
    cfg = job.config or _read_json_silent(jd / "config.json") or {}
    bstats = _read_json_silent(jd / "baseline_stats.json")
    tstats = _read_json_silent(jd / "tramline_stats.json")
    base_md = _format_insights_markdown(cfg, bstats or {}, tstats or {})

    # Try OpenAI if available, else return a friendly fallback
    global client
    client = client or _init_openai()
    if client is None:
        reply = (
            "Chat is not configured (no API key).\n\n"
            "Here’s a recap based on the job: \n\n" + base_md
        )
        return {"reply_md": reply}

    # Compose a constrained prompt
    ctx = (
        "You are a transport analyst. Summarize and answer using ONLY the provided job context.\n\n"
        f"Job config (JSON):\n{json.dumps(cfg, indent=2)}\n\n"
        f"Baseline stats (JSON):\n{json.dumps(bstats or {}, indent=2)}\n\n"
        f"Tramline stats (JSON):\n{json.dumps(tstats or {}, indent=2)}\n\n"
        f"User question: {req.query}\n"
    )
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Answer concisely in Markdown. If unsure, admit uncertainty."},
                {"role": "user", "content": ctx},
            ],
            max_tokens=500,
            temperature=0.2,
        )
        msg = resp.choices[0].message
        content = getattr(msg, "content", None)
        if isinstance(content, list):
            content = "".join(
                (getattr(p, "text", "") or "")
                for p in content
                if getattr(p, "type", "") in ("text", "output_text")
            )
        reply = (content or "").strip() or base_md
        return {"reply_md": reply}
    except Exception as e:
        log.warning("insights chat failed: %s", e)
        # graceful fallback
        return {"reply_md": base_md}




@app.get("/v1/status/{job_id}", response_model=StatusResponse)
def get_status(job_id: str):
    job = job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job_dir = JOBS_ROOT / job_id

    def _exists_nonempty(path: Path) -> bool:
        try:
            return path.exists() and path.stat().st_size > 0
        except Exception:
            return False

    # Required outputs: both stats, baseline map, and at least one tram map
    required_all = [
        job_dir / "baseline_stats.json",
        job_dir / "tramline_stats.json",
        job_dir / "baseline_access.html",
    ]
    optional_any = [
        job_dir / "tramline_access_colored.html",
        job_dir / "tramline_access.html",
    ]

    have_all = all(_exists_nonempty(p) for p in required_all) and any(
        _exists_nonempty(p) for p in optional_any
    )

    # Compute diagnostics
    elapsed = int(max(0, (datetime.now(timezone.utc) - job.submitted_at).total_seconds()))
    missing = [p.name for p in required_all if not _exists_nonempty(p)]
    stderr_path = job_dir / "stderr.log"
    stderr_text = ""
    has_error = False
    if _exists_nonempty(stderr_path):
        try:
            # Read last ~80 lines for a quick summary
            with open(stderr_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()[-80:]
            stderr_text = "".join(lines)
            ht = stderr_text.lower()
            has_error = ("traceback" in ht) or ("error" in ht) or ("exception" in ht)
        except Exception:
            pass

    message = None
    partial = False

    # Only mark complete when ALL required artifacts are present
    if have_all:
        if job.status != "complete":
            job.status = "complete"
            job.finished_at = datetime.now(timezone.utc)
        message = "All artifacts are ready."
    else:
        # If within wait window, remain running; provide a helpful message
        if elapsed < MAX_STATUS_WAIT_SEC:
            # If store prematurely flipped to complete, override to running
            if job.status == "complete":
                job.status = "running"
                job.finished_at = None
            if has_error:
                message = "Errors detected, still processing. Waiting for outputs…"
            else:
                message = "Generating outputs. This may take a moment…"
        else:
            # Past the wait window. If we have any artifacts, return complete with partial flag
            any_artifacts = any(_exists_nonempty(p) for p in required_all + optional_any)
            if any_artifacts:
                job.status = "complete"
                partial = True
                if job.finished_at is None:
                    job.finished_at = datetime.now(timezone.utc)
                if has_error:
                    message = "Partial results available (errors were logged)."
                else:
                    message = "Partial results available after timeout."
            else:
                # Nothing produced; mark failed with an explanation
                job.status = "failed"
                if has_error and stderr_text:
                    # Provide a short friendly summary
                    message = "Simulation failed. See stderr.log for details."
                else:
                    message = "Timed out waiting for results."

    # Always rebuild artifacts in the shape the model expects
    job.artifacts = _list_artifacts(job_id)

    return StatusResponse(
        job_id=job.job_id,
        status=job.status,
        submitted_at=job.submitted_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        progress=job.progress,
        artifacts=job.artifacts,
        config=job.config,
        message=message,
        partial=partial or None,
        error=has_error or None,
        missing=(missing or None),
        timeout_sec=MAX_STATUS_WAIT_SEC,
        elapsed_sec=elapsed,
    )



# -----------------------------------------------------------------------------
# Chat (RAG + OpenAI 1.x)
# -----------------------------------------------------------------------------
# Project docs path: repo root / project_docs
THIS_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(THIS_DIR, ".."))
PROJECT_DOCS_DIR = os.path.join(ROOT_DIR, "project_docs")

_index: Optional["VectorStoreIndex"] = None
client: Optional[OpenAI] = None

SYSTEM_PROMPT = (
    "You are a technical assistant for THIS project only. "
    "Use ONLY the provided context to answer. If unsure, say: "
    "'Sorry, I don't have enough context to answer that. Please contact the author Obaid Malik'. "
    "When relevant, include exact file names, relative paths, and small code snippets."
)

def _init_openai() -> Optional[OpenAI]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        log.warning("OPENAI_API_KEY not set; chat will return a friendly fallback.")
        return None
    try:
        return OpenAI(api_key=api_key)
    except Exception as e:
        log.warning("Failed to initialize OpenAI client: %s", e)
        return None

def _load_index_once() -> Optional["VectorStoreIndex"]:
    global _index
    if _index is not None:
        return _index
    if VectorStoreIndex is None or SimpleDirectoryReader is None:
        log.warning("LlamaIndex not available; RAG disabled.")
        return None
    if not os.path.isdir(PROJECT_DOCS_DIR):
        log.warning("project_docs folder not found at %s; RAG disabled.", PROJECT_DOCS_DIR)
        return None
    try:
        docs = SimpleDirectoryReader(PROJECT_DOCS_DIR).load_data()
        if not docs:
            log.warning("project_docs is empty; RAG disabled.")
            return None
        _index = VectorStoreIndex.from_documents(docs)
        log.info("RAG index built from %d document(s) in %s", len(docs), PROJECT_DOCS_DIR)
        return _index
    except Exception as e:
        log.warning("Failed to build RAG index: %s", e)
        return None

def _answer_with_rag(user_query: str) -> str:
    """
    Retrieve context from the index (if available) and answer with OpenAI.
    When anything is missing (index/client/docs), degrade gracefully with a scoped fallback.
    """
    # Ensure OpenAI client + index are available
    global client
    client = client or _init_openai()
    index = _load_index_once()

    if not user_query.strip():
        return "Please type a question."

    # If we lack either OpenAI or index/docs, return a scoped fallback (no 500s)
    if client is None or index is None:
        return "Sorry, I only answer questions about this project."

    # Retrieve top-K context
    try:
        retriever = index.as_retriever(similarity_top_k=3)
        nodes = retriever.retrieve(user_query)
        context_texts = [getattr(n, "text", "").strip() for n in nodes if getattr(n, "text", "").strip()]
        joined = " ".join(context_texts)
        if not context_texts or len(joined) < 20:
            return "Sorry, I only answer questions about this project."
        context_block = "\n\n".join(context_texts)
    except Exception as e:
        log.warning("RAG retrieval failed: %s", e)
        return "Sorry, I only answer questions about this project."

    # Compose prompts
    user_prompt = (
        f"Context:\n{context_block}\n\n"
        f"User question: {user_query}\n"
        f"Answer using ONLY the context above. If the answer is not in the context, refuse."
    )

    # OpenAI (new 1.x client)
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=500,
            temperature=0.2,
        )
        msg = resp.choices[0].message
        content = getattr(msg, "content", None)
        # Defensive: content is usually a string; if it's a list of parts, join text parts.
        if isinstance(content, list):
            content = "".join(
                (getattr(p, "text", "") or "")
                for p in content
                if getattr(p, "type", "") in ("text", "output_text")
            )
        return (content or "").strip() or "Sorry, I only answer questions about this project."
    except Exception as e:
        log.warning("OpenAI call failed: %s", e)
        return f"Sorry, there was an error contacting the model: {e}"

@app.on_event("startup")
def _warm_start():
    # Non-fatal warmup; we keep serving even if these fail
    try:
        _ = _init_openai()
        _ = _load_index_once()
    except Exception as e:
        log.warning("Startup warmup issues: %s", e)

@app.post("/v1/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    """
    Chat endpoint: accepts {messages:[{role,content}...]} and returns
    { "message": { "role": "assistant", "content": "..." } }
    """
    try:
        user_text = req.messages[-1].content
        answer = _answer_with_rag(user_text)
        return ChatResponse(message=ChatMessage(role="assistant", content=answer))
    except HTTPException:
        raise
    except Exception as e:
        log.exception("chat failed")
        raise HTTPException(status_code=500, detail=str(e))
