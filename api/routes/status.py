import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from api.models import StatusResponse
from api.globals import job_store, JOBS_ROOT, MAX_STATUS_WAIT_SEC, _list_artifacts

router = APIRouter()

@router.get("/v1/status/{job_id}", response_model=StatusResponse)
def get_status(job_id: str):
    """Get status of a simulation job."""
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