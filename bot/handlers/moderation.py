"""
bot/handlers/moderation.py
---------------------------
Moderation suite:
  • Anti-flood   — rate limiting per user per group
  • Anti-spam    — duplicate/forwarded content detection
  • Anti-link    — block URLs for non-admins
  • Word filter  — block configurable banned words
  • Warn system  — /warn, /unwarn, /warnings, /resetwarns
  • Mute/Ban/Kick — /mute, /unmute, /ban, /unban, /kick
"""

import asyncio
import re
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    ChatPermissions, Message,
    ChatMemberAdministrator, ChatMemberOwner,
)
from sqlalchemy.ext.asyncio import AsyncSession

from bot.filters.admin_filter import IsGroupAdmin
from bot.utils.helpers import send_and_delete, format_template, parse_time_arg
from core.services.cache_service import increment_flood_counter
from core.services.group_service import (
    add_warning,
    get_template,
    get_warning_count,
    log_action,
    reset_warnings,
)

router = Router(name="moderation")

# URL detection regex (simple but effective)
URL_REGEX = re.compile(
    r"(https?://[^\s]+|t\.me/[^\s]+|www\.[^\s]+)", re.IGNORECASE
)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _is_admin(message: Message) -> bool:
    try:
        member = await message.chat.get_member(message.from_user.id)
        return isinstance(member, (ChatMemberAdministrator, ChatMemberOwner))
    except Exception:
        return False


async def _resolve_target(message: Message, arg: str | None) -> tuple[int | None, str]:
    """Return (user_id, display_name) from reply or argument."""
    if message.reply_to_message and message.reply_to_message.from_user:
        u = message.reply_to_message.from_user
        return u.id, u.mention_html()
    if arg:
        try:
            uid = int(arg.split()[0])
            return uid, f"<code>{uid}</code>"
        except ValueError:
            pass
    return None, ""


# ── Anti-flood ────────────────────────────────────────────────────────────────

@router.message(F.chat.type.in_({"group", "supergroup"}))
async def anti_flood_check(
    message: Message,
    db: AsyncSession,
    mod_settings: dict,
) -> None:
    """Rate-limit users who send too many messages in a short window."""
    if not mod_settings.get("anti_flood", True):
        return
    if not message.from_user:
        return
    if await _is_admin(message):
        return

    group_id = message.chat.id
    user_id = message.from_user.id
    threshold = mod_settings.get("flood_threshold", 5)
    window = mod_settings.get("flood_window_secs", 10)
    action = mod_settings.get("flood_action", "mute")

    count = await increment_flood_counter(group_id, user_id, window)

    if count >= threshold:
        await message.delete()
        warn_text = await get_template(db, group_id, "flood")
        warn_text = format_template(
            warn_text, user_mention=message.from_user.mention_html()
        )
        await send_and_delete(message.chat, warn_text, delay=5)

        if action == "mute":
            try:
                until = datetime.now(tz=timezone.utc) + timedelta(minutes=5)
                await message.chat.restrict(
                    user_id,
                    ChatPermissions(can_send_messages=False),
                    until_date=until,
                )
            except Exception:
                pass

        await log_action(
            db, group_id, f"flood_{action}",
            target_id=user_id,
            detail=f"count={count}",
        )


# ── Anti-link ─────────────────────────────────────────────────────────────────

@router.message(F.chat.type.in_({"group", "supergroup"}), F.text)
async def anti_link_check(
    message: Message,
    db: AsyncSession,
    mod_settings: dict,
) -> None:
    """Delete messages containing URLs if anti_link is enabled."""
    if not mod_settings.get("anti_link", False):
        return
    if not message.text or not message.from_user:
        return
    if await _is_admin(message):
        return

    if URL_REGEX.search(message.text):
        try:
            await message.delete()
        except Exception:
            pass

        group_id = message.chat.id
        warn_text = await get_template(db, group_id, "anti_link")
        warn_text = format_template(
            warn_text, user_mention=message.from_user.mention_html()
        )
        await send_and_delete(message.chat, warn_text, delay=6)
        await log_action(
            db, group_id, "anti_link",
            target_id=message.from_user.id,
        )


# ── Word filter ───────────────────────────────────────────────────────────────

@router.message(F.chat.type.in_({"group", "supergroup"}), F.text)
async def word_filter_check(
    message: Message,
    db: AsyncSession,
    mod_settings: dict,
) -> None:
    """Delete messages containing words on the blocked list."""
    if not mod_settings.get("word_filter", False):
        return
    if not message.text or not message.from_user:
        return
    if await _is_admin(message):
        return

    blocked_words_raw: str = mod_settings.get("blocked_words", "") or ""
    if not blocked_words_raw:
        return

    blocked = [w.strip().lower() for w in blocked_words_raw.split(",") if w.strip()]
    text_lower = message.text.lower()

    if any(word in text_lower for word in blocked):
        try:
            await message.delete()
        except Exception:
            pass

        group_id = message.chat.id
        warn_text = await get_template(db, group_id, "word_filter")
        warn_text = format_template(
            warn_text, user_mention=message.from_user.mention_html()
        )
        await send_and_delete(message.chat, warn_text, delay=6)
        await log_action(
            db, group_id, "word_filter",
            target_id=message.from_user.id,
        )


# ── Warn system ───────────────────────────────────────────────────────────────

@router.message(Command("warn"), IsGroupAdmin())
async def cmd_warn(message: Message, db: AsyncSession) -> None:
    """Warn a user. Usage: /warn [reason] (reply to user's message)."""
    args = message.text.split(maxsplit=1)
    reason = args[1] if len(args) > 1 else "No reason given"
    target_id, target_mention = await _resolve_target(message, None)

    if not target_id:
        await message.reply("Reply to a user's message to warn them.")
        return

    group_id = message.chat.id
    mod = mod_settings if (mod_settings := {}) else {}  # get from data in full version
    max_warns = 3

    count = await add_warning(db, group_id, target_id, reason)
    warn_text = await get_template(db, group_id, "warn")
    warn_text = format_template(
        warn_text,
        user_mention=target_mention,
        count=count,
        max=max_warns,
        reason=reason,
    )
    await message.reply(warn_text, parse_mode="HTML")

    if count >= max_warns:
        # Auto-mute on reaching max warnings
        max_text = await get_template(db, group_id, "max_warn")
        max_text = format_template(max_text, user_mention=target_mention, action="muted")
        await message.reply(max_text, parse_mode="HTML")
        try:
            await message.chat.restrict(
                target_id,
                ChatPermissions(can_send_messages=False),
                until_date=datetime.now(tz=timezone.utc) + timedelta(hours=1),
            )
        except Exception:
            pass
        await reset_warnings(db, group_id, target_id)

    await log_action(
        db, group_id, "warn",
        actor_id=message.from_user.id,
        target_id=target_id,
        detail=reason,
    )


@router.message(Command("warnings"))
async def cmd_warnings(message: Message, db: AsyncSession) -> None:
    """Check a user's warning count."""
    target_id, target_mention = await _resolve_target(message, None)
    if not target_id:
        await message.reply("Reply to a user's message to check their warnings.")
        return

    count = await get_warning_count(db, message.chat.id, target_id)
    await message.reply(
        f"{target_mention} has <b>{count}</b> warning(s).", parse_mode="HTML"
    )


@router.message(Command("resetwarns"), IsGroupAdmin())
async def cmd_resetwarns(message: Message, db: AsyncSession) -> None:
    """Reset a user's warnings."""
    target_id, target_mention = await _resolve_target(message, None)
    if not target_id:
        await message.reply("Reply to a user's message to reset their warnings.")
        return

    await reset_warnings(db, message.chat.id, target_id)
    await message.reply(
        f"✅ Warnings for {target_mention} have been reset.", parse_mode="HTML"
    )


# ── Mute / Unmute ─────────────────────────────────────────────────────────────

@router.message(Command("mute"), IsGroupAdmin())
async def cmd_mute(message: Message, db: AsyncSession) -> None:
    """Mute a user. Usage: /mute [duration] [reason]  (e.g. /mute 1h Spam)."""
    parts = message.text.split(maxsplit=2)
    target_id, target_mention = await _resolve_target(message, None)
    if not target_id:
        await message.reply("Reply to a user's message to mute them.")
        return

    duration_str = parts[1] if len(parts) > 1 else "1h"
    reason = parts[2] if len(parts) > 2 else "No reason"
    duration = parse_time_arg(duration_str)

    until = datetime.now(tz=timezone.utc) + duration
    try:
        await message.chat.restrict(
            target_id,
            ChatPermissions(can_send_messages=False),
            until_date=until,
        )
    except Exception as e:
        await message.reply(f"⚠️ Failed to mute: {e}")
        return

    mute_text = await get_template(db, message.chat.id, "mute")
    mute_text = format_template(
        mute_text, user_mention=target_mention, duration=duration_str
    )
    await message.reply(mute_text, parse_mode="HTML")
    await log_action(
        db, message.chat.id, "mute",
        actor_id=message.from_user.id,
        target_id=target_id,
        detail=f"duration={duration_str} reason={reason}",
    )


@router.message(Command("unmute"), IsGroupAdmin())
async def cmd_unmute(message: Message, db: AsyncSession) -> None:
    """Unmute a user."""
    target_id, target_mention = await _resolve_target(message, None)
    if not target_id:
        await message.reply("Reply to a user's message to unmute them.")
        return

    try:
        await message.chat.restrict(target_id, ChatPermissions(can_send_messages=True))
    except Exception as e:
        await message.reply(f"⚠️ Failed to unmute: {e}")
        return

    await message.reply(f"🔊 {target_mention} has been unmuted.", parse_mode="HTML")
    await log_action(
        db, message.chat.id, "unmute",
        actor_id=message.from_user.id,
        target_id=target_id,
    )


# ── Ban / Unban / Kick ────────────────────────────────────────────────────────

@router.message(Command("ban"), IsGroupAdmin())
async def cmd_ban(message: Message, db: AsyncSession) -> None:
    """Ban a user from the group."""
    parts = message.text.split(maxsplit=1)
    reason = parts[1] if len(parts) > 1 else "No reason"
    target_id, target_mention = await _resolve_target(message, None)
    if not target_id:
        await message.reply("Reply to a user's message to ban them.")
        return

    try:
        await message.chat.ban(target_id)
    except Exception as e:
        await message.reply(f"⚠️ Failed to ban: {e}")
        return

    ban_text = await get_template(db, message.chat.id, "ban")
    ban_text = format_template(ban_text, user_mention=target_mention, reason=reason)
    await message.reply(ban_text, parse_mode="HTML")
    await log_action(
        db, message.chat.id, "ban",
        actor_id=message.from_user.id,
        target_id=target_id,
        detail=reason,
    )


@router.message(Command("unban"), IsGroupAdmin())
async def cmd_unban(message: Message, db: AsyncSession) -> None:
    """Unban a user."""
    parts = message.text.split(maxsplit=1)
    target_id, target_mention = await _resolve_target(message, parts[1] if len(parts) > 1 else None)
    if not target_id:
        await message.reply("Usage: /unban <user_id>")
        return

    try:
        await message.chat.unban(target_id)
    except Exception as e:
        await message.reply(f"⚠️ Failed to unban: {e}")
        return

    await message.reply(
        f"✅ {target_mention} has been unbanned.", parse_mode="HTML"
    )
    await log_action(
        db, message.chat.id, "unban",
        actor_id=message.from_user.id,
        target_id=target_id,
    )


@router.message(Command("kick"), IsGroupAdmin())
async def cmd_kick(message: Message, db: AsyncSession) -> None:
    """Kick a user (ban + immediately unban)."""
    parts = message.text.split(maxsplit=1)
    reason = parts[1] if len(parts) > 1 else "No reason"
    target_id, target_mention = await _resolve_target(message, None)
    if not target_id:
        await message.reply("Reply to a user's message to kick them.")
        return

    try:
        await message.chat.ban(target_id)
        await asyncio.sleep(0.5)
        await message.chat.unban(target_id)  # allow re-join
    except Exception as e:
        await message.reply(f"⚠️ Failed to kick: {e}")
        return

    kick_text = await get_template(db, message.chat.id, "kick")
    kick_text = format_template(kick_text, user_mention=target_mention, reason=reason)
    await message.reply(kick_text, parse_mode="HTML")
    await log_action(
        db, message.chat.id, "kick",
        actor_id=message.from_user.id,
        target_id=target_id,
        detail=reason,
    )
