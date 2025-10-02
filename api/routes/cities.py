from fastapi import APIRouter
from fastapi.responses import JSONResponse
from api.globals import CITIES_PATH

router = APIRouter()

@router.get("/cities")
def get_cities():
    """Get list of available cities."""
    with open(CITIES_PATH, "r", encoding="utf-8") as f:
        return JSONResponse(__import__("json").load(f))