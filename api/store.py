from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from pathlib import Path
import json
import os

@dataclass
class Job:
    job_id: str
    submitted_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    status: str = "queued"          # queued -> running -> complete | failed
    progress: int = 0               # 0..100
    config: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    artifacts: List[dict] = field(default_factory=list)

class InMemoryStore:
    def __init__(self):
        self.jobs: Dict[str, Job] = {}
        self._load_existing_jobs()

    def _load_existing_jobs(self):
        """Load existing jobs from disk that have output files."""
        jobs_dir = Path("local_data/jobs")
        if not jobs_dir.exists():
            return

        for job_dir in jobs_dir.iterdir():
            if not job_dir.is_dir():
                continue

            job_id = job_dir.name

            # Check if job has required output files
            config_path = job_dir / "config.json"
            baseline_stats = job_dir / "baseline_stats.json"
            tramline_stats = job_dir / "tramline_stats.json"

            if config_path.exists() and baseline_stats.exists() and tramline_stats.exists():
                try:
                    # Load config
                    with open(config_path, 'r') as f:
                        config = json.load(f)

                    # Load stats to check if job is complete
                    with open(baseline_stats, 'r') as f:
                        baseline_data = json.load(f)

                    with open(tramline_stats, 'r') as f:
                        tramline_data = json.load(f)

                    # Create job object
                    # Estimate submitted time from file modification or use current time
                    submitted_at = datetime.fromtimestamp(config_path.stat().st_mtime, tz=timezone.utc)

                    job = Job(
                        job_id=job_id,
                        submitted_at=submitted_at,
                        status="complete",
                        progress=100,
                        config=config,
                        finished_at=submitted_at  # Use file mod time as proxy
                    )

                    # Add artifacts
                    artifacts = []
                    for file_path in job_dir.iterdir():
                        if file_path.is_file():
                            artifacts.append({
                                "name": file_path.name,
                                "url": f"/files/jobs/{job_id}/{file_path.name}"
                            })

                    job.artifacts = artifacts
                    self.jobs[job_id] = job

                except Exception as e:
                    print(f"Warning: Failed to load existing job {job_id}: {e}")

    def create_job(self, job_id: str, config: dict) -> Job:
        now = datetime.now(timezone.utc)
        job = Job(job_id=job_id, submitted_at=now, config=config, status="queued", progress=0)
        self.jobs[job_id] = job
        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        job = self.jobs.get(job_id)
        if not job:
            return None

        # Auto-progress locally based on time since submitted
        now = datetime.now(timezone.utc)
        elapsed = (now - job.submitted_at).total_seconds()
        # Timeline: 0-2s queued, 2-12s running, 12s+ complete
        if elapsed < 2:
            job.status = "queued"; job.progress = 0
        elif elapsed < 12:
            job.status = "running"
            job.progress = min(99, int((elapsed - 2) / 10 * 100))  # 0..99
            job.started_at = job.started_at or (job.submitted_at + timedelta(seconds=2))
        else:
            job.status = "complete"
            job.progress = 100
            job.started_at = job.started_at or (job.submitted_at + timedelta(seconds=2))
            job.finished_at = job.finished_at or (job.submitted_at + timedelta(seconds=12))
            # if not job.artifacts:
            #     # Dummy artifacts
            #     job.artifacts = [
            #         {"name": "routes.csv", "url": "https://example.com/artifacts/routes.csv"},
            #         {"name": "metrics.json", "url": "https://example.com/artifacts/metrics.json"},
            #     ]
            #     job.metrics = {"agents": job.config.get("num_agents", 0), "avg_travel_time_s": 312.4}
        return job

STORE = InMemoryStore()
