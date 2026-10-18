"""Slice-1 demo: venue.json -> fire timeline -> predictive vs reactive routes -> one JSON.

    uv run python -m engine.demo --start 140 --summary
    uv run python -m engine.demo --start 110 --growth fast --departures 0,60,120,180,300 \\
        --frame-step 30 --out aria_110.json

Loads venue.json through engine.aria_venue, runs engine.fire.simulate on the adapted venue,
maps the timeline back to venue ids and routes every indoor space to SAFE at each departure time.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

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
from engine.fire import Timeline, simulate
from engine.routes import Blocks, evacuate, exits_lost, venue_timeline

SCHEMA_VERSION = "aria-engine-demo/1"
DEFAULT_START = "140"  # Collins Room, part 140: the biggest hacking area
DEFAULT_DEPARTURES = (0.0, 60.0, 120.0, 180.0, 300.0)

ASSUMPTIONS = [
    "Fire: engine.fire screening zone model (t² growth capped by fuel and air, NFPA 92 plume, "
    "one smoke layer per room, buoyant door spill, Thomas flashover, ISO 13571-style "
    "untenability: layer below 2 m or above 200 °C). No sprinklers, smoke control or fire "
    "service: a worst-case pre-plan.",
    "Skylight wells: each open_to_below space and the 1F spaces under it are ONE fire room: the "
    "1F floor area, with the ceiling set so the box holds the true volume (1F rooms plus the "
    "wells up to their tops). 2F well edges are doors of that room at the 2F level.",
    "Merged-room members on a different floor level (the Galleria far end, +0.62 m) are judged "
    "untenable from their own floor, using the room's layer at 1 s steps.",
    "Floor offsets outside merged rooms (150 at +0.62 m, the lawn at -0.6 m) are kept in "
    "venue.json but not used by the fire model, which uses one elevation per storey.",
    "Unprotected interior stairs between two ordinary rooms are stair shafts (open at both "
    "ends); stair 100ST, inside a well, is an open 2F door of the atrium.",
    "Outdoor spaces and SAFE are outside: smoke vents there and they never block.",
    "Exterior doors are closed for smoke (no venting) but usable for egress.",
    "Elevators: not egress; landing doors closed (60 min); the hoistway carries no smoke.",
    "Routes: one walker per space, free SFPE walking speed, no queues or pre-movement delay; "
    "departure time = when people start moving.",
    "A route must cross each opening before it is blocked and enter each space before it is "
    "blocked; a space blocked at departure is trapped.",
    "Routes never enter the room of fire origin from outside it (the zone model keeps it tenable "
    "until its layer drops, but nobody is sent past the fire); people inside may leave through "
    "it. --allow-origin-entry turns this off.",
]


def run_demo(
    start: str = DEFAULT_START,
    growth: str = "fast",
    horizon_s: float = 900.0,
    departures: tuple[float, ...] = DEFAULT_DEPARTURES,
    frame_step_s: float = 30.0,
    venue_path: str | Path = VENUE_JSON,
    door_overrides: dict[str, bool] | None = None,
    open_origin_doors: bool = True,
    avoid_origin: bool = True,
) -> dict:
    """Run fire + routes for one start space and return the demo JSON as a dict."""
    av = load_aria_venue(
        venue_path,
        door_overrides=door_overrides,
        origin_space=start,
        open_origin_doors=open_origin_doors,
    )
    room = av.fire_room(start)
    # 1 s frames inside (exact per-space times for merged rooms); thinned for the output.
    tl = simulate(av.fire, room, growth, horizon_s, frame_step_s=1.0)
    vt = venue_timeline(av, tl)
    blocks = Blocks.from_venue_timeline(vt, avoid=av.spaces_of[room] if avoid_origin else ())
    sources = av.route_sources()
    departures_out = evacuate(av.graph, blocks, sources, departures)
    lost = exits_lost(av, vt)
    events = _events(av, tl, vt, sources)
    result = {
        "schema_version": SCHEMA_VERSION,
        "venue_schema_version": av.raw.get("schema_version"),
        "building": av.raw.get("building", {}),
        "frame": av.raw.get("frame", {}).get("datum"),
        "scenario": {
            "start_space": start,
            "fire_room": room,
            "growth": growth,
            "horizon_s": horizon_s,
            "departures_s": list(departures),
            "frame_step_s": frame_step_s,
            "avoid_origin_room": avoid_origin,
        },
        "assumptions": _assumptions(av, open_origin_doors, door_overrides or {}),
        "adapter": _adapter(av),
        "fire": {
            "spaces": vt["spaces"],
            "openings": vt["openings"],
            "exits": lost,
            "events": events,
            "fire_rooms": tl.rooms,
            "fire_doors": tl.doors,
            "frames": _frames(av, tl, vt, frame_step_s),
        },
        "routes": {"departures": departures_out},
    }
    result["summary"] = _summary(av, tl, vt, sources, departures_out, lost)
    return result


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
        "origin_doors_opened": open_origin,
        "walking": {
            "level_m_s": round(WALK_LEVEL_M_S, 3),
            "stair_m_s": round(WALK_STAIR_M_S, 3),
            "ramp_m_s": round(WALK_RAMP_M_S, 3),
            "source": f"SFPE hydraulic model free speed: k(1 - 0.266*0.54), k = {K_LEVEL_M_S} m/s "
            f"level, {K_STAIR_M_S} m/s on 7/11 stairs (along the slope)",
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
        "route_excluded_openings": av.graph.excluded,
    }


def _venue_ids(av: AriaVenue, fire_id: str) -> list[str]:
    if av.spaces_of.get(fire_id):
        return av.spaces_of[fire_id]
    if fire_id in av.opening_of_door:
        return [av.opening_of_door[fire_id]]
    shafts = [oid for oid, rid in av.shaft_of_opening.items() if rid == fire_id]
    return shafts or [fire_id]


def _events(av: AriaVenue, tl: Timeline, vt: dict, sources: list[str]) -> list[dict]:
    events = [{**e, "venue_ids": _venue_ids(av, e["id"])} for e in tl.events]
    for sid in sources:
        info = vt["spaces"][sid]
        if info["floor_offset_m"] and info["smoke_untenable_s"] is not None:
            events.append(
                {
                    "t_s": info["smoke_untenable_s"],
                    "type": "untenable",
                    "id": sid,
                    "detail": f"{av.label(sid)} untenable (floor {info['floor_offset_m']:+.2f} m "
                    f"in {info['fire_room']})",
                    "venue_ids": [sid],
                }
            )
    return sorted(events, key=lambda e: e["t_s"])


def _frames(av: AriaVenue, tl: Timeline, vt: dict, step_s: float) -> list[dict]:
    """Per-space snapshots every step_s (plus the last step), from the 1 s fire frames."""
    if step_s <= 0 or not tl.frames:
        return []
    every = max(1, round(step_s))
    keep = [f for f in tl.frames if f["t_s"] % every == 0]
    if keep[-1] is not tl.frames[-1]:
        keep.append(tl.frames[-1])
    out = []
    for f in keep:
        t = f["t_s"]
        spaces = {}
        for sid, rid in av.room_of.items():
            row, info = f["rooms"][rid], vt["spaces"][sid]
            state = row["state"]
            if rid in av.merged and state in ("clear", "smoke", "untenable"):
                untenable = info["smoke_untenable_s"]
                if untenable is not None and untenable <= t:
                    state = "untenable"
                elif state == "untenable":
                    state = "smoke"
            spaces[sid] = {
                "layer_height_m": round(
                    max(0.0, row["layer_height_m"] - info["floor_offset_m"]), 2
                ),
                "layer_temp_c": row["layer_temp_c"],
                "hrr_kw": row["hrr_kw"],
                "state": state,
            }
        blocked = [
            k
            for group in (vt["spaces"], vt["openings"])
            for k, v in group.items()
            if v["blocked_s"] is not None and v["blocked_s"] <= t
        ]
        out.append({"t_s": t, "spaces": spaces, "blocked": sorted(blocked)})
    return out


def _first(vt: dict, ids: list[str], key: str) -> dict | None:
    rows = [(vt["spaces"][s][key], s) for s in ids if vt["spaces"][s][key] is not None]
    if not rows:
        return None
    t, sid = min(rows)
    return {"t_s": t, "space": sid}


def _summary(
    av: AriaVenue, tl: Timeline, vt: dict, sources: list[str], deps: list[dict], lost: list[dict]
) -> dict:
    beyond = [s for s in sources if vt["spaces"][s]["fire_room"] != tl.start_room]
    flashovers = sorted(
        (
            {"t_s": r["flashover_s"], "fire_room": rid, "spaces": _venue_ids(av, rid)}
            for rid, r in tl.rooms.items()
            if r["flashover_s"] is not None
        ),
        key=lambda x: x["t_s"],
    )
    return {
        "first_smoke_beyond_origin": _first(vt, beyond, "smoke_enters_s"),
        "first_untenable": _first(vt, sources, "smoke_untenable_s"),
        "first_untenable_beyond_origin": _first(vt, beyond, "smoke_untenable_s"),
        "flashovers": flashovers,
        "merged_member_offsets": [
            {
                "space": sid,
                "offset_m": vt["spaces"][sid]["floor_offset_m"],
                "untenable_s": vt["spaces"][sid]["smoke_untenable_s"],
            }
            for sid in sources
            if vt["spaces"][sid]["floor_offset_m"]
        ],
        "exits_lost": [e for e in lost if e["lost_s"] is not None],
        "exits_kept": [e["exit"] for e in lost if e["lost_s"] is None],
        "departures": [
            {
                "t0_s": d["t0_s"],
                "counts": d["counts"],
                "occupants_at_risk": d["occupants_at_risk"],
                "trapped": d["trapped"],
                "trapped_by_origin_only": d["trapped_by_origin_only"],
                "reactive_fails": [
                    {
                        k: f[k]
                        for k in (
                            "space",
                            "occupants",
                            "opening",
                            "reach_s",
                            "blocked_s",
                            "predictive",
                            "predictive_exit",
                            "predictive_eta_s",
                        )
                    }
                    for f in d["reactive_fails"]
                ],
                "different_exit": d["different_exit"],
            }
            for d in deps
        ],
    }


def _mmss(t: float | None) -> str:
    if t is None:
        return "  -  "
    t = int(round(t))
    return f"{t // 60:2d}:{t % 60:02d}"


def summary_text(result: dict) -> str:
    """A readable summary of run_demo's result."""
    s = result["summary"]
    lines = _header_lines(result)
    lines += ["", "Fire timeline (m:ss after ignition)", *_timeline_lines(s)]
    lines += ["", *_evacuation_lines(s)]
    lines += ["", "Predictive vs reactive (reactive route cut off on the way)", *_contrast_lines(s)]
    return "\n".join(lines)


def _header_lines(result: dict) -> list[str]:
    sc, adapter = result["scenario"], result["adapter"]
    lines = [
        f"Aria engine slice 1: {result['building'].get('name', '')}",
        f"Fire starts in {sc['start_space']} (fire room {sc['fire_room']}), {sc['growth']} t² "
        f"growth, {sc['horizon_s']:.0f} s horizon.",
        f"Model: {adapter['fire_rooms']} fire rooms, {adapter['fire_doors']} fire doors, "
        f"{len(adapter['stair_shafts'])} stair shafts; {adapter['route_nodes']} route nodes, "
        f"{adapter['route_arcs']} directed route arcs.",
    ]
    for rid, m in adapter["merged_rooms"].items():
        lines.append(
            f"Merged {rid}: {', '.join(m['spaces'])} ({m['floor_area_m2']:.0f} m² of floor, "
            f"{m['volume_m3']:.0f} m³ up to the skylights at {m['top_elevation_m']:.2f} m; "
            f"modelled as a {m['box_area_m2']:.0f} m² x {m['box_height_m']:.2f} m box)"
        )
    return lines


def _timeline_lines(s: dict) -> list[str]:
    lines, timeline = [], []
    for label, key in (
        ("first smoke beyond the origin", "first_smoke_beyond_origin"),
        ("first untenable space", "first_untenable"),
        ("first untenable beyond the origin", "first_untenable_beyond_origin"),
    ):
        row = s[key]
        if row:
            timeline.append((row["t_s"], f"{label}: {row['space']}"))
        else:
            lines.append(f"     -   {label}: none within the horizon")
    timeline += [(fo["t_s"], f"flashover: {fo['fire_room']}") for fo in s["flashovers"]]
    timeline += [
        (m["untenable_s"], f"untenable: {m['space']} (floor {m['offset_m']:+.2f} m)")
        for m in s["merged_member_offsets"]
        if m["untenable_s"] is not None
    ]
    timeline += [
        (e["lost_s"], f"exit lost: {e['exit']} (from {e['from']})") for e in s["exits_lost"]
    ]
    lines += [f"  {_mmss(t)}  {text}" for t, text in sorted(timeline, key=lambda x: x[0])]
    if not s["flashovers"]:
        lines.append("     -   no flashover within the horizon")
    lines.append(f"  exits never lost: {', '.join(s['exits_kept']) or 'none'}")
    return lines


def _evacuation_lines(s: dict) -> list[str]:
    lines = [
        "Evacuation by departure time (people = occupant_load of spaces not reaching SAFE)",
        "   t0    predictive ok/trapped (people)      reactive ok/cut off/trapped (people)",
    ]
    for d in s["departures"]:
        p, r = d["counts"]["predictive"], d["counts"]["reactive"]
        risk = d["occupants_at_risk"]
        lines.append(
            f"  {_mmss(d['t0_s'])}  {p['ok']:3d} / {p['trapped']:3d} ({risk['predictive']:4d})"
            f"                  {r['ok']:3d} / {r['cut_off']:3d} / {r['trapped']:3d} "
            f"({risk['reactive']:4d})"
        )
    lines += [
        "",
        "Trapped (no route reaches SAFE even with foresight; * = the only open way out passes "
        "through the room of fire origin)",
    ]
    for d in s["departures"]:
        origin_only = set(d["trapped_by_origin_only"])
        trapped = ", ".join(f"{t}*" if t in origin_only else t for t in d["trapped"]) or "none"
        lines.append(f"  {_mmss(d['t0_s'])}  {trapped}")
    return lines


def _contrast_lines(s: dict) -> list[str]:
    lines = []
    for d in s["departures"]:
        t0 = _mmss(d["t0_s"])
        for f in d["reactive_fails"]:
            if f["predictive"] == "ok":
                pred = (
                    f"predictive leaves by {f['predictive_exit']}, "
                    f"safe at {_mmss(f['predictive_eta_s'])}"
                )
            else:
                pred = "predictive: trapped too"
            lines.append(
                f"  {t0}  {f['space']} ({f['occupants']} people): reactive reaches "
                f"{f['opening']} at {_mmss(f['reach_s'])}, closed at "
                f"{_mmss(f['blocked_s'])}; {pred}"
            )
        if d["different_exit"]:
            diff = ", ".join(
                f"{x['space']} {x['reactive_exit']} -> {x['predictive_exit']}"
                for x in d["different_exit"]
            )
            lines.append(f"  {t0}  both safe, different exit: {diff}")
    return lines or ["  no reactive route is cut off at these departure times"]


def _parse_door(spec: str) -> tuple[str, bool]:
    oid, _, state = spec.rpartition("=")
    if not oid or state not in ("open", "closed"):
        raise argparse.ArgumentTypeError(f"--door expects ID=open or ID=closed, got {spec!r}")
    return oid, state == "open"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m engine.demo", description=__doc__.split("\n")[0])
    p.add_argument("--venue", default=str(VENUE_JSON), help="venue.json path")
    p.add_argument("--start", default=DEFAULT_START, help="indoor space id where the fire starts")
    p.add_argument("--growth", default="fast", choices=sorted(ALPHA_KW_S2))
    p.add_argument("--horizon", type=float, default=900.0, help="seconds to simulate")
    p.add_argument(
        "--departures", default="0,60,120,180,300", help="comma-separated departure times (s)"
    )
    p.add_argument("--frame-step", type=float, default=30.0, help="s between frames (0: none)")
    p.add_argument("--out", help="write the JSON to this file")
    p.add_argument("--summary", action="store_true", help="print a readable summary")
    p.add_argument(
        "--door",
        action="append",
        default=[],
        type=_parse_door,
        metavar="ID=open|closed",
        help="override one opening's event-night state (repeatable)",
    )
    p.add_argument(
        "--keep-origin-doors",
        action="store_true",
        help="leave the origin room's closed interior doors closed",
    )
    p.add_argument(
        "--allow-origin-entry",
        action="store_true",
        help="let routes pass through the room of fire origin until it is untenable",
    )
    args = p.parse_args(argv)
    try:
        departures = tuple(float(x) for x in args.departures.split(",") if x.strip())
    except ValueError:
        p.error(f"--departures expects numbers, got {args.departures!r}")
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
            avoid_origin=not args.allow_origin_entry,
        )
    except ValueError as err:
        p.error(str(err))
    if args.out:
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
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
