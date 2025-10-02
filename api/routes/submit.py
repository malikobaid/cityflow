import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from api.models import SubmitRequest, SubmitResponse
from api.globals import job_store, TRANS_SIM_DIR, CONFIG_ROOT, JOBS_ROOT

router = APIRouter()

@router.post("/v1/submit", response_model=SubmitResponse)
def submit_job(request: SubmitRequest):
    """Submit a new simulation job."""

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