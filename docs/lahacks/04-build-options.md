# Build options

Options only. Decided items are marked "decided"; everything else is open (see `01-decisions.md`). Effort numbers are rough guesses.

## World model (decided: from the scan + floor plan)

| Option | How | Trade-off |
|---|---|---|
| Hand-trace the plan | Mark rooms, doors, exits and stairs from the floor plan in a JSON graph, then line it up with the scan | Most reliable; least automatic |
| Vision reads the plan | A vision model turns the floor plan image into the graph; fix its mistakes by hand | Works on any building; needs checking |
| Geometry from the scan | Compute the walkable floor, walls and openings from the mesh | Most technical; most time |

- Lining the plan up with the scan: pick 2–3 points visible in both (corners, doors) and solve for scale, rotation and offset.
- Worth capturing per element: room area and floor elevation, door and corridor widths (they set how many people get through), exit type, stairs.

## Exit analysis (decided: routes first, crowd sim on top)

- **Routes:** the safest path from every room to every exit, with costs that rise as the hazard spreads. Output per route: open, partial or blocked, plus the safest way in for crews.
- **Crowd sim options:**
  - Flow model: people in each room move along routes, and each door or corridor passes a set number of people per second per unit of width (standard egress-engineering flow rates). Fast and easy to explain.
  - Agent-based: each person moves on their own and slows in crowds. Looks great on playback; slower to build.
- **Outputs judges understand:** time to clear each exit, bottleneck doors, people still inside at a given minute, and how those change as the hazard spreads.

## Hazards (decided: fire is the main hazard; flood as a second is open; earthquake as a stretch)

| Hazard | Simple model | Effect on the graph |
|---|---|---|
| Fire and smoke | Spreads room to room over time from a start room, faster through open doors | A room becomes untenable at some time; its paths slow, then block |
| Flood | Water rises at a set rate; each spot's floor elevation from the scan decides when it's under water | Depth past a threshold slows, then blocks, paths |
| Earthquake (stretch) | Shaking at the site (USGS live feed or a scenario quake) sets the odds that each stair, exit or glass wall fails | Randomly blocked paths; run many times to get odds |

## Agents (decided: orchestrator + world model, hazard, evac sim, report)

- The orchestrator talks to ASI:One through the Agent Chat Protocol, parses the request, calls the specialists, handles their failures and replies.
- Open: message formats between agents; whether the report uses ASI Interactive Cards; how results reach the web viewer (API, Supabase or files).
- Fetch bonus items to weigh: multi-agent collaboration, Payment Protocol, Interactive Cards, error recovery, real-time data, an agent that keeps running after the event.
- `apps/agents/hello_agent.py` was a working Chat Protocol pattern to copy. (Deleted Sun Oct 18 with the rest of `apps/agents`; it is in git history.)

## Models (open)

- Reasoning and the report: Claude (the current loop uses it), Gemini or ASI-1.
- Reading the floor plan, if vision is used: Claude, Gemini or Step 5 Preview.

## Channels

- ASI:One chat: required for Fetch.ai.
- Web viewer (leaning): the existing 3D viewer showing computed routes and sim playback.
- Text reports (maybe): Photon over iMessage or SMS.

## Hosting (decided: laptop first, cloud by Sunday)

- Laptop: agents connect to Agentverse through a mailbox. The laptop has to stay awake and online.
- Cloud options: Railway (where Aria's API runs now), Vultr (MLH prize) or Agentverse-hosted agents.

## Stretch and add-on options

| Option | What | Rough effort |
|---|---|---|
| Sentry (entered) | Tracing, AI agent monitoring, Profiling, Logs, Session Replay and Uptime Monitoring; full plan in `05-plan.md` | ~1 hr setup at the start, then save moments as they happen |
| Surrogate model (leaning) | Train on many sim runs to predict clearance times instantly; show its error vs. the full sim | 3–5 hrs |
| Solana report hash (leaning) | Write each pre-plan's hash to devnet as a tamper-proof record | ~1 hr |
| Earthquake | See hazards above | 2–4 hrs |
| Real data tools | Replace the stubs with FEMA flood zones, USGS quakes, NWS alerts and OpenStreetMap (none need API keys) | 1–3 hrs |
| Devin | Hand off self-contained work (real data tools, viewer overlays, deploy) through GitHub pull requests | Your review time |
| Voice | ElevenLabs reads the size-up | Under 1 hr |
| Domain | GoDaddy Registry domain | 10 min |
