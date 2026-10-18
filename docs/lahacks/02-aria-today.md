# Aria today

> **Historical (Fri Oct 17):** this describes the Miami code as ported. Since then the flood agent, `/agent/*`, the replay cache script and `apps/agents` are gone; the API now serves the engine (`/engine/*`) and the live layer (`/live/*`). The current picture is the root `README.md`.

The code in this repo was ported from the original Aria codebase (`C:\Users\lincb\Documents\GitHub\Aria-miami`, `main` at commit `1f05572`, Oct 6, 2026). What changes this weekend is in `07-changes.md`.

## What it is

Pre-incident planning for first responders: a 3D LiDAR scan of a building, hazard pins, evacuation paths and a storm-surge slider, plus a Claude agent that writes a structured size-up of the building.

## Layout

| Path | What | Hosted on |
|---|---|---|
| `apps/web` | Next.js 16, React 19, Tailwind 4, Three.js scan viewer, Mapbox dashboard | Vercel |
| `apps/api` | FastAPI on Python 3.12 (uv): Claude tool-use loop streamed over SSE, cached replays | Railway (Docker) |
| `apps/agents` | Fetch.ai uAgents; for now only a Chat Protocol toolchain check (`hello_agent.py`) | Laptop, then a cloud host |
| `packages/engine` | Empty: the new engine (world model, routes, hazards, crowd sim) goes here | — |
| `infra/supabase/migrations` | Postgres schema and seed data: `buildings`, `preplans`, `tool_calls`, `cached_runs` | Supabase |
| `docs/lahacks/` | These hackathon notes | — |

Pages: `/` landing, `/dashboard` map and agent activity, `/building/[id]` workbench (agent log · 3D scan · report).
API: `GET /health`, `POST /agent/run` (live run streamed over SSE, rate-limited), `POST /agent/replay/{building_id}` (cached run).

## What's real

- The web shell: dashboard, building workbench, 3D viewer with EVAC and hazard modes, surge slider (0/1/3/6/10 ft), report UI
- The agent loop: Claude (`claude-sonnet-4-5`) calls tools, streams each step and returns a strict JSON report. The schema is in `apps/api/app/agent/prompts.py` and is copied by hand into `apps/web/lib/types.ts`.
- A replay cache, so demos don't depend on a live run
- Unit tests for the evac and flood logic (web) and HTTP smoke tests (api); `pnpm check` at the root runs lint, format check, typecheck and the tests

## What's a stand-in

| Piece | Where | Today |
|---|---|---|
| Agent tools | `apps/api/app/tools/executors.py` | All five (Street View, satellite, FEMA flood zone, Miami-Dade surge zone, nearby assets) return fixed data |
| Exits and routes | `apps/web/lib/scan-evac-paths.ts` | Hand-placed per building; an exit counts as blocked at a fixed surge height |
| Flood | `apps/web/lib/scan-flood.ts` | Water height hardcoded per slider stop, per building |
| Buildings | several `apps/web/lib/` files | Keyed by hardcoded IDs; one demo building (The Dock, Miami) |
| Region | prompts and tools | Miami-Dade only |
| Map | `apps/web/app/dashboard/MapDashboard.tsx`, `apps/web/app/page.tsx` | Mapbox opens on a fixed Miami point; the landing globe faces Miami |

## Run it

```bash
# frontend
cd apps/web && cp .env.example .env.local && pnpm install    # then: pnpm dev (port 3000)
# backend
cd apps/api && cp .env.example .env && uv sync               # then: ./dev.sh (port 8000)
# both at once, from the repo root
pnpm dev
```

Environment variables: the web app needs `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` and `NEXT_PUBLIC_MAPBOX_TOKEN`. The API needs `ANTHROPIC_API_KEY` for live runs, and `SUPABASE_URL` plus `SUPABASE_SERVICE_ROLE_KEY` for caching.

## Keeping this repo separate from the original Aria

Nothing touches the original unless this repo is pointed at it:

- **Git:** this repo's remote is `Bazaza17/aria-lahacks`. Never push to `Bazaza17/aria-miami`.
- **Supabase:** use the new project. Don't run these migrations against Aria's live project. `0003` seeds The Dock with a scan in Aria's public `scans` bucket; seed the venue instead (`07-changes.md`).
- **Vercel and Railway:** create new projects for this repo. The existing `aria-miami` ones stay linked to the original.
- **Locally:** both repos use ports 3000 and 8000, so run one at a time.
