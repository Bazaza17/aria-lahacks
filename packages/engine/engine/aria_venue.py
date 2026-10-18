"""Aria's venue.json (schema v0.1) as a fire-model Venue and a routing graph.

`venue.json` (packages/engine/venue.json, documented in VENUE.md) holds spaces and openings in
the venue frame (room 2's scan frame: metres, Y up, plan [x, z], elevation 0 = lobby 110's
floor). The screening zone model in engine.fire wants rooms (one smoke layer each) and doors.
This module bridges the two and keeps the id maps both ways:

- Indoor spaces become rooms. Every skylight well (kind `open_to_below`) and the spaces under it
  become ONE tall room, so the atrium fills as one volume. The 2F openings that face a well
  become doors of that room at the 2F level, so atrium smoke spills onto the 2F. Two spaces
  joined by a `step` band (no wall, no door: 140 and 150) also become one room.
- Openings become doors, open or closed per EVENT_NIGHT_RULES (one table, overridable).
- An interior stair between two ordinary rooms becomes a stair shaft room (engine.venue's
  `kind="stair"`) with a door at each end. Elevators are not egress; their shafts are not
  modelled.
- Outdoor spaces and SAFE are the fire model's "outside": smoke vents there, fire never spreads.

It also builds the routing graph (engine.route_graph): every space plus SAFE as nodes, walkable
openings as arcs (both directions), door-to-door legs at SFPE walking speeds.

    from engine.aria_venue import load_aria_venue
    av = load_aria_venue(origin_space="140")
    av.fire              # engine.venue.Venue for engine.fire.simulate
    av.graph             # RouteGraph for engine.routes
    av.room_of["110"]    # "atrium:110"
    av.room_of["140"]    # "room:140+150"
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from engine.constants import DEFAULT_DOOR_HEIGHT_M, FUEL_CLASSES
from engine.geometry import Point, bbox, perimeter, shoelace
from engine.route_graph import (  # noqa: F401  (re-exported: the routing graph lives there)
    K_LEVEL_M_S,
    K_STAIR_M_S,
    SAFE,
    WALK_LEVEL_M_S,
    WALK_RAMP_M_S,
    WALK_STAIR_M_S,
    Arc,
    Node,
    RouteGraph,
    build_route_graph,
    position,
    stair_run,
)
from engine.venue import OUTSIDE, Door, Exit, Room, Venue

VENUE_JSON = Path(__file__).resolve().parent.parent / "venue.json"

# --- Fire-model mapping. ---
DEFAULT_CEILING_M = 3.0  # VENUE.md's placeholder height, used when a space has none
RATED_STAIR_DOOR_MIN = 60.0  # 1-hour stair/shaft enclosure -> 60-min door (IBC Table 716.1(2))
ELEVATOR_DOOR_MIN = 60.0  # ASSUMPTION: hoistway doors rated like a 1-hour shaft's doors
MIN_DOOR_HEIGHT_M = 0.3
SERVICE_KINDS = ("restroom", "closet", "mech", "elevator")
NON_WALKING_KINDS = ("open_to_below", "elevator")  # spaces nobody evacuates from (or ignites)
OPENABLE_FOR_A_SEALED_ORIGIN = ("service_door", "exterior_door")
DOOR_KINDS = ("door", "double_door")  # have a leaf: "no wall" style notes don't make them taller


@dataclass(frozen=True)
class DoorRule:
    open: bool  # door state for smoke and fire spread
    fire_rating_min: float
    egress: bool  # usable by people
    why: str


# EVENT-NIGHT ASSUMPTIONS: the one place door states are decided. Every opening falls in one
# category (see _classify). Override single openings with load_aria_venue(door_overrides=...)
# or `python -m engine.demo --door ID=open|closed`.
EVENT_NIGHT_RULES: dict[str, DoorRule] = {
    "exterior_door": DoorRule(
        False, 0.0, True, "Exterior door: closed for smoke (no venting), usable for egress."
    ),
    "exterior_open": DoorRule(
        True, 0.0, True, "Opening to outdoors with no door leaf: open, vents smoke."
    ),
    "event_door": DoorRule(
        True, 0.0, True, "Door between two event spaces: propped open for the event."
    ),
    "service_door": DoorRule(
        False,
        0.0,
        True,
        "Door to a closet, restroom, elevator or back-of-house room: closed, unrated.",
    ),
    "open_connection": DoorRule(
        True, 0.0, True, "Cased opening, gap, step or ramp: no door leaf, always open."
    ),
    "well_edge": DoorRule(
        True,
        0.0,
        False,
        "Skylight-well edge (railing or glazing unknown): open for smoke, not walkable.",
    ),
    "open_stair": DoorRule(
        True, 0.0, True, "Unprotected stair (protected false): open vertical connection."
    ),
    "protected_stair": DoorRule(
        False,
        RATED_STAIR_DOOR_MIN,
        True,
        "Protected stair: closed rated door (1-hour enclosure, 60-min door).",
    ),
    "elevator": DoorRule(
        False,
        ELEVATOR_DOOR_MIN,
        False,
        "Elevator landing door: closed hoistway door; elevators are not used for egress.",
    ),
}

# Openings that are not doors in the fire model, and why.
NOT_A_FIRE_DOOR: dict[str, str] = {
    "internal": "joins two parts of one merged fire room (inside the atrium volume)",
    "outdoor": "no indoor side: outdoor spaces and SAFE are the fire model's outside",
    "elevator_shaft": "elevator hoistway between floors: smoke in the shaft is not modelled",
    "unknown_space": "names a space that is not in venue.json",
}

_HEADER_RE = re.compile(
    r"(?:lintel|header)\s*(?:at\s*)?~?\s*(\d+(?:\.\d+)?)\s*m\b"
    r"|~?(\d+(?:\.\d+)?)\s*m\s+(?:lintel|header)",
    re.IGNORECASE,
)
_FULL_HEIGHT_RE = re.compile(r"no wall|at (?:any|every) height", re.IGNORECASE)


# --- The venue.json data, with defaults for missing fields. ---
@dataclass
class _Data:
    spaces: dict[str, dict]
    openings: dict[str, dict]
    floor_of_storey: dict[str, int]
    elevation_of_floor: dict[int, float]
    neighbours: dict[str, set[str]] = field(default_factory=dict)

    def indoor(self, sid: str | None) -> bool:
        return sid in self.spaces and not self.spaces[sid].get("is_outdoor", False)

    def kind(self, sid: str) -> str:
        return self.spaces[sid].get("kind") or "room"

    def floor(self, sid: str) -> int:
        return self.floor_of_storey.get(self.spaces[sid].get("storey"), 1)

    def floor_elevation(self, sid: str) -> float:
        fe = self.spaces[sid].get("floor_elevation")
        return float(fe) if fe is not None else self.elevation_of_floor.get(self.floor(sid), 0.0)

    def height(self, sid: str) -> float:
        h = self.spaces[sid].get("height")
        return float(h) if h else DEFAULT_CEILING_M

    def polygon(self, sid: str) -> list[Point]:
        return [(float(p[0]), float(p[1])) for p in self.spaces[sid].get("polygon") or []]

    def area(self, sid: str) -> float:
        a = self.spaces[sid].get("area")
        return float(a) if a else max(abs(shoelace(self.polygon(sid))), 1.0)

    def label(self, sid: str) -> str:
        if sid == SAFE:
            return "public way (SAFE)"
        s = self.spaces[sid]
        short = (s.get("name") or sid).split(" (")[0]
        return short if sid in short else f"{short} ({sid})"


def _load_data(raw: dict) -> _Data:
    storeys = sorted(raw.get("storeys", []), key=lambda s: float(s.get("elevation", 0.0)))
    floor_of_storey: dict[str, int] = {}
    elevation_of_floor: dict[int, float] = {}
    for i, st in enumerate(storeys, start=1):
        m = re.match(r"\s*(\d+)", str(st.get("id", "")))
        n = int(m.group(1)) if m else i
        floor_of_storey[st["id"]] = n
        elevation_of_floor[n] = float(st.get("elevation", 0.0))
    elevation_of_floor.setdefault(1, 0.0)
    data = _Data(
        spaces={s["id"]: s for s in raw.get("spaces", [])},
        openings={o["id"]: o for o in raw.get("openings", [])},
        floor_of_storey=floor_of_storey,
        elevation_of_floor=elevation_of_floor,
    )
    for o in data.openings.values():
        a, b = o.get("a"), o.get("b")
        data.neighbours.setdefault(a, set()).add(b)
        data.neighbours.setdefault(b, set()).add(a)
    return data


def _fuel_class(d: _Data, sid: str) -> str:
    kind = d.kind(sid)
    if kind in ("lobby", "corridor", "open_to_below", "elevator"):
        return "circulation"
    if kind in ("restroom", "stair"):
        return kind
    if kind in ("closet", "mech"):
        return "storage"
    s = d.spaces[sid]
    source = (s.get("occupant_load_source") or "").lower()
    if s.get("event_name") or "assembly" in source:
        return "assembly"
    return "office"


def _is_event_space(d: _Data, sid: str) -> bool:
    if d.kind(sid) in SERVICE_KINDS:
        return False
    s = d.spaces[sid]
    return bool(s.get("event_name")) or "assembly" in (s.get("occupant_load_source") or "").lower()


# --- Merged fire rooms: skylight wells with the spaces under them, and step bands. ---
def _merge_groups(d: _Data) -> dict[str, list[str]]:
    """Union-find over two kinds of link, both read from the data:
    - a skylight well (open_to_below) and the lower-floor space its floor void opens onto;
    - two indoor spaces joined by a `step` opening: a step band across an open floor, with no
      wall or door, so the two parts share one ceiling and one smoke layer (140/150).
    A group with a well is `atrium:<anchor>`; one without is `room:<a>+<b>`."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for o in d.openings.values():
        a, b = o.get("a"), o.get("b")
        if not (d.indoor(a) and d.indoor(b)):
            continue
        if o.get("kind") == "step" and d.floor(a) == d.floor(b):
            parent[find(a)] = find(b)
        for well, below in ((a, b), (b, a)):
            if d.kind(well) == "open_to_below" and d.floor(below) < d.floor(well):
                parent[find(well)] = find(below)
    groups: dict[str, list[str]] = {}
    for x in list(parent):
        groups.setdefault(find(x), []).append(x)
    merged = {}
    for members in groups.values():
        base = [m for m in members if d.kind(m) != "open_to_below"] or members
        wells = sorted(m for m in members if m not in base)
        if wells:
            anchor = min(base, key=lambda m: (d.floor(m), -d.area(m), m))
            rid = f"atrium:{anchor}"
        else:
            rid = "room:" + "+".join(sorted(base))
        merged[rid] = sorted(base, key=lambda m: -d.area(m)) + wells
    return merged


def _merged_room(d: _Data, rid: str, members: list[str]) -> tuple[Room, dict]:
    base = [m for m in members if d.kind(m) != "open_to_below"] or members
    wells = [m for m in members if m not in base]
    floor = min(d.floor(m) for m in base)
    area = sum(d.area(m) for m in base)
    volume = sum(d.area(m) * d.height(m) for m in base)
    for w in wells:
        under = [m for m in d.neighbours.get(w, ()) if m in base]
        bottom = max((d.floor_elevation(m) + d.height(m) for m in under), default=0.0)
        top = d.floor_elevation(w) + d.height(w)
        volume += d.area(w) * max(0.0, top - max(bottom, d.elevation_of_floor.get(floor, 0.0)))
    internal = sum(
        float(o.get("clear_width") or 0.0)
        for o in d.openings.values()
        if o.get("a") in base and o.get("b") in base
    )
    perim = sum(perimeter(d.polygon(m)) for m in base) - 2.0 * internal
    # Equivalent box: the true top (the wells' skylights) and the true volume. Its ceiling then
    # meets the 2F well edges where the real wells do, so smoke crosses them at the right
    # height in both directions; its floor area is volume / height.
    top = max(d.floor_elevation(m) + d.height(m) for m in members)
    height = max(top - d.elevation_of_floor.get(floor, 0.0), max(d.height(m) for m in base))
    if wells:
        name = f"Atrium ({' + '.join(base)} + {len(wells)} skylight wells)"
    else:
        event = d.spaces[base[0]].get("event_name")
        name = f"{event or 'Merged room'} ({' + '.join(base)})"
    room = Room(
        id=rid,
        name=name,
        floor=floor,
        area_m2=volume / height,
        ceiling_height_m=height,
        fuel_class=_fuel_class(d, base[0]),
        perimeter_m=max(perim, 4.0 * math.sqrt(area)),
        footprint=bbox([d.polygon(m) for m in members]),
    )
    info = {
        "spaces": members,
        "floor_spaces": base,
        "wells": wells,
        "floor_area_m2": round(area, 1),
        "volume_m3": round(volume, 1),
        "box_area_m2": round(room.area_m2, 1),
        "box_height_m": round(height, 2),
        "top_elevation_m": round(top, 2),
        "fuel_class": room.fuel_class,
        "why": "skylight wells over the floor spaces" if wells else "step band, no wall",
    }
    return room, info


# --- Door states. ---
def _classify(d: _Data, o: dict, room_of: dict[str, str]) -> str:
    """The opening's category: an EVENT_NIGHT_RULES key or a NOT_A_FIRE_DOOR key."""
    a, b, kind = o.get("a"), o.get("b"), o.get("kind") or "door"
    if any(s != SAFE and s not in d.spaces for s in (a, b)):
        return "unknown_space"
    indoor = [s for s in (a, b) if d.indoor(s)]
    if not indoor:
        return "outdoor"
    if len(indoor) == 2 and room_of[a] == room_of[b]:
        return "internal"
    if kind == "elevator":
        both_cars = len(indoor) == 2 and all(d.kind(s) == "elevator" for s in indoor)
        return "elevator_shaft" if both_cars else "elevator"
    if len(indoor) == 1:
        if kind == "stair" and not o.get("protected"):
            return "open_stair"
        return "exterior_door" if kind in ("door", "double_door", "stair") else "exterior_open"
    if kind == "stair":
        return "protected_stair" if o.get("protected") else "open_stair"
    smoke_only = float(o.get("effective_width") or 0.0) <= 0.0 and kind == "opening"
    if smoke_only or any(d.kind(s) == "open_to_below" for s in indoor):
        return "well_edge"
    if kind not in ("door", "double_door"):
        return "open_connection"
    if any(d.kind(s) in SERVICE_KINDS for s in indoor):
        return "service_door"
    return "event_door" if all(_is_event_space(d, s) for s in indoor) else "service_door"


def _door_states(
    d: _Data,
    room_of: dict[str, str],
    origin_room: str | None,
    open_origin_doors: bool,
    overrides: dict[str, bool],
) -> dict[str, dict]:
    states = {}
    for oid, o in d.openings.items():
        category = _classify(d, o, room_of)
        rule = EVENT_NIGHT_RULES.get(category)
        state = {
            "category": category,
            "open": rule.open if rule else None,
            "fire_rating_min": rule.fire_rating_min if rule else 0.0,
            "egress": rule.egress if rule else category in ("internal", "outdoor"),
            "why": rule.why if rule else NOT_A_FIRE_DOOR[category],
            "changed_by": None,
        }
        if oid in overrides and rule is not None:
            state.update(open=overrides[oid], changed_by="override")
        states[oid] = state
    if open_origin_doors and origin_room is not None:
        _vent_a_sealed_origin(d, room_of, origin_room, states, overrides)
    return states


def _vent_a_sealed_origin(
    d: _Data,
    room_of: dict[str, str],
    origin_room: str,
    states: dict[str, dict],
    overrides: dict[str, bool],
) -> None:
    """A room with no open opening has no air in the zone model, so its fire starves at 0 kW.
    Only then are its closed doors opened (a door left open, a window broken). A room with an
    open connection keeps its doors as the table sets them."""
    own = [
        oid
        for oid, o in d.openings.items()
        if origin_room in (room_of.get(o.get("a")), room_of.get(o.get("b")))
        and states[oid]["category"] in EVENT_NIGHT_RULES
    ]
    if any(states[oid]["open"] for oid in own):
        return
    for oid in own:
        if states[oid]["category"] in OPENABLE_FOR_A_SEALED_ORIGIN and oid not in overrides:
            states[oid].update(
                open=True,
                changed_by="origin room had no open opening (the fire would starve): opened",
            )


# --- Fire doors and stair shafts. ---
def _door_floor(d: _Data, o: dict, room_of: dict[str, str], merged: dict) -> int:
    indoor = [s for s in (o["a"], o["b"]) if d.indoor(s)]
    plain = [s for s in indoor if room_of[s] not in merged]
    if len(indoor) == 2 and len(plain) == 1:
        return d.floor(plain[0])  # atrium <-> side room: at the side room's level
    return max(d.floor(s) for s in indoor)


def _door_top(d: _Data, o: dict, category: str, door_floor: int) -> float:
    """Elevation of the opening's top (venue frame). An explicit `head_height` (m above the
    higher floor) wins; then a lintel/header height in the notes; then full height (the lower
    ceiling) for wells, open stairs, steps, ramps and leafless openings whose notes say "no wall"
    or "at any height"; else a 2.1 m door. Heights are above the higher of the two floors."""
    indoor = [s for s in (o["a"], o["b"]) if d.indoor(s) and d.kind(s) != "open_to_below"]
    level = [s for s in indoor if d.floor(s) == door_floor]  # a stair's door: its own landing
    indoor = level or indoor
    floor_top = max((d.floor_elevation(s) for s in indoor), default=0.0)
    notes = o.get("notes") or ""
    if o.get("head_height"):
        return floor_top + float(o["head_height"])
    m = _HEADER_RE.search(notes)
    if m:
        return floor_top + float(m.group(1) or m.group(2))
    full = (
        category in ("well_edge", "open_stair")
        or o.get("kind") in ("step", "ramp")
        or (o.get("kind") not in DOOR_KINDS and _FULL_HEIGHT_RE.search(notes))
    )
    if full and indoor:
        return min(d.floor_elevation(s) + d.height(s) for s in indoor)
    return floor_top + DEFAULT_DOOR_HEIGHT_M


def _clip_height(height: float, bottom: float, rooms: list[Room], elev: dict[int, float]) -> float:
    """Keep a door's top under the ceilings it joins (the merged atrium is a lower box)."""
    tops = [elev.get(r.floor, 0.0) + r.ceiling_height_m - bottom for r in rooms]
    limit = min(tops) if tops else height
    return min(height, limit) if limit >= MIN_DOOR_HEIGHT_M else height


def _shaft(
    d: _Data, o: dict, room_of: dict[str, str], state: dict, rooms: dict[str, Room]
) -> tuple[Room, list[Door]]:
    oid = o["id"]
    lo, hi = sorted((o["a"], o["b"]), key=lambda s: (d.floor(s), d.floor_elevation(s)))
    f_lo, f_hi = d.floor(lo), d.floor(hi)
    elev = d.elevation_of_floor
    width = float(o.get("clear_width") or 0.9)
    area = max(width * max(stair_run(o), 1.0), 1.0)
    pos = position(o)
    half = math.sqrt(area) / 2.0
    shaft = Room(
        id=f"shaft:{oid}",
        name=f"Stair {oid}",
        floor=f_lo,
        area_m2=area,
        ceiling_height_m=elev.get(f_hi, 0.0) - elev.get(f_lo, 0.0) + d.height(hi),
        fuel_class="stair",
        kind="stair",
        floors_served=(f_lo, f_hi),
        footprint=(pos[0] - half, pos[0] + half, pos[1] - half, pos[1] + half) if pos else None,
    )
    doors = []
    for side, floor, ends in (
        (lo, f_lo, (room_of[lo], shaft.id)),
        (hi, f_hi, (shaft.id, room_of[hi])),
    ):
        height = d.height(side) if state["open"] else DEFAULT_DOOR_HEIGHT_M
        bottom = elev.get(floor, 0.0)
        doors.append(
            Door(
                id=f"{oid}@{d.spaces[side].get('storey', floor)}",
                a=ends[0],
                b=ends[1],
                floor=floor,
                width_m=width,
                open=bool(state["open"]),
                fire_rating_min=state["fire_rating_min"],
                height_m=_clip_height(height, bottom, [rooms[room_of[side]], shaft], elev),
                name=f"Stair {oid} at {d.label(side)}",
                position=pos,
            )
        )
    return shaft, doors


def _direct_door(
    d: _Data, o: dict, room_of: dict[str, str], state: dict, rooms: dict[str, Room], merged: dict
) -> Door:
    ends = [room_of[s] if d.indoor(s) else OUTSIDE for s in (o["a"], o["b"])]
    if ends[0] == OUTSIDE:
        ends.reverse()
    floor = _door_floor(d, o, room_of, merged)
    bottom = d.elevation_of_floor.get(floor, 0.0)
    # engine.fire puts a door's bottom at its storey's elevation, so a raised floor (150 at
    # +0.70) goes into the height: the top lands where the real header is.
    height = max(_door_top(d, o, state["category"], floor) - bottom, MIN_DOOR_HEIGHT_M)
    joined = [rooms[e] for e in ends if e != OUTSIDE]
    return Door(
        id=o["id"],
        a=ends[0],
        b=ends[1],
        floor=floor,
        width_m=float(o.get("clear_width") or 0.9),
        open=bool(state["open"]),
        fire_rating_min=state["fire_rating_min"],
        height_m=_clip_height(height, bottom, joined, d.elevation_of_floor),
        name=f"{o.get('kind', 'door')} {d.label(o['a'])} / {d.label(o['b'])}",
        position=position(o),
    )


# --- The adapted venue. ---
@dataclass
class AriaVenue:
    raw: dict
    fire: Venue  # engine.venue.Venue for engine.fire.simulate
    graph: RouteGraph
    room_of: dict[str, str]  # indoor space id -> fire room id
    spaces_of: dict[str, list[str]]  # fire room id -> venue space ids (empty for shafts)
    doors_of_opening: dict[str, list[str]]  # opening id -> fire door ids
    opening_of_door: dict[str, str]  # fire door id -> opening id
    shaft_of_opening: dict[str, str]  # opening id -> stair shaft room id
    merged: dict[str, dict]  # merged room id -> what went in and its geometry
    door_states: dict[str, dict]  # opening id -> category, open, rating, why, changed_by
    fire_excluded: dict[str, str]  # opening id -> why it is not a fire-model door
    origin_space: str | None
    _data: _Data

    @property
    def spaces(self) -> dict[str, dict]:
        return self._data.spaces

    @property
    def openings(self) -> dict[str, dict]:
        return self._data.openings

    def label(self, sid: str) -> str:
        return self._data.label(sid)

    def fire_room(self, space_id: str) -> str:
        """Fire room for an indoor space id (or a fire room id itself)."""
        if space_id in self.fire.rooms:
            return space_id
        if space_id not in self.room_of:
            indoor = ", ".join(sorted(self.room_of))
            raise ValueError(f"{space_id!r} is not an indoor space. Indoor ids: {indoor}")
        return self.room_of[space_id]

    def floor(self, space_id: str) -> int:
        """Storey number of a space (1F -> 1)."""
        return self._data.floor(space_id)

    def height(self, space_id: str) -> float:
        """Floor-to-ceiling height of a space (3.0 m when venue.json has none)."""
        return self._data.height(space_id)

    def floor_offset(self, space_id: str) -> float:
        """Space floor minus its fire room's floor (nonzero for the Galleria's raised far end)."""
        room = self.fire.rooms[self.room_of[space_id]]
        return self._data.floor_elevation(space_id) - self.fire.elevation(room.floor)

    def route_sources(self) -> list[str]:
        """Indoor spaces people evacuate from (not wells, not elevator cars)."""
        return [
            sid
            for sid in self.spaces
            if self._data.indoor(sid) and self._data.kind(sid) not in NON_WALKING_KINDS
        ]


def load_aria_venue(
    path: str | Path = VENUE_JSON,
    *,
    door_overrides: dict[str, bool] | None = None,
    origin_space: str | None = None,
    open_origin_doors: bool = True,
) -> AriaVenue:
    """Read venue.json and build the fire Venue, the routing graph and the id maps.

    door_overrides: opening id -> open (True) or closed (False), applied last.
    origin_space: where the fire starts. With open_origin_doors, that room's closed interior
    doors are opened (worst case for spread, and a fire behind a shut door would starve).
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    d = _load_data(raw)
    overrides = dict(door_overrides or {})
    unknown = sorted(set(overrides) - set(d.openings))
    if unknown:
        raise ValueError(f"door overrides name unknown openings: {unknown}")

    merged_groups = _merge_groups(d)
    room_of = {sid: sid for sid in d.spaces if d.indoor(sid)}
    for rid, members in merged_groups.items():
        for m in members:
            room_of[m] = rid
    rooms: dict[str, Room] = {}
    merged: dict[str, dict] = {}
    for rid, members in merged_groups.items():
        rooms[rid], merged[rid] = _merged_room(d, rid, members)
    for sid in room_of:
        if room_of[sid] == sid:
            poly = d.polygon(sid)
            rooms[sid] = Room(
                id=sid,
                name=d.label(sid),
                floor=d.floor(sid),
                area_m2=d.area(sid),
                ceiling_height_m=d.height(sid),
                fuel_class=_fuel_class(d, sid),
                perimeter_m=perimeter(poly) or None,
                footprint=bbox([poly]),
            )
    for room in rooms.values():
        if room.fuel_class not in FUEL_CLASSES:
            raise ValueError(f"room {room.id}: unknown fuel_class {room.fuel_class!r}")

    origin_room = None
    if origin_space is not None:
        if origin_space not in room_of or d.kind(origin_space) in NON_WALKING_KINDS:
            starts = ", ".join(sorted(s for s in room_of if d.kind(s) not in NON_WALKING_KINDS))
            raise ValueError(
                f"a fire can't start in {origin_space!r} (not an indoor space, or a skylight well "
                f"or elevator car). Start ids: {starts}"
            )
        origin_room = room_of[origin_space]
    states = _door_states(d, room_of, origin_room, open_origin_doors, overrides)
    no_door = sorted(o for o in overrides if states[o]["category"] not in EVENT_NIGHT_RULES)
    if no_door:
        why = "; ".join(f"{o}: {NOT_A_FIRE_DOOR[states[o]['category']]}" for o in no_door)
        raise ValueError(f"door overrides name openings with no fire-model door ({why})")

    doors: dict[str, Door] = {}
    doors_of_opening: dict[str, list[str]] = {}
    shaft_of_opening: dict[str, str] = {}
    fire_excluded: dict[str, str] = {}
    for oid, o in d.openings.items():
        state = states[oid]
        if state["category"] in NOT_A_FIRE_DOOR:
            fire_excluded[oid] = NOT_A_FIRE_DOOR[state["category"]]
            doors_of_opening[oid] = []
            continue
        a, b = o["a"], o["b"]
        stair_between_rooms = (
            state["category"] in ("open_stair", "protected_stair")
            and d.indoor(a)
            and d.indoor(b)
            and d.floor(a) != d.floor(b)
            and room_of[a] not in merged
            and room_of[b] not in merged
        )
        if stair_between_rooms:
            shaft, shaft_doors = _shaft(d, o, room_of, state, rooms)
            rooms[shaft.id] = shaft
            shaft_of_opening[oid] = shaft.id
            new_doors = shaft_doors
        else:
            new_doors = [_direct_door(d, o, room_of, state, rooms, merged)]
        for door in new_doors:
            doors[door.id] = door
        doors_of_opening[oid] = [door.id for door in new_doors]

    exits = [
        Exit(
            id=oid,
            label=f"{oid}: {d.label(o['a'])} to {d.label(o['b'])}",
            door=doors_of_opening[oid][0],
            accessible=o.get("kind") not in ("stair", "step"),
        )
        for oid, o in d.openings.items()
        if o.get("is_exit") and doors_of_opening.get(oid)
    ]
    building = raw.get("building", {})
    frame = raw.get("frame", {})
    fire_venue = Venue(
        name=building.get("name", "venue.json"),
        verified=False,
        floor_elevations_m=dict(d.elevation_of_floor),
        rooms=rooms,
        doors=doors,
        exits=exits,
        notes=[f"Adapted from venue.json schema {raw.get('schema_version')} by engine.aria_venue"],
        scan={"frame": frame.get("datum"), "plan_axes": frame.get("plan_axes", ["x", "z"])},
    )
    spaces_of: dict[str, list[str]] = {rid: [] for rid in rooms}
    for sid, rid in room_of.items():
        spaces_of[rid].append(sid)
    return AriaVenue(
        raw=raw,
        fire=fire_venue,
        graph=build_route_graph(d, states),
        room_of=room_of,
        spaces_of=spaces_of,
        doors_of_opening=doors_of_opening,
        opening_of_door={did: oid for oid, dids in doors_of_opening.items() for did in dids},
        shaft_of_opening=shaft_of_opening,
        merged=merged,
        door_states=states,
        fire_excluded=fire_excluded,
        origin_space=origin_space,
        _data=d,
    )
