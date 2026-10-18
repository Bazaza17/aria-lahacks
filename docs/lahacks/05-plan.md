# Draft plan

> A starting point to plan with Claude Code. It's built from `01-decisions.md`. Decided items are marked; the rest is open.

## The goal

Aria, built out for real on a real building (the venue): scan + floor plan → world model → fire → routes and a crowd sim → a report for responders, with company and sponsor tracks brought in as the build takes shape. Team of three.

## Phases

The order matters more than the times. Decided: engine first, so phases 2–5 come before the agents.

0. **Move off the Miami specifics:** the new Supabase project, the venue instead of The Dock, the map centered on the venue (`07-changes.md`).
1. **Data:** capture the venue (scan, floor plan, address and details). Checklist: `06-venue-data.md`.
2. **World model:** floor plan + scan → a building graph lined up with the scan.
3. **Routes:** safe paths from every room to every exit.
4. **Hazards:** a fire timeline on the graph (flood as a second hazard is open).
5. **Crowd sim:** clearance times and bottlenecks, on top of the routes.
6. **Agents:** orchestrator + world model, hazard, evac sim and report agents, with the full flow working in ASI:One.
7. **Viewer and report:** the existing 3D viewer and report showing the computed results.
8. **Cloud:** move the agents to a cloud host by Sunday.
9. **Submission:** video, README, Devpost, and each track's deliverables.

## Decisions

Decided: engine first, MIT license, Sentry entered (plan below), fire only (flood dropped; earthquake second if time), capture order scan → export → floor plan, floor plan from online or drawn by Lincoln.

Still to make:

- **Split:** Lincoln leans toward the engine (he's also doing the scan and floor plan); the rest with the team. Separate folders let three people work in parallel (see Parallel sessions in `CLAUDE.md`).
- **Demo flow:** the 3–5 steps judges see.
- **Floor plan → graph:** hand-trace it, have a vision model read it, or derive it from the scan (`04-build-options.md`).
- **Crowd sim style:** flow model, agent-based, or both; Lincoln will discuss with the team. How the fire affects the building comes first.
- **Models:** which one does what (with the team).
- **Agent framework:** Fetch.ai is fading, so uAgents + ASI:One is no longer a given.
- **Other tracks:** no hard lock. Interested in many MLH challenges, Creao, Photon and ElevenLabs (quick view in `03-tracks.md`).
- **Agent cutoff:** no fixed time, but not too late. With engine first, the agents are the late risk.

## First slice (Sat afternoon)

The smallest end-to-end path: the real venue, a real fire, visible in the existing viewer. Items marked open above stay open; this only orders the work.

1. **Setup (done this session):** the new Supabase project (migrations, `scans` bucket, venue row), the new Mapbox token with the dashboard centered on the venue, the env files with Sentry slots.
2. **Capture (Lincoln):** Polycam scan of the hacking floors, every exit and the stairs between them → export GLB under 50 MB → upload to the `scans` bucket → set the venue row's `scan_url`. Then the floor plan (online, or drawn), with one measured door or corridor for scale.
3. **Engine, slice 1:** the venue's building graph (rooms, doors, exits, widths) for the demo floor, then a fire timeline from one start room showing when each room and door becomes untenable. This is the priority.
4. **Engine, slice 2:** routes from every room to every exit that block as the fire reaches them, as JSON the viewer can read.
5. **Viewer:** the venue scan loads at `/building/<venue id>`, with the engine's exits and routes for the venue in place of the hand-placed table.

Crowd sim, agents, the report and the extra tracks come after this slice works.

Later (Lincoln's idea, not urgent): in the viewer/dashboard, a layer toggle — the 3D scan, the annunciator plan image laid flat under it, and the venue graph (rooms, doors, exits, routes) — all in the same venue frame, so they line up.

## Rough time budget

A sketch to argue with, not a schedule. Hacking runs 24 hours, Sat 12:00 PM to Sun 12:00 PM.

| Block | Rough hours |
|---|---|
| Data capture | ~1 |
| World model + routes | ~5 |
| Hazards + crowd sim | ~4 |
| Agents end to end (in ASI:One only if Fetch.ai stays) | ~4 |
| Viewer + report | ~3 |
| Submission (feature freeze around Sun 9 AM) | ~2.5 |
| Sleep, buffer, extra tracks | the rest |

## Day-one setup per track (only for tracks you enter)

| Track | Set up at the start | Why at the start |
|---|---|---|
| Fetch.ai (fading) | Agentverse and ASI:One accounts; register on the LA Hacks ASI:One Submission Agent; run `apps/agents/hello_agent.py` end to end | Every agent has to be registered and reachable, and the shared chat URL and profile URLs are deliverables |
| Sentry (entered) | Two Sentry projects; the SDK in the API, agents, engine and web app (plan below) | It's judged on how observability shaped the build, so the moments have to happen during the build |
| Devin | Claim the free credits; connect Devin to the GitHub repo after the push | Devin works through the repo |
| Photon | Sign up for the Photon 2.0 beta and add a channel (iMessage or an SMS number) | — |
| Solana | A devnet wallet funded from the faucet | — |
| GoDaddy | Get the domain code from MLH (email or the opening ceremony) | — |
| Gemini, ElevenLabs | API keys or MLH credits | — |

## Sentry plan

Entered. Judges want to see how observability shaped the build, so setup goes in at the start and the proof gets collected all weekend.

### What to use, and where

| Product | Where | What it shows |
|---|---|---|
| Tracing | Viewer → API → orchestrator → each specialist agent | One trace per pre-plan request, so a slow or failing step stands out. Agent messages don't carry trace context on their own: send the `sentry-trace` and `baggage` values inside each message and continue the trace in the agent that receives it. |
| AI agent monitoring | Every agent and every Claude call | The Anthropic integration records each Claude call with its tools and tokens. Wrap each agent's work in an "invoke agent" span and each tool in an "execute tool" span so Sentry's Agents dashboard shows the whole pipeline. |
| Profiling | Engine: routing and the crowd sim | Finds the slow code when the sim runs on the real building. |
| Logs | Engine and agents | Structured logs per sim run (building, hazard, clearance times, blocked exits) and per agent step, searchable by those fields. |
| Session Replay | Web viewer | Catches broken viewer flows: scan loading, playback, the report. |
| Uptime Monitoring | The agents' health check on the cloud host | Shows the agents stay up after the event, which Fetch.ai also rewards. |

### Set up at the start

1. Create two Sentry projects: Python (API, agents, engine) and Next.js (web).
2. Python: `sentry-sdk` 2.35.0 or later; `sentry_sdk.init(dsn=..., traces_sample_rate=1.0, send_default_pii=True)`, with profiling turned on (check the current option name in Sentry's Python profiling docs). The Anthropic integration turns on by itself when the `anthropic` package is installed. Logs go through `sentry_sdk.logger`.
3. Web: run `npx @sentry/wizard@latest -i nextjs` in `apps/web`, then turn on Session Replay and Tracing.
4. DSNs go in the `.env` files, never in git. Tag events with an environment (`laptop` or `cloud`).
5. Optional: connect Sentry's MCP server to Claude Code so it can read issues and traces while fixing bugs.

### The proof (this is the submission)

- Keep a running list: a screenshot and one line for every time Sentry showed you something and you changed the code because of it, with before/after numbers where you have them.
- Aim for 3–5 strong moments. Watch for a slow specialist in a trace, a hot loop in a profile, a log search that pins down a wrong route, a replay of the viewer breaking, an uptime alert when the cloud agents went down.
- Devpost gets a "How Sentry shaped Aria" section built from that list.

## Keep track as you go

- **Sentry moments:** screenshot the trace, replay or log whenever it helps you fix something, with one line on what you found. These are the Sentry submission.
- **Fetch.ai:** save the ASI:One shared chat URL and each agent's Agentverse profile URL.
- **Build log:** Obsidian `03 Build Log`, for the Devpost "challenges" section.

## First message for Claude Code

> Read `CLAUDE.md` and `docs/lahacks/00-start-here.md`, then everything it links. Summarize the goal and the changes in `07-changes.md` back to me in a few lines. Then do the kickoff in `CLAUDE.md`: ask me everything that's still pending, then help me set up the new Supabase project, Mapbox and the env files. No feature code until I say go.
