"""Every text and call line, in and out, streamed into TigerData (comms_events).

record() writes one row per message or call line, tagged with who said it, the reply intent
(1 / 2 / HELP / SAFE) and any trigger word that brings in a human. A NOTIFY trigger streams each
row to the live view and the CREAO orchestrator. stats() reads the comms_1m continuous aggregate
(per-minute texts, call lines, calls, transfers, trigger words) plus reply rate and time to first
reply; thread() is one person's whole conversation across texts and calls.
"""

from datetime import datetime, timedelta
from statistics import median
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.creao import db, plan, rules
from app.creao.buildings import Building
from app.creao.db import utcnow
from app.creao.models import CommsEvent, Evacuation, Occupant


async def record(
    session: AsyncSession,
    building: Building,
    *,
    phone: str | None,
    channel: str,
    direction: str,
    role: str,
    kind: str = "text",
    text: str | None = None,
    conversation_id: str | None = None,
    occupant: Occupant | None = None,
    at: datetime | None = None,
) -> CommsEvent:
    """`at`: when it was said, for call lines that arrive after the call (defaults to now)."""
    if occupant is None and phone:
        occupant = await session.scalar(
            select(Occupant).where(Occupant.building_id == building.id, Occupant.phone == phone)
        )
    ev = await plan.active_evacuation(session, building.id)
    said = role == "person" and bool(text)
    trigger = rules.trigger_word(text) if said else None
    if trigger and kind == "line" and conversation_id:
        # the post-call transcript repeats what a live update already flagged: count it once
        flagged = await session.scalar(
            select(CommsEvent.id).where(
                CommsEvent.conversation_id == conversation_id,
                CommsEvent.kind == "call_update",
                CommsEvent.trigger == trigger,
            )
        )
        trigger = None if flagged else trigger
    row = CommsEvent(
        building_id=building.id,
        evacuation_id=ev.id if ev else None,
        occupant_id=occupant.id if occupant else None,
        phone=phone,
        channel=channel,
        direction=direction,
        role=role,
        kind=kind,
        text=text,
        conversation_id=conversation_id,
        trigger=trigger,
        intent=rules.reply_intent(text) if said else None,
        **({"created_at": at} if at else {}),
    )
    session.add(row)
    await session.commit()
    return row


async def stats(session: AsyncSession, building: Building, evacuation: Evacuation | None) -> dict:
    """Comms for the dashboard and the CREAO staff, read from TigerData."""
    since = evacuation.started_at if evacuation else utcnow() - timedelta(minutes=30)
    if db.status.get("comms_1m"):
        result = await session.execute(
            text(
                "SELECT bucket, texts_in, texts_out, call_lines, calls, transfers, triggers FROM comms_1m "
                "WHERE building_id = :b AND bucket >= :s ORDER BY bucket"
            ),
            {"b": building.id, "s": since - timedelta(minutes=1)},
        )
        minutes = [
            {
                "at": r[0].isoformat(),
                "texts_in": int(r[1]),
                "texts_out": int(r[2]),
                "call_lines": int(r[3]),
                "calls": int(r[4]),
                "transfers": int(r[5]),
                "triggers": int(r[6]),
            }
            for r in result.all()
        ]
        source = "tigerdata:comms_1m"
    else:
        rows = (
            await session.execute(
                select(CommsEvent).where(
                    CommsEvent.building_id == building.id, CommsEvent.created_at >= since
                )
            )
        ).scalars()
        buckets: dict[str, dict] = {}
        for c in rows:
            at = c.created_at.replace(second=0, microsecond=0).isoformat()
            b = buckets.setdefault(
                at,
                {
                    "at": at,
                    "texts_in": 0,
                    "texts_out": 0,
                    "call_lines": 0,
                    "calls": 0,
                    "transfers": 0,
                    "triggers": 0,
                },
            )
            b["texts_in"] += c.channel == "sms" and c.direction == "in"
            b["texts_out"] += c.channel == "sms" and c.direction == "out"
            b["call_lines"] += c.kind == "line"
            b["calls"] += c.kind == "call_started"
            b["transfers"] += c.kind == "call_transferred"
            b["triggers"] += c.trigger is not None
        minutes = sorted(buckets.values(), key=lambda b: b["at"])
        source = "comms_events"

    totals = {
        k: sum(m[k] for m in minutes)
        for k in ("texts_in", "texts_out", "calls", "transfers", "triggers")
    }
    calls = (
        await session.execute(
            select(CommsEvent.conversation_id, CommsEvent.kind).where(
                CommsEvent.building_id == building.id,
                CommsEvent.created_at >= since,
                CommsEvent.kind.in_(
                    ("call_started", "call_ended", "call_transferred", "call_update")
                ),
            )
        )
    ).all()
    started = {cid for cid, k in calls if k == "call_started"}
    finished = {cid for cid, k in calls if k in ("call_ended", "call_transferred")}

    first_reply = []
    if evacuation:
        rows = (
            await session.execute(
                select(Occupant.id, Occupant.alerted_at, CommsEvent.created_at)
                .join(CommsEvent, CommsEvent.occupant_id == Occupant.id)
                .where(
                    Occupant.building_id == building.id,
                    Occupant.alerted_at >= evacuation.started_at,
                    CommsEvent.role == "person",
                    CommsEvent.created_at >= evacuation.started_at,
                )
            )
        ).all()
        firsts: dict[str, float] = {}
        for oid, alerted, at in rows:
            secs = (at - alerted).total_seconds()
            firsts[oid] = min(firsts.get(oid, secs), secs)
        first_reply = list(firsts.values())
        alerted = len(
            (
                await session.execute(
                    select(Occupant.id).where(
                        Occupant.building_id == building.id,
                        Occupant.alerted_at >= evacuation.started_at,
                    )
                )
            ).all()
        )
    else:
        alerted = 0
    return {
        "source": source,
        "minutes": minutes[-30:],
        **totals,
        "active_calls": len(started - finished),
        "live_updates": sum(
            1 for _cid, k in calls if k == "call_update"
        ),  # mid-call, from the agent
        "alerted": alerted,
        "replied": len(first_reply),
        "reply_rate": round(len(first_reply) / alerted, 3) if alerted else None,
        "median_reply_secs": round(median(first_reply)) if first_reply else None,
    }


async def thread(
    session: AsyncSession, building: Building, occupant: Occupant, limit: int = 40
) -> list[dict[str, Any]]:
    """One person's conversation, texts and calls together, oldest first."""
    rows = (
        (
            await session.execute(
                select(CommsEvent)
                .where(CommsEvent.building_id == building.id, CommsEvent.occupant_id == occupant.id)
                .order_by(CommsEvent.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "at": c.created_at.isoformat(),
            "channel": c.channel,
            "direction": c.direction,
            "role": c.role,
            "kind": c.kind,
            "text": c.text,
            "trigger": c.trigger,
            "intent": c.intent,
        }
        for c in reversed(rows)
    ]
