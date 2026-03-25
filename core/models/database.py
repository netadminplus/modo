"""
core/models/database.py
-----------------------
SQLAlchemy async ORM models for the Telegram Management Bot.
Covers Groups, Users, TopicACL, ModerationSettings, MessageTemplates, and Logs.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey, Integer,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.ext.asyncio import (
    AsyncAttrs, AsyncEngine, AsyncSession,
    async_sessionmaker, create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from core.config import settings


# ── Base ─────────────────────────────────────────────────────────────────────

class Base(AsyncAttrs, DeclarativeBase):
    """Shared declarative base with async attribute support."""
    pass


# ── Engine / Session factory ──────────────────────────────────────────────────

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:  # type: ignore[return]
    """FastAPI dependency — yields an async DB session."""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    """Create all tables (idempotent — safe to call on startup)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ── Models ────────────────────────────────────────────────────────────────────

class Group(Base):
    """Represents a Telegram group/supergroup managed by the bot."""
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram chat_id
    title: Mapped[str] = mapped_column(String(255))
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_forum: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    language: Mapped[str] = mapped_column(String(10), default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    moderation: Mapped[Optional["ModerationSettings"]] = relationship(
        back_populates="group", uselist=False, cascade="all, delete-orphan"
    )
    topic_acls: Mapped[list["TopicACL"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )
    templates: Mapped[list["MessageTemplate"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )
    admins: Mapped[list["GroupAdmin"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )
    activity_logs: Mapped[list["ActivityLog"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Group id={self.id} title={self.title!r}>"


class TelegramUser(Base):
    """Cached Telegram user profile."""
    __tablename__ = "telegram_users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram user_id
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    first_name: Mapped[str] = mapped_column(String(255))
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<TelegramUser id={self.id} username={self.username!r}>"


class GroupAdmin(Base):
    """Maps which Telegram users are admins of which groups (cached from API)."""
    __tablename__ = "group_admins"
    __table_args__ = (UniqueConstraint("group_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("groups.id", ondelete="CASCADE")
    )
    user_id: Mapped[int] = mapped_column(BigInteger)
    is_owner: Mapped[bool] = mapped_column(Boolean, default=False)
    can_manage_topics: Mapped[bool] = mapped_column(Boolean, default=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    group: Mapped["Group"] = relationship(back_populates="admins")


class TopicACL(Base):
    """
    Access Control List for Forum Topics.
    A row here means the topic is RESTRICTED — only listed users/admins may post.
    """
    __tablename__ = "topic_acls"
    __table_args__ = (UniqueConstraint("group_id", "thread_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("groups.id", ondelete="CASCADE")
    )
    thread_id: Mapped[int] = mapped_column(BigInteger)  # message_thread_id
    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True
    )  # NULL means "restrict the topic" (sentinel row)
    is_restricted: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    group: Mapped["Group"] = relationship(back_populates="topic_acls")

    def __repr__(self) -> str:
        return (
            f"<TopicACL group={self.group_id} thread={self.thread_id} "
            f"user={self.user_id}>"
        )


class ModerationSettings(Base):
    """Per-group toggle switches for all moderation features."""
    __tablename__ = "moderation_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("groups.id", ondelete="CASCADE"), unique=True
    )

    # Feature toggles
    anti_flood: Mapped[bool] = mapped_column(Boolean, default=True)
    anti_spam: Mapped[bool] = mapped_column(Boolean, default=True)
    anti_link: Mapped[bool] = mapped_column(Boolean, default=False)
    word_filter: Mapped[bool] = mapped_column(Boolean, default=False)
    captcha_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    greet_new_members: Mapped[bool] = mapped_column(Boolean, default=True)
    delete_join_messages: Mapped[bool] = mapped_column(Boolean, default=False)
    delete_left_messages: Mapped[bool] = mapped_column(Boolean, default=False)
    topic_acl_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Anti-flood parameters
    flood_threshold: Mapped[int] = mapped_column(Integer, default=5)  # msgs
    flood_window_secs: Mapped[int] = mapped_column(Integer, default=10)
    flood_action: Mapped[str] = mapped_column(
        String(20), default="mute"
    )  # mute | kick | ban

    # Blocked words (comma-separated)
    blocked_words: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Warning count before action
    max_warnings: Mapped[int] = mapped_column(Integer, default=3)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    group: Mapped["Group"] = relationship(back_populates="moderation")


class MessageTemplate(Base):
    """
    Editable message templates for every bot response.
    key examples: welcome, farewell, warn, mute, ban, captcha, topic_denied.
    """
    __tablename__ = "message_templates"
    __table_args__ = (UniqueConstraint("group_id", "key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("groups.id", ondelete="CASCADE")
    )
    key: Mapped[str] = mapped_column(String(50))
    content: Mapped[str] = mapped_column(Text)
    # JSON-encoded InlineKeyboard buttons: [[{"text": "...", "url": "..."}]]
    buttons_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    group: Mapped["Group"] = relationship(back_populates="templates")


class UserWarning(Base):
    """Tracks warnings issued to users within a group."""
    __tablename__ = "user_warnings"
    __table_args__ = (UniqueConstraint("group_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger)
    count: Mapped[int] = mapped_column(Integer, default=0)
    last_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ActivityLog(Base):
    """Audit log for all moderation actions."""
    __tablename__ = "activity_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("groups.id", ondelete="CASCADE")
    )
    actor_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    target_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    action: Mapped[str] = mapped_column(String(50))  # e.g., "topic_deny", "warn", "ban"
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    thread_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    group: Mapped["Group"] = relationship(back_populates="activity_logs")

    def __repr__(self) -> str:
        return f"<ActivityLog action={self.action!r} group={self.group_id}>"


class CaptchaPending(Base):
    """Tracks users who are pending captcha verification."""
    __tablename__ = "captcha_pending"
    __table_args__ = (UniqueConstraint("group_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger)
    challenge: Mapped[str] = mapped_column(String(20))  # The expected answer
    message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
