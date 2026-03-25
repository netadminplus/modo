"""
web/health.py
--------------
Health check router — mounted on the main FastAPI app.
Used by Docker HEALTHCHECK and load balancers.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from core.models.database import engine
from core.services.cache_service import get_redis

router = APIRouter()


@router.get("/health")
async def health_check():
    """
    Returns 200 if both PostgreSQL and Redis are reachable.
    Returns 503 with details if any dependency is down.
    """
    status = {"status": "ok", "postgres": "ok", "redis": "ok"}
    http_status = 200

    # Check PostgreSQL
    try:
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
    except Exception as e:
        status["postgres"] = str(e)
        status["status"] = "degraded"
        http_status = 503

    # Check Redis
    try:
        redis = await get_redis()
        await redis.ping()
    except Exception as e:
        status["redis"] = str(e)
        status["status"] = "degraded"
        http_status = 503

    return JSONResponse(status, status_code=http_status)
