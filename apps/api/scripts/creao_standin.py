"""Rehearse the CREAO command staff locally, without CREAO (scripted roles, no AI, no credits).

Stands in for CREAO's API Trigger: it accepts the same POST /api/v1/apps/{app_id}/runs the API
sends, plays that role as fixed rules through the same MCP tools the real agents use, and calls the
webhookUrl when done. It's for testing the wiring; the real staff runs in CREAO and reasons.

    uv run python scripts/creao_standin.py --print-env      # lines to add to apps/api/.env
    uv run python scripts/creao_standin.py                  # listen on :8898
"""

import argparse
import asyncio
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.creao.agents import ROLES

STEP = 1.0  # seconds between tool calls, so the org chart shows each agent working

HANDOFFS = {
    "evacuation.started": [
        (
            "coordinator",
            "Check every zone's approved exit against hazards, the fire model and crowding.",
        ),
        ("accountability", "Start the roll call: who hasn't replied, who needs help."),
        ("liaison", "Prepare the briefing for arriving crews."),
        ("scribe", "Open the incident timeline."),
    ],
    "hazard.reported": [
        ("coordinator", "A hazard was reported; re-check the routes it touches."),
        ("scribe", "Log the hazard."),
    ],
    "fire_model.updated": [("coordinator", "The fire model changed; re-check routes.")],
    "statement": [("intake", "Read the new caller statements; pin hazards, flag anyone at risk.")],
    "risk": [
        ("intake", "High-risk words on a call or text: check whether a human needs to take it.")
    ],
    "occupant.call_requested": [
        ("accountability", "Someone hasn't replied; review who needs a call.")
    ],
    "handoff.requested": [
        ("liaison", "A caller needs a human; add them to the crew briefing."),
        ("scribe", "Log the handoff."),
    ],
    "handoff.transferred": [
        (
            "liaison",
            "ElevenLabs moved a call to the dispatcher line; add them to the crew briefing.",
        ),
        ("scribe", "Log the transfer."),
    ],
    "route.approved": [("scribe", "A route change was approved; log it.")],
    "route.rejected": [("scribe", "A route change was rejected; log it.")],
}


class MCP:
    def __init__(self, base: str, key: str) -> None:
        self.http = httpx.AsyncClient(
            base_url=base,
            timeout=30,
            headers={
                "Authorization": f"Bearer {key}",
                "Accept": "application/json, text/event-stream",
            },
        )
        self.n = 0

    async def __call__(self, tool: str, **args):
        self.n += 1
        r = await self.http.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": self.n,
                "method": "tools/call",
                "params": {"name": tool, "arguments": args},
            },
        )
        r.raise_for_status()
        result = r.json()["result"]
        out = result.get("structuredContent") or json.loads(result["content"][0]["text"])
        shown = ", ".join(f"{k}={str(v)[:30]!r}" for k, v in args.items() if k != "run_id")
        print(f"    {tool}({shown}) -> {str(out)[:90]}")
        await asyncio.sleep(STEP)
        return out


async def commander(mcp: MCP, inp: dict) -> str:
    events = inp.get("new_events") or []
    deployed = {s["role"] for s in inp.get("staff", []) if s["deployed"]}
    tasks: dict[str, list[str]] = {}
    for e in events:
        for role, task in HANDOFFS.get(e["type"], []):
            if role in deployed and task not in tasks.setdefault(role, []):
                tasks[role].append(task)
    for role, mine in tasks.items():
        detail = "; ".join(
            str(e.get("summary"))[:90]
            for e in events
            if any(r == role for r, _ in HANDOFFS.get(e["type"], []))
        )
        await mcp(
            "handoff_to_agent",
            run_id=inp["run_id"],
            role=role,
            task=f"{' '.join(mine)} ({detail[:300]})",
        )
    snap = inp.get("snapshot") or {}
    ev, rc = snap.get("evacuation"), snap.get("roll_call") or {}
    if ev:
        lines = [
            f"{ev['mode'].upper()}: fire at {ev['origin_label']}, minute {ev['minute_now']:.0f}.",
            f"Roll call: {rc.get('confirmed_safe', 0)} out, {rc.get('unconfirmed', 0)} unconfirmed, "
            f"{rc.get('needs_help', 0)} need help (of {rc.get('total', 0)}).",
            "Open exits: "
            + (", ".join(x["label"] for x in snap.get("exits", []) if not x["unsafe"]) or "none")
            + ".",
        ]
        if snap.get("handoffs"):
            lines.append(f"{len(snap['handoffs'])} caller(s) waiting for a human dispatcher.")
        if snap.get("open_route_proposals"):
            lines.append(
                f"{len(snap['open_route_proposals'])} route change(s) waiting for approval."
            )
        await mcp("update_report", run_id=inp["run_id"], section="overview", text="\n".join(lines))
    return f"Routed {len(events)} event(s) to {', '.join(ROLES[r]['title'] for r in tasks) or 'nobody'}."


async def intake(mcp: MCP, inp: dict) -> str:
    s = await mcp("get_building_situation", building_id=inp["building_id"])
    flagged = 0
    for i in s["incidents"]:
        if i["status"] != "active" or i.get("handoff"):
            continue
        detail = await mcp("get_incident", incident_id=i["id"], lines=6)
        said = " ".join(
            e["text"] or "" for e in detail["timeline"] if e["role"] == "caller"
        ).lower()
        if any(w in said for w in ("trapped", "can't get out", "can't breathe")):
            await mcp(
                "request_handoff",
                run_id=inp["run_id"],
                incident_id=i["id"],
                reason="life threat in what they said",
            )
            flagged += 1
    text = "\n".join(
        f"• {h['category']} — “{h['text'][:90]}” ({h['verification'].replace('_', ' ')})"
        for h in s["hazards"][:8]
    )
    if s.get("evacuation"):
        await mcp(
            "update_report",
            run_id=inp["run_id"],
            section="hazards",
            text=text or "No hazards reported.",
        )
    return f"{len(s['hazards'])} hazard(s) on the map; {flagged} new handoff(s)."


async def coordinator(mcp: MCP, inp: dict) -> str:
    s = await mcp("get_building_situation", building_id=inp["building_id"])
    ev = s.get("evacuation")
    if not ev:
        return "No active evacuation."
    exits = {e["id"]: e for e in s["exits"]}
    open_exits = [e for e in s["exits"] if not e["unsafe"]]
    pending = {p["zone_id"] for p in s["route_proposals"] if p["status"] == "proposed"}
    proposed = 0
    for r in ev["approved_routes"]:
        cur = exits.get(r["exit_id"])
        if cur and cur["unsafe"] and open_exits and r["zone_id"] not in pending:
            alt = min(open_exits, key=lambda e: e["heading"])
            out = await mcp(
                "propose_route",
                run_id=inp["run_id"],
                zone=r["zone_id"],
                to_exit=alt["id"],
                rationale=f"{cur['label']} is unsafe ({'; '.join(cur['reasons'])}). {alt['label']} is open with "
                f"{alt['heading']} heading there.",
            )
            proposed += bool(out.get("accepted"))
    flow = await mcp("get_exit_flow", building_id=inp["building_id"], minutes=10)
    moved = {}
    for b in flow["buckets"]:
        for x, c in b["by_exit"].items():
            moved[x] = moved.get(x, 0) + c
    lines = [
        f"• {r['zone_label']} → {r['exit_label']}"
        + (" ⚠ now unsafe" if exits[r["exit_id"]]["unsafe"] else "")
        for r in ev["approved_routes"]
    ]
    if moved:
        lines.append(
            "Out in the last 10 min: "
            + ", ".join(
                f"{exits[x]['label']} {c}"
                for x, c in sorted(moved.items(), key=lambda kv: -kv[1])
                if x in exits
            )
        )
    await mcp("update_report", run_id=inp["run_id"], section="routes", text="\n".join(lines))
    return f"Checked {len(ev['approved_routes'])} zone routes; proposed {proposed} change(s)."


async def accountability(mcp: MCP, inp: dict) -> str:
    s = await mcp("get_building_situation", building_id=inp["building_id"])
    rc = s["roll_call"]
    text = (
        f"{rc['confirmed_safe']} of {rc['total']} confirmed out. {rc['contacted']} replied but not out. "
        f"{rc['unconfirmed']} unconfirmed (not accounted for); {rc['call_requested']} queued for a call. "
        f"{rc['needs_help']} asked for help; {rc['needs_assistance']} with mobility needs still inside."
    )
    if s.get("evacuation"):
        await mcp("update_report", run_id=inp["run_id"], section="people", text=text)
    return text


async def liaison(mcp: MCP, inp: dict) -> str:
    s = await mcp("get_building_situation", building_id=inp["building_id"])
    lines = [f"• HUMAN NEEDED: {h['brief']['summary']}" for h in s["handoffs"]]
    lines += [
        f"• {i['priority']} {i['headline'][:70]} — {i['location'].get('label')}"
        for i in s["incidents"][:6]
        if i["status"] == "active"
    ]
    lines.append(
        "Safe exits: " + (", ".join(e["label"] for e in s["exits"] if not e["unsafe"]) or "none")
    )
    avoid = [f"{e['label']} ({'; '.join(e['reasons'])})" for e in s["exits"] if e["unsafe"]]
    if avoid:
        lines.append("Avoid: " + ", ".join(avoid))
    if s.get("evacuation"):
        await mcp(
            "update_report", run_id=inp["run_id"], section="responders", text="\n".join(lines)
        )
    return f"Briefing covers {len(s['incidents'])} incident(s), {len(s['handoffs'])} handoff(s)."


async def scribe(mcp: MCP, inp: dict) -> str:
    r = await mcp("get_live_report", building_id=inp["building_id"])
    if not r["evacuation"]:
        return "No active evacuation."
    old = next((sec for sec in r["sections"] if sec["section"] == "timeline"), {})
    previous = [] if old.get("automatic") else old.get("text", "").splitlines()
    entry = f"{datetime.now().strftime('%H:%M:%S')}  {inp['task'][:200]}"
    await mcp(
        "update_report",
        run_id=inp["run_id"],
        section="timeline",
        text="\n".join([entry, *previous][:20]),
    )
    return "Timeline updated."


PLAYS = {
    "commander": commander,
    "intake": intake,
    "coordinator": coordinator,
    "accountability": accountability,
    "liaison": liaison,
    "scribe": scribe,
}


def build_app(base: str, key: str) -> Starlette:
    mcp = MCP(base, key)

    async def play(inp: dict, webhook: str, creao_run_id: str) -> None:
        role = inp.get("role")
        print(f"[{datetime.now():%H:%M:%S}] {ROLES[role]['title']}: {inp.get('task', '')[:110]}")
        status = "completed"
        try:
            await asyncio.sleep(STEP)
            summary = await PLAYS[role](mcp, inp)
            await mcp("complete_task", run_id=inp["run_id"], summary=summary)
        except Exception as e:  # noqa: BLE001  report it like CREAO would: a failed run
            status, summary = "failed", f"{type(e).__name__}: {e}"
            print(f"    failed: {summary}")
        async with httpx.AsyncClient(timeout=15) as client:
            await client.post(
                webhook,
                headers={"X-Creao-Delivery-Id": uuid.uuid4().hex},
                json={"runId": creao_run_id, "status": status, "output": {"summary": summary}},
            )

    async def runs(request: Request) -> JSONResponse:
        body = await request.json()
        inp, webhook = body.get("inputs") or {}, body.get("webhookUrl")
        if inp.get("role") not in PLAYS or not webhook:
            return JSONResponse({"error": "unknown role or no webhookUrl"}, status_code=400)
        creao_run_id = f"standin_{uuid.uuid4().hex[:10]}"
        asyncio.create_task(play(inp, webhook, creao_run_id))
        return JSONResponse({"runId": creao_run_id, "status": "queued"})

    return Starlette(routes=[Route("/api/v1/apps/{app_id}/runs", runs, methods=["POST"])])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000", help="the Aria API (for MCP calls)")
    ap.add_argument("--port", type=int, default=8898)
    ap.add_argument("--mcp-key", default="sandbox-mcp-key")
    ap.add_argument("--print-env", action="store_true")
    args = ap.parse_args()
    if args.print_env:
        staff = {r: {"app_id": r, "api_key": "standin"} for r in ROLES}
        print(f"CREAO_AGENTS={json.dumps(staff, separators=(',', ':'))}")
        print(f"CREAO_TRIGGER_URL=http://localhost:{args.port}/api/v1/apps/{{app_id}}/runs")
        print(f"MCP_API_KEYS={args.mcp_key}")
        print("CREAO_DEBOUNCE_SECS=5")
        return
    print(f"CREAO stand-in on :{args.port} (scripted roles, no AI)")
    uvicorn.run(
        build_app(args.base, args.mcp_key), host="127.0.0.1", port=args.port, log_level="warning"
    )


if __name__ == "__main__":
    main()
