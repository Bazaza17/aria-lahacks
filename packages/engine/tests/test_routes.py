"""Time-dependent routing on a toy graph: predictive vs reactive, and door capacity."""

from engine.aria_venue import SAFE, Arc, Node, RouteGraph
from engine.evacuate import evacuate, plan_routes
from engine.flow import queue_check
from engine.routes import NO_FIRE, Blocks, predictive_route, reactive_route


def _graph(
    edges: list[tuple[str, str, str, float, float]],
    people: dict[str, int] | None = None,
    widths: dict[str, float] | None = None,
) -> RouteGraph:
    """edges: (opening, a, b, seconds a->opening, seconds opening->b). Every space holds 10
    people and every opening is 0.6 m effective, unless `people` / `widths` say otherwise."""
    people, widths = people or {}, widths or {}
    ids = {a for _, a, *_ in edges} | {b for _, _, b, *_ in edges}
    nodes = {
        n: Node(
            n,
            n,
            "room",
            "1F",
            n == SAFE,
            None if n == SAFE else (0.0, 0.0),
            0.0,
            0 if n == SAFE else people.get(n, 10),
        )
        for n in ids
    }
    arcs = {n: [] for n in nodes}

    def arc(oid: str, frm: str, to: str, t_in: float, t_out: float) -> Arc:
        return Arc(
            opening=oid,
            frm=frm,
            to=to,
            kind="door",
            t_in_s=t_in,
            t_out_s=t_out,
            d_in_m=t_in,
            d_out_m=t_out,
            effective_width_m=widths.get(oid, 0.6),
            is_exit=to == SAFE,
            point=(0.0, 0.0, 0.0),
        )

    for oid, a, b, t_a, t_b in edges:
        arcs[a].append(arc(oid, a, b, t_a, t_b))
        if b != SAFE:
            arcs[b].append(arc(oid, b, a, t_b, t_a))
    return RouteGraph(nodes=nodes, arcs=arcs)


# Hall H has two ways out: a short corridor C (20 s) and a long way through lounge L (40 s).
TOY = _graph(
    [
        ("d-hall-corridor", "H", "C", 5, 5),
        ("d-corridor-out", "C", SAFE, 10, 0),
        ("d-hall-lounge", "H", "L", 5, 15),
        ("d-lounge-out", "L", SAFE, 20, 0),
    ]
)
# Smoke fills the corridor at 12 s: open when people set off, closed before they get through.
CORRIDOR_CLOSES = Blocks(
    spaces={"C": 12.0}, openings={"d-hall-corridor": 12.0, "d-corridor-out": 12.0}
)


def test_predictive_avoids_a_corridor_that_closes_before_arrival():
    route = predictive_route(TOY, CORRIDOR_CLOSES, "H", 0.0)
    assert route.ok
    assert "C" not in route.path
    assert route.path == ["H", "d-hall-lounge", "L", "d-lounge-out", SAFE]
    assert route.eta_s == 40.0
    assert route.exit == "d-lounge-out"


def test_reactive_takes_the_open_corridor_and_is_cut_off():
    route = reactive_route(TOY, CORRIDOR_CLOSES, "H", 0.0)
    assert route.status == "cut_off"
    assert route.path[:3] == ["H", "d-hall-corridor", "C"]
    assert route.cut_off["opening"] == "d-corridor-out"
    assert route.cut_off["reach_s"] == 20.0
    assert route.cut_off["blocked_s"] == 12.0


def test_reactive_sees_what_is_already_closed_at_departure():
    route = reactive_route(TOY, CORRIDOR_CLOSES, "H", 15.0)
    assert route.ok and "C" not in route.path


def test_blocked_at_departure_is_trapped_and_everything_is_open_without_fire():
    trapped = predictive_route(TOY, Blocks(spaces={"H": 30.0}), "H", 30.0)
    assert trapped.status == "trapped" and trapped.reason == "untenable at departure"
    [no_fire] = evacuate(TOY, NO_FIRE, ["H", "C", "L"], [0.0])
    everyone_out = {"ok": 3, "partial": 0, "cut_off": 0, "trapped": 0}
    assert no_fire["counts"]["predictive"] == everyone_out
    assert no_fire["counts"]["reactive"] == everyone_out
    assert no_fire["occupants_at_risk"] == {"predictive": 0, "reactive": 0}


def test_routes_never_enter_the_room_of_fire_origin():
    avoid_corridor = Blocks(avoid=frozenset({"C"}))
    assert "C" not in predictive_route(TOY, avoid_corridor, "H", 0.0).path
    assert "C" not in reactive_route(TOY, avoid_corridor, "H", 0.0).path
    assert predictive_route(TOY, avoid_corridor, "C", 0.0).ok  # people inside may leave


# 100 people in the hall. The corridor door is 0.6 m (0.78 people/s) and the corridor fills
# with smoke at 60 s; the lounge doors are 2.0 m (2.6 people/s) and never close.
CROWD = _graph(
    [
        ("d-hall-corridor", "H", "C", 5, 5),
        ("d-corridor-out", "C", SAFE, 10, 0),
        ("d-hall-lounge", "H", "L", 5, 15),
        ("d-lounge-out", "L", SAFE, 20, 0),
    ],
    people={"H": 100, "C": 0, "L": 0},
    widths={"d-hall-lounge": 2.0, "d-lounge-out": 2.0},
)
CORRIDOR_AT_60 = Blocks(spaces={"C": 60.0}, openings={"d-corridor-out": 60.0})
LOAD = {"H": 100, "C": 0, "L": 0}


def test_queue_check_counts_people_still_queued_when_the_door_closes():
    route = reactive_route(CROWD, CORRIDOR_AT_60, "H", 0.0)
    assert route.ok and "C" in route.path  # the first walker gets through
    flow = queue_check(CORRIDOR_AT_60, {"H": route}, LOAD)["spaces"]["H"]
    # 0.78 people/s; the exit door passes the first at 20 s, so by 60 s 40 x 0.78 = 31.2 are out.
    assert flow["cleared"] == 31 and flow["at_risk"] == 69
    assert flow["limited_by"] == "d-corridor-out"


def test_the_capacity_plan_sends_a_crowd_through_the_wider_doors():
    plan = plan_routes(CROWD, CORRIDOR_AT_60, ["H", "C", "L"], 0.0)
    assert plan["H"].ok and "L" in plan["H"].path
    flow = queue_check(CORRIDOR_AT_60, plan, LOAD)["spaces"]["H"]
    assert flow["at_risk"] == 0
    [dep] = evacuate(CROWD, CORRIDOR_AT_60, ["H", "C", "L"], [0.0])
    assert dep["occupants_at_risk"] == {"predictive": 0, "reactive": 69}
    assert dep["contrasts"][0]["space"] == "H" and dep["contrasts"][0]["saved"] == 69
