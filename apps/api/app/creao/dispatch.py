"""Dispatcher management for first responders: drills and fires, approved routes, human handoffs.

- start(): declare a fire or a labeled drill. Each zone gets an approved exit (the safe, least
  crowded nearest one); every occupant gets the message for their zone (Sai's pipeline texts them).
- With an origin, the fire model comes from Aria's building engine (engine_model): when each
  zone fills with smoke, when each exit is lost, and the engine's route for every zone.
- Hazards and the fire model mark exits unsafe; the rules propose route changes. Nothing
  reaches occupants until a dispatcher approves (plan.decide).
- Life-threat words put a human dispatcher on the call, with a brief so they never re-ask.
- People who ignore the alert for CHASE_AFTER get a voice call (Sai's pipeline places it).
"""

from datetime import timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.creao import engine_model, hub, plan, rules
from app.creao import location as loc
from app.creao.buildings import Building, get_building
from app.creao.db import utcnow
from app.creao.intake import HAZARD_WINDOW, add_event, incident_out
from app.creao.models import (
    Evacuation,
    Hazard,
    Incident,
    IncidentEvent,
    Occupant,
    OccupantStatus,
    ProposalStatus,
    RouteProposal,
    Severity,
    Verification,
)
from app.creao.situation import evacuation_out

CHASE_AFTER = timedelta(seconds=60)


# ---------------------------------------------------------------- fires and drills


async def start(
    session: AsyncSession,
    building: Building,
    *,
    mode: str,
    origin: str | None,
    description: str | None,
    dispatcher: str | None,
    fire_model: dict | None,
    growth: str | None = None,
) -> dict[str, Any]:
    engine = None
    if not fire_model and origin:  # the engine's fire for the declared origin (simulation)
        engine = await engine_model.fire_model_for(building, origin, growth)
    for old in (
        await session.execute(
            select(Evacuation).where(
                Evacuation.building_id == building.id, Evacuation.status == "active"
            )
        )
    ).scalars():
        old.status, old.ended_at = "ended", utcnow()
        await session.execute(
            update(RouteProposal)
            .where(
                RouteProposal.evacuation_id == old.id,
                RouteProposal.status == ProposalStatus.proposed,
            )
            .values(status=ProposalStatus.stale)
        )
    # A new incident starts from a clean hazard map.
    await session.execute(
        update(Hazard)
        .where(Hazard.building_id == building.id, Hazard.active.is_(True))
        .values(active=False)
    )
    if engine:
        oz = building.zone(engine["origin"]["zone_id"])
        place = ("zone", oz.id) if oz else None
    else:
        place = loc.match_place(building, origin) if origin else None
    item = (
        (building.exit(place[1]) if place[0] == "exit" else building.zone(place[1]))
        if place
        else None
    )
    ev = Evacuation(
        building_id=building.id,
        mode="live" if mode == "live" else "drill",
        description=description,
        origin_zone=place[1] if place and place[0] == "zone" else (item.zone if item else None),
        origin_exit=place[1] if place and place[0] == "exit" else None,
        origin_label=item.label if item else origin,
        started_by=dispatcher,
        approved_routes={},
        report={},
        fire_model=engine
        or (plan.normalize_fire_model(building, fire_model) if fire_model else None),
    )
    session.add(ev)
    # The declared fire is a verified hazard. With the engine's model, the engine times the
    # origin's exits itself (when each is lost), so its doors aren't closed from minute 0.
    if item and not engine:
        session.add(
            Hazard(
                building_id=building.id,
                zone_id=ev.origin_zone,
                exit_id=ev.origin_exit,
                category="fire_hazard",
                text=description or f"Fire declared at {item.label}",
                source="dispatcher",
                verification=Verification.dispatcher_verified,
                verified_by=dispatcher,
            )
        )
    await session.commit()

    ev.approved_routes = await plan.initial_plan(session, building, ev)
    now, recipients = utcnow(), []
    # The first text asks one question: can you get out, or do you need help finding an exit?
    drill = "DRILL: " if ev.mode == "drill" else ""
    alert = f"{drill}Fire reported at {ev.origin_label or 'the building'}. {rules.ALERT_QUESTION}"
    for occ in (
        await session.execute(select(Occupant).where(Occupant.building_id == building.id))
    ).scalars():
        occ.status, occ.exit_id, occ.call_requested_at = OccupantStatus.unconfirmed, None, None
        occ.alerted_at, occ.last_contact_at = now, None
        occ.last_instruction = alert
        route = plan.instruction(building, ev, occ.location)  # what they're told once they answer
        recipients.append(
            {
                "phone": occ.phone,
                "name": occ.name,
                "message": alert,
                "route": route["message"],
                "exit_id": route["exit_id"],
                "mobility": occ.mobility,
            }
        )
    await session.commit()
    payload = {"evacuation": evacuation_out(ev, building), "recipients": recipients}
    await hub.publish(
        "evacuation.started",
        building_id=building.id,
        data={"evacuation": payload["evacuation"], "recipients_count": len(recipients)},
    )
    await hub.send_texts(building.id, recipients, reason="alert", drill=ev.mode != "live")
    return payload


async def end(session: AsyncSession, ev: Evacuation) -> None:
    """End it, keep an after-action draft read from TigerData, clear the console, brief the Scribe."""
    from app.creao import after_action

    building = get_building(ev.building_id)
    facts = await after_action.freeze(session, building, ev) if building else None
    ev.status, ev.ended_at = "ended", utcnow()
    if facts:
        ev.report = {
            **(ev.report or {}),
            "after_action_facts": facts,
            "after_action": {
                "text": after_action.draft(facts),
                "role": "aria",
                "by": "Aria (automatic, from TigerData)",
                "at": utcnow().isoformat(),
                "automatic": True,
            },
        }
    await session.execute(
        update(RouteProposal)
        .where(
            RouteProposal.evacuation_id == ev.id, RouteProposal.status == ProposalStatus.proposed
        )
        .values(status=ProposalStatus.stale)
    )
    await session.commit()
    await after_action.clear(session, ev.building_id, f"{ev.mode} ended")
    await hub.publish(
        "evacuation.ended",
        building_id=ev.building_id,
        data={"evacuation_id": ev.id, "after_action": bool(facts)},
    )
    if facts:
        after_action.brief_scribe(ev.building_id, facts)


async def set_fire_model(session: AsyncSession, building: Building, model: dict) -> dict:
    """A hand-typed step model, or {"engine": {"start": space or place, "growth": "fast"}}."""
    ev = await plan.active_evacuation(session, building.id)
    if ev is None:
        raise LookupError("No active evacuation for this building")
    if isinstance(model.get("engine"), dict):
        spec = model["engine"]
        engine = await engine_model.fire_model_for(building, spec.get("start"), spec.get("growth"))
        if engine is None:
            raise ValueError(f"No engine start space for {spec.get('start')!r}; see /engine/starts")
        ev.fire_model = engine
        if not ev.origin_label:
            ev.origin_label = engine["origin"]["label"]
            ev.origin_zone = engine["origin"]["zone_id"]
    else:
        ev.fire_model = plan.normalize_fire_model(building, model)
    await session.commit()
    await hub.publish(
        "fire_model.updated", building_id=building.id, data={"steps": len(ev.fire_model["steps"])}
    )
    await plan.bump_hazards(session, building)
    return ev.fire_model


async def hazards_changed(session: AsyncSession, building: Building) -> None:
    """New hazard picture: re-check every zone's approved exit (proposals only)."""
    await plan.bump_hazards(session, building)


# How the answer to the alert opens, by what they replied (rules, not the AI, answer these)
LEADS = {
    "evacuating": "Good, keep going",
    "directions": "We're calling you now to walk you out",
}


async def reply_for(
    session: AsyncSession, building: Building, occ: Occupant, intent: str | None = None
) -> dict[str, Any]:
    """What to tell this person: only the approved route for where they are. When their reply was
    an answer to the alert (1, 2, HELP, SAFE), `answer` is the exact text to send back."""
    ev = await plan.active_evacuation(session, building.id)
    first_contact = False
    if ev is not None and occ.alerted_at is None:
        # Someone we'd never alerted texts during the evacuation: they count as alerted now and
        # get the current instruction straight back, like everyone who got the alert
        occ.alerted_at, first_contact = utcnow(), True
    instruction = plan.instruction(building, ev, occ.location, lead=LEADS.get(intent))
    pending = (
        await session.scalar(
            select(RouteProposal.id)
            .where(
                RouteProposal.building_id == building.id,
                RouteProposal.status == ProposalStatus.proposed,
                RouteProposal.zone_id == instruction.get("zone_id"),
            )
            .limit(1)
        )
        if ev and instruction.get("zone_id")
        else None
    )
    states = await plan.exit_states(session, building, ev)
    chosen = states.get(occ.exit_id) if occ.exit_id else None
    if ev is not None:
        instruction = _safer(building, ev, occ, instruction, states)
    answered = ev is not None and (
        first_contact or intent in ("evacuating", "directions", "help", "safe")
    )
    if first_contact:
        occ.last_instruction = instruction["message"]
        await session.commit()
    return {
        "status": occ.status.value,
        "first_contact": first_contact,
        "drill": ev is not None and ev.mode != "live",
        "answer": instruction["message"] if answered else None,
        "instruction": instruction,  # send this, nothing else
        "route_change_pending": bool(pending),
        "exit": {
            "id": occ.exit_id,
            "label": chosen.label,
            "unsafe": chosen.unsafe,
            "reasons": chosen.reasons,
        }
        if chosen
        else None,
    }


def _safer(
    building: Building, ev: Evacuation, occ: Occupant, instruction: dict, states: dict
) -> dict:
    """The approved instruction, adjusted for who this person is right now. Never sends someone
    who is out back in, someone who asked for help down the stairs, or anyone toward an exit that
    was just reported unsafe while its route change waits for the dispatcher."""
    drill = "DRILL: " if ev.mode == "drill" else ""
    if occ.status == OccupantStatus.confirmed_safe:
        return {
            **instruction,
            "exit_id": None,
            "exit_label": None,
            "message": f"{drill}Thanks, you're marked safe. Stay {plan.assembly_words(building)}, and tell "
            "responders if you know anyone still inside.",
        }
    if occ.status == OccupantStatus.needs_help:
        where = (occ.location or {}).get("label")
        return {
            **instruction,
            "exit_id": None,
            "exit_label": None,
            "message": f"{drill}Help is coming{' to ' + where if where else ''}. If it's safe where you are, stay "
            "there, close the door and keep low. Reply with any change, or CALL to talk to us.",
        }
    exit_id = instruction.get("exit_id")
    if exit_id and states.get(exit_id) and states[exit_id].unsafe:
        others = [
            building.exit(x)
            for x in plan.approved_exits(ev)
            if x != exit_id and not states[x].unsafe
        ]
        reason = "; ".join(states[exit_id].reasons) or "reported unsafe"
        go = (
            f"Leave by the nearest of: {', '.join(e.label for e in others)}."
            if others
            else ("Stay where you are, close the door and keep low; responders know where you are.")
        )
        return {
            **instruction,
            "exit_id": None,
            "exit_label": None,
            "warning": reason,
            "message": f"{drill}Avoid {states[exit_id].label} ({reason}). {go} A dispatcher is confirming your "
            "new route. Reply SAFE, HELP, or CALL.",
        }
    return instruction


# ---------------------------------------------------------------- chase people who don't reply


async def chase(session: AsyncSession) -> list[dict]:
    cutoff, chased = utcnow() - CHASE_AFTER, []
    for ev in (
        (await session.execute(select(Evacuation).where(Evacuation.status == "active")))
        .scalars()
        .all()
    ):
        due = (
            (
                await session.execute(
                    select(Occupant).where(
                        Occupant.building_id == ev.building_id,
                        Occupant.status == OccupantStatus.unconfirmed,
                        Occupant.alerted_at.is_not(None),
                        Occupant.alerted_at <= cutoff,
                        Occupant.last_contact_at.is_(None),
                        Occupant.call_requested_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        batch = []
        for occ in due:
            claimed = await session.execute(
                update(Occupant)
                .where(  # atomic: replicas never double-call
                    Occupant.id == occ.id, Occupant.call_requested_at.is_(None)
                )
                .values(call_requested_at=utcnow())
            )
            if claimed.rowcount:
                batch.append(
                    {
                        "phone": occ.phone,
                        "name": occ.name,
                        "mobility": occ.mobility,
                        "reason": "no reply to the evacuation alert",
                        "last_instruction": occ.last_instruction,
                    }
                )
        await session.commit()
        for item in batch:
            await hub.publish("occupant.call_requested", building_id=ev.building_id, data=item)
        chased.extend(batch)
    return chased


# ---------------------------------------------------------------- human handoff


async def affected_zone(
    session: AsyncSession, building: Building, location: dict | None
) -> str | None:
    zone_id = plan.zone_for(building, location)
    if not zone_id:
        return None
    hazard = await session.scalar(
        select(Hazard)
        .where(
            Hazard.building_id == building.id,
            Hazard.active.is_(True),
            Hazard.zone_id == zone_id,
            Hazard.created_at >= utcnow() - HAZARD_WINDOW,
        )
        .limit(1)
    )
    if hazard:
        return f"{rules.HAZARD_CATEGORIES.get(hazard.category, hazard.category)} reported in {building.zone(zone_id).label}"
    ev = await plan.active_evacuation(session, building.id)
    if ev and ev.fire_model:
        for step in ev.fire_model["steps"]:
            if step["place"] == zone_id and step["minute"] <= plan.minute_now(ev):
                return f"fire model: {step['kind']} reached {step['label']} (simulation)"
    return None


async def check_handoff(
    session: AsyncSession, building: Building, inc: Incident, text: str
) -> None:
    """Life-threat words ("trapped", "can't breathe") put a human on the line, wherever they are."""
    m = rules.LIFE_THREAT.search(text)
    critical = [w for c, s, w in rules.risk(text) if s == Severity.critical]
    if m or critical:
        await request_handoff(
            session, building, inc, reason=f'said "{m.group(0) if m else critical[0]}"'
        )


async def request_handoff(
    session: AsyncSession,
    building: Building,
    inc: Incident,
    *,
    reason: str,
    requested_by: str | None = None,
) -> dict:
    handoff = dict(inc.handoff or {})
    first = not handoff or handoff.get("status") == "resolved"
    if first:
        handoff = {"requested_at": utcnow().isoformat(), "reasons": []}
    handoff["reasons"] = list(dict.fromkeys([*handoff.get("reasons", []), reason]))[-5:]
    handoff["status"] = (
        handoff.get("status")
        if handoff.get("status") in ("requested", "joined", "transferred")
        else "requested"
    )
    handoff["brief"] = await brief(session, building, inc)
    inc.handoff = handoff
    inc.severity = Severity.critical
    await session.commit()
    if first:
        await add_event(session, inc, "flag", role="system", text=f"Dispatcher needed: {reason}")
    await hub.publish(
        "handoff.requested",
        building_id=building.id,
        incident_id=inc.id,
        data={"handoff": handoff, "first": first, "requested_by": requested_by},
    )
    await hub.publish(
        "incident.updated", building_id=building.id, incident_id=inc.id, data=incident_out(inc)
    )
    return handoff


async def brief(session: AsyncSession, building: Building, inc: Incident) -> dict[str, Any]:
    """Who, where, condition, needs, what's been said, what they were told, what we don't know."""
    occ = (
        await session.scalar(
            select(Occupant).where(
                Occupant.building_id == building.id, Occupant.phone == inc.caller
            )
        )
        if inc.caller
        else None
    )
    said = (
        (
            await session.execute(
                select(IncidentEvent.text)
                .where(
                    IncidentEvent.incident_id == inc.id,
                    IncidentEvent.kind.in_(("transcript", "sms_in")),
                    IncidentEvent.role == "caller",
                )
                .order_by(IncidentEvent.created_at.desc())
                .limit(4)
            )
        )
        .scalars()
        .all()[::-1]
    )
    location = inc.location or (occ.location if occ else None) or {}
    ev = await plan.active_evacuation(session, building.id)
    danger = await affected_zone(session, building, location)
    facts = inc.facts or {}
    mobility = sorted(set((occ.mobility if occ else []) or []))
    where = location.get("label") or "location unknown"
    if location.get("approx") or not location:
        where += " (approximate; ask for floor and nearest landmark)"
    name = (occ.name if occ else None) or facts.get("people_involved")
    return {
        "name": name,
        "phone": inc.caller,
        "location": where,
        "floor": location.get("floor"),
        "in_affected_zone": danger,
        "condition": facts.get("injuries")
        or facts.get("description")
        or (said[-1] if said else None),
        "mobility": mobility,
        "what_was_said": said,
        "instruction_given": (occ.last_instruction if occ else None)
        or plan.instruction(building, ev, location).get("message"),
        "unknowns": [
            u
            for u, missing in (
                ("exact location", bool(location.get("approx")) or not location),
                ("how many people are with them", "people_involved" not in facts),
            )
            if missing
        ],
        "summary": f"{name or inc.caller or 'Caller'} · {where}"
        + (f" · {danger}" if danger else "")
        + (f" · {', '.join(mobility)}" if mobility else ""),
    }


async def call_transferred(
    session: AsyncSession,
    building: Building,
    inc: Incident,
    *,
    to: str | None,
    reason: str | None,
) -> dict:
    """The voice agent heard a trigger word and moved the call to the dispatcher's line."""
    await request_handoff(
        session, building, inc, reason=f"call moved to dispatcher ({reason or 'trigger word'})"
    )
    handoff = dict(inc.handoff or {})
    handoff.update(status="transferred", transferred_at=utcnow().isoformat(), transfer_to=to)
    inc.handoff = handoff
    await session.commit()
    await add_event(
        session, inc, "status", role="system", text="ElevenLabs moved the call to the dispatcher"
    )
    await hub.publish(
        "handoff.transferred",
        building_id=building.id,
        incident_id=inc.id,
        data={"handoff": handoff, "caller": inc.caller},
    )
    await hub.publish(
        "incident.updated", building_id=building.id, incident_id=inc.id, data=incident_out(inc)
    )
    return handoff


async def join_handoff(
    session: AsyncSession, inc: Incident, dispatcher: str, transfer_to: str | None
) -> dict:
    handoff = dict(inc.handoff or {})
    handoff.update(status="joined", joined_by=dispatcher, joined_at=utcnow().isoformat())
    inc.handoff = handoff
    await session.commit()
    await add_event(
        session, inc, "status", role="dispatcher", text=f"{dispatcher} took over the call"
    )
    # Sai's pipeline transfers the live call to the dispatcher's phone (or calls back).
    await hub.publish(
        "handoff.joined",
        building_id=inc.building_id,
        incident_id=inc.id,
        data={
            "dispatcher": dispatcher,
            "transfer_to": transfer_to,
            "conversation_id": inc.conversation_id,
            "caller": inc.caller,
        },
    )
    return handoff


async def resolve_handoff(session: AsyncSession, inc: Incident, dispatcher: str) -> dict:
    handoff = dict(inc.handoff or {})
    handoff.update(status="resolved", resolved_by=dispatcher, resolved_at=utcnow().isoformat())
    inc.handoff = handoff
    await session.commit()
    await hub.publish(
        "incident.updated", building_id=inc.building_id, incident_id=inc.id, data=incident_out(inc)
    )
    return handoff


async def recheck_routes(session: AsyncSession) -> int:
    """The fire model moves on with the clock (exits get lost, the engine's routes change):
    re-check every active evacuation that has one. Changes are proposals only."""
    n = 0
    for ev in (
        (await session.execute(select(Evacuation).where(Evacuation.status == "active")))
        .scalars()
        .all()
    ):
        # filter here, not in SQL: a None fire model is stored as JSON 'null', not SQL NULL
        if not ev.fire_model:
            continue
        building = get_building(ev.building_id)
        if building:
            n += len(await plan.reevaluate(session, building, ev))
    return n


async def run_chase_loop() -> None:
    import asyncio
    import logging

    from app.creao.db import sessions

    while True:
        await asyncio.sleep(10)
        try:
            async with sessions()() as session:
                await chase(session)
                await recheck_routes(session)
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception("chase loop")


def building_of(inc: Incident) -> Building:
    return get_building(inc.building_id)
