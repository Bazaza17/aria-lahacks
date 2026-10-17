"""Shared rate limiter.

Keyed by client IP. In-memory storage is fine for a single-instance Railway
deploy; swap `storage_uri` to Redis if we ever scale horizontally.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    # Sane global ceiling so no single IP can hammer the API.
    default_limits=["120/minute"],
)
