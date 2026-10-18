"""The demo JSON: CLI options that must not crash, and what the viewer draws."""

import json

import pytest

from engine import outputs
from engine.aria_venue import load_aria_venue
from engine.demo import run_demo
from engine.fire import simulate
from engine.routes import venue_timeline


@pytest.fixture(scope="module")
def collins():
    av = load_aria_venue(origin_space="140")
    tl = simulate(av.fire, av.fire_room("140"), "fast", 600, frame_step_s=1, flashover_layer_c=600)
    return av, tl, venue_timeline(av, tl, origin_space="140")


def test_demo_runs_without_the_origin_limit():
    result = run_demo(origin_limit=False, horizon_s=300, departures=(0.0,), scan_step_s=60)
    origin = result["fire"]["origin"]
    assert origin["limit_kw"] is None and origin["limit_s"] is None
    assert result["fire"]["criteria"]["origin_limit_kw"] is None
    json.dumps(result, allow_nan=False)


def test_only_the_start_space_of_the_room_of_origin_ignites(collins):
    av, _, vt = collins
    assert av.room_of["150"] == av.room_of["140"]
    assert vt["spaces"]["140"]["ignition_s"] == 0
    assert vt["spaces"]["150"]["ignition_s"] is None


def test_frames_keep_smoke_below_each_spaces_own_ceiling(collins):
    av, tl, vt = collins
    frames = outputs.frames(av, tl, vt, "140", 30)
    assert frames
    for f in frames:
        for sid, row in f["rooms"].items():
            ceiling = av.height(sid)
            assert 0 <= row["layer_height_m"] <= ceiling, (f["t_s"], sid)
            assert row["smoke_depth_m"] == pytest.approx(ceiling - row["layer_height_m"], abs=0.01)
    lobby = frames[0]["rooms"]["110"]  # under the 8 m skylight box: capped at its 3.6 m ceiling
    assert lobby["layer_height_m"] == av.height("110") and lobby["smoke_depth_m"] == 0
