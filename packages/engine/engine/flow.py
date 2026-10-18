"""Screening hydraulic check: does everyone behind the first walker get through in time?

Routes (engine.routes) move one walker per space. Here each space's occupant_load follows its
route as a group, and every opening passes at most Fs x We people per second (SFPE maximum
specific flow Fs: 1.3 persons/s/m for doors, corridors and ramps, 1.01 on 7/11 stairs; We is
venue.json's effective_width). At each opening the groups queue first come, first served, by
when their first walker arrives. A group's last person crosses an opening when the queue
releases it, and never sooner than they crossed the previous opening plus the walk between.
Everyone who crosses an opening after it closes (smoke, fire) is at risk; the rest are cleared.

Limits (screening only): no pre-movement time, no slowing in dense rooms or smoke, no merging-
flow priority, groups don't split across routes, and a group's first walker isn't delayed by
queues upstream. Those make it optimistic; it still turns "one walker got out" into a count of
people who can't get through the doors in time.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.routes import Blocks, Route


def _capacity_p_s(route: Route) -> dict[str, float]:
    return {a.opening: a.specific_flow * a.effective_width_m for a in route.arcs}


def queue_check(blocks: Blocks, routes: dict[str, Route], load: dict[str, int]) -> dict:
    """Per space: people cleared and at risk, the last person's ETA and the bottleneck.
    Per opening: people through it, when its queue clears, and whether that's after it closes.
    Only routes with status "ok" and occupants are checked."""
    groups: dict[str, list[tuple[float, str, int]]] = {}
    capacity: dict[str, float] = {}
    for sid, r in routes.items():
        if not r.ok or load.get(sid, 0) <= 0:
            continue
        capacity.update(_capacity_p_s(r))
        for k, (oid, t) in enumerate(r.crossings):
            groups.setdefault(oid, []).append((t, sid, k))

    window: dict[tuple[str, int], tuple[float, float]] = {}
    openings = {}
    for oid, gs in groups.items():
        gs.sort()
        cap = max(capacity[oid], 1e-6)
        end = -math.inf
        for t, sid, k in gs:
            start = max(t, end)
            end = start + load[sid] / cap
            window[(sid, k)] = (start, end)
        closes = min(
            blocks.closes(a)
            for sid in {g[1] for g in gs}
            for a in routes[sid].arcs
            if a.opening == oid
        )
        openings[oid] = {
            "people": sum(load[s] for _, s, _ in gs),
            "spaces": len(gs),
            "capacity_p_s": round(cap, 2),
            "first_s": round(gs[0][0], 1),
            "clear_s": round(end, 1),
            "closes_s": None if closes == math.inf else round(closes, 1),
            "late": end >= closes,
        }

    spaces = {}
    for sid, r in routes.items():
        n = load.get(sid, 0)
        if not r.ok or n <= 0:
            continue
        spaces[sid] = _group(r, n, window, blocks)
    return {"spaces": spaces, "openings": openings}


def _group(r: Route, n: int, window: dict, blocks: Blocks) -> dict:
    cleared, limited_by = float(n), None
    bottleneck, spread_max = None, -1.0
    tail = None
    for k, ((oid, t), arc) in enumerate(zip(r.crossings, r.arcs, strict=True)):
        start, end = window[(r.space, k)]
        if tail is not None:  # the last person walks on from the previous opening
            end = max(end, tail + (t - r.crossings[k - 1][1]))
        if end - t > spread_max:
            spread_max, bottleneck = end - t, oid
        closes = blocks.closes(arc)
        if end >= closes:
            through = n * min(1.0, max(0.0, (closes - start) / (end - start)))
            if through < cleared:
                cleared, limited_by = through, oid
        tail = end
    cleared_people = math.floor(cleared + 1e-9)
    last_out = tail + (r.eta_s - r.crossings[-1][1]) if r.crossings else r.eta_s
    return {
        "people": n,
        "cleared": cleared_people,
        "at_risk": n - cleared_people,
        "last_out_s": round(last_out, 1),
        "bottleneck": bottleneck,
        "bottleneck_spread_s": round(spread_max, 1),
        "limited_by": limited_by,
    }
