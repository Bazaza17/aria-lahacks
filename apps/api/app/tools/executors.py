"""Tool executors. Tonight: hardcoded fake data. Saturday: real APIs."""

from typing import Any


async def execute_tool(name: str, tool_input: dict[str, Any]) -> Any:
    """Dispatch a tool call to its implementation."""
    if name == "fetch_street_view":
        return await _fetch_street_view(**tool_input)
    if name == "fetch_satellite":
        return await _fetch_satellite(**tool_input)
    if name == "lookup_flood_zone":
        return await _lookup_flood_zone(**tool_input)
    if name == "lookup_surge_zone":
        return await _lookup_surge_zone(**tool_input)
    if name == "lookup_nearby":
        return await _lookup_nearby(**tool_input)
    return f"Unknown tool: {name}"


async def _fetch_street_view(address: str, heading: float, pitch: float = 0, fov: float = 90):
    """Stub. Saturday: hit Google Street View Static API, return base64 image."""
    return [
        {
            "type": "text",
            "text": (
                f"Street View at heading={heading}, pitch={pitch}, fov={fov}. "
                f"[STUB: Saturday this returns a real image. For now, assume the building "
                f"is a mid-rise reinforced concrete structure with ground-floor glass facade "
                f"and rooftop HVAC units.]"
            ),
        }
    ]


async def _fetch_satellite(address: str, zoom: int = 19):
    return [
        {
            "type": "text",
            "text": (
                f"Satellite view at zoom={zoom}. [STUB: rectangular footprint, ~40m x 25m, "
                f"flat roof with mechanical units, surrounded by paved parking on south, "
                f"vegetation on north, adjacent buildings within 15m on east and west.]"
            ),
        }
    ]


async def _lookup_flood_zone(lat: float, lng: float):
    return {
        "zone": "AE",
        "bfe_ft": 9,
        "description": "1% annual chance flood zone, base flood elevation 9ft NAVD88",
    }


async def _lookup_surge_zone(lat: float, lng: float):
    return {
        "zone": "B",
        "evacuation_order_priority": 2,
        "description": "Category 3+ hurricane evacuation zone",
    }


async def _lookup_nearby(lat: float, lng: float, type: str, radius_mi: float = 1.0):
    fixtures = {
        "hospital": [{"name": "Jackson Memorial Hospital", "distance_mi": 1.2}],
        "shelter": [{"name": "Miami Senior High School Shelter", "distance_mi": 0.8}],
        "hydrant": [{"name": "Hydrant SE-1247", "distance_mi": 0.05}],
        "fire_station": [{"name": "Miami Fire Rescue Station 4", "distance_mi": 0.6}],
        "fuel_storage": [],
    }
    return {"results": fixtures.get(type, [])}
