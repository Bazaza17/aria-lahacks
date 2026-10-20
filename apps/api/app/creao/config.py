"""Settings for the CREAO layer, read from the environment (apps/api/.env)."""

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache

ROLES = ("commander", "intake", "coordinator", "accountability", "liaison", "scribe")


def _csv(name: str) -> set[str]:
    return {v.strip() for v in os.environ.get(name, "").split(",") if v.strip()}


@dataclass(frozen=True)
class Settings:
    # TigerData / Supabase Postgres in the cloud (postgresql+asyncpg://...); a local SQLite file
    # otherwise, so the API always boots.
    database_url: str = "sqlite+aiosqlite:///./creao_live.db"
    public_base_url: str = "http://localhost:8000"
    default_building_id: str | None = None
    # Who may call what
    tool_secret: str | None = None  # Sai's pipeline + ElevenLabs server tools: X-Tool-Secret
    dispatch_keys: set[str] = field(default_factory=set)  # dispatcher dashboard: Bearer
    mcp_api_keys: set[str] = field(default_factory=set)  # CREAO custom MCP connector: Bearer
    # CREAO command staff: {"commander": {"app_id": "...", "api_key": "capi_..."}, "intake": {...}, ...}
    creao_agents: dict[str, dict[str, str]] = field(default_factory=dict)
    creao_trigger_url: str = "https://agent.creao.ai/api/v1/apps/{app_id}/runs"
    creao_webhook_token: str | None = None
    creao_debounce_secs: float = 15.0
    # Human handoff: "join call" transfers the caller here when set
    dispatcher_phone: str | None = None
    cloud: bool = False  # SENTRY_ENVIRONMENT=cloud: a missing key is an error, never "open"
    # Open drills: anyone may declare one, so a drill ends itself after this long
    drill_max_minutes: float = 20.0
    # Keyless drills text and call real phones, so they're off unless PUBLIC_DRILLS=1
    public_drills: bool = False


@lru_cache
def get_settings() -> Settings:
    env = os.environ.get
    agents: dict = {}
    if raw := env("CREAO_AGENTS", "").strip():
        try:
            agents = {
                k: v for k, v in json.loads(raw).items() if v.get("app_id") and v.get("api_key")
            }
        except (ValueError, AttributeError):
            agents = {}
    elif key := env("CREAO_API_KEY", "").strip():
        # One CREAO key (it starts every agent in the account) plus each role's app id: the id in the
        # agent's install link, agent.creao.ai/install/<app id>.
        agents = {
            role: {"app_id": app_id, "api_key": key}
            for role in ROLES
            if (app_id := env(f"CREAO_APP_{role.upper()}", "").split("#")[0].strip())
        }
    dispatch, mcp = _csv("DISPATCH_API_KEYS"), _csv("MCP_API_KEYS")
    return Settings(
        database_url=env("CREAO_DATABASE_URL") or Settings.database_url,
        public_base_url=env("PUBLIC_BASE_URL") or Settings.public_base_url,
        default_building_id=env("CREAO_DEFAULT_BUILDING_ID") or None,
        tool_secret=env("CREAO_TOOL_SECRET") or None,
        dispatch_keys=dispatch,
        mcp_api_keys=mcp,
        creao_agents=agents,
        creao_trigger_url=env("CREAO_TRIGGER_URL") or Settings.creao_trigger_url,
        creao_webhook_token=env("CREAO_WEBHOOK_TOKEN") or None,
        creao_debounce_secs=float(env("CREAO_DEBOUNCE_SECS") or Settings.creao_debounce_secs),
        dispatcher_phone=env("DISPATCHER_PHONE") or None,
        cloud=env("SENTRY_ENVIRONMENT", "laptop") == "cloud",
        drill_max_minutes=float(env("DRILL_MAX_MINUTES") or Settings.drill_max_minutes),
        public_drills=env("PUBLIC_DRILLS", "").strip().lower() in ("1", "true", "yes"),
    )
