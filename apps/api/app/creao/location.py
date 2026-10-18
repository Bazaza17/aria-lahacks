"""Turn what people say (or their phone's GPS) into a position on the building scan.

Text: match against the building profile's zone and exit names and aliases, so "I'm by the
loading dock" lands on the loading dock. Only named places count: if nothing matches, the
position falls back to the floor or building centre and is flagged approximate (the map draws
it as such), rather than guessed.

GPS: project lat/lng onto the building footprint (Geo in the profile). Indoors GPS is coarse,
so anything worse than 15 m accuracy is flagged approximate.
"""

import math
import re
from dataclasses import dataclass

from app.creao.buildings import Anchor, Building

ORDINALS = {
    "ground": 1,
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
    "basement": 0,
    "lobby": 1,
}
FLOOR_PATTERNS = [
    re.compile(r"\b(?:floor|level|fl\.?)\s*(\d{1,2})\b", re.I),
    re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s*(?:floor|level|fl)\b", re.I),
    re.compile(
        r"\b(ground|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|basement|lobby)\s*(?:floor|level)?\b",
        re.I,
    ),
]
# A floor said in so many words ("second floor", "level 2", "2nd fl"); a bare "second" or
# "lobby" is not one, so "give me a second" never moves anyone off their room.
EXPLICIT_FLOOR = [
    *FLOOR_PATTERNS[:2],
    re.compile(
        r"\b(ground|first|second|third|fourth|fifth|basement)\s*(?:floor|level|story|storey)\b",
        re.I,
    ),
]
# Floor words that say where, not what: these override a generic place on another floor.
POSITION_WORDS = {2: ("upstairs", "up stairs")}
GPS_APPROX_M = 15


@dataclass
class Location:
    anchor: Anchor
    label: str
    source: str  # zone | exit | floor | building | gps
    approx: bool
    floor: int | None = None
    zone_id: str | None = None
    exit_id: str | None = None
    lat: float | None = None
    lng: float | None = None

    def as_dict(self) -> dict:
        return {
            "anchor": self.anchor.model_dump(),
            "label": self.label,
            "source": self.source,
            "approx": self.approx,
            "floor": self.floor,
            "zone_id": self.zone_id,
            "exit_id": self.exit_id,
            "lat": self.lat,
            "lng": self.lng,
        }


def parse_floor(text: str | None) -> int | None:
    if not text:
        return None
    for pattern in FLOOR_PATTERNS:
        if m := pattern.search(text):
            value = m.group(1).lower()
            return ORDINALS[value] if value in ORDINALS else int(value)
    return None


def _norm(text: str) -> str:
    # drop apostrophes first (phones send curly ones), so "Collin’s room" matches "collins room"
    text = re.sub(r"['’‘`]", "", text.lower())
    return " " + re.sub(r"[^a-z0-9]+", " ", text).strip() + " "


def match_place(
    building: Building, text: str | None, kinds: tuple[str, ...] = ("exit", "zone")
) -> tuple[str, str] | None:
    """Best named place in text: ("exit"|"zone", id). Longest alias wins; exits beat zones on ties."""
    if not text:
        return None
    hay = _norm(text)
    best: tuple[int, int, str, str] | None = None
    groups = {"exit": (building.exits, 1), "zone": (building.zones, 0)}
    for kind, (items, rank) in ((k, groups[k]) for k in kinds):
        for item in items:
            for name in [item.label, item.id.replace("_", " "), *item.aliases]:
                needle = _norm(name)
                if len(needle.strip()) >= 3 and needle in hay:
                    score = (len(needle), rank)
                    if best is None or score > best[:2]:
                        best = (*score, kind, item.id)
    return (best[2], best[3]) if best else None


def match_exit(building: Building, text: str | None) -> str | None:
    """Exit by id or by name/alias in free text."""
    if not text:
        return None
    if building.exit(text.strip()):
        return text.strip()
    if place := match_place(building, text, kinds=("exit",)):
        return place[1]
    # "the loading dock area" names a zone that belongs to an exit
    if place := match_place(building, text, kinds=("zone",)):
        return next((e.id for e in building.exits if e.zone == place[1]), None)
    return None


def _floor_anchor(building: Building, floor: int | None) -> tuple[Anchor, str]:
    f = building.floor(floor) or building.floors[0]
    if f.anchor:  # the middle of the floor's indoor rooms (from the venue model)
        return f.anchor.model_copy(), f.label
    return Anchor(nx=0.5, ny=f.ny, nz=0.5), f.label


def floor_alias(building: Building, text: str | None) -> int | None:
    """A floor named by a word that names no single room: "upstairs", "at the workshops"."""
    if not text:
        return None
    hay = _norm(text)
    for f in building.floors:
        if any(_norm(a) in hay for a in f.aliases if len(a.strip()) >= 3):
            return f.level
    return None


def explicit_floor(text: str | None) -> int | None:
    """A floor the text states outright ("second floor", "upstairs"), or None."""
    if not text:
        return None
    for pattern in EXPLICIT_FLOOR:
        if m := pattern.search(text):
            value = m.group(1).lower()
            return ORDINALS[value] if value in ORDINALS else int(value)
    hay = _norm(text)
    for level, words in POSITION_WORDS.items():
        if any(_norm(w) in hay for w in words):
            return level
    return None


def from_text(
    building: Building, text: str | None, floor_hint: int | str | None = None
) -> Location:
    if isinstance(floor_hint, str) and floor_hint.strip().isdigit():
        floor_hint = int(floor_hint.strip())  # agents send "2" as often as 2
    floor = (
        floor_hint
        if isinstance(floor_hint, int)
        else parse_floor(str(floor_hint) if floor_hint else None)
    )
    # only a floor said outright counts: a bare "second" ("give me a second") is not one
    floor = floor if floor is not None else explicit_floor(text)
    place = match_place(building, text)
    if floor is None and place is None:
        floor = floor_alias(building, text)
    if place:
        kind, place_id = place
        item = building.exit(place_id) if kind == "exit" else building.zone(place_id)
        anchor = item.anchor.model_copy()
        item_floor = getattr(item, "floor", None)
        stated = floor  # the hint, or a floor the text says outright
        is_stair = kind == "exit" and getattr(item, "kind", None) == "stair"
        if (
            stated is not None
            and item_floor is not None
            and stated != item_floor
            and not is_stair
            and building.floor(stated)
        ):
            # "second floor hallway", "upstairs bathroom": the floor is what they know, the
            # place name matched a room on another floor. Keep the floor, drop the room, so the
            # unknown-position route sends that floor's stairs.
            anchor, label = _floor_anchor(building, stated)
            return Location(anchor=anchor, label=label, source="floor", approx=True, floor=stated)
        if floor is not None and (f := building.floor(floor)) and floor != item_floor:
            anchor.ny = f.ny  # same spot on another floor (e.g. "stairwell B, floor 3")
        return Location(
            anchor=anchor,
            label=item.label + (f", floor {floor}" if floor and len(building.floors) > 1 else ""),
            source=kind,
            approx=False,
            floor=floor if floor is not None else item_floor,
            zone_id=place_id if kind == "zone" else item.zone,
            exit_id=place_id if kind == "exit" else None,
        )
    if floor is not None and building.floor(floor):
        anchor, label = _floor_anchor(building, floor)
        return Location(anchor=anchor, label=label, source="floor", approx=True, floor=floor)
    anchor, _ = _floor_anchor(building, None)
    return Location(anchor=anchor, label=building.name, source="building", approx=True)


def from_gps(
    building: Building,
    lat: float,
    lng: float,
    accuracy_m: float | None = None,
    floor: int | None = None,
) -> Location:
    north_m = (lat - building.lat) * 111_320
    east_m = (lng - building.lng) * 111_320 * math.cos(math.radians(building.lat))
    # Rotate into the scan's axes (x = across, z = depth).
    theta = math.radians(building.geo.bearing_deg)
    x_m = east_m * math.cos(theta) + north_m * math.sin(theta)
    z_m = -north_m * math.cos(theta) + east_m * math.sin(theta)
    nx = min(1.0, max(0.0, 0.5 + x_m / building.geo.width_m))
    nz = min(1.0, max(0.0, 0.5 + z_m / building.geo.depth_m))
    f = building.floor(floor) or building.floors[0]
    outside = abs(x_m) > building.geo.width_m / 2 or abs(z_m) > building.geo.depth_m / 2
    return Location(
        anchor=Anchor(nx=nx, ny=f.ny, nz=nz),
        label="Outside the building" if outside else f"GPS position, {f.label.lower()}",
        source="gps",
        approx=accuracy_m is None or accuracy_m > GPS_APPROX_M,
        floor=f.level,
        lat=lat,
        lng=lng,
    )


def better(current: dict | None, new: Location) -> bool:
    """Only replace a known position with an equally or more precise one."""
    if not current:
        return True
    rank = {"building": 0, "floor": 1, "gps": 2, "zone": 3, "exit": 3}
    if current.get("approx") and not new.approx:
        return True
    return rank.get(new.source, 0) >= rank.get(current.get("source"), 0)
