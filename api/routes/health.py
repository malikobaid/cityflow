from fastapi import APIRouter
from datetime import datetime, timezone

router = APIRouter()

@router.get("/health")
def health():
    """Health check endpoint."""
    print("Health check OK")
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}