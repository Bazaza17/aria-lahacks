"""Who may call the CREAO layer.

- Sai's pipeline and the ElevenLabs server tools: header X-Tool-Secret = CREAO_TOOL_SECRET
- The dispatcher dashboard: Authorization: Bearer <one of DISPATCH_API_KEYS> (or ?token= for SSE)
- CREAO's MCP connector: Bearer <one of MCP_API_KEYS> (checked in mcp.py)
- Everyone else (open drills): the console's read routes and the drill actions take no key.
  viewer() tells a route whether the caller holds a key (full data) or is the public (phones
  masked, first names only; see situation.mask_public). Live mode still needs the dispatcher key.

On the laptop with no keys set, calls are allowed so the sandbox works out of the box. With
SENTRY_ENVIRONMENT=cloud a missing key rejects everything instead.
"""

import hmac

from fastapi import Header, HTTPException, Query

from app.creao.config import get_settings


def _ok(given: str | None, allowed: set[str]) -> bool:
    return bool(given) and any(hmac.compare_digest(given, k) for k in allowed)


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def _open(configured: bool) -> bool:
    return not configured and not get_settings().cloud


async def require_tool(x_tool_secret: str | None = Header(None)) -> None:
    secret = get_settings().tool_secret
    if _open(bool(secret)) or (secret and _ok(x_tool_secret, {secret})):
        return
    raise HTTPException(401, "X-Tool-Secret required")


async def require_dispatcher(
    authorization: str | None = Header(None), token: str | None = Query(None)
) -> None:
    if is_dispatcher(authorization, token):
        return
    raise HTTPException(401, "Dispatcher key required")


async def require_dispatcher_or_tool(
    authorization: str | None = Header(None),
    token: str | None = Query(None),
    x_tool_secret: str | None = Header(None),
) -> None:
    s = get_settings()
    if s.tool_secret and _ok(x_tool_secret, {s.tool_secret}):
        return
    await require_dispatcher(authorization, token)


def is_dispatcher(authorization: str | None, token: str | None) -> bool:
    """A valid dispatcher key (or the open laptop sandbox with no keys set)."""
    keys = get_settings().dispatch_keys
    return _open(bool(keys)) or _ok(_bearer(authorization) or token, keys)


async def viewer(
    authorization: str | None = Header(None),
    token: str | None = Query(None),
    x_tool_secret: str | None = Header(None),
) -> bool:
    """Anyone may call; True when the caller holds a dispatcher key or the tool secret (full data),
    False for the public (masked data, drills only)."""
    s = get_settings()
    if s.tool_secret and _ok(x_tool_secret, {s.tool_secret}):
        return True
    return is_dispatcher(authorization, token)
