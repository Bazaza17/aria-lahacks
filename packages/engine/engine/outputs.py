"""The demo JSON's drawing blocks: geometry, venue-level events and frames, and a `viewer` block
in the shape apps/web/lib/scan-fire.ts (FireTimeline) already loads, keyed by venue space and
opening ids instead of fire-model ids."""

from __future__ import annotations

import re

from engine.aria_venue import NON_WALKING_KINDS, AriaVenue
from engine.fire import Timeline
from engine.geometry import bbox

_FLASHED = ("flashover", "burnt_out")
_DATUM_RE = re.compile(r"elevation\s*=\s*Y_room2\s*([+-])\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
_KEEP_FIRE_EVENTS = ("ignition", "flashover", "door_burn_through", "burnout")


def geometry(av: AriaVenue) -> dict:
    """Everything needed to draw spaces and openings, copied from venue.json."""
    spaces = {}
    for sid, s in av.spaces.items():
        spaces[sid] = {
            "name": s.get("name"),
            "kind": s.get("kind"),
            "storey": s.get("storey"),
            "is_outdoor": bool(s.get("is_outdoor")),
            "floor_elevation": s.get("floor_elevation"),
            "height": s.get("height"),
            "occupant_load": s.get("occupant_load"),
            "polygon": s.get("polygon"),
        }
    openings = {
        oid: {
            k: o.get(k)
            for k in ("a", "b", "kind", "position", "is_exit", "clear_width", "effective_width")
        }
        for oid, o in av.openings.items()
    }
    return {"storeys": av.raw.get("storeys", []), "spaces": spaces, "openings": openings}


def scan_floor_y(av: AriaVenue) -> float | None:
    return datum_floor_y(av.raw)


def datum_floor_y(raw: dict) -> float | None:
    """Room 2's scan Y of elevation 0, read from the frame datum ("elevation = Y_room2 + 3.91")."""
    m = _DATUM_RE.search(str(raw.get("frame", {}).get("datum", "")))
    if not m:
        return None
    offset = float(m.group(2)) * (1 if m.group(1) == "+" else -1)
    return -offset


def _venue_ids(av: AriaVenue, fire_id: str) -> list[str]:
    if av.spaces_of.get(fire_id):
        return av.spaces_of[fire_id]
    if fire_id in av.opening_of_door:
        return [av.opening_of_door[fire_id]]
    shafts = [oid for oid, rid in av.shaft_of_opening.items() if rid == fire_id]
    return shafts or [fire_id]


def _drawn(av: AriaVenue, sid: str) -> bool:
    return av.spaces[sid].get("kind") not in NON_WALKING_KINDS


def events(av: AriaVenue, tl: Timeline, vt: dict, exits: list[dict]) -> list[dict]:
    """Venue-level events: the fire model's ignition, flashover, burn-through and burnout
    events, plus smoke and untenability per space and exits lost, at the per-space times
    (members of merged rooms on their own floors, the origin limit)."""
    out = [
        {**e, "venue_ids": _venue_ids(av, e["id"])}
        for e in tl.events
        if e["type"] in _KEEP_FIRE_EVENTS
    ]
    origin = vt.get("origin") or {}
    for sid, row in vt["spaces"].items():
        if not _drawn(av, sid):
            continue
        name = av.label(sid)
        if row["smoke_enters_s"] is not None:
            out.append(_event(row["smoke_enters_s"], "smoke_enters", sid, f"smoke reaches {name}"))
        if sid == origin.get("space") and origin.get("limit_s") is not None:
            detail = f"{name} untenable: the fire reaches {origin['limit_kw']} kW (radiant limit)"
            out.append(_event(origin["limit_s"], "untenable", sid, detail))
        elif row["smoke_untenable_s"] is not None:
            why = "smoke layer below 2 m" if row["untenable_by"] == "smoke_layer" else "hot layer"
            out.append(
                _event(row["smoke_untenable_s"], "untenable", sid, f"{name} untenable ({why})")
            )
    for e in exits:
        if e["lost_s"] is not None:
            out.append(_event(e["lost_s"], "exit_blocked", e["exit"], f"exit {e['exit']} lost"))
        if e.get("reachable_until_s") is not None:
            detail = f"no occupied space can reach exit {e['exit']} any more"
            out.append(_event(e["reachable_until_s"], "exit_unreachable", e["exit"], detail))
    return sorted(out, key=lambda e: (e["t_s"], e["type"]))


def _event(t: float, kind: str, item: str, detail: str) -> dict:
    return {"t_s": int(round(t)), "type": kind, "id": item, "detail": detail, "venue_ids": [item]}


def _space_state(room: dict, info: dict, t: float, burns_here: bool) -> str:
    if room["state"] in _FLASHED:
        return room["state"]
    if room["state"] == "burning" and burns_here:
        return "burning"
    if info["smoke_untenable_s"] is not None and info["smoke_untenable_s"] <= t:
        return "untenable"
    if info["smoke_enters_s"] is not None and info["smoke_enters_s"] <= t:
        return "smoke"
    return "clear"


def frames(av: AriaVenue, tl: Timeline, vt: dict, start: str, step_s: float) -> list[dict]:
    """Per-space snapshots every step_s (and the last step), from the 1 s fire frames.

    layer_height_m is above the space's own floor, capped at its own ceiling (a merged room's
    layer can sit up in the skylight well); smoke_depth_m is the smoke below that ceiling.
    Inside the room of origin only the start space burns and carries the HRR; its other members
    (the rest of a merged room) show their own smoke state. A room the fire spread into burns
    as a whole."""
    if step_s <= 0 or not tl.frames:
        return []
    every = max(1, round(step_s))
    keep = [f for f in tl.frames if f["t_s"] % every == 0]
    if keep[-1] is not tl.frames[-1]:
        keep.append(tl.frames[-1])
    first_fo = _min_flashover(tl)
    out = []
    for f in keep:
        t = f["t_s"]
        rooms = {}
        for sid, rid in av.room_of.items():
            room, info = f["rooms"][rid], vt["spaces"][sid]
            burns_here = rid != tl.start_room or sid == start
            state = _space_state(room, info, t, burns_here)
            burning_here = state in ("burning", *_FLASHED)
            ceiling = av.height(sid)
            layer = min(max(0.0, room["layer_height_m"] - info["floor_offset_m"]), ceiling)
            rooms[sid] = {
                "layer_height_m": round(layer, 2),
                "smoke_depth_m": round(ceiling - layer, 2),
                "layer_temp_c": room["layer_temp_c"],
                "hrr_kw": room["hrr_kw"] if burning_here else 0,
                "state": state,
            }
        blocked = [
            k
            for group in (vt["spaces"], vt["openings"])
            for k, v in group.items()
            if v["blocked_s"] is not None and v["blocked_s"] <= t
        ]
        out.append(
            {
                "t_s": t,
                "rooms": rooms,
                "blocked": sorted(blocked),
                "beyond_screening": first_fo is not None and t >= first_fo,
            }
        )
    return out


def _min_flashover(tl: Timeline) -> int | None:
    times = [r["flashover_s"] for r in tl.rooms.values() if r["flashover_s"] is not None]
    return min(times) if times else None


def validity(tl: Timeline) -> dict:
    first = _min_flashover(tl)
    room = next((rid for rid, r in tl.rooms.items() if r["flashover_s"] == first), None)
    return {
        "first_flashover_s": first,
        "first_flashover_room": room,
        "note": "A screening zone model: after the first flashover its layer temperatures, HRR "
        "and spread are indicative only (frames carry beyond_screening).",
    }


def viewer(
    av: AriaVenue,
    tl: Timeline,
    start: str,
    growth: str,
    frames_out: list[dict],
    events_out: list[dict],
    exits: list[dict],
) -> dict:
    """A FireTimeline (apps/web/lib/scan-fire.ts) keyed by venue ids: buildFireLayer draws it
    as is. Footprints are polygon bounding boxes in the venue frame (room 2's scan x, z)."""
    rooms = {}
    for sid in av.room_of:
        poly = [(float(p[0]), float(p[1])) for p in av.spaces[sid].get("polygon") or []]
        box = bbox([poly])
        rooms[sid] = {
            "name": av.label(sid),
            "floor": av.floor(sid),
            "footprint": {"x": [box[0], box[1]], "z": [box[2], box[3]]} if box else None,
            "polygon": [[round(x, 2), round(z, 2)] for x, z in poly] or None,
            "ceiling_height_m": av.height(sid),
            "floor_elevation_m": av.spaces[sid].get("floor_elevation"),
        }
    doors = {
        oid: {
            "name": oid,
            "position": {"x": o["position"][0], "z": o["position"][1]}
            if o.get("position")
            else None,
            "connects": [o.get("a"), o.get("b")],
        }
        for oid, o in av.openings.items()
    }
    return {
        "venue": av.raw.get("building", {}).get("name", ""),
        "verified": False,
        "start_room": start,
        "growth": growth,
        "horizon_s": tl.horizon_s,
        "rooms": rooms,
        "doors": doors,
        "exits": [
            {"id": e["exit"], "label": e["exit"], "door": e["exit"], "blocked_s": e["lost_s"]}
            for e in exits
        ],
        "events": [{k: e[k] for k in ("t_s", "type", "id", "detail")} for e in events_out],
        "frames": frames_out,
        "scan": {
            "frame": "venue frame = room 2's scan frame (x, z); see frame.scan_transforms",
            "floor_y": scan_floor_y(av),
        },
    }


def _route_line(sid: str, occupants: int, kind: str, r: dict) -> dict:
    return {
        "space": sid,
        "occupants": occupants,
        "kind": kind,
        "status": r.get("status"),
        "at_risk": r.get("at_risk", 0),
        "exit": r.get("exit"),
        "points": [[round(p[0], 2), round(p[1], 2), round(p[2], 2)] for p in r.get("points") or []],
    }


def viewer_routes(deps: list[dict]) -> dict:
    """Per departure time: Aria's plan for every occupied space, plus the self-chosen
    (reactive) route wherever it puts people at risk. Points are [x, z, elevation]."""
    out = []
    for dep in deps:
        lines = []
        for sid, sp in dep["spaces"].items():
            occupants = sp.get("occupants", 0)
            if not occupants:
                continue
            plan, reactive = sp.get("predictive") or {}, sp.get("reactive") or {}
            if plan.get("points"):
                lines.append(_route_line(sid, occupants, "plan", plan))
            fails = reactive.get("at_risk") or reactive.get("status") != "ok"
            if reactive.get("points") and fails:
                lines.append(_route_line(sid, occupants, "reactive", reactive))
        out.append(
            {
                "t0_s": dep["t0_s"],
                "at_risk": {
                    "plan": dep["occupants_at_risk"].get("predictive", 0),
                    "reactive": dep["occupants_at_risk"].get("reactive", 0),
                },
                "routes": lines,
            }
        )
    return {"departures": out}
