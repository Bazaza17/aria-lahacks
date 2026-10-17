"""Tool definitions for the Anthropic API."""

from anthropic.types import ToolParam

TOOLS: list[ToolParam] = [
    {
        "name": "fetch_street_view",
        "description": (
            "Fetches a Google Street View image of an address at a specified heading "
            "(0=N, 90=E, 180=S, 270=W) and pitch (-90 to 90, 0=level). Returns the "
            "image for visual analysis. Use to inspect the building from multiple "
            "angles. If an image is occluded or unclear, call again with adjusted "
            "parameters."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {"type": "string"},
                "heading": {"type": "number", "description": "0-360"},
                "pitch": {"type": "number", "description": "-90 to 90", "default": 0},
                "fov": {"type": "number", "description": "10-120", "default": 90},
            },
            "required": ["address", "heading"],
        },
    },
    {
        "name": "fetch_satellite",
        "description": "Fetches a top-down satellite image. Useful for footprint and roof features.",
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {"type": "string"},
                "zoom": {"type": "number", "description": "18-21", "default": 19},
            },
            "required": ["address"],
        },
    },
    {
        "name": "lookup_flood_zone",
        "description": "Queries FEMA flood hazard layer. Returns zone (X, AE, VE), BFE, description.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number"},
                "lng": {"type": "number"},
            },
            "required": ["lat", "lng"],
        },
    },
    {
        "name": "lookup_surge_zone",
        "description": "Queries Miami-Dade hurricane evacuation zones. Returns A-E.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number"},
                "lng": {"type": "number"},
            },
            "required": ["lat", "lng"],
        },
    },
    {
        "name": "lookup_nearby",
        "description": "Finds nearby assets. Types: hospital, shelter, hydrant, fire_station, fuel_storage.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number"},
                "lng": {"type": "number"},
                "type": {
                    "type": "string",
                    "enum": ["hospital", "shelter", "hydrant", "fire_station", "fuel_storage"],
                },
                "radius_mi": {"type": "number", "default": 1.0},
            },
            "required": ["lat", "lng", "type"],
        },
    },
]
