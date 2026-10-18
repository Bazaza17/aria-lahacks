"""The live situation for one building, read from TigerData.

This is what the dispatcher dashboard draws and what the CREAO staff reasons over:
incidents pinned on the scan by priority, exits (open / hazard / predicted, how many people are
heading to each and who's out through it), flows from where people were to the exit they took,
the roll call, hazards, the approved routes and the route changes waiting for a dispatcher.

flow() reads the evac_flow_15s continuous aggregate on TigerData (raw evac_events elsewhere).
"""

from datetime import timedelta
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.creao import comms, db, plan, rules
from app.creao.buildings import Building
from app.creao.db import utcnow
from app.creao.intake import HAZARD_WINDOW, incident_out
from app.creao.models import (
    EvacEvent,
    Evacuation,
    Hazard,
    Incident,
    Occupant,
    OccupantStatus,
    ProposalStatus,
    RouteProposal,
)

LOOKBACK = timedelta(hours=12)


def _anchor(location: dict | None, building: Building) -> dict:
    if location and location.get("anchor"):
        return location["anchor"]
    return {"nx": 0.5, "ny": building.floors[0].ny, "nz": 0.5}


def person_out(
    o: Occupant, building: Building, evacuation: Evacuation | None, states: dict, now
) -> dict[str, Any]:
    """One person for the map and the dispatcher queue: where they are, the exit they were told and
    the exit they say they're using (when it differs). Names only, never phone numbers."""
    told = (
        plan.instruction(building, evacuation, o.location)["exit_id"]
        if evacuation and o.status in (OccupantStatus.unconfirmed, OccupantStatus.contacted)
        else None
    )
    said = o.exit_id if o.status == OccupantStatus.contacted else None
    x = building.exit(said)
    said = said if x and said != told and not x.assembly else None
    silent = o.status == OccupantStatus.unconfirmed and o.alerted_at and not o.last_contact_at
    return {
        "id": o.id,
        "name": o.name or f"…{o.phone[-4:]}",
        "status": o.status.value,
        "anchor": _anchor(o.location, building) if o.location else None,
        "place": (o.location or {}).get("label"),
        "floor": (o.location or {}).get("floor"),
        "approx": bool((o.location or {}).get("approx", True)),
        "exit_id": o.exit_id,
        "told_exit_id": told,
        "said_exit_id": said,
        "heading_unsafe": bool(said and states.get(said) and states[said].unsafe),
        "no_reply_secs": int((now - o.alerted_at).total_seconds()) if silent else None,
        "call_requested": bool(o.call_requested_at),
        "mobility": o.mobility or [],
        "incident_id": o.incident_id,
    }


async def log(
    session: AsyncSession, building: Building, evacuation: Evacuation | None, incidents: list
) -> list[dict]:
    """What a dispatcher needs to see happened, newest first (no agent bookkeeping)."""
    if evacuation is None:
        return []
    out = []
    alerted = await session.scalar(
        select(func.count()).where(
            Occupant.building_id == building.id, Occupant.alerted_at >= evacuation.started_at
        )
    )
    by = f" by {evacuation.started_by}" if evacuation.started_by else ""
    out.append(
        {
            "at": evacuation.started_at.isoformat(),
            "kind": "start",
            "text": f"{evacuation.mode.capitalize()} declared{by} · alert texted to {alerted}",
        }
    )
    for h in (
        await session.execute(
            select(Hazard).where(
                Hazard.building_id == building.id, Hazard.created_at >= evacuation.started_at
            )
        )
    ).scalars():
        place = building.exit(h.exit_id) or building.zone(h.zone_id)
        where = place.label if place else "the building"
        what = rules.HAZARD_CATEGORIES.get(h.category, h.category).lower()
        note = " · verified" if h.verification.value == "verified" else ""
        out.append(
            {
                "at": h.created_at.isoformat(),
                "kind": "hazard",
                "text": f"{what.capitalize()} reported at {where}{note}",
            }
        )
    for p in (
        await session.execute(
            select(RouteProposal).where(
                RouteProposal.evacuation_id == evacuation.id,
                RouteProposal.status.in_([ProposalStatus.approved, ProposalStatus.rejected]),
            )
        )
    ).scalars():
        z, x = building.zone(p.zone_id), building.exit(p.to_exit_id)
        verb = "approved" if p.status == ProposalStatus.approved else "rejected"
        texted = f" · {p.affected} re-texted" if verb == "approved" and p.affected else ""
        out.append(
            {
                "at": (p.decided_at or p.created_at).isoformat(),
                "kind": "route",
                "text": f"Route {z.label if z else p.zone_id} → {x.label if x else 'shelter in place'} {verb}"
                f"{' by ' + p.decided_by if p.decided_by else ''}{texted}",
            }
        )
    for i in incidents:
        h = i.get("handoff") or {}
        if h.get("requested_at"):
            out.append(
                {
                    "at": h["requested_at"],
                    "kind": "handoff",
                    "text": f"Needs a human: {i['headline']}",
                }
            )
        if h.get("transferred_at"):
            out.append(
                {
                    "at": h["transferred_at"],
                    "kind": "handoff",
                    "text": f"Call moved to the dispatcher line: {i['headline']}",
                }
            )
        if h.get("joined_at"):
            out.append(
                {
                    "at": h["joined_at"],
                    "kind": "handoff",
                    "text": f"{h.get('joined_by') or 'Dispatcher'} took over: {i['headline']}",
                }
            )
    safe = (
        await session.execute(
            select(EvacEvent.created_at, Occupant.name, Occupant.phone)
            .join(Occupant, Occupant.id == EvacEvent.occupant_id)
            .where(
                EvacEvent.building_id == building.id,
                EvacEvent.status == OccupantStatus.confirmed_safe.value,
                EvacEvent.created_at >= evacuation.started_at,
            )
        )
    ).all()
    for at, name, phone in safe:
        out.append(
            {
                "at": at.isoformat(),
                "kind": "safe",
                "text": f"{name or '…' + phone[-4:]} confirmed out",
            }
        )
    out.sort(key=lambda e: e["at"], reverse=True)
    return out[:30]


def evacuation_out(e: Evacuation, building: Building) -> dict[str, Any]:
    return {
        "id": e.id,
        "mode": e.mode,
        "status": e.status,
        "origin_label": e.origin_label,
        "description": e.description,
        "started_by": e.started_by,
        "started_at": e.started_at.isoformat(),
        "minute_now": round(plan.minute_now(e), 2),
        "hazard_version": e.hazard_version,
        "approved_routes": [
            {
                "zone_id": z,
                "zone_label": building.zone(z).label if building.zone(z) else z,
                "exit_id": x,
                "exit_label": building.exit(x).label if building.exit(x) else x,
            }
            for z, x in (e.approved_routes or {}).items()
        ],
    }


async def build(session: AsyncSession, building: Building) -> dict[str, Any]:
    now = utcnow()
    evacuation = await plan.active_evacuation(session, building.id)
    rows = (
        (
            await session.execute(
                select(Incident).where(
                    Incident.building_id == building.id,
                    or_(Incident.status == "active", Incident.started_at >= now - LOOKBACK),
                )
            )
        )
        .scalars()
        .all()
    )
    incidents, handoffs = [], []
    for i in rows:
        out = incident_out(i)
        out["location"] = {
            **(i.location or {"label": building.name, "source": "building", "approx": True}),
            "anchor": _anchor(i.location, building),
        }
        incidents.append(out)
        if i.handoff and i.handoff.get("status") != "resolved":
            handoffs.append(
                {
                    "incident_id": i.id,
                    "status": i.handoff["status"],
                    "reasons": i.handoff.get("reasons"),
                    "brief": i.handoff.get("brief"),
                    "requested_at": i.handoff.get("requested_at"),
                }
            )
    incidents.sort(key=lambda x: (x["priority"], x["status"] != "active", x["started_at"]))

    occupants = (
        (await session.execute(select(Occupant).where(Occupant.building_id == building.id)))
        .scalars()
        .all()
    )
    hazards = (
        (
            await session.execute(
                select(Hazard)
                .where(
                    Hazard.building_id == building.id,
                    Hazard.active.is_(True),
                    Hazard.created_at >= now - HAZARD_WINDOW,
                )
                .order_by(Hazard.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    states = await plan.exit_states(session, building, evacuation)
    in_plan = set((evacuation.approved_routes or {}).values()) if evacuation else set()

    moving = [
        o
        for o in occupants
        if o.exit_id and o.status in (OccupantStatus.contacted, OccupantStatus.confirmed_safe)
    ]
    exits = []
    for x in building.exits:
        x_hazards = [h for h in hazards if h.exit_id == x.id or (x.zone and h.zone_id == x.zone)]
        heading = sum(
            1 for o in moving if o.exit_id == x.id and o.status == OccupantStatus.contacted
        )
        safe = sum(
            1 for o in moving if o.exit_id == x.id and o.status == OccupantStatus.confirmed_safe
        )
        st = states[x.id]
        exits.append(
            {
                "id": x.id,
                "label": x.label,
                "anchor": x.anchor.model_dump(),
                "assembly": x.assembly,
                "heading": heading,
                "safe": safe,
                "total": heading + safe,
                "share": round((heading + safe) / len(moving), 3) if moving else 0.0,
                "status": "hazard" if x_hazards else ("predicted" if st.unsafe else "open"),
                "unsafe": st.unsafe,
                "reasons": st.reasons,
                "predicted_minute": st.predicted_minute,
                "in_approved_plan": x.id in in_plan,
            }
        )

    flows: dict[tuple, dict] = {}
    for o in moving:
        origin = o.location or {}
        key = (origin.get("zone_id") or origin.get("label") or "unknown", o.exit_id)
        f = flows.setdefault(
            key,
            {
                "from_label": origin.get("label") or "Unknown position",
                "from_anchor": _anchor(origin, building),
                "exit_id": o.exit_id,
                "count": 0,
            },
        )
        f["count"] += 1

    by_status = {s.value: sum(1 for o in occupants if o.status == s) for s in OccupantStatus}
    ranked = sorted((e for e in exits if e["total"]), key=lambda e: -e["total"])
    proposals = []
    if evacuation:
        prows = (
            (
                await session.execute(
                    select(RouteProposal)
                    .where(RouteProposal.evacuation_id == evacuation.id)
                    .order_by(RouteProposal.created_at.desc())
                    .limit(12)
                )
            )
            .scalars()
            .all()
        )
        proposals = [
            plan.proposal_out(p, building) for p in prows if p.status != ProposalStatus.stale
        ]

    return {
        "building": {"id": building.id, "name": building.name, "scan_url": building.scan_url},
        "generated_at": now.isoformat(),
        "evacuation": evacuation_out(evacuation, building) if evacuation else None,
        "fire_model": evacuation.fire_model if evacuation and evacuation.fire_model else None,
        "report": (evacuation.report or {}) if evacuation else {},
        "incidents": incidents,
        "handoffs": handoffs,
        "exits": exits,
        "flows": sorted(flows.values(), key=lambda f: -f["count"]),
        "people": [person_out(o, building, evacuation, states, now) for o in occupants],
        "log": await log(session, building, evacuation, incidents),
        "comms": await comms.stats(session, building, evacuation),
        "roll_call": {
            "total": len(occupants),
            **by_status,
            "needs_assistance": sum(
                1 for o in occupants if o.mobility and o.status != OccupantStatus.confirmed_safe
            ),
            "call_requested": sum(
                1
                for o in occupants
                if o.call_requested_at and o.status == OccupantStatus.unconfirmed
            ),
        },
        "hazards": [
            {
                "id": h.id,
                "category": rules.HAZARD_CATEGORIES.get(h.category, h.category),
                "verification": h.verification.value,
                "text": h.text,
                "zone_id": h.zone_id,
                "exit_id": h.exit_id,
                "source": h.source,
                "created_at": h.created_at.isoformat(),
                "anchor": (
                    p.anchor.model_dump()
                    if (p := building.exit(h.exit_id) or building.zone(h.zone_id))
                    else None
                ),
            }
            for h in hazards
        ],
        "route_proposals": proposals,
        "top_exit": {
            "id": ranked[0]["id"],
            "label": ranked[0]["label"],
            "share": ranked[0]["share"],
        }
        if ranked
        else None,
    }


async def flow(session: AsyncSession, building: Building, minutes: int = 10) -> dict[str, Any]:
    """People confirmed out per exit per 15 s (the evacuation curve), from TigerData's aggregate."""
    start = utcnow() - timedelta(minutes=minutes)
    if db.status.get("evac_flow_15s"):
        result = await session.execute(
            text(
                "SELECT bucket, status, exit_id, sum(events) FROM evac_flow_15s "
                "WHERE building_id = :b AND bucket >= :start GROUP BY 1, 2, 3 ORDER BY 1"
            ),
            {"b": building.id, "start": start},
        )
        rows = [(b, s, e, int(c)) for b, s, e, c in result.all()]
        source = "tigerdata:evac_flow_15s"
    else:
        result = await session.execute(
            select(EvacEvent.created_at, EvacEvent.status, EvacEvent.exit_id).where(
                EvacEvent.building_id == building.id, EvacEvent.created_at >= start
            )
        )
        rows = []
        for at, s, e in result.all():
            bucket = at.replace(second=at.second - at.second % 15, microsecond=0)
            rows.append((bucket, s, e, 1))
        source = "evac_events"
    buckets: dict[str, dict] = {}
    for bucket, status, exit_id, count in rows:
        b = buckets.setdefault(
            bucket.isoformat(), {"at": bucket.isoformat(), "confirmed_safe": 0, "by_exit": {}}
        )
        if status == "confirmed_safe":
            b["confirmed_safe"] += count
            if exit_id:
                b["by_exit"][exit_id] = b["by_exit"].get(exit_id, 0) + count
    return {
        "building_id": building.id,
        "bucket_secs": 15,
        "source": source,
        "buckets": sorted(buckets.values(), key=lambda b: b["at"]),
    }
