"""The venue.json adapter: every opening accounted for, the merged atrium, door rules, reach."""

import pytest

from engine.aria_venue import SAFE, load_aria_venue
from engine.fire import simulate
from engine.routes import NO_FIRE, predictive_route, venue_timeline
from engine.venue import OUTSIDE


@pytest.fixture(scope="module")
def av():
    return load_aria_venue()


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


def test_atrium_smoke_reaches_the_second_floor():
    av = load_aria_venue(origin_space="110")
    tl = simulate(av.fire, av.fire_room("110"), "fast", horizon_s=300, frame_step_s=0)
    upstairs = [
        sid
        for sid, rid in av.room_of.items()
        if av.spaces[sid].get("storey") == "2F" and rid != av.room_of["110"]
    ]
    assert any(tl.rooms[av.room_of[s]]["smoke_untenable_s"] is not None for s in upstairs)


def test_raised_far_end_is_untenable_no_later_than_the_lobby():
    av = load_aria_venue(origin_space="140")
    tl = simulate(av.fire, "140", "fast", horizon_s=900, frame_step_s=1)
    spaces = venue_timeline(av, tl)["spaces"]
    far, lobby = spaces["galleria_far_end"], spaces["110"]
    assert far["floor_offset_m"] > 0
    if lobby["smoke_untenable_s"] is not None:
        assert far["smoke_untenable_s"] <= lobby["smoke_untenable_s"]


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


def test_safe_is_reachable_from_every_indoor_space_when_nothing_burns(av):
    for sid in av.route_sources():
        route = predictive_route(av.graph, NO_FIRE, sid, 0.0)
        assert route.ok, f"{sid} cannot reach SAFE"
        assert route.path[0] == sid and route.path[-1] == SAFE
        assert route.eta_s > 0 and route.distance_m > 0
