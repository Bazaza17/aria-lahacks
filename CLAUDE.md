# CLAUDE.md — Hackathon Mode

> Built from `hackathon-CLAUDE.md`. Brackets are choices Lincoln hasn't made yet; fill them in as he decides.

## The Project

- **Name:** Aria
- **One-liner:** Aria turns a phone scan of a building into a fire pre-plan: how fire spreads, which exits stay open, how long everyone takes to get out, and a size-up for responders.
- **Demo flow:** scan → pick where the fire starts → engine shows smoke, lost exits and routes → declare the drill on the live console → agents text/call people with engine routes, dispatcher approves.
- **Deadline:** Sun Oct 18, 12:00 PM PDT. Judging at 12:30 PM, in person.
- **Goal:** win. Main track: Applied Intelligence. Other company challenges are open, favoring recruiting benefits and good cash prizes (`docs/lahacks/03-tracks.md`).
- **Sentry:** entered. Set it up at the start and collect the "moments" all weekend (plan in `docs/lahacks/05-plan.md`).
- **Team:** Lincoln plus two teammates. Lincoln leans toward the engine (he's also doing the scan and floor plan). [the rest of the split; see Parallel sessions]
- **Build order:** engine first (world model → routes → fire timeline → crowd sim), then the live layer: CREAO command staff, messenger and the dispatcher console, fed by the engine.
- **Stack:** Next.js 16 + React 19 + Tailwind 4 + Three.js + Mapbox (`apps/web`, Vercel); FastAPI (`apps/api`, Railway) serving the engine on demand (`/engine/*`) and the CREAO live layer (`/live/*`, `/mcp`, TigerData); the engine in `packages/engine` (venue.json, fire, smoke, exits, routes); the messenger in `apps/messenger` (Photon texts + ElevenLabs calls, on a teammate's machine); Supabase (`infra/supabase`) for the venue row and the scan mesh.
- **Context:** `docs/lahacks/`. Start with `00-start-here.md`; what's decided and what's open is in `01-decisions.md`.

## What changes from the Miami version

The code came from Aria's Miami build. This weekend:

- **Flood → fire.** Fire is the main hazard. The flood-era Claude pre-plan agent (prompt, report schema, tools, replay cache) has been removed from the API; the engine replaces it.
- **The Dock → the venue.** The venue (James West Alumni Center, UCLA) replaces the one hardcoded Miami building. The venue row is `547b5ec5-30c5-4f76-8080-012a52e90bd9` (`infra/supabase/migrations/0005_venue.sql`, `NEXT_PUBLIC_VENUE_BUILDING_ID`).
- **The map.** Done: the dashboard map centres on the venue and the landing-page globe faces Los Angeles.
- **Supabase.** A new project replaces Aria's.

Every file involved, plus the Supabase steps: `docs/lahacks/07-changes.md`.

## Kickoff: questions first, then setup

At the start of the first session, and whenever I say **"questions"**:

1. **Ask me everything that's still pending** so we can narrow the plan: the Open list in `docs/lahacks/01-decisions.md`, "Still to make" in `docs/lahacks/05-plan.md`, the brackets in this file, and what venue data I have so far (`docs/lahacks/06-venue-data.md`). Ask lots of questions, a few at a time, multiple choice where it fits (the AskUserQuestion tool), with your recommendation first when you have one. Write my answers into `01-decisions.md`, then narrow `05-plan.md` into a concrete first slice.
2. **Then do the setup.** Every step is in `docs/lahacks/07-changes.md`:
   - The new Supabase project: migrations `0001`, `0002`, `0004` and `0005` (the venue row; see `infra/supabase/README.md`), and the public `scans` bucket. If you can reach the database (Supabase MCP, CLI or `psql`), run it; otherwise give me the SQL to paste into the SQL editor.
   - Mapbox: the token in `apps/web/.env.local`, and the dashboard map centered on the venue instead of Miami.
   - The env files for web, API and messenger.

   Ask me for each value you need (project URL, keys, coordinates, Mapbox token). Secrets go only in the gitignored env files; never commit them or repeat them back.

## Commands

- Env files: copy each `.env.example` to `apps/web/.env.local`, `apps/api/.env` and `apps/messenger/.env`. A real `apps/api/.env` points at the shared live database: don't run the API locally with it unless you mean to.
- Web: `pnpm --dir apps/web dev` → http://localhost:3000
- API: `cd apps/api && uv run uvicorn app.main:app --reload --reload-dir app --port 8000`
- Both at once: `pnpm dev` (it runs `apps/api/dev.sh`, so it needs a bash shell)
- Checks: `pnpm check` (web lint, format, typecheck and unit tests; API ruff and pytest)
- Engine: `cd packages/engine && uv run python -m engine.demo --start 140 --summary`, tests `uv run pytest -q`
- Messenger: `apps/messenger/README.md`

## Rules for this repo

- No code after Sun 12:00 PM.
- The Devpost submission must say which features were built at the event; judges score only those.
- Use only this repo's own Supabase, Vercel and Railway projects. Never point it at the original Aria's live services, and never push to `Bazaza17/aria-miami`.
- Scan meshes (USDZ, GLB) go in Supabase Storage, never in git.

## Hackathon Mode — Priorities

This is a time-boxed hackathon. These instructions override the global ECC rules where they conflict:

1. **A working, deployed demo beats everything.** Optimize for the demo flow above working end to end.
2. **TDD and 80% coverage are NOT required.** Skip writing tests unless I ask, or for one critical piece of logic that keeps breaking.
3. **Don't auto-spawn review agents after every change.** Only run reviewers (`code-reviewer`, `security-reviewer`, etc.) when I ask, or before the final submission.
4. **Smallest change that works.** No refactors, abstractions, or "nice to have" architecture unless they unblock the demo.
5. **Ship in thin slices.** Get each feature working end to end before polishing anything.
6. **Mock what's slow.** If an external API or feature would take more than ~30 minutes, propose a mock or hardcoded fallback first.
7. **Keep the app runnable at all times.** After each change, make sure it still builds (`pnpm --dir apps/web build`) and the API still starts. If something breaks, fixing it is the top priority.
8. **Commit often** with short conventional messages (`feat:`, `fix:`) so we can roll back.

## ECC

My global ECC setup (agents, skills, commands and the GateGuard hook) is installed. The priorities above override its rules where they conflict.

- **Commands I drive with:** `/plan-prd` and `/plan` to plan; `/orch-add-feature`, `/orch-change-feature` and `/orch-fix-defect` for features and bugs; `/build-fix` (`/react-build` for Next.js build failures); `/code-review`, `/prp-commit` and `/pr`. For long runs, `/goal` and `/loop`.
- **Skills to use when they fit:** `browser-qa` for "demo check"; `documentation-lookup` for current docs (Next.js 16, React 19, Mapbox GL, Supabase, uAgents); `council` when we're stuck between two approaches; `frontend-design-direction` and `make-interfaces-feel-better` for UI polish; `frontend-slides` for the pitch deck; `tdd-workflow` only for logic that keeps breaking.
- **Agents:** `security-reviewer` for the leaked-keys check before submitting; `code-reviewer` only when I ask (priority 3).
- **GateGuard** asks for facts once per new file. Just answer it; I can start Claude with `ECC_GATEGUARD=off` if it's slowing us down.

## Non-negotiables (even in a rush)

- Never hardcode secrets or API keys. Use `.env` / `.env.local` and the host's environment variables; `.env*` is already in `.gitignore`.
- Never commit or push to `main` with a broken build right before a deadline.
- Ask before deleting files, dropping database tables, or doing anything hard to undo.

## How to work with me

- Only do what I explicitly ask. Propose options; I decide.
- Don't lock in tracks, features or architecture I haven't chosen.
- For small implementation details, pick the option that's fastest to demo and say which you picked. Anything that changes scope, tracks or architecture, ask first.
- Be brief. Tell me what you changed and what to check, not a long explanation.
- When I say **"status"**, give me: what works, what's broken, what's next, and time-risk items.
- When I say **"demo check"**, walk the demo flow (use the browser if available), list anything broken, and fix the blockers.
- When I say **"ship it"**, run the build, fix errors, deploy, and give me the live URLs.

## Parallel sessions

Three people, each running their own sessions. Per person, keep it to 2–3 sessions at a time (more burns usage fast), each in its own worktree (desktop app: new session → Local → worktree). `.worktreeinclude` copies the env files into new worktrees. Stay inside your assigned area and don't edit files owned by another session:

- **Lincoln (leaning) — Engine:** `packages/engine/` (world model, routes, fire, crowd sim)
- **[Name] — Live layer and API:** `apps/api/`, `apps/messenger/`, Supabase
- **[Name] — Web:** `apps/web/` (viewer, map, report)
- **[Who] — Non-code:** pitch deck, README, demo script, Devpost

Shared contracts: the engine output (`packages/engine`, served by `apps/api/app/routes/engine.py`) and what `apps/web/lib/scan-fire.ts` reads from it; the live layer's events (`docs/creao-layer.md`), which the messenger consumes; the database lives in `infra/supabase/migrations/`. Say so before changing either, and when you do change one, tell whoever depends on it. Sessions on the same machine can message each other ("tell the web session the report schema changed").

[edit to match the actual split]

## Final hour checklist

- [ ] Demo flow works on the **deployed** setup (not just localhost)
- [ ] No console errors on the demo pages
- [ ] Env vars set on every host
- [ ] README has: what it is, how to run, live link, screenshots
- [ ] Devpost says which features were built at the event
- [ ] Demo video: 2–3 minutes (Fetch.ai asks for 3–5)
- [ ] "How Sentry shaped Aria" section built from the saved moments
- [ ] Each company challenge entered has its own deliverables done (see `docs/lahacks/03-tracks.md`)
- [ ] Pitch deck done
- [ ] Quick `security-reviewer` pass for leaked keys
