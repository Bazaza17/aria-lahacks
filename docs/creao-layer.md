# The CREAO layer: live incidents, exit tracking, the CREAO command staff

Six CREAO agents, built on agent.creao.ai, run Aria's live response. Their agent IDs, their links
and a run share link are under [Agent links](#agent-links).

Aayush's piece of Aria. While a fire (or a labeled drill) is happening:

1. **Intake.** Sai's Photon + ElevenLabs pipeline posts every text, call line and location to
   `POST /live/intake/events`. Each caller or texter who reports something becomes an incident:
   a pin on the scan with a priority, a headline and a position. Everything lands in **TigerData**.
2. **TigerData streams it.** Triggers on `comms_events`, `incident_events`, `evac_events` and `hazards` call
   `pg_notify` on every insert, so each change is streamed the moment it's written, whoever wrote
   it. The dashboard's SSE stream and the CREAO orchestrator both listen to that channel.
3. **CREAO runs the incident.** The orchestrator wakes the CREAO **Incident Commander** (API
   Trigger) with the new events and a snapshot read from TigerData. The Commander hands tasks to
   five specialists. Each run gets a snapshot read from TigerData and ends its reply with an
   `aria-actions` block, which the API runs through the safety rules: pin hazards, propose routes,
   flag life threats, and write the **live incident report**. When a drill ends, the Incident
   Scribe writes the after-action report.
4. **The dispatcher decides.** Route changes pass the safety rules, then wait for a dispatcher's
   approval before anyone is texted. Life-threat words put a human on the call, with a brief.

It runs on the same building and the same fire as the pre-plan:

- **One venue model.** `apps/api/app/creao/buildings/james_west.json` is generated from the
  engine's `packages/engine/venue.json` by `scripts/build_profile.py` (`cd apps/api && uv run
  python scripts/build_profile.py`; never edit the JSON by hand). Zones are venue spaces (grouped
  under the event map's names, with their venue space ids), exits are all 14 venue exits plus the
  stairs down from floor 2, and each zone's assumed occupant load (NFPA capacity from venue.json's
  default `2F_indoor` scenario, not a headcount) comes from venue.json. Floor 2 comes from the floor plan, not the scan, and is labelled that way. There is
  no assembly point: people are told to go outside, away from the building, where staff direct
  them.
- **The engine's fire.** Declaring a drill or fire with an `origin` runs Aria's building engine
  (`app.routes.engine.run`) for that start space: the fire model's steps (smoke and untenable
  times per zone, exit lost times), its summary (exits lost, rooms at risk, last group out) and each
  zone's route all come from the engine (`app/creao/engine_model.py`).

```
caller/texter ─ Photon + ElevenLabs (Sai) ─> POST /live/intake/events ─> TigerData
                                                                           │ pg_notify on insert
                         ┌─────────────────────────────────────────────────┤
                         ▼                                                 ▼
     dashboard: GET /live/stream (SSE)                 orchestrator ─ API Trigger ─> CREAO Commander
     + /situation, /report, approvals                                                 │ handoff_to_agent
                                                     aria-actions <── Intake · Coordinator · Accountability
                                                     (snapshot in, actions in each reply:   Liaison · Scribe
                                                      proposals, hazards, report sections)
```

Code: `apps/api/app/creao/` and `apps/api/app/routes/live.py`, wired in `app/main.py` (router,
lifespan, `/mcp` mount). The flood-era pre-plan agent (`/agent/*`) was deleted on Sun Oct 18.

## Run it locally (sandbox)

```bash
cd apps/api
docker run -d --name tiger-local -p 55432:5432 -e POSTGRES_PASSWORD=<pick one> timescale/timescaledb:latest-pg17
docker exec tiger-local psql -U postgres -c "CREATE DATABASE aria_live"
# apps/api/.env: CREAO_DATABASE_URL=postgresql+asyncpg://postgres:<password>@localhost:55432/aria_live
uv run python scripts/creao_standin.py --print-env >> .env   # rehearse the CREAO staff without CREAO
uv run uvicorn app.main:app --port 8000 --timeout-graceful-shutdown 5   # open SSE streams otherwise block shutdown
uv run python scripts/creao_standin.py                      # second terminal: scripted CREAO agents (no AI)
curl -N "http://localhost:8000/live/stream?building_id=547b5ec5-30c5-4f76-8080-012a52e90bd9"
```

To rehearse, declare a drill from the console (`/live/view`) and text the line from a real
phone: there is no scripted feed of invented people any more.

`GET /live/health` shows the database (TimescaleDB, hypertables, triggers, aggregate), whether the
TigerData LISTEN is connected, and which CREAO agents are configured. On the laptop with no keys
set, the endpoints are open; with `SENTRY_ENVIRONMENT=cloud` a missing key rejects every
protected call (the console and drills stay open; see "Open drills" below).

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
  or dispatcher. Someone who texts for the first time during an evacuation is counted as alerted
  and `reply.answer` carries the current instruction (`reply.first_contact` is true).
- **Calls:** ElevenLabs carries them. `call.started`, then the transcript lines as the call goes
  (polled from ElevenLabs), `call.transferred` when the agent hands the call to the dispatcher
  (its `transfer_to_number` tool, on a trigger word such as "trapped" or "can't breathe"), then
  `call.ended` with ElevenLabs' termination reason.
- **From the live stream:** `occupant.message` texts one person (the alert, an approved route
  change, or a dispatcher's re-send; one event per person, so a full venue never overflows a
  notification). Each carries `by` (`aria` or `dispatcher`, with the dispatcher's initials in
  `dispatcher`), `drill` (true unless the evacuation is live), `name` when known and `reason`
  (`alert`, `route_change`, `retext`). `occupant.call_requested` places the ElevenLabs call;
  `handoff.joined` tells the person a dispatcher is taking over.
- **The building brief:** `GET /live/buildings/{id}/brief` (open; no personal data)
  returns `{building, text, exits: [{id, label, floor}], stairs, assembly, updated_at}`: plain-text
  layout facts for the phone agent (floors and rooms with the event's names, every exterior exit,
  the stairs down, "elevators are not used in an evacuation", where to go once out), built from
  the generated profile. It claims no assembly point, refuge area or step-free route.
- **TigerData:** every text and call line, in and out, lands in the `comms_events` hypertable
  (with the reply intent and any trigger word) and the `comms_1m` continuous aggregate.

What people are told comes from the API and depends on who they are:

- **Unknown position:** the approved exits (only floor 2's stairs when they said "upstairs",
  "networking" or "workshops"), and a request to say where they are. A floor said outright
  ("second floor", "upstairs") beats a generic place on another floor: "second floor hallway"
  or "upstairs bathroom" is an unknown position on floor 2, not the Galleria or the ground-floor
  restrooms. "Entrance" and "front entrance" mean outside at check-in; "main entrance" and
  "front doors" name the doors.
- **Their zone's approved exit is fine:** that exit; on floor 2, the stair down and then the door
  the engine's route leaves by.
- **Their exit was just reported unsafe** (route change waiting for the dispatcher): avoid it, and
  use the other approved exits.
- **They asked for help:** help is coming, stay put if it's safe.
- **They're marked safe:** stay outside, away from the building, where staff direct them.

The James West profile is generated from `packages/engine/venue.json`; when the venue model
changes, run `scripts/build_profile.py` again. The messenger reads the same facts through the
brief.

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

## What the dashboard reads

**Open drills.** The console (`/live/view`, linked as "Live response ↗" from the building page
and the dashboard) and everything below work without a key: anyone can watch, declare a drill,
end it, approve routes, re-text, call, assign and take a handoff. The guardrails:

- **Live mode needs the dispatcher key.** Declaring `"mode": "live"`, ending a live evacuation
  and every action while a live one is running answer 401 without it. The console keeps the key
  in a small "Dispatcher key" menu (kept in that browser only); with an accepted key it offers
  Drill / Live fire.
- **One at a time.** Without a key, a declare is refused (409) while an evacuation is running
  (one public declare at a time per building, so two at once can't both pass).
- **Only the venue's own places.** A public declare must name an engine start space, a zone or an
  exit (422 otherwise), so the alert text only ever carries the venue's label; a hand-typed
  `fire_model` is ignored, and `description` / `dispatcher` are capped at 200 / 64 characters.
- **Only during a drill.** Without a key, approve/reject, re-text, call, acknowledge/assign and
  handoff answer 409 when no drill is running. A public "call" rings each person once per drill
  (409 after that); person actions are rate limited to 60 a minute per IP.
- **Drills end themselves** after `DRILL_MAX_MINUTES` (default 20), checked on each read, declare
  and action. Declares are rate limited to 10 a minute per IP.
- **Privacy.** Without a dispatcher key or `X-Tool-Secret`, every payload (situation, stream,
  reports, staff, route proposals, action replies) is masked: phone numbers become `•••• 1234`
  (fields, and free text with or without a `+`), emails keep only their domain, and people keep
  only their first name, including a caller who says "my name is ..." (`situation.mask_public`).
  `situation` carries
  `"viewer": "dispatcher" | "public"`. With the key or the tool secret, full data as before.
- **Still protected:** the intake and tool endpoints (`X-Tool-Secret`), `GET /occupants` and
  `/incidents`, hazards, `PUT /fire-model` (key or secret) and `/mcp` (`MCP_API_KEYS`). With
  `SENTRY_ENVIRONMENT=cloud`, a missing key still rejects those.

With a key: header `Authorization: Bearer <DISPATCH_API_KEYS entry>` (`?token=` for SSE).

| | |
|---|---|
| `GET /live/buildings/{id}/situation` | incidents (pins with anchor + priority), exits (open/hazard/predicted, heading, safe, share), flows, roll call, hazards, approved routes, route proposals, handoffs, fire model |
| `GET /live/buildings/{id}/flow?minutes=10` | people out per exit per 15 s (TigerData `evac_flow_15s` continuous aggregate) |
| `GET /live/stream?building_id=` | SSE: every change, streamed out of TigerData |
| `GET /live/buildings/{id}/report` (`.md`) | the live incident report, each section signed by its CREAO agent |
| `GET /live/buildings/{id}/staff` | the CREAO org chart: each agent's status and last task, handoffs, activity |
| `GET /live/incidents/{id}/report` | what opens when a pin is clicked: the incident, the person, the handoff brief, CREAO notes and actions on it, the signed report sections, the TigerData timeline |
| `GET /live/view` | the dispatch console: the scan with pins, exits and people, the CREAO report drawer, **Declare drill** (origin picked from `GET /engine/starts`, fast growth) and **End** (the console clears and the CREAO Scribe writes the after-action report), and the engine's fire summary (origin, exits lost and when, rooms at risk) under the header |
| `GET /live/buildings/{id}/after-action` (`.md`) | after a drill ends: the frozen facts from TigerData and the after-action report the CREAO Scribe writes |
| `POST /live/buildings/{id}/clear` | close leftover incidents and hazards and reset roll-call states once nothing is running (key needed after a live evacuation) |
| `GET /live/buildings/{id}/brief` | plain-text layout facts for the phone agent (see the messenger section) |
| `POST /live/buildings/{id}/evacuations`, `POST /live/evacuations/{id}/end` | declare / end a fire or drill: `{"mode": "drill", "origin": "140", "growth": "fast", "dispatcher": "AP"}` (origin: a venue space id or a place name) |
| `GET /live/buildings/{id}/route-proposals`, `POST /live/route-proposals/{id}/decision` | approve / reject (409 + `replacement` if stale) |
| `POST /live/buildings/{id}/hazards`, `/live/hazards/{id}/verify`, `/clear` | dispatcher hazards |
| `POST /live/incidents/{id}/acknowledge`, `/assign`, `/handoff/join`, `/handoff/resolve` | incident actions |
| `POST /live/occupants/{id}/retext`, `/call` | from the dispatcher's queue: re-send someone their approved route (`occupant.message`), or call them now (`occupant.call_requested`) |

Anchors are normalized in the profile's `frame` (the venue frame in metres: room 2's scan x, z;
elevation 0 = lobby 110's floor), taken from venue.json's polygons and opening positions; the
console maps them back with `world()` and places the scan by its recorded transform, so pins land
on the rooms they name.

## For Lincoln: the fire model

The fire model comes from the engine. Declare with an `origin`, or set it on a running evacuation:
`PUT /live/buildings/{id}/fire-model` with `{"engine": {"start": "140", "growth": "fast"}}`. The
API runs the engine (cached per start and growth, about 1-2 s the first time) and stores:

- `steps`: per zone, when smoke enters and when it becomes untenable (the engine's `fire.spaces`
  through the zone's venue spaces); per exit, when it is lost (`fire.exits`, or `fire.openings`
  for the inside stairs). `source: "aria-engine"`, `simulation: true`.
- `routes`: each zone's engine route (the capacity-aware `predictive` exit of its spaces) at each
  departure time (0, 1, 2, 3, 4, 5, 7 min). Routing uses the latest departure up to the minutes
  since the evacuation started; the nearest-safe-exit heuristic is only the fallback for a zone
  with no engine route, or when someone reports a hazard at the engine's exit. Floor 2 zones get
  the stair their route goes down, then the door it leaves by.
- `summary`: exits lost with times, occupied rooms and rooms at risk leaving now vs by the
  obvious way out, when the last group is out, and a sentence the console and the CREAO agents
  quote. Crowds are modelled at each room's assumed capacity (NFPA), not a headcount, so the
  console reports rooms, not people.

The API re-checks routes every 10 s while a fire model is active, so as exits are lost the rules
propose changes for the dispatcher to approve. A hand-typed model still works
(`{"label", "steps": [{"minute", "place", "kind"}]}`, `source: "manual"`): any exit it expects to
lose within 5 minutes is unsafe for routing. Shown everywhere as a simulation.

## CREAO setup

1. **Six agents** in CREAO, one per role (done: see the links below). Paste the instructions
   below. No connector: CREAO can't attach a custom MCP connector, so each run's inputs carry
   `snapshot` (the situation read from TigerData), `new_events` and `how_to`. The agent ends its
   reply with an `aria-actions` block, a JSON list of tool calls. When CREAO's callback reaches
   `POST /live/creao/run-result`, the API runs them through the same tool functions `/mcp` serves,
   safety rules included (`bridge.apply_actions`, at most 12 per run; once a drill has ended, a
   late reply may only write reports and notes).
2. In the API's env: `CREAO_API_KEY` (one `capi_` key starts all six; tested), the six
   `CREAO_APP_<ROLE>` ids (already in `.env.example`), `CREAO_WEBHOOK_TOKEN` and `PUBLIC_BASE_URL`.
3. Optional: `/mcp` (bearer = one of `MCP_API_KEYS`) still serves the same tools, for the local
   stand-in (`scripts/creao_standin.py`) or any MCP client.

**Cost control:** routine events are batched per building (`CREAO_DEBOUNCE_SECS`); a new routine
batch waits while the last Commander run is still working; a declared fire or a caller's first
handoff go at once; the staff's own actions never wake the staff again.

The tools (in an `aria-actions` block from CREAO, or over `/mcp`; the `get_*` reads are on `/mcp` only):

| Tool | Does |
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

| Role | CREAO agent | Agent ID |
|---|---|---|
| Incident Commander | [Aria · Incident Commander](https://agent.creao.ai/install/ef349685-a692-4a0d-ae20-eb2e1f524624?version=092e0321-8250-43be-83dc-38e5ae9aa893) | `ef349685-a692-4a0d-ae20-eb2e1f524624` |
| Intake Analyst | [Aria · Intake Analyst](https://agent.creao.ai/install/113efaf2-fd95-4ca2-9e84-3f3481309423?version=dfe9624c-ab7e-4c35-9b4e-478429eeb9cd) | `113efaf2-fd95-4ca2-9e84-3f3481309423` |
| Evacuation Coordinator | [Aria · Evacuation Coordinator](https://agent.creao.ai/install/e433f077-c48d-4080-8d6f-4ff771633c06?version=9b0e6560-468d-46f7-9a1a-cb89bf4d841b) | `e433f077-c48d-4080-8d6f-4ff771633c06` |
| Accountability Officer | [Aria · Accountability Officer](https://agent.creao.ai/install/2d6f125c-13a4-4872-a54d-0471491485f8?version=81c53a6e-fe89-4e14-90a0-8b0b547c2aaf) | `2d6f125c-13a4-4872-a54d-0471491485f8` |
| Responder Liaison | [Aria · Responder Liaison](https://agent.creao.ai/install/20ca703a-c164-48af-8752-69887706dd04?version=e4037f5d-ed3d-4dbf-a448-a20cf6e4411d) | `20ca703a-c164-48af-8752-69887706dd04` |
| Incident Scribe | [Aria · Incident Scribe](https://agent.creao.ai/install/db6d854b-42ed-4df9-be21-90131c53ec3e?version=473d1852-0321-46ff-8e91-8d1118848784) | `db6d854b-42ed-4df9-be21-90131c53ec3e` |

The Agent ID is the id in `/install/<id>`, the same id the API Trigger uses (`CREAO_APP_<ROLE>`).
Check it against the ID shown on each agent's page before submitting.

Run share link (Incident Commander): CREAO_RUN_SHARE_LINK · CREAO run id `e3b669dc-2e26-4529-a669-db8e787a160d`

The live API lists every run and action the staff took (public, phone numbers masked):
`GET https://aria-lahacks-production.up.railway.app/live/buildings/547b5ec5-30c5-4f76-8080-012a52e90bd9/staff`.
Its activity lines read "Started in CREAO (<run id>)" and "Aria ran N of M action(s) from the reply".

### Agent instructions

> In CREAO, each run's `inputs.how_to` overrides the tool-calling parts of these instructions.
> Reads come from `inputs.snapshot` (the situation read from TigerData) and `inputs.new_events`,
> not from `get_*` tools. Actions go in one `aria-actions` block at the end of the reply. The
> `get_*` tools are only on `/mcp` (the local stand-in).

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
