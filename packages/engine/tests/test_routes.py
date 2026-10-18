"""Time-dependent routing on a toy graph: predictive vs reactive."""

from engine.aria_venue import SAFE, Arc, Node, RouteGraph
from engine.routes import NO_FIRE, Blocks, evacuate, predictive_route, reactive_route


def _graph(edges: list[tuple[str, str, str, float, float]]) -> RouteGraph:
    """edges: (opening, a, b, seconds a->opening, seconds opening->b)."""
    ids = {a for _, a, *_ in edges} | {b for _, _, b, *_ in edges}
    nodes = {
        n: Node(n, n, "room", "1F", n == SAFE, None if n == SAFE else (0.0, 0.0), 0.0, 10)
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
            effective_width_m=0.6,
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
    assert no_fire["counts"]["predictive"] == {"ok": 3, "cut_off": 0, "trapped": 0}
    assert no_fire["counts"]["reactive"] == {"ok": 3, "cut_off": 0, "trapped": 0}
    assert no_fire["occupants_at_risk"] == {"predictive": 0, "reactive": 0}


def test_routes_never_enter_the_room_of_fire_origin():
    avoid_corridor = Blocks(avoid=frozenset({"C"}))
    assert "C" not in predictive_route(TOY, avoid_corridor, "H", 0.0).path
    assert "C" not in reactive_route(TOY, avoid_corridor, "H", 0.0).path
    assert predictive_route(TOY, avoid_corridor, "C", 0.0).ok  # people inside may leave
