"""
Redis cache for the ops queue.

Strategy: versioned keys. Every cached queue/summary key embeds a version number stored
in Redis. Any write to an Application or one of its child rows bumps the version, so all
existing entries are orphaned at once (no key scanning, no per-filter bookkeeping) and
expire on their own TTL. Bumping is done immediately AND again on transaction commit, so
a reader that repopulates the cache between the two sees committed data only briefly
stale, never permanently.
"""

import hashlib
import json
import logging

from django.conf import settings
from django.core.cache import cache
from django.db import transaction

logger = logging.getLogger(__name__)

VERSION_KEY = "ops:queue:version"
PREFIX = "ops:queue"


def queue_version() -> int:
    try:
        v = cache.get(VERSION_KEY)
        if v is None:
            cache.add(VERSION_KEY, 1, timeout=None)
            v = cache.get(VERSION_KEY) or 1
        return int(v)
    except Exception:  # noqa: BLE001 — Redis down: callers fall through to the database
        logger.exception("Could not read ops queue cache version")
        return 0


def bump_queue_version() -> None:
    try:
        cache.incr(VERSION_KEY)
    except ValueError:  # key missing (evicted / first write)
        cache.set(VERSION_KEY, 1, timeout=None)
    except Exception:  # noqa: BLE001 — cache trouble must never break a write
        logger.exception("Could not bump ops queue cache version")


def invalidate_queue() -> None:
    """Call from any code path that changes what the queue shows."""
    bump_queue_version()
    transaction.on_commit(bump_queue_version)


def queue_cache_key(kind: str, user, params: dict) -> str:
    """
    kind: "list" or "summary". `params` is the normalised filter dict.
    Keys are per-user only when the result depends on who is asking
    (assigned=me, or the summary's `mine` count).
    """
    per_user = kind == "summary" or params.get("assigned") == "me"
    payload = {"v": queue_version(), "p": params, "u": str(user.id) if per_user else "*"}
    digest = hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    return f"{PREFIX}:{kind}:{digest}"


def get_cached(key: str):
    try:
        return cache.get(key)
    except Exception:  # noqa: BLE001 — degrade to uncached
        logger.exception("Cache read failed")
        return None


def set_cached(key: str, value) -> None:
    try:
        cache.set(key, value, timeout=settings.OPS_QUEUE_CACHE_SECONDS)
    except Exception:  # noqa: BLE001
        logger.exception("Cache write failed")
