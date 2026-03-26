"""
bot/main.py
-----------
Aiogram 3.x bot entry point.
Sets up the dispatcher, registers all routers, middlewares,
and starts the bot in polling or webhook mode.
"""

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from bot.handlers import group_setup, moderation, topic_acl, welcome
from bot.middlewares.db_middleware import DatabaseMiddleware, ModerationSettingsMiddleware
from core.config import settings
from core.models.database import init_db
from core.services.cache_service import close_redis

# ── Logging ───────────────────────────────────────────────────────────────────
# Ensure log directory exists
import os
os.makedirs("data/logs", exist_ok=True)

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
# Add file handler separately with error handling
try:
    file_handler = logging.FileHandler("data/logs/bot.log")
    logging.getLogger().addHandler(file_handler)
except (PermissionError, OSError):
    logging.warning("Could not create bot.log - continuing without file logging")

logger = logging.getLogger(__name__)

# ── Bot instance (module-level for access in helpers) ─────────────────────────
bot = Bot(
    token=settings.bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)


def create_dispatcher() -> Dispatcher:
    """Build and configure the Aiogram Dispatcher."""
    dp = Dispatcher()

    # ── Global middlewares (applied to ALL updates) ────────────────────────
    dp.message.middleware(DatabaseMiddleware())
    dp.callback_query.middleware(DatabaseMiddleware())
    dp.message.middleware(ModerationSettingsMiddleware())
    dp.callback_query.middleware(ModerationSettingsMiddleware())

    # ── Register routers (order matters — guards first) ────────────────────
    # topic_acl.router has the guard that must run BEFORE regular handlers
    dp.include_router(group_setup.router)
    dp.include_router(topic_acl.router)
    dp.include_router(welcome.router)
    dp.include_router(moderation.router)

    return dp


async def on_startup(bot: Bot) -> None:
    """Startup hook — initialise DB, log bot info."""
    await init_db()
    me = await bot.get_me()
    logger.info("Bot started: @%s (id=%d)", me.username, me.id)


async def on_shutdown(bot: Bot) -> None:
    """Shutdown hook — clean up connections."""
    await close_redis()
    await bot.session.close()
    logger.info("Bot shut down cleanly.")


# ── Polling mode (development / simple deployments) ──────────────────────────

async def run_polling() -> None:
    dp = create_dispatcher()
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    logger.info("Starting bot in POLLING mode...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


# ── Webhook mode (production) ─────────────────────────────────────────────────

WEBHOOK_PATH = f"/webhook/{settings.bot_token}"
WEBHOOK_URL = f"https://{settings.domain}{WEBHOOK_PATH}"


async def run_webhook() -> None:
    dp = create_dispatcher()
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    await bot.set_webhook(WEBHOOK_URL)
    logger.info("Webhook set: %s", WEBHOOK_URL)

    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", settings.web_port)
    await site.start()
    logger.info("Webhook server listening on port %d", settings.web_port)

    # Keep running
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "polling"
    if mode == "webhook":
        asyncio.run(run_webhook())
    else:
        asyncio.run(run_polling())
