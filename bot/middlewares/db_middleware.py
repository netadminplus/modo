"""
bot/middlewares/db_middleware.py
---------------------------------
Aiogram middleware that injects a SQLAlchemy AsyncSession and
pre-loaded moderation settings into every handler's data dict.
"""

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

from core.models.database import AsyncSessionLocal, ModerationSettings
from core.services.cache_service import get_cached_mod_settings, cache_mod_settings
from core.services.group_service import get_moderation_settings
import json


class DatabaseMiddleware(BaseMiddleware):
    """
    Injects `db` (AsyncSession) into handler data.
    The session is committed/rolled-back automatically.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        async with AsyncSessionLocal() as session:
            data["db"] = session
            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise


class ModerationSettingsMiddleware(BaseMiddleware):
    """
    Pre-loads ModerationSettings for the current chat and stores them
    in data["mod_settings"] — checked from Redis cache first.
    Only runs for Message and CallbackQuery events in groups.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        chat = None
        if isinstance(event, Message) and event.chat:
            chat = event.chat
        elif isinstance(event, CallbackQuery) and event.message and event.message.chat:
            chat = event.message.chat

        if chat and chat.type in ("group", "supergroup"):
            group_id = chat.id

            # Try cache first
            cached = await get_cached_mod_settings(group_id)
            if cached:
                data["mod_settings"] = cached
            else:
                db = data.get("db")
                if db:
                    settings = await get_moderation_settings(db, group_id)
                    if settings:
                        settings_dict = {
                            col.name: getattr(settings, col.name)
                            for col in ModerationSettings.__table__.columns
                        }
                        await cache_mod_settings(group_id, settings_dict)
                        data["mod_settings"] = settings_dict
                    else:
                        data["mod_settings"] = {}
        else:
            data["mod_settings"] = {}

        return await handler(event, data)
