"""Whole-building evacuation per departure time: Aria's capacity-aware plan vs reactive routes.

Every space's occupant_load moves as a group. The reactive groups each take the route that looks
open when they set off (engine.routes.reactive_route). Aria's plan books door and stair time
group by group (a greedy capacity-constrained route planner) and keeps the best of four
candidate plans. Both are then checked by engine.flow: people still queued at an opening when it
closes are at risk.
"""

from __future__ import annotations

import bisect
from collections.abc import Iterable
from dataclasses import replace

from engine.flow import queue_check
from engine.route_graph import Arc, RouteGraph
from engine.routes import (
    INF,
    MARGINAL_S,
    ORIGIN_ONLY,
    Blocks,
    Route,
    _arcs_to,
    _search_all,
    _walk,
    predictive_route,
    reactive_route,
)

# --- Capacity-aware plan: the predictive mode of evacuate(). ---
QUEUED_OUT = "no route gets this group through before its doors close, even queued"
MAX_REROUTES = 4  # tries per group after its last person turns out too late somewhere


def _capacity(arc: Arc) -> float:
    """People per second through the opening (SFPE specific flow x effective width)."""
    return max(arc.specific_flow * arc.effective_width_m, 1e-6)


def _fit(booked: list[tuple[float, float]], t: float, dur: float) -> float:
    """Earliest start >= t of a dur-long slot clear of the booked (sorted) slots. It never
    decreases as t grows, so holding walkers with it keeps the search FIFO."""
    start = t
    for a, b in booked:
        if start + dur <= a:
            break
        if start < b:
            start = b
    return start


def capacity_route(
    graph: RouteGraph,
    blocks: Blocks,
    source: str,
    t0: float,
    people: int,
    booked: dict[str, list[tuple[float, float]]],
    avoid: frozenset[str] = frozenset(),
    banned: frozenset[str] = frozenset(),
) -> tuple[Route | None, str | None]:
    """Earliest arrival for a whole group: at each opening the group waits for a slot clear of
    the groups booked before it, and the opening (and the space beyond) must still be open when
    its last person is through, people / (Fs x We) after its first. Routes don't enter `avoid`
    from outside it or use `banned` openings.

    The search checks each opening on its own; the walk then follows the last person along the
    route (a narrow door upstream delays them at every later one). Returns (route, None), or
    (None, the opening the last person reaches too late), or (None, None) if nothing fits."""
    if blocks.space(source) <= t0:
        return None, None

    def hold(arc: Arc, t: float) -> float:
        return _fit(booked.get(arc.opening, []), t, people / _capacity(arc))

    def usable(arc: Arc, t_start: float) -> bool:
        if arc.opening in banned or (arc.to in avoid and arc.frm not in avoid):
            return False
        last_through = t_start + people / _capacity(arc)
        return last_through < blocks.closes(arc) and blocks.may_enter(arc)

    _, prev, goal = _search_all(graph, source, t0, usable, hold=hold)
    if goal is None:
        return None, None
    route = _walk(graph, source, t0, "predictive", _arcs_to(prev, goal), blocks, hold=hold)
    margin, late = _last_person(route, people, blocks)
    if late is not None:
        return None, late
    route.margin_s = margin
    return route, None


def _last_person(route: Route, people: int, blocks: Blocks) -> tuple[float | None, str | None]:
    """Follow the group's last person: (least time to spare, first opening reached too late)."""
    tail, prev_t, margin = None, None, INF
    for (oid, t), arc in zip(route.crossings, route.arcs, strict=True):
        end = t + people / _capacity(arc)
        if tail is not None:
            end = max(end, tail + (t - prev_t))
        slack = blocks.closes(arc) - end
        if slack <= 0:
            return None, oid
        margin = min(margin, slack)
        tail, prev_t = end, t
    return (None if margin == INF else margin), None


def _book(route: Route, people: int, booked: dict[str, list[tuple[float, float]]]) -> None:
    for (oid, t), arc in zip(route.crossings, route.arcs, strict=True):
        bisect.insort(booked.setdefault(oid, []), (t, t + people / _capacity(arc)))


def _origin_sets(blocks: Blocks, source: str) -> list[frozenset[str]]:
    """Keep out of the room of fire origin if there's any way round it; else allow it."""
    if blocks.origin and blocks.origin != source:
        return [frozenset({blocks.origin}), frozenset()]
    return [frozenset()]


def _group_route(
    graph: RouteGraph,
    blocks: Blocks,
    sid: str,
    t0: float,
    people: int,
    booked: dict[str, list[tuple[float, float]]],
) -> Route | None:
    for avoid in _origin_sets(blocks, sid):
        banned: set[str] = set()
        for _ in range(MAX_REROUTES):
            route, late = capacity_route(
                graph, blocks, sid, t0, people, booked, avoid, frozenset(banned)
            )
            if route is not None:
                return route
            if late is None:
                break
            banned.add(late)
    return None


def free_route(graph: RouteGraph, blocks: Blocks, source: str, t0: float) -> Route:
    """The single-walker predictive route, kept out of the room of origin if possible."""
    if blocks.origin and blocks.origin != source:
        route = predictive_route(
            graph, replace(blocks, avoid=frozenset({blocks.origin})), source, t0
        )
        if route.ok:
            return route
    return predictive_route(graph, blocks, source, t0)


def _enters_origin(route: Route, origin: str | None) -> bool:
    return bool(origin) and route.space != origin and origin in route.path


def plan_routes(
    graph: RouteGraph,
    blocks: Blocks,
    sources: list[str],
    t0: float,
    free: dict[str, Route] | None = None,
    urgent_first: bool = True,
) -> dict[str, Route]:
    """Capacity-aware plan at t0. Groups (a space's occupant_load) take turns, each choosing
    the earliest route that gets the whole group through before anything on it closes, given
    the door and stair time booked by the groups before it: a greedy capacity-constrained route
    planner (CCRP, Lu, George & Shekhar 2005). Routes keep out of the room of fire origin when
    there is a way round. The turn order is the shortest single-walker ETA first, or with
    urgent_first the space that becomes untenable soonest (the room of origin) first. A group no
    route fits joins the queues on its single-walker route; engine.flow then counts who doesn't
    get through. `free`: the single-walker routes (free_route), if already computed."""
    if free is None:
        free = {sid: free_route(graph, blocks, sid, t0) for sid in sources}

    def turn(s: str) -> tuple:
        eta = free[s].eta_s if free[s].ok else INF
        return (blocks.space(s), eta, s) if urgent_first else (eta, s)

    booked: dict[str, list[tuple[float, float]]] = {}
    plan: dict[str, Route] = {}
    for sid in sorted(sources, key=turn):
        n = graph.nodes[sid].occupant_load
        if n <= 0 or not free[sid].ok:
            plan[sid] = free[sid]
            continue
        route = _group_route(graph, blocks, sid, t0, n, booked)
        if route is None:  # join the queues on its fastest route; some may not get through

            def queue(arc: Arc, t: float) -> float:
                return _fit(booked.get(arc.opening, []), t, 0.0)

            route = _walk(graph, sid, t0, "predictive", free[sid].arcs, blocks, hold=queue)
            if not route.ok:  # even its first walker reaches a closed door
                route = Route(sid, "predictive", t0, "trapped", reason=QUEUED_OUT)
        if route.ok:
            _book(route, n, booked)
        plan[sid] = route
    return plan


# --- Whole-building evacuation per departure time. ---
def evacuate(
    graph: RouteGraph, blocks: Blocks, sources: Iterable[str], departures: Iterable[float]
) -> list[dict]:
    """For every departure time: Aria's capacity-aware predictive plan and everyone's reactive
    routes, each checked for door and stair capacity (engine.flow)."""
    sources = list(sources)
    return [_departure(graph, blocks, sources, float(t0)) for t0 in departures]


def _at_risk(routes: dict[str, Route], check: dict, load: dict[str, int]) -> int:
    return sum(
        (check["spaces"][s]["at_risk"] if s in check["spaces"] else 0) if r.ok else load[s]
        for s, r in routes.items()
    )


def best_plan(
    graph: RouteGraph,
    blocks: Blocks,
    sources: list[str],
    t0: float,
    react: dict[str, Route],
    load: dict[str, int],
) -> tuple[dict[str, Route], dict, dict]:
    """Aria's recommended plan: of four candidates, the one that leaves the fewest people at
    risk after the capacity check. "capacity" and "capacity_eta" are the greedy CCRP plan with
    the most urgent or the nearest groups first; "fastest" sends every group the single-walker
    predictive way; "obvious" keeps each group's reactive route where it stays open and keeps
    out of the room of origin (the predictive one elsewhere). Ties go to "capacity"."""
    free = {sid: free_route(graph, blocks, sid, t0) for sid in sources}
    candidates = {
        "capacity": plan_routes(graph, blocks, sources, t0, free, urgent_first=True),
        "capacity_eta": plan_routes(graph, blocks, sources, t0, free, urgent_first=False),
        "fastest": free,
        "obvious": {
            s: replace(react[s], mode="predictive")
            if react[s].ok and not _enters_origin(react[s], blocks.origin)
            else free[s]
            for s in sources
        },
    }
    checks = {name: queue_check(blocks, c, load) for name, c in candidates.items()}
    risk = {name: _at_risk(c, checks[name], load) for name, c in candidates.items()}
    chosen = min(candidates, key=lambda n: (risk[n], n != "capacity"))
    return candidates[chosen], checks[chosen], {"chosen": chosen, "at_risk": risk}


def _status(route: Route, flow: dict | None) -> str:
    """ok, partial (some of the group still queued when a door closes), cut_off or trapped
    (including a group none of whom gets through the queues in time)."""
    if route.ok and flow and flow["at_risk"] > 0:
        return "trapped" if flow["cleared"] == 0 else "partial"
    return route.status


def _outcome(route: Route, flow: dict | None, people: int) -> dict:
    """The route plus its capacity check: final status and people at risk."""
    status = _status(route, flow)
    at_risk = flow["at_risk"] if route.ok and flow else (0 if route.ok else people)
    out = {**route.to_dict(), "status": status, "at_risk": at_risk, "flow": flow}
    if route.ok and status == "trapped":
        out["reason"] = QUEUED_OUT
    return out


def _departure(graph: RouteGraph, blocks: Blocks, sources: list[str], t0: float) -> dict:
    load = {sid: graph.nodes[sid].occupant_load for sid in sources}
    react = {sid: reactive_route(graph, blocks, sid, t0) for sid in sources}
    pred, pred_flow, plan = best_plan(graph, blocks, sources, t0, react, load)
    flow = {"predictive": pred_flow, "reactive": queue_check(blocks, react, load)}
    spaces = {
        sid: {
            "occupants": load[sid],
            "predictive": _outcome(pred[sid], flow["predictive"]["spaces"].get(sid), load[sid]),
            "reactive": _outcome(react[sid], flow["reactive"]["spaces"].get(sid), load[sid]),
        }
        for sid in sources
    }
    counts = {m: {"ok": 0, "partial": 0, "cut_off": 0, "trapped": 0} for m in flow}
    at_risk = {m: 0 for m in flow}
    for row in spaces.values():
        for mode in flow:
            counts[mode][row[mode]["status"]] += 1
            at_risk[mode] += row[mode]["at_risk"]
    contrasts = sorted(
        (
            _contrast_row(sid, row)
            for sid, row in spaces.items()
            if row["reactive"]["at_risk"] > row["predictive"]["at_risk"]
        ),
        key=lambda c: -c["saved"],
    )
    why = {s: row["predictive"]["reason"] for s, row in spaces.items()}
    no_way = [s for s in sources if spaces[s]["predictive"]["status"] == "trapped"]
    return {
        "t0_s": t0,
        "plan": plan,
        "counts": counts,
        "occupants_at_risk": at_risk,
        "untenable_at_departure": sorted(s for s in no_way if why[s] == "untenable at departure"),
        "trapped": sorted(s for s in no_way if why[s] != "untenable at departure"),
        "trapped_by_origin_only": sorted(s for s in no_way if why[s] == ORIGIN_ONLY),
        "partial": {
            mode: sorted(s for s, row in spaces.items() if row[mode]["status"] == "partial")
            for mode in flow
        },
        "reactive_cut_off": sorted(s for s in sources if react[s].status == "cut_off"),
        "contrasts": contrasts,
        "flow": {mode: f["openings"] for mode, f in flow.items()},
        "spaces": spaces,
    }


def _contrast_row(sid: str, row: dict) -> dict:
    """One space where the plan leaves fewer people at risk than the reactive routes."""
    p, r = row["predictive"], row["reactive"]
    rf, pf = r.get("flow") or {}, p.get("flow") or {}
    out = {
        "space": sid,
        "occupants": row["occupants"],
        "saved": r["at_risk"] - p["at_risk"],
        "reactive": {
            "status": r["status"],
            "at_risk": r["at_risk"],
            "exit": r["exit"],
            "cut_off": r.get("cut_off"),
            "limited_by": rf.get("limited_by"),
        },
        "predictive": {
            "status": p["status"],
            "at_risk": p["at_risk"],
            "exit": p["exit"],
            "path": p["path"],
            "eta_s": p["eta_s"],
            "last_out_s": pf.get("last_out_s"),
            "margin_s": p["margin_s"],
            "reason": p["reason"],
        },
    }
    cut = r.get("cut_off")
    out["marginal"] = bool(
        (cut and cut["late_by_s"] < MARGINAL_S)
        or (p["margin_s"] is not None and p["margin_s"] < MARGINAL_S)
    )
    return out
