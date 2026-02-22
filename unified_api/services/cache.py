"""
Redis caching service for analytics and frequently accessed data.

Uses Redis database 2 (Celery uses 0 and 1).
Default TTL: 1 hour for analytics, 5 minutes for search results.
"""
import json
import hashlib
from typing import Optional, Any
from functools import wraps

import redis
import structlog

from unified_api.config import settings

logger = structlog.get_logger(__name__)

# Use database 2 for caching (0=celery broker, 1=celery results)
CACHE_REDIS_URL = settings.redis_url.replace("/0", "/2")

_redis_client: Optional[redis.Redis] = None


def get_redis() -> redis.Redis:
    """Get or create Redis client for caching."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(
            CACHE_REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        logger.info("Redis cache client initialized", url=CACHE_REDIS_URL)
    return _redis_client


def cache_key(prefix: str, **kwargs) -> str:
    """Generate a cache key from prefix and parameters."""
    params_str = json.dumps(kwargs, sort_keys=True, default=str)
    param_hash = hashlib.md5(params_str.encode()).hexdigest()[:12]
    return f"bd:{prefix}:{param_hash}"


def cache_get(key: str) -> Optional[Any]:
    """Get a value from cache. Returns None on miss or error."""
    try:
        r = get_redis()
        data = r.get(key)
        if data:
            return json.loads(data)
    except (redis.ConnectionError, redis.TimeoutError) as e:
        logger.warning("Redis cache get failed", key=key, error=str(e))
    except json.JSONDecodeError:
        pass
    return None


def cache_set(key: str, value: Any, ttl: int = 3600) -> bool:
    """Set a value in cache with TTL (seconds). Returns success."""
    try:
        r = get_redis()
        r.setex(key, ttl, json.dumps(value, default=str))
        return True
    except (redis.ConnectionError, redis.TimeoutError) as e:
        logger.warning("Redis cache set failed", key=key, error=str(e))
    return False


def cache_invalidate(pattern: str = "bd:*") -> int:
    """Invalidate cache entries matching pattern. Returns count deleted."""
    try:
        r = get_redis()
        keys = list(r.scan_iter(match=pattern, count=100))
        if keys:
            return r.delete(*keys)
    except (redis.ConnectionError, redis.TimeoutError) as e:
        logger.warning("Redis cache invalidation failed", error=str(e))
    return 0


# TTL constants
TTL_ANALYTICS = 3600        # 1 hour for analytics aggregations
TTL_SEARCH = 300            # 5 minutes for search results
TTL_AUTOCOMPLETE = 7200     # 2 hours for autocomplete data
TTL_STATS = 1800            # 30 minutes for stats
