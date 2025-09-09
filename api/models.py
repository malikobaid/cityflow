from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Literal, Dict
from datetime import datetime

Status = Literal["queued", "running", "complete", "failed"]

Role = Literal["system", "user", "assistant"]

class AgentDistribution(BaseModel):
    drive: int = 50
    cycle: int = 30
    tram: int = 20

class TramlineConfig(BaseModel):
    scenario: Literal["tramline"] = "tramline"
    city: str
    tram_start: str
    tram_end: str
    num_agents: int = Field(ge=1, default=100)
    agent_distribution: AgentDistribution
    sim_date: str
    sim_time: str
    traffic_level: Literal["off_peak", "normal", "rush_hour"] = "normal"

class SubmitRequest(BaseModel):
    city: str
    tram_start: str
    tram_end: str
    num_agents: int
    agent_distribution: Dict[str, int]
    sim_date: str
    sim_time: str
    traffic_level: str


class SubmitResponse(BaseModel):
    job_id: str
    submitted_at: datetime

class Artifact(BaseModel):
    name: str
    url: str

class StatusResponse(BaseModel):
    job_id: str
    status: Status
    progress: int
    submitted_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    metrics: Optional[Dict] = None
    artifacts: List[Artifact] = []
    # Include the job's config so the UI can read city/agents/traffic
    config: Optional[Dict] = None
    # New: user-facing message and diagnostics
    message: Optional[str] = None
    partial: Optional[bool] = None
    error: Optional[bool] = None
    missing: Optional[List[str]] = None
    timeout_sec: Optional[int] = None
    elapsed_sec: Optional[int] = None

class ChatMessage(BaseModel):
    role: Role
    content: str = Field(min_length=1, max_length=4000)

class ChatRequest(BaseModel):
    messages: List[ChatMessage] = Field(..., min_items=1)
    session_id: Optional[str] = None

    @field_validator("messages")
    @classmethod
    def last_must_be_user(cls, msgs: List[ChatMessage]):
        if not msgs or msgs[-1].role != "user":
            raise ValueError("Last message must be from role 'user'.")
        return msgs

class ChatResponse(BaseModel):
    message: ChatMessage
