"""Hot copy of the lists the final call reads. Postgres remains the stored copy."""

from __future__ import annotations

import json
import os
from typing import Optional

_CLIENT = None
_CLIENT_URL = ""
LIST_TTL_SECONDS = 6 * 60 * 60


def cache_get(key: str) -> Optional[dict]:
    client = _client()
    if client is None:
        return None
    try:
        raw = client.get(key)
    except Exception:
        return None
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def cache_set(key: str, value: dict, ttl: int = LIST_TTL_SECONDS) -> None:
    client = _client()
    if client is None:
        return
    try:
        client.set(key, json.dumps(value), ex=ttl)
    except Exception:
        return


def _client():
    """Return a Redis client when REDIS_URL is set. A missing cache is not an error."""
    global _CLIENT, _CLIENT_URL
    url = os.environ.get("REDIS_URL", "").strip()
    if not url:
        return None
    if _CLIENT is not None and _CLIENT_URL == url:
        return _CLIENT
    try:
        import redis
    except ImportError:
        return None
    try:
        _CLIENT = redis.Redis.from_url(url, socket_timeout=0.4, socket_connect_timeout=0.4, decode_responses=True)
        _CLIENT_URL = url
    except Exception:
        _CLIENT = None
        _CLIENT_URL = ""
    return _CLIENT
