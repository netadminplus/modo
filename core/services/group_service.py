"""
core/services/group_service.py
------------------------------
Database-level service layer for Group, TopicACL, and ModerationSettings.
All heavy DB logic lives here; handlers stay thin.
"""

from typing import Optional

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.models.database import (
    ActivityLog, Group, GroupAdmin, ModerationSettings,
    MessageTemplate, TopicACL, UserWarning,
)

# ── Default message templates ─────────────────────────────────────────────────

DEFAULT_TEMPLATES: dict[str, str] = {
    "welcome": (
        "👋 Welcome to {group_title}, {user_mention}!\n"
        "Please read the rules before posting."
    ),
    "farewell": "👋 {user_name} has left the group.",
    "topic_denied": (
        "🚫 {user_mention}, you are not allowed to post in this topic.\n"
        "Your message has been removed."
    ),
    "warn": (
        "⚠️ {user_mention}, you have received a warning ({count}/{max}).\n"
        "Reason: {reason}"
    ),
    "max_warn": (
        "🔨 {user_mention} has reached the maximum warning count and has been {action}."
    ),
    "flood": "🌊 {user_mention}, please slow down! You are sending messages too fast.",
    "anti_link": "🔗 {user_mention}, links are not allowed in this group.",
    "word_filter": "🤬 {user_mention}, your message contained a banned word.",
    "captcha_prompt": (
        "🤖 Welcome {user_mention}! Please solve this to verify you're human:\n\n"
        "What is {a} + {b}?"
    ),
    "captcha_success": "✅ {user_mention}, verification successful! Welcome.",
    "captcha_fail": "❌ {user_mention}, wrong answer. Please try again.",
    "mute": "🔇 {user_mention} has been muted for {duration}.",
    "ban": "🔨 {user_mention} has been banned. Reason: {reason}",
    "kick": "👢 {user_mention} has been kicked. Reason: {reason}",
}


# ── Group CRUD ────────────────────────────────────────────────────────────────

async def get_or_create_group(
    session: AsyncSession,
    chat_id: int,
    title: str,
    is_forum: bool = False,
    username: Optional[str] = None,
) -> Group:
    """Fetch existing group or create it with default settings."""
    result = await session.execute(
        select(Group)
        .options(selectinload(Group.moderation))
        .where(Group.id == chat_id)
    )
    group = result.scalar_one_or_none()

    if group is None:
        group = Group(
            id=chat_id,
            title=title,
            username=username,
            is_forum=is_forum,
        )
        session.add(group)
        await session.flush()  # get group.id before creating related rows

        # Create default moderation settings
        mod = ModerationSettings(group_id=chat_id)
        session.add(mod)

        # Seed default message templates
        for key, content in DEFAULT_TEMPLATES.items():
            session.add(MessageTemplate(group_id=chat_id, key=key, content=content))

        await session.commit()
        await session.refresh(group)
    else:
        # Update metadata if it changed
        group.title = title
        if username:
            group.username = username
        group.is_forum = is_forum
        await session.commit()

    return group


async def get_group(session: AsyncSession, chat_id: int) -> Optional[Group]:
    """Return group with moderation settings loaded."""
    result = await session.execute(
        select(Group)
        .options(selectinload(Group.moderation))
        .where(Group.id == chat_id)
    )
    return result.scalar_one_or_none()


async def list_groups(session: AsyncSession) -> list[Group]:
    """Return all active groups."""
    result = await session.execute(
        select(Group).where(Group.is_active.is_(True)).order_by(Group.title)
    )
    return list(result.scalars().all())


async def get_groups_for_admin(
    session: AsyncSession, user_id: int
) -> list[Group]:
    """Return groups where user_id is a registered admin."""
    result = await session.execute(
        select(Group)
        .join(GroupAdmin, GroupAdmin.group_id == Group.id)
        .where(GroupAdmin.user_id == user_id, Group.is_active.is_(True))
        .order_by(Group.title)
    )
    return list(result.scalars().all())


# ── Topic ACL ─────────────────────────────────────────────────────────────────

async def is_topic_restricted(
    session: AsyncSession, group_id: int, thread_id: int
) -> bool:
    """Return True if the topic has at least one restriction sentinel row."""
    result = await session.execute(
        select(TopicACL).where(
            TopicACL.group_id == group_id,
            TopicACL.thread_id == thread_id,
            TopicACL.user_id.is_(None),   # sentinel: NULL user_id = topic is restricted
            TopicACL.is_restricted.is_(True),
        )
    )
    return result.scalar_one_or_none() is not None


async def is_user_allowed_in_topic(
    session: AsyncSession, group_id: int, thread_id: int, user_id: int
) -> bool:
    """Return True if user_id is explicitly whitelisted in the topic."""
    result = await session.execute(
        select(TopicACL).where(
            TopicACL.group_id == group_id,
            TopicACL.thread_id == thread_id,
            TopicACL.user_id == user_id,
        )
    )
    return result.scalar_one_or_none() is not None


async def restrict_topic(
    session: AsyncSession, group_id: int, thread_id: int
) -> None:
    """Mark a topic as restricted (create sentinel row if not exists)."""
    existing = await session.execute(
        select(TopicACL).where(
            TopicACL.group_id == group_id,
            TopicACL.thread_id == thread_id,
            TopicACL.user_id.is_(None),
        )
    )
    if not existing.scalar_one_or_none():
        session.add(
            TopicACL(group_id=group_id, thread_id=thread_id, user_id=None, is_restricted=True)
        )
        await session.commit()


async def unrestrict_topic(
    session: AsyncSession, group_id: int, thread_id: int
) -> None:
    """Remove all ACL rows for a topic (makes it public again)."""
    await session.execute(
        delete(TopicACL).where(
            TopicACL.group_id == group_id,
            TopicACL.thread_id == thread_id,
        )
    )
    await session.commit()


async def add_topic_user(
    session: AsyncSession,
    group_id: int,
    thread_id: int,
    user_id: int,
    note: Optional[str] = None,
) -> TopicACL:
    """Whitelist a user for a specific topic."""
    existing = await session.execute(
        select(TopicACL).where(
            TopicACL.group_id == group_id,
            TopicACL.thread_id == thread_id,
            TopicACL.user_id == user_id,
        )
    )
    acl = existing.scalar_one_or_none()
    if not acl:
        acl = TopicACL(
            group_id=group_id, thread_id=thread_id,
            user_id=user_id, note=note
        )
        session.add(acl)
        await session.commit()
    return acl


async def remove_topic_user(
    session: AsyncSession, group_id: int, thread_id: int, user_id: int
) -> None:
    """Remove a user from the whitelist of a topic."""
    await session.execute(
        delete(TopicACL).where(
            TopicACL.group_id == group_id,
            TopicACL.thread_id == thread_id,
            TopicACL.user_id == user_id,
        )
    )
    await session.commit()


async def get_topic_allowed_users(
    session: AsyncSession, group_id: int, thread_id: int
) -> list[TopicACL]:
    """List all whitelisted users for a given topic."""
    result = await session.execute(
        select(TopicACL).where(
            TopicACL.group_id == group_id,
            TopicACL.thread_id == thread_id,
            TopicACL.user_id.isnot(None),
        )
    )
    return list(result.scalars().all())


async def get_all_restricted_topics(
    session: AsyncSession, group_id: int
) -> list[int]:
    """Return list of thread_ids that are restricted in a group."""
    result = await session.execute(
        select(TopicACL.thread_id).where(
            TopicACL.group_id == group_id,
            TopicACL.user_id.is_(None),
            TopicACL.is_restricted.is_(True),
        )
    )
    return [row[0] for row in result.all()]


# ── Moderation Settings ───────────────────────────────────────────────────────

async def get_moderation_settings(
    session: AsyncSession, group_id: int
) -> Optional[ModerationSettings]:
    """Return moderation settings for a group."""
    result = await session.execute(
        select(ModerationSettings).where(ModerationSettings.group_id == group_id)
    )
    return result.scalar_one_or_none()


async def update_moderation_setting(
    session: AsyncSession, group_id: int, **kwargs
) -> None:
    """Bulk-update one or more fields in ModerationSettings."""
    await session.execute(
        update(ModerationSettings)
        .where(ModerationSettings.group_id == group_id)
        .values(**kwargs)
    )
    await session.commit()


# ── Message Templates ─────────────────────────────────────────────────────────

async def get_template(
    session: AsyncSession, group_id: int, key: str
) -> Optional[str]:
    """Return the content of a message template by key."""
    result = await session.execute(
        select(MessageTemplate.content).where(
            MessageTemplate.group_id == group_id,
            MessageTemplate.key == key,
        )
    )
    row = result.scalar_one_or_none()
    return row if row else DEFAULT_TEMPLATES.get(key, "")


async def set_template(
    session: AsyncSession, group_id: int, key: str, content: str,
    buttons_json: Optional[str] = None,
) -> None:
    """Create or update a message template."""
    existing = await session.execute(
        select(MessageTemplate).where(
            MessageTemplate.group_id == group_id,
            MessageTemplate.key == key,
        )
    )
    tmpl = existing.scalar_one_or_none()
    if tmpl:
        tmpl.content = content
        tmpl.buttons_json = buttons_json
    else:
        session.add(
            MessageTemplate(
                group_id=group_id, key=key,
                content=content, buttons_json=buttons_json,
            )
        )
    await session.commit()


# ── Warnings ──────────────────────────────────────────────────────────────────

async def add_warning(
    session: AsyncSession, group_id: int, user_id: int, reason: str = ""
) -> int:
    """Increment warning count and return new total."""
    result = await session.execute(
        select(UserWarning).where(
            UserWarning.group_id == group_id,
            UserWarning.user_id == user_id,
        )
    )
    warn = result.scalar_one_or_none()
    if warn:
        warn.count += 1
        warn.last_reason = reason
    else:
        warn = UserWarning(group_id=group_id, user_id=user_id, count=1, last_reason=reason)
        session.add(warn)
    await session.commit()
    return warn.count


async def reset_warnings(
    session: AsyncSession, group_id: int, user_id: int
) -> None:
    """Reset warning counter for a user in a group."""
    await session.execute(
        delete(UserWarning).where(
            UserWarning.group_id == group_id,
            UserWarning.user_id == user_id,
        )
    )
    await session.commit()


async def get_warning_count(
    session: AsyncSession, group_id: int, user_id: int
) -> int:
    """Return current warning count for a user."""
    result = await session.execute(
        select(UserWarning.count).where(
            UserWarning.group_id == group_id,
            UserWarning.user_id == user_id,
        )
    )
    return result.scalar_one_or_none() or 0


# ── Admin sync ────────────────────────────────────────────────────────────────

async def sync_group_admins(
    session: AsyncSession,
    group_id: int,
    admins: list[dict],
) -> None:
    """
    Replace stored admin list for a group.
    admins: list of dicts with keys: user_id, is_owner, can_manage_topics
    """
    await session.execute(
        delete(GroupAdmin).where(GroupAdmin.group_id == group_id)
    )
    for a in admins:
        session.add(
            GroupAdmin(
                group_id=group_id,
                user_id=a["user_id"],
                is_owner=a.get("is_owner", False),
                can_manage_topics=a.get("can_manage_topics", False),
            )
        )
    await session.commit()


# ── Activity Logging ──────────────────────────────────────────────────────────

async def log_action(
    session: AsyncSession,
    group_id: int,
    action: str,
    actor_id: Optional[int] = None,
    target_id: Optional[int] = None,
    detail: Optional[str] = None,
    thread_id: Optional[int] = None,
) -> None:
    """Append a moderation action to the activity log."""
    session.add(
        ActivityLog(
            group_id=group_id,
            action=action,
            actor_id=actor_id,
            target_id=target_id,
            detail=detail,
            thread_id=thread_id,
        )
    )
    await session.commit()
