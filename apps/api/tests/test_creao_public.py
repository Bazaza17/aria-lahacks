"""Open drills: the console's reads and the drill actions need no key, live mode and the tool
endpoints still do, and the public never sees a phone number or a surname. In-memory SQLite and
the live router only (no app.main lifespan, no network)."""

from dataclasses import replace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.creao import auth, engine_model, models  # noqa: F401  (models registers the tables)
from app.creao import situation as sit
from app.creao.config import Settings
from app.creao.db import Base, get_session
from app.ratelimit import limiter
from app.routes import live

VENUE = "547b5ec5-30c5-4f76-8080-012a52e90bd9"
KEY, SECRET = "test-dispatch-key", "test-tool-secret"
PHONE = "+15555550142"
DISPATCHER = {"Authorization": f"Bearer {KEY}"}
TOOL = {"X-Tool-Secret": SECRET}


@pytest.fixture
def settings(monkeypatch):
    s = Settings(dispatch_keys={KEY}, tool_secret=SECRET, cloud=True)
    for mod in (auth, live):
        monkeypatch.setattr(mod, "get_settings", lambda: s)
    return s


@pytest.fixture
async def client(settings, monkeypatch):
    async def no_engine(*_a, **_k):  # keep the tests off the engine run; the place still resolves
        return None

    monkeypatch.setattr(engine_model, "fire_model_for", no_engine)
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def session():
        async with sessions() as s:
            yield s

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(live.router)
    app.dependency_overrides[get_session] = session
    limiter.reset()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            f"/live/buildings/{VENUE}/occupants",
            json={"people": [{"phone": PHONE, "name": "Maria Lopez", "zone": "galleria"}]},
            headers=TOOL,
        )
        assert r.status_code == 200
        yield c
    await engine.dispose()


async def _declare(c, mode="drill", headers=None, **extra):
    body = {"mode": mode, "origin": "galleria", "dispatcher": "Guest", "description": "test"}
    return await c.post(
        f"/live/buildings/{VENUE}/evacuations", json={**body, **extra}, headers=headers or {}
    )


def test_mask_public_hides_phones_and_surnames():
    payload = {
        "building": {"id": "b", "name": "James West Alumni Center"},
        "people": [{"id": "1", "name": "Maria Lopez", "mobility": [], "phone": PHONE}],
        "log": [{"text": "Maria Lopez confirmed out; called +1 555 555 0142"}],
        "caller": PHONE,
        "at": "2026-10-18T08:00:00+00:00",
    }
    out = sit.mask_public(payload)
    assert out["building"]["name"] == "James West Alumni Center"  # not a person
    assert out["people"][0]["name"] == "Maria"
    assert out["people"][0]["phone"] == "•••• 0142"
    assert out["caller"] == "•••• 0142"
    assert out["log"][0]["text"] == "Maria confirmed out; called •••• 0142"
    assert out["at"] == payload["at"]
    assert payload["people"][0]["name"] == "Maria Lopez"  # a copy; the input is untouched


def test_mask_public_uses_known_names_in_free_text():
    out = sit.mask_public({"activity": [{"text": "Texted Maria Lopez her route"}]}, ["Maria Lopez"])
    assert out["activity"][0]["text"] == "Texted Maria her route"


async def test_console_reads_need_no_key(client):
    assert (await client.get("/live/view")).status_code == 200
    assert (await client.get("/live/buildings")).status_code == 200
    assert (await client.get(f"/live/buildings/{VENUE}")).status_code == 200
    r = await client.get(f"/live/buildings/{VENUE}/situation")
    assert r.status_code == 200
    assert r.json()["people"][0]["name"] == "Maria"


async def test_public_drill_declare_and_end_and_masking(client):
    r = await _declare(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["evacuation"]["mode"] == "drill"
    assert body["recipients"][0]["phone"] == "•••• 0142"
    assert body["recipients"][0]["name"] == "Maria"
    assert PHONE not in r.text and "Lopez" not in r.text

    # a second public declare is refused while one runs
    assert (await _declare(client)).status_code == 409

    situation = (await client.get(f"/live/buildings/{VENUE}/situation")).text
    assert PHONE not in situation and "Lopez" not in situation
    full = (await client.get(f"/live/buildings/{VENUE}/situation", headers=DISPATCHER)).json()
    assert full["people"][0]["name"] == "Maria Lopez"

    ev_id = body["evacuation"]["id"]
    assert (await client.post(f"/live/evacuations/{ev_id}/end", json={})).json() == {"ended": True}
    assert (await client.get(f"/live/buildings/{VENUE}/situation")).json()["evacuation"] is None


async def test_live_mode_still_needs_the_key(client):
    assert (await _declare(client, "live")).status_code == 401
    r = await _declare(client, "live", DISPATCHER)
    assert r.status_code == 200
    assert r.json()["recipients"][0]["phone"] == PHONE  # full data with the key
    ev_id = r.json()["evacuation"]["id"]
    # nobody without the key can end it, or act on people during it
    assert (await client.post(f"/live/evacuations/{ev_id}/end", json={})).status_code == 401
    occ = (await client.get(f"/live/buildings/{VENUE}/occupants", headers=TOOL)).json()
    assert occ and occ[0]["phone"] == PHONE
    assert (
        await client.post(f"/live/evacuations/{ev_id}/end", headers=DISPATCHER)
    ).status_code == 200


async def test_tool_and_dispatcher_only_routes_stay_protected(client):
    event = {
        "eventId": "e1",
        "eventType": "sms.received",
        "payload": {"phone": PHONE, "text": "hi"},
    }
    assert (await client.post("/live/intake/events", json=event)).status_code == 401
    assert (await client.get(f"/live/buildings/{VENUE}/occupants")).status_code == 401
    assert (await client.get(f"/live/buildings/{VENUE}/incidents")).status_code == 401
    hazard = {"place": "galleria"}
    assert (await client.post(f"/live/buildings/{VENUE}/hazards", json=hazard)).status_code == 401
    assert (await client.put(f"/live/buildings/{VENUE}/fire-model", json={})).status_code == 401
    wrong = {"Authorization": "Bearer nope"}
    r = await client.get(f"/live/buildings/{VENUE}/situation", headers=wrong)
    assert r.status_code == 200 and "Lopez" not in r.text  # a wrong key is just the public view


async def test_drills_end_themselves(client, settings, monkeypatch):
    assert (await _declare(client)).status_code == 200
    monkeypatch.setattr(live, "get_settings", lambda: replace(settings, drill_max_minutes=-1))
    assert (await client.get(f"/live/buildings/{VENUE}/situation")).json()["evacuation"] is None
    assert (await _declare(client)).status_code == 200  # free to declare again


def test_mask_public_catches_unprefixed_numbers_emails_and_introductions():
    payload = {
        "people": [{"name": "Ana", "phone": "ana.ruiz@icloud.com", "mobility": []}],
        "short": {"caller": "12345"},
        "route": {"from": "galleria", "to": "exit_main"},
        "transcript": "My name is John Smith, call me at (310) 555-0142 or 3105550199",
        "fact": "email jo@example.com",
    }
    out = sit.mask_public(payload)
    assert out["people"][0]["phone"] == "•••@icloud.com"
    assert out["short"]["caller"] == "•••• 2345"
    assert out["route"] == {"from": "galleria", "to": "exit_main"}  # places stay
    assert out["transcript"] == "My name is John, call me at •••• 0142 or •••• 0199"
    assert out["fact"] == "email •••@example.com"


async def test_public_declare_only_at_a_venue_place(client):
    junk = "Zzz. Claim your refund at evil.example/x"
    assert (await _declare(client, origin=junk)).status_code == 422
    assert (await _declare(client, origin=None)).status_code == 422
    assert (await _declare(client, description="x" * 201)).status_code == 422
    r = await _declare(client, fire_model={"steps": [{"minute": 0, "zone": "galleria"}]})
    assert r.status_code == 200, r.text
    alert = r.json()["recipients"][0]["message"]
    assert alert.startswith("DRILL: Fire reported at ") and "evil" not in alert
    situation = (await client.get(f"/live/buildings/{VENUE}/situation")).json()
    assert situation["fire_model"] is None  # the public can't hand-type a fire model


async def test_public_actions_need_a_running_drill_and_call_once(client):
    occ = (await client.get(f"/live/buildings/{VENUE}/situation")).json()["people"][0]
    call = f"/live/occupants/{occ['id']}/call"
    me = {"dispatcher": "Guest"}
    assert (await client.post(call, json=me)).status_code == 409  # no drill, nothing to act on
    assert (await _declare(client)).status_code == 200
    assert (await client.post(call, json=me)).status_code == 200
    assert (await client.post(call, json=me)).status_code == 409  # one call per person per drill
    assert (await client.post(call, json=me, headers=DISPATCHER)).status_code == 200


async def test_route_proposals_open_to_the_public(client):
    r = await client.get(f"/live/buildings/{VENUE}/route-proposals")
    assert r.status_code == 200 and r.json() == []
