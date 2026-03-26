"""
bot/handlers/group_setup.py
----------------------------
Handles the bot being added to or removed from a group.
On join: registers the group in DB, syncs admins, sends a setup greeting.
On removal: marks the group as inactive.
"""

import logging

from aiogram import F, Router
from aiogram.filters import IS_MEMBER, IS_NOT_MEMBER, ChatMemberUpdatedFilter, Command
from aiogram.types import ChatMemberUpdated, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.filters.admin_filter import IsGroupAdmin
from core.services.group_service import get_or_create_group
from core.utils.admin_sync import sync_admins_for_group

print("!!! group_setup.py MODULE LOADED !!!")

router = Router(name="group_setup")
logger = logging.getLogger(__name__)

print(f"!!! group_setup router created with {len(router.handlers)} handlers")

# Startup message handler - very specific command
@router.command("startuptest")
async def startup_test(message: Message) -> None:
    """Test handler to verify module is loaded."""
    print("!!! STARTUP_TEST HANDLER CALLED !!!")
    await message.reply("✅ Module loaded! Test successful.")


@router.my_chat_member(
    ChatMemberUpdatedFilter(member_status_changed=IS_MEMBER)
)
async def bot_added_to_group(event: ChatMemberUpdated, db: AsyncSession) -> None:
    """
    Fires when the bot is added to (or promoted in) a group.
    Registers the group and syncs the admin list.
    """
    chat = event.chat
    if chat.type not in ("group", "supergroup"):
        return

    logger.info("Bot added to group: %s (%d)", chat.title, chat.id)

    # Register group in DB (creates default settings + templates)
    group = await get_or_create_group(
        db,
        chat_id=chat.id,
        title=chat.title or "Unknown",
        is_forum=bool(getattr(chat, "is_forum", False)),
        username=chat.username,
    )

    # Sync admin list
    from bot.main import bot
    await sync_admins_for_group(bot, db, chat.id)

    # Send a greeting message
    try:
        await event.bot.send_message(
            chat.id,
            "👋 <b>Hi! I'm your Group Manager Bot.</b>\n\n"
            "I'm now ready to help you manage this group.\n\n"
            "📌 <b>Quick start:</b>\n"
            "• <code>/settings</code> — Open the web dashboard\n"
            "• <code>/restrict_topic</code> — Restrict a forum topic\n"
            "• <code>/warn</code> <i>(reply)</i> — Warn a user\n\n"
            "Make sure I'm an admin with enough permissions to delete messages!",
            parse_mode="HTML",
        )
    except Exception:
        pass  # Can't send if bot lacks permission


@router.my_chat_member(
    ChatMemberUpdatedFilter(member_status_changed=IS_NOT_MEMBER)
)
async def bot_removed_from_group(event: ChatMemberUpdated, db: AsyncSession) -> None:
    """Mark the group as inactive when the bot is removed."""
    chat = event.chat
    if chat.type not in ("group", "supergroup"):
        return

    logger.info("Bot removed from group: %s (%d)", chat.title, chat.id)

    from sqlalchemy import update
    from core.models.database import Group

    await db.execute(
        update(Group).where(Group.id == chat.id).values(is_active=False)
    )
    await db.commit()


@router.message(Command("register"), IsGroupAdmin())
async def register_group(message: Message, db: AsyncSession) -> None:
    """
    Manually register the current group (fallback if bot missed the join event).
    Only works in groups, only admins can use it.
    """
    chat = message.chat
    logger.info("Received /register command in: %s (%d) type=%s", chat.title, chat.id, chat.type)
    
    if chat.type not in ("group", "supergroup"):
        logger.warning("/register used in non-group chat: %s", chat.type)
        return  # Silently ignore in private chats
    
    logger.info("Manually registering group: %s (%d)", chat.title, chat.id)

    # Register group in DB
    group = await get_or_create_group(
        db,
        chat_id=chat.id,
        title=chat.title or "Unknown",
        is_forum=bool(getattr(chat, "is_forum", False)),
        username=chat.username,
    )

    # Sync admin list
    from bot.main import bot
    await sync_admins_for_group(bot, db, chat.id)

    # Try to send confirmation in group, fallback to private message
    try:
        await message.reply(
            f"✅ <b>Group registered!</b>\n\n"
            f"Title: {chat.title}\n"
            f"ID: <code>{chat.id}</code>\n\n"
            "It should now appear in your web dashboard.",
            parse_mode="HTML",
        )
        logger.info("Sent confirmation in group")
    except Exception as e:
        # Can't send in group, send via private message
        logger.warning("Could not send confirmation in group %s: %s", chat.id, str(e))
        try:
            await message.answer(
                "✅ Group registered! Check your dashboard.",
                parse_mode="HTML",
            )
            logger.info("Sent confirmation via DM")
        except Exception as e2:
            logger.error("Could not send confirmation via DM: %s", str(e2))
            pass  # Give up silently
