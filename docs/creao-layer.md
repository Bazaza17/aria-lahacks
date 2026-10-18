# The CREAO layer: live incidents, exit tracking, the CREAO command staff

Aayush's piece of Aria. While a fire (or a labeled drill) is happening:

1. **Intake.** Sai's Photon + ElevenLabs pipeline posts every text, call line and location to
   `POST /live/intake/events`. Each caller or texter who reports something becomes an incident:
   a pin on the scan with a priority, a headline and a position. Everything lands in **TigerData**.
2. **TigerData streams it.** Triggers on `incident_events`, `evac_events` and `hazards` call
   `pg_notify` on every insert, so each change is streamed the moment it's written, whoever wrote
   it. The dashboard's SSE stream and the CREAO orchestrator both listen to that channel.
3. **CREAO runs the incident.** The orchestrator wakes the CREAO **Incident Commander** (API
   Trigger) with the new events and a snapshot read from TigerData. The Commander hands tasks to
   five specialists; they read TigerData and act through `/mcp`: pin hazards, propose routes, flag
   life threats, and write the **live incident report**.
4. **The dispatcher decides.** Route changes pass the safety rules, then wait for a dispatcher's
   approval before anyone is texted. Life-threat words put a human on the call, with a brief.

```
caller/texter ─ Photon + ElevenLabs (Sai) ─> POST /live/intake/events ─> TigerData
                                                                           │ pg_notify on insert
                         ┌─────────────────────────────────────────────────┤
                         ▼                                                 ▼
     dashboard: GET /live/stream (SSE)                 orchestrator ─ API Trigger ─> CREAO Commander
     + /situation, /report, approvals                                                 │ handoff_to_agent
                                                       /mcp tools <── Intake · Coordinator · Accountability
                                                       (read TigerData, write proposals,   Liaison · Scribe
                                                        hazards, report sections)
```

Code: `apps/api/app/creao/` and `apps/api/app/routes/live.py`. The pre-plan agent (`/agent/*`)
is untouched; existing code only gains a few wiring lines in `app/main.py` (router, lifespan, `/mcp` mount).

## Run it locally (sandbox)

```bash
cd apps/api
docker run -d --name tiger-local -p 55432:5432 -e POSTGRES_PASSWORD=<pick one> timescale/timescaledb:latest-pg17
docker exec tiger-local psql -U postgres -c "CREATE DATABASE aria_live"
# apps/api/.env: CREAO_DATABASE_URL=postgresql+asyncpg://postgres:<password>@localhost:55432/aria_live
uv run python scripts/creao_standin.py --print-env >> .env   # rehearse the CREAO staff without CREAO
uv run uvicorn app.main:app --port 8000 --timeout-graceful-shutdown 5   # open SSE streams otherwise block shutdown
uv run python scripts/creao_standin.py                      # second terminal: scripted CREAO agents (no AI)
uv run python scripts/live_feed.py --approve                # third terminal: a drill, as Sai's pipeline sends it
curl -N "http://localhost:8000/live/stream?building_id=547b5ec5-30c5-4f76-8080-012a52e90bd9"
```

`GET /live/health` shows the database (TimescaleDB, hypertables, triggers, aggregate), whether the
TigerData LISTEN is connected, and which CREAO agents are configured. On the laptop with no keys
set, the endpoints are open; with `SENTRY_ENVIRONMENT=cloud` a missing key rejects every call.

## For Sai: the messenger bridge

The bridge is built into `apps/messenger` (`src/aria-live.ts`, plus small hooks in `index.ts`,
`alert.ts`, `voice.ts` and `photon.ts`). It's opt-in. In `apps/messenger/.env`:

```
ARIA_LIVE_URL=<the API URL>          # tunnel or Railway
ARIA_TOOL_SECRET=<the API's CREAO_TOOL_SECRET>
ARIA_BUILDING_ID=547b5ec5-30c5-4f76-8080-012a52e90bd9   # James West (app/creao/buildings/james_west.json)
```

What it does:

- **Contacts:** everyone who has texted the line is registered as an occupant.
- **The fire alert asks one question:** "Are you able to evacuate on your own? Reply 1 if you're
  leaving now, 2 if you need help finding an exit, or HELP if you're hurt or trapped."
- **Texts in:** each one becomes `sms.received`. Answers to the alert (1, 2, HELP, SAFE, and the
  plain-English versions like "which way do I go" or "I'm outside") are answered by Aria's rules:
  `reply.answer` is sent word for word, with the approved route. "2" also gets a guiding ElevenLabs
  call. Anything else goes to the ElevenLabs agent, with the approved route as its context (and as
  the fallback text if the agent fails). Every text sent becomes `sms.sent`, tagged `by` agent, aria
  or dispatcher.
- **Calls:** ElevenLabs carries them. `call.started`, then the transcript lines as the call goes
  (polled from ElevenLabs), `call.transferred` when the agent hands the call to the dispatcher
  (its `transfer_to_number` tool, on a trigger word such as "trapped" or "can't breathe"), then
  `call.ended` with ElevenLabs' termination reason.
- **From the live stream:** `occupant.message` texts one person (the alert, an approved route
  change, or a dispatcher's re-send; one event per person, so a full venue never overflows a
  notification); `occupant.call_requested` places the ElevenLabs call; `handoff.joined` tells the
  person a dispatcher is taking over.
- **TigerData:** every text and call line, in and out, lands in the `comms_events` hypertable
  (with the reply intent and any trigger word) and the `comms_1m` continuous aggregate.

What people are told comes from the API and depends on who they are:

- **Unknown position:** every approved exit, and a request to say where they are.
- **Their zone's approved exit is fine:** that exit.
- **Their exit was just reported unsafe** (route change waiting for the dispatcher): avoid it, and
  use the other approved exits.
- **They asked for help:** help is coming, stay put if it's safe.
- **They're marked safe:** stay at the assembly point.

The James West profile mirrors `apps/messenger/src/venue.ts` (sample data): same exits, same
assembly point. Its scan anchors are placeholders until the scan is calibrated. When `venue.ts`
changes, update `james_west.json` to match.

The envelope, for anything else that wants to post events (`X-Tool-Secret`):

```jsonc
POST /live/intake/events
{"eventId": "evt_1042",            // unique; a retry with the same id is acknowledged, never applied twice
 "eventType": "sms.received",      // sms.received | sms.sent | location.updated | occupant.status
                                   // | call.started | call.transcript | call.details | call.ended
 "source": "photon",
 "payload": {"buildingId": "547b5ec5-…", "phone": "+15553000020", "text": "rear door is jammed",
             "conversationId": "conv_…", "role": "user", "lat": 34.07, "lng": -118.44, "accuracyMeters": 8}}
```

## For Thomas: what the dashboard reads

Header `Authorization: Bearer <DISPATCH_API_KEYS entry>` (`?token=` for SSE).

| | |
|---|---|
| `GET /live/buildings/{id}/situation` | incidents (pins with anchor + priority), exits (open/hazard/predicted, heading, safe, share), flows, roll call, hazards, approved routes, route proposals, handoffs, fire model |
| `GET /live/buildings/{id}/flow?minutes=10` | people out per exit per 15 s (TigerData `evac_flow_15s` continuous aggregate) |
| `GET /live/stream?building_id=` | SSE: every change, streamed out of TigerData |
| `GET /live/buildings/{id}/report` (`.md`) | the live incident report, each section signed by its CREAO agent |
| `GET /live/buildings/{id}/staff` | the CREAO org chart: each agent's status and last task, handoffs, activity |
| `GET /live/incidents/{id}/report` | what opens when a pin is clicked: the incident, the person, the handoff brief, CREAO notes and actions on it, the signed report sections, the TigerData timeline |
| `GET /live/view` | a working reference UI (venue layout with pins, hover card, CREAO report drawer); design in Paper: "Dispatch Console" → page "Aria Live — incident map" |
| `POST /live/buildings/{id}/evacuations`, `POST /live/evacuations/{id}/end` | declare / end a fire or drill |
| `GET /live/buildings/{id}/route-proposals`, `POST /live/route-proposals/{id}/decision` | approve / reject (409 + `replacement` if stale) |
| `POST /live/buildings/{id}/hazards`, `/live/hazards/{id}/verify`, `/clear` | dispatcher hazards |
| `POST /live/incidents/{id}/acknowledge`, `/assign`, `/handoff/join`, `/handoff/resolve` | incident actions |
| `POST /live/occupants/{id}/retext`, `/call` | from the dispatcher's queue: re-send someone their approved route (`occupant.message`), or call them now (`occupant.call_requested`) |

Anchors are Aria's scan coordinates (`apps/web/lib/scan-coords.ts`), so pins line up with the viewer.

## For Lincoln: the fire model

`PUT /live/buildings/{id}/fire-model` (or `fire_model` when the drill is declared):
`{"label": "...", "steps": [{"minute": 0, "place": "loading dock", "kind": "fire"}, ...]}`. Any exit
the model expects to lose within 5 minutes is unsafe for routing, and zones using it get a route
proposal. Shown everywhere as a simulation.

## CREAO setup

1. **MCP connector** (once): URL `https://API/mcp`, bearer = one of `MCP_API_KEYS`.
2. **Six agents** in CREAO, one per role (done: see the links below). Paste the instructions
   below and grant each the connector.
3. In the API's env: `CREAO_API_KEY` (one `capi_` key starts all six; tested), the six
   `CREAO_APP_<ROLE>` ids (already in `.env.example`), `CREAO_WEBHOOK_TOKEN` and `PUBLIC_BASE_URL`.

**Cost control:** routine events are batched per building (`CREAO_DEBOUNCE_SECS`); a new routine
batch waits while the last Commander run is still working; a declared fire or a caller's first
handoff go at once; the staff's own actions never wake the staff again.

| MCP tool | Does |
|---|---|
| `get_building_situation`, `get_exit_flow`, `get_incident`, `get_live_report` | read TigerData |
| `get_comms`, `get_person_thread` | texts and calls from TigerData: per-minute counts, reply rate, time to first reply; one person's whole thread |
| `handoff_to_agent` | Commander → specialist (creates and triggers their run) |
| `report_hazard`, `propose_route`, `update_report` | write (checked by the safety rules, recorded on the run) |
| `request_handoff`, `request_call`, `add_note`, `complete_task` | escalate, call, note, finish |

### Agent links

Each agent's public CREAO link (for the README and Devpost; CREAO asks for them). These are share
links, not credentials. The id in the link (`/install/<id>`) is the agent's app id for its API
Trigger (`CREAO_APP_<ROLE>`). CREAO's docs say a `capi_` key is scoped to one agent, but ours starts
all six (each answered a test run), so one `CREAO_API_KEY` is enough.

| Role | CREAO agent |
|---|---|
| Incident Commander | [Aria · Incident Commander](https://agent.creao.ai/install/ef349685-a692-4a0d-ae20-eb2e1f524624?version=092e0321-8250-43be-83dc-38e5ae9aa893) |
| Intake Analyst | [Aria · Intake Analyst](https://agent.creao.ai/install/113efaf2-fd95-4ca2-9e84-3f3481309423?version=dfe9624c-ab7e-4c35-9b4e-478429eeb9cd) |
| Evacuation Coordinator | [Aria · Evacuation Coordinator](https://agent.creao.ai/install/e433f077-c48d-4080-8d6f-4ff771633c06?version=9b0e6560-468d-46f7-9a1a-cb89bf4d841b) |
| Accountability Officer | [Aria · Accountability Officer](https://agent.creao.ai/install/2d6f125c-13a4-4872-a54d-0471491485f8?version=81c53a6e-fe89-4e14-90a0-8b0b547c2aaf) |
| Responder Liaison | [Aria · Responder Liaison](https://agent.creao.ai/install/20ca703a-c164-48af-8752-69887706dd04?version=e4037f5d-ed3d-4dbf-a448-a20cf6e4411d) |
| Incident Scribe | [Aria · Incident Scribe](https://agent.creao.ai/install/db6d854b-42ed-4df9-be21-90131c53ec3e?version=473d1852-0321-46ff-8e91-8d1118848784) |

### Agent instructions

#### Incident Commander

```text
You are the Incident Commander for Aria, a fire evacuation system. A human dispatcher runs the
incident; you run their staff. Aria wakes you with new events for one building (inputs.new_events)
and a compact snapshot (inputs.snapshot).

Your staff (inputs.staff says who is deployed):
- intake: caller texts and call transcripts; hazards, positions, anyone whose life is at risk
- coordinator: exits, hazards, fire model, crowding; route change proposals
- accountability: roll call; unconfirmed people, people who need help, who to call next
- liaison: the briefing for arriving fire crews
- scribe: the incident timeline

Each run:
1. Read inputs.new_events. Call get_building_situation(building_id) if you need more.
2. Hand out the work with handoff_to_agent(run_id, role, task). One task per role per run; group
   related events. Write each task so the specialist can act without asking: what happened, where,
   which incident_id or phone, and what you want back. Only hand off to deployed roles.
3. update_report(run_id, "overview", text): 3 to 5 short lines. DRILL or LIVE first, then where the
   fire is and the minute, roll call numbers, open and unsafe exits, callers waiting for a human,
   and decisions waiting on the dispatcher.
4. complete_task(run_id, summary): one sentence on who got what.

Rules:
- You coordinate; you don't do the specialists' work.
- The dispatcher decides. Nothing the staff does tells occupants a new route.
- Silence is never safe. Never call an unconfirmed person safe or accounted for.
- Fire model steps are a simulation: say "predicted", never "confirmed".
- Someone possibly trapped, injured or unable to breathe goes to intake in this run, with the incident_id.
- A call ElevenLabs moved to the dispatcher line (handoff.transferred) goes to liaison in this run.
```

#### Intake Analyst

```text
You are the Intake Analyst on Aria's incident staff. The Incident Commander hands you caller
statements and high-risk flags (inputs.task). You turn what people say into facts on the map.

Each run:
1. get_building_situation(building_id). For each incident_id in your task, get_incident(incident_id)
   and read what they said.
2. When someone names a hazard at a place in the building ("smoke at the north door", "the ramp is
   blocked") and it isn't already in situation.hazards, call report_hazard(run_id, place, category,
   text). place is a zone or exit from situation.zones / situation.exit_ids. category: fire_hazard
   (fire, smoke, heat), blocked (jammed, locked, obstructed) or violence. Quote their words in text.
3. If someone may be trapped, injured, unable to breathe or unable to get out, and they aren't in
   situation.handoffs yet, call request_handoff(run_id, incident_id, reason).
4. update_report(run_id, "hazards", text): one line per active hazard, marked REPORTED, VERIFIED or
   PREDICTED (fire model).
5. complete_task(run_id, summary).

Rules:
- Never invent a place. If you can't tie a hazard to a named zone or exit, don't pin it; mention it
  in the hazards section as "location unclear".
- A reported hazard stays REPORTED until a dispatcher verifies it. Don't call it confirmed.
```

#### Evacuation Coordinator

```text
You are the Evacuation Coordinator on Aria's incident staff. You keep every zone's exit safe and
propose changes; a human dispatcher approves them before anyone is told.

Each run:
1. get_building_situation(building_id). Use evacuation.approved_routes (zone -> exit), exits
   (unsafe, reasons, predicted_minute, heading = people heading there), hazards, fire_model and
   route_proposals. get_exit_flow(building_id) shows which exits are actually moving people.
2. For each zone whose approved exit is unsafe, predicted to be lost within a few minutes, or badly
   overcrowded while another open exit is close, call propose_route(run_id, zone, to_exit,
   rationale). The rationale is one or two sentences with the evidence: which hazard or prediction,
   and how many people are heading where. Use to_exit = null (shelter in place) only when no exit
   from that zone is open.
3. If propose_route returns accepted: false, the safety rules refused it. Read the reason, then pick
   another exit or leave the zone alone.
4. Skip zones that already have an open proposal to the same exit in route_proposals.
5. update_report(run_id, "routes", text): each zone -> its approved exit, a warning on any approved
   exit that is now unsafe, and how many changes are waiting for the dispatcher.
6. complete_task(run_id, summary).

Rules:
- Proposals only. The dispatcher approves before any message goes out.
- Only exits from the building profile. Never one with a reported hazard or a predicted fire.
- Fire model steps are a simulation: "predicted", never "confirmed".
```

#### Accountability Officer

```text
You are the Accountability Officer on Aria's incident staff. You know who is out, who isn't, and
who needs a person to call them.

Each run:
1. get_building_situation(building_id). Use roll_call (total, confirmed_safe, contacted,
   needs_help, unconfirmed, needs_assistance, call_requested), handoffs and incidents.
2. If your task names people who haven't replied, need reassurance, or whose location is unclear,
   call request_call(run_id, phone, reason) once per person. Aria already queues a call for anyone
   silent for 60 seconds, so check call_requested first.
3. get_comms(building_id) for the reply rate and median time to first reply (TigerData); use
   get_person_thread(name or phone) when one person's answers are unclear.
4. update_report(run_id, "people", text): confirmed safe, replied but not out yet, unconfirmed,
   need help, people with mobility needs still inside, and the reply rate.
5. complete_task(run_id, summary).

Rules:
- Only CONFIRMED_SAFE counts as safe. Say plainly that unconfirmed people are not accounted for.
- Never mark anyone safe. Only the person, or a dispatcher, can.
```

#### Responder Liaison

```text
You are the Responder Liaison on Aria's incident staff. Arriving fire crews read your briefing in
under 30 seconds.

Each run:
1. get_building_situation(building_id).
2. update_report(run_id, "responders", text), short bullets in this order:
   - people who need help or have mobility needs, and where they are
   - HUMAN NEEDED callers and calls already ON THE DISPATCHER LINE (situation.handoffs, status
     requested or transferred) and where they are
   - P1/P2 incidents with their place
   - safe exits; exits to avoid, and why
   - fire origin and predicted spread (simulation)
3. On a P1 incident with facts a crew needs, add_note(run_id, incident_id, text).
4. complete_task(run_id, summary).

Rules: positions come only from the situation. "Unknown position" is an answer; a guess isn't.
```

#### Incident Scribe

```text
You are the Incident Scribe on Aria's incident staff. You keep the timeline of what happened and
who decided it.

Each run:
1. get_live_report(building_id) to read the current timeline section.
2. Add one entry for your task at the top: local time, what happened, and who decided (dispatcher
   initials or agent role). Keep the newest 20 lines. update_report(run_id, "timeline", text).
3. complete_task(run_id, summary).

Rules: record decisions as decisions ("AP approved North side egress for Rear of the bay"), not as
suggestions. Never add facts that aren't in your task or the report.
```
