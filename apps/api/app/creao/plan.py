"""Exit safety and routes: which exit each zone should use, and how route changes get approved.

Rules (from the product decisions):
- Routes only ever come from the building profile's exits; nothing is invented.
- An exit is unsafe when a hazard is reported or verified there, or the fire model predicts it
  will be affected within HORIZON_MIN minutes. Unsafe exits are never proposed.
- With the engine's fire model active, each zone gets the engine's capacity-aware route
  (app.creao.engine_model) for the latest departure time; the nearest safe exit that isn't
  overcrowded is only the fallback when the engine has no route for that zone.
- The coordinator only PROPOSES changes. People keep getting the approved route until a dispatcher
  approves a proposal, and a proposal made against an older hazard picture is refused as stale.
"""

import math
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.creao import engine_model, hub
from app.creao import location as loc
from app.creao.buildings import Anchor, Building, Exit
from app.creao.db import utcnow
from app.creao.models import (
    Evacuation,
    Hazard,
    Occupant,
    OccupantStatus,
    ProposalStatus,
    RouteProposal,
    Verification,
)

HORIZON_MIN = (
    5  # never route people toward an exit the fire model expects to lose within this many minutes
)
UNKNOWN_POSITION = {"building", "floor"}  # location sources that don't place someone in a zone
FLOOR_HEIGHT_M = 4.0
CROWD_PENALTY_M = 2.0  # each person already heading to an exit "costs" this many metres
CAPACITY = 25  # above this many heading to one exit, it counts as overcrowded


class StaleProposal(Exception):
    def __init__(self, replacement: RouteProposal | None):
        self.replacement = replacement


@dataclass
class ExitState:
    id: str
    label: str
    unsafe: bool = False
    reasons: list[str] = field(default_factory=list)
    hazard_ids: list[str] = field(default_factory=list)
    predicted_minute: float | None = None
    heading: int = 0


# ---------------------------------------------------------------- geometry


def distance_m(building: Building, a: Anchor, b: Anchor) -> float:
    dx = (a.nx - b.nx) * building.geo.width_m
    dz = (a.nz - b.nz) * building.geo.depth_m
    dy = abs(a.ny - b.ny) * building.geo.height_m
    return math.hypot(dx, dz) + (FLOOR_HEIGHT_M * 2 if dy > FLOOR_HEIGHT_M / 2 else 0) + dy


def plan_zones(building: Building) -> list[str]:
    """Zones people evacuate from (assembly points are destinations, not origins)."""
    assembly_zones = {e.zone for e in building.exits if e.assembly}
    return [z.id for z in building.zones if z.id not in assembly_zones]


def outside(building: Building, zone_id: str | None) -> bool:
    """Already out of the building: an outdoor zone on the ground floor. An upper-floor patio
    still needs a way down, so it gets a route like any room."""
    zone = building.zone(zone_id)
    return bool(zone and zone.outdoor and zone.floor == min(f.level for f in building.floors))


def route_zones(building: Building) -> list[str]:
    """Zones that get an exit route. Ground-floor patios don't: people there move away to the
    building instead, so they never get a route or a route-change proposal."""
    return [z for z in plan_zones(building) if not outside(building, z)]


def exit_floor(building: Building, exit: Exit) -> int:
    if exit.floor is not None:
        return exit.floor
    return min(building.floors, key=lambda f: abs(f.ny - exit.anchor.ny)).level


def zone_for(building: Building, location: dict | None) -> str | None:
    """The zone someone is in: their named zone, else the zone nearest their position.

    None when we don't know where they are (nothing, or only "somewhere in the building / on this
    floor"). Guessing a zone would send them one zone's route; they get every open exit instead."""
    if location and location.get("zone_id") in plan_zones(building):
        return location["zone_id"]
    if (
        location
        and location.get("exit_id")
        and (e := building.exit(location["exit_id"]))
        and e.zone in plan_zones(building)
    ):
        return e.zone
    if not location or not location.get("anchor") or location.get("source") in UNKNOWN_POSITION:
        return None
    zones = [building.zone(z) for z in plan_zones(building)]
    if not zones:
        return None
    anchor = Anchor(**location["anchor"])
    return min(zones, key=lambda z: distance_m(building, z.anchor, anchor)).id


# ---------------------------------------------------------------- fire model


def minute_now(evacuation: Evacuation) -> float:
    return max(0.0, (utcnow() - evacuation.started_at).total_seconds() / 60)


def normalize_fire_model(building: Building, model: dict) -> dict:
    """Resolve each step's place (id or name) to a zone/exit; drop steps naming unknown places."""
    steps = []
    for step in model.get("steps", []):
        place = str(step.get("place", ""))
        kind = "exit" if building.exit(place) else "zone" if building.zone(place) else None
        place_id = place
        if kind is None and (match := loc.match_place(building, place)):
            kind, place_id = match
        if kind is None:
            continue
        item = building.exit(place_id) if kind == "exit" else building.zone(place_id)
        steps.append(
            {
                "minute": float(step.get("minute", 0)),
                "place": place_id,
                "place_kind": kind,
                "label": item.label,
                "kind": step.get("kind", "fire"),
                "severity": step.get("severity", "high"),
                "anchor": item.anchor.model_dump(),
            }
        )
    steps.sort(key=lambda s: s["minute"])
    return {
        "scenario_id": model.get("scenario_id", "scenario"),
        "label": model.get("label"),
        "source": model.get("source") or "manual",  # typed in by hand unless said otherwise
        "simulation": True,
        "steps": steps,
    }


def predicted_minutes(building: Building, evacuation: Evacuation | None) -> dict[str, float]:
    """First minute each exit is predicted to be affected (directly or via its zone)."""
    if not evacuation or not evacuation.fire_model:
        return {}
    # The engine times each exit's loss itself; a hand-typed model marks exits by their zone too
    engine = engine_model.is_engine(evacuation.fire_model)
    first: dict[str, float] = {}
    for step in evacuation.fire_model.get("steps", []):
        if engine and step.get("place_kind") != "exit":
            continue
        first[step["place"]] = min(first.get(step["place"], math.inf), step["minute"])
    out = {}
    for exit in building.exits:
        m = min(
            first.get(exit.id, math.inf),
            first.get(exit.zone, math.inf) if exit.zone and not engine else math.inf,
        )
        if m != math.inf:
            out[exit.id] = m
    return out


# ---------------------------------------------------------------- exit safety


async def exit_states(
    session: AsyncSession, building: Building, evacuation: Evacuation | None
) -> dict[str, ExitState]:
    from app.creao.intake import HAZARD_WINDOW
    from app.creao.rules import HAZARD_CATEGORIES

    hazards = (
        (
            await session.execute(
                select(Hazard).where(
                    Hazard.building_id == building.id,
                    Hazard.active.is_(True),
                    Hazard.created_at >= utcnow() - HAZARD_WINDOW,
                )
            )
        )
        .scalars()
        .all()
    )
    occupants = (
        (
            await session.execute(
                select(Occupant.exit_id).where(
                    Occupant.building_id == building.id, Occupant.status == OccupantStatus.contacted
                )
            )
        )
        .scalars()
        .all()
    )
    predicted = predicted_minutes(building, evacuation)
    now_min = minute_now(evacuation) if evacuation else 0

    states = {}
    for exit in building.exits:
        st = ExitState(
            id=exit.id, label=exit.label, heading=sum(1 for e in occupants if e == exit.id)
        )
        for h in hazards:
            if h.exit_id == exit.id or (exit.zone and h.zone_id == exit.zone):
                st.unsafe = True
                st.hazard_ids.append(h.id)
                trust = (
                    "dispatcher verified"
                    if h.verification == Verification.dispatcher_verified
                    else "reported"
                )
                st.reasons.append(f"{HAZARD_CATEGORIES.get(h.category, h.category)} {trust}")
        if exit.id in predicted:
            st.predicted_minute = predicted[exit.id]
            if predicted[exit.id] <= now_min + HORIZON_MIN:
                st.unsafe = True
                st.reasons.append(
                    f"fire model predicts it affected by minute {predicted[exit.id]:g}"
                )
        states[exit.id] = st
    return states


def engine_exit(
    building: Building, evacuation: Evacuation | None, zone_id: str
) -> tuple[str | None, str | None]:
    """The engine's planned (exit, then-exit) for a zone right now, if its fire model is active."""
    if evacuation is None or not engine_model.is_engine(evacuation.fire_model):
        return None, None
    exit_id, then = engine_model.engine_route(
        evacuation.fire_model, zone_id, minute_now(evacuation)
    )
    return (exit_id, then) if building.exit(exit_id) else (None, None)


def _engine_ok(st: ExitState, now_min: float) -> bool:
    """The engine's own route is fine unless someone reported a hazard there or the exit is
    already lost: it already planned around when each exit goes (the 5-minute horizon is for
    the heuristic)."""
    if not st.unsafe:
        return True
    return not st.hazard_ids and st.predicted_minute is not None and st.predicted_minute > now_min


def choose_exit(
    building: Building,
    zone_id: str,
    states: dict[str, ExitState],
    preferred: str | None = None,
    now_min: float = 0.0,
) -> tuple[str | None, float | None]:
    zone = building.zone(zone_id)
    if preferred and preferred in states and _engine_ok(states[preferred], now_min):
        return preferred, distance_m(building, zone.anchor, building.exit(preferred).anchor)
    # Only exits on the zone's own floor when it has any (e.g. stairs down from an upper patio)
    floor_exits = [e for e in building.exits if exit_floor(building, e) == zone.floor]
    best, best_score, best_dist = None, math.inf, None
    for exit in floor_exits or building.exits:
        st = states[exit.id]
        if exit.assembly and not exit.zone:
            continue  # a meeting point outside (e.g. a lawn), not a way out of the building
        if st.unsafe:
            continue
        dist = distance_m(building, zone.anchor, exit.anchor)
        score = dist + CROWD_PENALTY_M * st.heading + (50 if st.heading > CAPACITY else 0)
        if score < best_score:
            best, best_score, best_dist = exit.id, score, dist
    return best, best_dist


# ---------------------------------------------------------------- plans & instructions


async def active_evacuation(session: AsyncSession, building_id: str) -> Evacuation | None:
    return await session.scalar(
        select(Evacuation)
        .where(Evacuation.building_id == building_id, Evacuation.status == "active")
        .order_by(Evacuation.started_at.desc())
        .limit(1)
    )


async def initial_plan(
    session: AsyncSession, building: Building, evacuation: Evacuation
) -> dict[str, str]:
    states = await exit_states(session, building, evacuation)
    now = minute_now(evacuation)
    plan = {}
    for zone_id in route_zones(building):
        preferred, _ = engine_exit(building, evacuation, zone_id)
        exit_id, _ = choose_exit(building, zone_id, states, preferred, now)
        if exit_id:
            plan[zone_id] = exit_id
            states[exit_id].heading += 1  # spread zones across exits a little
    return plan


def assembly_words(building: Building) -> str:
    """Where people go once out: an assembly exit if the profile has one, else honest words."""
    assembly = building.exit(building.assembly_exit_id)
    return assembly.label if assembly else building.assembly


def once_out(building: Building) -> str:
    assembly = building.exit(building.assembly_exit_id)
    if assembly:
        return f"Then go to {assembly.label}."
    return "Then move away from the building; staff will direct you."


MAX_LISTED_EXITS = 4  # an SMS for someone whose position we don't know


def _floor_of(building: Building, location: dict | None) -> int | None:
    if not location:
        return None
    if location.get("floor") is not None:
        return location["floor"]
    if location.get("anchor") and location.get("source") == "floor":
        ny = location["anchor"]["ny"]
        return min(building.floors, key=lambda f: abs(f.ny - ny)).level
    return None


def instruction(
    building: Building,
    evacuation: Evacuation | None,
    location: dict | None,
    *,
    update: bool = False,
    lead: str | None = None,
) -> dict:
    """The approved route for someone at this location, as the text we send them."""
    if evacuation is None:
        return {"exit_id": None, "exit_label": None, "message": None}
    zone_id = zone_for(building, location)
    exit_id = (evacuation.approved_routes or {}).get(zone_id) if zone_id else None
    prefix = "DRILL: " if evacuation.mode == "drill" else ""
    origin = evacuation.origin_label or "the building"
    lead = lead or ("Route update" if update else f"Fire reported at {origin}")
    if outside(building, zone_id):  # already outside: move away from the building
        return {
            "exit_id": None,
            "exit_label": None,
            "zone_id": zone_id,
            "message": f"{prefix}{lead}. You're outside on {building.zone(zone_id).label}. Move away from the building "
            "and stay clear of the doors; staff will direct you. Reply SAFE when you're clear, or HELP.",
        }
    if zone_id is None:  # position unknown: the approved exits (on their floor if we know it)
        floor = _floor_of(building, location)
        routes = evacuation.approved_routes or {}
        on_floor = [
            x
            for z, x in routes.items()
            if floor is not None and building.zone(z) and building.zone(z).floor == floor
        ]
        ids = on_floor or list(routes.values())
        # the exits most zones are routed to first; an SMS can't list every door
        ranked = sorted(dict.fromkeys(ids), key=lambda x: -ids.count(x))
        exits = [building.exit(x) for x in ranked if building.exit(x)][:MAX_LISTED_EXITS]
        if not exits:
            return {
                "exit_id": None,
                "exit_label": None,
                "zone_id": None,
                "message": f"{prefix}{lead}. Stay where you are, close the door, keep low. Reply with where you are, "
                "or HELP or CALL, and call 911 if you can.",
            }
        return {
            "exit_id": None,
            "exit_label": None,
            "zone_id": None,
            "exits": [e.id for e in exits],
            "message": f"{prefix}{lead}. Leave now by the nearest of: {', '.join(e.label for e in exits)}. "
            f"Avoid {origin}. Don't use the elevator. Reply SAFE, HELP, or CALL, and tell us where you are.",
        }
    if exit_id:
        exit = building.exit(exit_id)
        planned, then_id = engine_exit(building, evacuation, zone_id)
        then = building.exit(then_id) if planned == exit_id and then_id else None
        way = f"{exit.label}, then out by {then.label}" if then else exit.label
        down = " Don't use the elevator." if exit.kind == "stair" else ""
        message = (
            f"{prefix}{lead}. Leave now via {way}. {once_out(building)}{down} "
            "Reply SAFE, HELP, or CALL."
        )
        return {
            "exit_id": exit_id,
            "exit_label": exit.label,
            "zone_id": zone_id,
            "message": message,
        }
    zone = building.zone(zone_id) if zone_id else None
    return {
        "exit_id": None,
        "exit_label": None,
        "zone_id": zone_id,
        "message": f"{prefix}Fire reported at {origin}. Stay where you are{' in ' + zone.label if zone else ''}, close the door, "
        "keep low. Responders know your location. Reply HELP or CALL, and call 911 if you can.",
    }


# ---------------------------------------------------------------- proposals


def proposal_out(p: RouteProposal, building: Building) -> dict[str, Any]:
    zone = building.zone(p.zone_id)
    src, dst = building.exit(p.from_exit_id), building.exit(p.to_exit_id)
    return {
        "id": p.id,
        "zone_id": p.zone_id,
        "zone_label": zone.label if zone else p.zone_id,
        "from_exit_id": p.from_exit_id,
        "from_exit_label": src.label if src else None,
        "to_exit_id": p.to_exit_id,
        "to_exit_label": dst.label if dst else "Shelter in place",
        "status": p.status.value,
        "rationale": p.rationale,
        "affected": p.affected,
        "hazard_version": p.hazard_version,
        "proposed_by": p.proposed_by,
        "decided_by": p.decided_by,
        "created_at": p.created_at.isoformat(),
        "requires_dispatcher_approval": True,
    }


def approved_exits(evacuation: Evacuation) -> list[str]:
    """Every exit some zone is approved to use, in plan order (what unknown-position people are told)."""
    return list(dict.fromkeys((evacuation.approved_routes or {}).values()))


async def _people_in_zone(
    session: AsyncSession, building: Building, zone_id: str | None
) -> list[Occupant]:
    """People not yet safe in this zone (zone_id None = people whose position we don't know)."""
    occupants = (
        (
            await session.execute(
                select(Occupant).where(
                    Occupant.building_id == building.id,
                    Occupant.status != OccupantStatus.confirmed_safe,
                )
            )
        )
        .scalars()
        .all()
    )
    return [o for o in occupants if zone_for(building, o.location) == zone_id]


async def _would_tell(
    session: AsyncSession,
    building: Building,
    evacuation: Evacuation,
    zone_id: str,
    to_exit: str | None,
) -> int:
    """How many people approving this change messages: the zone, plus unknown-position people if
    their all-exits list changes."""
    count = len(await _people_in_zone(session, building, zone_id))
    routes = dict(evacuation.approved_routes or {})
    if to_exit:
        routes[zone_id] = to_exit
    else:
        routes.pop(zone_id, None)
    if list(dict.fromkeys(routes.values())) != approved_exits(evacuation):
        count += len(await _people_in_zone(session, building, None))
    return count


async def reevaluate(
    session: AsyncSession, building: Building, evacuation: Evacuation | None = None
) -> list[RouteProposal]:
    """After any hazard or fire-model change: propose changes for zones whose approved exit became unsafe."""
    evacuation = evacuation or await active_evacuation(session, building.id)
    if evacuation is None:
        return []
    states = await exit_states(session, building, evacuation)
    open_props = (
        (
            await session.execute(
                select(RouteProposal).where(
                    RouteProposal.evacuation_id == evacuation.id,
                    RouteProposal.status == ProposalStatus.proposed,
                )
            )
        )
        .scalars()
        .all()
    )
    created = []
    for zone_id in route_zones(building):
        current = (evacuation.approved_routes or {}).get(zone_id)
        cur = states.get(current) if current else None
        overloaded = cur is not None and cur.heading > CAPACITY
        if cur is not None and not cur.unsafe and not overloaded:
            for p in open_props:  # the situation recovered: drop pending changes for this zone
                if p.zone_id == zone_id:
                    p.status = ProposalStatus.stale
            continue
        preferred, _ = engine_exit(building, evacuation, zone_id)
        best, dist = choose_exit(building, zone_id, states, preferred, minute_now(evacuation))
        if best == current:
            continue
        zone = building.zone(zone_id)
        why_from = (
            f"{cur.label}: {'; '.join(cur.reasons)}"
            if cur and cur.unsafe
            else f"{cur.label} is overcrowded ({cur.heading} heading)"
            if cur
            else "no approved route"
        )
        why_to = (
            f"Proposed {states[best].label}: "
            + (
                "the engine's planned route now (simulation), "
                if best and best == preferred
                else "open, "
            )
            + f"{dist:.0f} m from {zone.label}, {states[best].heading} heading"
            if best
            else "No safe exit: shelter in place and send crews"
        )
        rationale = f"{why_from}. {why_to}."
        affected = await _would_tell(session, building, evacuation, zone_id, best)
        same = next((p for p in open_props if p.zone_id == zone_id and p.to_exit_id == best), None)
        if same:  # refresh against the latest hazard picture
            same.rationale, same.affected, same.hazard_version = (
                rationale,
                affected,
                evacuation.hazard_version,
            )
            continue
        for p in open_props:
            if p.zone_id == zone_id:
                p.status = ProposalStatus.stale
        proposal = RouteProposal(
            evacuation_id=evacuation.id,
            building_id=building.id,
            zone_id=zone_id,
            from_exit_id=current,
            to_exit_id=best,
            rationale=rationale,
            affected=affected,
            hazard_version=evacuation.hazard_version,
        )
        session.add(proposal)
        created.append(proposal)
    await session.commit()
    for p in created:
        await hub.publish(
            "route.proposed", building_id=building.id, data={"proposal": proposal_out(p, building)}
        )
    return created


async def bump_hazards(session: AsyncSession, building: Building) -> None:
    """Hazard picture changed: new version, then re-check every zone's route."""
    evacuation = await active_evacuation(session, building.id)
    if evacuation is None:
        return
    evacuation.hazard_version += 1
    await session.commit()
    await reevaluate(session, building, evacuation)


async def decide(
    session: AsyncSession,
    building: Building,
    proposal: RouteProposal,
    approve: bool,
    dispatcher: str,
) -> dict:
    evacuation = await session.get(Evacuation, proposal.evacuation_id)
    if (
        proposal.status == ProposalStatus.stale
    ):  # superseded: point the dispatcher at what replaced it
        raise StaleProposal(
            await session.scalar(
                select(RouteProposal)
                .where(
                    RouteProposal.evacuation_id == proposal.evacuation_id,
                    RouteProposal.zone_id == proposal.zone_id,
                    RouteProposal.status == ProposalStatus.proposed,
                )
                .limit(1)
            )
        )
    if proposal.status != ProposalStatus.proposed:
        raise ValueError(f"proposal is already {proposal.status.value}")
    if evacuation is None or evacuation.status != "active":
        raise ValueError("evacuation is not active")
    if proposal.hazard_version != evacuation.hazard_version:
        proposal.status = ProposalStatus.stale
        await session.commit()
        fresh = await reevaluate(session, building, evacuation)
        replacement = next((p for p in fresh if p.zone_id == proposal.zone_id), None)
        if replacement is None:
            replacement = await session.scalar(
                select(RouteProposal)
                .where(
                    RouteProposal.evacuation_id == evacuation.id,
                    RouteProposal.zone_id == proposal.zone_id,
                    RouteProposal.status == ProposalStatus.proposed,
                )
                .limit(1)
            )
        raise StaleProposal(replacement)

    proposal.status = ProposalStatus.approved if approve else ProposalStatus.rejected
    proposal.decided_by, proposal.decided_at = dispatcher, utcnow()
    recipients = []
    if approve:
        before = approved_exits(evacuation)
        routes = dict(evacuation.approved_routes or {})
        if proposal.to_exit_id:
            routes[proposal.zone_id] = proposal.to_exit_id
        else:
            routes.pop(proposal.zone_id, None)
        evacuation.approved_routes = routes
        told = await _people_in_zone(session, building, proposal.zone_id)
        if approved_exits(evacuation) != before:  # the all-exits message changed too
            told += await _people_in_zone(session, building, None)
        for occ in told:
            msg = instruction(building, evacuation, occ.location, update=True)
            occ.last_instruction = msg["message"]
            if msg["exit_id"] and occ.status == OccupantStatus.contacted:
                occ.exit_id = msg["exit_id"]
            recipients.append(
                {
                    "phone": occ.phone,
                    "name": occ.name,
                    "message": msg["message"],
                    "exit_id": msg["exit_id"],
                }
            )
    await session.commit()
    event = "route.approved" if approve else "route.rejected"
    await hub.publish(
        event,
        building_id=building.id,
        data={
            "proposal": proposal_out(proposal, building),
            "recipients_count": len(recipients),
            "decided_by": dispatcher,
        },
    )
    await hub.send_texts(
        building.id,
        recipients,
        reason="route_change",
        drill=evacuation.mode != "live",
        approved_by=dispatcher,
    )
    return {"proposal": proposal_out(proposal, building), "recipients": recipients}


class ProposalRejected(ValueError):
    pass


async def propose_from_agent(
    session: AsyncSession,
    building: Building,
    *,
    zone: str,
    to_exit: str | None,
    rationale: str,
    proposed_by: str,
) -> RouteProposal:
    """An agent's route proposal, checked against the safety rules before a dispatcher ever sees it."""
    evacuation = await active_evacuation(session, building.id)
    if evacuation is None:
        raise ProposalRejected("No active evacuation")
    zone_id = (
        zone
        if building.zone(zone)
        else (m[1] if (m := loc.match_place(building, zone, kinds=("zone",))) else None)
    )
    if zone_id not in plan_zones(building):
        raise ProposalRejected(f"Unknown zone {zone!r}; use a zone id from the building profile")
    if zone_id not in route_zones(building):
        raise ProposalRejected(
            f"{building.zone(zone_id).label} is outdoors; people there move away from the building"
        )
    exit_id = None
    if to_exit:
        exit_id = to_exit if building.exit(to_exit) else loc.match_exit(building, to_exit)
        if not exit_id:
            raise ProposalRejected(
                f"Unknown exit {to_exit!r}; routes may only use exits in the building profile"
            )
        x = building.exit(exit_id)
        if x.assembly and not x.zone:
            raise ProposalRejected(f"{x.label} is not a way out of the building; propose a door")
        here = building.zone(zone_id).floor
        if exit_floor(building, x) != here and any(
            exit_floor(building, e) == here for e in building.exits
        ):
            raise ProposalRejected(
                f"{x.label} is on another floor; people on floor {here} leave by an exit on their floor"
            )
        state = (await exit_states(session, building, evacuation))[exit_id]
        if state.unsafe:
            raise ProposalRejected(
                f"{state.label} is unsafe ({'; '.join(state.reasons)}); propose an open exit"
            )
    current = (evacuation.approved_routes or {}).get(zone_id)
    if exit_id == current:
        raise ProposalRejected("That is already the approved route for this zone")
    affected = await _would_tell(session, building, evacuation, zone_id, exit_id)
    open_props = (
        (
            await session.execute(
                select(RouteProposal).where(
                    RouteProposal.evacuation_id == evacuation.id,
                    RouteProposal.zone_id == zone_id,
                    RouteProposal.status == ProposalStatus.proposed,
                )
            )
        )
        .scalars()
        .all()
    )
    for p in open_props:
        if (
            p.to_exit_id == exit_id
        ):  # agrees with the safety rules' proposal: enrich it, keep one card
            p.rationale = (
                f"{rationale.strip()} (Safety rules agree: {p.rationale})"
                if p.proposed_by == "rules"
                else rationale
            )
            p.proposed_by = f"{proposed_by}+rules" if p.proposed_by == "rules" else proposed_by
            p.hazard_version = evacuation.hazard_version
            await session.commit()
            return p
        p.status = ProposalStatus.stale
    proposal = RouteProposal(
        evacuation_id=evacuation.id,
        building_id=building.id,
        zone_id=zone_id,
        from_exit_id=current,
        to_exit_id=exit_id,
        rationale=rationale.strip()[:1500],
        affected=affected,
        hazard_version=evacuation.hazard_version,
        proposed_by=proposed_by,
    )
    session.add(proposal)
    await session.commit()
    await hub.publish(
        "route.proposed",
        building_id=building.id,
        data={"proposal": proposal_out(proposal, building)},
    )
    return proposal
