"""
bot/filters/admin_filter.py
----------------------------
Custom Aiogram filters for admin and bot-admin checks.
"""

from aiogram.filters import BaseFilter
from aiogram.types import Message, ChatMemberAdministrator, ChatMemberOwner

from core.config import settings


class IsGroupAdmin(BaseFilter):
    """
    Passes if the message sender is a chat administrator or owner.
    Works in groups and supergroups.
    """

    async def __call__(self, message: Message) -> bool:
        if not message.chat or message.chat.type not in ("group", "supergroup"):
            return False
        try:
            member = await message.chat.get_member(message.from_user.id)
            return isinstance(member, (ChatMemberAdministrator, ChatMemberOwner))
        except Exception:
            return False


class IsBotAdmin(BaseFilter):
    """
    Passes if the sender's Telegram ID is in the ADMIN_IDS env list.
    These are global super-admins who can manage the bot itself.
    """

    async def __call__(self, message: Message) -> bool:
        if not message.from_user:
            return False
        return message.from_user.id in settings.admin_ids


class IsOwner(BaseFilter):
    """Passes only for the chat owner."""

    async def __call__(self, message: Message) -> bool:
        if not message.chat or message.chat.type not in ("group", "supergroup"):
            return False
        try:
            member = await message.chat.get_member(message.from_user.id)
            return isinstance(member, ChatMemberOwner)
        except Exception:
            return False
