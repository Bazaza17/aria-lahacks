"""GET /engine/* — runs Aria's building engine (packages/engine) on demand.

The engine is a stdlib-only package beside the API in the monorepo. It is imported from
../../packages/engine (repo root/packages/engine), locally and in the Docker image, which
copies it to the same place. One run takes about a second, so results are cached per
start space and growth.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Response

_ENGINE_DIR = Path(__file__).resolve().parents[4] / "packages" / "engine"
if _ENGINE_DIR.is_dir() and str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

from engine import demo  # noqa: E402
from engine.aria_venue import NON_WALKING_KINDS  # noqa: E402
from engine.constants import ALPHA_KW_S2  # noqa: E402

router = APIRouter(prefix="/engine", tags=["engine"])

# The same run the viewer's static file was made with (public/fire/venue.json).
VIEWER_DEPARTURES = (0.0, 60.0, 120.0, 180.0, 240.0, 300.0, 420.0)
VIEWER_FRAME_STEP_S = 10.0
CACHE_RUNS = 24  # ~0.7 MB of viewer JSON each

# Where the outlines come from: only four 1F rooms are scanned; the rest is the floor plan.
PROVENANCE_NOTE = (
    "1F: four rooms scanned with phone LiDAR and stitched (about +/-0.3 m at the joins); the "
    "rest of the 1F and the upper floors come from the floor plan."
)


# --- venue.json lookups. ---
@lru_cache(maxsize=1)
def _venue() -> dict:
    return json.loads(Path(demo.VENUE_JSON).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _spaces() -> dict[str, dict]:
    return {s["id"]: s for s in _venue()["spaces"]}


@lru_cache(maxsize=1)
def _openings() -> dict[str, dict]:
    return {o["id"]: o for o in _venue()["openings"]}


def _space_name(sid: str | None, plan: bool = False) -> str:
    """The event name (Collins Conference Room) or, with plan or without one, the plan name's
    short form."""
    if not sid or sid == "SAFE":
        return "outside"
    s = _spaces().get(sid)
    if s is None:
        return sid
    if s.get("event_name") and not plan:
        return s["event_name"]
    short = (s.get("name") or sid).split(" (")[0].split(", ")[0]
    return f"Room {short}" if short[:1].isdigit() and " " not in short else short


def _opening_label(oid: str) -> str:
    o = _openings().get(oid) or {}
    if o.get("name"):  # the human exit name the scan labels use too
        return o["name"]
    aliases = o.get("aliases") or []
    if aliases:
        # An exterior stair reads better by what it is than by where it goes.
        alias = next((a for a in aliases if "exterior" in a), aliases[0])
        return alias[:1].upper() + alias[1:]
    return f"{_space_name(o.get('a'))} to {_space_name(o.get('b'))}"


# Notes from reading the floor plan photo ("could read 128"), not names.
_PLAN_NOTES = ("could read", "reads like", "maybe", "you are here", " or ")


def _start_label(s: dict) -> str:
    """A picker label from venue.json's plan name: keeps the useful qualifier ("210 (north
    part)") and drops plan-reading notes and trailing detail ("126 (could read 128)" -> "126")."""
    name = s.get("name") or s["id"]
    m = re.match(r"^(.*?)\s*\((.*?)\)", name)
    if m:
        head, inner = m.groups()
        keep = [c.strip() for c in re.split(r"[;,]", inner) if c.strip()]
        keep = [c for c in keep if not any(w in f" {c.lower()} " for w in _PLAN_NOTES)]
        label = f"{head} ({', '.join(keep)})" if keep else head
    else:
        label = name.split(", with ")[0]
    # A bare room number reads better as "Room 126".
    return f"Room {label}" if re.match(r"^\d{3}[A-Z]?(\s|$)", label) else label


@lru_cache(maxsize=1)
def starts() -> list[dict]:
    """Indoor spaces a fire can start in, from venue.json."""
    out = []
    for s in _venue()["spaces"]:
        if s.get("is_outdoor") or s.get("kind") in NON_WALKING_KINDS:
            continue
        out.append(
            {
                "id": s["id"],
                "name": s.get("event_name") or s.get("name") or s["id"],
                "label": _start_label(s),
                "storey": s.get("storey"),
                "kind": s.get("kind"),
                "occupant_load": s.get("occupant_load", 0),
            }
        )
    return out


def _viewer_with_provenance(viewer: dict) -> dict:
    """The engine's viewer block plus, per room, where its outline comes from (venue.json's
    geometry_source) and its storey. A copy: the engine result itself is left unchanged."""
    spaces = _spaces()
    rooms = {}
    for sid, room in viewer["rooms"].items():
        src = spaces.get(sid, {})
        source = src.get("geometry_source") or "plan"
        rooms[sid] = {
            **room,
            "storey": src.get("storey"),
            "event_name": src.get("event_name"),
            "geometry_source": source,
            "scanned": source == "scan",
        }
    return {**viewer, "rooms": rooms, "provenance": PROVENANCE_NOTE}


@lru_cache(maxsize=CACHE_RUNS)
def _run(start: str, growth: str) -> dict:
    result = demo.run_demo(
        start=start,
        growth=growth,
        departures=VIEWER_DEPARTURES,
        frame_step_s=VIEWER_FRAME_STEP_S,
    )
    viewer = _viewer_with_provenance(result["viewer"])
    return {
        "viewer": json.dumps(viewer, ensure_ascii=False).encode("utf-8"),
        "scenario": result,
        "sizeup": _sizeup(result),
    }


def _check(start: str, growth: str) -> None:
    if growth not in ALPHA_KW_S2:
        raise HTTPException(422, f"growth must be one of {sorted(ALPHA_KW_S2)}")
    if start not in {s["id"] for s in starts()}:
        raise HTTPException(404, f"unknown start space {start!r}; see /engine/starts")


async def run(start: str, growth: str = "fast") -> dict:
    """The full engine result for one scenario (cached), off the event loop."""
    _check(start, growth)
    return (await asyncio.to_thread(_run, start, growth))["scenario"]


@router.get("/starts")
async def list_starts() -> dict:
    return {"default": demo.DEFAULT_START, "growths": sorted(ALPHA_KW_S2), "starts": starts()}


@router.get("/viewer")
async def viewer(start: str = Query(demo.DEFAULT_START), growth: str = Query("fast")) -> Response:
    """The viewer block (FireTimeline + routes) apps/web draws on the scan."""
    _check(start, growth)
    body = (await asyncio.to_thread(_run, start, growth))["viewer"]
    return Response(content=body, media_type="application/json")


@router.get("/summary")
async def scenario_summary(
    start: str = Query(demo.DEFAULT_START), growth: str = Query("fast")
) -> dict:
    """Scenario, readable summary, exits lost and the responder size-up (apps/web's panel)."""
    _check(start, growth)
    cached = await asyncio.to_thread(_run, start, growth)
    result = cached["scenario"]
    return {
        "scenario": result["scenario"],
        "summary": result["summary"],
        "exits": result["fire"]["exits"],
        "origin": result["fire"]["origin"],
        "sizeup": cached["sizeup"],
    }


# --- The responder size-up. ---
SIZEUP_ASSUMPTIONS = [
    "Worst case: no sprinklers, no smoke control, no fire service action.",
    "Screening zone model, one smoke layer per room; after the first flashover its numbers "
    "are indicative only.",
    "Untenable: smoke layer below 2 m or hotter than 200 C; the room of origin once the fire "
    "radiates 2.5 kW/m2 at 3 m.",
    "Crowds: every room is modelled at its full assumed capacity (NFPA occupant load, 2nd-floor "
    "workshops indoors), not a headcount, so results are given in rooms, not people. Groups move "
    "at SFPE walking speeds and door and stair flows, starting the moment they leave.",
    "Elevators are not used for evacuation.",
    "Connections marked uncertain in the venue data are modelled open: check them on site.",
]


def _mark(row: dict | None) -> dict | None:
    if not row:
        return None
    sid = row.get("space")
    return {"t_s": row["t_s"], "space": sid, "name": _space_name(sid)}


def _room_at_risk(route: dict) -> bool:
    """A room is at risk when anyone in it can't get out on that route in time."""
    return bool(route.get("at_risk")) or (route.get("status") or "ok") != "ok"


def _all_out(dep: dict, mode: str) -> dict:
    """Rooms (and modelled people) at risk, and when the last group out is out, for one
    departure time. The web shows rooms: the people counts rest on assumed capacities."""
    at_risk = rooms_at_risk = 0
    last = None
    for sp in dep["spaces"].values():
        if not sp.get("occupants"):
            continue
        route = sp.get(mode) or {}
        at_risk += route.get("at_risk") or 0
        rooms_at_risk += _room_at_risk(route)
        flow = route.get("flow") or {}
        if flow.get("cleared") and flow.get("last_out_s") is not None:
            last = max(last or 0.0, float(flow["last_out_s"]))
    return {"at_risk": at_risk, "rooms_at_risk": rooms_at_risk, "last_out_s": last}


def _departures(result: dict) -> list[dict]:
    out = []
    for dep in result["routes"]["departures"]:
        occupants = sum(sp.get("occupants") or 0 for sp in dep["spaces"].values())
        rooms = sum(1 for sp in dep["spaces"].values() if sp.get("occupants"))
        out.append(
            {
                "t0_s": dep["t0_s"],
                "occupants": occupants,
                "rooms": rooms,
                "plan": _all_out(dep, "predictive"),
                "self": _all_out(dep, "reactive"),
            }
        )
    return out


def _ways_down(summary: dict) -> dict[str, list[dict]]:
    return {
        storey: [
            {
                "stair": w["stair"],
                "label": _opening_label(w["stair"]),
                "from": _space_name(w["from"]),
                "to": _space_name(w["to"]),
                "outdoors": w["lands_in"] == "outdoors",
            }
            for w in stairs
        ]
        for storey, stairs in sorted(summary["ways_down"].items())
    }


def _check_on_site(summary: dict) -> list[dict]:
    out = []
    for oid in summary["uncertain_open_connections"]:
        o = _openings().get(oid) or {}
        out.append(
            {
                "opening": oid,
                "between": [_space_name(o.get("a"), True), _space_name(o.get("b"), True)],
                "note": o.get("notes") or "",
            }
        )
    return out


def _exits(result: dict) -> dict:
    exits = result["fire"]["exits"]
    lost = sorted((e for e in exits if e["lost_s"] is not None), key=lambda e: e["lost_s"])
    return {
        "exits_total": len(exits),
        "exits_lost": [
            {
                "exit": e["exit"],
                "label": _opening_label(e["exit"]),
                "from": _space_name(e.get("from")),
                "lost_s": e["lost_s"],
            }
            for e in lost
        ],
        "exits_kept": [
            {"exit": e["exit"], "label": _opening_label(e["exit"])}
            for e in exits
            if e["lost_s"] is None
        ],
    }


def _best_on_grid(departures: list[dict], flashover_s: float | None) -> dict | None:
    """Where Aria's plan matters most, on the panel's own departure times (the engine's
    best_moment scans every 15 s, so its time can fall between them and the panel's numbers
    wouldn't match). Before the first flashover, the most rooms saved; earliest on ties."""
    best = None
    for d in departures:
        if flashover_s is not None and d["t0_s"] >= flashover_s:
            continue
        saved = d["self"]["rooms_at_risk"] - d["plan"]["rooms_at_risk"]
        if saved > 0 and (best is None or saved > best["rooms_saved"]):
            best = {
                "t0_s": d["t0_s"],
                "plan_rooms_at_risk": d["plan"]["rooms_at_risk"],
                "self_rooms_at_risk": d["self"]["rooms_at_risk"],
                "rooms_saved": saved,
                "rooms": d["rooms"],
            }
    return best


def _sizeup(result: dict) -> dict:
    s, sc = result["summary"], result["scenario"]
    start = sc["start_space"]
    departures = _departures(result)
    first_flashover = result["fire"]["validity"].get("first_flashover_s")
    return {
        "verified": bool(result["viewer"].get("verified")),
        "origin": {
            "space": start,
            "name": _space_name(start),
            "storey": _spaces().get(start, {}).get("storey"),
            "growth": sc["growth"],
            "untenable_s": (s.get("origin") or {}).get("limit_s"),
        },
        "first_smoke_beyond_origin": _mark(s.get("first_smoke_beyond_origin")),
        "first_untenable_beyond_origin": _mark(s.get("first_untenable_beyond_origin")),
        "first_flashover_s": first_flashover,
        **_exits(result),
        "departures": departures,
        "ways_down": _ways_down(s),
        "check_on_site": _check_on_site(s),
        "best_moment": _best_on_grid(departures, first_flashover),
        "assumptions": SIZEUP_ASSUMPTIONS,
        "provenance": PROVENANCE_NOTE,
    }
