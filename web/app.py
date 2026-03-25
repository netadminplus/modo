"""
web/app.py
----------
FastAPI web dashboard for the Telegram Management Bot.
Features:
  - Telegram Login Widget authentication
  - List of administered groups
  - Toggle switches for all moderation settings per group
  - Topic ACL management
  - Message template editor
  - Activity log viewer
"""

import hashlib
import hmac
import json
import secrets
import time
from typing import Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.models.database import (
    ActivityLog, Group, ModerationSettings, MessageTemplate,
    TopicACL, get_db,
)
from core.services.cache_service import (
    delete_session, get_session, set_session, invalidate_mod_settings,
    invalidate_topic_cache,
)
from core.services.group_service import (
    get_groups_for_admin, get_moderation_settings,
    get_template, set_template, update_moderation_setting,
    restrict_topic, unrestrict_topic, add_topic_user, remove_topic_user,
    get_all_restricted_topics, get_topic_allowed_users,
)

from web.lifespan import lifespan
from web.health import router as health_router

# ── FastAPI App ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="TG Bot Dashboard",
    description="Telegram Management Bot Web Dashboard",
    lifespan=lifespan,
    docs_url="/api/docs" if settings.debug else None,
)

app.include_router(health_router)

app.mount("/static", StaticFiles(directory="web/static"), name="static")
templates = Jinja2Templates(directory="web/templates")


# ── Auth helpers ──────────────────────────────────────────────────────────────

def verify_telegram_login(data: dict) -> bool:
    """
    Verify the Telegram Login Widget auth data.
    https://core.telegram.org/widgets/login#checking-authorization
    """
    auth_hash = data.pop("hash", None)
    if not auth_hash:
        return False

    # Build check string
    check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(data.items()) if v is not None
    )

    # HMAC-SHA256 with SHA256 of bot token as key
    secret_key = hashlib.sha256(settings.bot_token.encode()).digest()
    expected_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()

    # Check expiry (1 day)
    auth_date = int(data.get("auth_date", 0))
    if time.time() - auth_date > 86400:
        return False

    return hmac.compare_digest(expected_hash, auth_hash)


async def get_current_user(request: Request) -> Optional[dict]:
    """Return the current session user dict or None."""
    token = request.cookies.get("session_token")
    if not token:
        return None
    return await get_session(token)


async def require_user(request: Request) -> dict:
    """Dependency — redirect to login if not authenticated."""
    user = await get_current_user(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"},
        )
    return user


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(
        "auth/login.html",
        {
            "request": request,
            "bot_username": settings.bot_username,
            "domain": settings.domain,
        },
    )


@app.get("/auth/telegram")
async def telegram_auth_callback(request: Request):
    """Telegram Login Widget redirect — verify and set session."""
    data = dict(request.query_params)

    if not verify_telegram_login(dict(data)):  # pass a copy — modifies dict
        raise HTTPException(status_code=400, detail="Invalid Telegram auth data")

    user_data = {
        "id": int(data["id"]),
        "first_name": data.get("first_name", ""),
        "last_name": data.get("last_name", ""),
        "username": data.get("username", ""),
        "photo_url": data.get("photo_url", ""),
    }

    token = secrets.token_urlsafe(32)
    await set_session(token, user_data)

    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie("session_token", token, httponly=True, max_age=86400, samesite="lax")
    return response


@app.get("/logout")
async def logout(request: Request):
    token = request.cookies.get("session_token")
    if token:
        await delete_session(token)
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("session_token")
    return response


# ── Dashboard home ────────────────────────────────────────────────────────────

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_home(
    request: Request,
    user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Main dashboard — list of groups the user administers."""
    user_id = user["id"]

    # Super-admins see all groups
    if user_id in settings.admin_ids:
        from core.services.group_service import list_groups
        groups = await list_groups(db)
    else:
        groups = await get_groups_for_admin(db, user_id)

    return templates.TemplateResponse(
        "dashboard/home.html",
        {"request": request, "user": user, "groups": groups},
    )


# ── Group settings ────────────────────────────────────────────────────────────

@app.get("/dashboard/group/{group_id}", response_class=HTMLResponse)
async def group_settings_page(
    group_id: int,
    request: Request,
    user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Settings page for a specific group."""
    group = await _get_group_or_403(db, group_id, user)
    mod = await get_moderation_settings(db, group_id)
    templates_list = await _get_templates(db, group_id)
    restricted_topics = await get_all_restricted_topics(db, group_id)

    return templates.TemplateResponse(
        "dashboard/group_settings.html",
        {
            "request": request,
            "user": user,
            "group": group,
            "mod": mod,
            "templates": templates_list,
            "restricted_topics": restricted_topics,
        },
    )


@app.post("/api/group/{group_id}/settings")
async def update_group_settings(
    group_id: int,
    request: Request,
    user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """API endpoint to update moderation toggle switches."""
    await _get_group_or_403(db, group_id, user)
    body = await request.json()

    # Only allow known setting keys
    allowed_keys = {
        "anti_flood", "anti_spam", "anti_link", "word_filter",
        "captcha_enabled", "greet_new_members", "delete_join_messages",
        "delete_left_messages", "topic_acl_enabled",
        "flood_threshold", "flood_window_secs", "flood_action",
        "blocked_words", "max_warnings",
    }
    filtered = {k: v for k, v in body.items() if k in allowed_keys}

    await update_moderation_setting(db, group_id, **filtered)
    await invalidate_mod_settings(group_id)

    return JSONResponse({"status": "ok"})


# ── Template editor ───────────────────────────────────────────────────────────

@app.post("/api/group/{group_id}/template/{key}")
async def update_template(
    group_id: int,
    key: str,
    request: Request,
    user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a message template for a group."""
    await _get_group_or_403(db, group_id, user)
    body = await request.json()
    content = body.get("content", "")
    buttons_json = body.get("buttons_json", None)

    if not content:
        raise HTTPException(status_code=400, detail="Content is required")

    await set_template(db, group_id, key, content, buttons_json)
    return JSONResponse({"status": "ok"})


# ── Topic ACL management ──────────────────────────────────────────────────────

@app.get("/dashboard/group/{group_id}/topics", response_class=HTMLResponse)
async def topic_management_page(
    group_id: int,
    request: Request,
    user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Topic ACL management page."""
    group = await _get_group_or_403(db, group_id, user)
    restricted_topics = await get_all_restricted_topics(db, group_id)

    # Build a mapping of thread_id -> [allowed user ids]
    topic_users = {}
    for tid in restricted_topics:
        acls = await get_topic_allowed_users(db, group_id, tid)
        topic_users[tid] = [a.user_id for a in acls]

    return templates.TemplateResponse(
        "dashboard/topics.html",
        {
            "request": request,
            "user": user,
            "group": group,
            "restricted_topics": restricted_topics,
            "topic_users": topic_users,
        },
    )


@app.post("/api/group/{group_id}/topic/{thread_id}/restrict")
async def api_restrict_topic(
    group_id: int,
    thread_id: int,
    user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_group_or_403(db, group_id, user)
    await restrict_topic(db, group_id, thread_id)
    await invalidate_topic_cache(group_id, thread_id)
    return JSONResponse({"status": "restricted"})


@app.delete("/api/group/{group_id}/topic/{thread_id}/restrict")
async def api_unrestrict_topic(
    group_id: int,
    thread_id: int,
    user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_group_or_403(db, group_id, user)
    await unrestrict_topic(db, group_id, thread_id)
    await invalidate_topic_cache(group_id, thread_id)
    return JSONResponse({"status": "unrestricted"})


@app.post("/api/group/{group_id}/topic/{thread_id}/user/{user_id}")
async def api_add_topic_user(
    group_id: int,
    thread_id: int,
    user_id: int,
    user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_group_or_403(db, group_id, user)
    await add_topic_user(db, group_id, thread_id, user_id)
    await invalidate_topic_cache(group_id, thread_id)
    return JSONResponse({"status": "added"})


@app.delete("/api/group/{group_id}/topic/{thread_id}/user/{user_id}")
async def api_remove_topic_user(
    group_id: int,
    thread_id: int,
    user_id: int,
    user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_group_or_403(db, group_id, user)
    await remove_topic_user(db, group_id, thread_id, user_id)
    await invalidate_topic_cache(group_id, thread_id)
    return JSONResponse({"status": "removed"})


# ── Activity logs ─────────────────────────────────────────────────────────────

@app.get("/api/group/{group_id}/logs")
async def get_activity_logs(
    group_id: int,
    limit: int = 50,
    user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Return recent activity logs for a group as JSON."""
    await _get_group_or_403(db, group_id, user)
    result = await db.execute(
        select(ActivityLog)
        .where(ActivityLog.group_id == group_id)
        .order_by(ActivityLog.created_at.desc())
        .limit(min(limit, 200))
    )
    logs = result.scalars().all()
    return JSONResponse(
        [
            {
                "id": log.id,
                "action": log.action,
                "actor_id": log.actor_id,
                "target_id": log.target_id,
                "detail": log.detail,
                "thread_id": log.thread_id,
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ]
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _get_group_or_403(
    db: AsyncSession, group_id: int, user: dict
) -> Group:
    """Return the group or raise 403 if the user has no access."""
    result = await db.execute(select(Group).where(Group.id == group_id))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    # Super-admins bypass ownership check
    if user["id"] in settings.admin_ids:
        return group

    # Check user is admin of this group
    from core.models.database import GroupAdmin
    admin_result = await db.execute(
        select(GroupAdmin).where(
            GroupAdmin.group_id == group_id,
            GroupAdmin.user_id == user["id"],
        )
    )
    if not admin_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Access denied")

    return group


async def _get_templates(db: AsyncSession, group_id: int) -> list[MessageTemplate]:
    result = await db.execute(
        select(MessageTemplate).where(MessageTemplate.group_id == group_id)
    )
    return list(result.scalars().all())
