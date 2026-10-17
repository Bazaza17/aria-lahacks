# Aria

Pre-incident planning for first responders. Aria combines 3D LiDAR building
scans, hazard pins, evacuation paths and hazard simulation with an AI agent
that assembles a structured size-up of a building before crews arrive.

> The product name is defined in one place per app —
> [`apps/web/lib/brand.ts`](apps/web/lib/brand.ts) and
> [`apps/api/app/brand.py`](apps/api/app/brand.py) — so it can be renamed
> without touching components.

## Repository layout

```
apps/
  web/        Next.js 16 frontend (dashboard, building workbench, 3D scan viewer)  → Vercel
  api/        FastAPI backend (agent loop, SSE streaming, cached replays)          → Railway
  agents/     Fetch.ai uAgents (Agent Chat Protocol, ASI:One)
packages/
  engine/     Simulation engine (world model, routes, hazards, crowd sim)
infra/
  supabase/migrations/   Postgres schema + seed data
```

## Prerequisites

- Node.js 20+ and [pnpm](https://pnpm.io) 10
- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- A Supabase project, a Mapbox token and an Anthropic API key (for live agent runs)

## Setup

```bash
# Frontend
cd apps/web
cp .env.example .env.local      # fill in values
pnpm install

# Backend
cd ../api
cp .env.example .env            # fill in values
uv sync

# Agents
cd ../agents
cp .env.example .env            # fill in values
uv sync
```

### Database (Supabase)

1. In the SQL editor, run `infra/supabase/migrations/0001_init.sql`,
   `0002_cached_runs.sql` and `0004_rls.sql`, in that order.
   `0003_the_dock.sql` seeds a Miami demo building; skip it when setting up a
   different building.
2. Create a public Storage bucket named `scans` and upload the building's scan
   (GLB or USDZ). Scans never go in git.
3. Add the building to `buildings` (`address`, `lat`, `lng`, `scan_url`,
   `is_demo = true`) and set `is_demo = false` on any others.

### Environment variables

| App | Variable | Required | Purpose |
|---|---|---|---|
| web | `NEXT_PUBLIC_API_URL` | yes | Base URL of the API |
| web | `NEXT_PUBLIC_SUPABASE_URL` | yes | Supabase project URL (also used for Storage scan URLs) |
| web | `NEXT_PUBLIC_SUPABASE_ANON_KEY` | yes | Supabase publishable (anon) key |
| web | `NEXT_PUBLIC_MAPBOX_TOKEN` | yes | Mapbox public token for the dashboard map |
| api | `ANTHROPIC_API_KEY` | for live runs | Claude API key used by the agent loop |
| api | `SUPABASE_URL` | for caching | Supabase project URL |
| api | `SUPABASE_SERVICE_ROLE_KEY` | for caching | Supabase secret (service role) key for writing cached runs — never expose to the browser |
| api | `ALLOWED_ORIGINS` | no | Extra CORS origins, comma-separated |
| agents | `HELLO_AGENT_SEED` | for the agent check | Fixes the agent's address; keep it secret |

The committed `.env.example` files list the same variables with no values.
Supabase's newer publishable (`sb_publishable_…`) and secret (`sb_secret_…`)
keys go in the same variables as the legacy anon and service role keys.

## Scripts

Run from the repo root:

| Command | What it does |
|---|---|
| `pnpm dev` | Frontend on :3000 and API on :8000 together (needs a bash shell for `apps/api/dev.sh`) |
| `pnpm check` | Lint, format check, typecheck and unit tests for both apps |
| `pnpm format` | Auto-format both apps (Prettier + ruff) |
| `pnpm test:e2e` | Playwright end-to-end test (needs the dev server and a seeded Supabase) |

Per app:

| `apps/web` | `apps/api` |
|---|---|
| `pnpm dev`, `pnpm build` | `./dev.sh` (uvicorn with reload) |
| `pnpm lint`, `pnpm format:check`, `pnpm typecheck` | `uv run ruff check .`, `uv run ruff format --check .` |
| `pnpm test` (node test runner), `pnpm test:e2e` | `uv run pytest` |

Agents: see [`apps/agents/README.md`](apps/agents/README.md).

## Testing

- **Unit (web):** `apps/web/lib/*.test.ts`, run with Node's built-in test runner via `tsx`.
- **Unit (api):** `apps/api/tests/` — HTTP smoke tests with FastAPI's `TestClient`; no network or keys needed.
- **End-to-end:** `apps/web/tests/e2e/` — Playwright against a running dev server; needs live Supabase data.

## Deployment

| Piece | Host | Root directory |
|---|---|---|
| Frontend (Next.js) | Vercel | `apps/web` |
| API (FastAPI) | Railway (Dockerfile) | `apps/api` |
| Agents | Laptop with an Agentverse mailbox, or any cloud host | `apps/agents` |
| Database + scan storage | Supabase | — |

Deploy the API first so you have its URL for the frontend.

1. **API → Railway:** New Project → Deploy from GitHub repo → this repo. Set
   **Root Directory** to `apps/api`; the build uses `apps/api/Dockerfile`
   (configured in `railway.toml`). Add the API variables above, then
   **Settings → Networking → Generate Domain**. `GET <url>/health` should
   return `{"ok": true}`. CORS always allows `http://localhost:3000` and any
   `*.vercel.app` origin; add other domains with `ALLOWED_ORIGINS`.
2. **Frontend → Vercel:** Add New → Project → import this repo. Set **Root
   Directory** to `apps/web` (Next.js is auto-detected; `vercel.json` sets
   pnpm). Add the web variables above, with `NEXT_PUBLIC_API_URL` set to the
   Railway URL, then deploy.
3. **Database → Supabase:** see Database above. Optionally pre-warm the replay
   cache so the first demo is instant (the building list is set in the script):
   ```bash
   cd apps/api
   ARIA_API_URL=<Railway URL> uv run python scripts/prewarm_cache.py
   ```

Smoke test: `/` loads, `/dashboard` shows the building marker → **VIEW
BUILDING**, and on `/building/{id}` **RUN PRE-PLAN AGENT** streams the agent
log and the report appears. If the agent log stays empty,
`NEXT_PUBLIC_API_URL` is wrong or the cache is cold.
