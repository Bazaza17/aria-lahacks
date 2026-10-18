"""The CREAO layer's HTTP surface, under /live. See app/creao/__init__.py.

Intake (Sai's Photon + ElevenLabs pipeline, X-Tool-Secret):
  POST /live/intake/events                 one normalized SMS / call / location event (idempotent)
  POST /live/tools/log-incident-details    ElevenLabs server tool
  POST /live/tools/update-evacuee          ElevenLabs server tool
  POST /live/buildings/{id}/occupants      who is in the building

Live view (open: no key needed; without a dispatcher key or X-Tool-Secret, phone numbers are
masked and people keep only their first name, see situation.mask_public):
  GET  /live/view                          the console
  GET  /live/buildings/{id}/situation      pins, exits, flows, roll call, hazards, routes
  GET  /live/buildings/{id}/flow           people out per exit per 15 s (TigerData continuous aggregate)
  GET  /live/stream?building_id=&token=    Server-Sent Events, streamed out of TigerData
  GET  /live/buildings/{id}/report[.md]    the live incident report the CREAO staff writes
  GET  /live/buildings/{id}/staff          the CREAO command staff: org chart, handoffs, activity

CREAO callback:
  POST /live/creao/run-result?push=<run_id>&token=   CREAO calls this when an agent run finishes

Open drills (no key for a drill; a live evacuation needs the dispatcher key):
  POST /live/buildings/{id}/evacuations    declare a drill (mode "live": key only); an "origin" runs
                                           the engine. Without a key it's refused while one is active.
  POST /live/evacuations/{id}/end          drills also end themselves after DRILL_MAX_MINUTES (20)
  GET  /live/buildings/{id}/route-proposals, POST /live/route-proposals/{id}/decision
  POST /live/incidents/{id}/acknowledge, /assign, /handoff/join, /handoff/resolve
  POST /live/occupants/{id}/retext, /call  re-send someone their approved route, or call them now

Dispatcher management (Bearer dispatcher key or X-Tool-Secret):
  PUT  /live/buildings/{id}/fire-model     {"engine": {"start", "growth"}} or hand-typed steps
  POST /live/buildings/{id}/hazards, /live/hazards/{id}/verify, /live/hazards/{id}/clear

Phone agent / messenger (Bearer dispatcher key or X-Tool-Secret):
  GET  /live/buildings/{id}/brief          plain-text layout facts from the venue model
"""

import asyncio
import hmac
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.creao import (
    agents,
    bridge,
    brief,
    comms,
    db,
    dispatch,
    engine_model,
    hub,
    intake,
    plan,
    report,
    rules,
    situation,
)
from app.creao import location as loc
from app.creao.auth import require_dispatcher, require_dispatcher_or_tool, require_tool, viewer
from app.creao.buildings import (
    Building,
    all_buildings,
    building_for_line,
    default_building,
    get_building,
)
from app.creao.config import get_settings
from app.creao.db import get_session, utcnow
from app.creao.models import (
    AgentRun,
    Evacuation,
    Hazard,
    InboundEvent,
    Incident,
    Occupant,
    ProposalStatus,
    RouteProposal,
    Verification,
)
from app.ratelimit import limiter

router = APIRouter(prefix="/live", tags=["live"])
Session = Annotated[AsyncSession, Depends(get_session)]
# True with a dispatcher key or X-Tool-Secret (full data); False for the public (open drills)
Privileged = Annotated[bool, Depends(viewer)]


async def _names(session: AsyncSession, building_id: str) -> list[str]:
    rows = await session.execute(
        select(Occupant.name).where(Occupant.building_id == building_id, Occupant.name.is_not(None))
    )
    return [n for (n,) in rows.all()]


async def _out(session: AsyncSession, privileged: bool, building_id: str, payload: Any) -> Any:
    """The payload as is for a dispatcher or the messenger; masked for the public."""
    if privileged:
        return payload
    return situation.mask_public(payload, await _names(session, building_id))


async def _expire_drill(session: AsyncSession, building_id: str) -> None:
    """Anyone can declare a drill, so a drill ends itself after DRILL_MAX_MINUTES."""
    ev = await plan.active_evacuation(session, building_id)
    if ev and ev.mode == "drill" and plan.minute_now(ev) > get_settings().drill_max_minutes:
        await dispatch.end(session, ev)


async def _drill_only(session: AsyncSession, privileged: bool, building_id: str) -> None:
    """Without a key, actions only touch a running drill: with no evacuation there is nothing to
    act on, and a live evacuation needs the dispatcher key."""
    if privileged:
        return
    await _expire_drill(session, building_id)
    ev = await plan.active_evacuation(session, building_id)
    if ev is None:
        raise HTTPException(409, "No drill is running here")
    if ev.mode != "drill":
        raise HTTPException(401, "Dispatcher key required during a live evacuation")


def _known_origin(building: Building, origin: str | None) -> bool:
    """A public declare must name one of the venue's own places (an engine start space, a zone or
    an exit), so the alert text only ever carries the venue's label, never typed text."""
    if not origin or not origin.strip():
        return False
    if loc.match_place(building, origin) is not None:
        return True
    return engine_model.resolve_start(building, origin, engine_model.start_spaces()) is not None


# One public declare at a time per building (two at once could both pass the "already running"
# check, and dispatch.start would end the first and alert everyone twice).
_declare_locks: dict[str, asyncio.Lock] = {}


def _building(building_id: str | None = None, line: str | None = None) -> Building:
    b = get_building(building_id) if building_id else building_for_line(line)
    if b is None:
        raise HTTPException(404, "Unknown building")
    return b


def _occupant_out(o: Occupant) -> dict[str, Any]:
    return {
        "phone": o.phone,
        "name": o.name,
        "status": o.status.value,
        "exit_id": o.exit_id,
        "location": o.location,
        "mobility": o.mobility or [],
        "incident_id": o.incident_id,
        "last_instruction": o.last_instruction,
    }


@router.get("/health")
@limiter.exempt
async def health() -> dict:
    s = get_settings()
    default = default_building()
    return {
        "ok": True,
        "database": db.status,
        "live": {**hub.state, "subscribers": hub.subscriber_count()},
        "buildings": [
            {"id": b.id, "name": b.name, "default": b.id == (default and default.id)}
            for b in all_buildings().values()
        ],
        "creao_staff": sorted(s.creao_agents),
        "mcp": bool(s.mcp_api_keys),
    }


# ---------------------------------------------------------------- intake


def _said_at(value: Any) -> datetime | None:
    """A call line's real time (call start + time in call, from the messenger); never in the future."""
    try:
        at = datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
    except ValueError:
        return None
    return at if at and at.tzinfo and at <= utcnow() else None


class LiveEvent(BaseModel):
    eventId: str = Field(min_length=1, max_length=128)
    eventType: Literal[
        "call.started",
        "call.transcript",
        "call.details",
        "call.ended",
        "call.transferred",
        "sms.received",
        "sms.sent",
        "location.updated",
        "occupant.status",
    ]
    occurredAt: datetime | None = None
    source: str = Field("photon", max_length=32)
    payload: dict[str, Any]


@router.post("/intake/events", dependencies=[Depends(require_tool)])
@limiter.exempt
async def intake_event(event: LiveEvent, session: Session) -> dict:
    """Sai's pipeline posts every SMS, call line and location here; it lands in TigerData."""
    session.add(
        InboundEvent(event_id=event.eventId, source=event.source, event_type=event.eventType)
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return {"accepted": True, "duplicate": True}

    p, kind = event.payload, event.eventType
    building = _building(p.get("buildingId"), p.get("line"))
    phone = p.get("phone")
    conversation_id = p.get("conversationId") or p.get("conversation_id")

    if kind.startswith("call."):
        inc = await intake.get_incident(
            session, building, conversation_id=conversation_id, caller=phone, channel="voice"
        )
        voice = {"phone": phone, "channel": "voice", "conversation_id": conversation_id}
        if kind == "call.started":  # dialing; they count as reached once they speak
            await comms.record(
                session, building, **voice, direction="out", role="aria", kind="call_started"
            )
        elif kind == "call.transcript" and p.get("text"):
            person = p.get("role", "user") == "user"
            if person and phone:  # status, place and trigger words, like a text
                await intake.occupant_update(
                    session, building, phone=phone, text=p["text"], incident=inc, source="call"
                )
            else:
                await intake.caller_said(
                    session, building, inc, p["text"], role="caller" if person else "agent"
                )
            await comms.record(
                session,
                building,
                **voice,
                direction="in" if person else "out",
                role="person" if person else "agent",
                kind="line",
                text=p["text"],
                at=_said_at(p.get("at")),  # when it was said, not when the transcript arrived
            )
        elif kind == "call.details":
            await intake.details(session, building, inc, p)
        elif kind == "call.transferred":
            await comms.record(
                session,
                building,
                **voice,
                direction="out",
                role="agent",
                kind="call_transferred",
                text=p.get("reason"),
            )
            await dispatch.call_transferred(
                session, building, inc, to=p.get("to"), reason=p.get("reason")
            )
        elif kind == "call.ended":
            await comms.record(
                session,
                building,
                **voice,
                direction="out",
                role="aria",
                kind="call_ended",
                text=p.get("reason"),
            )
            await intake.end_incident(session, inc, p.get("reason"))
        return {"accepted": True, "duplicate": False, "incident_id": inc.id}

    if not phone:
        raise HTTPException(422, "payload.phone is required")
    if kind == "sms.sent":
        occ = await session.scalar(
            select(Occupant).where(Occupant.building_id == building.id, Occupant.phone == phone)
        )
        if occ:
            occ.last_instruction = p.get("text") or occ.last_instruction
            await session.commit()
            if occ.incident_id and (inc := await session.get(Incident, occ.incident_id)):
                await intake.add_event(session, inc, "sms_out", role="system", text=p.get("text"))
        by = p.get("by") if p.get("by") in ("agent", "aria", "dispatcher") else "aria"
        await comms.record(
            session,
            building,
            phone=phone,
            channel="sms",
            direction="out",
            role=by,
            text=p.get("text"),
            occupant=occ,
        )
        return {"accepted": True, "duplicate": False}
    occ = await intake.occupant_update(
        session,
        building,
        phone=phone,
        text=p.get("text"),
        status=p.get("status"),
        exit=p.get("exit"),
        place=p.get("location"),
        floor=p.get("floor"),
        lat=p.get("lat"),
        lng=p.get("lng"),
        accuracy_m=p.get("accuracyMeters") or p.get("accuracy_m"),
        mobility=p.get("mobility"),
        name=p.get("name"),
        source="sms",
    )
    if p.get("text"):
        await comms.record(
            session,
            building,
            phone=phone,
            channel="sms",
            direction="in",
            role="person",
            text=p["text"],
            occupant=occ,
        )
    return {
        "accepted": True,
        "duplicate": False,
        "occupant": _occupant_out(occ),
        "reply": await dispatch.reply_for(
            session, building, occ, intent=rules.reply_intent(p.get("text"))
        ),
    }


class ToolContext(BaseModel):
    conversation_id: str | None = None
    caller_id: str | None = None
    called_number: str | None = None


class IncidentDetails(ToolContext):
    description: str | None = None
    category: str | None = None
    location: str | None = None
    zone: str | None = None
    floor: str | None = None
    injuries: str | None = None
    hazards: str | None = None
    people_involved: str | None = None
    urgency: str | None = None


@router.post("/tools/log-incident-details", dependencies=[Depends(require_tool)])
@limiter.exempt
async def tool_log_incident_details(body: IncidentDetails, session: Session) -> dict:
    building = _building(line=body.called_number)
    inc = await intake.get_incident(
        session, building, conversation_id=body.conversation_id, caller=body.caller_id
    )
    facts = body.model_dump(exclude={"conversation_id", "caller_id", "called_number"})
    inc = await intake.details(session, building, inc, facts)
    return {
        "logged": True,
        "priority": intake.incident_out(inc)["priority"],
        "pinned_at": (inc.location or {}).get("label"),
    }


class EvacueeUpdate(ToolContext):
    # Filled from the call's dynamic variables (the ElevenLabs tool config), never by the model
    phone: str | None = None
    building_id: str | None = None
    channel: str | None = None  # "voice" on calls Aria places; "sms" in a text session
    # Filled by the model, mid-call, each time the caller says where they are or how they are
    said: str | None = Field(None, description="the caller's own words, as close as possible")
    status: str | None = Field(None, description="safe = outside; en_route; help = can't get out")
    exit: str | None = None
    floor: str | None = None
    location: str | None = None
    mobility: list[str] | None = None


@router.post("/tools/update-evacuee", dependencies=[Depends(require_tool)])
@limiter.exempt
async def tool_update_evacuee(body: EvacueeUpdate, session: Session) -> dict:
    """The ElevenLabs agent's live update, mid-call: lands in TigerData (comms_events) as it happens,
    instead of only when the post-call transcript arrives. Answers with the approved route."""
    phone = body.phone or body.caller_id
    if not phone or not re.fullmatch(r"\+\d{8,15}", phone):  # "none" in dashboard test chats
        raise HTTPException(422, "phone is required (E.164)")
    building = _building(body.building_id, body.called_number)
    if body.channel == "sms":  # texts already reach Aria through the messenger; only answer
        occ = await session.scalar(
            select(Occupant).where(Occupant.building_id == building.id, Occupant.phone == phone)
        )
        if occ is None:
            return {"recorded": False, "approved_instruction": None}
        reply = await dispatch.reply_for(session, building, occ)
        return {"recorded": False, "approved_instruction": reply["instruction"]["message"]}
    inc = await intake.get_incident(
        session, building, conversation_id=body.conversation_id, caller=phone, channel="voice"
    )
    occ = await intake.occupant_update(
        session,
        building,
        phone=phone,
        text=body.said,
        status=body.status,
        exit=body.exit,
        place=body.location,
        floor=body.floor,
        mobility=body.mobility,
        incident=inc,
        source="call",
    )
    summary = "; ".join(
        f"{k}: {v}"
        for k, v in (("status", body.status), ("at", body.location), ("exit", body.exit))
        if v
    )
    row = await comms.record(
        session,
        building,
        phone=phone,
        channel="voice",
        direction="in",
        role="person",
        kind="call_update",
        text=body.said or summary or None,
        conversation_id=body.conversation_id,
        occupant=occ,
    )
    if row.trigger:  # a life threat, heard mid-call: the dispatcher sees it now, not after hang-up
        await dispatch.request_handoff(
            session, building, inc, reason=f"said “{row.trigger}” on the call", requested_by="call"
        )
    reply = await dispatch.reply_for(session, building, occ)
    return {
        "recorded": True,
        "status": occ.status.value,
        "approved_instruction": reply["instruction"]["message"],
        "approved_exit": reply["instruction"].get("exit_label"),
        "route_change_pending": reply["route_change_pending"],
        "exit_warning": f"{reply['exit']['label']} is unsafe: {'; '.join(reply['exit']['reasons'])}"
        if reply["exit"] and reply["exit"]["unsafe"]
        else None,
    }


class People(BaseModel):
    people: list[dict[str, Any]] = Field(
        description='[{"phone", "name", "zone", "floor", "mobility": []}]'
    )


@router.post(
    "/buildings/{building_id}/occupants", dependencies=[Depends(require_dispatcher_or_tool)]
)
async def register(building_id: str, body: People, session: Session) -> dict:
    return {
        "registered": await intake.register_occupants(session, _building(building_id), body.people)
    }


@router.get(
    "/buildings/{building_id}/occupants", dependencies=[Depends(require_dispatcher_or_tool)]
)
async def occupants(building_id: str, session: Session) -> list[dict]:
    rows = (
        await session.execute(
            select(Occupant).where(Occupant.building_id == _building(building_id).id)
        )
    ).scalars()
    return [_occupant_out(o) for o in rows]


@router.get(
    "/buildings/{building_id}/incidents", dependencies=[Depends(require_dispatcher_or_tool)]
)
async def incidents(building_id: str, session: Session) -> list[dict]:
    rows = (
        await session.execute(
            select(Incident)
            .where(Incident.building_id == _building(building_id).id)
            .order_by(Incident.started_at.desc())
            .limit(100)
        )
    ).scalars()
    return [intake.incident_out(i) for i in rows]


# ---------------------------------------------------------------- live view


@router.get("/buildings/{building_id}/situation")
async def get_situation(building_id: str, session: Session, privileged: Privileged) -> dict:
    building = _building(building_id)
    await _expire_drill(session, building.id)
    out = await _out(session, privileged, building.id, await situation.build(session, building))
    return {**out, "viewer": "dispatcher" if privileged else "public"}


@router.get("/buildings/{building_id}/flow")
async def get_flow(building_id: str, session: Session, minutes: int = 10) -> dict:
    return await situation.flow(session, _building(building_id), max(1, min(minutes, 120)))


@router.get("/stream")
@limiter.exempt
async def stream(
    request: Request, session: Session, privileged: Privileged, building_id: str | None = None
) -> StreamingResponse:
    """Every live change for a building as Server-Sent Events (event: <type>, data: JSON).
    Masked for the public (no key): phone numbers hidden, first names only."""
    names = await _names(session, building_id) if building_id and not privileged else []
    await session.close()  # never hold a database connection for the life of the stream

    async def events():
        async with hub.subscribe() as queue:
            yield f"event: hello\ndata: {json.dumps({'building_id': building_id, 'backend': hub.state['backend']})}\n\n"
            while not await request.is_disconnected():
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                if building_id and msg.get("building_id") not in (building_id, None):
                    continue
                if not privileged:
                    msg = situation.mask_public(msg, names)
                yield f"event: {msg['type']}\ndata: {json.dumps(msg, default=str)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------- dispatcher management


class EvacuationIn(BaseModel):
    mode: Literal["drill", "live"] = "drill"
    origin: str | None = Field(
        None,
        description="Where the fire starts: a venue space id (GET /engine/starts), or a zone id or "
        "place name. With one, Aria's engine runs the fire model (simulation).",
        max_length=120,
    )
    growth: Literal["slow", "medium", "fast", "ultrafast"] | None = Field(
        None, description="Fire growth for the engine (default fast)"
    )
    description: str | None = Field(None, max_length=200)
    dispatcher: str | None = Field(None, max_length=64)
    fire_model: dict | None = Field(
        None, description="A hand-typed step model instead (dispatcher key only)"
    )


@router.post("/buildings/{building_id}/evacuations")
@limiter.limit("10/minute")
async def start_evacuation(
    request: Request, building_id: str, body: EvacuationIn, session: Session, privileged: Privileged
) -> dict:
    """Open drills: anyone may declare a drill at one of the venue's places when none is running;
    "live" and a hand-typed fire model need the key."""
    building = _building(building_id)
    if privileged:
        return await _declare(session, building, body, body.fire_model)
    if body.mode == "live":
        raise HTTPException(401, "Dispatcher key required to declare a live evacuation")
    if not _known_origin(building, body.origin):
        raise HTTPException(422, "Pick where the fire starts from the venue's places")
    async with _declare_locks.setdefault(building.id, asyncio.Lock()):
        await _expire_drill(session, building.id)
        if await plan.active_evacuation(session, building.id):
            raise HTTPException(409, "An evacuation is already running here; end it first")
        out = await _declare(session, building, body, None)
    return await _out(session, privileged, building.id, out)


async def _declare(
    session: AsyncSession, building: Building, body: EvacuationIn, fire_model: dict | None
) -> dict:
    return await dispatch.start(
        session,
        building,
        mode=body.mode,
        origin=body.origin,
        description=body.description,
        dispatcher=body.dispatcher or None,
        fire_model=fire_model,
        growth=body.growth,
    )


@router.post("/evacuations/{evacuation_id}/end")
async def end_evacuation(evacuation_id: str, session: Session, privileged: Privileged) -> dict:
    ev = await session.get(Evacuation, evacuation_id)
    if ev is None:
        raise HTTPException(404, "Unknown evacuation")
    if ev.mode == "live" and not privileged:
        raise HTTPException(401, "Dispatcher key required to end a live evacuation")
    await dispatch.end(session, ev)
    return {"ended": True}


@router.put(
    "/buildings/{building_id}/fire-model", dependencies=[Depends(require_dispatcher_or_tool)]
)
async def put_fire_model(building_id: str, body: dict[str, Any], session: Session) -> dict:
    try:
        return await dispatch.set_fire_model(session, _building(building_id), body)
    except LookupError as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/buildings/{building_id}/route-proposals")
async def route_proposals(building_id: str, session: Session, privileged: Privileged) -> list[dict]:
    building = _building(building_id)
    ev = await plan.active_evacuation(session, building.id)
    if ev is None:
        return []
    rows = (
        await session.execute(
            select(RouteProposal).where(
                RouteProposal.evacuation_id == ev.id,
                RouteProposal.status == ProposalStatus.proposed,
            )
        )
    ).scalars()
    return await _out(
        session, privileged, building.id, [plan.proposal_out(p, building) for p in rows]
    )


class Decision(BaseModel):
    decision: Literal["approve", "reject"]
    dispatcher: str = Field(min_length=1, max_length=64)


@router.post("/route-proposals/{proposal_id}/decision")
async def decide(
    proposal_id: str, body: Decision, session: Session, privileged: Privileged
) -> dict:
    proposal = await session.get(RouteProposal, proposal_id)
    if proposal is None:
        raise HTTPException(404, "Unknown proposal")
    building = _building(proposal.building_id)
    await _drill_only(session, privileged, building.id)
    try:
        out = await plan.decide(
            session, building, proposal, body.decision == "approve", body.dispatcher
        )
    except plan.StaleProposal as e:
        raise HTTPException(
            409,
            {
                "error": "stale",
                "message": "The hazard picture changed; review the replacement.",
                "replacement": plan.proposal_out(e.replacement, building)
                if e.replacement
                else None,
            },
        ) from e
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    return await _out(session, privileged, building.id, out)


class HazardIn(BaseModel):
    place: str
    category: Literal["fire_hazard", "blocked", "violence"] = "fire_hazard"
    text: str | None = None
    dispatcher: str | None = None


@router.post("/buildings/{building_id}/hazards", dependencies=[Depends(require_dispatcher)])
async def add_hazard(building_id: str, body: HazardIn, session: Session) -> dict:
    building = _building(building_id)
    place = (
        ("exit", body.place)
        if building.exit(body.place)
        else ("zone", body.place)
        if building.zone(body.place)
        else loc.match_place(building, body.place)
    )
    if not place:
        raise HTTPException(422, "Unknown place; use a zone or exit from the building profile")
    kind, pid = place
    h = Hazard(
        building_id=building.id,
        category=body.category,
        source="dispatcher",
        zone_id=pid if kind == "zone" else building.exit(pid).zone,
        exit_id=pid if kind == "exit" else None,
        text=body.text or f"Marked by {body.dispatcher or 'dispatcher'}",
        verification=Verification.dispatcher_verified,
        verified_by=body.dispatcher,
    )
    session.add(h)
    await session.commit()
    await dispatch.hazards_changed(session, building)
    return {"hazard_id": h.id}


@router.post("/hazards/{hazard_id}/{action}", dependencies=[Depends(require_dispatcher)])
async def hazard_action(
    hazard_id: str,
    action: Literal["verify", "clear"],
    session: Session,
    dispatcher: str = "dispatcher",
) -> dict:
    h = await session.get(Hazard, hazard_id)
    if h is None:
        raise HTTPException(404, "Unknown hazard")
    if action == "verify":
        h.verification, h.verified_by = Verification.dispatcher_verified, dispatcher
    else:
        h.active = False
    await session.commit()
    await dispatch.hazards_changed(session, _building(h.building_id))
    await hub.publish(f"hazard.{action}", building_id=h.building_id, data={"hazard_id": h.id})
    return {"hazard_id": h.id, "active": h.active, "verification": h.verification.value}


class IncidentAction(BaseModel):
    dispatcher: str = Field(min_length=1, max_length=64)
    unit: str | None = None


async def _incident(session: AsyncSession, incident_id: str) -> Incident:
    inc = await session.get(Incident, incident_id)
    if inc is None:
        raise HTTPException(404, "Unknown incident")
    return inc


@router.post("/incidents/{incident_id}/{action}")
async def incident_action(
    incident_id: str,
    action: Literal["acknowledge", "assign"],
    body: IncidentAction,
    session: Session,
    privileged: Privileged,
) -> dict:
    inc = await _incident(session, incident_id)
    await _drill_only(session, privileged, inc.building_id)
    if action == "acknowledge":
        inc.acknowledged_by = body.dispatcher
        note = f"Acknowledged by {body.dispatcher}"
    else:
        inc.assigned_unit = body.unit or inc.assigned_unit
        note = f"{body.unit} assigned by {body.dispatcher}"
    inc.updated_at = utcnow()
    await session.commit()
    await intake.add_event(session, inc, "note", role="dispatcher", text=note)
    await hub.publish(
        "incident.updated",
        building_id=inc.building_id,
        incident_id=inc.id,
        data=intake.incident_out(inc),
    )
    return await _out(session, privileged, inc.building_id, intake.incident_out(inc))


@router.post("/incidents/{incident_id}/handoff/{action}")
async def handoff_action(
    incident_id: str,
    action: Literal["join", "resolve"],
    body: IncidentAction,
    session: Session,
    privileged: Privileged,
) -> dict:
    inc = await _incident(session, incident_id)
    await _drill_only(session, privileged, inc.building_id)
    if action == "join":
        out = await dispatch.join_handoff(
            session, inc, body.dispatcher, get_settings().dispatcher_phone
        )
    else:
        out = await dispatch.resolve_handoff(session, inc, body.dispatcher)
    return await _out(session, privileged, inc.building_id, out)


@router.post("/occupants/{occupant_id}/{action}")
@limiter.limit("60/minute")
async def occupant_action(
    request: Request,
    occupant_id: str,
    action: Literal["retext", "call"],
    body: IncidentAction,
    session: Session,
    privileged: Privileged,
) -> dict:
    """From the dispatcher's queue: re-text someone the route they're approved for (e.g. they said
    they're heading to an unsafe exit), or have the messenger call them now."""
    occ = await session.get(Occupant, occupant_id)
    if occ is None:
        raise HTTPException(404, "Unknown person")
    building = _building(occ.building_id)
    await _drill_only(session, privileged, building.id)
    if action == "retext":
        reply = await dispatch.reply_for(session, building, occ)
        message = reply["instruction"]["message"]
        if not message:
            raise HTTPException(409, "No active evacuation to re-text")
        occ.last_instruction = message
        await session.commit()
        await hub.send_texts(
            building.id,
            [
                {
                    "phone": occ.phone,
                    "name": occ.name,
                    "message": message,
                    "exit_id": reply["instruction"].get("exit_id"),
                }
            ],
            reason="retext",
            drill=reply["drill"],
            by="dispatcher",
            dispatcher=body.dispatcher,
        )
        return await _out(session, privileged, building.id, {"ok": True, "message": message})
    if not privileged and occ.call_requested_at is not None:
        # one call per person per drill from the public console (each one rings a real phone)
        raise HTTPException(409, "A call to this person is already requested in this drill")
    occ.call_requested_at = utcnow()
    await session.commit()
    await hub.publish(
        "occupant.call_requested",
        building_id=building.id,
        data={
            "phone": occ.phone,
            "name": occ.name,
            "mobility": occ.mobility,
            "reason": f"dispatcher {body.dispatcher} asked for a call",
            "last_instruction": occ.last_instruction,
        },
    )
    return {"ok": True}


# ---------------------------------------------------------------- live incident report


@router.get("/buildings/{building_id}/report")
async def get_report(building_id: str, session: Session, privileged: Privileged) -> dict:
    building = _building(building_id)
    return await _out(session, privileged, building.id, await report.build(session, building))


@router.get("/buildings/{building_id}/report.md", response_class=PlainTextResponse)
async def get_report_md(building_id: str, session: Session, privileged: Privileged) -> str:
    building = _building(building_id)
    data = await _out(session, privileged, building.id, await report.build(session, building))
    return report.markdown(data)


# ---------------------------------------------------------------- CREAO command staff

_deliveries: list[str] = []


def _summary(body: dict) -> str:
    """CREAO's callback: {"runId", "status", "result": {"text", "chatText", "artifacts"}}. The chat reply
    is the agent's own words; result.text can be its structured output."""
    for key in ("chatText", "summary", "output", "result", "message", "text"):
        v = body.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()[:1000]
        if isinstance(v, dict) and (inner := _summary(v)) != "CREAO run finished":
            return inner
    return "CREAO run finished"


@router.post("/creao/run-result")
@limiter.exempt
async def creao_run_result(
    request: Request,
    session: Session,
    push: str,
    token: str | None = None,
    x_creao_delivery_id: str | None = Header(None),
) -> dict:
    expected = get_settings().creao_webhook_token
    if expected and not (token and hmac.compare_digest(token, expected)):
        raise HTTPException(401, "Invalid token")
    if x_creao_delivery_id:  # CREAO delivers at least once
        if x_creao_delivery_id in _deliveries:
            return {"received": True, "duplicate": True}
        _deliveries.append(x_creao_delivery_id)
        del _deliveries[:-1000]
    body = json.loads(await request.body() or b"{}")
    run = await session.get(AgentRun, push)
    if run is None:
        raise HTTPException(404, "Unknown run")
    if run.status not in ("done", "failed"):
        # CREAO has no custom connector: the agent's tool calls come back in its reply
        if ran := await bridge.apply_actions(run, body):
            await session.refresh(run)
            ok = sum(1 for a in ran if a.get("ok"))
            await agents.record_action(
                session, run, "actions", f"Aria ran {ok} of {len(ran)} action(s) from the reply"
            )
    if run.status not in ("done", "failed"):
        failed = str(body.get("status", "")).lower() in ("failed", "error")
        await agents.finish_run(
            session, run, summary=_summary(body), error=_summary(body) if failed else None
        )
    return {"received": True}


@router.get("/buildings/{building_id}/staff")
async def staff(building_id: str, session: Session, privileged: Privileged) -> dict:
    building = _building(building_id)
    overview = await agents.staff_overview(session, building.id, set(bridge.deployed()))
    return await _out(session, privileged, building.id, overview)


# ---------------------------------------------------------------- live view (demo / testing)

_VIEW = Path(__file__).resolve().parent.parent / "creao" / "view.html"


@router.get("/view", response_class=HTMLResponse, include_in_schema=False)
@limiter.exempt
async def view() -> HTMLResponse:
    """A live map of the layer (pins, exits, roll call, approvals, CREAO staff). Open: no key needed
    to watch or run a drill; a dispatcher key (in its menu) unlocks live mode and full names."""
    return HTMLResponse(_VIEW.read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache"})


@router.get("/buildings")
async def buildings_list() -> list[dict]:
    default = default_building()
    return [
        {"id": b.id, "name": b.name, "default": b.id == (default and default.id)}
        for b in all_buildings().values()
    ]


@router.get("/buildings/{building_id}")
async def building_profile(building_id: str) -> dict:
    return _building(building_id).model_dump(mode="json")


@router.get("/buildings/{building_id}/brief")
async def building_brief(building_id: str) -> dict:
    """Plain-text layout facts for the phone agent (floors, rooms, every exit, the stairs), from
    the profile generated from the engine's venue model."""
    return brief.brief(_building(building_id).id)


SCANS = Path(__file__).resolve().parents[3] / "web" / "public" / "scans"


@router.get("/scans/{name:path}")
async def get_scan(name: str) -> FileResponse:
    """A scan in apps/web/public/scans (gitignored), for the console's 3D map. Open like the
    console; the web app already shows the same scan publicly."""
    path = (SCANS / name).resolve()
    if (
        not re.fullmatch(r"[\w-]+(/[\w-]+)*\.glb", name)
        or SCANS.resolve() not in path.parents
        or not path.is_file()
    ):
        raise HTTPException(404, "Scan not found")
    return FileResponse(path, media_type="model/gltf-binary")


@router.get("/incidents/{incident_id}/report")
async def get_incident_report(incident_id: str, session: Session, privileged: Privileged) -> dict:
    """What opens when the dispatcher clicks a pin: the incident with its CREAO report and timeline."""
    inc = await _incident(session, incident_id)
    out = await report.incident_report(session, _building(inc.building_id), inc)
    return await _out(session, privileged, inc.building_id, out)
