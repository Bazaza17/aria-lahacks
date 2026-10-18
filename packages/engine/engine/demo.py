"""Slice-1 demo: venue.json -> fire timeline -> Aria's plan vs reactive routes -> one JSON.

    uv run python -m engine.demo --start 140 --summary
    uv run python -m engine.demo --start 110 --departures 0,60,120,180,300 \\
        --frame-step 30 --out aria_110.json

Loads venue.json through engine.aria_venue, runs engine.fire.simulate on the adapted venue
(with a 600 °C layer flashover criterion), maps the timeline back to venue ids, then at each
departure time routes every indoor space to SAFE twice: Aria's capacity-aware predictive plan
and the reactive routes people would take from what they see, both checked for door and stair
flow. It also scans departure times to find where the plan matters most.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from engine import outputs, summary
from engine.aria_venue import (
    EVENT_NIGHT_RULES,
    K_LEVEL_M_S,
    K_STAIR_M_S,
    VENUE_JSON,
    WALK_LEVEL_M_S,
    WALK_RAMP_M_S,
    WALK_STAIR_M_S,
    AriaVenue,
    load_aria_venue,
)
from engine.constants import ALPHA_KW_S2
from engine.evacuate import evacuate
from engine.fire import simulate
from engine.route_graph import FS_LEVEL_P_S_M, FS_STAIR_P_S_M
from engine.routes import (
    FLASHOVER_LAYER_C,
    MARGINAL_S,
    ORIGIN_LIMIT_KW,
    Blocks,
    exit_reach,
    exit_sides,
    exits_lost,
    venue_timeline,
)

SCHEMA_VERSION = "aria-engine-demo/2"
DEFAULT_START = "140"  # Collins Room, part 140: the biggest hacking area
DEFAULT_DEPARTURES = (0.0, 60.0, 120.0, 180.0, 300.0)
DEFAULT_SCAN_STEP_S = 15.0

ASSUMPTIONS = [
    "Fire: engine.fire screening zone model (t² growth capped by fuel and air, NFPA 92 plume, "
    "one smoke layer per room, buoyant door spill, ISO 13571-style untenability: layer below "
    "2 m or above 200 °C). Flashover at Thomas's Q_fo or an upper layer of 600 °C (Peacock et "
    "al. 1999), whichever comes first; after it, fire spreads as engine.fire sets out. No "
    "sprinklers, smoke control or fire service: a worst-case pre-plan.",
    "Room of origin: untenable once the fire radiates 2.5 kW/m² (ISO 13571) at 3 m, a point "
    "source with radiative fraction 0.3: about 942 kW, 2:22 into a fast fire. The zone model "
    "alone keeps a room that vents into a big neighbour tenable much longer.",
    "Skylight wells: each open_to_below space and the 1F spaces under it are ONE fire room, "
    "modelled as a box with the true top (the skylights) and the true volume, so its floor area "
    "is volume / height. 2F well edges are doors of that room at the 2F level.",
    "Step bands: two indoor spaces joined by a `step` opening (no wall, no door: 140 and 150) "
    "are one fire room the same way.",
    "Spaces inside a merged room are judged from their own floor and ceiling (the Galleria far "
    "end at +0.62 m, 150 at +0.70 m), from the room's layer at 1 s steps.",
    "Door tops sit at the real header height above the higher floor (150's opening to the "
    "Galleria tops out at 3.7 m). Outside merged rooms the fire model still uses one elevation "
    "per storey.",
    "Unprotected interior stairs between two ordinary rooms are stair shafts (open at both "
    "ends); stair 100ST, inside a well, is an open 2F door of the atrium.",
    "Outdoor spaces and SAFE are outside: smoke vents there and they never block.",
    "Exterior doors are closed for smoke (no venting) but usable for egress. A room of origin "
    "with no open opening at all gets its doors opened, or the fire would starve.",
    "Elevators: not egress; landing doors closed (60 min); the hoistway carries no smoke.",
    "Routes walk door to door at the SFPE free speed (1.20 m/s level, 0.92 m/s along 7/11 "
    "stairs). A route must cross each opening before it is blocked and enter each space before "
    "it is blocked; a space blocked at departure is trapped. No pre-movement delay: the "
    "departure time is when people start moving.",
    "Each space's occupant_load moves as a group. Openings pass at most 1.3 people/s per metre "
    "of effective width (1.01 on stairs, SFPE). Aria's plan books door and stair time group by "
    "group (greedy CCRP) and keeps the best of four candidate plans; reactive groups queue "
    "first come, first served. People still queued when an opening closes are at risk.",
    f"Cut-offs and margins under {MARGINAL_S:.0f} s are flagged marginal: inside the models' "
    "timing error.",
]


def _core(
    start: str,
    growth: str,
    horizon_s: float,
    departures: tuple[float, ...],
    venue_path: str | Path,
    door_overrides: dict[str, bool] | None,
    open_origin_doors: bool,
    origin_limit: bool,
    avoid_origin: bool,
) -> tuple:
    """Fire, per-venue timeline, blocks and the evacuation at each departure time."""
    if horizon_s <= 0:
        raise ValueError(f"horizon must be > 0 s, got {horizon_s}")
    if growth not in ALPHA_KW_S2:
        raise ValueError(f"unknown growth {growth!r}; use one of {sorted(ALPHA_KW_S2)}")
    av = load_aria_venue(
        venue_path,
        door_overrides=door_overrides,
        origin_space=start,
        open_origin_doors=open_origin_doors,
    )
    room = av.fire_room(start)
    # 1 s frames inside (per-space times in merged rooms, the origin limit); thinned for output.
    tl = simulate(av.fire, room, growth, horizon_s, 1.0, flashover_layer_c=FLASHOVER_LAYER_C)
    limit_kw = ORIGIN_LIMIT_KW if origin_limit else math.inf
    vt = venue_timeline(av, tl, origin_space=start, origin_limit_kw=limit_kw)
    blocks = Blocks.from_venue_timeline(vt, avoid=[start] if avoid_origin else ())
    deps = evacuate(av.graph, blocks, av.route_sources(), departures)
    return av, tl, vt, blocks, deps, limit_kw


def run_demo(
    start: str = DEFAULT_START,
    growth: str = "fast",
    horizon_s: float = 900.0,
    departures: tuple[float, ...] = DEFAULT_DEPARTURES,
    frame_step_s: float = 30.0,
    venue_path: str | Path = VENUE_JSON,
    door_overrides: dict[str, bool] | None = None,
    open_origin_doors: bool = True,
    origin_limit: bool = True,
    avoid_origin: bool = False,
    scan_step_s: float = DEFAULT_SCAN_STEP_S,
    sensitivity: bool = False,
) -> dict:
    """Run fire + routes for one start space and return the demo JSON as a dict.
    With sensitivity, also rerun with each uncertain open connection closed."""
    args = (start, growth, horizon_s, departures, venue_path)
    rules = (open_origin_doors, origin_limit, avoid_origin)
    av, tl, vt, blocks, deps, limit_kw = _core(*args, door_overrides, *rules)
    room = av.fire_room(start)
    sources = av.route_sources()
    grid = _grid(horizon_s, scan_step_s)
    scan = _scan(evacuate(av.graph, blocks, sources, grid), scan_step_s)
    exits_out = {oid: outside for oid, (_, outside) in exit_sides(av).items()}
    reach = exit_reach(av.graph, blocks, sources, exits_out, grid)
    lost = exits_lost(av, vt, reach)
    events = outputs.events(av, tl, vt, lost)
    frames = outputs.frames(av, tl, vt, start, frame_step_s)
    result = {
        "schema_version": SCHEMA_VERSION,
        "venue_schema_version": av.raw.get("schema_version"),
        "building": av.raw.get("building", {}),
        "frame": av.raw.get("frame", {}),
        "scenario": {
            "start_space": start,
            "fire_room": room,
            "growth": growth,
            "horizon_s": horizon_s,
            "departures_s": list(departures),
            "frame_step_s": frame_step_s,
            "scan_step_s": scan_step_s,
            "origin_limit": origin_limit,
            "avoid_origin_room": avoid_origin,
        },
        "assumptions": _assumptions(av, open_origin_doors, door_overrides or {}),
        "adapter": _adapter(av),
        "geometry": outputs.geometry(av),
        "fire": {
            "criteria": {
                "flashover_layer_c": FLASHOVER_LAYER_C,
                "origin_limit_kw": None if math.isinf(limit_kw) else round(limit_kw),
            },
            "validity": outputs.validity(tl),
            "origin": vt["origin"],
            "spaces": vt["spaces"],
            "openings": vt["openings"],
            "exits": lost,
            "events": events,
            "fire_rooms": tl.rooms,
            "fire_doors": tl.doors,
        },
        "viewer": {
            **outputs.viewer(av, tl, start, growth, frames, events, lost),
            "routes": outputs.viewer_routes(deps),
        },
        "routes": {"departures": deps, "scan": scan},
    }
    result["summary"] = summary.build(av, tl, vt, start, deps, scan, lost)
    if sensitivity:
        result["sensitivity"] = _sensitivity(args, rules, door_overrides or {}, deps, lost, av)
    return result


def _sensitivity(
    args: tuple, rules: tuple, overrides: dict[str, bool], deps: list[dict], lost: list, av
) -> list[dict]:
    """Each uncertain open connection closed in turn: people at risk per departure time (plan
    and reactive) and the first exit lost, against the base run."""

    def first_lost(rows: list[dict]) -> float | None:
        return min((e["lost_s"] for e in rows if e["lost_s"] is not None), default=None)

    def risk(ds: list[dict], mode: str) -> list[int]:
        return [d["occupants_at_risk"][mode] for d in ds]

    rows = [
        {
            "opening": None,
            "plan_at_risk": risk(deps, "predictive"),
            "reactive_at_risk": risk(deps, "reactive"),
            "first_exit_lost_s": first_lost(lost),
        }
    ]
    for oid in summary.uncertain_open(av):
        if oid in overrides:
            continue
        alt_av, _, alt_vt, _, alt_deps, _ = _core(*args, {**overrides, oid: False}, *rules)
        rows.append(
            {
                "opening": oid,
                "plan_at_risk": risk(alt_deps, "predictive"),
                "reactive_at_risk": risk(alt_deps, "reactive"),
                "first_exit_lost_s": first_lost(exits_lost(alt_av, alt_vt)),
            }
        )
    return rows


def _grid(horizon_s: float, step_s: float) -> list[float]:
    step = max(step_s, 1.0)
    return [i * step for i in range(int(horizon_s // step) + 1)]


def _scan(deps: list[dict], step_s: float) -> list[dict]:
    """People at risk per departure time, plan vs reactive, and who the plan saves.
    `saved_clear` leaves out the marginal cases (cut-offs or margins under MARGINAL_S)."""
    rows = []
    for d in deps:
        risk = d["occupants_at_risk"]
        rows.append(
            {
                "t0_s": d["t0_s"],
                "step_s": step_s,
                "at_risk": risk,
                "saved": risk["reactive"] - risk["predictive"],
                "saved_clear": sum(c["saved"] for c in d["contrasts"] if not c["marginal"]),
                "plan": d["plan"]["chosen"],
                "contrasts": [_brief(c) for c in d["contrasts"][:6]],
            }
        )
    return rows


def _brief(c: dict) -> dict:
    r, p = c["reactive"], c["predictive"]
    return {
        "space": c["space"],
        "occupants": c["occupants"],
        "saved": c["saved"],
        "marginal": c["marginal"],
        "reactive": {k: r[k] for k in ("status", "at_risk", "exit", "limited_by")},
        "predictive": {k: p[k] for k in ("status", "at_risk", "exit", "margin_s")},
    }


def _assumptions(av: AriaVenue, open_origin: bool, overrides: dict[str, bool]) -> dict:
    return {
        "notes": ASSUMPTIONS,
        "event_night_rules": {
            k: {
                "open": r.open,
                "fire_rating_min": r.fire_rating_min,
                "egress": r.egress,
                "why": r.why,
            }
            for k, r in EVENT_NIGHT_RULES.items()
        },
        "door_states": av.door_states,
        "door_overrides": overrides,
        "sealed_origin_doors_opened": open_origin,
        "walking": {
            "level_m_s": round(WALK_LEVEL_M_S, 3),
            "stair_m_s": round(WALK_STAIR_M_S, 3),
            "ramp_m_s": round(WALK_RAMP_M_S, 3),
            "source": f"SFPE hydraulic model free speed: k(1 - 0.266*0.54), k = {K_LEVEL_M_S} m/s "
            f"level, {K_STAIR_M_S} m/s on 7/11 stairs (along the slope)",
        },
        "flow": {
            "level_p_s_m": FS_LEVEL_P_S_M,
            "stair_p_s_m": FS_STAIR_P_S_M,
            "source": "SFPE maximum specific flow per metre of effective width",
        },
    }


def _adapter(av: AriaVenue) -> dict:
    return {
        "fire_rooms": len(av.fire.rooms),
        "fire_doors": len(av.fire.doors),
        "merged_rooms": av.merged,
        "space_to_fire_room": av.room_of,
        "opening_to_fire_doors": av.doors_of_opening,
        "stair_shafts": av.shaft_of_opening,
        "fire_excluded_openings": av.fire_excluded,
        "route_nodes": len(av.graph.nodes),
        "route_arcs": av.graph.arc_count(),
        "route_legs": len(av.graph.legs),
        "route_excluded_openings": av.graph.excluded,
        "estimated_positions": av.graph.estimated_positions,
    }


def summary_text(result: dict) -> str:
    """A readable summary of run_demo's result."""
    return summary.text(result)


def _parse_door(spec: str) -> tuple[str, bool]:
    oid, _, state = spec.rpartition("=")
    if not oid or state not in ("open", "closed"):
        raise argparse.ArgumentTypeError(f"--door expects ID=open or ID=closed, got {spec!r}")
    return oid, state == "open"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m engine.demo", description=__doc__.split("\n")[0])
    p.add_argument("--venue", default=str(VENUE_JSON), help="venue.json path")
    p.add_argument("--start", default=DEFAULT_START, help="indoor space id where the fire starts")
    p.add_argument("--growth", default="fast", choices=sorted(ALPHA_KW_S2))
    p.add_argument("--horizon", type=float, default=900.0, help="seconds to simulate")
    p.add_argument(
        "--departures", default="0,60,120,180,300", help="comma-separated departure times (s)"
    )
    p.add_argument("--frame-step", type=float, default=30.0, help="s between frames (0: none)")
    p.add_argument(
        "--scan-step", type=float, default=DEFAULT_SCAN_STEP_S, help="s between scanned departures"
    )
    p.add_argument("--out", help="write the JSON to this file")
    p.add_argument(
        "--viewer-out",
        help="also write just the viewer block (FireTimeline + routes) here, e.g. "
        "../../apps/web/public/fire/venue.json",
    )
    p.add_argument("--summary", action="store_true", help="print a readable summary")
    p.add_argument(
        "--door",
        action="append",
        default=[],
        type=_parse_door,
        metavar="ID=open|closed",
        help="override one opening's event-night state for smoke and fire (repeatable); people "
        "can still walk through a closed door",
    )
    p.add_argument(
        "--keep-origin-doors",
        action="store_true",
        help="don't open the doors of a room of origin that has no open opening",
    )
    p.add_argument(
        "--no-origin-limit",
        action="store_true",
        help="judge the room of origin by the zone model only (no 942 kW radiant limit)",
    )
    p.add_argument(
        "--sensitivity",
        action="store_true",
        help="also rerun with each uncertain open connection closed (slower)",
    )
    p.add_argument(
        "--avoid-origin",
        action="store_true",
        help="never route anyone into the start space, even before the fire grows",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    p = _parser()
    args = p.parse_args(argv)
    try:
        departures = tuple(float(x) for x in args.departures.split(",") if x.strip())
    except ValueError:
        p.error(f"--departures expects numbers, got {args.departures!r}")
    if args.horizon <= 0:
        p.error(f"--horizon must be > 0, got {args.horizon}")
    late = [t for t in departures if t >= args.horizon]
    if late:
        print(f"warning: departures at or after the horizon: {late}", file=sys.stderr)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    try:
        result = run_demo(
            start=args.start,
            growth=args.growth,
            horizon_s=args.horizon,
            departures=departures,
            frame_step_s=args.frame_step,
            venue_path=args.venue,
            door_overrides=dict(args.door),
            open_origin_doors=not args.keep_origin_doors,
            origin_limit=not args.no_origin_limit,
            avoid_origin=args.avoid_origin,
            scan_step_s=args.scan_step,
            sensitivity=args.sensitivity,
        )
    except ValueError as err:
        p.error(str(err))
    if args.out:
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    if args.viewer_out:
        Path(args.viewer_out).write_text(
            json.dumps(result["viewer"], ensure_ascii=False), encoding="utf-8"
        )
    if args.summary:
        print(summary_text(result))
        if args.out:
            print(f"\nJSON written to {args.out}")
    elif not args.out:
        json.dump(result, sys.stdout, ensure_ascii=False)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
