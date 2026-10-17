#!/usr/bin/env python3
"""Pre-warm the agent cache by running the live agent against both demo
buildings and verifying the cache row landed in Supabase. Run once before
demo day so judging runs are zero-latency replays.

    cd apps/api
    uv run python scripts/prewarm_cache.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=True)

# Local FastAPI must be running on this URL for the script to work.
API_BASE = os.environ.get("ARIA_API_URL", "http://localhost:8000")

DEMO_BUILDINGS: list[tuple[str, str, str]] = [
    (
        "The Dock",
        "e5a3fddc-e22c-431c-a5d3-ee29ef8604d1",
        "400 NW 26th St, Miami, FL 33127",
    ),
]

DEFAULT_SCENARIO = {"wind_mph": 130, "surge_ft": 6, "rainfall_in": 4}


@dataclass
class RunStats:
    completed: bool
    duration_s: float
    tool_calls: int
    iterations: int
    error: str | None


def run_one(building_id: str, address: str) -> RunStats:
    """Hit /agent/run and consume the SSE stream until completion."""
    body = json.dumps(
        {
            "address": address,
            "scenario_params": DEFAULT_SCENARIO,
            "building_id": building_id,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        f"{API_BASE}/agent/run",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )

    started = time.monotonic()
    tool_calls = 0
    iterations = 0
    completed = False
    error: str | None = None

    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            buffer = ""
            while True:
                chunk = resp.read1(8192).decode("utf-8", errors="replace")
                if not chunk:
                    break
                buffer += chunk
                while "\n\n" in buffer:
                    block, buffer = buffer.split("\n\n", 1)
                    event_type = ""
                    for line in block.splitlines():
                        if line.startswith("event:"):
                            event_type = line[6:].strip()
                    if event_type == "tool_call":
                        tool_calls += 1
                    elif event_type == "thinking":
                        iterations += 1
                    elif event_type == "complete":
                        completed = True
                    elif event_type == "error":
                        error = "agent emitted error event"
                if completed or error:
                    break
    except urllib.error.URLError as e:
        error = f"transport: {e}"
    except Exception as e:  # noqa: BLE001
        error = f"{type(e).__name__}: {e}"

    return RunStats(
        completed=completed,
        duration_s=time.monotonic() - started,
        tool_calls=tool_calls,
        iterations=iterations,
        error=error,
    )


def verify_cache(building_id: str) -> dict | None:
    """Read the cache row back from Supabase to confirm persistence."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return None
    try:
        from supabase import create_client

        sb = create_client(url, key)
        res = (
            sb.table("cached_runs")
            .select("total_duration_ms, tool_call_count, iteration_count")
            .eq("building_id", building_id)
            .maybe_single()
            .execute()
        )
        return res.data if res else None
    except Exception as e:  # noqa: BLE001
        print(f"  ! cache verify failed: {e}", file=sys.stderr)
        return None


def main() -> int:
    print(f"Pre-warming cache via {API_BASE} ...")
    print()
    summary: list[str] = []
    overall_ok = True

    for name, bid, address in DEMO_BUILDINGS:
        print(f"━━━ {name} ({bid[:8]}…) ━━━")
        print(f"  address: {address}")
        print("  running live agent (this takes ~60-90s) ...")
        stats = run_one(bid, address)
        if not stats.completed:
            overall_ok = False
            print(f"  ✗ FAILED after {stats.duration_s:.1f}s: {stats.error or 'no complete event'}")
            summary.append(f"✗ {name}: {stats.error or 'no complete event'}")
            continue
        print(
            f"  ✓ agent completed in {stats.duration_s:.1f}s "
            f"({stats.tool_calls} tool calls, {stats.iterations} iterations)"
        )
        cache = verify_cache(bid)
        if cache:
            print(
                f"  ✓ cache row present "
                f"({cache.get('total_duration_ms')}ms · "
                f"{cache.get('tool_call_count')} tools · "
                f"{cache.get('iteration_count')} iters)"
            )
            summary.append(f"✓ {name}: {stats.duration_s:.0f}s, {stats.tool_calls} tool calls")
        else:
            overall_ok = False
            print("  ! cache row NOT found in Supabase")
            summary.append(f"✗ {name}: cache write missing")
        print()

    print("━━━ SUMMARY ━━━")
    for line in summary:
        print(f"  {line}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
