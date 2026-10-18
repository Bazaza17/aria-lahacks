"""Intake: what callers and texters tell Aria through ElevenLabs + Photon, written into TigerData.

Each caller (voice) or texter who reports something becomes an incident: a pin on the scan with a
severity, a headline and a position. Every line they say is an incident_event; every roll-call
change is an evac_event; every place-tied hazard is a hazard row. The TigerData triggers stream
each of those rows to the dashboard and the CREAO orchestrator the moment they're written.
"""

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.creao import hub, rules
from app.creao import location as loc
from app.creao.buildings import Building
from app.creao.db import utcnow
from app.creao.models import (
    EvacEvent,
    Hazard,
    Incident,
    IncidentEvent,
    Occupant,
    OccupantStatus,
    Severity,
    Verification,
)

HAZARD_WINDOW = timedelta(hours=2)  # the same hazard reported again within this window refreshes it


def incident_out(i: Incident) -> dict[str, Any]:
    return {
        "id": i.id,
        "building_id": i.building_id,
        "channel": i.channel,
        "caller": i.caller,
        "status": i.status,
        "severity": i.severity.value,
        "priority": rules.PRIORITY[i.severity],
        "headline": i.headline or ("Caller on the line" if i.channel == "voice" else "Text thread"),
        "category": i.category,
        "facts": i.facts or {},
        "location": i.location,
        "handoff": i.handoff,
        "acknowledged_by": i.acknowledged_by,
        "assigned_unit": i.assigned_unit,
        "started_at": i.started_at.isoformat(),
        "updated_at": i.updated_at.isoformat() if i.updated_at else None,
    }


async def _changed(i: Incident) -> None:
    await hub.publish(
        "incident.updated", building_id=i.building_id, incident_id=i.id, data=incident_out(i)
    )


# ---------------------------------------------------------------- incidents


async def get_incident(
    session: AsyncSession,
    building: Building,
    *,
    conversation_id: str | None = None,
    caller: str | None = None,
    channel: str = "voice",
) -> Incident:
    """The caller's incident: by ElevenLabs conversation id, else their open text thread, else new."""
    inc = None
    if conversation_id:
        inc = await session.scalar(
            select(Incident).where(Incident.conversation_id == conversation_id)
        )
    if inc is None and caller and channel == "sms":
        inc = await session.scalar(
            select(Incident)
            .where(
                Incident.building_id == building.id,
                Incident.caller == caller,
                Incident.channel == "sms",
                Incident.status == "active",
            )
            .limit(1)
        )
    if inc is None:
        inc = Incident(
            building_id=building.id,
            conversation_id=conversation_id,
            caller=caller,
            channel=channel,
            severity=Severity.low,
            facts={},
        )
        session.add(inc)
        await session.commit()
        await add_event(
            session,
            inc,
            "status",
            role="system",
            text=f"{'Call' if channel == 'voice' else 'Text thread'} started",
        )
        await _changed(inc)
    return inc


async def add_event(
    session: AsyncSession,
    inc: Incident,
    kind: str,
    *,
    role: str | None = None,
    text: str | None = None,
    data: dict | None = None,
) -> IncidentEvent:
    ev = IncidentEvent(
        incident_id=inc.id,
        building_id=inc.building_id,
        kind=kind,
        role=role,
        text=text,
        data=data or {},
    )
    session.add(ev)
    await session.commit()  # the TigerData trigger streams it from here
    return ev


async def set_location(session: AsyncSession, inc: Incident, found: loc.Location) -> bool:
    if found.source == "building" or not loc.better(inc.location, found):
        return False
    inc.location = found.as_dict()
    await session.commit()
    return True


async def caller_said(
    session: AsyncSession,
    building: Building,
    inc: Incident,
    text: str,
    *,
    role: str = "caller",
    source: str = "call",
) -> dict:
    """One line from the caller or texter: log it, then raise severity, pin them, pin hazards."""
    await add_event(
        session, inc, "transcript" if source == "call" else "sms_in", role=role, text=text
    )
    if role != "caller":
        return {"hits": [], "hazards": []}
    hits = rules.risk(text)
    changed = False
    if hits:
        severity = rules.top_severity(inc.severity, *(sev for _c, sev, _w in hits))
        if severity != inc.severity:
            inc.severity, changed = severity, True
        if not inc.category:
            inc.category = hits[0][0]
        await add_event(
            session,
            inc,
            "flag",
            role="system",
            text=", ".join(f"{c}: “{w}”" for c, _s, w in hits),
            data={"hits": [{"category": c, "severity": s.value, "matched": w} for c, s, w in hits]},
        )
    if not inc.headline and (hits or len(text) > 25):
        inc.headline, changed = text.strip()[:140], True
    changed |= await set_location(session, inc, loc.from_text(building, text))
    hazards = await report_hazards(session, building, text, source=source)
    if changed:
        await session.commit()
        await _changed(inc)
    from app.creao import dispatch

    await dispatch.check_handoff(session, building, inc, text)
    return {"hits": hits, "hazards": hazards}


async def details(
    session: AsyncSession, building: Building, inc: Incident, facts: dict
) -> Incident:
    """The ElevenLabs agent's log_incident_details: description, category, place, injuries, urgency."""
    facts = {k: v for k, v in facts.items() if v not in (None, "", [])}
    inc.facts = {**(inc.facts or {}), **facts}
    if facts.get("description"):
        inc.headline = str(facts["description"])[:140]
    if facts.get("category"):
        inc.category = str(facts["category"])[:32]
    urgency = {"critical": Severity.critical, "high": Severity.high, "medium": Severity.medium}.get(
        str(facts.get("urgency", "")).lower()
    )
    text = " ".join(str(facts[k]) for k in ("description", "injuries", "hazards") if facts.get(k))
    inc.severity = rules.top_severity(
        inc.severity, urgency, *(sev for _c, sev, _w in rules.risk(text))
    )
    place = " ".join(str(facts[k]) for k in ("zone", "location") if facts.get(k))
    await set_location(session, inc, loc.from_text(building, place or text, facts.get("floor")))
    await session.commit()
    await add_event(session, inc, "detail", role="agent", text=inc.headline, data=facts)
    await report_hazards(
        session,
        building,
        " ".join(filter(None, [place, str(facts.get("hazards") or "")])) or None,
        source="call",
    )
    await _changed(inc)
    return inc


async def end_incident(session: AsyncSession, inc: Incident, reason: str | None = None) -> None:
    if inc.status == "ended":
        return
    note = f"Call ended{': ' + reason if reason else ''}"
    if (inc.handoff or {}).get("status") in ("requested", "transferred", "joined"):
        # With a human now (or waiting for one): the AI call is over, the incident isn't
        await add_event(session, inc, "status", role="system", text=note)
        return
    inc.status, inc.ended_at = "ended", utcnow()
    await session.commit()
    await add_event(session, inc, "status", role="system", text=note)
    await _changed(inc)


# ---------------------------------------------------------------- hazards


async def report_hazards(
    session: AsyncSession, building: Building, text: str | None, *, source: str
) -> list[Hazard]:
    """'Smoke by the loading dock' -> a REPORTED hazard there. No named place, no pin."""
    place = loc.match_place(building, text)
    hits = rules.hazard_hits(text)
    if not (place and hits):
        return []
    kind, pid = place
    exit_id = pid if kind == "exit" else next((e.id for e in building.exits if e.zone == pid), None)
    zone_id = pid if kind == "zone" else building.exit(pid).zone
    created = []
    for category, _words in hits:
        recent = await session.scalar(
            select(Hazard)
            .where(
                Hazard.building_id == building.id,
                Hazard.active.is_(True),
                Hazard.category == category,
                Hazard.zone_id == zone_id,
                Hazard.exit_id == exit_id,
                Hazard.created_at >= utcnow() - HAZARD_WINDOW,
            )
            .limit(1)
        )
        if recent:
            if (
                recent.verification == Verification.reported
            ):  # never put a caller's words on a verified hazard
                recent.text = text[:500]
            continue
        h = Hazard(
            building_id=building.id,
            zone_id=zone_id,
            exit_id=exit_id,
            category=category,
            text=text[:500],
            source=source,
            verification=Verification.reported,
        )
        session.add(h)
        created.append(h)
    await session.commit()  # each new row is streamed by its trigger
    if created:
        from app.creao import plan

        await plan.bump_hazards(session, building)  # re-check routes; changes are proposals only
    return created


# ---------------------------------------------------------------- roll call


async def _occupant(session: AsyncSession, building_id: str, phone: str) -> Occupant:
    occ = await session.scalar(
        select(Occupant).where(Occupant.building_id == building_id, Occupant.phone == phone)
    )
    if occ is None:
        occ = Occupant(
            building_id=building_id, phone=phone, mobility=[], status=OccupantStatus.unconfirmed
        )
        session.add(occ)
    return occ


async def register_occupants(session: AsyncSession, building: Building, people: list[dict]) -> int:
    for p in people:
        occ = await _occupant(session, building.id, p["phone"])
        occ.name = p.get("name") or occ.name
        if p.get("mobility"):
            occ.mobility = list(p["mobility"])
        found = loc.from_text(building, p.get("zone"), p.get("floor"))
        if found.source not in ("building",) and loc.better(occ.location, found):
            occ.location = found.as_dict()
    await session.commit()
    await hub.publish("roll_call.registered", building_id=building.id, data={"count": len(people)})
    return len(people)


async def occupant_update(
    session: AsyncSession,
    building: Building,
    *,
    phone: str,
    text: str | None = None,
    status: str | None = None,
    exit: str | None = None,
    place: str | None = None,
    floor: Any = None,
    lat: float | None = None,
    lng: float | None = None,
    accuracy_m: float | None = None,
    mobility: list[str] | None = None,
    name: str | None = None,
    incident: Incident | None = None,
    source: str = "sms",
) -> Occupant:
    """A text, a status from the voice agent, or a location from someone in the building."""
    occ = await _occupant(session, building.id, phone)
    before = (occ.status, occ.exit_id)
    occ.name = name or occ.name
    occ.last_contact_at = utcnow()
    if mobility:
        occ.mobility = sorted(set(occ.mobility or []) | set(mobility))
    word = (status or "").strip().lower()
    first = text.strip().split()[0].strip(".,!:").upper() if text and text.strip() else ""
    if not word and first in ("SAFE", "HELP", "CALL"):
        word = (
            first.lower()
        )  # the alert asks people to reply SAFE / HELP / CALL (maybe with more words)
    intent = rules.reply_intent(text) if not word else None
    if intent == "safe" or (not word and first in ("SAFE", "OUT")):
        word = "safe"  # "I'm outside", "I'm safe"
    new_status = rules.STATUS_WORDS.get(word)
    if new_status is None and occ.status == OccupantStatus.unconfirmed:
        new_status = OccupantStatus.contacted  # any reply means contact; never assume safe
    if new_status:
        occ.status = new_status
    # "2" / "which way do I go": ElevenLabs calls them and walks them out (texts only, never mid-call)
    guide = intent == "directions" and source == "sms" and occ.call_requested_at is None
    asked = word == "call" and source == "sms"
    if (asked or guide) and occ.call_requested_at is None:
        occ.call_requested_at = utcnow()
    if exit_id := loc.match_exit(building, exit) or loc.match_exit(building, text):
        occ.exit_id = exit_id
    if occ.status == OccupantStatus.confirmed_safe and not occ.exit_id:
        occ.exit_id = building.assembly_exit_id
    if lat is not None and lng is not None:
        found = loc.from_gps(
            building, lat, lng, accuracy_m, floor if isinstance(floor, int) else None
        )
    else:
        found = loc.from_text(building, " ".join(filter(None, [place, text])), floor)
    # Naming an exit when we already know their room says where they're heading, not where they are
    heading = found.source == "exit" and (occ.location or {}).get("source") == "zone"
    if found.source != "building" and not heading and loc.better(occ.location, found):
        occ.location = found.as_dict()
    await session.flush()
    if (
        occ.status,
        occ.exit_id,
    ) != before:  # the time series behind exit flow (streamed by trigger)
        session.add(
            EvacEvent(
                building_id=building.id,
                occupant_id=occ.id,
                status=occ.status.value,
                exit_id=occ.exit_id,
            )
        )
    await session.commit()

    # Someone who needs help, says their life is at risk, or reports a hazard gets an incident (a pin).
    said = " ".join(filter(None, [place, text]))
    if incident is None and (
        occ.status == OccupantStatus.needs_help
        or rules.LIFE_THREAT.search(said)
        or rules.hazard_hits(said)
    ):
        incident = await get_incident(session, building, caller=phone, channel="sms")
    if incident is not None:
        if occ.incident_id != incident.id:
            occ.incident_id = incident.id
            await session.commit()
        if occ.location:  # the incident pin follows the person
            await set_location(
                session,
                incident,
                loc.Location(**{**occ.location, "anchor": loc.Anchor(**occ.location["anchor"])}),
            )
        if (
            occ.status == OccupantStatus.needs_help
            and rules.RANK[incident.severity] < rules.RANK[Severity.high]
        ):
            incident.severity = Severity.high
            incident.headline = (
                incident.headline
                or f"{occ.name or phone} needs help evacuating"
                + (f" ({', '.join(occ.mobility)})" if occ.mobility else "")
            )
            await session.commit()
            await _changed(incident)
        if said:
            await caller_said(session, building, incident, said, source=source)
    elif said:
        await report_hazards(session, building, said, source=source)
    if word == "help" and source == "sms" and incident is not None:
        from app.creao import dispatch  # noqa: PLC0415  (dispatch imports intake)

        await dispatch.request_handoff(
            session, building, incident, reason="replied HELP (hurt or trapped)"
        )
    if asked or guide:
        await hub.publish(
            "occupant.call_requested",
            building_id=building.id,
            data={
                "phone": phone,
                "name": occ.name,
                "reason": "replied CALL" if word == "call" else "asked for help finding an exit",
                "last_instruction": occ.last_instruction,
                "mobility": occ.mobility,
            },
        )
    return occ
