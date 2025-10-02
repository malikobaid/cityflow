from fastapi import APIRouter
from datetime import datetime, timezone

router = APIRouter()

@router.get("/v1/health")
def health():
    """Health check endpoint."""
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}