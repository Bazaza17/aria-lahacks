"""TigerData -> CREAO: the orchestrator that wakes the command staff.

The orchestrator subscribes to the live stream coming out of TigerData (LISTEN creao_live). It
collects what matters per building (a declared fire, hazards, caller statements, life threats,
silent occupants, decisions), batches routine events for CREAO_DEBOUNCE_SECS, and triggers the
Incident Commander's API Trigger with the new events and a snapshot read from TigerData:

    POST https://agent.creao.ai/api/v1/apps/{app_id}/runs
    Authorization: Bearer capi_...
    {"inputs": {...}, "webhookUrl": "https://API/live/creao/run-result?push=<run_id>&token=..."}

The Commander hands tasks to specialists with the handoff_to_agent MCP tool, which comes back
here (trigger_role). Critical events (a declared fire, a caller's first handoff) skip the batch.
The staff's own actions never wake the staff again, so there are no loops.
"""

import asyncio
import contextlib
import logging
import time
from collections import defaultdict
from urllib.parse import quote

import httpx

from app.creao import agents, hub
from app.creao.buildings import get_building
from app.creao.config import get_settings
from app.creao.db import sessions
from app.creao.models import AgentRun

log = logging.getLogger(__name__)

CRITICAL = {"evacuation.started", "handoff.requested"}
COMMANDER_BUSY_SECS = (
    90  # a routine batch waits while the last Commander run is still working (at most this long)
)
ROUTE_BY_EVENT = {  # with no Commander deployed, events go straight to the owner
    "statement": "intake",
    "risk": "intake",
    "hazard.reported": "coordinator",
    "fire_model.updated": "coordinator",
    "occupant.call_requested": "accountability",
    "handoff.requested": "liaison",
    "handoff.transferred": "liaison",
    "evacuation.started": "coordinator",
    "route.approved": "scribe",
    "route.rejected": "scribe",
}


def deployed() -> dict[str, dict[str, str]]:
    return {k: v for k, v in get_settings().creao_agents.items() if k in agents.ROLES}


async def _post(role: str, inputs: dict, run_id: str) -> tuple[str | None, str | None]:
    """Trigger one CREAO agent. Returns (creao_run_id, error)."""
    s, cfg = get_settings(), deployed()[role]
    webhook = f"{s.public_base_url.rstrip('/')}/live/creao/run-result?push={quote(run_id)}"
    if s.creao_webhook_token:
        webhook += f"&token={quote(s.creao_webhook_token)}"
    error = None
    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    s.creao_trigger_url.format(app_id=cfg["app_id"]),
                    headers={"Authorization": f"Bearer {cfg['api_key']}"},
                    json={"inputs": inputs, "webhookUrl": webhook},
                )
            if r.status_code < 300:
                body = (
                    r.json()
                    if r.headers.get("content-type", "").startswith("application/json")
                    else {}
                )
                return body.get("runId") or body.get("id"), None
            error = f"HTTP {r.status_code}: {r.text[:300]}"
            if r.status_code < 500 and r.status_code != 429:
                break
        except httpx.HTTPError as e:
            error = str(e) or type(e).__name__
        await asyncio.sleep(2**attempt)
    return None, error


async def snapshot(session, building_id: str | None) -> dict:
    """What the agent needs to act without reading everything, straight from TigerData."""
    from app.creao import situation

    building = get_building(building_id)
    if building is None:
        return {}
    s = await situation.build(session, building)
    return {
        "building": s["building"],
        "evacuation": s["evacuation"]
        and {
            k: s["evacuation"][k] for k in ("mode", "origin_label", "minute_now", "approved_routes")
        },
        "roll_call": s["roll_call"],
        "exits": [
            {
                k: e[k]
                for k in (
                    "id",
                    "label",
                    "status",
                    "unsafe",
                    "reasons",
                    "heading",
                    "safe",
                    "predicted_minute",
                )
            }
            for e in s["exits"]
        ],
        "hazards": [
            {k: h[k] for k in ("category", "text", "verification", "zone_id", "exit_id")}
            for h in s["hazards"][:10]
        ],
        "open_route_proposals": [p for p in s["route_proposals"] if p["status"] == "proposed"],
        "handoffs": [
            {
                "incident_id": h["incident_id"],
                "summary": (h["brief"] or {}).get("summary"),
                "status": h["status"],
            }
            for h in s["handoffs"]
        ],
        "top_incidents": [
            {
                "incident_id": i["id"],
                "priority": i["priority"],
                "headline": i["headline"],
                "place": i["location"].get("label"),
            }
            for i in s["incidents"][:6]
        ],
        "fire_model": s["fire_model"]
        and {
            "label": s["fire_model"].get("label"),
            "source": s["fire_model"].get("source"),
            "simulation": True,
            # the engine's own numbers to quote (exits lost with times, at risk, last out)
            "summary": s["fire_model"].get("summary"),
            "steps": _snapshot_steps(s["fire_model"]),
        },
    }


def _snapshot_steps(fire_model: dict) -> list[dict]:
    """The steps the agents see. An engine model has a step per zone per stage, so it is cut to
    the ones that change a route (fire, exit lost, untenable); a hand-typed model goes as is."""
    steps = [
        {"minute": st.get("minute"), "label": st.get("label"), "kind": st.get("kind", "fire")}
        for st in fire_model.get("steps") or []
    ]
    if fire_model.get("source") != "aria-engine":
        return steps
    return [st for st in steps if st["kind"] in ("fire", "exit lost", "untenable")][:30]


async def trigger_role(
    role: str,
    *,
    task: str,
    building_id: str | None,
    parent_id: str | None = None,
    trigger: str | None = None,
    extra: dict | None = None,
) -> AgentRun:
    async with sessions()() as session:
        run = await agents.create_run(
            session,
            role=role,
            task=task,
            building_id=building_id,
            parent_id=parent_id,
            trigger=trigger,
        )
        if role not in deployed():
            await agents.finish_run(
                session, run, error=f"{agents.ROLES[role]['title']} is not deployed in CREAO"
            )
            return run
        snap = await snapshot(session, building_id)
    staff = deployed()
    inputs = {
        "run_id": run.id,
        "role": role,
        "role_title": agents.ROLES[role]["title"],
        "task": task,
        "building_id": building_id,
        "snapshot": snap,
        "staff": [
            {"role": r, "title": m["title"], "does": m["does"], "deployed": r in staff}
            for r, m in agents.ROLES.items()
            if r != "commander"
        ],
        "how_to": "Use the incident-dispatch MCP tools. Pass run_id to every write tool. Hand work to a "
        "specialist with handoff_to_agent. Finish with complete_task(run_id, summary).",
        **(extra or {}),
    }
    creao_run_id, error = await _post(role, inputs, run.id)
    async with sessions()() as session:
        run = await session.get(AgentRun, run.id)
        if error:
            await agents.finish_run(session, run, error=error)
        else:
            run.creao_run_id, run.status = creao_run_id, "running"
            await session.commit()
            await agents.record_action(
                session, run, "run.started", f"Started in CREAO ({creao_run_id or 'run'})"
            )
    (log.warning if error else log.info)(
        "CREAO %s run %s -> %s", role, run.id, error or creao_run_id
    )
    return run


def _summary(kind: str, data: dict) -> str:
    if kind == "evacuation.started":
        ev = data.get("evacuation") or {}
        n = data.get("recipients_count", len(data.get("recipients") or []))
        return f"{ev.get('mode', 'drill')} declared: fire at {ev.get('origin_label')}; {n} alerted"
    if kind == "hazard.reported":
        return f"{data.get('category')} at {data.get('exit_id') or data.get('zone_id')}: {data.get('text')}"
    if kind == "occupant.call_requested":
        return f"call {data.get('name') or data.get('phone')}: {data.get('reason')}"
    if kind.startswith("route."):
        p = data.get("proposal") or {}
        return f"{p.get('zone_label')}: {p.get('to_exit_label')} {kind.split('.')[1]} by {data.get('decided_by')}"
    if kind == "handoff.requested":
        return ((data.get("handoff") or {}).get("brief") or {}).get(
            "summary"
        ) or "a caller needs a human"
    if kind == "handoff.transferred":
        brief = ((data.get("handoff") or {}).get("brief") or {}).get("summary") or data.get(
            "caller"
        )
        return f"ElevenLabs moved the call to the dispatcher line: {brief}"
    return kind


class Orchestrator:
    def __init__(self) -> None:
        self.task: asyncio.Task | None = None
        self.pending: dict[str, list[dict]] = defaultdict(list)
        self.first_at: dict[str, float] = {}
        self.commander_started: dict[str, float] = {}
        self.commander_run: dict[str, str] = {}

    async def start(self) -> None:
        if deployed():
            self.task = asyncio.create_task(self._run(), name="creao-orchestrator")
            log.info("CREAO orchestrator on; staff: %s", ", ".join(deployed()))

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task

    async def _run(self) -> None:
        async with hub.subscribe() as queue:
            while True:
                try:
                    self.collect(await asyncio.wait_for(queue.get(), timeout=2))
                except TimeoutError:
                    pass
                await self._flush_due()

    def collect(self, message: dict) -> None:
        kind, data, building_id = (
            message.get("type"),
            message.get("data") or {},
            message.get("building_id"),
        )
        if not building_id:
            return
        by = str(data.get("requested_by") or data.get("source") or "")
        if by.startswith("creao:"):
            return  # the staff's own actions don't wake the staff
        event = None
        if kind in (
            "evacuation.started",
            "hazard.reported",
            "occupant.call_requested",
            "route.approved",
            "route.rejected",
            "fire_model.updated",
        ):
            event = {"type": kind, "summary": _summary(kind, data)}
        elif kind == "handoff.transferred":
            event = {
                "type": kind,
                "incident_id": message.get("incident_id"),
                "summary": _summary(kind, data),
            }
        elif kind == "handoff.requested" and data.get("first", True):
            event = {
                "type": kind,
                "incident_id": message.get("incident_id"),
                "summary": _summary(kind, data),
            }
        elif (
            kind == "incident.event"
            and data.get("kind") in ("transcript", "sms_in")
            and data.get("role") == "caller"
        ):
            event = {
                "type": "statement",
                "incident_id": message.get("incident_id"),
                "summary": data.get("text"),
            }
        elif kind == "incident.event" and data.get("kind") == "flag":
            hits = (data.get("data") or {}).get("hits") or []
            if any(h.get("severity") in ("critical", "high") for h in hits):
                event = {
                    "type": "risk",
                    "incident_id": message.get("incident_id"),
                    "summary": data.get("text"),
                }
        if event is None:
            return
        self.pending[building_id].append(event)
        self.first_at.setdefault(building_id, time.monotonic())
        if kind in CRITICAL:
            self.first_at[building_id] = 0  # flush now

    async def _commander_busy(self, building_id: str, now: float) -> bool:
        if now - self.commander_started.get(building_id, -1e9) >= COMMANDER_BUSY_SECS:
            return False
        run_id = self.commander_run.get(building_id)
        if not run_id:
            return True  # triggered moments ago; its run id isn't back yet
        async with sessions()() as session:
            run = await session.get(AgentRun, run_id)
            return bool(run and run.status in ("queued", "running"))

    async def _flush_due(self) -> None:
        now, debounce = time.monotonic(), get_settings().creao_debounce_secs
        for building_id, events in list(self.pending.items()):
            if not events or now - self.first_at.get(building_id, now) < debounce:
                continue
            critical = any(e["type"] in CRITICAL for e in events)
            if "commander" in deployed():
                if not critical and await self._commander_busy(building_id, now):
                    continue
                self.commander_run.pop(building_id, None)
                self.commander_started[building_id] = now
                job = self._commander(building_id, events)
            else:
                job = self._direct(building_id, events)
            self.pending[building_id], self.first_at[building_id] = [], now
            asyncio.create_task(self._safe(job))

    async def _commander(self, building_id: str, events: list[dict]) -> None:
        kinds = sorted({e["type"] for e in events})
        run = await trigger_role(
            "commander",
            building_id=building_id,
            trigger=",".join(kinds),
            task=f"{len(events)} new event(s): {', '.join(kinds)}. Decide who handles each and keep the overview current.",
            extra={"new_events": events[-25:]},
        )
        self.commander_run[building_id] = run.id

    async def _direct(self, building_id: str, events: list[dict]) -> None:
        by_role: dict[str, list[dict]] = defaultdict(list)
        for e in events:
            by_role[ROUTE_BY_EVENT.get(e["type"], "scribe")].append(e)
        for role, mine in by_role.items():
            if role in deployed():
                await trigger_role(
                    role,
                    building_id=building_id,
                    trigger="direct",
                    extra={"new_events": mine[-25:]},
                    task=f"Handle {len(mine)} new event(s): "
                    + "; ".join(str(e["summary"])[:120] for e in mine[:5]),
                )

    @staticmethod
    async def _safe(coro) -> None:
        try:
            await coro
        except Exception:  # noqa: BLE001
            log.exception("CREAO orchestration failed")


orchestrator = Orchestrator()
