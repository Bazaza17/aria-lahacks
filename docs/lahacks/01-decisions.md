# Decisions so far

Only what Lincoln said explicitly. Anything not listed is open.

## Decided

- **Project:** Aria, built out for real at LA Hacks.
- **One-liner:** Aria turns a phone scan of a building into a fire pre-plan: how fire spreads, which exits stay open, how long everyone takes to get out, and a size-up for responders.
- **Team:** Lincoln plus two teammates who joined at the event.
- **Repo:** `Bazaza17/aria-lahacks` (public, MIT), at `Documents\GitHub\aria-lahacks`. Anything not ported over yet is in `Documents\GitHub\aria-lahacks-source`. `LICENSE`, `CONTRIBUTING.md` and `docs/` are tracked in git.
- **Focus:** the world model and making it accurate, and the agent exit analysis. How the fire actually affects the building is the priority.
- **Hazard:** fire is the only hazard for now. Flood is dropped as the second hazard (it makes little sense in LA), though not ruled out. Earthquake is the second hazard if there's time.
- **Building:** the venue (James West Alumni Center) replaces the hardcoded Miami building (The Dock).
- **Building input:** a Polycam scan of the building (the most important piece), its floor plan, and its address and other details.
- **Capture order:** Polycam scan → export → floor plan. Nothing is captured yet (Sat afternoon).
- **Floor plan source:** online; if none turns up, Lincoln draws it. Found Sat evening: a photo of the building's fire alarm annunciator (room numbers, stairs and alarm devices for floors 1–3) and the LA Hacks event map (room names). Both are in `docs/lahacks/img/`.
- **Scans so far:** three Polycam room scans (Sat evening), not uploaded yet; Lincoln is scanning more rooms first. Room 1 findings are in `10-scan-room1.md`.
- **World model source:** the scan plus the floor plan.
- **Exit analysis:** routes first, then a crowd sim on top.
- **Architecture:** no new API. The engine is a plain Python library in `packages/engine` (no HTTP inside it). The existing FastAPI app in `apps/api` stays the one backend the web app calls; it imports the engine and gets new routes only when the viewer needs them. The API's Dockerfile has to be able to see `packages/engine` once it imports it.
- **Agent tools:** no more fixed data. The current stubs (Street View, satellite, flood zone, surge zone, nearby assets) get replaced by tools that call the engine or real sources.
- **Bar:** it all has to be technically impressive, not just working.
- **Agents:** an orchestrator plus 4 specialists: world model, hazard, evac sim, report.
- **Database:** a new Supabase project replaces Aria's: ref `sntyqjzoyjfgrjesguvs` in the `aria-lahacks` org (us-east-1, named "lincolnwbazail@gmail.com's Project"). Set up Sat Oct 17: migrations `0001`, `0002`, `0004`, the public `scans` bucket, and the venue row. **Venue ID: `547b5ec5-30c5-4f76-8080-012a52e90bd9`**; it takes The Dock's place. The Miami placeholder row is kept with `is_demo = false`. The project auto-enables RLS on new tables, so any new table the web app reads needs a select policy.
- **Mapbox:** a new public token for this repo, not Aria's.
- **Venue coordinates:** Lincoln pastes them from Google Maps.
- **Main track:** Applied Intelligence.
- **Hosting:** agents run on the laptop first and on a cloud host by Sunday.
- **Build order:** engine first (world model, routes, hazards, crowd sim), then wrap it in the agents.
- **Sentry:** entered. Set it up at the start and make it strong; plan in `05-plan.md`. DSN slots go in the env files now; the SDK comes later.

## Leaning toward

- **Ownership:** Lincoln on the engine, since he's also doing the scan and the floor plan. The rest of the split gets decided with the team.
- **Fetch.ai ASI:One challenge:** fading. Lincoln doesn't see how a marketplace-listed agent fits Aria. `apps/agents` still has the uAgents setup.
- **Other tracks:** many of the MLH challenges, plus Creao, Photon and ElevenLabs. Note: `03-tracks.md` marks Creao as a conflict because a Creao agent has to do the core work.
- **Add-ons to stack with the team as the build allows:** earthquake, a GoDaddy domain, Gemini or ElevenLabs, Vultr or Solana.
- **If time allows:** a Model Learning surrogate model, a Solana report hash.
- **Channels:** a web viewer, and maybe text messages for reports.
- **Payments:** not a focus; something with Solana only if it's possible.
- **Paper's design prize:** probably crowded, since many teams will go for it.
- **Agents:** no fixed cutoff for starting them, but not too late.

## Open

- Who owns which part beyond Lincoln on the engine
- The demo flow (the 3–5 steps judges see)
- Which models do what (with the team)
- The agent framework, now that Fetch.ai is fading (uAgents is what's set up)
- The ASI:One flow, only if Fetch.ai stays
- How the floor plan becomes the graph (hand-trace, a vision model, or from the scan; `04-build-options.md`)
- Crowd sim style: flow model, agent-based, or both. Lincoln will discuss it with the team; all the options stay in `04-build-options.md`.
- Which company challenges to enter, including whether Creao can fit. No hard lock; preference for recruiting benefits and good cash prizes (quick view in `03-tracks.md`). As a team, the Commit Fellowship is now possible.
- Whether and how to use Devin
- How each specialist agent works inside
