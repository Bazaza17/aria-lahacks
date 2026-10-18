"""MCP server for the CREAO command staff: how the agents read TigerData and act.

Endpoint: POST https://API/mcp (Streamable HTTP, stateless, JSON). Auth: Bearer <MCP_API_KEYS entry>.
In CREAO, add a custom MCP connector with that URL and token and grant it to every staff agent.

Reads come straight from TigerData (situation, the exit-flow continuous aggregate, transcripts).
Writes are recorded on the agent's run, so the dashboard's org chart shows every tool call.
Agents analyse and propose; route changes pass the safety rules and then a dispatcher's approval.
"""

import asyncio
import contextlib
import hmac
import json
from typing import Any, Literal
from urllib.parse import urlparse

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy import select
from starlette.types import ASGIApp, Receive, Scope, Send

from app.creao import agents, comms, dispatch, hub, intake, plan, report, situation
from app.creao import location as loc
from app.creao.buildings import default_building, get_building
from app.creao.config import get_settings
from app.creao.db import sessions, utcnow
from app.creao.models import AgentRun, Hazard, Incident, IncidentEvent, Occupant, Verification

mcp = MCPServer(
    name="incident-dispatch",
    instructions=(
        "Aria fire-evacuation command post. You are one agent on the CREAO command staff (Incident Commander, "
        "Intake Analyst, Evacuation Coordinator, Accountability Officer, Responder Liaison, Incident Scribe). "
        "The data is live: calls and texts from ElevenLabs + Photon, the roll call, hazards and the fire model, "
        "all stored in TigerData. Pass your run_id to every write tool and finish with complete_task. You analyse "
        "and propose; you never message occupants. Route changes need a dispatcher's approval, and only exits from "
        "the building profile exist. Silence is never safe. Fire-model steps are a simulation. Never invent facts "
        "or places; quote what people said."
    ),
)

Role = Literal["intake", "coordinator", "accountability", "liaison", "scribe"]


async def _run(session, run_id: str) -> AgentRun:
    run = await session.get(AgentRun, run_id)
    if run is None:
        raise ValueError(f"unknown run_id {run_id}; use the run_id from your inputs")
    return run


def _building(building_id: str | None = None, run: AgentRun | None = None):
    b = get_building(building_id or (run.building_id if run else None)) or default_building()
    if b is None:
        raise ValueError("unknown building")
    return b


# ---------------------------------------------------------------- reads (TigerData)


@mcp.tool(
    description="The live situation from TigerData: incidents on the scan (priority, place, what was said), "
    "exits (open / unsafe and why, how many heading there), hazards, roll call, approved routes, "
    "route changes waiting for a dispatcher, human handoffs, and the fire model (simulation)."
)
async def get_building_situation(building_id: str | None = None) -> dict[str, Any]:
    b = _building(building_id)
    async with sessions()() as session:
        s = await situation.build(session, b)
    s["zones"] = [{"id": z.id, "label": z.label} for z in b.zones]
    s["exit_ids"] = [{"id": e.id, "label": e.label} for e in b.exits]
    return s


@mcp.tool(
    description="People confirmed out per exit, per 15 seconds, over the last N minutes (TigerData continuous "
    "aggregate evac_flow_15s). Use it to see which exits are moving people and which are stalled."
)
async def get_exit_flow(building_id: str | None = None, minutes: int = 10) -> dict[str, Any]:
    async with sessions()() as session:
        return await situation.flow(session, _building(building_id), max(1, min(minutes, 120)))


@mcp.tool(
    description="One incident in full: who, where, severity, facts the voice agent logged, and the transcript "
    "or text thread (newest last)."
)
async def get_incident(incident_id: str, lines: int = 30) -> dict[str, Any]:
    async with sessions()() as session:
        inc = await session.get(Incident, incident_id)
        if inc is None:
            return {"error": f"incident {incident_id} not found"}
        events = (
            (
                await session.execute(
                    select(IncidentEvent)
                    .where(IncidentEvent.incident_id == inc.id)
                    .order_by(IncidentEvent.created_at.desc())
                    .limit(min(lines, 100))
                )
            )
            .scalars()
            .all()
        )
        return {
            **intake.incident_out(inc),
            "timeline": [
                {"at": e.created_at.isoformat(), "kind": e.kind, "role": e.role, "text": e.text}
                for e in reversed(events)
            ],
        }


@mcp.tool(
    description="Texts and calls from TigerData: per-minute texts in/out, call lines, calls placed, calls moved "
    "to a dispatcher and trigger words (continuous aggregate comms_1m), plus how many people were alerted, how "
    "many replied, the reply rate and the median seconds to first reply."
)
async def get_comms(building_id: str | None = None) -> dict[str, Any]:
    async with sessions()() as session:
        b = _building(building_id)
        return await comms.stats(session, b, await plan.active_evacuation(session, b.id))


@mcp.tool(
    description="One person's whole conversation from TigerData, texts and calls together (oldest first): who "
    "said what, their reply to the alert (evacuating, directions, help, safe) and any trigger word. Look them "
    "up by name or phone number."
)
async def get_person_thread(person: str, building_id: str | None = None) -> dict[str, Any]:
    async with sessions()() as session:
        b = _building(building_id)
        digits = "".join(c for c in person if c.isdigit())[-10:]
        people = (
            (await session.execute(select(Occupant).where(Occupant.building_id == b.id)))
            .scalars()
            .all()
        )
        occ = next(
            (
                o
                for o in people
                if (digits and o.phone.endswith(digits))
                or (o.name and o.name.lower() == person.strip().lower())
            ),
            None,
        )
        if occ is None:
            return {"error": f"no one called {person!r} is registered at {b.name}"}
        return {
            "name": occ.name,
            "phone": occ.phone,
            "status": occ.status.value,
            "place": (occ.location or {}).get("label"),
            "last_instruction": occ.last_instruction,
            "thread": await comms.thread(session, b, occ),
        }


@mcp.tool(
    description="The live incident report: each section's text, who wrote it, and whether it is still Aria's "
    "automatic draft (waiting for its owner on the staff)."
)
async def get_live_report(building_id: str | None = None) -> dict[str, Any]:
    async with sessions()() as session:
        return await report.build(session, _building(building_id))


# ---------------------------------------------------------------- the staff hands work to each other


@mcp.tool(
    description="Incident Commander: hand a task to a specialist. Roles: intake (statements -> hazard pins, life "
    "threats), coordinator (route proposals), accountability (roll call, who to call), liaison "
    "(briefing for arriving crews), scribe (timeline)."
)
async def handoff_to_agent(run_id: str, role: Role, task: str) -> dict[str, Any]:
    from app.creao import bridge

    async with sessions()() as session:
        run = await _run(session, run_id)
        await agents.record_action(
            session, run, "handoff", f"Handed to {agents.ROLES[role]['title']}: {task}", to=role
        )
        building_id = run.building_id
    asyncio.create_task(
        bridge.trigger_role(
            role, task=task, building_id=building_id, parent_id=run_id, trigger="handoff"
        )
    )
    return {"handed_off_to": role, "deployed": role in bridge.deployed()}


@mcp.tool(description="Finish your task with a short summary of what you found and did.")
async def complete_task(run_id: str, summary: str) -> dict[str, Any]:
    async with sessions()() as session:
        await agents.finish_run(session, await _run(session, run_id), summary=summary)
    return {"done": True}


# ---------------------------------------------------------------- writes (checked, recorded, streamed)


@mcp.tool(
    description="Pin a hazard someone reported at a named place (stays REPORTED until a dispatcher verifies it). "
    "place = a zone or exit id or name from the building. category: fire_hazard, blocked, violence."
)
async def report_hazard(
    run_id: str, place: str, category: Literal["fire_hazard", "blocked", "violence"], text: str
) -> dict[str, Any]:
    async with sessions()() as session:
        run = await _run(session, run_id)
        b = _building(run=run)
        match = (
            ("exit", place)
            if b.exit(place)
            else ("zone", place)
            if b.zone(place)
            else loc.match_place(b, place)
        )
        if not match:
            return {"error": f"unknown place {place!r}; use a zone or exit from the building"}
        kind, pid = match
        h = Hazard(
            building_id=b.id,
            zone_id=pid if kind == "zone" else b.exit(pid).zone,
            exit_id=pid if kind == "exit" else next((e.id for e in b.exits if e.zone == pid), None),
            category=category,
            text=text[:500],
            source=f"creao:{run.role}",
            verification=Verification.reported,
        )
        session.add(h)
        await session.commit()
        label = (b.exit(h.exit_id) or b.zone(h.zone_id)).label
        await agents.record_action(
            session, run, "hazard", f"Pinned {category.replace('_', ' ')} at {label}: {text}"
        )
        await plan.bump_hazards(session, b)
        return {"hazard_id": h.id, "place": label, "verification": "reported"}


@mcp.tool(
    description="Propose a route change for one zone. The safety rules check it (only exits from the building, "
    "never one with a reported hazard or predicted fire); then a dispatcher must approve before "
    "anyone is told. to_exit = null means shelter in place."
)
async def propose_route(
    run_id: str, zone: str, to_exit: str | None, rationale: str
) -> dict[str, Any]:
    async with sessions()() as session:
        run = await _run(session, run_id)
        b = _building(run=run)
        try:
            p = await plan.propose_from_agent(
                session,
                b,
                zone=zone,
                to_exit=to_exit,
                rationale=rationale,
                proposed_by=f"creao:{run.role}",
            )
        except plan.ProposalRejected as e:
            await agents.record_action(
                session, run, "proposal.rejected", f"Safety rules refused: {e}"
            )
            return {"accepted": False, "reason": str(e)}
        out = plan.proposal_out(p, b)
        await agents.record_action(
            session,
            run,
            "proposal",
            f"Proposed {out['to_exit_label']} for {out['zone_label']} (awaiting dispatcher)",
        )
        return {"accepted": True, "proposal_id": p.id, "status": "awaiting dispatcher approval"}


@mcp.tool(
    description="Write your section of the live incident report: overview, hazards, routes, people, responders, "
    "timeline. Replace the whole section each time; short and factual."
)
async def update_report(
    run_id: str,
    section: Literal[
        "overview", "hazards", "routes", "people", "responders", "timeline", "after_action"
    ],
    text: str,
) -> dict[str, Any]:
    async with sessions()() as session:
        run = await _run(session, run_id)
        try:
            await report.write(
                session,
                _building(run=run),
                section,
                text,
                role=run.role,
                by=agents.ROLES[run.role]["title"],
            )
        except LookupError as e:
            return {"error": str(e)}
        await agents.record_action(
            session,
            run,
            "report",
            "Wrote the after-action report"
            if section == "after_action"
            else f"Updated the {report.SECTIONS[section][0].lower()} section",
        )
        return {"updated": section}


@mcp.tool(
    description="Put a human dispatcher on an incident's call or text thread because a life is at risk. Say why."
)
async def request_handoff(run_id: str, incident_id: str, reason: str) -> dict[str, Any]:
    async with sessions()() as session:
        run = await _run(session, run_id)
        inc = await session.get(Incident, incident_id)
        if inc is None:
            return {"error": f"incident {incident_id} not found"}
        await dispatch.request_handoff(
            session,
            _building(inc.building_id),
            inc,
            reason=f"{agents.ROLES[run.role]['title']}: {reason}",
            requested_by=f"creao:{run.role}",
        )
        await agents.record_action(
            session,
            run,
            "handoff.requested",
            f"Asked for a human on {inc.caller or incident_id}: {reason}",
        )
        return {"handoff": "requested"}


@mcp.tool(
    description="Ask the voice agent to call an occupant (no reply, needs reassurance, location unclear)."
)
async def request_call(run_id: str, phone: str, reason: str) -> dict[str, Any]:
    async with sessions()() as session:
        run = await _run(session, run_id)
        b = _building(run=run)
        occ = await session.scalar(
            select(Occupant).where(Occupant.building_id == b.id, Occupant.phone == phone)
        )
        if occ is None:
            return {"error": f"{phone} is not registered in {b.name}"}
        if occ.call_requested_at:
            return {"call_requested": True, "already_requested": True}
        occ.call_requested_at = utcnow()
        await session.commit()
        await hub.publish(
            "occupant.call_requested",
            building_id=b.id,
            data={
                "phone": phone,
                "name": occ.name,
                "reason": reason,
                "last_instruction": occ.last_instruction,
                "requested_by": f"creao:{run.role}",
            },
        )
        await agents.record_action(
            session, run, "call.requested", f"Requested a call to {occ.name or phone}: {reason}"
        )
        return {"call_requested": True}


@mcp.tool(
    description="Add a note to an incident's timeline (dispatchers see it live), e.g. facts a crew needs."
)
async def add_note(run_id: str, incident_id: str, text: str) -> dict[str, Any]:
    async with sessions()() as session:
        run = await _run(session, run_id)
        inc = await session.get(Incident, incident_id)
        if inc is None:
            return {"error": f"incident {incident_id} not found"}
        await intake.add_event(
            session, inc, "note", role="creao", text=f"{agents.ROLES[run.role]['title']}: {text}"
        )
        await agents.record_action(
            session, run, "note", f"Note on {inc.caller or incident_id}: {text}"
        )
        return {"noted": True}


# ---------------------------------------------------------------- mount


class _BearerAuth:
    def __init__(self, app: ASGIApp, keys: set[str]) -> None:
        self.app, self.keys = app, keys

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"].startswith("/mcp"):
            headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
            auth = headers.get("authorization", "")
            token = (
                auth[7:].strip() if auth.lower().startswith("bearer ") else headers.get("x-api-key")
            )
            if not token or not any(hmac.compare_digest(token, k) for k in self.keys):
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"www-authenticate", b"Bearer"),
                        ],
                    }
                )
                await send(
                    {
                        "type": "http.response.body",
                        "body": json.dumps({"error": "unauthorized"}).encode(),
                    }
                )
                return
        await self.app(scope, receive, send)


class MCPMount:
    """ASGI app for /mcp; rebuilt each startup because a session manager can only run once."""

    def __init__(self, keys: set[str]) -> None:
        self.keys, self.inner = keys, None

    @contextlib.asynccontextmanager
    async def lifespan(self):
        base = get_settings().public_base_url.rstrip("/")
        security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[h for h in (urlparse(base).netloc, "127.0.0.1:*", "localhost:*") if h],
            allowed_origins=[base, "http://localhost:*", "http://127.0.0.1:*"],
        )
        app = mcp.streamable_http_app(
            streamable_http_path="/mcp",
            stateless_http=True,
            json_response=True,
            transport_security=security,
        )
        async with mcp.session_manager.run():
            self.inner = _BearerAuth(app, self.keys)
            try:
                yield
            finally:
                self.inner = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self.inner is None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 503,
                    "headers": [(b"content-type", b"text/plain")],
                }
            )
            await send({"type": "http.response.body", "body": b"MCP server not started"})
            return
        await self.inner(scope, receive, send)


mount = MCPMount(get_settings().mcp_api_keys) if get_settings().mcp_api_keys else None
