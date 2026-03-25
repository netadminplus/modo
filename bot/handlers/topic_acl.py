"""
bot/handlers/topic_acl.py
--------------------------
Topic Access Control List handler.

Flow for every message in a forum group:
  1. Check if the message has a thread_id (is in a topic).
  2. Check Redis cache → DB whether the topic is restricted.
  3. If restricted and user is not whitelisted / not an admin → delete + warn.

Admin commands:
  /restrict_topic        — mark the current topic as restricted
  /unrestrict_topic      — remove all restrictions from current topic
  /allow_user <user_id>  — whitelist a user in the current topic
  /deny_user  <user_id>  — remove a user from the whitelist
  /topic_users           — list whitelisted users for this topic
"""

import asyncio
from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import ChatMemberAdministrator, ChatMemberOwner, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.filters.admin_filter import IsGroupAdmin
from bot.utils.helpers import send_and_delete, format_template
from core.services.cache_service import (
    cache_topic_restricted,
    cache_user_topic_allowed,
    get_cached_topic_restricted,
    get_cached_user_topic_allowed,
    invalidate_topic_cache,
)
from core.services.group_service import (
    add_topic_user,
    get_topic_allowed_users,
    is_topic_restricted,
    is_user_allowed_in_topic,
    log_action,
    remove_topic_user,
    restrict_topic,
    unrestrict_topic,
    get_template,
)

router = Router(name="topic_acl")


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _is_admin(message: Message) -> bool:
    """Check if sender is a group admin via Telegram API."""
    try:
        member = await message.chat.get_member(message.from_user.id)
        return isinstance(member, (ChatMemberAdministrator, ChatMemberOwner))
    except Exception:
        return False


async def _resolve_user_id(message: Message, arg: Optional[str]) -> Optional[int]:
    """Resolve a user ID from command argument (numeric) or reply."""
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id
    if arg:
        try:
            return int(arg)
        except ValueError:
            return None
    return None


# ── Guard middleware (registered on this router) ──────────────────────────────

@router.message(F.chat.type.in_({"group", "supergroup"}))
async def topic_acl_guard(
    message: Message,
    db: AsyncSession,
    mod_settings: dict,
) -> None:
    """
    Main ACL guard — fires on EVERY message in a group.
    Deletes messages in restricted topics if the sender is not allowed.
    This handler is a "guard" so it must NOT block other handlers;
    it only acts and the router continues normally.
    """
    # Only relevant if group is a forum and message is in a topic
    thread_id = message.message_thread_id
    if not thread_id:
        return  # not in a topic

    # Check if topic ACL feature is enabled
    if not mod_settings.get("topic_acl_enabled", True):
        return

    group_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None
    if not user_id:
        return

    # ── Step 1: Is the topic restricted? (Cache → DB) ──────────────────────
    restricted = await get_cached_topic_restricted(group_id, thread_id)
    if restricted is None:
        restricted = await is_topic_restricted(db, group_id, thread_id)
        await cache_topic_restricted(group_id, thread_id, restricted)

    if not restricted:
        return  # open topic, nothing to do

    # ── Step 2: Is the user an admin? ──────────────────────────────────────
    if await _is_admin(message):
        return  # admins always allowed

    # ── Step 3: Is the user in the whitelist? (Cache → DB) ────────────────
    allowed = await get_cached_user_topic_allowed(group_id, thread_id, user_id)
    if allowed is None:
        allowed = await is_user_allowed_in_topic(db, group_id, thread_id, user_id)
        await cache_user_topic_allowed(group_id, thread_id, user_id, allowed)

    if allowed:
        return  # whitelisted

    # ── Step 4: Delete message and warn ───────────────────────────────────
    try:
        await message.delete()
    except Exception:
        pass  # may fail if bot lacks permissions

    # Fetch template
    warn_text = await get_template(db, group_id, "topic_denied")
    user_mention = (
        message.from_user.mention_html()
        if message.from_user
        else "User"
    )
    warn_text = format_template(
        warn_text, user_mention=user_mention, group_title=message.chat.title or ""
    )

    # Send self-deleting warning
    await send_and_delete(message.chat, warn_text, delay=8, thread_id=thread_id)

    # Log the denial
    await log_action(
        db,
        group_id=group_id,
        action="topic_deny",
        actor_id=None,
        target_id=user_id,
        detail=f"thread_id={thread_id}",
        thread_id=thread_id,
    )


# ── Admin Commands ────────────────────────────────────────────────────────────

@router.message(Command("restrict_topic"), IsGroupAdmin(), F.message_thread_id)
async def cmd_restrict_topic(message: Message, db: AsyncSession) -> None:
    """Mark the current topic as restricted (admins + whitelist only)."""
    group_id = message.chat.id
    thread_id = message.message_thread_id

    await restrict_topic(db, group_id, thread_id)
    await invalidate_topic_cache(group_id, thread_id)
    await log_action(
        db, group_id, "topic_restrict",
        actor_id=message.from_user.id,
        thread_id=thread_id,
    )
    reply = await message.reply(
        f"🔒 Topic <b>{thread_id}</b> is now <b>restricted</b>. "
        "Only admins and whitelisted users may post here.",
        parse_mode="HTML",
    )
    # Auto-delete admin confirmation after 10s
    asyncio.create_task(_delayed_delete(reply, 10))


@router.message(Command("unrestrict_topic"), IsGroupAdmin(), F.message_thread_id)
async def cmd_unrestrict_topic(message: Message, db: AsyncSession) -> None:
    """Remove all restrictions from the current topic."""
    group_id = message.chat.id
    thread_id = message.message_thread_id

    await unrestrict_topic(db, group_id, thread_id)
    await invalidate_topic_cache(group_id, thread_id)
    await log_action(
        db, group_id, "topic_unrestrict",
        actor_id=message.from_user.id,
        thread_id=thread_id,
    )
    reply = await message.reply(
        f"🔓 Topic <b>{thread_id}</b> is now <b>open</b> to everyone.",
        parse_mode="HTML",
    )
    asyncio.create_task(_delayed_delete(reply, 10))


@router.message(Command("allow_user"), IsGroupAdmin(), F.message_thread_id)
async def cmd_allow_user(message: Message, db: AsyncSession) -> None:
    """Whitelist a user in the current topic. Usage: /allow_user <user_id> or reply."""
    args = message.text.split(maxsplit=1)
    arg = args[1] if len(args) > 1 else None
    user_id = await _resolve_user_id(message, arg)

    if not user_id:
        await message.reply("Usage: /allow_user <user_id>  or reply to a message.")
        return

    group_id = message.chat.id
    thread_id = message.message_thread_id

    await add_topic_user(db, group_id, thread_id, user_id)
    await invalidate_topic_cache(group_id, thread_id)
    await log_action(
        db, group_id, "topic_allow_user",
        actor_id=message.from_user.id,
        target_id=user_id,
        thread_id=thread_id,
    )
    reply = await message.reply(
        f"✅ User <code>{user_id}</code> has been <b>whitelisted</b> in this topic.",
        parse_mode="HTML",
    )
    asyncio.create_task(_delayed_delete(reply, 10))


@router.message(Command("deny_user"), IsGroupAdmin(), F.message_thread_id)
async def cmd_deny_user(message: Message, db: AsyncSession) -> None:
    """Remove a user from the topic whitelist."""
    args = message.text.split(maxsplit=1)
    arg = args[1] if len(args) > 1 else None
    user_id = await _resolve_user_id(message, arg)

    if not user_id:
        await message.reply("Usage: /deny_user <user_id>  or reply to a message.")
        return

    group_id = message.chat.id
    thread_id = message.message_thread_id

    await remove_topic_user(db, group_id, thread_id, user_id)
    await invalidate_topic_cache(group_id, thread_id)
    await log_action(
        db, group_id, "topic_deny_user",
        actor_id=message.from_user.id,
        target_id=user_id,
        thread_id=thread_id,
    )
    reply = await message.reply(
        f"❌ User <code>{user_id}</code> has been <b>removed</b> from this topic's whitelist.",
        parse_mode="HTML",
    )
    asyncio.create_task(_delayed_delete(reply, 10))


@router.message(Command("topic_users"), IsGroupAdmin(), F.message_thread_id)
async def cmd_topic_users(message: Message, db: AsyncSession) -> None:
    """List all whitelisted users for the current topic."""
    group_id = message.chat.id
    thread_id = message.message_thread_id

    users = await get_topic_allowed_users(db, group_id, thread_id)
    is_restricted = await is_topic_restricted(db, group_id, thread_id)

    status = "🔒 Restricted" if is_restricted else "🔓 Open"
    if not users:
        user_list = "  <i>No users whitelisted yet.</i>"
    else:
        user_list = "\n".join(
            f"  • <code>{acl.user_id}</code>"
            + (f" — {acl.note}" if acl.note else "")
            for acl in users
        )

    await message.reply(
        f"<b>Topic {thread_id} — {status}</b>\n\n"
        f"<b>Whitelisted users:</b>\n{user_list}",
        parse_mode="HTML",
    )


# ── Utility ───────────────────────────────────────────────────────────────────

async def _delayed_delete(message: Message, delay: int) -> None:
    """Delete a message after `delay` seconds."""
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass
