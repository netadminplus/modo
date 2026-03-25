"""Initial schema — all tables

Revision ID: 0001_initial
Revises:
Create Date: 2025-01-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # groups
    op.create_table(
        "groups",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("username", sa.String(100), nullable=True),
        sa.Column("is_forum", sa.Boolean(), default=False, nullable=False),
        sa.Column("is_active", sa.Boolean(), default=True, nullable=False),
        sa.Column("language", sa.String(10), default="en", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    # telegram_users
    op.create_table(
        "telegram_users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("username", sa.String(100), nullable=True),
        sa.Column("first_name", sa.String(255), nullable=False),
        sa.Column("last_name", sa.String(255), nullable=True),
        sa.Column("is_bot", sa.Boolean(), default=False, nullable=False),
        sa.Column("is_premium", sa.Boolean(), default=False, nullable=False),
        sa.Column("first_seen", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    # group_admins
    op.create_table(
        "group_admins",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("group_id", sa.BigInteger(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("is_owner", sa.Boolean(), default=False, nullable=False),
        sa.Column("can_manage_topics", sa.Boolean(), default=False, nullable=False),
        sa.Column("synced_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("group_id", "user_id"),
    )

    # topic_acls
    op.create_table(
        "topic_acls",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("group_id", sa.BigInteger(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("thread_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("is_restricted", sa.Boolean(), default=True, nullable=False),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("group_id", "thread_id", "user_id"),
    )
    op.create_index("ix_topic_acls_group_thread", "topic_acls", ["group_id", "thread_id"])

    # moderation_settings
    op.create_table(
        "moderation_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("group_id", sa.BigInteger(), sa.ForeignKey("groups.id", ondelete="CASCADE"), unique=True, nullable=False),
        sa.Column("anti_flood", sa.Boolean(), default=True, nullable=False),
        sa.Column("anti_spam", sa.Boolean(), default=True, nullable=False),
        sa.Column("anti_link", sa.Boolean(), default=False, nullable=False),
        sa.Column("word_filter", sa.Boolean(), default=False, nullable=False),
        sa.Column("captcha_enabled", sa.Boolean(), default=False, nullable=False),
        sa.Column("greet_new_members", sa.Boolean(), default=True, nullable=False),
        sa.Column("delete_join_messages", sa.Boolean(), default=False, nullable=False),
        sa.Column("delete_left_messages", sa.Boolean(), default=False, nullable=False),
        sa.Column("topic_acl_enabled", sa.Boolean(), default=True, nullable=False),
        sa.Column("flood_threshold", sa.Integer(), default=5, nullable=False),
        sa.Column("flood_window_secs", sa.Integer(), default=10, nullable=False),
        sa.Column("flood_action", sa.String(20), default="mute", nullable=False),
        sa.Column("blocked_words", sa.Text(), nullable=True),
        sa.Column("max_warnings", sa.Integer(), default=3, nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    # message_templates
    op.create_table(
        "message_templates",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("group_id", sa.BigInteger(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(50), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("buttons_json", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("group_id", "key"),
    )

    # user_warnings
    op.create_table(
        "user_warnings",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("group_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("count", sa.Integer(), default=0, nullable=False),
        sa.Column("last_reason", sa.String(255), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("group_id", "user_id"),
    )

    # activity_logs
    op.create_table(
        "activity_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("group_id", sa.BigInteger(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), nullable=True),
        sa.Column("target_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("thread_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_activity_logs_group_created", "activity_logs", ["group_id", "created_at"])

    # captcha_pending
    op.create_table(
        "captcha_pending",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("group_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("challenge", sa.String(20), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("group_id", "user_id"),
    )


def downgrade() -> None:
    op.drop_table("captcha_pending")
    op.drop_index("ix_activity_logs_group_created", "activity_logs")
    op.drop_table("activity_logs")
    op.drop_table("user_warnings")
    op.drop_table("message_templates")
    op.drop_table("moderation_settings")
    op.drop_index("ix_topic_acls_group_thread", "topic_acls")
    op.drop_table("topic_acls")
    op.drop_table("group_admins")
    op.drop_table("telegram_users")
    op.drop_table("groups")
