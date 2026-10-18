"""The live incident report, written by the CREAO command staff on top of TigerData.

Six sections: overview, hazards, routes, people, responders, timeline. Each CREAO agent owns one
(update_report over MCP) and signs it. Until an agent has written a section, Aria fills it with a
factual draft computed from the live situation, labeled as automatic, so the report is never
empty and never pretends an agent wrote it.
"""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.creao import hub, plan, situation
from app.creao.buildings import Building
from app.creao.db import utcnow
from app.creao.intake import incident_out
from app.creao.models import AgentRun, Incident, IncidentEvent, Occupant

SECTIONS = {
    "overview": ("Overview", "commander"),
    "hazards": ("Hazards", "intake"),
    "routes": ("Exits & routes", "coordinator"),
    "people": ("People", "accountability"),
    "responders": ("Responder briefing", "liaison"),
    "timeline": ("Timeline", "scribe"),
}


def _clock(iso: str) -> str:
    return iso[11:19] if iso and len(iso) >= 19 else iso


def _place(building: Building, h: dict) -> str:
    item = building.exit(h["exit_id"]) or building.zone(h["zone_id"])
    return item.label if item else "unknown place"


async def _drafts(session: AsyncSession, building: Building, s: dict) -> dict[str, str]:
    ev, rc = s["evacuation"], s["roll_call"]
    doors = [
        e
        for e in s["exits"]
        if not (e["assembly"] and e["id"] not in {x.id for x in building.exits if x.zone})
    ]
    open_x = [e["label"] for e in doors if not e["unsafe"]]
    unsafe_x = [f"{e['label']} ({'; '.join(e['reasons'])})" for e in doors if e["unsafe"]]
    pending = [p for p in s["route_proposals"] if p["status"] == "proposed"]
    lines = {}
    lines["overview"] = "\n".join(
        filter(
            None,
            [
                f"{ev['mode'].upper()}: fire at {ev['origin_label']}, minute {ev['minute_now']:.0f}."
                if ev
                else "No evacuation declared.",
                f"{rc['confirmed_safe']} of {rc['total']} confirmed out; {rc['unconfirmed']} unconfirmed; {rc['needs_help']} need help.",
                f"Open exits: {', '.join(open_x) or 'none'}.",
                f"{len(s['handoffs'])} caller(s) need a human dispatcher."
                if s["handoffs"]
                else None,
                f"{len(pending)} route change(s) waiting for approval." if pending else None,
            ],
        )
    )
    lines["hazards"] = (
        "\n".join(
            f"• {h['category']} at {_place(building, h)}: “{h['text'][:120]}” "
            f"({h['verification'].replace('_', ' ')})"
            for h in s["hazards"][:10]
        )
        or "No hazards reported."
    )
    if s["fire_model"]:
        lines["hazards"] += "\nFire model (simulation): " + ", ".join(
            f"{st['kind']} at {st['label']} by minute {st['minute']:g}"
            for st in s["fire_model"]["steps"]
        )
    lines["routes"] = (
        "\n".join(
            [
                *(
                    f"• {r['zone_label']} → {r['exit_label']}"
                    for r in (ev or {}).get("approved_routes", [])
                ),
                *(f"Avoid: {x}" for x in unsafe_x),
            ]
        )
        or "No approved routes yet."
    )
    lines["people"] = (
        f"{rc['confirmed_safe']} confirmed safe, {rc['contacted']} replied but not out, "
        f"{rc['unconfirmed']} unconfirmed (not accounted for), {rc['needs_help']} need help, "
        f"{rc['needs_assistance']} with mobility needs still inside, {rc['call_requested']} queued for a call."
    )
    lines["responders"] = "\n".join(
        [
            *(f"• HUMAN NEEDED: {h['brief']['summary']}" for h in s["handoffs"]),
            *(
                f"• {i['priority']} {i['headline'][:80]} — {i['location'].get('label')}"
                for i in s["incidents"][:6]
                if i["status"] == "active"
            ),
            f"Safe exits: {', '.join(open_x) or 'none'}.",
        ]
    )
    since = datetime.fromisoformat(ev["started_at"]) if ev else utcnow() - timedelta(hours=1)
    events = (
        (
            await session.execute(
                select(IncidentEvent)
                .where(
                    IncidentEvent.building_id == building.id,
                    IncidentEvent.kind.in_(("flag", "note", "status")),
                    IncidentEvent.created_at >= since,
                )
                .order_by(IncidentEvent.created_at.desc())
                .limit(12)
            )
        )
        .scalars()
        .all()
    )
    lines["timeline"] = (
        "\n".join(f"{_clock(e.created_at.isoformat())}  {e.text}" for e in events) or "Nothing yet."
    )
    return lines


async def build(session: AsyncSession, building: Building) -> dict[str, Any]:
    s = await situation.build(session, building)
    written = s["report"] or {}
    drafts = await _drafts(session, building, s)
    sections = []
    for key, (title, owner) in SECTIONS.items():
        if key in written:
            sections.append(
                {"section": key, "title": title, "owner": owner, **written[key], "automatic": False}
            )
        else:
            sections.append(
                {
                    "section": key,
                    "title": title,
                    "owner": owner,
                    "text": drafts[key],
                    "by": "Aria (automatic, from TigerData)",
                    "at": s["generated_at"],
                    "automatic": True,
                }
            )
    return {
        "building": s["building"],
        "evacuation": s["evacuation"],
        "generated_at": s["generated_at"],
        "sections": sections,
    }


async def write(
    session: AsyncSession, building: Building, section: str, text: str, *, role: str, by: str
) -> dict:
    ev = await plan.active_evacuation(session, building.id)
    if ev is None:
        raise LookupError("no active evacuation")
    ev.report = {
        **(ev.report or {}),
        section: {"text": text[:4000], "role": role, "by": by, "at": utcnow().isoformat()},
    }
    await session.commit()
    await hub.publish(
        "report.updated", building_id=building.id, data={"section": section, "by": by}
    )
    return ev.report[section]


def markdown(r: dict) -> str:
    ev = r["evacuation"]
    head = f"# Incident report: {r['building']['name']}\n\n"
    if ev:
        head += f"**{ev['mode'].upper()}** · fire at {ev['origin_label']} · started {_clock(ev['started_at'])} UTC · minute {ev['minute_now']:.0f}\n\n"
    body = "\n\n".join(
        f"## {s['title']}\n\n{s['text']}\n\n_{s['by']}, {_clock(s['at'])} UTC_"
        for s in r["sections"]
    )
    return head + body + "\n"


async def incident_report(
    session: AsyncSession, building: Building, inc: Incident
) -> dict[str, Any]:
    """One incident as the dispatcher opens it from its pin: who and where, what the CREAO staff
    wrote about it, the building report sections they signed, what the person was last told, and
    the timeline from TigerData."""
    occ = (
        await session.scalar(
            select(Occupant).where(
                Occupant.building_id == building.id, Occupant.phone == inc.caller
            )
        )
        if inc.caller
        else None
    )
    events = (
        (
            await session.execute(
                select(IncidentEvent)
                .where(IncidentEvent.incident_id == inc.id)
                .order_by(IncidentEvent.created_at)
            )
        )
        .scalars()
        .all()
    )
    notes = [{"at": e.created_at.isoformat(), "text": e.text} for e in events if e.role == "creao"]
    # Agent actions that name this person or incident (pins, handoff requests, calls)
    runs = (
        (
            await session.execute(
                select(AgentRun)
                .where(AgentRun.building_id == building.id)
                .order_by(AgentRun.created_at.desc())
                .limit(60)
            )
        )
        .scalars()
        .all()
    )
    keys = [k for k in (inc.id, inc.caller, occ.name if occ else None) if k]
    actions = [
        {"at": a["at"], "role": r.role, "text": a["text"]}
        for r in runs
        for a in (r.actions or [])
        if any(k in a.get("text", "") for k in keys)
    ]
    live = await build(session, building)
    signed = [x for x in live["sections"] if not x["automatic"]]
    out = incident_out(inc)
    return {
        "incident": out,
        "person": {
            "name": occ.name if occ else None,
            "phone": inc.caller,
            "status": occ.status.value if occ else None,
            "mobility": occ.mobility if occ else [],
            "last_instruction": occ.last_instruction if occ else None,
        },
        "handoff": inc.handoff,
        "creao": {
            "notes": notes,
            "actions": sorted(actions, key=lambda a: a["at"]),
            "sections": signed,
        },
        "timeline": [
            {"at": e.created_at.isoformat(), "kind": e.kind, "role": e.role, "text": e.text}
            for e in events
            if e.text
        ],
    }
