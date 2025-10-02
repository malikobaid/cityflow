import os
import logging
import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# ----- OpenAI (new 1.x client) -----
from openai import OpenAI

# ----- FAISS (RAG) -----
# For loading prebuilt RAG index
try:
    import faiss
    import numpy as np
except Exception as _e:
    faiss = None  # type: ignore
    np = None  # type: ignore

# Import store and models
from .store import InMemoryStore, Job, STORE
from .models import ChatRequest, ChatResponse, ChatMessage

# -----------------------------------------------------------------------------
# Global configuration and paths
# -----------------------------------------------------------------------------

# Job store instance
job_store = STORE

# Repo root; API package lives under /api
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_ROOT = ROOT_DIR / "local_data"
JOBS_ROOT = DATA_ROOT / "jobs"
JOBS_ROOT.mkdir(parents=True, exist_ok=True)
TRANS_SIM_DIR = ROOT_DIR / "transport_sim"
CONFIG_ROOT = DATA_ROOT / "configs"
CITIES_PATH = TRANS_SIM_DIR / "data" / "cities.json"
WEB_DIR = ROOT_DIR / "web"

# Static files
FILES_PREFIX = "/files"  # already mounted to DATA_ROOT

# Load site-level config (preferred over env for CI/CD)
SITE_CONFIG_PATH = ROOT_DIR / "config" / "site.json"

# Global variables for OpenAI
client: Optional[OpenAI] = None

# System prompt for chat
SYSTEM_PROMPT = (
    "You are a technical assistant for THIS project only. "
    "Use ONLY the provided context to answer. If unsure, say: "
    "'Sorry, I don't have enough context to answer that. Please contact the author Obaid Malik'. "
    "When relevant, include exact file names, relative paths, and small code snippets."
)

# RAG folder path for prebuilt files
RAG_DIR = ROOT_DIR / "RAG"

# Global RAG assets (loaded at startup)
_rag_index = None
_rag_embeddings = None
_rag_metadata = None

# Logging setup
log = logging.getLogger("cityflow.api")
logging.basicConfig(level=logging.INFO)

# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------

def _load_site_max_wait() -> int:
    """Load max wait time from site config."""
    try:
        with open(SITE_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            v = int(cfg.get("maxStatusWaitSec", 180))
            return v
    except Exception:
        return 180

def _list_artifacts(job_id: str) -> list[dict]:
    """List artifacts for a job."""
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

def _job_dir(job_id: str) -> Path:
    """Get job directory path."""
    return JOBS_ROOT / job_id

def _read_json_silent(path: Path):
    """Read JSON file silently, return None if fails."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def _read_tail(path: Path, n: int = 50) -> str:
    """Read last n lines from file."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()[-n:]
        return "".join(lines).strip()
    except Exception:
        return ""

def _format_insights_markdown(cfg: dict, bstats: dict, tstats: dict) -> str:
    """Format insights as markdown."""
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

def _init_openai() -> Optional[OpenAI]:
    """Initialize OpenAI client."""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        log.warning("OPENAI_API_KEY not set; chat will return a friendly fallback.")
        return None
    try:
        return OpenAI(api_key=api_key)
    except Exception as e:
        log.warning("Failed to initialize OpenAI client: %s", e)
        return None

def _load_rag_assets() -> bool:
    """Load prebuilt RAG assets from RAG/ folder."""
    global _rag_index, _rag_embeddings, _rag_metadata

    if _rag_index is not None:
        return True  # Already loaded

    if faiss is None or np is None:
        log.warning("FAISS or NumPy not available; RAG disabled.")
        return False

    try:
        # Load FAISS index
        index_path = RAG_DIR / "rag_index.faiss"
        if not index_path.exists():
            log.warning("RAG index not found at %s; RAG disabled.", index_path)
            return False

        _rag_index = faiss.read_index(str(index_path))

        # Load embeddings
        embeddings_path = RAG_DIR / "rag_embeddings.npy"
        if not embeddings_path.exists():
            log.warning("RAG embeddings not found at %s; RAG disabled.", embeddings_path)
            return False

        _rag_embeddings = np.load(str(embeddings_path))

        # Load metadata
        metadata_path = RAG_DIR / "rag_metadata.json"
        if not metadata_path.exists():
            log.warning("RAG metadata not found at %s; RAG disabled.", metadata_path)
            return False

        with open(metadata_path, 'r', encoding='utf-8') as f:
            _rag_metadata = json.load(f)

        log.info("Loaded RAG assets: %d vectors, %d metadata entries",
                _rag_index.ntotal, len(_rag_metadata))
        return True

    except Exception as e:
        log.warning("Failed to load RAG assets: %s", e)
        return False

def _get_rag_context(user_query: str, top_k: int = 3) -> str:
    """
    Retrieve context from prebuilt RAG index for a user query.
    Returns relevant context chunks or empty string if RAG unavailable.
    """
    global _rag_index, _rag_embeddings, _rag_metadata

    if not _load_rag_assets():
        return ""  # RAG not available

    if not user_query.strip():
        return ""

    try:
        # Generate embedding for the query
        global client
        client = client or _init_openai()
        if client is None:
            return ""

        response = client.embeddings.create(
            input=[user_query],
            model="text-embedding-3-small"
        )
        query_embedding = np.array([response.data[0].embedding], dtype=np.float32)
        faiss.normalize_L2(query_embedding)

        # Search the index
        scores, indices = _rag_index.search(query_embedding, top_k)

        # Collect context from relevant chunks
        context_chunks = []
        for score, idx in zip(scores[0], indices[0]):
            if idx != -1 and idx < len(_rag_metadata):  # Valid index
                chunk_id = list(_rag_metadata.keys())[idx]
                chunk_data = _rag_metadata[chunk_id]
                context_chunks.append(f"Source: {chunk_data['source']}\n{chunk_data['content']}")

        if not context_chunks:
            return ""

        return "\n\n---\n\n".join(context_chunks)

    except Exception as e:
        log.warning("RAG context retrieval failed: %s", e)
        return ""

def _answer_with_rag_context(user_query: str, context: str = "") -> str:
    """
    Answer query using OpenAI with optional RAG context.
    """
    global client
    client = client or _init_openai()

    if not user_query.strip():
        return "Please type a question."

    if client is None:
        return "Sorry, I only answer questions about this project."

    # Compose prompt with context if available
    if context.strip():
        user_prompt = (
            f"Context:\n{context}\n\n"
            f"User question: {user_query}\n"
            "Answer using ONLY the context above. If the answer is not in the context, refuse."
        )
    else:
        user_prompt = (
            f"User question: {user_query}\n"
            "Answer based on your knowledge of this project. If unsure, admit uncertainty."
        )

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

# -----------------------------------------------------------------------------
# Middleware and startup
# -----------------------------------------------------------------------------

def add_request_id_middleware(app):
    """Add request ID middleware to app."""
    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers["x-request-id"] = request.state.request_id
        return response

def _warm_start():
    """Startup event handler."""
    # Non-fatal warmup; we keep serving even if these fail
    try:
        _ = _init_openai()
        _ = _load_rag_assets()
    except Exception as e:
        log.warning("Startup warmup issues: %s", e)

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

MAX_STATUS_WAIT_SEC = _load_site_max_wait()