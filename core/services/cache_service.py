"""
core/services/cache_service.py
------------------------------
Redis-backed caching layer.
Handles: anti-flood counters, captcha state, ACL caching, session tokens.
"""

import json
from typing import Any, Optional

import redis.asyncio as aioredis

from core.config import settings

# ── Redis pool ────────────────────────────────────────────────────────────────

_redis: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    """Return (and lazily initialise) the global async Redis client."""
    global _redis
    if _redis is None:
        _redis = await aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis


async def close_redis() -> None:
    """Close the Redis connection pool (call on shutdown)."""
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


# ── Anti-flood ────────────────────────────────────────────────────────────────

async def increment_flood_counter(
    group_id: int,
    user_id: int,
    window_secs: int,
) -> int:
    """
    Increment message counter for user within the flood window.
    Returns the current count AFTER increment.
    Uses a sliding-window approach with Redis INCR + EXPIRE.
    """
    redis = await get_redis()
    key = f"flood:{group_id}:{user_id}"
    pipe = redis.pipeline()
    pipe.incr(key)
    pipe.expire(key, window_secs)
    results = await pipe.execute()
    return results[0]  # current count


async def reset_flood_counter(group_id: int, user_id: int) -> None:
    redis = await get_redis()
    await redis.delete(f"flood:{group_id}:{user_id}")


# ── Topic ACL cache ───────────────────────────────────────────────────────────

TOPIC_ACL_TTL = 300  # 5 minutes


async def cache_topic_restricted(
    group_id: int, thread_id: int, is_restricted: bool
) -> None:
    redis = await get_redis()
    key = f"topic_restricted:{group_id}:{thread_id}"
    await redis.set(key, "1" if is_restricted else "0", ex=TOPIC_ACL_TTL)


async def get_cached_topic_restricted(
    group_id: int, thread_id: int
) -> Optional[bool]:
    """Return None if not cached, else True/False."""
    redis = await get_redis()
    val = await redis.get(f"topic_restricted:{group_id}:{thread_id}")
    if val is None:
        return None
    return val == "1"


async def cache_user_topic_allowed(
    group_id: int, thread_id: int, user_id: int, allowed: bool
) -> None:
    redis = await get_redis()
    key = f"topic_allowed:{group_id}:{thread_id}:{user_id}"
    await redis.set(key, "1" if allowed else "0", ex=TOPIC_ACL_TTL)


async def get_cached_user_topic_allowed(
    group_id: int, thread_id: int, user_id: int
) -> Optional[bool]:
    redis = await get_redis()
    val = await redis.get(f"topic_allowed:{group_id}:{thread_id}:{user_id}")
    if val is None:
        return None
    return val == "1"


async def invalidate_topic_cache(group_id: int, thread_id: int) -> None:
    """Call this after any ACL change to force fresh DB lookups."""
    redis = await get_redis()
    pattern = f"topic_*:{group_id}:{thread_id}*"
    # Use SCAN to avoid blocking KEYS in production
    async for key in redis.scan_iter(match=pattern):
        await redis.delete(key)


# ── Moderation settings cache ─────────────────────────────────────────────────

MOD_SETTINGS_TTL = 600  # 10 minutes


async def cache_mod_settings(group_id: int, settings_dict: dict) -> None:
    redis = await get_redis()
    await redis.set(
        f"mod_settings:{group_id}",
        json.dumps(settings_dict),
        ex=MOD_SETTINGS_TTL,
    )


async def get_cached_mod_settings(group_id: int) -> Optional[dict]:
    redis = await get_redis()
    raw = await redis.get(f"mod_settings:{group_id}")
    return json.loads(raw) if raw else None


async def invalidate_mod_settings(group_id: int) -> None:
    redis = await get_redis()
    await redis.delete(f"mod_settings:{group_id}")


# ── Captcha state ─────────────────────────────────────────────────────────────

CAPTCHA_TTL = 300  # 5 minutes


async def set_captcha_state(
    group_id: int, user_id: int, answer: str, message_id: Optional[int] = None
) -> None:
    redis = await get_redis()
    data = json.dumps({"answer": answer, "message_id": message_id})
    await redis.set(f"captcha:{group_id}:{user_id}", data, ex=CAPTCHA_TTL)


async def get_captcha_state(
    group_id: int, user_id: int
) -> Optional[dict]:
    redis = await get_redis()
    raw = await redis.get(f"captcha:{group_id}:{user_id}")
    return json.loads(raw) if raw else None


async def delete_captcha_state(group_id: int, user_id: int) -> None:
    redis = await get_redis()
    await redis.delete(f"captcha:{group_id}:{user_id}")


# ── Dashboard session tokens ──────────────────────────────────────────────────

SESSION_TTL = 86_400  # 24 hours


async def set_session(token: str, user_data: dict) -> None:
    redis = await get_redis()
    await redis.set(f"session:{token}", json.dumps(user_data), ex=SESSION_TTL)


async def get_session(token: str) -> Optional[dict]:
    redis = await get_redis()
    raw = await redis.get(f"session:{token}")
    return json.loads(raw) if raw else None


async def delete_session(token: str) -> None:
    redis = await get_redis()
    await redis.delete(f"session:{token}")


# ── Generic helpers ───────────────────────────────────────────────────────────

async def set_key(key: str, value: Any, ttl: Optional[int] = None) -> None:
    redis = await get_redis()
    if isinstance(value, (dict, list)):
        value = json.dumps(value)
    await redis.set(key, value, ex=ttl)


async def get_key(key: str) -> Optional[str]:
    redis = await get_redis()
    return await redis.get(key)


async def delete_key(key: str) -> None:
    redis = await get_redis()
    await redis.delete(key)
