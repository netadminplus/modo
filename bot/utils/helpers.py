"""
bot/utils/helpers.py
---------------------
Shared utility functions used across handlers.
"""

import asyncio
from datetime import timedelta
from typing import Optional

from aiogram.types import Chat, Message


def format_template(text: str, **kwargs) -> str:
    """
    Replace {placeholder} tokens in a template string.
    Safe — unknown placeholders are left as-is.
    """
    for key, value in kwargs.items():
        text = text.replace(f"{{{key}}}", str(value))
    return text


async def send_and_delete(
    chat: Chat,
    text: str,
    delay: int = 8,
    thread_id: Optional[int] = None,
    parse_mode: str = "HTML",
) -> None:
    """Send a message then delete it after `delay` seconds."""
    try:
        kwargs: dict = {"parse_mode": parse_mode}
        if thread_id:
            kwargs["message_thread_id"] = thread_id
        sent: Message = await chat.bot.send_message(chat.id, text, **kwargs)
        asyncio.create_task(_delete_after(sent, delay))
    except Exception:
        pass


async def _delete_after(message: Message, delay: int) -> None:
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass


def parse_time_arg(arg: str) -> timedelta:
    """
    Parse a time string like '1h', '30m', '1d', '7d' into a timedelta.
    Defaults to 1 hour on failure.
    """
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    arg = arg.strip().lower()
    if arg and arg[-1] in units:
        try:
            return timedelta(seconds=int(arg[:-1]) * units[arg[-1]])
        except ValueError:
            pass
    return timedelta(hours=1)  # default


def human_readable_duration(td: timedelta) -> str:
    """Convert a timedelta to a human-readable string."""
    total = int(td.total_seconds())
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m"
    if total < 86400:
        return f"{total // 3600}h"
    return f"{total // 86400}d"
