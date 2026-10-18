"""Building graph: rooms are nodes, doors/openings are edges. Loaded from JSON."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from engine.constants import DEFAULT_DOOR_HEIGHT_M, FUEL_CLASSES

OUTSIDE = "outside"
SAMPLE_VENUE = Path(__file__).parent / "data" / "james_west_sample.json"


@dataclass(frozen=True)
class Room:
    id: str
    name: str
    floor: int
    area_m2: float
    ceiling_height_m: float
    fuel_class: str
    kind: str = "room"  # "room" or "stair" (a shaft spanning several floors)
    perimeter_m: float | None = None  # defaults to a square room's perimeter
    window_area_m2: float = 0.0  # glazing assumed to fail and vent once the fire grows
    window_height_m: float = 1.5
    floors_served: tuple[int, ...] = ()  # stairs only
    # (x_min, x_max, z_min, z_max) in the scan's frame (see Venue.scan); None if not traced
    footprint: tuple[float, float, float, float] | None = None

    @property
    def perimeter(self) -> float:
        if self.perimeter_m:
            return self.perimeter_m
        if self.footprint:
            x0, x1, z0, z1 = self.footprint
            return 2.0 * ((x1 - x0) + (z1 - z0))
        return 4.0 * math.sqrt(self.area_m2)


@dataclass(frozen=True)
class Door:
    id: str
    a: str  # room id
    b: str  # room id or "outside"
    floor: int  # floor the door sits on (matters for stairs)
    width_m: float
    open: bool
    fire_rating_min: float = 0.0
    height_m: float = DEFAULT_DOOR_HEIGHT_M
    name: str = ""
    position: tuple[float, float] | None = None  # (x, z) in the scan's frame

    def other(self, room_id: str) -> str:
        return self.b if room_id == self.a else self.a


@dataclass(frozen=True)
class Exit:
    id: str
    label: str
    door: str
    accessible: bool


@dataclass
class Venue:
    name: str
    verified: bool
    floor_elevations_m: dict[int, float]
    rooms: dict[str, Room]
    doors: dict[str, Door]
    exits: list[Exit]
    refuge_areas: list[dict] = field(default_factory=list)
    assembly_point: str = ""
    notes: list[str] = field(default_factory=list)
    scan: dict = field(default_factory=dict)  # which mesh the footprints are traced on

    def doors_of(self, room_id: str) -> list[Door]:
        return [d for d in self.doors.values() if room_id in (d.a, d.b)]

    def elevation(self, floor: int) -> float:
        return self.floor_elevations_m[floor]


def load_venue(path: str | Path = SAMPLE_VENUE) -> Venue:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    floors = {int(f["level"]): float(f["elevation_m"]) for f in raw["floors"]}
    rooms = {}
    for r in raw["rooms"]:
        footprint = None
        if "footprint" in r:
            (x0, x1), (z0, z1) = sorted(r["footprint"]["x"]), sorted(r["footprint"]["z"])
            footprint = (float(x0), float(x1), float(z0), float(z1))
        if "area_m2" in r:
            area = float(r["area_m2"])
        elif footprint:
            area = (footprint[1] - footprint[0]) * (footprint[3] - footprint[2])
        else:
            raise ValueError(f"room {r['id']}: needs area_m2 or a footprint")
        room = Room(
            id=r["id"],
            name=r["name"],
            floor=int(r["floor"]),
            area_m2=area,
            ceiling_height_m=float(r["ceiling_height_m"]),
            fuel_class=r["fuel_class"],
            kind=r.get("kind", "room"),
            perimeter_m=r.get("perimeter_m"),
            window_area_m2=float(r.get("window_area_m2", 0.0)),
            window_height_m=float(r.get("window_height_m", 1.5)),
            floors_served=tuple(r.get("floors_served", ())),
            footprint=footprint,
        )
        if room.fuel_class not in FUEL_CLASSES:
            raise ValueError(f"room {room.id}: unknown fuel_class {room.fuel_class!r}")
        rooms[room.id] = room
    doors = {}
    for d in raw["doors"]:
        door = Door(
            id=d["id"],
            a=d["a"],
            b=d["b"],
            floor=int(d.get("floor", rooms[d["a"]].floor)),
            width_m=float(d["width_m"]),
            open=bool(d["open"]),
            fire_rating_min=float(d.get("fire_rating_min", 0.0)),
            height_m=float(d.get("height_m", DEFAULT_DOOR_HEIGHT_M)),
            name=d.get("name", ""),
            position=(float(d["position"]["x"]), float(d["position"]["z"]))
            if "position" in d
            else None,
        )
        for side in (door.a, door.b):
            if side != OUTSIDE and side not in rooms:
                raise ValueError(f"door {door.id}: unknown room {side!r}")
        doors[door.id] = door
    clash = set(rooms) & set(doors)
    if clash:
        raise ValueError(f"ids used for both a room and a door: {sorted(clash)}")
    exits = [
        Exit(id=e["id"], label=e["label"], door=e["door"], accessible=e.get("accessible", True))
        for e in raw.get("exits", [])
    ]
    for e in exits:
        if e.door not in doors:
            raise ValueError(f"exit {e.id}: unknown door {e.door!r}")
    return Venue(
        name=raw["name"],
        verified=bool(raw.get("verified", False)),
        floor_elevations_m=floors,
        rooms=rooms,
        doors=doors,
        exits=exits,
        refuge_areas=raw.get("refuge_areas", []),
        assembly_point=raw.get("assembly_point", ""),
        notes=raw.get("notes", []),
        scan=raw.get("scan", {}),
    )
