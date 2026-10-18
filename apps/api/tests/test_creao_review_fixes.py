"""Review fixes for the live layer: place parsing, the brief's exit list, the 10 s recheck,
start spaces from venue.json and the agents' fire-model snapshot. No network or app.main."""

import asyncio
import json
from pathlib import Path

import pytest

from app.creao import bridge, brief, dispatch, engine_model, plan
from app.creao import location as loc
from app.creao.buildings import get_building

VENUE_ID = "547b5ec5-30c5-4f76-8080-012a52e90bd9"
VENUE_JSON = Path(__file__).resolve().parents[3] / "packages" / "engine" / "venue.json"


@pytest.fixture(scope="module")
def jw():
    return get_building(VENUE_ID)


@pytest.mark.parametrize(
    "text", ["I'm at the entrance", "outside at the front entrance", "at check-in"]
)
def test_entrance_words_mean_outside_at_check_in(jw, text):
    found = loc.from_text(jw, text)
    assert found.zone_id == "entrance"
    assert plan.outside(jw, found.zone_id)


def test_main_entrance_still_names_the_doors(jw):
    assert loc.from_text(jw, "by the main entrance").exit_id == "main_entrance"


@pytest.mark.parametrize(
    "text", ["second floor hallway", "upstairs bathroom", "2nd floor restrooms", "upstairs lobby"]
)
def test_upstairs_with_a_generic_place_stays_on_floor_2(jw, text):
    found = loc.from_text(jw, text)
    assert found.floor == 2
    assert found.source == "floor"
    assert found.zone_id is None


def test_floor_hint_overrides_a_ground_floor_place(jw):
    found = loc.from_text(jw, "hallway", "2")
    assert (found.floor, found.zone_id) == (2, None)


@pytest.mark.parametrize(
    ("text", "zone"),
    [
        ("room 219 second floor", "room_219"),
        ("upstairs on the terrace", "terrace"),
        ("give me a second, I'm in the Collins room", "collins_room"),
        ("200A", "room_200"),
    ],
)
def test_named_rooms_keep_their_zone(jw, text, zone):
    found = loc.from_text(jw, text)
    assert found.zone_id == zone
    assert found.floor == jw.zone(zone).floor


def test_entrance_aliases_are_not_on_the_doors(jw):
    for eid in ("main_entrance", "main_entrance_2"):
        aliases = jw.exit(eid).aliases
        assert "entrance" not in aliases and "front entrance" not in aliases


def test_200a_belongs_to_room_200(jw):
    assert "200A" in jw.zone("room_200").spaces
    assert "200A" not in jw.zone("room_219").spaces


def test_brief_lists_all_14_exits_under_the_exits_heading(jw):
    text = brief.text(jw)
    block = text.split("Exits out of the building (14):", 1)[1].split("\n\n", 1)[0]
    ids = [line[2:].split(":", 1)[0] for line in block.strip().splitlines()]
    assert len(ids) == 14
    assert "outside_stairs" in ids


def test_start_spaces_come_from_venue_json():
    venue = json.loads(VENUE_JSON.read_text(encoding="utf-8"))
    expected = {
        s["id"]
        for s in venue["spaces"]
        if not s.get("is_outdoor") and s.get("kind") not in ("open_to_below", "elevator")
    }
    assert set(engine_model.start_spaces()) == expected
    assert "140" in expected


def test_manual_fire_model_steps_reach_the_agents_unfiltered():
    steps = [{"minute": m, "label": f"smoke {m}", "kind": "smoke"} for m in range(40)]
    assert len(bridge._snapshot_steps({"source": "manual", "steps": steps})) == 40
    engine = bridge._snapshot_steps({"source": "aria-engine", "steps": steps})
    assert engine == []


def test_recheck_skips_evacuations_without_a_fire_model(monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.creao.db import Base
    from app.creao.models import Evacuation

    calls = []

    async def fake_reevaluate(session, building, ev):
        calls.append(ev.id)
        return []

    monkeypatch.setattr(plan, "reevaluate", fake_reevaluate)

    async def go():
        db = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with db.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(db, expire_on_commit=False)
        async with maker() as session:
            session.add(Evacuation(id="nomodel", building_id=VENUE_ID, fire_model=None))
            session.add(
                Evacuation(id="engine", building_id=VENUE_ID, fire_model={"steps": [{"minute": 1}]})
            )
            await session.commit()
            await dispatch.recheck_routes(session)
        await db.dispose()

    asyncio.run(go())
    assert calls == ["engine"]
