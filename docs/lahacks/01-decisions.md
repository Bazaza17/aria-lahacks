# Decisions so far

Only what Lincoln said explicitly, plus (Sun Oct 18, ~11 AM) what the built code now settles. Anything not listed is open.

## Decided

- **Project:** Aria, built out for real at LA Hacks.
- **One-liner:** Aria turns a phone scan of a building into a fire pre-plan: how fire spreads, which exits stay open, how long everyone takes to get out, and a size-up for responders.
- **Team:** Lincoln plus two teammates who joined at the event.
- **Repo:** `Bazaza17/aria-lahacks` (MIT; private as of Sun Oct 18 ~11 AM and must be made public before submitting, after a leaked-keys check), at `Documents\GitHub\aria-lahacks`. Anything not ported over yet is in `Documents\GitHub\aria-lahacks-source`. `LICENSE`, `CONTRIBUTING.md` and `docs/` are tracked in git.
- **Focus:** the world model and making it accurate, and the agent exit analysis. How the fire actually affects the building is the priority.
- **Hazard:** fire is the only hazard for now. Flood is dropped as the second hazard (it makes little sense in LA), though not ruled out. Earthquake is the second hazard if there's time.
- **Building:** the venue (James West Alumni Center) replaces the hardcoded Miami building (The Dock).
- **Building input:** a Polycam scan of the building (the most important piece), its floor plan, and its address and other details.
- **Capture order:** Polycam scan → export → floor plan. Nothing is captured yet (Sat afternoon).
- **Floor plan source:** online; if none turns up, Lincoln draws it. Found Sat evening: a photo of the building's fire alarm annunciator (room numbers, stairs and alarm devices for floors 1–3) and the LA Hacks event map (room names). Both are in `docs/lahacks/img/`.
- **Scans so far:** four Polycam room scans (Sat evening): Galleria far end, lobby 110 + entrance, Founders' Room + Patio, Collins Room. Not uploaded yet; Lincoln is scanning more rooms first. Findings are in `10-scan-room1.md` and `11-venue-plan-and-scans.md`.
- **Scanning is done** (dark outside, Sat ~10 PM). The four 1st-floor scans plus the fire alarm annunciator plan are the data; the rest of the building, including the 2nd floor, comes from the plan.
- **Engine:** build on the teammate's draft in `packages/engine/engine/` (a cited zone model in `fire.py`). Our `venue.json` feeds it through an adapter, routes are added on top, and the draft will be iterated to be more realistic.
- **No tape measurements.** Door and opening widths come from the scans where they can be measured, otherwise realistic standard values (single door 0.9 m, double door 1.8 m and so on), marked as placeholders.
- **World model source:** the scan plus the floor plan.
- **Exit analysis:** routes first, then a crowd sim on top.
- **Architecture:** no new API. The engine is a plain Python library in `packages/engine` (no HTTP inside it). The existing FastAPI app in `apps/api` stays the one backend the web app calls; it imports the engine and gets new routes only when the viewer needs them. The API's Dockerfile has to be able to see `packages/engine` once it imports it.
- **Agent tools:** the flood-era agent and its stub tools were deleted Sun Oct 18. The live agents' tools are the CREAO actions in `docs/creao-layer.md`.
- **Bar:** it all has to be technically impressive, not just working.
- **Agents:** an orchestrator plus 4 specialists: world model, hazard, evac sim, report. (Superseded Sun Oct 18: the engine does the world model, fire and routes as plain code, and the agents are the CREAO command staff below.)
- **Database:** a new Supabase project replaces Aria's: ref `sntyqjzoyjfgrjesguvs` in the `aria-lahacks` org (us-east-1, named "lincolnwbazail@gmail.com's Project"). Set up Sat Oct 17: migrations `0001`, `0002`, `0004`, the public `scans` bucket, and the venue row. **Venue ID: `547b5ec5-30c5-4f76-8080-012a52e90bd9`**; it takes The Dock's place. The Miami placeholder row is kept with `is_demo = false`. The project auto-enables RLS on new tables, so any new table the web app reads needs a select policy.
- **Mapbox:** a new public token for this repo, not Aria's.
- **Venue coordinates:** Lincoln pastes them from Google Maps.
- **Main track:** Applied Intelligence.
- **Hosting:** agents run on the laptop first and on a cloud host by Sunday. As built: web on Vercel (https://aria-lahacks.vercel.app), API on Railway (https://aria-lahacks-production.up.railway.app), the CREAO agents on agent.creao.ai, the messenger on Sai's machine.
- **Build order:** engine first (world model, routes, hazards, crowd sim), then wrap it in the agents.
- **Cleanup (Sun Oct 18, ~4 AM):** the flood-era Claude pre-plan agent (`apps/api/app/agent`, `app/tools`, `/agent/*`, the replay prewarm script), `apps/agents` (Fetch.ai boilerplate) and migration `0003_the_dock.sql` are deleted. The engine's `venue.json` is the single venue model; the 2F event use is read as indoors (`2F_indoor`). No invented facts in anything people are told: no named assembly point, no area of refuge, no step-free claims, elevators not used.
- **Sentry:** entered. Set it up at the start and make it strong; plan in `05-plan.md`. As built: Tracing, Session Replay, Logs and Profiling; moments in `08-sentry-moments.md`.
- **Live layer: the CREAO command staff (Sun Oct 18).** Six CREAO agents built on agent.creao.ai (Incident Commander, Intake Analyst, Evacuation Coordinator, Accountability Officer, Responder Liaison, Incident Scribe) run the live response. TigerData's pg_notify wakes the Commander through its API Trigger; each agent ends its reply with an `aria-actions` block that the API runs through the safety rules; the dispatcher approves every route change. Details, agent IDs and links: `docs/creao-layer.md`.
- **Creao:** entered. Six CREAO agents run the live layer; the README carries the Commander's agent ID (`ef349685-a692-4a0d-ae20-eb2e1f524624`) and a run share link, and the demo shows a run.
- **Fetch.ai / Agentverse:** dropped. `apps/agents` (uAgents) was deleted Sun Oct 18; there is no ASI:One flow.
- **Live database:** TigerData (Tiger Cloud): hypertables, continuous aggregates and pg_notify for the live layer. Supabase keeps the venue row and the scan mesh.
- **Messenger:** Photon texts and ElevenLabs calls (`apps/messenger`), joined to the live layer.
- **Ownership (as built, per git):** Lincoln: engine, scan, floor plan and web. Aayush Pal: the CREAO live layer, the API and TigerData. Sai: the messenger (Photon + ElevenLabs).
- **Demo flow (`CLAUDE.md`):** scan → pick where the fire starts → the engine shows smoke, lost exits and routes → declare the drill on the live console → the CREAO staff and the messenger text/call people with the engine's routes, and the dispatcher approves.
- **No invented numbers:** the UI reports rooms, not headcounts. Crowds are modelled at each room's assumed (NFPA) capacity, never shown as real people counts.

## Leaning toward

- **Other tracks:** many of the MLH challenges, plus Photon and ElevenLabs (both built into the messenger) and Tiger Data (the live layer's database). Opt-ins beyond Creao and Sentry aren't decided; `03-tracks.md` has the fit for each.
- **Add-ons to stack with the team as the build allows:** earthquake, a GoDaddy domain, Gemini or ElevenLabs, Vultr or Solana.
- **If time allows:** a Model Learning surrogate model, a Solana report hash.
- **Channels:** a web viewer, and maybe text messages for reports.
- **Payments:** not a focus; something with Solana only if it's possible.
- **Paper's design prize:** probably crowded, since many teams will go for it.

## Open

- Which models do what (with the team)
- How the floor plan becomes the graph (hand-trace, a vision model, or from the scan; `04-build-options.md`)
- Crowd sim style: flow model, agent-based, or both. Lincoln will discuss it with the team; all the options stay in `04-build-options.md`.
- Which other prizes to opt into on Devpost, beyond Creao and Sentry. No hard lock; preference for recruiting benefits and good cash prizes (quick view in `03-tracks.md`). As a team, the Commit Fellowship is now possible.
- Whether and how to use Devin

Settled Sun Oct 18 (moved to Decided): ownership, the demo flow, the agent framework (CREAO), the ASI:One flow (dropped with Fetch.ai), how each specialist agent works (its CREAO instructions are in `docs/creao-layer.md`).
