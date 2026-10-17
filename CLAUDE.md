# CLAUDE.md — Hackathon Mode

> Built from `hackathon-CLAUDE.md`. Brackets are choices Lincoln hasn't made yet; fill them in as he decides.

## The Project

- **Name:** Aria
- **One-liner:** [what it does, in one sentence]
- **Demo flow:** [the 3–5 steps judges will see]
- **Deadline:** Sun Oct 18, 12:00 PM PDT. Judging at 12:30 PM, in person.
- **Goal:** win. Main track: Applied Intelligence. Other company challenges are open, favoring recruiting benefits and good cash prizes (`docs/lahacks/03-tracks.md`).
- **Sentry:** entered. Set it up at the start and collect the "moments" all weekend (plan in `docs/lahacks/05-plan.md`).
- **Team:** Lincoln plus two teammates. [who owns what; see Parallel sessions]
- **Build order:** engine first (world model → routes → fire timeline → crowd sim), then wrap it in agents: an orchestrator plus world model, hazard, evac sim and report specialists.
- **Stack:** Next.js 16 + React 19 + Tailwind 4 + Three.js + Mapbox (`apps/web`), FastAPI + Claude tool loop over SSE (`apps/api`), Supabase (`infra/supabase`), the engine in `packages/engine` (empty), agents in `apps/agents` [agent framework: Fetch.ai uAgents + ASI:One is set up there and is the lean]. Agents run on the laptop first and on a cloud host by Sunday.
- **Context:** `docs/lahacks/`. Start with `00-start-here.md`; what's decided and what's open is in `01-decisions.md`.

## What changes from the Miami version

The code came from Aria's Miami build. This weekend:

- **Flood → fire.** Fire is the main hazard. The prompt, report schema, tools, scenario slider, evac logic, 3D layers and copy are all built around storm surge today.
- **The Dock → the venue.** The venue (James West Alumni Center, UCLA) replaces the one hardcoded Miami building. Per-building data is keyed by hardcoded IDs across `apps/web/lib/`, the scan viewer, tests, the replay script and a seed migration.
- **The map.** Mapbox and the landing-page globe open on Miami.
- **Supabase.** A new project replaces Aria's.

Every file involved, plus the Supabase steps: `docs/lahacks/07-changes.md`.

## Commands

- Env files: copy each `.env.example` to `apps/web/.env.local`, `apps/api/.env` and `apps/agents/.env`.
- Web: `pnpm --dir apps/web dev` → http://localhost:3000
- API: `cd apps/api && uv run uvicorn app.main:app --reload --reload-dir app --port 8000`
- Both at once: `pnpm dev` (it runs `apps/api/dev.sh`, so it needs a bash shell)
- Checks: `pnpm check` (web lint, format, typecheck and unit tests; API ruff and pytest)
- Agents: toolchain check in `apps/agents/README.md`

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
7. **Keep the app runnable at all times.** After each change, make sure it still builds (`pnpm --dir apps/web build`) and the API and agents still start. If something breaks, fixing it is the top priority.
8. **Commit often** with short conventional messages (`feat:`, `fix:`) so we can roll back.

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

Three people, each running their own sessions (a separate clone, or one worktree per session). Stay inside your assigned area and don't edit files owned by another session:

- **[Name] — Engine:** `packages/engine/` (world model, routes, fire, crowd sim)
- **[Name] — Agents and API:** `apps/agents/`, `apps/api/`, Supabase
- **[Name] — Web:** `apps/web/` (viewer, map, report)

Shared contracts: the report schema lives in `apps/api/app/agent/prompts.py` and is copied by hand into `apps/web/lib/types.ts`; the database lives in `infra/supabase/migrations/`. Say so before changing either.

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
