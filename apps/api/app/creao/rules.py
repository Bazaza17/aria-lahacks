"""Deterministic rules run on every caller line and text: microseconds, no network.

- risk(): severity of what someone said (a life threat is critical; fire, smoke, injury high)
- hazard_hits(): hazards worth pinning on the map when the text also names a place
- LIFE_THREAT: words that put a human dispatcher on the line
- STATUS_WORDS: replies to the alert (SAFE / HELP / CALL) and pipeline statuses
- reply_intent(): what a reply to the fire alert means (1 leaving, 2 needs help finding an exit,
  HELP hurt or trapped, SAFE out), including the plain-English versions
"""

import re

from app.creao.models import OccupantStatus, Severity

RANK = {Severity.low: 1, Severity.medium: 2, Severity.high: 3, Severity.critical: 4}
PRIORITY = {Severity.critical: "P1", Severity.high: "P2", Severity.medium: "P3", Severity.low: "P4"}

LIFE_THREAT = re.compile(
    r"\b(trapped|stuck|can'?t get out|can'?t breathe|cannot breathe|passing out|pass(?:ed)? out|unconscious|"
    r"not breathing|on fire|burn(?:ed|ing|s)|collapsed|can'?t move)\b",
    re.I,
)

_RULES: list[tuple[str, Severity, re.Pattern]] = [
    ("life_threat", Severity.critical, LIFE_THREAT),
    (
        "violence",
        Severity.critical,
        re.compile(r"\b(gun|knife|weapon|shot|stabbed|shooting|hostage)\b", re.I),
    ),
    (
        "fire_hazard",
        Severity.high,
        re.compile(r"\b(fire|smoke|flames?|burning|gas leak|smell (?:of )?gas|explosion)\b", re.I),
    ),
    (
        "injury",
        Severity.high,
        re.compile(r"\b(injur(?:ed|y|ies)|hurt|bleeding|broken (?:arm|leg|bone)|fell)\b", re.I),
    ),
    (
        "blocked",
        Severity.high,
        re.compile(
            r"\b(blocked|jammed|locked|stuck shut|won'?t open|can'?t open|obstructed)\b", re.I
        ),
    ),
    (
        "needs_help",
        Severity.high,
        re.compile(r"\b(help me|need help|wheelchair|can'?t walk)\b", re.I),
    ),
]
HAZARD_CATEGORIES = {
    "fire_hazard": "fire / smoke",
    "blocked": "blocked",
    "violence": "weapon / violence",
}

STATUS_WORDS = {
    "safe": OccupantStatus.confirmed_safe,
    "out": OccupantStatus.confirmed_safe,
    "confirmed_safe": OccupantStatus.confirmed_safe,
    "en_route": OccupantStatus.contacted,
    "leaving": OccupantStatus.contacted,
    "evacuating": OccupantStatus.contacted,
    "contacted": OccupantStatus.contacted,
    "call": OccupantStatus.contacted,
    "help": OccupantStatus.needs_help,
    "needs_help": OccupantStatus.needs_help,
    "unconfirmed": OccupantStatus.unconfirmed,
}


def risk(text: str | None) -> list[tuple[str, Severity, str]]:
    """(category, severity, matched words) for every rule the text trips."""
    if not text:
        return []
    return [(cat, sev, m.group(0)) for cat, sev, rx in _RULES if (m := rx.search(text))]


def top_severity(*severities: Severity | None) -> Severity:
    return max((s for s in severities if s), key=lambda s: RANK[s], default=Severity.low)


def hazard_hits(text: str | None) -> list[tuple[str, str]]:
    """(category, matched words) for hazards in the text."""
    return [(cat, words) for cat, _sev, words in risk(text) if cat in HAZARD_CATEGORIES]


# The fire alert asks one question; these are the answers it understands.
ALERT_QUESTION = (
    "Are you able to evacuate on your own? Reply 1 if you're leaving now, 2 if you need help finding "
    "an exit, or HELP if you're hurt or trapped."
)
_CODES = {
    "1": "evacuating",
    "2": "directions",
    "safe": "safe",
    "out": "safe",
    "help": "help",
    "call": "call",
}
_DIRECTIONS = re.compile(
    r"\b(which way|where (?:do|should|can) i go|how do i get out|can'?t find (?:an? |the )?(?:exit|way out)|"
    r"help (?:me )?find|need directions|i'?m lost|we'?re lost|show me the way|need help finding)\b",
    re.I,
)
_EVACUATING = re.compile(
    r"\b(leaving now|heading out|on my way out|evacuating|getting out|i can (?:get out|leave|evacuate)|yes,? i can)\b",
    re.I,
)
_OUT = re.compile(r"\b(i'?m|we'?re|i am|we are) (?:out|outside|safe)\b", re.I)


def reply_intent(text: str | None) -> str | None:
    """evacuating | directions | help | safe | call, or None for anything else (the agent answers)."""
    if not text or not text.strip():
        return None
    first = text.strip().split()[0].strip(".,!:?").lower()
    if first in _CODES:
        return _CODES[first]
    if _DIRECTIONS.search(text):
        return "directions"
    if _OUT.search(text):
        return "safe"
    if _EVACUATING.search(text):
        return "evacuating"
    return None


def trigger_word(text: str | None) -> str | None:
    """The life-threat words that move a call or thread to a human dispatcher."""
    m = LIFE_THREAT.search(text or "")
    return m.group(0).lower() if m else None
