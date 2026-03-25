"""
web/lifespan.py
----------------
FastAPI lifespan events: initialise DB on startup, clean up on shutdown.
Import and use via:  app = FastAPI(lifespan=lifespan)
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.models.database import init_db
from core.services.cache_service import close_redis, get_redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager."""
    # ── Startup ──────────────────────────────────────────────────────────
    await init_db()
    await get_redis()  # pre-warm the connection pool
    yield
    # ── Shutdown ─────────────────────────────────────────────────────────
    await close_redis()
