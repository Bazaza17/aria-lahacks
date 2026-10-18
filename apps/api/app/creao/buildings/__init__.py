"""Building profiles: floors, named zones and exits, in Aria's scan coordinates.

One JSON file per building here. james_west.json is the venue (James West Alumni Center), the
only building, and it is GENERATED from the engine's venue model (packages/engine/venue.json) by
scripts/build_profile.py: zones are venue spaces, exits are every venue exit plus the stairs down
from floor 2. Anchors are normalized in 'frame' (the venue frame, metres), which view.html maps
back onto the scan. A default building id that names no profile here falls back to the first one.

People and incidents are only ever placed at these named zones and exits (or GPS). Nothing is
invented: anything else falls back to the floor or building, marked approximate.
"""

import json
import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from app.creao.config import get_settings


class Anchor(BaseModel):
    nx: float
    ny: float
    nz: float


class Floor(BaseModel):
    level: int
    label: str
    ny: float
    source: str | None = None  # what the floor's geometry comes from (scan / floor plan)
    anchor: Anchor | None = None  # "somewhere on this floor": the middle of its indoor rooms
    aliases: list[str] = []  # words for the floor that name no single room ("upstairs")


class Zone(BaseModel):
    id: str
    label: str
    floor: int = 1
    anchor: Anchor
    # For drawing: [width, depth] as fractions of the building, or the room's shape as [nx, nz] points
    size: list[float] | None = None
    outline: list[list[float]] | None = None
    outdoor: bool = False  # a patio or courtyard
    spaces: list[str] = []  # the venue spaces (packages/engine/venue.json) this zone covers
    aliases: list[str] = []
    event_name: str | None = None  # the LA Hacks event map's name for it
    occupants: int = 0  # venue.json occupant_load (its default scenario)
    source: str | None = None  # "scan" or "floor plan"


class Exit(BaseModel):
    id: str
    label: str
    anchor: Anchor
    zone: str | None = None
    assembly: bool = False
    opening: str | None = None  # the venue opening (door or stair) it is
    openings: list[str] = []  # every venue opening it stands for (a stair with two flights)
    kind: str = "door"  # "door" (out of the building) or "stair" (a way down from floor 2)
    floor: int | None = None
    exterior: bool = True  # a venue exit (is_exit); False for the inside stairs down
    note: str | None = None
    aliases: list[str] = []


class Geo(BaseModel):
    bearing_deg: float = 0
    width_m: float = 30
    depth_m: float = 30
    height_m: float = 10


class Building(BaseModel):
    id: str
    name: str
    address: str
    lat: float
    lng: float
    scan_url: str | None = None
    lines: list[str] = Field(default_factory=list)  # Photon numbers (E.164) that serve it
    geo: Geo = Geo()
    # The frame anchors are normalized in (metres, the venue/scan frame), and where each scan file
    # sits in it (offset, rotation), so the live markers land on the scan as-is
    frame: dict | None = None
    scans: list[dict] = []
    floors: list[Floor] = [Floor(level=1, label="Ground floor", ny=0.05)]
    zones: list[Zone] = []
    exits: list[Exit] = []
    assembly_exit_id: str | None = None
    # Where people go once out. No assembly point is confirmed for the venue, so it's words only
    assembly: str = "outside, away from the building, where staff direct you"
    generated_at: str | None = None
    occupant_scenario: str | None = None
    venue_schema_version: str | None = None

    def exit_for_opening(self, opening: str | None) -> Exit | None:
        return next(
            (e for e in self.exits if opening and (opening == e.opening or opening in e.openings)),
            None,
        )

    def zone(self, zone_id: str | None) -> Zone | None:
        return next((z for z in self.zones if z.id == zone_id), None)

    def exit(self, exit_id: str | None) -> Exit | None:
        return next((e for e in self.exits if e.id == exit_id), None)

    def floor(self, level: int | None) -> Floor | None:
        return next((f for f in self.floors if f.level == level), None)


@lru_cache
def all_buildings() -> dict[str, Building]:
    out = {}
    for path in sorted(Path(__file__).parent.glob("*.json")):
        data = {
            k: v
            for k, v in json.loads(path.read_text(encoding="utf-8")).items()
            if not k.startswith("_")
        }
        b = Building.model_validate(data)
        out[b.id] = b
    return out


def get_building(building_id: str | None) -> Building | None:
    return all_buildings().get(building_id) if building_id else None


def default_building() -> Building | None:
    buildings = all_buildings()
    preferred = get_settings().default_building_id
    # an id from an old .env (e.g. The Dock's) must not leave the console on a blank building
    return buildings.get(preferred or "") or next(iter(buildings.values()), None)


def _digits(number: str) -> str:
    return re.sub(r"\D", "", number)[-10:]


def building_for_line(number: str | None) -> Building | None:
    """The building a Photon line serves; else the default building."""
    if number:
        for b in all_buildings().values():
            if any(_digits(number) == _digits(line) for line in b.lines):
                return b
    return default_building()
