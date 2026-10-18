import json

import pytest

from engine.fire import simulate
from engine.venue import OUTSIDE, load_venue


def test_footprint_gives_area_and_perimeter(tmp_path):
    raw = {
        "name": "Box",
        "floors": [{"level": 1, "elevation_m": 0.0}],
        "rooms": [
            {"id": "r", "name": "R", "floor": 1, "footprint": {"x": [4, -2], "z": [0, 3]},
             "ceiling_height_m": 3.0, "fuel_class": "office"}
        ],
        "doors": [{"id": "d", "a": "r", "b": "outside", "position": {"x": 1, "z": 0},
                   "width_m": 0.9, "open": True}],
    }
    path = tmp_path / "box.json"
    path.write_text(json.dumps(raw))
    venue = load_venue(path)
    room = venue.rooms["r"]
    assert room.footprint == (-2.0, 4.0, 0.0, 3.0)
    assert room.area_m2 == pytest.approx(18.0)
    assert room.perimeter == pytest.approx(18.0)
    assert venue.doors["d"].position == (1.0, 0.0)


def _on_edge(pos, fp, tol=1e-6):
    x, z = pos
    x0, x1, z0, z1 = fp
    inside = x0 - tol <= x <= x1 + tol and z0 - tol <= z <= z1 + tol
    edge = min(abs(x - x0), abs(x - x1), abs(z - z0), abs(z - z1)) <= tol
    return inside and edge


def test_sample_doors_sit_on_the_walls_they_join():
    venue = load_venue()
    for door in venue.doors.values():
        for side in (door.a, door.b):
            if side != OUTSIDE:
                assert _on_edge(door.position, venue.rooms[side].footprint), (door.id, side)


def test_frames_cover_the_run_and_carry_states():
    tl = simulate(load_venue(), "f1-main-hall", "fast", horizon_s=900, frame_step_s=10)
    assert [f["t_s"] for f in tl.frames] == list(range(0, 901, 10))
    last = tl.frames[-1]
    assert last["rooms"]["f1-main-hall"]["state"] in ("flashover", "burnt_out")
    assert "f1-main-hall" in last["blocked"]
    assert tl.frames[0]["blocked"] == []
    data = tl.to_dict()
    assert data["scan"]["floor_y"] == -0.85
    assert data["rooms"]["f1-lobby"]["footprint"] == {"x": [-4.0, 4.0], "z": [1.0, 9.0]}
    assert data["doors"]["d-lobby-hall"]["position"] == {"x": 0.0, "z": 1.0}
