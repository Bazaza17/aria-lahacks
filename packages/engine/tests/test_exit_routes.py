"""Exits and drawn routes on the real venue: exits lost to the fire drop out of every later plan,
and the route lines stay inside the spaces they walk through and stop at the building exit."""

import math

import pytest

from engine.aria_venue import load_aria_venue
from engine.demo import run_demo
from engine.geometry import inside
from engine.outputs import exit_state
from engine.route_graph import inner_path
from engine.routes import STEP_OUT_M

WALL_GAP_M = 0.9  # a door traced in the gap between two plan outlines (wall thickness + tracing)


@pytest.fixture(scope="module")
def collins() -> dict:
    """Fire in the Collins Room (140); departures before and after its patio doors are lost."""
    return run_demo(start="140", horizon_s=600, departures=(0.0, 60.0, 150.0, 240.0, 330.0))


def _lost(result: dict) -> dict[str, float]:
    return {e["exit"]: e["lost_s"] for e in result["fire"]["exits"] if e["lost_s"] is not None}


def test_no_plan_or_self_chosen_route_uses_an_exit_already_lost(collins):
    lost = _lost(collins)
    assert lost, "the Collins fire should take at least one exit within 10 minutes"
    rerouted = 0
    for dep in collins["routes"]["departures"]:
        t0 = dep["t0_s"]
        for sid, row in dep["spaces"].items():
            for mode in ("predictive", "reactive"):
                path = row[mode]["path"]
                gone = [oid for oid, t in lost.items() if t <= t0 and oid in path]
                assert not gone, f"{mode} route from {sid} at t0={t0} uses lost exit {gone}"
        rerouted += sum(1 for oid, t in lost.items() if t <= t0)
    assert rerouted, "no departure falls after an exit is lost: the test proves nothing"


def test_collins_patio_doors_are_used_until_lost_then_dropped(collins):
    lost = _lost(collins)["D-140-OUT"]
    for dep in collins["viewer"]["routes"]["departures"]:
        used = dep["exit_use"].get("D-140-OUT", {}).get("plan", 0)
        if dep["t0_s"] >= lost:
            assert used == 0
    first = collins["viewer"]["routes"]["departures"][0]
    assert first["exit_use"].get("D-140-OUT", {}).get("plan", 0) > 0


def test_viewer_exits_carry_human_names_and_states(collins):
    exits = collins["viewer"]["exits"]
    assert exits and all(e["label"] != e["id"] for e in exits)
    patio = next(e for e in exits if e["id"] == "D-140-OUT")
    assert patio["label"] == "Collins Room patio doors"
    assert collins["viewer"]["doors"]["D-140-OUT"]["name"] == "Collins Room patio doors"
    assert exit_state(patio, 0.0) == "open"
    assert exit_state(patio, patio["blocked_s"]) == "lost"


def _near(p: tuple[float, float], poly: list[tuple[float, float]], tol: float) -> bool:
    if inside(p, poly):
        return True
    for (x0, z0), (x1, z1) in zip(poly, poly[1:] + poly[:1], strict=True):
        dx, dz = x1 - x0, z1 - z0
        t = max(0.0, min(1.0, ((p[0] - x0) * dx + (p[1] - z0) * dz) / ((dx * dx + dz * dz) or 1)))
        if math.dist(p, (x0 + t * dx, z0 + t * dz)) <= tol:
            return True
    return False


def _polygon(av, sid: str) -> list[tuple[float, float]]:
    return [(float(x), float(z)) for x, z in av.spaces[sid].get("polygon") or []]


def test_route_lines_stay_inside_the_spaces_they_walk(collins):
    av = load_aria_venue()
    deps = {d["t0_s"]: d for d in collins["routes"]["departures"]}
    checked = 0
    for dep in collins["viewer"]["routes"]["departures"]:
        for line in dep["routes"]:
            mode = "predictive" if line["kind"] == "plan" else "reactive"
            path = deps[dep["t0_s"]]["spaces"][line["space"]][mode]["path"]
            polys = [_polygon(av, s) for s in path[0::2] if s in av.spaces]
            pts = line["points"]
            segs = list(zip(pts, pts[1:], strict=False))[:-1]  # the last is the step outside
            for a, b in segs:
                if abs(a[2] - b[2]) > 0.05:
                    continue  # a stair or step run between two floors
                n = max(2, int(math.dist(a[:2], b[:2]) / 0.25))
                for i in range(n + 1):
                    f = i / n
                    q = (a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]))
                    assert any(_near(q, p, WALL_GAP_M) for p in polys if len(p) >= 3), (
                        f"{line['kind']} route from {line['space']} at t0={dep['t0_s']} "
                        f"leaves its spaces at {q}"
                    )
                    checked += 1
    assert checked > 1000


def test_route_lines_end_just_past_the_exit(collins):
    av = load_aria_venue()
    for dep in collins["viewer"]["routes"]["departures"]:
        for line in dep["routes"]:
            if not line["exit"] or line["status"] == "trapped":
                continue
            o = av.openings[line["exit"]]
            ends = list((o.get("ends") or {}).values()) or [o["position"]]
            last = line["points"][-1][:2]
            assert min(math.dist(last, e) for e in ends) <= STEP_OUT_M + 0.01


def test_inner_path_turns_at_the_inner_corner_of_an_l_shaped_room():
    # An L: 10 x 10 with the top-right 6 x 6 cut away (counter-clockwise in x, z).
    room = [(0.0, 0.0), (10.0, 0.0), (10.0, 4.0), (4.0, 4.0), (4.0, 10.0), (0.0, 10.0)]
    door_a, door_b = (10.0, 2.0), (2.0, 10.0)
    via = inner_path(door_a, door_b, room)
    assert len(via) == 1
    corner = via[0]
    assert math.dist(corner, (4.0, 4.0)) < 0.6 and inside(corner, room)
    assert inner_path((1.0, 1.0), (9.0, 1.0), room) == []  # straight line stays inside
