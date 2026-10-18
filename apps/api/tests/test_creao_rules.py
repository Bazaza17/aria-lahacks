"""The rules that decide what a reply to the fire alert means. No network or database."""

import pytest

from app.creao import rules


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("1", "evacuating"),
        ("1.", "evacuating"),
        ("2", "directions"),
        ("2 please", "directions"),
        ("HELP", "help"),
        ("help my friend fell", "help"),
        ("SAFE", "safe"),
        ("I'm outside now", "safe"),
        ("which way do I go?", "directions"),
        ("im lost", "directions"),
        ("I can get out", "evacuating"),
        ("CALL", "call"),
        ("is the elevator ok to use?", None),
        ("", None),
    ],
)
def test_reply_intent(text: str, intent: str | None) -> None:
    assert rules.reply_intent(text) == intent


@pytest.mark.parametrize(
    ("text", "word"),
    [
        ("I'm trapped in the restroom", "trapped"),
        ("there's smoke and I can't breathe", "can't breathe"),
        ("my friend is unconscious", "unconscious"),
        ("heading to the main entrance", None),
    ],
)
def test_trigger_word(text: str, word: str | None) -> None:
    assert rules.trigger_word(text) == word


def test_alert_asks_the_question() -> None:
    q = rules.ALERT_QUESTION
    assert "1" in q and "2" in q and "HELP" in q and "evacuate" in q


@pytest.mark.parametrize(
    ("text", "zone"),
    [
        (
            "Hi I’m in the Collin’s room right now",
            "collins_room",
        ),  # curly apostrophes, from a real phone
        ("hi, in the collins room", "collins_room"),
        ("I'm in the Founder's room", "founders_room"),
    ],
)
def test_text_names_a_room(text: str, zone: str) -> None:
    from app.creao.buildings import get_building
    from app.creao.location import match_place

    jw = get_building("547b5ec5-30c5-4f76-8080-012a52e90bd9")
    assert match_place(jw, text, kinds=("zone",)) == ("zone", zone)


@pytest.mark.parametrize("configured", ["e5a3fddc-e22c-431c-a5d3-ee29ef8604d1", None, ""])
def test_console_opens_on_the_venue(monkeypatch, configured) -> None:
    """An old .env naming The Dock (removed) or nothing at all still opens James West."""
    from types import SimpleNamespace

    from app.creao import buildings

    monkeypatch.setattr(
        buildings, "get_settings", lambda: SimpleNamespace(default_building_id=configured)
    )
    assert buildings.default_building().name == "James West Alumni Center"
    assert [b.name for b in buildings.all_buildings().values()] == ["James West Alumni Center"]


def test_listen_dsn_uses_sslmode(monkeypatch) -> None:
    """Tiger Cloud URLs carry ?ssl=require (SQLAlchemy); the raw asyncpg LISTEN needs sslmode."""
    import asyncio

    from sqlalchemy.engine import make_url

    from app.creao import hub

    url = make_url("postgresql+asyncpg://u:p@db.example.com:5432/tsdb?ssl=require")
    monkeypatch.setattr(hub, "engine", lambda: type("E", (), {"url": url})())
    seen = {}

    async def fake_listen(dsn):
        seen["dsn"] = dsn

    monkeypatch.setattr(hub, "_listen_forever", fake_listen)

    async def run():
        await hub.start()
        await hub._listener

    asyncio.run(run())
    assert seen["dsn"] == "postgresql://u:p@db.example.com:5432/tsdb?sslmode=require"
