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
        ("Hi I’m in the Collin’s room right now", "collins_room"),  # curly apostrophes, from a real phone
        ("hi, in the collins room", "collins_room"),
        ("I'm in the Founder's room", "founders_room"),
    ],
)
def test_text_names_a_room(text: str, zone: str) -> None:
    from app.creao.buildings import get_building
    from app.creao.location import match_place

    jw = get_building("547b5ec5-30c5-4f76-8080-012a52e90bd9")
    assert match_place(jw, text, kinds=("zone",)) == ("zone", zone)
