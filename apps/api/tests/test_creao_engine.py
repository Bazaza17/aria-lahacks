"""The live layer on the engine and the one venue model. No network, database or app.main.

The engine runs once for a Collins Room fire (~4 s) and every test reads that result.
"""

import asyncio
import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.creao import brief, engine_model, plan
from app.creao import location as loc
from app.creao.buildings import get_building
from app.creao.db import utcnow

VENUE_ID = "547b5ec5-30c5-4f76-8080-012a52e90bd9"
VENUE_JSON = Path(__file__).resolve().parents[3] / "packages" / "engine" / "venue.json"


@pytest.fixture(scope="module")
def jw():
    return get_building(VENUE_ID)


@pytest.fixture(scope="module")
def venue():
    return json.loads(VENUE_JSON.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def collins(jw):
    from app.routes.engine import run

    result = asyncio.run(run("140", "fast"))
    return result, engine_model.build_fire_model(jw, result)


def _evacuation(model, minute=0.0, routes=None, mode="drill"):
    return SimpleNamespace(
        fire_model=model,
        started_at=utcnow() - timedelta(minutes=minute),
        approved_routes=routes or {},
        mode=mode,
        origin_label="Collins Room",
    )


# ---------------------------------------------------------------- one venue model


def test_profile_has_every_venue_exit(jw, venue):
    venue_exits = {o["id"] for o in venue["openings"] if o.get("is_exit")}
    assert len(venue_exits) == 14
    assert {e.opening for e in jw.exits if e.exterior} == venue_exits
    assert all(jw.exit_for_opening(o) for o in venue_exits)


def test_profile_zones_are_venue_spaces(jw, venue):
    spaces = {s["id"]: s for s in venue["spaces"]}
    covered = [sid for z in jw.zones for sid in z.spaces]
    assert len(covered) == len(set(covered))  # no space in two zones
    assert set(covered) <= set(spaces)
    walkable = {s for s, v in spaces.items() if v["kind"] not in ("open_to_below", "elevator")}
    assert walkable <= set(covered)
    # occupants from the default 2F_indoor scenario
    assert sum(z.occupants for z in jw.zones) == sum(
        spaces[s].get("occupant_load") or 0 for s in covered
    )
    assert jw.occupant_scenario == "2F_indoor"


@pytest.mark.parametrize(
    "text", ["I'm in room 219", "in 219 upstairs", "Room 219 on the second floor"]
)
def test_room_219_is_an_indoor_2f_room(jw, text):
    found = loc.from_text(jw, text)
    zone = jw.zone(found.zone_id)
    assert zone and zone.id == "room_219" and zone.floor == 2 and not zone.outdoor


@pytest.mark.parametrize(
    "text", ["upstairs", "I'm at the workshops", "networking area", "second floor", "2nd floor"]
)
def test_upstairs_words_mean_the_indoor_2f_not_the_terrace(jw, text):
    found = loc.from_text(jw, text)
    assert found.floor == 2
    assert found.zone_id is None or not jw.zone(found.zone_id).outdoor
    assert "terrace" not in found.label.lower()
    f2 = jw.floor(2)
    assert found.anchor.ny == f2.ny


def test_floor_two_is_labelled_floor_plan(jw):
    assert "floor plan" in jw.floor(2).label.lower()
    assert all(z.source == "floor plan" for z in jw.zones if z.floor == 2)


def test_no_invented_assembly_point(jw):
    assert jw.assembly_exit_id is None
    assert not any(e.assembly for e in jw.exits)
    words = json.dumps(jw.model_dump()).lower()
    for bad in ("north lawn", "pauley", "refuge", "evacuation chair"):
        assert bad not in words


# ---------------------------------------------------------------- brief


def test_brief_has_every_exit_and_no_invented_facts(jw):
    b = brief.brief(VENUE_ID)
    assert b["building"] == VENUE_ID and b["updated_at"]
    assert len(b["exits"]) == 14
    for e in b["exits"]:
        assert e["id"] in b["text"] and {"id", "label", "floor"} <= set(e)
    text = b["text"].lower()
    for bad in ("lawn", "pauley", "refuge", "evacuation chair", "evac chair", "step-free route"):
        assert bad not in text
    assert "elevators are not used in an evacuation" in text
    assert b["assembly"] in b["text"]
    assert "floor plan" in text and "room 219" in text
    for stair in ("outside_stairs", "ne_stairs", "galleria_stair"):
        assert stair in b["text"]


# ---------------------------------------------------------------- engine -> fire model


def test_engine_fire_model(jw, collins):
    result, model = collins
    assert model["source"] == "aria-engine" and model["simulation"] is True
    assert model["origin"]["zone_id"] == "collins_room"
    steps = {(s["place"], s["kind"]): s["minute"] for s in model["steps"]}
    assert steps[("collins_room", "fire")] == 0
    lost = {e["exit"]: e["lost_s"] for e in result["fire"]["exits"]}
    assert steps[("collins_patio_doors", "exit lost")] == round(lost["D-140-OUT"] / 60, 1)
    # an exit the engine keeps has no loss step
    assert lost["D-100-OUT"] is None and ("office_100_door", "exit lost") not in steps
    # smoke in a zone comes from its spaces' engine times
    gal = [result["fire"]["spaces"][s]["smoke_enters_s"] for s in jw.zone("galleria").spaces]
    assert steps[("galleria", "smoke")] == round(min(t for t in gal if t is not None) / 60, 1)
    summary = model["summary"]
    assert summary["exits_lost"][0]["exit_id"] == "collins_patio_doors"
    assert [e["minute"] for e in summary["exits_lost"]] == sorted(
        e["minute"] for e in summary["exits_lost"]
    )
    assert (
        summary["at_risk_leaving_now"]
        == result["routes"]["departures"][0]["occupants_at_risk"]["predictive"]
    )
    assert "Collins Room" in summary["text"]


def test_engine_exits_only_predict_by_their_own_times(jw, collins):
    _, model = collins
    predicted = plan.predicted_minutes(jw, _evacuation(model))
    # Collins Room's corner door is lost when the engine says, not when smoke enters the room
    assert predicted["collins_corner_door"] > predicted["collins_patio_doors"] > 1


def test_engine_routes_map_to_profile_exits(jw, collins):
    result, model = collins
    dep0 = model["routes"][0]
    assert dep0["t0_min"] == 0
    assert set(dep0["zones"]) <= {z.id for z in jw.zones}
    for zone_id, exit_id in dep0["zones"].items():
        assert plan.exit_floor(jw, jw.exit(exit_id)) == jw.zone(zone_id).floor
    # room 219's engine route goes down a stair; the profile sends them to that stair, then out
    pred = result["routes"]["departures"][0]["spaces"]["219"]["predictive"]
    stair = next(jw.exit_for_opening(o) for o in pred["path"] if o.startswith("ST-"))
    assert dep0["zones"]["room_219"] == stair.id
    assert dep0["then"]["room_219"] == jw.exit_for_opening(pred["exit"]).id


def test_engine_route_uses_latest_departure(collins):
    _, model = collins
    times = [d["t0_min"] for d in model["routes"]]
    exit_at_2, _ = engine_model.engine_route(model, "galleria", 2.5)
    latest = max(t for t in times if t <= 2.5)
    assert exit_at_2 == next(d for d in model["routes"] if d["t0_min"] == latest)["zones"].get(
        "galleria"
    )


def test_choose_exit_takes_the_engine_route(jw, collins):
    _, model = collins
    ev = _evacuation(model)
    preferred, _ = plan.engine_exit(jw, ev, "collins_room")
    assert preferred
    states = {x.id: plan.ExitState(id=x.id, label=x.label) for x in jw.exits}
    assert plan.choose_exit(jw, "collins_room", states, preferred, 0)[0] == preferred
    # predicted loss later than now: still the engine's route
    states[preferred].unsafe, states[preferred].predicted_minute = True, 3.0
    assert plan.choose_exit(jw, "collins_room", states, preferred, 1.0)[0] == preferred
    # someone reported a hazard there: fall back to the heuristic
    states[preferred].hazard_ids = ["h1"]
    assert plan.choose_exit(jw, "collins_room", states, preferred, 1.0)[0] != preferred
    # no engine model: no preferred route
    assert plan.engine_exit(jw, _evacuation(None), "collins_room") == (None, None)


def test_instruction_for_2f_names_the_stair_then_the_door(jw, collins):
    _, model = collins
    dep0 = model["routes"][0]
    ev = _evacuation(model, routes=dict(dep0["zones"]))
    found = loc.from_text(jw, "room 219").as_dict()
    msg = plan.instruction(jw, ev, found)["message"]
    assert msg.startswith("DRILL: ")
    assert jw.exit(dep0["zones"]["room_219"]).label in msg
    assert "then out by" in msg and "elevator" in msg
    assert "lawn" not in msg.lower()
    # someone who only said "upstairs" gets the floor 2 routes, not the ground floor doors
    up = plan.instruction(jw, ev, loc.from_text(jw, "upstairs").as_dict())
    assert up["exits"] and all(jw.exit(x).floor == 2 for x in up["exits"])


def test_hand_typed_models_are_manual(jw):
    model = plan.normalize_fire_model(
        jw, {"steps": [{"minute": 0, "place": "galleria", "kind": "fire"}]}
    )
    assert model["source"] == "manual" and model["steps"][0]["place"] == "galleria"


def test_resolve_start(jw):
    starts = engine_model.start_spaces()
    assert engine_model.resolve_start(jw, "140", starts)[0] == "140"
    space, zone = engine_model.resolve_start(jw, "the galleria", starts)
    assert space == "110" and zone.id == "galleria"
    assert engine_model.resolve_start(jw, "somewhere odd", starts) is None
