"""GET /engine/* — runs Aria's building engine (packages/engine) on demand.

The engine is a stdlib-only package beside the API in the monorepo. It is imported from
../../packages/engine (repo root/packages/engine), locally and in the Docker image, which
copies it to the same place. One run takes about a second, so results are cached per
start space and growth.
"""

from __future__ import annotations

import asyncio
import json
import sys
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Response

_ENGINE_DIR = Path(__file__).resolve().parents[4] / "packages" / "engine"
if _ENGINE_DIR.is_dir() and str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

from engine import demo  # noqa: E402
from engine.aria_venue import NON_WALKING_KINDS  # noqa: E402
from engine.constants import ALPHA_KW_S2  # noqa: E402

router = APIRouter(prefix="/engine", tags=["engine"])

# The same run the viewer's static file was made with (public/fire/venue.json).
VIEWER_DEPARTURES = (0.0, 60.0, 120.0, 180.0, 240.0, 300.0, 420.0)
VIEWER_FRAME_STEP_S = 10.0
CACHE_RUNS = 24  # ~0.7 MB of viewer JSON each


@lru_cache(maxsize=1)
def starts() -> list[dict]:
    """Indoor spaces a fire can start in, from venue.json."""
    raw = json.loads(Path(demo.VENUE_JSON).read_text(encoding="utf-8"))
    out = []
    for s in raw["spaces"]:
        if s.get("is_outdoor") or s.get("kind") in NON_WALKING_KINDS:
            continue
        out.append(
            {
                "id": s["id"],
                "name": s.get("event_name") or s.get("name") or s["id"],
                "storey": s.get("storey"),
                "kind": s.get("kind"),
                "occupant_load": s.get("occupant_load", 0),
            }
        )
    return out


@lru_cache(maxsize=CACHE_RUNS)
def _run(start: str, growth: str) -> dict:
    result = demo.run_demo(
        start=start,
        growth=growth,
        departures=VIEWER_DEPARTURES,
        frame_step_s=VIEWER_FRAME_STEP_S,
    )
    return {
        "viewer": json.dumps(result["viewer"], ensure_ascii=False).encode("utf-8"),
        "scenario": result,
    }


def _check(start: str, growth: str) -> None:
    if growth not in ALPHA_KW_S2:
        raise HTTPException(422, f"growth must be one of {sorted(ALPHA_KW_S2)}")
    if start not in {s["id"] for s in starts()}:
        raise HTTPException(404, f"unknown start space {start!r}; see /engine/starts")


async def run(start: str, growth: str = "fast") -> dict:
    """The full engine result for one scenario (cached), off the event loop."""
    _check(start, growth)
    return (await asyncio.to_thread(_run, start, growth))["scenario"]


@router.get("/starts")
async def list_starts() -> dict:
    return {"default": demo.DEFAULT_START, "growths": sorted(ALPHA_KW_S2), "starts": starts()}


@router.get("/viewer")
async def viewer(start: str = Query(demo.DEFAULT_START), growth: str = Query("fast")) -> Response:
    """The viewer block (FireTimeline + routes) apps/web draws on the scan."""
    _check(start, growth)
    body = (await asyncio.to_thread(_run, start, growth))["viewer"]
    return Response(content=body, media_type="application/json")


@router.get("/summary")
async def scenario_summary(
    start: str = Query(demo.DEFAULT_START), growth: str = Query("fast")
) -> dict:
    """Scenario, readable summary and exits lost: what the agents and the report quote."""
    result = await run(start, growth)
    return {
        "scenario": result["scenario"],
        "summary": result["summary"],
        "exits": result["fire"]["exits"],
        "origin": result["fire"]["origin"],
    }
