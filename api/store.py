from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

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
