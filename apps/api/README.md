# API (`apps/api`)

FastAPI backend for [Aria](../../README.md). It does two jobs:

1. **The building engine on demand** (`app/routes/engine.py`). It imports `packages/engine`
   and runs a fire, smoke, exits and routes scenario for any start room on the venue, about 1 s
   per run, cached in memory.
2. **The live response layer** (`app/creao/`, `app/routes/live.py`). Incidents, people and
   exits during a drill or a fire: intake from the messenger (texts and calls), the CREAO
   command staff, route proposals the dispatcher approves, and the dispatcher console at
   `/live/view`. The six CREAO agents are started through CREAO's API Trigger and act through an
   `aria-actions` block in their reply (`app/creao/bridge.py`), because CREAO can't attach a custom
   MCP connector. When a drill ends, the console clears and the CREAO Scribe writes the
   after-action report (`app/creao/after_action.py`). Full write-up, agent IDs and links:
   [`docs/creao-layer.md`](../../docs/creao-layer.md).

## Stack

- Python 3.12, FastAPI, uvicorn, pydantic v2, SQLAlchemy (async)
- TigerData (Postgres) for live data; a local SQLite file when `CREAO_DATABASE_URL` is empty
- slowapi (per-IP rate limits), Sentry (off unless `SENTRY_DSN` is set)
- Package manager: uv

## Layout

```
apps/api/
├── app/
│   ├── main.py            # FastAPI app: Sentry, rate limits, CORS, routers, /mcp mount
│   ├── ratelimit.py       # per-IP limiter (600/min default; health, intake, tools, stream, console and CREAO callback exempt; declares and clears 10/min, person actions 60/min)
│   ├── routes/
│   │   ├── engine.py      # GET /engine/starts, /engine/viewer, /engine/summary
│   │   └── live.py        # /live/*: intake, stream, evacuations, approvals, console
│   └── creao/             # the live layer: models, rules, planning, CREAO agents, MCP tools
│       └── buildings/     # per-building profiles the live layer reads
├── scripts/
│   ├── build_profile.py   # regenerate app/creao/buildings/james_west.json from packages/engine/venue.json
│   └── creao_standin.py   # rehearse the CREAO staff without CREAO (scripted, through /mcp)
├── tests/
├── Dockerfile             # built from the repo root (it copies packages/engine)
└── dev.sh                 # uvicorn with reload on :8000
```

## Engine endpoints

| Endpoint | Returns |
|---|---|
| `GET /engine/starts` | Default start, growth rates, every space a fire can start in |
| `GET /engine/viewer?start=140&growth=fast` | The viewer block (fire timeline and routes) the web app draws on the scan |
| `GET /engine/summary?start=140&growth=fast` | Scenario, summary, exits, origin and the responder size-up |

From Python, `await run(start, growth="fast")` in `app/routes/engine.py` returns the full
`engine.demo.run_demo` result.

## Environment variables

Copy `.env.example` to `.env` (git-ignored). The live layer's variables (database, dispatcher
keys, tool secret, CREAO keys) are documented there and in `docs/creao-layer.md`. Others:
`ALLOWED_ORIGINS` (extra CORS origins), `SENTRY_DSN`, `SENTRY_ENVIRONMENT`.

## Dev

```bash
uv sync
./dev.sh                                    # or: uv run uvicorn app.main:app --reload --reload-dir app --port 8000
uv run ruff check . && uv run ruff format --check .
uv run pytest
curl "http://localhost:8000/engine/summary?start=140"
```

Careful: with a real `.env`, a local run connects to the shared live database and the real
texting and calling services. Point `CREAO_DATABASE_URL` at a local database (or leave it empty
for SQLite) when you only want to try things.

## Deploy

Railway, from the repo root (Root Directory blank), using the root `railway.toml`, which points
at `apps/api/Dockerfile`. Uvicorn runs with `--proxy-headers`, so rate limits see the real client
IP behind Railway's proxy.
