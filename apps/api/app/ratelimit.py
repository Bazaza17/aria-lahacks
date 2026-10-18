"""Shared rate limiter.

Keyed by client IP. Behind Railway/Vercel the Dockerfile runs uvicorn with
--proxy-headers, so that is the real caller, not the proxy. In-memory storage is
fine for a single-instance Railway deploy.

The ceiling is high on purpose: the dispatcher console polls and streams during a
drill, and a 429 mid-incident is worse than a noisy client. The live routes that
matter most are @limiter.exempt in routes/live.py.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    # Global per-IP ceiling: stops a runaway client, never a busy drill.
    default_limits=["600/minute"],
)
