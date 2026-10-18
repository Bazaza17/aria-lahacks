"""Regenerate the live layer's building profile from the engine's venue model.

    cd apps/api && uv run python scripts/build_profile.py

packages/engine/venue.json is the one venue model. This writes
app/creao/buildings/james_west.json from it: zones are venue spaces (grouped where the event map
names them together), exits are EVERY exterior exit in venue.json (is_exit) plus the tops of the
stairs down from the 2nd floor, and anchors are the spaces' and openings' own positions in the
venue frame, normalized the way view.html's world() reads them back. Nothing here is invented:
labels, aliases and occupant numbers come from venue.json (2F_indoor, its default scenario) and
the LA Hacks event map's names. Floor 2 and up come from the floor plan, not the scan.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
VENUE_JSON = ROOT / "packages" / "engine" / "venue.json"
OUT = Path(__file__).resolve().parents[1] / "app" / "creao" / "buildings" / "james_west.json"
sys.path.insert(0, str(ROOT / "packages" / "engine"))

from engine.geometry import centroid, inside, representative_point, shoelace  # noqa: E402

# The venue frame (metres: room 2's scan x, z; elevation 0 = lobby 110's floor), as the console
# draws it: x = x0 + nx * (x1 - x0), z = z1 - nz * (z1 - z0) (flip_z), elevation = y0 + ny * (y1 - y0)
FRAME = {"x0": -30.0, "x1": 53.0, "z0": -35.0, "z1": 31.0, "y0": -1.0, "y1": 12.0, "flip_z": True}
SCAN_URL = (
    "https://sntyqjzoyjfgrjesguvs.supabase.co/storage/v1/object/public/scans/"
    "james_west/venue_4rooms_web.glb"
)
SCANS = [
    {
        "file": "venue_4rooms_web.glb",
        "x": 0,
        "y": 3.91,
        "z": 0,
        "rotate_y_deg": 0,
        "note": "Lincoln's four-room scan, already in the venue frame; elevation = Y + 3.91.",
    },
    {
        "file": "venue/scan.glb",
        "x": 11.26,
        "y": 0.78,
        "z": -13.13,
        "rotate_y_deg": -94.59,
        "note": "The first single-room scan (room 1); venue.json frame.scan_transforms.room1.",
    },
]
ASSEMBLY = "outside, away from the building, where staff direct you"
STOREY_LEVEL = {"1F": 1, "2F": 2, "3F": 2}  # the tower's 3F room (330) counts with floor 2
FLOOR_LABEL = {1: "Floor 1", 2: "Floor 2 (floor plan)"}
FLOOR_SOURCE = {
    1: "LiDAR scan (Galleria, Founders' Room, Collins Room) and the floor plan",
    2: "the floor plan only (not scanned; elevation 5 m is a placeholder)",
}
# Words for "somewhere upstairs" that name no single room. The event's Networking and Workshops
# were upstairs indoors (venue.json 2F_indoor), but which 2F room held which isn't recorded.
FLOOR_ALIASES = {
    2: [
        "upstairs",
        "up stairs",
        "networking",
        "workshops",
        "workshop",
        "workshop area",
        "northeast patio",
        "ne patio",
        "room 210",
        "in 210",
    ]
}

# Zones: (id, label, event name, venue spaces, aliases). Spaces not listed join the zone of the
# neighbour they open onto (closets, small offices); elevators and skylight wells join none.
GROUPS = [
    # Floor 1, indoors
    (
        "galleria",
        "Galleria (sponsors)",
        "Galleria",
        ["110", "corridor_core"],
        ["galleria", "sponsors", "sponsor booths", "sponsor area", "sponsor tables", "hallway"],
    ),
    (
        "galleria_far_end",
        "Galleria far end (back)",
        "Galleria",
        ["galleria_far_end"],
        [
            "back of the galleria",
            "back of galleria",
            "by the curved stairs",
            "south lobby",
            "back lobby",
            "by the back doors",
        ],
    ),
    (
        "restrooms",
        "Restrooms",
        "Restrooms",
        ["121", "131"],
        ["restrooms", "restroom", "bathroom", "bathrooms", "toilets"],
    ),
    (
        "collins_room",
        "Collins Room",
        "Collins Conference Room",
        ["140", "150"],
        ["collins room", "collins", "main hacking room"],
    ),
    (
        "founders_room",
        "Founders' Room",
        "Founders' Room",
        ["120"],
        ["founders room", "founders", "founder's room"],
    ),
    (
        "offices_100",
        "Office suite 100",
        None,
        ["100", "100G"],
        ["office suite", "offices", "room 100", "bottom of the ne stairs"],
    ),
    (
        "rooms_130",
        "Rooms 130 (round tower)",
        None,
        ["130C", "130A", "130E", "130D", "vestibule_130d_north"],
        ["round tower", "room 130", "130c", "fire alarm control panel"],
    ),
    ("room_170", "Room 170", None, ["170"], ["room 170"]),
    ("room_180", "Room 180", None, ["180"], ["room 180"]),
    ("room_190", "Room 190", None, ["190"], ["room 190"]),
    ("room_192", "Room 192", None, ["192"], ["room 192"]),
    ("room_126", "Room 126", None, ["126"], ["room 126", "room 128"]),
    # Floor 1, outdoors
    (
        "entrance",
        "Entrance & Check-in (covered entry)",
        "Entrance & Check-in",
        ["entry_plaza"],
        [
            "entrance",
            "check-in",
            "check in",
            "front entrance",
            "main entrance area",
            "registration",
        ],
    ),
    (
        "founders_patio",
        "Founders' Patio",
        "Founders' Patio",
        ["courtyard_north", "courtyard_north_lawn"],
        ["founders patio", "founder's patio"],
    ),
    (
        "collins_patio",
        "Collins Patio",
        "Collins Patio",
        ["courtyard_sw_north", "courtyard_sw_south"],
        ["collins patio", "food", "food area", "food tables", "by the food"],
    ),
    (
        "outside_stairs_foot",
        "Foot of the outside stairs",
        None,
        ["w_stair_enclosure"],
        ["bottom of the outside stairs", "foot of the outside stairs", "stair enclosure"],
    ),
    (
        "south_porch",
        "South porch (outside the back doors)",
        None,
        ["south_porch"],
        ["south porch", "porch"],
    ),
    ("patio_se", "Patio by rooms 170 and 192", None, ["patio_se"], ["patio by 170"]),
    ("nw_walkway", "Walkway by the round tower", None, ["nw_walkway"], ["walkway"]),
    ("service_yard", "Service yard by room 190", None, ["service_yard_se"], ["service yard"]),
    # Floor 2 (floor plan): the indoor rooms where the event's Networking and Workshops were
    ("room_210_n", "Room 210 north (2nd floor)", None, ["210_n"], ["210 north"]),
    ("room_210_w", "Room 210 west (2nd floor)", None, ["210_w"], ["210 west"]),
    (
        "room_210_sw",
        "Room 210 southwest (2nd floor)",
        None,
        ["210_sw"],
        ["210 southwest", "room 216"],
    ),
    ("room_219", "Room 219 (2nd floor)", None, ["219"], ["room 219", "219"]),
    ("room_210a", "Room 210A (2nd floor)", None, ["210A"], ["room 210a", "210a"]),
    (
        "room_200",
        "Room 200 (2nd floor, by the NE stairs)",
        None,
        ["200", "200A"],
        ["room 200", "200a"],
    ),
    (
        "tower_230",
        "Tower room 230 (2nd floor)",
        None,
        ["230", "330"],
        ["room 230", "tower room", "room 330"],
    ),
    (
        "terrace",
        "Terrace (2nd floor, outdoors)",
        None,
        ["terrace_landing", "230A", "terrace_upper_block"],
        ["terrace", "top of the outside stairs", "230a"],
    ),
]

# Exits: every venue exit (is_exit), by opening id: (id, label, aliases)
EXITS = {
    "D-110-OUT-1": (
        "main_entrance",
        "Main entrance (doors nearer the Founders' Room)",
        [
            "main entrance",
            "front door",
            "front doors",
            "entrance doors",
            "main doors",
            "check-in doors",
        ],
    ),
    "D-110-OUT-2": (
        "main_entrance_2",
        "Main entrance (doors nearer the office suite)",
        ["main entrance doors nearer the offices"],
    ),
    "D-galleria_far_end-OUT-1": (
        "galleria_back_doors",
        "Galleria back doors (to the south porch)",
        [
            "back doors",
            "back exit",
            "back door",
            "far end doors",
            "south doors",
            "porch doors",
            "galleria back doors",
            "rear doors",
        ],
    ),
    "D-galleria_far_end-OUT-2": (
        "galleria_back_doors_2",
        "Galleria back doors (second pair, to the south porch)",
        [],
    ),
    "D-120-OUT-2": (
        "founders_patio_doors",
        "Founders' Room patio doors",
        ["founders patio doors", "founders doors", "founder's patio doors"],
    ),
    "D-120-OUT-1": (
        "founders_corner_door",
        "Founders' Room corner door (by the arcade)",
        ["founders corner door"],
    ),
    "D-140-OUT": (
        "collins_patio_doors",
        "Collins Room patio doors",
        ["collins patio doors", "collins doors", "doors to the patio"],
    ),
    "D-150-OUT-1": (
        "collins_150_doors",
        "Collins Room doors to the food area",
        ["doors to the food area", "food area doors", "patio doors by the food"],
    ),
    "D-150-OUT-2": (
        "collins_corner_door",
        "Collins Room corner door (far wall)",
        ["collins corner door"],
    ),
    "D-170-OUT": ("room_170_doors", "Room 170 doors to the patio", ["170 doors"]),
    "D-192-OUT": ("room_192_door", "Room 192 door to the patio", ["192 door"]),
    "D-190-OUT": ("room_190_door", "Room 190 door to the service yard", ["190 door"]),
    "D-100-OUT": ("office_100_door", "Office suite 100 outside door", ["office door"]),
    "ST-W": (
        "outside_stairs",
        "Outside stairs down from the terrace",
        [
            "outside stairs",
            "exterior stairs",
            "exterior stair",
            "outdoor stair",
            "stairs to 2nd floor",
            "stairs to second floor",
            "west stairs",
        ],
    ),
}
# The other ways down from floor 2 (inside the building; venue.json: not protected)
STAIRS = [
    (
        "galleria_stair",
        ["ST-100"],
        "landing_200st",
        "Open stair down to the Galleria far end (indoors)",
        ["open stair", "galleria stair", "100st", "200st"],
        "inside the Galleria's skylight well, not enclosed: smoke in the Galleria reaches it",
    ),
    (
        "ne_stairs",
        ["ST-NE-2", "ST-NE-1"],
        "200",
        "NE stairs down to the lobby (from room 200)",
        ["ne stairs", "northeast stairs", "ne stair"],
        "two flights down to 100G, whose way out is one door into lobby 110; not known to be enclosed",
    ),
]
EXIT_NOTES = {
    "ST-W": "open-air exterior stair from the 2nd floor terrace; the 2nd floor's only way down "
    "that does not pass through the Galleria",
}


def norm(x: float, z: float, elevation: float) -> dict:
    f = FRAME
    return {
        "nx": round((x - f["x0"]) / (f["x1"] - f["x0"]), 4),
        "ny": round((elevation - f["y0"]) / (f["y1"] - f["y0"]), 4),
        "nz": round((f["z1"] - z) / (f["z1"] - f["z0"]), 4),
    }


def storey_elevation(venue: dict, storey: str) -> float:
    return next(s["elevation"] for s in venue["storeys"] if s["id"] == storey)


def zone_point(spaces: list[dict]) -> tuple[float, float]:
    """Area-weighted centre of the zone's spaces, kept inside one of them."""
    total = sum(abs(shoelace(s["polygon"])) for s in spaces) or 1.0
    cx = sum(centroid(s["polygon"])[0] * abs(shoelace(s["polygon"])) for s in spaces) / total
    cz = sum(centroid(s["polygon"])[1] * abs(shoelace(s["polygon"])) for s in spaces) / total
    if any(inside((cx, cz), s["polygon"]) for s in spaces):
        return cx, cz
    big = max(spaces, key=lambda s: abs(shoelace(s["polygon"])))
    return tuple(representative_point(big["polygon"]))


def assign_spaces(venue: dict) -> dict[str, str]:
    """Space id -> zone id: the listed groups, then leftovers join the neighbour they open onto."""
    skip = {"open_to_below", "elevator"}
    owner = {sid: g[0] for g in GROUPS for sid in g[3]}
    spaces = {s["id"]: s for s in venue["spaces"] if s["kind"] not in skip}
    load = {zid: 0 for zid in {g[0] for g in GROUPS}}
    for sid, zid in owner.items():
        load[zid] += spaces[sid].get("occupant_load") or 0
    pending = [sid for sid in spaces if sid not in owner]
    while pending:
        progress = False
        for sid in list(pending):
            near = [
                owner[o["b"] if o["a"] == sid else o["a"]]
                for o in venue["openings"]
                if sid in (o["a"], o["b"])
                and o["kind"] not in ("elevator", "stair")
                and (o["b"] if o["a"] == sid else o["a"]) in owner
            ]
            if near:
                owner[sid] = max(near, key=lambda z: load[z])
                pending.remove(sid)
                progress = True
        if not progress:
            raise SystemExit(f"spaces with no zone: {pending}")
    return owner


def build() -> dict:
    venue = json.loads(VENUE_JSON.read_text(encoding="utf-8"))
    spaces = {s["id"]: s for s in venue["spaces"]}
    owner = assign_spaces(venue)
    members: dict[str, list[str]] = {}
    for sid, zid in owner.items():
        members.setdefault(zid, []).append(sid)

    zones = []
    for zid, label, event, listed, aliases in GROUPS:
        sids = listed + sorted(s for s in members[zid] if s not in listed)
        group = [spaces[s] for s in sids]
        level = STOREY_LEVEL[group[0]["storey"]]
        x, z = zone_point([s for s in group if s["storey"] == group[0]["storey"]])
        elevation = group[0].get("floor_elevation", storey_elevation(venue, group[0]["storey"]))
        venue_aliases = [a for s in group for a in (s.get("aliases") or [])]
        zones.append(
            {
                "id": zid,
                "label": label,
                "event_name": event,
                "floor": level,
                "anchor": norm(x, z, elevation),
                "outdoor": all(s["is_outdoor"] for s in group),
                "spaces": sids,
                "occupants": sum(s.get("occupant_load") or 0 for s in group),
                "aliases": list(dict.fromkeys(a.lower() for a in [*aliases, *venue_aliases])),
                "source": "scan"
                if any(s.get("geometry_source") == "scan" for s in group)
                else "floor plan",
            }
        )
    zone_of = {sid: z["id"] for z in zones for sid in z["spaces"]}

    # A venue opening alias that also names a zone ("entrance") stays with the zone, so someone
    # outside at check-in is not placed inside at the doors.
    zone_words = {
        w.lower() for z in zones for w in [z["id"].replace("_", " "), z["label"], *z["aliases"]]
    }
    exits = []
    for o in venue["openings"]:
        if not o.get("is_exit"):
            continue
        eid, label, aliases = EXITS[o["id"]]
        inner = spaces[o["a"]]
        if o["kind"] == "stair":  # the top, where 2F people reach it
            x, z = (o.get("ends") or {}).get(o["a"], o["position"])
        else:
            x, z = o["position"]
        level = STOREY_LEVEL[inner["storey"]]
        exits.append(
            {
                "id": eid,
                "label": label,
                "kind": "stair" if o["kind"] == "stair" else "door",
                "floor": level,
                "anchor": norm(x, z, inner.get("floor_elevation", 0.0)),
                "zone": zone_of.get(o["a"]),
                "opening": o["id"],
                "openings": [o["id"]],
                "exterior": True,
                "aliases": list(
                    dict.fromkeys(
                        [
                            *aliases,
                            *(a for a in o.get("aliases") or [] if a.lower() not in zone_words),
                        ]
                    )
                ),
                "note": EXIT_NOTES.get(o["id"]),
            }
        )
    for eid, ops, top, label, aliases, note in STAIRS:
        stairs = [next(o for o in venue["openings"] if o["id"] == op) for op in ops]
        pts = [(s.get("ends") or {}).get(top, s["position"]) for s in stairs]
        x, z = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
        exits.append(
            {
                "id": eid,
                "label": label,
                "kind": "stair",
                "floor": 2,
                "anchor": norm(x, z, storey_elevation(venue, "2F")),
                "zone": zone_of.get(top),
                "opening": ops[0],
                "openings": ops,
                "exterior": False,
                "aliases": aliases,
                "note": note,
            }
        )
    if len([e for e in exits if e["exterior"]]) != sum(
        1 for o in venue["openings"] if o.get("is_exit")
    ):
        raise SystemExit("not every venue exit made it into the profile")

    floors = []
    for level in (1, 2):
        indoor = [
            spaces[s]
            for z in zones
            if z["floor"] == level and not z["outdoor"]
            for s in z["spaces"]
            if not spaces[s]["is_outdoor"]
            and STOREY_LEVEL[spaces[s]["storey"]] == level
            and spaces[s]["storey"] != "3F"
        ]
        x, z = zone_point(indoor)
        elevation = storey_elevation(venue, "1F" if level == 1 else "2F")
        floors.append(
            {
                "level": level,
                "label": FLOOR_LABEL[level],
                "ny": norm(0, 0, elevation)["ny"],
                "source": FLOOR_SOURCE[level],
                "anchor": norm(x, z, elevation),
                "aliases": FLOOR_ALIASES.get(level, []),
            }
        )

    scenario = next(s for s in venue["occupant_scenarios"] if s.get("default"))
    return {
        "id": venue["building"]["id"],
        "name": venue["building"]["name"],
        "address": venue["building"]["address"],
        "_source_note": "GENERATED by apps/api/scripts/build_profile.py from "
        "packages/engine/venue.json; do not edit by hand. Zones are venue spaces (spaces), exits "
        "are every venue exit (opening) plus the stairs down from floor 2. Occupants: venue "
        f"scenario {scenario['id']}. Floor 2 comes from the floor plan, not the scan.",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "venue_schema_version": str(venue.get("schema_version")),
        "occupant_scenario": scenario["id"],
        "lat": 34.0714,
        "lng": -118.4459,
        "scan_url": SCAN_URL,
        "lines": [],
        "geo": {
            "bearing_deg": 0,
            "width_m": FRAME["x1"] - FRAME["x0"],
            "depth_m": FRAME["z1"] - FRAME["z0"],
            "height_m": FRAME["y1"] - FRAME["y0"],
        },
        "frame": FRAME,
        "scans": SCANS,
        "floors": floors,
        "assembly": ASSEMBLY,
        "assembly_exit_id": None,
        "zones": zones,
        "exits": exits,
    }


if __name__ == "__main__":
    profile = build()
    OUT.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"wrote {OUT.relative_to(ROOT)}: {len(profile['zones'])} zones, "
        f"{sum(e['exterior'] for e in profile['exits'])} exterior exits, "
        f"{sum(not e['exterior'] for e in profile['exits'])} inside stairs"
    )
