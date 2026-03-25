"""
core/utils/admin_sync.py
-------------------------
Utility to sync a group's admin list from the Telegram API into the database.
Should be called periodically (e.g., on bot startup, or via a /sync_admins command).
"""

import logging

from aiogram import Bot
from aiogram.types import ChatMemberAdministrator, ChatMemberOwner
from sqlalchemy.ext.asyncio import AsyncSession

from core.services.group_service import sync_group_admins

logger = logging.getLogger(__name__)


async def sync_admins_for_group(
    bot: Bot, session: AsyncSession, group_id: int
) -> int:
    """
    Fetch admin list from Telegram and write it to the database.
    Returns the count of admins synced.
    """
    try:
        members = await bot.get_chat_administrators(group_id)
    except Exception as exc:
        logger.warning("Failed to get admins for group %d: %s", group_id, exc)
        return 0

    admins = []
    for m in members:
        if m.user.is_bot:
            continue  # skip bot accounts
        admins.append({
            "user_id": m.user.id,
            "is_owner": isinstance(m, ChatMemberOwner),
            "can_manage_topics": (
                isinstance(m, ChatMemberAdministrator)
                and getattr(m, "can_manage_topics", False)
            ),
        })

    await sync_group_admins(session, group_id, admins)
    logger.info("Synced %d admins for group %d", len(admins), group_id)
    return len(admins)
