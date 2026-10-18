"""The live layer's fire model, from Aria's building engine (packages/engine via app.routes.engine).

A drill or fire declared with an origin runs the engine for that start space and turns its result
into the evacuation's fire_model:
- steps: when smoke enters and when each zone becomes untenable (the engine's fire.spaces, mapped
  through each zone's venue spaces), and when each exit is lost (fire.exits; for the inside stairs
  down from floor 2, fire.openings). Source "aria-engine", simulation true.
- routes: the engine's capacity-aware (predictive) exit for every zone at each departure time
  (routes.departures[].spaces[space].predictive), mapped to the profile's exits. Floor 2 zones
  get the stair their engine route goes down, and "then" the door it leaves by.
- summary: exits lost with times and the at-risk / last-out numbers for leaving now, which the
  console and the CREAO agents quote.
Everything here is a simulation from the venue model; nothing is observed.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.creao import location as loc
from app.creao.buildings import Building, Zone

SOURCE = "aria-engine"
DEFAULT_GROWTH = "fast"


def _minute(seconds: float | None) -> float | None:
    return None if seconds is None else round(seconds / 60, 1)


# Spaces nobody evacuates from or ignites (the engine's NON_WALKING_KINDS).
NOT_A_START = ("open_to_below", "elevator")


def _venue_json() -> Path:
    here = Path(__file__).resolve().parents[4] / "packages" / "engine" / "venue.json"
    if here.is_file():
        return here
    import engine  # noqa: PLC0415  (the engine package, wherever the deploy put it)

    return Path(engine.__file__).resolve().parents[1] / "venue.json"


@lru_cache(maxsize=1)
def start_spaces() -> dict[str, dict]:
    """Indoor venue spaces a fire can start in (the same set as /engine/starts), read from
    venue.json here so only run(start, growth) is shared with the engine route."""
    venue = json.loads(_venue_json().read_text(encoding="utf-8"))
    return {
        s["id"]: {
            "id": s["id"],
            "name": s.get("event_name") or s.get("name") or s["id"],
            "storey": s.get("storey"),
            "occupant_load": s.get("occupant_load", 0),
        }
        for s in venue["spaces"]
        if not s.get("is_outdoor") and s.get("kind") not in NOT_A_START
    }


def resolve_start(
    building: Building, origin: str | None, starts: dict[str, dict]
) -> tuple[str, Zone | None] | None:
    """A declared origin (venue space id, zone id, or a place name) -> (start space, its zone)."""
    if not origin or not origin.strip():
        return None
    origin = origin.strip()
    zone_of = {sid: z for z in building.zones for sid in z.spaces}
    if origin in starts:
        return origin, zone_of.get(origin)
    zone = building.zone(origin)
    if zone is None and (place := loc.match_place(building, origin)):
        kind, pid = place
        zone = building.zone(pid if kind == "zone" else building.exit(pid).zone)
    if zone is None:
        return None
    candidates = [sid for sid in zone.spaces if sid in starts]
    if not candidates:
        return None
    best = max(candidates, key=lambda sid: starts[sid].get("occupant_load") or 0)
    return best, zone


def _route_exit(building: Building, zone: Zone, predictive: dict) -> tuple[str, str] | None:
    """The profile exit for an engine route: the stair down for an upper floor, else the door.
    Returns (exit id people are sent to, exit id they finally leave by)."""
    final = building.exit_for_opening(predictive.get("exit"))
    if final is None:
        return None
    if zone.floor > 1:
        for opening in predictive.get("path") or []:
            stair = building.exit_for_opening(opening)
            if stair and stair.floor == zone.floor:
                return stair.id, final.id
    return final.id, final.id


def _routes(building: Building, result: dict) -> list[dict]:
    out = []
    for dep in result["routes"]["departures"]:
        zones, then = {}, {}
        for zone in building.zones:
            if zone.outdoor and zone.floor == 1:
                continue  # already outside: no route
            votes: dict[tuple[str, str], int] = {}
            for sid in zone.spaces:
                pred = ((dep.get("spaces") or {}).get(sid) or {}).get("predictive") or {}
                if not pred.get("exit"):
                    continue
                pick = _route_exit(building, zone, pred)
                if pick:
                    people = (dep["spaces"][sid].get("occupants") or 0) + 1
                    votes[pick] = votes.get(pick, 0) + people
            if votes:
                (go, out_by), _ = max(votes.items(), key=lambda kv: kv[1])
                zones[zone.id] = go
                if out_by != go:
                    then[zone.id] = out_by
        out.append({"t0_min": round(dep["t0_s"] / 60, 2), "zones": zones, "then": then})
    return out


def _steps(building: Building, result: dict, origin_zone: Zone | None) -> list[dict]:
    fire = result["fire"]
    spaces = fire.get("spaces") or {}
    steps = []

    def add(t_s: float, place, kind: str, severity: str, place_kind: str) -> None:
        steps.append(
            {
                "minute": _minute(t_s),
                "t_s": round(t_s, 1),  # exact, for display (minute is rounded to 0.1)
                "place": place.id,
                "place_kind": place_kind,
                "label": place.label,
                "kind": kind,
                "severity": severity,
                "anchor": place.anchor.model_dump(),
            }
        )

    if origin_zone:
        add(0.0, origin_zone, "fire", "high", "zone")
    for zone in building.zones:
        rows = [spaces[s] for s in zone.spaces if s in spaces]
        smoke = [r["smoke_enters_s"] for r in rows if r.get("smoke_enters_s") is not None]
        bad = [r["blocked_s"] for r in rows if r.get("blocked_s") is not None]
        if smoke and zone is not origin_zone:
            add(min(smoke), zone, "smoke", "medium", "zone")
        if bad:
            add(min(bad), zone, "untenable", "high", "zone")
    lost = {e["exit"]: e.get("lost_s") for e in fire.get("exits") or []}
    openings = fire.get("openings") or {}
    for x in building.exits:
        times = [
            lost.get(op) if x.exterior else (openings.get(op) or {}).get("blocked_s")
            for op in (x.openings or [x.opening])
        ]
        times = [t for t in times if t is not None]
        if times:
            add(min(times), x, "exit lost", "high", "exit")
    steps.sort(key=lambda s: s["minute"])
    return steps


def _summary(building: Building, result: dict, start: str, origin_label: str) -> dict:
    fire, summ = result["fire"], result.get("summary") or {}
    dep0 = (result["routes"]["departures"] or [{}])[0]
    exits_lost, kept = [], []
    steps = {s["place"]: s for s in _steps(building, result, None) if s["kind"] == "exit lost"}
    for x in building.exits:
        if x.id in steps:
            st = steps[x.id]
            exits_lost.append(
                {"exit_id": x.id, "label": x.label, "minute": st["minute"], "t_s": st["t_s"]}
            )
        else:
            kept.append({"exit_id": x.id, "label": x.label})
    exits_lost.sort(key=lambda e: e["t_s"])
    occupants = sum((s.get("occupants") or 0) for s in (dep0.get("spaces") or {}).values())
    # Same rule as the web size-up (routes/engine.py _all_out): groups that got people out.
    flows = [
        ((s.get("predictive") or {}).get("flow") or {}) for s in (dep0.get("spaces") or {}).values()
    ]
    last_out = [
        f["last_out_s"] for f in flows if f.get("cleared") and f.get("last_out_s") is not None
    ]
    at_risk = dep0.get("occupants_at_risk") or {}
    # Crowds are modelled at assumed capacity, so the console reports rooms, not people.
    occupied = [s for s in (dep0.get("spaces") or {}).values() if s.get("occupants")]

    def rooms_at_risk(mode: str) -> int:
        return sum(
            1
            for s in occupied
            if (s.get(mode) or {}).get("at_risk")
            or ((s.get(mode) or {}).get("status") or "ok") != "ok"
        )

    rooms_plan, rooms_self = rooms_at_risk("predictive"), rooms_at_risk("reactive")
    growth = result["scenario"].get("growth")
    first_bad = summ.get("first_untenable_beyond_origin") or summ.get("first_untenable") or {}
    lost_txt = (
        "; ".join(f"{e['label']} by minute {e['minute']:g}" for e in exits_lost[:6])
        or "none within the run"
    )
    text = (
        f"Simulation (Aria's engine, {growth} growth): fire starts in {origin_label}. "
        f"Exits lost: {lost_txt}. Leaving now on Aria's routes: "
        f"{rooms_plan} of {len(occupied)} occupied rooms have people at risk"
        + (f", last group out at minute {max(last_out) / 60:.1f}" if last_out else "")
        + f"; by the obvious way out instead: {rooms_self} rooms at risk. (Crowds are modelled "
        "at each room's assumed capacity, not a headcount.)"
    )
    return {
        "engine": SOURCE,
        "start_space": start,
        "origin_label": origin_label,
        "growth": growth,
        "exits_lost": exits_lost,
        "exits_kept": kept,
        "occupants": occupants,
        "at_risk_leaving_now": at_risk.get("predictive"),
        "at_risk_obvious_route": at_risk.get("reactive"),
        "rooms_occupied": len(occupied),
        "rooms_at_risk_leaving_now": rooms_plan,
        "rooms_at_risk_obvious_route": rooms_self,
        "last_out_min": round(max(last_out) / 60, 1) if last_out else None,
        "last_out_s": round(max(last_out), 1) if last_out else None,
        "first_untenable": {
            "minute": _minute(first_bad.get("t_s")),
            "space": first_bad.get("space"),
        }
        if first_bad
        else None,
        "flashover_min": _minute((summ.get("flashovers") or [{}])[0].get("t_s"))
        if summ.get("flashovers")
        else None,
        "origin_room_untenable_min": _minute((fire.get("origin") or {}).get("limit_s")),
        "text": text,
    }


def build_fire_model(building: Building, result: dict, zone: Zone | None = None) -> dict:
    """The evacuation's fire_model from one engine result (app.routes.engine.run)."""
    start = result["scenario"]["start_space"]
    zone = zone or next((z for z in building.zones if start in z.spaces), None)
    label = zone.label if zone else start
    return {
        "scenario_id": f"engine:{start}:{result['scenario'].get('growth')}",
        "label": f"{label} fire ({result['scenario'].get('growth')} growth, simulation)",
        "source": SOURCE,
        "simulation": True,
        "origin": {"space": start, "zone_id": zone.id if zone else None, "label": label},
        "steps": _steps(building, result, zone),
        "routes": _routes(building, result),
        "summary": _summary(building, result, start, label),
    }


async def fire_model_for(
    building: Building, origin: str | None, growth: str | None = None
) -> dict | None:
    """Run the engine for a declared origin; None when the origin names no start space."""
    from app.routes.engine import run  # noqa: PLC0415

    found = resolve_start(building, origin, start_spaces())
    if found is None:
        return None
    start, zone = found
    result = await run(start, growth or DEFAULT_GROWTH)
    return build_fire_model(building, result, zone)


def is_engine(model: dict | None) -> bool:
    return bool(model) and model.get("source") == SOURCE


def engine_route(model: dict | None, zone_id: str, minute: float) -> tuple[str | None, str | None]:
    """(exit, then-exit) the engine plans for this zone at the latest departure <= minute."""
    if not is_engine(model) or not model.get("routes"):
        return None, None
    best = None
    for dep in model["routes"]:
        if dep["t0_min"] <= minute + 1e-6:
            best = dep
    best = best or model["routes"][0]
    return best["zones"].get(zone_id), (best.get("then") or {}).get(zone_id)


def summary_brief(model: dict | None) -> dict[str, Any] | None:
    """What the agents and the console quote."""
    if not is_engine(model):
        return None
    return model.get("summary")
