"""The routing graph: venue.json spaces (plus SAFE) as nodes, walkable openings as arcs.

Times come from SFPE walking speeds. A route starts at a point inside its space's polygon, then
walks door to door: through each intermediate space it goes straight from the opening it came in
by to the opening it leaves by when that line stays inside the polygon, or else along the
shortest path inside it, turning at the polygon's inner corners (pulled 0.4 m into the room): an
L-shaped room or a corridor with a bend. Stairs and ramps add their slope length at stair speed,
and a route's polyline climbs or drops between the stair's two ends (venue.json `ends`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from engine.geometry import Point, inside, representative_point, segment_inside

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

# --- Route geometry (drawing and leg lengths). ---
CORNER_INSET_M = 0.4  # how far inside the room a path turns at an inner corner (half a shoulder)
VISIBILITY_STEP_M = 0.2  # sample spacing when testing that a straight walk stays inside a room
DOOR_MARGIN_M = 0.5  # door points sit on (or, with tracing error, just off) a room's outline
ANCHOR_NUDGE_M = 0.1  # a door off the outline enters the room this far inside it
ANCHOR_MARGIN_M = 0.15  # end margin once both ends are inside the room


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
    # Where the opening meets each side ([x, z]): a stair's two ends (venue.json `ends`), else
    # `point` on both sides.
    end_frm: Point | None = None
    end_to: Point | None = None
    elev_frm: float = 0.0  # floor elevation on each side
    elev_to: float = 0.0

    def side(self, sid: str) -> Point:
        """Where this opening meets space `sid` in plan."""
        end = self.end_frm if sid == self.frm else self.end_to if sid == self.to else None
        return end or self.point[:2]

    def crossing_points(self) -> list[Point3]:
        """The polyline across the opening: one point for a level door, or the two ends of a
        stair, step or ramp at each side's floor elevation."""
        a, b = self.side(self.frm), self.side(self.to)
        if abs(self.elev_frm - self.elev_to) < 0.05 and a == b:
            return [self.point]
        return [(*a, self.elev_frm), (*b, self.elev_to)]


@dataclass(frozen=True)
class Leg:
    """Level walk across a space from one opening to another."""

    t_s: float
    d_m: float
    via: tuple[Point3, ...] = ()  # turning points inside the space (none: straight across)


@dataclass
class RouteGraph:
    nodes: dict[str, Node]
    arcs: dict[str, list[Arc]]  # outgoing arcs by node id
    excluded: dict[str, str] = field(default_factory=dict)  # opening id -> why not walkable
    legs: dict[tuple[str, str, str], Leg] = field(default_factory=dict)  # (space, in, out)
    estimated_positions: dict[str, str] = field(default_factory=dict)  # opening id -> how
    # From a space's own point to one of its openings: turning points inside the space.
    starts: dict[tuple[str, str], tuple[Point3, ...]] = field(default_factory=dict)

    def arc_count(self) -> int:
        return sum(len(v) for v in self.arcs.values())

    def step(self, prev: Arc | None, arc: Arc) -> tuple[float, float, tuple[Point3, ...]]:
        """Time, distance and the turning points inside the space from arriving through `prev`
        (None: from the space's own point, at the start of a route) to crossing `arc`'s
        opening."""
        if prev is None:
            return arc.t_in_s, arc.d_in_m, self.starts.get((arc.frm, arc.opening), ())
        leg = self.legs.get((arc.frm, prev.opening, arc.opening))
        if leg is None:  # no geometry (a toy graph): via the space's own point
            node = self.nodes[arc.frm]
            via = () if node.point is None else ((*node.point, node.elevation),)
            return prev.t_out_s + arc.t_in_s, prev.d_out_m + arc.d_in_m, via
        return prev.half_s + leg.t_s + arc.half_s, prev.half_m + leg.d_m + arc.half_m, leg.via


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


def _end(o: dict, sid: str) -> Point | None:
    """Where a stair meets space `sid` (venue.json `ends`), if given."""
    p = (o.get("ends") or {}).get(sid)
    return (float(p[0]), float(p[1])) if p else None


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
        end_frm=_end(o, frm),
        end_to=_end(o, to),
        elev_frm=nodes[frm].elevation,
        elev_to=nodes[to].elevation if to != SAFE else nodes[frm].elevation,
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


def _inner_corners(poly: list[Point], inset: float = CORNER_INSET_M) -> list[Point]:
    """The polygon's reflex (inner) corners, each pulled `inset` into the room: the only
    places a shortest walk inside the room needs to turn."""
    n = len(poly)
    if n < 4:
        return []
    ccw = (
        sum(x0 * z1 - x1 * z0 for (x0, z0), (x1, z1) in zip(poly, poly[1:] + poly[:1], strict=True))
        > 0
    )
    out = []
    for i, v in enumerate(poly):
        a, b = poly[i - 1], poly[(i + 1) % n]
        cross = (v[0] - a[0]) * (b[1] - v[1]) - (v[1] - a[1]) * (b[0] - v[0])
        if (cross < -1e-9) if ccw else (cross > 1e-9):  # turns away from the inside: reflex
            ua, ub = _unit(a, v), _unit(b, v)
            bis = (ua[0] + ub[0], ua[1] + ub[1])
            norm = math.hypot(*bis) or 1.0
            for sign in (1.0, -1.0):
                c = (v[0] + sign * inset * bis[0] / norm, v[1] + sign * inset * bis[1] / norm)
                if inside(c, poly):
                    out.append(c)
                    break
    return out


def _unit(p: Point, q: Point) -> Point:
    """Unit vector from q towards p."""
    d = math.dist(p, q) or 1.0
    return ((p[0] - q[0]) / d, (p[1] - q[1]) / d)


def _sees(p: Point, q: Point, poly: list[Point], margin: float = DOOR_MARGIN_M) -> bool:
    samples = max(16, int(math.dist(p, q) / VISIBILITY_STEP_M))
    return segment_inside(p, q, poly, samples=samples, end_margin_m=margin)


def _anchor(p: Point, poly: list[Point]) -> Point:
    """p itself if it is inside the polygon, else the nearest point of the outline nudged
    just inside: where a door traced in the wall gap between two plan outlines enters the
    room."""
    if inside(p, poly):
        return p
    best, best_d = p, math.inf
    for (x0, z0), (x1, z1) in zip(poly, poly[1:] + poly[:1], strict=True):
        dx, dz = x1 - x0, z1 - z0
        t = max(
            0.0, min(1.0, ((p[0] - x0) * dx + (p[1] - z0) * dz) / ((dx * dx + dz * dz) or 1e-9))
        )
        c = (x0 + t * dx, z0 + t * dz)
        if math.dist(p, c) < best_d:
            best, best_d = c, math.dist(p, c)
    d = best_d or 1.0
    nudged = (
        best[0] + ANCHOR_NUDGE_M * (best[0] - p[0]) / d,
        best[1] + ANCHOR_NUDGE_M * (best[1] - p[1]) / d,
    )
    return nudged if inside(nudged, poly) else best


def inner_path(p: Point, q: Point, poly: list[Point], fallback: Point | None = None) -> list[Point]:
    """Turning points of the shortest walk from p to q inside the polygon (a visibility graph
    over its inner corners, Dijkstra). [] when the straight line stays inside. A door traced
    more than DOOR_MARGIN_M off the outline (plan tracing error, wall thickness) first steps to
    the nearest point inside. [fallback] (the room's own point) when no path is found."""
    if len(poly) < 3 or _sees(p, q, poly):
        return []
    pa, qa = _anchor(p, poly), _anchor(q, poly)
    head = [pa] if math.dist(p, pa) > DOOR_MARGIN_M else []
    tail = [qa] if math.dist(q, qa) > DOOR_MARGIN_M else []
    if head or tail:
        if _sees(pa, qa, poly, ANCHOR_MARGIN_M):
            return [*head, *tail]
    pts = [pa, qa, *_inner_corners(poly)]
    best = {0: 0.0}
    prev: dict[int, int] = {}
    todo, done = {0}, set()
    while todo:
        i = min(todo, key=best.__getitem__)
        todo.discard(i)
        done.add(i)
        if i == 1:
            break
        for j in range(1, len(pts)):
            if j in done:
                continue
            d = best[i] + math.dist(pts[i], pts[j])
            if d < best.get(j, math.inf) and _sees(pts[i], pts[j], poly, ANCHOR_MARGIN_M):
                best[j], prev[j] = d, i
                todo.add(j)
    if 1 not in prev:
        return [fallback] if fallback else []
    chain, k = [], prev[1]
    while k != 0:
        chain.append(pts[k])
        k = prev[k]
    return [*head, *chain[::-1], *tail]


def _length(points: list[Point]) -> float:
    return sum(math.dist(a, b) for a, b in zip(points, points[1:], strict=False))


def _legs(d: _Data, nodes: dict[str, Node], arcs: dict[str, list[Arc]]) -> tuple[dict, dict]:
    """Door-to-door walks across every space, for each pair of its walkable openings, and the
    first walk from each space's own point to each of its openings.

    A leg's length is the shortest walk inside the polygon between the two openings' centres,
    less half of any stair or ramp run on either side (that part is timed on the slope). Its
    turning points are drawn from where each opening meets this space (a stair's end)."""
    legs, starts = {}, {}
    touching: dict[str, dict[str, Arc]] = {sid: {} for sid in nodes}
    for out in arcs.values():
        for a in out:  # position and run don't depend on direction
            touching[a.frm].setdefault(a.opening, a)
            touching[a.to].setdefault(a.opening, a)
    for sid, by_opening in touching.items():
        if sid == SAFE:
            continue
        node, poly = nodes[sid], d.polygon(sid)
        elev = node.elevation

        def lift(points: list[Point], elev: float = elev) -> tuple[Point3, ...]:
            return tuple((x, z, elev) for x, z in points)

        for a in by_opening.values():
            if node.point is not None:
                starts[(sid, a.opening)] = lift(inner_path(node.point, a.side(sid), poly))
        for a_in in by_opening.values():
            for a_out in by_opening.values():
                if a_in.opening == a_out.opening:
                    continue
                p, q = a_in.point[:2], a_out.point[:2]
                length = _length([p, *inner_path(p, q, poly, node.point), q])
                level = max(0.0, length - a_in.run_half_m - a_out.run_half_m)
                ps, qs = a_in.side(sid), a_out.side(sid)
                via = lift(inner_path(ps, qs, poly, node.point))
                legs[(sid, a_in.opening, a_out.opening)] = Leg(
                    t_s=level / WALK_LEVEL_M_S, d_m=level, via=via
                )
    return legs, starts


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
    legs, starts = _legs(d, nodes, arcs)
    return RouteGraph(
        nodes=nodes,
        arcs=arcs,
        excluded=excluded,
        legs=legs,
        estimated_positions=estimated,
        starts=starts,
    )
