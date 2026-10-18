# Aria

Aria turns a phone scan of a building into a fire pre-plan, then uses it during the real thing.

1. **Scan.** Phone LiDAR scans of the venue (James West Alumni Center, UCLA) plus its floor plan
   become one building model, `packages/engine/venue.json`: 63 spaces, 99 openings, 14 exits.
   Only four 1F rooms are scanned; the rest of 1F and the floors above come from the floor plan.
2. **Engine.** Pick where the fire starts. The engine works out how smoke and fire spread, which
   exits are lost and when, and a capacity-aware route out for every occupied room, compared
   with the routes people would pick themselves. The web app draws it on the 3D scan.
3. **Live response.** A dispatcher declares a drill (or an incident) on the live console. Agents
   text and call the people in the building with routes, take their replies, and propose route
   changes that the dispatcher approves before anyone is told.

> The product name is defined in one place per app,
> [`apps/web/lib/brand.ts`](apps/web/lib/brand.ts) and
> [`apps/api/app/brand.py`](apps/api/app/brand.py).

## Repository layout

```
apps/
  web/         Next.js 16 frontend: dashboard, building page, 3D scan viewer      → Vercel
  api/         FastAPI: the engine on demand (/engine/*) and the live layer (/live/*, /mcp)  → Railway
  messenger/   Texts (Photon) and voice calls (ElevenLabs) for people in the building; runs on a teammate's machine
packages/
  engine/      The building engine: venue model, fire and smoke, exits, routes (stdlib Python)
infra/
  supabase/    Postgres schema and the venue row (see infra/supabase/README.md)
docs/          Design notes; the live layer is in docs/creao-layer.md
```

## Prerequisites

- Node.js 20+ and [pnpm](https://pnpm.io) 10
- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- A Supabase project (venue row and scan storage) and a Mapbox token
- For the live layer: a Postgres database (TigerData), and for the messenger Photon and
  ElevenLabs accounts

## Setup

```bash
# Frontend
cd apps/web
cp .env.example .env.local      # fill in values
pnpm install

# API
cd ../api
cp .env.example .env            # fill in values
uv sync

# Messenger (optional; see apps/messenger/README.md)
cd ../messenger
cp .env.example .env
npm install
```

Careful: with a real `apps/api/.env`, a local API connects to the shared live database and,
through the messenger, to real texting and calling. Leave `CREAO_DATABASE_URL` empty (a local
SQLite file) when you only want to try things.

### Database (Supabase)

See [`infra/supabase/README.md`](infra/supabase/README.md): run migrations `0001`, `0002`,
`0004` and `0005` (the venue row), create the public `scans` bucket and upload the mesh.

### Environment variables

| App | Variable | Required | Purpose |
|---|---|---|---|
| web | `NEXT_PUBLIC_API_URL` | yes | Base URL of the API (the web app proxies `/engine/*` and `/live/*` to it, in dev and on Vercel) |
| web | `NEXT_PUBLIC_SUPABASE_URL` | yes | Supabase project URL (also used for Storage scan URLs) |
| web | `NEXT_PUBLIC_SUPABASE_ANON_KEY` | yes | Supabase publishable (anon) key |
| web | `NEXT_PUBLIC_MAPBOX_TOKEN` | yes | Mapbox public token for the dashboard map |
| web | `NEXT_PUBLIC_VENUE_BUILDING_ID` | yes | Supabase id of the venue row (`547b5ec5-30c5-4f76-8080-012a52e90bd9`) |
| web | `NEXT_PUBLIC_SENTRY_DSN`, `NEXT_PUBLIC_SENTRY_ENVIRONMENT` | no | Sentry for the web app |
| api | `CREAO_DATABASE_URL` | for live data | TigerData/Postgres URL; empty means a local SQLite file |
| api | `DISPATCH_API_KEYS` | for the console | Dispatcher keys (`Authorization: Bearer`), comma-separated |
| api | `CREAO_TOOL_SECRET` | for the messenger | Shared secret the messenger and ElevenLabs tools send as `X-Tool-Secret` |
| api | `CREAO_DEFAULT_BUILDING_ID`, `PUBLIC_BASE_URL`, `MCP_API_KEYS`, `CREAO_API_KEY`, `CREAO_APP_*`, `CREAO_WEBHOOK_TOKEN`, `DISPATCHER_PHONE` | for the CREAO staff | See `apps/api/.env.example` and `docs/creao-layer.md` |
| api | `ALLOWED_ORIGINS` | no | Extra CORS origins, comma-separated |
| api | `SENTRY_DSN`, `SENTRY_ENVIRONMENT` | no | Sentry for the API |
| messenger | `PHOTON_PROJECT_ID`, `PHOTON_API_KEY` | yes | Texting (Photon) |
| messenger | `ELEVENLABS_API_KEY`, `ELEVENLABS_AGENT_ID`, `ELEVENLABS_PHONE_NUMBER_ID` | for calls | Voice agent (ElevenLabs) |
| messenger | `ARIA_LIVE_URL`, `ARIA_TOOL_SECRET`, `ARIA_BUILDING_ID`, `ARIA_PUBLIC_URL` | to join the live layer | The API's URL, its `CREAO_TOOL_SECRET`, the venue id, the API's public URL |
| messenger | `DISPATCHER_PHONE` | no | Number calls are handed to |

The committed `.env.example` files list the same variables with no values. Secrets go only in
the git-ignored env files.

## Running it

From the repo root:

| Command | What it does |
|---|---|
| `pnpm dev` | Frontend on :3000 and API on :8000 together (needs a bash shell for `apps/api/dev.sh`) |
| `pnpm check` | Lint, format check, typecheck and unit tests for web and API |
| `pnpm format` | Auto-format both apps (Prettier + ruff) |

Per piece:

| Piece | Commands |
|---|---|
| `apps/web` | `pnpm dev`, `pnpm build`, `pnpm lint`, `pnpm typecheck`, `pnpm test` |
| `apps/api` | `./dev.sh` (uvicorn with reload on :8000), `uv run ruff check .`, `uv run pytest` |
| `packages/engine` | `uv run python -m engine.demo --start 140 --summary`, `uv run pytest -q` |
| `apps/messenger` | `npm run start`, `npm run agent:sync` (see its README) |

### Engine endpoints

| Endpoint | Returns |
|---|---|
| `GET /engine/starts` | Default start, growth rates, every space a fire can start in |
| `GET /engine/viewer?start=140&growth=fast` | The viewer block (fire timeline and routes) drawn on the scan |
| `GET /engine/summary?start=140&growth=fast` | Scenario, summary, exits, origin and the responder size-up |

The live layer's endpoints (`/live/*`, the console at `/live/view`, `/mcp`) are documented in
[`docs/creao-layer.md`](docs/creao-layer.md).

## Testing

- **Engine:** `packages/engine/tests/`: physics, venue, routes, demo and place lookup.
- **API:** `apps/api/tests/`: HTTP smoke tests (no lifespan, no network) and the live layer's rules.
- **Web:** `apps/web/lib/*.test.ts` with Node's test runner via `tsx`.

## Deployment

| Piece | Host | Root directory |
|---|---|---|
| Frontend (Next.js) | Vercel | `apps/web` |
| API (FastAPI + engine + live layer) | Railway (Dockerfile) | repo root (blank) |
| Messenger | A teammate's machine (Photon + ElevenLabs) | `apps/messenger` |
| Venue row + scan storage | Supabase | — |
| Live data | TigerData | — |

Deploy the API first so you have its URL for the frontend and the messenger.

1. **API → Railway:** New Project → Deploy from GitHub repo → this repo. Leave **Root
   Directory** blank (the repo root), so the image also gets `packages/engine`; the root
   `railway.toml` points the build at `apps/api/Dockerfile`. Add the API variables, then
   **Settings → Networking → Generate Domain**. `GET <url>/health` should return
   `{"ok": true}` and `GET <url>/engine/starts` the list of starts. CORS always allows
   `http://localhost:3000` and any `*.vercel.app` origin; add others with `ALLOWED_ORIGINS`.
2. **Frontend → Vercel:** import this repo, **Root Directory** `apps/web`. Add the web
   variables, with `NEXT_PUBLIC_API_URL` set to the Railway URL, then deploy.
3. **Supabase:** see Database above.
4. **Messenger:** set `ARIA_LIVE_URL`, `ARIA_TOOL_SECRET` and `ARIA_PUBLIC_URL` to the Railway
   API and run it (see `apps/messenger/README.md`).

Smoke test: `/` loads, `/dashboard` shows the venue marker, the building page shows the scan,
and picking a fire start redraws smoke, lost exits and routes from `/engine`. If nothing
redraws, `NEXT_PUBLIC_API_URL` is wrong or the API is down.
