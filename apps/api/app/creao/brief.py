"""The building brief: plain-text layout facts a phone agent can read to a caller.

GET /live/buildings/{id}/brief. Built from the building profile, which is generated from the
engine's venue model (packages/engine/venue.json), so it says only what the venue model says:
the floors and their rooms (with the event's names), every exterior exit, the stairs down from
floor 2, that elevators are not used, and where to go once out. No assembly point, refuge area or
step-free route is claimed, because none is confirmed.
"""

from __future__ import annotations

from functools import lru_cache

from app.creao.buildings import Building, get_building

NO_ELEVATOR = "Elevators are not used in an evacuation."
NO_STEP_FREE = (
    "No step-free way out is confirmed: tell the dispatcher about anyone who uses a wheelchair "
    "or can't manage stairs, and where they are."
)


def _room(z) -> str:
    name = z.label
    if z.event_name and z.event_name.lower() not in name.lower():
        name += f" (event name: {z.event_name})"
    if z.outdoor:
        name += ", outdoors"
    return name


def text(building: Building) -> str:
    lines = [
        f"{building.name}, {building.address}. Layout facts for an evacuation call, from Aria's "
        "venue model; nothing here is a live observation.",
    ]
    for f in building.floors:
        lines.append("")
        lines.append(f"{f.label}{' (from ' + f.source + ')' if f.source else ''}:")
        rooms = [z for z in building.zones if z.floor == f.level]
        named = [z for z in rooms if z.event_name or z.occupants >= 50 or z.outdoor]
        rest = [z for z in rooms if z not in named]
        for z in named:
            lines.append(f"- {_room(z)}")
        if rest:
            lines.append("- Smaller rooms: " + ", ".join(z.label for z in rest))
        if f.level > 1:
            lines.append(
                "- The event's Networking and Workshops were upstairs in the indoor rooms; which "
                "room held which is not recorded."
            )
    exterior = [e for e in building.exits if e.exterior]
    lines += ["", f"Exits out of the building ({len(exterior)}):"]
    for e in exterior:
        where = f"stairs from floor {e.floor} down to the ground" if e.kind == "stair" else ""
        lines.append(f"- {e.id}: {e.label} ({where or f'floor {e.floor}'})")
    stairs = [e for e in building.exits if e.kind == "stair"]
    if stairs:
        lines += ["", "Stairs down from floor 2:"]
        for e in stairs:
            note = f"; {e.note}" if e.note else ""
            exit_word = ", an exit" if e.exterior else ""
            lines.append(f"- {e.id}: {e.label} (floor {e.floor}{exit_word}{note})")
    lines += [
        "",
        NO_ELEVATOR,
        NO_STEP_FREE,
        f"Once out: go {building.assembly}. There is no fixed assembly point.",
        "Floor 2 and above come from the floor plan, not the scan.",
    ]
    return "\n".join(lines)


@lru_cache(maxsize=8)
def _brief(building_id: str) -> dict:
    b = get_building(building_id)
    if b is None:
        raise LookupError(building_id)
    return {
        "building": b.id,
        "name": b.name,
        "text": text(b),
        "exits": [{"id": e.id, "label": e.label, "floor": e.floor} for e in b.exits if e.exterior],
        "stairs": [
            {"id": e.id, "label": e.label, "floor": e.floor, "exit": e.exterior}
            for e in b.exits
            if e.kind == "stair"
        ],
        "assembly": b.assembly,
        "updated_at": b.generated_at,
    }


def brief(building_id: str) -> dict:
    """Cached: the profile only changes with a deploy."""
    return _brief(building_id)
