"""
bot/handlers/welcome.py
-----------------------
Handles new member greetings, captcha verification, and
service message cleanup (join/left notifications).
"""

import asyncio
import random
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery, ChatPermissions, InlineKeyboardButton,
    InlineKeyboardMarkup, Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from bot.filters.admin_filter import IsGroupAdmin
from bot.utils.helpers import format_template, send_and_delete
from core.services.cache_service import (
    delete_captcha_state,
    get_captcha_state,
    set_captcha_state,
)
from core.services.group_service import get_template, log_action

router = Router(name="welcome")


# ── New member handler ────────────────────────────────────────────────────────

@router.message(F.new_chat_members)
async def on_new_member(
    message: Message,
    db: AsyncSession,
    mod_settings: dict,
) -> None:
    """
    Fires when one or more users join the group.
    1. Optionally delete the service message.
    2. If captcha is enabled, restrict user and send challenge.
    3. Otherwise send the welcome message.
    """
    group_id = message.chat.id

    # ── Delete service join message if configured ─────────────────────────
    if mod_settings.get("delete_join_messages", False):
        try:
            await message.delete()
        except Exception:
            pass
        return  # don't greet if we deleted the service message

    for new_user in message.new_chat_members:
        if new_user.is_bot:
            continue  # Skip bots

        user_mention = new_user.mention_html()

        if mod_settings.get("captcha_enabled", False):
            # Restrict user until they solve captcha
            try:
                await message.chat.restrict(
                    new_user.id,
                    ChatPermissions(can_send_messages=False),
                )
            except Exception:
                pass

            # Generate captcha challenge
            a, b = random.randint(1, 20), random.randint(1, 20)
            answer = str(a + b)

            await set_captcha_state(group_id, new_user.id, answer)

            captcha_text = await get_template(db, group_id, "captcha_prompt")
            captcha_text = format_template(
                captcha_text,
                user_mention=user_mention,
                a=a,
                b=b,
            )

            # Inline buttons for answer choices (±3 distractors)
            choices = list({answer, str(a + b + 1), str(a + b - 1), str(a + b + 2)})
            random.shuffle(choices)
            buttons = [
                [
                    InlineKeyboardButton(
                        text=choice,
                        callback_data=f"captcha:{group_id}:{new_user.id}:{choice}",
                    )
                    for choice in choices
                ]
            ]
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

            sent = await message.answer(captcha_text, parse_mode="HTML", reply_markup=keyboard)

            # Auto-kick if not solved in 5 minutes
            asyncio.create_task(
                _captcha_timeout(message.chat.id, new_user.id, sent.message_id, 300)
            )

            await log_action(
                db, group_id, "captcha_sent", target_id=new_user.id
            )

        elif mod_settings.get("greet_new_members", True):
            # Send welcome message
            welcome_text = await get_template(db, group_id, "welcome")
            welcome_text = format_template(
                welcome_text,
                user_mention=user_mention,
                group_title=message.chat.title or "",
            )
            await message.answer(welcome_text, parse_mode="HTML")
            await log_action(
                db, group_id, "welcome_sent", target_id=new_user.id
            )


# ── Captcha callback ──────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("captcha:"))
async def on_captcha_answer(
    callback: CallbackQuery,
    db: AsyncSession,
) -> None:
    """Handle captcha button press."""
    _, group_id_str, user_id_str, chosen = callback.data.split(":", 3)
    group_id = int(group_id_str)
    user_id = int(user_id_str)

    # Only the challenged user can answer
    if callback.from_user.id != user_id:
        await callback.answer("This captcha is not for you!", show_alert=True)
        return

    state = await get_captcha_state(group_id, user_id)
    if not state:
        await callback.answer("Captcha expired.", show_alert=True)
        return

    if chosen == state["answer"]:
        # Correct — lift restriction
        try:
            await callback.message.chat.restrict(
                user_id,
                ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                ),
            )
        except Exception:
            pass

        success_text = await get_template(db, group_id, "captcha_success")
        success_text = format_template(
            success_text,
            user_mention=callback.from_user.mention_html(),
        )
        await callback.message.edit_text(success_text, parse_mode="HTML")
        await delete_captcha_state(group_id, user_id)
        await log_action(db, group_id, "captcha_pass", target_id=user_id)
    else:
        fail_text = await get_template(db, group_id, "captcha_fail")
        fail_text = format_template(
            fail_text,
            user_mention=callback.from_user.mention_html(),
        )
        await callback.answer(fail_text.replace("<b>", "").replace("</b>", ""), show_alert=True)
        await log_action(db, group_id, "captcha_fail", target_id=user_id)


# ── Member left ───────────────────────────────────────────────────────────────

@router.message(F.left_chat_member)
async def on_member_left(
    message: Message,
    db: AsyncSession,
    mod_settings: dict,
) -> None:
    """Handle service message for user leaving."""
    if mod_settings.get("delete_left_messages", False):
        try:
            await message.delete()
        except Exception:
            pass
        return

    group_id = message.chat.id
    left_user = message.left_chat_member
    farewell_text = await get_template(db, group_id, "farewell")
    farewell_text = format_template(
        farewell_text,
        user_name=left_user.full_name,
        group_title=message.chat.title or "",
    )
    sent = await message.answer(farewell_text, parse_mode="HTML")
    # Auto-delete farewell after 30 seconds
    asyncio.create_task(_delayed_delete(sent, 30))


# ── Settings command ──────────────────────────────────────────────────────────

@router.message(Command("settings"), IsGroupAdmin())
async def cmd_settings(message: Message) -> None:
    """Show link to the web dashboard for this group."""
    from core.config import settings as cfg
    dashboard_url = f"https://{cfg.domain}/dashboard/group/{message.chat.id}"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="⚙️ Open Web Dashboard",
                url=dashboard_url,
            )
        ]]
    )
    await message.reply(
        "🔧 Manage all settings for this group in the Web Dashboard:",
        reply_markup=keyboard,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _delayed_delete(message: Message, delay: int) -> None:
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass


async def _captcha_timeout(
    chat_id: int, user_id: int, msg_id: int, timeout: int
) -> None:
    """Kick user if they haven't solved the captcha within timeout seconds."""
    await asyncio.sleep(timeout)
    state = await get_captcha_state(chat_id, user_id)
    if state:
        from aiogram import Bot
        # We need the bot instance; import lazily to avoid circular imports
        try:
            from bot.main import bot  # set during startup
            await bot.ban_chat_member(chat_id, user_id)
            await asyncio.sleep(1)
            await bot.unban_chat_member(chat_id, user_id)
            await bot.delete_message(chat_id, msg_id)
        except Exception:
            pass
        await delete_captcha_state(chat_id, user_id)
