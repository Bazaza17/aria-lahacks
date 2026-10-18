"""Time-dependent evacuation routes against a fire timeline.

Two ways to pick a route from a space at departure time t0:

- **predictive**: earliest-arrival time-dependent Dijkstra. The label is the arrival time. An
  opening is usable only if you reach it before its blocked time, and you can't enter a space at
  or after its blocked time. Edge times are fixed and every constraint is a deadline, so
  arriving earlier never hurts (FIFO) and label-setting Dijkstra is exact (Cooke & Halsey 1966;
  Orda & Rom 1990).
- **reactive**: the shortest route over what is open at t0 (what someone sees when they set
  off), then walked in time. If something on it closes before they reach it, it is cut off.

The gap between the two is the headline: where the obvious route walks into smoke.

Blocked times come from engine.fire's Timeline, mapped back to venue ids by venue_timeline().
Outdoor spaces and SAFE never block.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from engine import physics
from engine.aria_venue import SAFE, Arc, AriaVenue, RouteGraph
from engine.fire import Timeline

INF = math.inf
ORIGIN_ONLY = "every open route passes through the room of fire origin"


def _min(*values: float | None) -> float | None:
    present = [v for v in values if v is not None]
    return min(present) if present else None


# --- The fire timeline per venue id. ---
def _member_untenable_s(
    frames: list[dict], room_id: str, ceiling_m: float, offset_m: float
) -> int | None:
    """First frame at which a merged-room member on a raised (or sunk) floor is untenable.

    Same criterion as engine.physics.is_untenable, with the layer height measured from the
    member's own floor. Exact at 1 s frames; coarser frames round the time up to a frame.
    """
    for f in frames:
        row = f["rooms"].get(room_id)
        if row is None:
            continue
        h = row["layer_height_m"]
        if physics.is_untenable(h - offset_m, row["layer_temp_c"] + 273.15, ceiling_m - h):
            return f["t_s"]
    return None


def venue_timeline(av: AriaVenue, tl: Timeline) -> dict:
    """Fire results per venue space and opening id (merged rooms and shafts unfolded)."""
    spaces = {}
    for sid, rid in av.room_of.items():
        row = tl.rooms[rid]
        offset = av.floor_offset(sid) if rid in av.merged else 0.0
        untenable = row["smoke_untenable_s"]
        if abs(offset) > 0.005 and tl.frames:
            ceiling = av.fire.rooms[rid].ceiling_height_m
            untenable = _member_untenable_s(tl.frames, rid, ceiling, offset)
        reached = row["ignition_s"] if rid != tl.start_room else None
        spaces[sid] = {
            "fire_room": rid,
            "floor_offset_m": round(offset, 2),
            "smoke_enters_s": row["smoke_enters_s"],
            "smoke_untenable_s": untenable,
            "ignition_s": row["ignition_s"],
            "flashover_s": row["flashover_s"],
            "blocked_s": _min(untenable, row["flashover_s"], reached),
        }
    openings = {}
    for oid, o in av.openings.items():
        doors = av.doors_of_opening.get(oid, [])
        shaft = av.shaft_of_opening.get(oid)
        times = [tl.doors[d]["blocked_s"] for d in doors]
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
    return {"spaces": spaces, "openings": openings}


@dataclass(frozen=True)
class Blocks:
    """When each venue space and opening stops being usable (s after ignition).

    `avoid`: spaces nobody may walk INTO from outside the set, at any time: the room of fire
    origin. The zone model keeps that room tenable until its layer drops, but a pre-plan never
    sends people past the fire itself. People already inside may still leave through it.
    """

    spaces: dict[str, float] = field(default_factory=dict)
    openings: dict[str, float] = field(default_factory=dict)
    avoid: frozenset[str] = frozenset()

    def space(self, sid: str) -> float:
        return self.spaces.get(sid, INF)

    def opening(self, oid: str) -> float:
        return self.openings.get(oid, INF)

    def may_enter(self, arc: Arc) -> bool:
        return arc.to not in self.avoid or arc.frm in self.avoid

    @classmethod
    def from_venue_timeline(cls, vt: dict, avoid: Iterable[str] = ()) -> Blocks:
        return cls(
            spaces={
                k: v["blocked_s"] for k, v in vt["spaces"].items() if v["blocked_s"] is not None
            },
            openings={
                k: v["blocked_s"] for k, v in vt["openings"].items() if v["blocked_s"] is not None
            },
            avoid=frozenset(avoid),
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
    eta_s: float | None = None  # reaches SAFE (s after ignition)
    cut_off: dict | None = None  # where and when a reactive route is cut

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict:
        def r(v: float | None) -> float | None:
            return None if v is None else round(v, 1)

        out = {
            "status": self.status,
            "reason": self.reason,
            "exit": self.exit,
            "path": self.path,
            "points": [[round(c, 2) for c in p] for p in self.points],
            "distance_m": r(self.distance_m),
            "depart_s": r(self.depart_s),
            "exit_s": r(self.exit_s),
            "eta_s": r(self.eta_s),
            "travel_s": r(None if self.eta_s is None else self.eta_s - self.depart_s),
        }
        if self.cut_off:
            out["cut_off"] = {k: r(v) if k.endswith("_s") else v for k, v in self.cut_off.items()}
        return out


Usable = Callable[[Arc, float], bool]


def _search(graph: RouteGraph, source: str, t0: float, usable: Usable) -> list[Arc] | None:
    """Earliest-arrival Dijkstra from source at t0 to SAFE over arcs that pass `usable`."""
    best = {source: t0}
    prev: dict[str, Arc] = {}
    heap = [(t0, 0, source)]
    pushed = 0
    while heap:
        t, _, u = heapq.heappop(heap)
        if t > best.get(u, INF):
            continue
        if u == SAFE:
            arcs = []
            while u != source:
                arcs.append(prev[u])
                u = prev[u].frm
            return arcs[::-1]
        for arc in graph.arcs.get(u, ()):
            t_cross = t + arc.t_in_s
            if not usable(arc, t_cross):
                continue
            t_next = t_cross + arc.t_out_s
            if t_next < best.get(arc.to, INF):
                best[arc.to] = t_next
                prev[arc.to] = arc
                pushed += 1
                heapq.heappush(heap, (t_next, pushed, arc.to))
    return None


def _build_route(
    graph: RouteGraph, source: str, t0: float, mode: str, arcs: list[Arc], blocks: Blocks
) -> Route:
    """Walk the arcs from t0; record the path, polyline, times and any cut-off."""
    node = graph.nodes[source]
    path, points = [source], [[*node.point, node.elevation]]
    t, distance, cut = t0, 0.0, None
    declared_exit = leaves_building = None  # (arc, crossing time)
    for arc in arcs:
        t_cross = t + arc.t_in_s
        closes = min(blocks.opening(arc.opening), blocks.space(arc.to))
        if cut is None and t_cross >= closes:
            cut = {"opening": arc.opening, "into": arc.to, "reach_s": t_cross, "blocked_s": closes}
        if declared_exit is None and arc.is_exit:
            declared_exit = (arc, t_cross)
        outward = not graph.nodes[arc.frm].is_outdoor and graph.nodes[arc.to].is_outdoor
        if leaves_building is None and outward:
            leaves_building = (arc, t_cross)
        path += [arc.opening, arc.to]
        points.append(list(arc.point))
        target = graph.nodes[arc.to]
        if target.point is not None:
            points.append([*target.point, target.elevation])
        distance += arc.d_in_m + arc.d_out_m
        t = t_cross + arc.t_out_s
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
        exit_s=exit_s,
        eta_s=t,
        cut_off=cut,
    )


def predictive_route(graph: RouteGraph, blocks: Blocks, source: str, t0: float) -> Route:
    """Earliest arrival at SAFE, using only openings and spaces still usable when reached."""
    if blocks.space(source) <= t0:
        return Route(source, "predictive", t0, "trapped", reason="untenable at departure")

    def usable(arc: Arc, t_cross: float) -> bool:
        before = t_cross < blocks.opening(arc.opening) and t_cross < blocks.space(arc.to)
        return before and blocks.may_enter(arc)

    arcs = _search(graph, source, t0, usable)
    if arcs is None:
        reason = "every route closes first"
        if blocks.avoid:  # would a route exist if it could pass the fire?
            past_fire = _search(
                graph,
                source,
                t0,
                lambda a, t: t < blocks.opening(a.opening) and t < blocks.space(a.to),
            )
            if past_fire is not None:
                reason = ORIGIN_ONLY
        return Route(source, "predictive", t0, "trapped", reason=reason)
    return _build_route(graph, source, t0, "predictive", arcs, blocks)


def reactive_route(graph: RouteGraph, blocks: Blocks, source: str, t0: float) -> Route:
    """Shortest route over what is open at t0, then walked in time (may be cut off)."""
    if blocks.space(source) <= t0:
        return Route(source, "reactive", t0, "trapped", reason="untenable at departure")

    def open_at_departure(arc: Arc, _t_cross: float) -> bool:
        is_open = blocks.opening(arc.opening) > t0 and blocks.space(arc.to) > t0
        return is_open and blocks.may_enter(arc)

    arcs = _search(graph, source, t0, open_at_departure)
    if arcs is None:
        return Route(source, "reactive", t0, "trapped", reason="no route open at departure")
    return _build_route(graph, source, t0, "reactive", arcs, blocks)


# --- Whole-building evacuation per departure time. ---
def evacuate(
    graph: RouteGraph, blocks: Blocks, sources: Iterable[str], departures: Iterable[float]
) -> list[dict]:
    """Predictive and reactive routes for every source at every departure time."""
    sources = list(sources)
    return [_departure(graph, blocks, sources, float(t0)) for t0 in departures]


def _departure(graph: RouteGraph, blocks: Blocks, sources: list[str], t0: float) -> dict:
    routes = {
        sid: (predictive_route(graph, blocks, sid, t0), reactive_route(graph, blocks, sid, t0))
        for sid in sources
    }
    load = {sid: graph.nodes[sid].occupant_load for sid in sources}
    counts = {"predictive": _count(), "reactive": _count()}
    at_risk = {"predictive": 0, "reactive": 0}
    reactive_fails, different_exit = [], []
    for sid, (pred, react) in routes.items():
        for mode, route in (("predictive", pred), ("reactive", react)):
            counts[mode][route.status] += 1
            at_risk[mode] += 0 if route.ok else load[sid]
        if react.status == "cut_off":
            reactive_fails.append(
                {
                    "space": sid,
                    "occupants": load[sid],
                    "reactive_exit": react.exit,
                    **react.to_dict()["cut_off"],
                    "predictive": pred.status,
                    "predictive_exit": pred.exit,
                    "predictive_eta_s": None if pred.eta_s is None else round(pred.eta_s, 1),
                }
            )
        elif pred.ok and react.ok and pred.exit != react.exit:
            different_exit.append(
                {"space": sid, "predictive_exit": pred.exit, "reactive_exit": react.exit}
            )
    return {
        "t0_s": t0,
        "counts": counts,
        "occupants_at_risk": at_risk,
        "trapped": sorted(sid for sid, (pred, _) in routes.items() if not pred.ok),
        "trapped_by_origin_only": sorted(
            sid for sid, (pred, _) in routes.items() if pred.reason == ORIGIN_ONLY
        ),
        "reactive_fails": reactive_fails,
        "different_exit": different_exit,
        "spaces": {
            sid: {"occupants": load[sid], "predictive": p.to_dict(), "reactive": r.to_dict()}
            for sid, (p, r) in routes.items()
        },
    }


def _count() -> dict[str, int]:
    return {"ok": 0, "cut_off": 0, "trapped": 0}


def exits_lost(av: AriaVenue, vt: dict) -> list[dict]:
    """Each building exit and when the fire takes it (None: never within the horizon)."""
    rows = []
    for oid, o in av.openings.items():
        if not o.get("is_exit"):
            continue
        a, b = o.get("a"), o.get("b")
        inside, outside = (b, a) if b in av.room_of and a not in av.room_of else (a, b)
        rows.append(
            {"exit": oid, "from": inside, "to": outside, "lost_s": vt["openings"][oid]["blocked_s"]}
        )
    rows.sort(key=lambda r: (r["lost_s"] is None, r["lost_s"] or 0, r["exit"]))
    return rows
