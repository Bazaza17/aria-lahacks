"""The CREAO command staff: one saved CREAO agent per role, handing work to each other.

    Incident Commander (orchestrator, triggered by Aria via API Trigger)
      ├── Intake Analyst          texts + call transcripts -> hazard pins, locations, life-threat flags
      ├── Evacuation Coordinator  exits + hazards + fire model -> route proposals (dispatcher approves)
      ├── Accountability Officer  roll call -> who's unconfirmed, who needs help, who to call next
      ├── Responder Liaison       briefing for arriving crews: where the high-impact people are
      └── Incident Scribe         the live incident report and the after-action report

Every task is an AgentRun; every tool call an agent makes is recorded on its run. The Commander
hands tasks to specialists with the handoff_to_agent MCP tool, so the console's org chart shows
real handoffs. The agents analyse and propose; safety rules validate; the dispatcher approves
anything that changes what people are told.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.creao import hub
from app.creao.db import utcnow
from app.creao.models import AgentRun

ROLES: dict[str, dict[str, Any]] = {
    "commander": {
        "title": "Incident Commander",
        "reports_to": None,
        "does": "Reads every new event, decides who handles it, hands tasks to specialists, keeps the overview current.",
    },
    "intake": {
        "title": "Intake Analyst",
        "reports_to": "commander",
        "does": "Reads texts and call transcripts; pins hazards and locations; flags anyone whose life is at risk.",
    },
    "coordinator": {
        "title": "Evacuation Coordinator",
        "reports_to": "commander",
        "does": "Weighs exits, reported hazards, the fire model and crowding; proposes route changes for approval.",
    },
    "accountability": {
        "title": "Accountability Officer",
        "reports_to": "commander",
        "does": "Runs the roll call: unconfirmed, needs help, mobility needs; decides who gets called next.",
    },
    "liaison": {
        "title": "Responder Liaison",
        "reports_to": "commander",
        "does": "Briefs arriving firefighters: where the high-impact people are and which exits are safe.",
    },
    "scribe": {
        "title": "Incident Scribe",
        "reports_to": "commander",
        "does": "Keeps the live incident report and timeline; writes the after-action report.",
    },
}
ACTIVITY_LIMIT = 40


def _iso(dt: datetime | None) -> str | None:
    """SQLite hands back naive datetimes; they're UTC, so say so (browsers read naive ISO as local time)."""
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).isoformat()


async def create_run(
    session: AsyncSession,
    *,
    role: str,
    task: str,
    building_id: str | None,
    parent_id: str | None = None,
    trigger: str | None = None,
) -> AgentRun:
    run = AgentRun(
        role=role,
        task=task[:2000],
        building_id=building_id,
        parent_id=parent_id,
        trigger=trigger,
        actions=[],
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    await _publish(run, {"type": "run.created", "text": task[:200]})
    return run


async def record_action(
    session: AsyncSession, run: AgentRun, kind: str, text: str, **data: Any
) -> None:
    run.actions = [
        *(run.actions or []),
        {"type": kind, "text": text[:400], "at": utcnow().isoformat(), **data},
    ][-50:]
    if run.status in ("queued", "running"):
        run.status = "running"
    await session.commit()
    await _publish(run, {"type": kind, "text": text[:400]})


async def finish_run(
    session: AsyncSession, run: AgentRun, *, summary: str | None = None, error: str | None = None
) -> None:
    run.status = "failed" if error else "done"
    run.summary = (summary or run.summary or "")[:2000] or None
    run.error = error
    run.finished_at = utcnow()
    await session.commit()
    await _publish(
        run, {"type": "run.failed" if error else "run.done", "text": (error or summary or "")[:300]}
    )


async def _publish(run: AgentRun, entry: dict) -> None:
    await hub.publish(
        "agent.activity",
        building_id=run.building_id,
        data={
            "run_id": run.id,
            "role": run.role,
            "title": ROLES.get(run.role, {}).get("title", run.role),
            "parent_id": run.parent_id,
            "status": run.status,
            **entry,
        },
    )


def run_out(run: AgentRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "role": run.role,
        "title": ROLES.get(run.role, {}).get("title", run.role),
        "parent_id": run.parent_id,
        "task": run.task,
        "status": run.status,
        "trigger": run.trigger,
        "summary": run.summary,
        "error": run.error,
        "actions": run.actions or [],
        "created_at": _iso(run.created_at),
        "finished_at": _iso(run.finished_at),
    }


async def staff_overview(
    session: AsyncSession, building_id: str, deployed: set[str]
) -> dict[str, Any]:
    """The org chart with each role's latest work, recent handoffs, an activity feed, and the live report."""
    from app.creao import report
    from app.creao.buildings import get_building

    # This building's runs plus line-wide ones (urgent calls that aren't tied to any building).
    runs = (
        (
            await session.execute(
                select(AgentRun)
                .where(or_(AgentRun.building_id == building_id, AgentRun.building_id.is_(None)))
                .order_by(AgentRun.created_at.desc())
                .limit(80)
            )
        )
        .scalars()
        .all()
    )
    by_id = {r.id: r for r in runs}
    roles = []
    for role, meta in ROLES.items():
        mine = [r for r in runs if r.role == role]
        latest = mine[0] if mine else None
        roles.append(
            {
                "role": role,
                **meta,
                "deployed": role in deployed,
                "status": latest.status if latest else "idle",
                "last_task": latest.task if latest else None,
                "last_summary": latest.summary if latest else None,
                "last_at": _iso(latest.finished_at or latest.created_at) if latest else None,
                "runs": len(mine),
                "actions": sum(len(r.actions or []) for r in mine),
            }
        )
    handoffs = [
        {
            "from": by_id[r.parent_id].role,
            "to": r.role,
            "task": r.task,
            "status": r.status,
            "at": _iso(r.created_at),
        }
        for r in runs
        if r.parent_id and r.parent_id in by_id
    ][:15]
    activity = []
    for r in runs:
        # A handoff already shows as the Commander's "handoff" action; only Aria's own triggers get a line here.
        if not r.parent_id and r.trigger:
            activity.append(
                {
                    "at": _iso(r.created_at),
                    "role": r.role,
                    "kind": "triggered",
                    "text": f"Woken by Aria: {r.task}",
                }
            )
        for a in r.actions or []:
            activity.append({"at": a["at"], "role": r.role, "kind": a["type"], "text": a["text"]})
        if r.status == "failed":
            activity.append(
                {
                    "at": _iso(r.finished_at or r.created_at),
                    "role": r.role,
                    "kind": "failed",
                    "text": r.error or "failed",
                }
            )
        elif r.status == "done" and r.summary:
            activity.append(
                {
                    "at": _iso(r.finished_at or r.created_at),
                    "role": r.role,
                    "kind": "done",
                    "text": f"Done: {r.summary}",
                }
            )
    activity.sort(key=lambda a: a["at"], reverse=True)

    building = get_building(building_id)
    live = await report.build(session, building) if building else {"sections": []}
    return {
        "deployed": sorted(deployed),
        "roles": roles,
        "handoffs": handoffs,
        "activity": activity[:ACTIVITY_LIMIT],
        "report": live["sections"],
    }
