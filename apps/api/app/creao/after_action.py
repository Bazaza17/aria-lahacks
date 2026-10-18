"""After a drill or fire: read the run back out of TigerData, clear the console, brief the Scribe.

When an evacuation ends, Aria first freezes what happened (texts and calls from comms_1m, people
out per exit from evac_flow_15s, the live report the staff wrote), saves a factual draft on the
evacuation, then clears the console: the drill's incidents close, handoffs resolve, hazards go
inactive and everyone's roll-call state resets (registrations stay). The CREAO Incident Scribe
gets the frozen facts and writes the after-action report with update_report(section="after_action").
The history itself stays in TigerData's hypertables.
"""

import asyncio
import logging
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.creao import comms, report, situation
from app.creao.buildings import Building
from app.creao.db import utcnow
from app.creao.models import (
    Evacuation,
    Hazard,
    Incident,
    Occupant,
    OccupantStatus,
    ProposalStatus,
    RouteProposal,
)

log = logging.getLogger(__name__)

TITLE = "After-action report"


async def latest_ended(session: AsyncSession, building_id: str) -> Evacuation | None:
    return await session.scalar(
        select(Evacuation)
        .where(Evacuation.building_id == building_id, Evacuation.status == "ended")
        .order_by(Evacuation.ended_at.desc())
        .limit(1)
    )


async def freeze(session: AsyncSession, building: Building, ev: Evacuation) -> dict[str, Any]:
    """What happened in this evacuation, read before the console is cleared."""
    s = await situation.build(session, building)
    live = await report.build(session, building)
    talk = await comms.stats(session, building, ev)
    minutes = max(1, int((utcnow() - ev.started_at).total_seconds() // 60) + 1)
    flow = await situation.flow(session, building, minutes=minutes)
    out_by_exit: dict[str, int] = {}
    for bucket in flow["buckets"]:
        for exit_id, n in bucket["by_exit"].items():
            out_by_exit[exit_id] = out_by_exit.get(exit_id, 0) + n
    decided = (
        await session.execute(
            select(RouteProposal.status).where(RouteProposal.evacuation_id == ev.id)
        )
    ).scalars()
    routes = [str(st) for st in decided]
    started = ev.started_at.isoformat()
    mine = [i for i in s["incidents"] if i["started_at"] >= started]
    return {
        "evacuation_id": ev.id,
        "mode": ev.mode,
        "origin": ev.origin_label,
        "started_at": started,
        "ended_at": utcnow().isoformat(),
        "minutes": round((utcnow() - ev.started_at).total_seconds() / 60, 1),
        "roll_call": s["roll_call"],
        "comms": {
            k: talk.get(k)
            for k in (
                "alerted",
                "replied",
                "reply_rate",
                "median_reply_secs",
                "texts_in",
                "texts_out",
                "calls",
                "transfers",
                "triggers",
            )
        },
        "exits_used": [
            {"exit_id": x, "label": (building.exit(x).label if building.exit(x) else x), "out": n}
            for x, n in sorted(out_by_exit.items(), key=lambda kv: -kv[1])
        ],
        "hazards": [
            {"category": h["category"], "text": h["text"][:160], "verification": h["verification"]}
            for h in s["hazards"][:10]
        ],
        "incidents": {
            "total": len(mine),
            "human_needed": sum(1 for i in mine if (i.get("handoff") or {}).get("status")),
            "on_dispatcher_line": sum(
                1 for i in mine if (i.get("handoff") or {}).get("status") == "transferred"
            ),
        },
        "routes": {
            "approved": routes.count(ProposalStatus.approved.value),
            "rejected": routes.count(ProposalStatus.rejected.value),
            "approved_plan": [
                f"{r['zone_label']} → {r['exit_label']}"
                for r in (s["evacuation"] or {}).get("approved_routes", [])
            ],
        },
        "live_report": [
            {"title": x["title"], "by": x["by"], "text": x["text"][:1200]} for x in live["sections"]
        ],
        "sources": {"comms": talk["source"], "exit_flow": flow["source"]},
    }


def draft(f: dict[str, Any]) -> str:
    """The automatic version, shown until the Scribe's report arrives."""
    c, rc = f["comms"], f["roll_call"]
    rate = f"{round(c['reply_rate'] * 100)}%" if c.get("reply_rate") is not None else "–"
    median = f"{c['median_reply_secs']}s" if c.get("median_reply_secs") is not None else "–"
    exits = (
        ", ".join(f"{x['label']} ({x['out']})" for x in f["exits_used"]) or "nobody confirmed out"
    )
    lines = [
        f"{f['mode'].upper()}: fire at {f['origin']}, {f['minutes']:g} min.",
        f"Alerted {c.get('alerted') or 0}; {c.get('replied') or 0} replied ({rate}), median first reply {median}.",
        f"Roll call at the end: {rc['confirmed_safe']} out, {rc['contacted']} moving, "
        f"{rc['needs_help']} needed help, {rc['unconfirmed']} unconfirmed.",
        f"Exits used: {exits}.",
        f"Texts {c.get('texts_in') or 0} in / {c.get('texts_out') or 0} out; calls {c.get('calls') or 0}, "
        f"{c.get('transfers') or 0} moved to the dispatcher line.",
        f"{f['incidents']['total']} incident(s); {f['incidents']['human_needed']} needed a human.",
        f"Route changes: {f['routes']['approved']} approved, {f['routes']['rejected']} rejected.",
    ]
    if f["hazards"]:
        lines.append(
            "Hazards: " + "; ".join(f"{h['category']}: “{h['text'][:80]}”" for h in f["hazards"])
        )
    return "\n".join(lines)


async def clear(session: AsyncSession, building_id: str, why: str) -> None:
    """Close incidents and handoffs, retire hazards, reset the roll call (people stay registered)."""
    now = utcnow()
    for inc in (
        await session.execute(
            select(Incident).where(Incident.building_id == building_id, Incident.status == "active")
        )
    ).scalars():
        inc.status, inc.ended_at = "ended", now
        if inc.handoff and inc.handoff.get("status") != "resolved":
            inc.handoff = {**inc.handoff, "status": "resolved", "resolved_by": why}
    await session.execute(
        update(Hazard)
        .where(Hazard.building_id == building_id, Hazard.active.is_(True))
        .values(active=False)
    )
    await session.execute(
        update(Occupant)
        .where(Occupant.building_id == building_id)
        .values(
            status=OccupantStatus.unconfirmed,
            location=None,
            exit_id=None,
            incident_id=None,
            last_instruction=None,
            alerted_at=None,
            call_requested_at=None,
        )
    )
    await session.commit()


async def has_leftovers(session: AsyncSession, building_id: str) -> bool:
    """Anything still on the console with no evacuation running."""
    checks = (
        select(Incident.id).where(Incident.building_id == building_id, Incident.status == "active"),
        select(Hazard.id).where(Hazard.building_id == building_id, Hazard.active.is_(True)),
        select(Occupant.id).where(
            Occupant.building_id == building_id,
            (Occupant.status != OccupantStatus.unconfirmed) | Occupant.alerted_at.is_not(None),
        ),
    )
    for q in checks:
        if await session.scalar(q.limit(1)):
            return True
    return False


def brief_scribe(building_id: str, f: dict[str, Any]) -> None:
    """Ask the CREAO Incident Scribe for the after-action report (in the background)."""
    from app.creao import bridge

    task = (
        f"The {f['mode']} (fire at {f['origin']}) just ended after {f['minutes']:g} min. Write the "
        "after-action report from after_action_facts, which Aria read from TigerData (texts and calls "
        "from comms_1m, people out per exit from evac_flow_15s) plus the live report the staff kept. "
        "Cover: what happened, how fast people replied and got out, which exits they used, hazards, "
        "who needed a human, what went well, what to fix before the next drill. Plain sentences, no "
        "phone numbers. Then call update_report with section after_action and the whole report as "
        "text, and complete_task."
    )

    async def run() -> None:
        try:
            await bridge.trigger_role(
                "scribe",
                task=task,
                building_id=building_id,
                trigger="evacuation.ended",
                extra={"after_action_facts": f},
            )
        except Exception:  # noqa: BLE001 (the draft stays; the console still works)
            log.exception("CREAO after-action brief failed")

    task_ref = asyncio.create_task(run())
    _running.add(task_ref)
    task_ref.add_done_callback(_running.discard)


_running: set[asyncio.Task] = set()
