"""The venue.json adapter: every opening accounted for, merged rooms, door rules, fire rules."""

import math

import pytest

from engine.aria_venue import SAFE, load_aria_venue
from engine.constants import ALPHA_KW_S2
from engine.fire import simulate
from engine.routes import (
    FLASHOVER_LAYER_C,
    NO_FIRE,
    ORIGIN_LIMIT_KW,
    predictive_route,
    venue_timeline,
)
from engine.venue import OUTSIDE


@pytest.fixture(scope="module")
def av():
    return load_aria_venue()


@pytest.fixture(scope="module")
def collins():
    """A fast fire in 140 (the Collins Room), 1 s frames, with the demo's fire rules."""
    av = load_aria_venue(origin_space="140")
    tl = simulate(av.fire, av.fire_room("140"), "fast", 900, frame_step_s=1, flashover_layer_c=600)
    return av, tl, venue_timeline(av, tl, origin_space="140")


def test_every_opening_maps_or_is_excluded_with_a_reason(av):
    walkable = {arc.opening for arcs in av.graph.arcs.values() for arc in arcs}
    for oid in av.openings:
        assert av.doors_of_opening[oid] or av.fire_excluded.get(oid), f"{oid}: no fire mapping"
        assert oid in walkable or av.graph.excluded.get(oid), f"{oid}: no route mapping"
    for did, door in av.fire.doors.items():
        assert av.opening_of_door[did] in av.openings
        assert all(side == OUTSIDE or side in av.fire.rooms for side in (door.a, door.b))
    assert all(e.door in av.fire.doors for e in av.fire.exits)
    assert set(av.room_of) == {s for s, v in av.spaces.items() if not v.get("is_outdoor")}
    exits = [o for o, v in av.openings.items() if v.get("is_exit")]
    assert exits and all(o in walkable for o in exits), "an exit dropped out of routing"


def test_skylight_wells_and_the_galleria_are_one_tall_room(av):
    atrium = av.room_of["110"]
    wells = [sid for sid, s in av.spaces.items() if s.get("kind") == "open_to_below"]
    assert av.room_of["galleria_far_end"] == atrium
    assert wells and all(av.room_of[w] == atrium for w in wells)
    room, info = av.fire.rooms[atrium], av.merged[atrium]
    assert room.ceiling_height_m > av.spaces["110"]["height"]
    assert room.area_m2 * room.ceiling_height_m == pytest.approx(info["volume_m3"], rel=1e-3)
    spill_to_2f = [
        d for d in av.fire.doors.values() if atrium in (d.a, d.b) and d.floor == 2 and d.open
    ]
    assert spill_to_2f, "the atrium needs open doors at the 2F level"


def test_a_step_band_joins_two_spaces_into_one_fire_room(av):
    steps = [
        o
        for o in av.openings.values()
        if o.get("kind") == "step" and o["a"] in av.room_of and o["b"] in av.room_of
    ]
    assert steps
    for o in steps:
        assert av.room_of[o["a"]] == av.room_of[o["b"]], o["id"]


def test_atrium_smoke_reaches_the_second_floor():
    av = load_aria_venue(origin_space="110")
    tl = simulate(av.fire, av.fire_room("110"), "fast", horizon_s=300, frame_step_s=0)
    upstairs = [
        sid
        for sid, rid in av.room_of.items()
        if av.spaces[sid].get("storey") == "2F" and rid != av.room_of["110"]
    ]
    assert any(tl.rooms[av.room_of[s]]["smoke_untenable_s"] is not None for s in upstairs)


def test_raised_far_end_is_untenable_no_later_than_the_lobby(collins):
    _, _, vt = collins
    far, lobby = vt["spaces"]["galleria_far_end"], vt["spaces"]["110"]
    assert far["floor_offset_m"] > 0
    assert lobby["smoke_untenable_s"] is not None, "lobby should go untenable in 15 min"
    assert far["smoke_untenable_s"] <= lobby["smoke_untenable_s"]


def test_an_opening_closes_no_later_than_either_of_its_spaces(collins):
    av, _, vt = collins
    for oid, row in vt["openings"].items():
        for sid in (av.openings[oid]["a"], av.openings[oid]["b"]):
            if sid in vt["spaces"] and vt["spaces"][sid]["blocked_s"] is not None:
                assert row["blocked_s"] is not None, oid
                assert row["blocked_s"] <= vt["spaces"][sid]["blocked_s"], oid


def test_origin_room_closes_at_the_radiant_limit_and_the_room_flashes_over(collins):
    av, tl, vt = collins
    expected = math.sqrt(ORIGIN_LIMIT_KW / ALPHA_KW_S2["fast"])  # t² fire, about 142 s
    assert vt["origin"]["limit_s"] == pytest.approx(expected, abs=1.5)
    assert vt["spaces"]["140"]["blocked_s"] == vt["origin"]["limit_s"]
    room = tl.rooms[av.room_of["140"]]
    assert room["flashover_s"] is not None, "a 600 °C layer must count as flashover"
    assert FLASHOVER_LAYER_C == 600.0


def test_event_night_door_rules_and_overrides(av):
    states = av.door_states
    exterior = [o for o, s in states.items() if s["category"] == "exterior_door"]
    service = [o for o, s in states.items() if s["category"] == "service_door"]
    assert exterior and all(states[o]["open"] is False for o in exterior)
    assert service and all(states[o]["open"] is False for o in service)
    assert all(s["open"] for s in states.values() if s["category"] == "event_door")
    flipped = load_aria_venue(door_overrides={exterior[0]: True})
    assert flipped.door_states[exterior[0]]["open"] is True
    assert flipped.fire.doors[flipped.doors_of_opening[exterior[0]][0]].open
    with pytest.raises(ValueError):
        load_aria_venue(door_overrides={"no-such-opening": True})
    outdoor = next(o for o, s in states.items() if s["category"] == "outdoor")
    with pytest.raises(ValueError):
        load_aria_venue(door_overrides={outdoor: False})


def test_only_a_sealed_room_of_origin_gets_its_doors_opened():
    sealed = load_aria_venue(origin_space="170")  # its one opening is an exterior door
    assert sealed.door_states["D-170-OUT"]["open"] is True
    vented = load_aria_venue(origin_space="140")  # already open to the Galleria
    assert vented.door_states["D-130D-140"]["open"] is False
    with pytest.raises(ValueError):
        load_aria_venue(origin_space="well_mid")  # a fire can't start in a skylight well


def test_safe_is_reachable_from_every_indoor_space_when_nothing_burns(av):
    for sid in av.route_sources():
        route = predictive_route(av.graph, NO_FIRE, sid, 0.0)
        assert route.ok, f"{sid} cannot reach SAFE"
        assert route.path[0] == sid and route.path[-1] == SAFE
        assert route.eta_s > 0 and route.distance_m > 0
