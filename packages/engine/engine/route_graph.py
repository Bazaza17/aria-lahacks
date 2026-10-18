"""The routing graph: venue.json spaces (plus SAFE) as nodes, walkable openings as arcs.

Times come from SFPE walking speeds. A route starts at a point inside its space's polygon, then
walks door to door: through each intermediate space it goes straight from the opening it came in
by to the opening it leaves by, or via a point inside the space when the straight line would
leave the polygon (an L-shaped room). Stairs and ramps add their slope length at stair speed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from engine.geometry import Point, representative_point, segment_inside

if TYPE_CHECKING:
    from engine.aria_venue import _Data

SAFE = "SAFE"  # venue.json's single sink node for the public way

# --- Walking speeds. ---
# SFPE hydraulic egress model (Nelson & Mowrer; Gwynne & Rosenbaum, SFPE Handbook 5th ed.):
# S = k (1 - 0.266 D) for densities D >= 0.54 persons/m². Below 0.54 people walk at the free
# speed k (1 - 0.266 * 0.54) = 0.856 k. Routes use the free speed; queues at openings come from
# the specific-flow check in engine.flow.
SFPE_FREE_SPEED_FACTOR = 1.0 - 0.266 * 0.54
K_LEVEL_M_S = 1.40  # SFPE k: corridors, doorways, level floors
K_STAIR_M_S = 1.08  # SFPE k: 7 in riser / 11 in tread stairs, speed along the line of travel
WALK_LEVEL_M_S = K_LEVEL_M_S * SFPE_FREE_SPEED_FACTOR  # ~1.20 m/s
WALK_STAIR_M_S = K_STAIR_M_S * SFPE_FREE_SPEED_FACTOR  # ~0.92 m/s
WALK_RAMP_M_S = WALK_LEVEL_M_S  # ASSUMPTION: a 1:12 ramp is walked at the level speed
RISER_M = 0.178  # 7 in. With TREAD_M, turns a stair's rise into a run when no length is given
TREAD_M = 0.279  # 11 in

# --- Flow capacity (SFPE maximum specific flow, persons per second per metre of effective
# width; effective width = clear width minus boundary layers, venue.json's effective_width). ---
FS_LEVEL_P_S_M = 1.3  # doors, corridors, ramps (SFPE Fsm 1.3; 0.9 m door -> 0.78 p/s)
FS_STAIR_P_S_M = 1.01  # 7/11 stairs (SFPE Fsm for k = 1.08)

Point3 = tuple[float, float, float]


@dataclass(frozen=True)
class Node:
    id: str
    name: str
    kind: str
    storey: str | None
    is_outdoor: bool
    point: Point | None  # representative point inside the polygon; None for SAFE
    elevation: float
    occupant_load: int


@dataclass(frozen=True)
class Arc:
    """One walkable opening, in one direction (frm -> opening -> to)."""

    opening: str
    frm: str
    to: str
    kind: str
    t_in_s: float  # frm's own point to the opening (the first step of a route)
    t_out_s: float  # opening to to's point (only the half slope when `to` is SAFE)
    d_in_m: float  # walking distance (slope length on stairs and ramps)
    d_out_m: float
    effective_width_m: float
    is_exit: bool
    point: Point3  # opening position [x, z, elevation]
    half_s: float = 0.0  # time on half the stair or ramp (each side of the opening)
    half_m: float = 0.0  # half the slope length
    run_half_m: float = 0.0  # half the horizontal run (the stair is centred on `point`)
    specific_flow: float = FS_LEVEL_P_S_M  # persons/s/m of effective width


@dataclass(frozen=True)
class Leg:
    """Level walk across a space from one opening to another."""

    t_s: float
    d_m: float
    bend: Point3 | None  # via this point inside the space, when the straight line leaves it


@dataclass
class RouteGraph:
    nodes: dict[str, Node]
    arcs: dict[str, list[Arc]]  # outgoing arcs by node id
    excluded: dict[str, str] = field(default_factory=dict)  # opening id -> why not walkable
    legs: dict[tuple[str, str, str], Leg] = field(default_factory=dict)  # (space, in, out)
    estimated_positions: dict[str, str] = field(default_factory=dict)  # opening id -> how

    def arc_count(self) -> int:
        return sum(len(v) for v in self.arcs.values())

    def step(self, prev: Arc | None, arc: Arc) -> tuple[float, float, Point3 | None]:
        """Time, distance and any bend point from arriving through `prev` (None: from the
        space's own point, at the start of a route) to crossing `arc`'s opening."""
        if prev is None:
            return arc.t_in_s, arc.d_in_m, None
        leg = self.legs.get((arc.frm, prev.opening, arc.opening))
        if leg is None:  # no geometry (a toy graph): via the space's own point
            node = self.nodes[arc.frm]
            bend = None if node.point is None else (*node.point, node.elevation)
            return prev.t_out_s + arc.t_in_s, prev.d_out_m + arc.d_in_m, bend
        return prev.half_s + leg.t_s + arc.half_s, prev.half_m + leg.d_m + arc.half_m, leg.bend


def stair_run(o: dict) -> float:
    if o.get("length"):
        return float(o["length"])
    return abs(float(o.get("rise") or 0.0)) / RISER_M * TREAD_M


def position(o: dict) -> Point | None:
    p = o.get("position")
    return (float(p[0]), float(p[1])) if p else None


def _not_walkable(o: dict, state: dict) -> str | None:
    if state["category"] == "unknown_space":
        return "names a space that is not in venue.json"
    if o.get("kind") == "elevator":
        return "elevator: not used for egress"
    if float(o.get("effective_width") or 0.0) <= 0.0:
        return "effective width 0 (floor void, well edge or shaft): carries smoke, not people"
    if not state["egress"]:
        return state["why"]
    return None


def _slope(o: dict) -> tuple[float, float, float, float]:
    """(horizontal run, slope length, speed, specific flow) for one opening."""
    kind = o.get("kind") or "door"
    rise = float(o.get("rise") or 0.0)
    if kind in ("stair", "step") and rise:
        run = stair_run(o)
        return run, math.hypot(run, rise), WALK_STAIR_M_S, FS_STAIR_P_S_M
    if kind == "ramp":
        run = float(o.get("length") or 0.0)
        return run, math.hypot(run, rise) if run else 0.0, WALK_RAMP_M_S, FS_LEVEL_P_S_M
    return 0.0, 0.0, WALK_LEVEL_M_S, FS_LEVEL_P_S_M


def _arc(nodes: dict[str, Node], o: dict, pos: Point, frm: str, to: str) -> Arc:
    run, slope, speed, flow = _slope(o)
    d_in = math.dist(nodes[frm].point, pos) if nodes[frm].point else 0.0
    d_out = math.dist(pos, nodes[to].point) if nodes[to].point else 0.0
    level_in = max(0.0, d_in - run / 2.0)
    level_out = max(0.0, d_out - run / 2.0)
    half_s = slope / 2.0 / speed
    sides = [s for s in (frm, to) if s != SAFE]
    elevation = sum(nodes[s].elevation for s in sides) / len(sides)
    return Arc(
        opening=o["id"],
        frm=frm,
        to=to,
        kind=o.get("kind") or "door",
        t_in_s=level_in / WALK_LEVEL_M_S + half_s,
        t_out_s=level_out / WALK_LEVEL_M_S + half_s,
        d_in_m=level_in + slope / 2.0,
        d_out_m=level_out + slope / 2.0,
        effective_width_m=float(o.get("effective_width") or 0.0),
        is_exit=bool(o.get("is_exit")),
        point=(pos[0], pos[1], round(elevation, 3)),
        half_s=half_s,
        half_m=slope / 2.0,
        run_half_m=run / 2.0,
        specific_flow=flow,
    )


def _node(d: _Data, sid: str) -> Node:
    s = d.spaces[sid]
    poly = d.polygon(sid)
    if len(poly) >= 3:
        point = representative_point(poly)
    else:  # no polygon: the mean of its openings' positions
        ps = [position(o) for o in d.openings.values() if sid in (o.get("a"), o.get("b"))]
        ps = [p for p in ps if p]
        point = (
            (sum(p[0] for p in ps) / len(ps), sum(p[1] for p in ps) / len(ps)) if ps else (0.0, 0.0)
        )
    return Node(
        id=sid,
        name=d.label(sid),
        kind=d.kind(sid),
        storey=s.get("storey"),
        is_outdoor=bool(s.get("is_outdoor")),
        point=point,
        elevation=d.floor_elevation(sid),
        occupant_load=int(s.get("occupant_load") or 0),
    )


def _legs(d: _Data, nodes: dict[str, Node], arcs: dict[str, list[Arc]]) -> dict:
    """Door-to-door walks across every space, for each pair of its walkable openings."""
    legs = {}
    touching: dict[str, dict[str, Arc]] = {sid: {} for sid in nodes}
    for out in arcs.values():
        for a in out:  # position and run don't depend on direction
            touching[a.frm].setdefault(a.opening, a)
            touching[a.to].setdefault(a.opening, a)
    for sid, by_opening in touching.items():
        if sid == SAFE:
            continue
        node, poly = nodes[sid], d.polygon(sid)
        for a_in in by_opening.values():
            for a_out in by_opening.values():
                if a_in.opening == a_out.opening:
                    continue
                p, q = a_in.point[:2], a_out.point[:2]
                bend = None
                if segment_inside(p, q, poly):
                    length = math.dist(p, q)
                else:
                    bend = (*node.point, node.elevation)
                    length = math.dist(p, node.point) + math.dist(node.point, q)
                level = max(0.0, length - a_in.run_half_m - a_out.run_half_m)
                legs[(sid, a_in.opening, a_out.opening)] = Leg(
                    t_s=level / WALK_LEVEL_M_S, d_m=level, bend=bend
                )
    return legs


def build_route_graph(d: _Data, states: dict[str, dict]) -> RouteGraph:
    nodes = {sid: _node(d, sid) for sid in d.spaces}
    nodes[SAFE] = Node(SAFE, d.label(SAFE), "safe", None, True, None, 0.0, 0)
    arcs: dict[str, list[Arc]] = {nid: [] for nid in nodes}
    excluded: dict[str, str] = {}
    estimated: dict[str, str] = {}
    for oid, o in d.openings.items():
        why = _not_walkable(o, states[oid])
        if why:
            excluded[oid] = why
            continue
        pos = position(o)
        if pos is None:  # midway between the two spaces' points, and say so
            pts = [nodes[s].point for s in (o["a"], o["b"]) if nodes[s].point]
            pos = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
            estimated[oid] = "no position in venue.json: midway between its two spaces"
        for frm, to in ((o["a"], o["b"]), (o["b"], o["a"])):
            # Nobody walks back in from the public way, or from outdoors into the building.
            if frm == SAFE or (nodes[frm].is_outdoor and not nodes[to].is_outdoor):
                continue
            arcs[frm].append(_arc(nodes, o, pos, frm, to))
    return RouteGraph(
        nodes=nodes,
        arcs=arcs,
        excluded=excluded,
        legs=_legs(d, nodes, arcs),
        estimated_positions=estimated,
    )
