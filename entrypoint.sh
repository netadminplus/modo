#!/bin/sh
# =============================================================================
# entrypoint.sh
# Starts the FastAPI web dashboard and Aiogram bot concurrently.
# In production, consider running them as separate Docker services instead.
# =============================================================================

set -e

echo "⏳  Waiting for PostgreSQL..."
until python -c "
import asyncio, asyncpg, os
async def check():
    conn = await asyncpg.connect(os.environ['DATABASE_URL'].replace('+asyncpg',''))
    await conn.close()
asyncio.run(check())
" 2>/dev/null; do
  echo "   PostgreSQL not ready — retrying in 2s..."
  sleep 2
done
echo "✅  PostgreSQL is ready."

echo "⏳  Waiting for Redis..."
until python -c "
import asyncio, redis.asyncio as aioredis, os
async def check():
    r = await aioredis.from_url(os.environ['REDIS_URL'])
    await r.ping()
    await r.aclose()
asyncio.run(check())
" 2>/dev/null; do
  echo "   Redis not ready — retrying in 2s..."
  sleep 2
done
echo "✅  Redis is ready."

echo "🗃️  Initialising database tables..."
python -c "
import asyncio
from core.models.database import init_db
asyncio.run(init_db())
"
echo "✅  Database initialised."

# ── Start web dashboard (background) ─────────────────────────────────────────
echo "🌐  Starting FastAPI web dashboard on port ${WEB_PORT:-8000}..."
uvicorn web.app:app \
    --host 0.0.0.0 \
    --port "${WEB_PORT:-8000}" \
    --workers 2 \
    --access-log \
    --log-level "${LOG_LEVEL:-info}" &

WEB_PID=$!

# ── Start Aiogram bot (foreground) ────────────────────────────────────────────
echo "🤖  Starting Telegram bot (polling mode)..."
python -m bot.main polling &

BOT_PID=$!

# ── Graceful shutdown handler ─────────────────────────────────────────────────
trap 'echo "🛑 Shutting down..."; kill $WEB_PID $BOT_PID 2>/dev/null; wait; echo "✅ Done."' TERM INT

# Keep container alive; exit if either process dies
wait -n
EXIT_CODE=$?
echo "⚠️  A process exited with code $EXIT_CODE. Stopping container."
kill $WEB_PID $BOT_PID 2>/dev/null
exit $EXIT_CODE
