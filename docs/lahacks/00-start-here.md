# LA Hacks AI Hackathon 2026 — start here

Context for Claude Code sessions on Aria during LA Hacks AI Hackathon 2026: Sat Oct 17, 12:00 PM to Sun Oct 18, 12:00 PM PDT, James West Alumni Center, UCLA.

These notes live in three places with the same content: this repo (`docs/lahacks/`), `C:\Users\lincb\Documents\LA_hacks\context\`, and Obsidian (`LA Hacks/Claude Context/`, where the tracks table is the note `07 Track Map`).

## Submission (Sun Oct 18, due 12:00 PM)

- `15-devpost.md`: the Devpost draft (what it does, built at the event, the CREAO and Sentry sections, prize opt-ins)
- `05-plan.md`, "Submission checklist": what's done and what still needs a person
- `08-sentry-moments.md`: the Sentry moments and the "How Sentry shaped Aria" section

## Read in this order

0. Root `README.md` and `docs/creao-layer.md`: what runs now (engine, live layer, CREAO staff). `02-aria-today.md` is historical.
1. `01-decisions.md`: what's decided, what's leaning, and what's still open
2. `07-changes.md`: what changes from the Miami version (flood → fire, the hardcoded building, the map, the new Supabase project), with the files involved
3. `02-aria-today.md`: what was in the codebase when it was ported from Miami (historical)
4. `05-plan.md`: phases, decisions still to make, a rough time budget, the Sentry plan
5. `04-build-options.md`: options for the world model, exit analysis, hazards, agents and stretch work
6. `03-tracks.md`: every track and prize, what it needs, how it's judged, and how Aria could fit
7. `06-venue-data.md`: what to capture at the venue
8. `09-engine-research.md`: what already exists for each engine piece (install-tested), with options for the open decisions
   - `10-scan-room1.md` and `11-venue-plan-and-scans.md`: what the first scans and the venue's floor plans show, and what to scan next (`venue-plan-inventory.json` is the plan as data)
9. `08-sentry-moments.md`: the Sentry moments for the write-up
10. `12-handoff.md`, `13-engine-plan.md`, `14-restyle-wiring-plan.md`: the engine handoff notes, the engine accuracy plan, and the Paper restyle plan for `apps/web`
11. `C:\Users\lincb\Documents\LA_hacks\LA_Hacks_AI_Hackathon_2026.md`: full event info (schedule, submission, Fetch.ai details). Its MLH prize list is out of date; `03-tracks.md` has the event's own list.

## First message for Claude Code

(Used at kickoff on Sat; setup is done.)

> Read `CLAUDE.md` and `docs/lahacks/00-start-here.md`, then everything it links. Summarize the goal and the changes in `07-changes.md` back to me in a few lines. Then do the kickoff in `CLAUDE.md`: ask me everything that's still pending, then help me set up the new Supabase project, Mapbox and the env files. No feature code until I say go.

## How Lincoln works

- Do only what he explicitly asks. Propose options; he decides.
- Don't lock in tracks, features or architecture he hasn't chosen. Open items in `01-decisions.md` stay open until he says otherwise.
- Be brief and direct.

## Key times (PDT)

| When | What |
|---|---|
| Sat 12:00 PM | Hacking starts |
| Sat 1:00 PM | Fetch.ai workshop, 2nd Floor Patio |
| Sat 7:00 PM | Cognition (Devin) workshop, 2nd Floor Patio |
| Sun 12:00 PM | Hacking ends, submissions due |
| Sun 12:30 PM | Judging, Collins Conference Room (must be there in person) |

## Rules that matter most

- Pre-existing work is allowed only if it's open source, and the submission must say exactly which features were built at the event. Judges score only the new work.
- No code after Sun 12:00 PM.
- Every submission needs a public repo, a 2–3 minute demo video and a complete Devpost page. (Fetch.ai, which asked for 3–5 minutes, is dropped.)
- CREAO also needs: the README names the agent ID and a share link to one of its runs, and the demo shows the agent running.
- As of Sun ~11 AM the repo (and the `Aria-miami` source it was ported from) is private; both must be public before submitting.
