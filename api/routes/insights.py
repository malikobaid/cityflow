import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException

from api.models import InsightsChatRequest
from api.globals import (
    job_store, _job_dir, _read_json_silent, _read_tail,
    _format_insights_markdown, _compact_stats_for_prompt,
    client, _init_openai, log
)

router = APIRouter()

@router.post("/insights/{job_id}")
def get_insights(job_id: str):
    """Get insights for a completed job."""
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
                        "Explain reasons behind changes, not just metrics."
                        ""
                    )},
                    {"role": "user", "content": (
                        "Context (compact):\n" + prompt_ctx + "\n\n"
                        "Write bullets: Outcome, Why, Modes, Traffic, Risks, Action."
                    )},
                ],
                max_tokens=500,
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

@router.post("/insights/{job_id}/chat")
def insights_chat(job_id: str, req: InsightsChatRequest):
    """Chat about insights for a specific job."""
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