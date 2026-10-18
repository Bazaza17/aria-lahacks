"""Time-dependent evacuation routes against a fire timeline.

Two ways to pick a route from a space at departure time t0:

- **predictive**: earliest-arrival time-dependent Dijkstra. The label is the arrival time. An
  opening is usable only if you reach it before its blocked time, and you can't enter a space at
  or after its blocked time. Edge times are fixed and every constraint is a deadline, so
  arriving earlier never hurts (FIFO) and label-setting Dijkstra is exact (Cooke & Halsey 1966;
  Orda & Rom 1990). Walks are door to door, so a search state is (space, opening came in by).
- **reactive**: the shortest route over what is open at t0 (what someone sees when they set
  off), then walked in time. If something on it closes before they reach it, it is cut off.

The gap between the two is the headline: where the obvious route walks into smoke. Both are
one walker per space; engine.evacuate moves whole groups (door and stair capacity) and
engine.flow checks whether everyone behind the first walker gets through.

Blocked times come from engine.fire's Timeline, mapped back to venue ids by venue_timeline(),
with two rules on top of the zone model: flashover also at a 600 °C upper layer, and the room of
fire origin untenable once the fire radiates 2.5 kW/m² at 3 m. Outdoor spaces and SAFE never
block.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from engine import physics
from engine.aria_venue import AriaVenue
from engine.constants import (
    SMOKE_PRESENT_DEPTH_M,
    TENABLE_LAYER_HEIGHT_M,
    TENABLE_LAYER_TEMP_K,
)
from engine.fire import Timeline
from engine.route_graph import SAFE, Arc, RouteGraph

INF = math.inf
ORIGIN_ONLY = "the only way out passes through the room of fire origin"
MARGINAL_S = 10.0  # ASSUMPTION: closer calls than this are inside the models' timing error

# --- Fire criteria applied on top of engine.fire. ---
# Flashover also when the upper layer reaches 600 °C (Peacock et al. 1999, "Defining flashover
# for fire hazard calculations", Fire Safety Journal 32: the usual zone-model criterion). Thomas
# alone counts every open interior opening as a vent, so a room opening into a big neighbour
# (140 into the atrium) never reached Q_fo within 15 min while its layer sat at 1000 °C.
FLASHOVER_LAYER_C = 600.0
# Room of origin: untenable once the fire radiates 2.5 kW/m² (ISO 13571 radiant limit) at 3 m,
# point source with radiative fraction 0.3 (SFPE): Q = 4 pi R² q'' / chi_r = 942 kW, 2:22 into a
# fast t² fire. ASSUMPTION: 3 m is as far as anyone can count on being from a fire whose position
# in the room is unknown. The zone model alone kept 140 tenable to 6:55 because its smoke
# drained into the atrium.
ORIGIN_RADIANT_LIMIT_KW_M2 = 2.5
ORIGIN_DISTANCE_M = 3.0
RADIATIVE_FRACTION = 0.3
ORIGIN_LIMIT_KW = (
    4.0 * math.pi * ORIGIN_DISTANCE_M**2 * ORIGIN_RADIANT_LIMIT_KW_M2 / RADIATIVE_FRACTION
)


def _min(*values: float | None) -> float | None:
    present = [v for v in values if v is not None]
    return min(present) if present else None


# --- The fire timeline per venue id. ---
def _member_times(
    frames: list[dict], room_id: str, offset_m: float, height_m: float
) -> tuple[int | None, int | None, str | None]:
    """Smoke and untenable times for one space inside a merged fire room, from its 1 s frames.

    The layer is measured from the space's own floor, and only smoke below the space's own
    ceiling counts: a hot layer up in a skylight well doesn't make the lobby under it untenable.
    Same criterion as engine.physics.is_untenable otherwise.
    """
    enters = untenable = by = None
    for f in frames:
        row = f["rooms"][room_id]
        h = row["layer_height_m"] - offset_m
        depth = height_m - h
        if enters is None and depth >= SMOKE_PRESENT_DEPTH_M:
            enters = f["t_s"]
        if untenable is None and physics.is_untenable(h, row["layer_temp_c"] + 273.15, depth):
            untenable = f["t_s"]
            by = _by(h, row["layer_temp_c"])
            break
    return enters, untenable, by


def _by(layer_height_m: float, layer_temp_c: float) -> str:
    """Which untenability limit tripped. Frames are rounded, so judge by temperature: a layer
    under 200 °C can only have tripped the 2 m smoke limit."""
    hot = layer_temp_c + 273.15 >= TENABLE_LAYER_TEMP_K
    return "heat" if hot and layer_height_m >= TENABLE_LAYER_HEIGHT_M else "smoke_layer"


def _untenable_by(tl: Timeline, room_id: str, t_s: int | None) -> str | None:
    if t_s is None or t_s >= len(tl.frames):
        return None
    row = tl.frames[t_s]["rooms"][room_id]
    return _by(row["layer_height_m"], row["layer_temp_c"])


def _origin_limit_s(tl: Timeline, room_id: str, limit_kw: float) -> int | None:
    for f in tl.frames:
        if f["rooms"][room_id]["hrr_kw"] >= limit_kw:
            return f["t_s"]
    return None


def _check_frames(tl: Timeline) -> None:
    times = [f["t_s"] for f in tl.frames[:2]]
    if len(times) < 2 or times[1] - times[0] != 1 or times[0] != 0:
        raise ValueError("venue_timeline needs the fire run's 1 s frames: simulate(frame_step_s=1)")


def venue_timeline(
    av: AriaVenue,
    tl: Timeline,
    origin_space: str | None = None,
    origin_limit_kw: float = ORIGIN_LIMIT_KW,
) -> dict:
    """Fire results per venue space and opening id (merged rooms and shafts unfolded).

    Needs 1 s frames (the per-space times inside merged rooms and the origin limit read them).
    With origin_space, that space is also blocked once the fire reaches origin_limit_kw.
    """
    _check_frames(tl)
    spaces = {}
    for sid, rid in av.room_of.items():
        row = tl.rooms[rid]
        offset = av.floor_offset(sid) if rid in av.merged else 0.0
        if rid in av.merged:
            enters, untenable, by = _member_times(tl.frames, rid, offset, av.height(sid))
        else:
            enters, untenable = row["smoke_enters_s"], row["smoke_untenable_s"]
            by = _untenable_by(tl, rid, untenable)
        reached = row["ignition_s"] if rid != tl.start_room else None
        spaces[sid] = {
            "fire_room": rid,
            "floor_offset_m": round(offset, 2),
            "smoke_enters_s": enters,
            "smoke_untenable_s": untenable,
            "untenable_by": by,
            "ignition_s": row["ignition_s"],
            "flashover_s": row["flashover_s"],
            "blocked_s": _min(untenable, row["flashover_s"], reached),
        }
    origin = None
    if origin_space is not None:
        limit_s = _origin_limit_s(tl, av.room_of[origin_space], origin_limit_kw)
        row = spaces[origin_space]
        origin = {
            "space": origin_space,
            "limit_kw": round(origin_limit_kw),
            "limit_s": limit_s,
            "zone_model_blocked_s": row["blocked_s"],
            "why": f"room of origin: untenable once the fire radiates "
            f"{ORIGIN_RADIANT_LIMIT_KW_M2:g} kW/m² at {ORIGIN_DISTANCE_M:g} m (ISO 13571; point "
            f"source, radiative fraction {RADIATIVE_FRACTION:g}): {origin_limit_kw:.0f} kW",
        }
        row["origin_limit_s"] = limit_s
        row["blocked_s"] = _min(row["blocked_s"], limit_s)
    openings = {}
    for oid, o in av.openings.items():
        doors = av.doors_of_opening.get(oid, [])
        shaft = av.shaft_of_opening.get(oid)
        # The fire doors' own blocked_s is room-level; the spaces' times are per space (members
        # of merged rooms, the origin limit), so take fire passage from the doors and the rest
        # from the spaces.
        times = [tl.doors[d]["fire_passes_s"] for d in doors]
        if shaft:
            times.append(tl.rooms[shaft]["blocked_s"])
        times += [spaces[s]["blocked_s"] for s in (o.get("a"), o.get("b")) if s in spaces]
        state = av.door_states[oid]
        openings[oid] = {
            "category": state["category"],
            "open": state["open"],
            "fire_doors": doors,
            "shaft": shaft,
            "burn_through_s": _min(*(tl.doors[d]["burn_through_s"] for d in doors)),
            "fire_passes_s": _min(*(tl.doors[d]["fire_passes_s"] for d in doors)),
            "blocked_s": _min(*times),
        }
    return {"spaces": spaces, "openings": openings, "origin": origin}


@dataclass(frozen=True)
class Blocks:
    """When each venue space and opening stops being usable (s after ignition).

    `origin`: the space where the fire starts (for explaining traps).
    `avoid`: spaces nobody may walk INTO from outside the set, at any time (off by default; the
    origin limit in venue_timeline already closes the room of origin once the fire is big).
    """

    spaces: dict[str, float] = field(default_factory=dict)
    openings: dict[str, float] = field(default_factory=dict)
    avoid: frozenset[str] = frozenset()
    origin: str | None = None

    def space(self, sid: str) -> float:
        return self.spaces.get(sid, INF)

    def opening(self, oid: str) -> float:
        return self.openings.get(oid, INF)

    def closes(self, arc: Arc) -> float:
        """When crossing this arc stops being possible: its opening or the space beyond."""
        return min(self.opening(arc.opening), self.space(arc.to))

    def may_enter(self, arc: Arc) -> bool:
        return arc.to not in self.avoid or arc.frm in self.avoid

    @classmethod
    def from_venue_timeline(cls, vt: dict, avoid: Iterable[str] = ()) -> Blocks:
        origin = vt.get("origin") or {}
        return cls(
            spaces={
                k: v["blocked_s"] for k, v in vt["spaces"].items() if v["blocked_s"] is not None
            },
            openings={
                k: v["blocked_s"] for k, v in vt["openings"].items() if v["blocked_s"] is not None
            },
            avoid=frozenset(avoid),
            origin=origin.get("space"),
        )


NO_FIRE = Blocks()


# --- Routes. ---
@dataclass
class Route:
    space: str
    mode: str  # "predictive" or "reactive"
    depart_s: float
    status: str  # "ok", "cut_off" (reactive only) or "trapped"
    reason: str | None = None
    exit: str | None = None  # building exit opening id
    path: list[str] = field(default_factory=list)  # space, opening, space, ..., SAFE
    points: list[list[float]] = field(default_factory=list)  # [x, z, elevation]
    distance_m: float | None = None
    exit_s: float | None = None  # crosses the building exit (s after ignition)
    eta_s: float | None = None  # reaches SAFE (s after ignition); None when cut off
    planned_eta_s: float | None = None  # what the ETA would have been (cut-off routes)
    margin_s: float | None = None  # least time to spare at any opening (None: nothing closes)
    cut_off: dict | None = None  # where and when a reactive route is cut
    arcs: list[Arc] = field(default_factory=list, repr=False)
    crossings: list[tuple[str, float]] = field(default_factory=list)  # (opening, head walker t)

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def marginal(self) -> bool:
        return self.ok and self.margin_s is not None and self.margin_s < MARGINAL_S

    def to_dict(self) -> dict:
        def r(v: float | None) -> float | None:
            return None if v is None else round(v, 1)

        out = {
            "status": self.status,
            "reason": self.reason,
            "exit": self.exit,
            "path": self.path,
            "points": [[round(c, 2) for c in p] for p in self.points],
            "crossings": [[oid, r(t)] for oid, t in self.crossings],
            "distance_m": r(self.distance_m),
            "depart_s": r(self.depart_s),
            "exit_s": r(self.exit_s),
            "eta_s": r(self.eta_s),
            "travel_s": r(None if self.eta_s is None else self.eta_s - self.depart_s),
            "margin_s": r(self.margin_s),
            "marginal": self.marginal,
        }
        if self.cut_off:
            out["planned_eta_s"] = r(self.planned_eta_s)
            out["cut_off"] = {k: r(v) if k.endswith("_s") else v for k, v in self.cut_off.items()}
        return out


Usable = Callable[[Arc, float], bool]
Hold = Callable[[Arc, float], float]  # first walker reaches an opening -> starts through it
_State = tuple[str, str | None]  # (space, opening came in by; None at the start)


def _search_all(
    graph: RouteGraph,
    source: str,
    t0: float,
    usable: Usable,
    stop_at_safe: bool = True,
    hold: Hold | None = None,
) -> tuple[dict[_State, float], dict[_State, tuple[_State, Arc]], _State | None]:
    """Earliest-arrival Dijkstra over (space, entry opening) states from source at t0.

    Returns the labels, the back-pointers and the first SAFE state popped (None: SAFE not
    reached). With stop_at_safe=False it labels every reachable state. `hold` delays the walker
    at an opening (a queue booked ahead of it); it must not decrease with arrival time, which
    keeps the search FIFO and exact.
    """
    start: _State = (source, None)
    best: dict[_State, float] = {start: t0}
    prev: dict[_State, tuple[_State, Arc]] = {}
    heap: list = [(t0, 0, start, None)]
    pushed = 0
    goal = None
    while heap:
        t, _, key, via = heapq.heappop(heap)
        if t > best.get(key, INF):
            continue
        u = key[0]
        if u == SAFE:
            if goal is None:
                goal = key
            if stop_at_safe:
                break
            continue
        for arc in graph.arcs.get(u, ()):
            if via is not None and arc.opening == via.opening:
                continue  # no turning back through the door just used
            dt, _, _ = graph.step(via, arc)
            t_cross = t + dt if hold is None else hold(arc, t + dt)
            if not usable(arc, t_cross):
                continue
            t_next = t_cross + (arc.t_out_s if arc.to == SAFE else 0.0)
            nkey = (arc.to, arc.opening)
            if t_next < best.get(nkey, INF):
                best[nkey] = t_next
                prev[nkey] = (key, arc)
                pushed += 1
                heapq.heappush(heap, (t_next, pushed, nkey, arc))
    return best, prev, goal


def _arcs_to(prev: dict[_State, tuple[_State, Arc]], key: _State) -> list[Arc]:
    arcs = []
    while key in prev:
        key, arc = prev[key][0], prev[key][1]
        arcs.append(arc)
    return arcs[::-1]


def _search(graph: RouteGraph, source: str, t0: float, usable: Usable) -> list[Arc] | None:
    _, prev, goal = _search_all(graph, source, t0, usable)
    return None if goal is None else _arcs_to(prev, goal)


def _walk(
    graph: RouteGraph,
    source: str,
    t0: float,
    mode: str,
    arcs: list[Arc],
    blocks: Blocks,
    hold: Hold | None = None,
) -> Route:
    """Walk the arcs from t0; record the path, polyline, crossing times, margin and cut-off."""
    node = graph.nodes[source]
    path, points = [source], [[*node.point, node.elevation]]
    t, distance, cut, margin = t0, 0.0, None, INF
    crossings: list[tuple[str, float]] = []
    declared_exit = leaves_building = None  # (arc, crossing time)
    prev = None
    for arc in arcs:
        dt, dd, bend = graph.step(prev, arc)
        t_cross = t + dt if hold is None else hold(arc, t + dt)
        closes = blocks.closes(arc)
        margin = min(margin, closes - t_cross)
        if cut is None and t_cross >= closes:
            cut = {
                "opening": arc.opening,
                "into": arc.to,
                "reach_s": t_cross,
                "blocked_s": closes,
                "late_by_s": t_cross - closes,
            }
        if declared_exit is None and arc.is_exit:
            declared_exit = (arc, t_cross)
        outward = not graph.nodes[arc.frm].is_outdoor and graph.nodes[arc.to].is_outdoor
        if leaves_building is None and outward:
            leaves_building = (arc, t_cross)
        path += [arc.opening, arc.to]
        if bend is not None:
            points.append(list(bend))
        points.append(list(arc.point))
        crossings.append((arc.opening, t_cross))
        distance += dd
        t = t_cross
        prev = arc
    if prev is not None:
        t += prev.t_out_s
        distance += prev.d_out_m
    # The exit is the opening venue.json marks is_exit; failing that, the first door outdoors.
    exit_arc, exit_s = declared_exit or leaves_building or (None, None)
    return Route(
        space=source,
        mode=mode,
        depart_s=t0,
        status="cut_off" if cut else "ok",
        exit=exit_arc.opening if exit_arc else None,
        path=path,
        points=points,
        distance_m=distance,
        exit_s=None if cut else exit_s,
        eta_s=None if cut else t,
        planned_eta_s=t if cut else None,
        margin_s=None if margin == INF else margin,
        cut_off=cut,
        arcs=list(arcs),
        crossings=crossings,
    )


def _only_through_origin(graph: RouteGraph, blocks: Blocks, source: str, t0: float) -> bool:
    """With no fire at all, is every way out of `source` through the room of origin?"""
    origin = blocks.origin
    if origin is None or source == origin:
        return False
    return _search(graph, source, t0, lambda a, _t: a.to != origin) is None


def predictive_route(graph: RouteGraph, blocks: Blocks, source: str, t0: float) -> Route:
    """Earliest arrival at SAFE, using only openings and spaces still usable when reached."""
    if blocks.space(source) <= t0:
        return Route(source, "predictive", t0, "trapped", reason="untenable at departure")

    def usable(arc: Arc, t_cross: float) -> bool:
        return t_cross < blocks.closes(arc) and blocks.may_enter(arc)

    arcs = _search(graph, source, t0, usable)
    if arcs is None:
        reason = "every route closes first"
        past_avoid = blocks.avoid and _search(graph, source, t0, lambda a, t: t < blocks.closes(a))
        if past_avoid or _only_through_origin(graph, blocks, source, t0):
            reason = ORIGIN_ONLY
        return Route(source, "predictive", t0, "trapped", reason=reason)
    return _walk(graph, source, t0, "predictive", arcs, blocks)


def reactive_route(graph: RouteGraph, blocks: Blocks, source: str, t0: float) -> Route:
    """Shortest route over what is open at t0, then walked in time (may be cut off)."""
    if blocks.space(source) <= t0:
        return Route(source, "reactive", t0, "trapped", reason="untenable at departure")

    def open_at_departure(arc: Arc, _t_cross: float) -> bool:
        return blocks.closes(arc) > t0 and blocks.may_enter(arc)

    arcs = _search(graph, source, t0, open_at_departure)
    if arcs is None:
        return Route(source, "reactive", t0, "trapped", reason="no route open at departure")
    return _walk(graph, source, t0, "reactive", arcs, blocks)


# --- Exits: when each is lost, and from where it can still be reached. ---
def _reachable_exits(
    graph: RouteGraph, blocks: Blocks, source: str, t0: float, exits: dict[str, str]
) -> set[str]:
    """Exits a walker leaving `source` at t0 can cross outward (into exits[e]) in time."""
    if blocks.space(source) <= t0:
        return set()

    def usable(arc: Arc, t_cross: float) -> bool:
        return t_cross < blocks.closes(arc) and blocks.may_enter(arc)

    best, _, _ = _search_all(graph, source, t0, usable, stop_at_safe=False)
    return {e for e, outside in exits.items() if (outside, e) in best}


def exit_reach(
    graph: RouteGraph,
    blocks: Blocks,
    sources: Iterable[str],
    exits: dict[str, str],
    grid: list[float],
) -> dict[str, dict]:
    """For each exit (id -> the space it leads out to) and each occupied source: the last
    departure time on `grid` at which a walker leaving then can still cross that exit,
    outward, before anything on the way closes."""
    occupied = [s for s in sources if graph.nodes[s].occupant_load > 0]
    wanted = exits
    last: dict[str, dict[str, float]] = {e: {} for e in exits}
    count: dict[str, list[int]] = {e: [] for e in exits}
    for t0 in grid:
        hits = {e: 0 for e in exits}
        for sid in occupied:
            for e in _reachable_exits(graph, blocks, sid, t0, wanted):
                last[e][sid] = t0
                hits[e] += 1
        for e in exits:
            count[e].append(hits[e])
    out = {}
    for e in exits:
        still = [s for s, t in last[e].items() if t >= grid[-1]]
        out[e] = {
            "spaces_at_start": count[e][0] if grid else 0,
            "reachable_counts": count[e],
            "reachable_until_s": None if still or not last[e] else max(last[e].values()),
            "kept_by": sorted(still),
            "last_reached_s": dict(sorted(last[e].items())),
        }
    return out


def exit_sides(av: AriaVenue) -> dict[str, tuple[str, str]]:
    """Each is_exit opening -> (inside, outside). An exit between two outdoor spaces (the west
    exterior stair) is listed from its upper side, `a` (VENUE.md)."""
    sides = {}
    for oid, o in av.openings.items():
        if o.get("is_exit"):
            a, b = o.get("a"), o.get("b")
            sides[oid] = (b, a) if b in av.room_of and a not in av.room_of else (a, b)
    return sides


def exits_lost(av: AriaVenue, vt: dict, reach: dict[str, dict] | None = None) -> list[dict]:
    """Each building exit: when the fire takes the opening itself (None: never within the
    horizon) and, with `reach`, until when occupied spaces can still get to it."""
    rows = []
    for oid, (inside, outside) in exit_sides(av).items():
        row = {
            "exit": oid,
            "from": inside,
            "to": outside,
            "lost_s": vt["openings"][oid]["blocked_s"],
        }
        if reach and oid in reach:
            row.update(reach[oid])
        rows.append(row)
    rows.sort(key=lambda r: (r["lost_s"] is None, r["lost_s"] or 0, r["exit"]))
    return rows
