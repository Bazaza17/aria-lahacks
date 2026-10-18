# Sentry moments

> The proof for Sentry's "Best Use of Sentry" track. Fill the log as you build; the Devpost section at the bottom comes from it.
> Org `aria-lahacks` (us.sentry.io). Projects: `aria-api` (Python: the API on Railway, which also runs the engine and the CREAO live layer) and `aria-web` (Next.js on Vercel).

## What the judges want

From `03-tracks.md` and the Sentry plan in `05-plan.md`:

- **At least 2 Sentry products beyond error monitoring.** Their list: Session Replay, Logs, Tracing, Profiling, Uptime Monitoring, MCP / AI agent monitoring.
- **Judged on how observability shaped what we built**, not on how much is turned on.
- **Shown with real moments:** a slow call found in a trace, a broken flow caught in a replay, a bug the logs pointed to. Each one needs what Sentry showed, what we changed, and a number or screenshot.
- The moments have to happen during the build. Aim for 3 to 5 strong ones.
- Prize: a guaranteed internship or new-grad interview for each team member.

## Setup check (Sat Oct 17, ~4:35 PM)

| Project | Test event | Arrived | Notes |
|---|---|---|---|
| `aria-api` | `f0613589…` → [ARIA-API-1](https://aria-lahacks.sentry.io/issues/ARIA-API-1) | Yes | env `laptop`, release `2ff2275`. Sent from a `python -c` script, so its trace has no spans. No `aria-api` spans in the last 24 h: API tracing, profiling, logs and the Anthropic integration are still unproven until a real agent run goes through the running API. |
| `aria-web` | `79613b3e…` → [ARIA-WEB-1](https://aria-lahacks.sentry.io/issues/ARIA-WEB-1) | Yes | env `laptop`, release `2ff2275`. [Replay](https://aria-lahacks.sentry.io/explore/replays/0d0a549cbe6b4c4c8fc285921e03ed56/) attached (17 min, `/` → `/dashboard`). [Page-load trace](https://aria-lahacks.sentry.io/explore/traces/trace/ebab3b84092042729e7e944a7a4046ea) attached (117 spans). |

No dropped error events in the last 24 h.

Worth a look (a lead, not a moment yet): in that page-load trace, the server render of `/dashboard` took 6.2 s, and one Supabase `GET` inside it took 5.9 s. It was local dev mode on hackathon Wi-Fi, so check it again before reading anything into it.

## Products and how to capture a moment

| Product | What it shows for Aria | Where to look, what to screenshot |
|---|---|---|
| **Tracing** | Browser → Vercel `/live` proxy → Railway API, with TigerData `db` spans and the `/engine/*` routes, 100% sampled. Web → API propagation is on (`sentry-trace` / `baggage`; CORS allows both). | Explore → Traces, filter by `transaction` (e.g. the agent run route). Open one trace and screenshot the waterfall with the slow span selected and its duration showing. Copy the trace URL. |
| **AI agent monitoring** *(not claimed)* | (Flood-era agent deleted Sun Oct 18 in `584a4ea`, with its `gen_ai` spans; nothing in the API calls Claude now. Don't claim it.) The Anthropic integration recorded each Claude call: model, prompt, tool calls and tokens. | Insights → AI → Agents (or the trace's `gen_ai.*` spans). Screenshot the run showing the number of calls, tools used and tokens. Before/after: tokens or calls per pre-plan. |
| **Profiling** | Which functions are hot when the engine's fire sim or routing runs on the real building (continuous profiling, trace lifecycle, 100%). On: cloud API transactions carry a `profiler.id`. No moment came from it. | Explore → Profiles, or "Profile" on a slow span in a trace. Screenshot the flame graph with the hot function highlighted. Before/after: the span's duration. |
| **Logs** | The API's Python `logging` (which includes the engine routes and the CREAO live layer), searchable by field. API only: there are no `aria-web` logs, so don't claim web Logs. | Explore → Logs, filter by message or attribute (building, hazard, run id). Screenshot the search with the line that pointed to the bug. Logs also show inside the trace. |
| **Session Replay** | A video-like replay of the viewer, with text unmasked, linked to errors and traces. | Explore → Replays, or the replay on an issue. Screenshot the moment it breaks (frame + console / network tab). Copy the replay URL with the timestamp. |
| **Errors** | Uncaught exceptions in the web app and API, with release and environment. | Issues. Screenshot the issue with stack trace and the linked replay/trace. Errors alone don't count toward the "2 beyond" rule, but they tie the others together. |
| **Uptime** *(not set up)* | Whether the cloud API stays up after the event. | Alerts → Uptime, on the agents' health URL. Screenshot the uptime bar and any downtime incident. |
| **Sentry MCP** | Claude Code reads issues, traces and replays straight from Sentry while fixing bugs. This setup check was done through it. | Screenshot the Claude Code session where the MCP pulled the trace or issue that led to the fix, next to the fix itself. |

## Moments log

One row per time Sentry showed us something and we changed the code because of it. Only real
moments. Filled Sun Oct 18 (~11 AM) from the Sentry MCP (org `aria-lahacks`) and git. Times are PDT,
Sun Oct 18. Screenshots go in `docs/lahacks/sentry/` (not created yet: see "Screenshots to take").
The Sentry links work only for org members, so judges see the screenshots.

| Time | Product | What Sentry showed | What we changed | Before → after | Screenshot | Sentry link |
|---|---|---|---|---|---|---|
| 3:04–3:37 AM | **Logs** (aria-api) | One warning, every few seconds: `TigerData LISTEN dropped (parameter "ssl" cannot be changed now); reconnecting` (`apps/api/app/creao/hub.py`). 832 lines (743 `cloud`, 89 `laptop`). While it repeated, the live hub never got a LISTEN connection, so no database event reached the CREAO orchestrator or the console's live stream. | `6aa8385` (Aayush Pal, 3:32 AM): the URL's `ssl=require` becomes libpq's `sslmode`, plus a test. | 832 warnings in about 33 minutes, none after 3:37 AM. The commit message doesn't mention Sentry: ask Aayush whether he saw it there first. Either way, Sentry confirms the fix. | to take | [Logs search](https://aria-lahacks.sentry.io/explore/logs/?logsQuery=message%3A%22*LISTEN+dropped*%22&project=-1) |
| 5:47 AM | Errors + **Session Replay** + **Tracing** (aria-web) | Five ReferenceErrors in `BuildingScan` within 44 seconds during the restyle: ARIA-WEB-6 (`latestEvent`), -7 (`loadFireStarts`), -8 (`fireStart`, browser), -9 (`fireStart`, server render), -A (`indicative`). WEB-9 and WEB-A share trace `95a43d5d…`; a 12-minute replay shows the page (it also holds ARIA-WEB-5, a missing `BRAND_WORDMARK` export on the landing page). | `e94f964` (7:29 AM) finishes moving the fire-start picker and timeline into `ScenarioProvider`; all four names are gone from `BuildingScan.tsx`. | 1 event each, none since. The restyle plan (`14-restyle-wiring-plan.md`) already listed some of these names, so Sentry caught them with a replay; it didn't discover them. | to take | [Replay](https://aria-lahacks.sentry.io/explore/replays/a0fc532db7ea4e3ba549f7a7487825da/) |
| 2:59 AM | Errors + **Session Replay** (aria-web) | ARIA-WEB-3: `resolvePlacePin is not a function`. The place search crashed on submit; the replay shows the click. | `67ab53c` (3:04 AM) ships the place search with `export function resolvePlacePin` in `scanSceneLayers.ts`. | 1 event, none since | — | [Replay](https://aria-lahacks.sentry.io/explore/replays/8960a25ac4ad4a85a886c1d4633aa671/) |
| 3:54–8:22 AM | Errors + **Session Replay** (aria-web, local dev) | ARIA-WEB-4: `Module not found: Can't resolve './ScanSelectionCard'`. The building page failed to compile 12 times; 3 replays. | `311bf95` (8:54 AM) defines `ScanSelectionCard` inside `BuildingScan.tsx`. | Last event 8:22 AM, none since | — | [Replay](https://aria-lahacks.sentry.io/explore/replays/c2832627dc75494799e88132298a8455/) |

### Looked into, not changed

| Signal | Product | What Sentry showed | Decision |
|---|---|---|---|
| ARIA-WEB-2 (laptop), -B and -C (cloud; -C is the Playwright smoke run, HeadlessChrome) | **Tracing** (performance issue "N+1 API Call") | The repeated spans are `blob:` URLs, about 20–25 ms each: very likely three.js `GLTFLoader` unpacking the textures inside the scan GLB in memory, not network calls. | Left as is; still open. Not a fix. |
| `/live/buildings/{id}/situation` on Railway | **Tracing** | p95 about 2.2 s. [Trace 899c8c47](https://aria-lahacks.sentry.io/explore/traces/trace/899c8c474c6a479da4c13f70c7ce3ac3) shows up to 15 TigerData queries run one after another (about 65 ms each) per request (`app/creao/situation.py` `build()`), and the console polls it with `/staff`. | Found Sun morning; not fixed before the freeze. "What we'd add next." |
| ARIA-API-3: `HTTPException: Cache backend not configured` on `/agent/replay/{building_id}` | Errors | 3 events (Sat 6:56 PM to Sun 1:59 AM), all from our own pytest run. | The flood-era routes were deleted in `584a4ea` (Sun 5:06 AM) for other reasons. Weak link; optional. |

### Screenshots to take

Create `docs/lahacks/sentry/` and save:

1. The Logs search for "LISTEN dropped", showing the burst ending at 3:37 AM.
2. Replay `a0fc532d` with the error list (ARIA-WEB-6 to -A).
3. Trace `899c8c47` with the situation span and its `db` children.

## Candidate moments to watch for

Written Sat for the flood-era agent pipeline; kept for the record. What actually happened is in the moments log above.

- **Engine slow on the real building (Profiling).** The fire sim or routing on the venue's graph takes seconds; the flame graph shows which function, e.g. recomputing all-pairs paths on every tick.
- **Slow step in a full pre-plan (Tracing).** In a viewer → API → engine → Claude trace, one span dominates: the engine, a Supabase call, or a Claude turn. Fix it and show the trace before and after.
- **Wasted Claude calls (AI agent monitoring).** The agent calls the same tool twice, re-reads the whole building each turn, or burns tokens on a step a plain function could do. Show calls and tokens per pre-plan before and after.
- **Viewer fails on a big GLB scan (Session Replay).** The venue scan loads slowly or blank on a phone or a slow network. The replay shows what the user saw, and the trace shows how long the download took.
- **Errors swallowed in the agent stream (Errors + Logs).** A failing agent run shows up only as an `error` SSE event in the browser, with nothing in Sentry (the first known gap, fixed Sat evening). Catching a real failure now that it's fixed is the moment.
- **Cloud agents go down (Uptime).** The Railway host sleeps or crashes; the uptime monitor alerts before a judge finds it.

## Known gaps

1–3 fixed Sat Oct 17 evening; 4 fixed by Sun Oct 18 (`cloud` events show on both projects).

> **Sun Oct 18:** the flood-era Claude pre-plan agent (`app/agent/`, `app/tools/`, `routes/agent.py`) was deleted from the API. Items 1 and 2 below happened, and their Sentry links still work, but the routes and the `gen_ai.*` spans no longer exist, so the write-up must not promise AI agent monitoring of the live product.

1. ~~**Agent stream errors never reach Sentry.**~~ **Fixed in `d2f4743`.** `_captured_stream` in `apps/api/app/routes/agent.py` now calls `sentry_sdk.capture_exception(e)` before yielding the SSE `error` event. Checked with a synthetic failing run: it became [ARIA-API-2](https://aria-lahacks.sentry.io/issues/ARIA-API-2) (env `verify`, safe to resolve) and the browser still got the `error` event.
2. ~~**Tool executions aren't spans.**~~ **Fixed in `e1be8ed`.** `apps/api/app/agent/loop.py` wraps each run in a `gen_ai.invoke_agent` span (`invoke_agent Aria pre-plan`) and each tool call in a `gen_ai.execute_tool` span (`execute_tool <tool>`, with `gen_ai.tool.call.arguments` / `.result`), per the sentry-sdk 2.72 manual agent instrumentation. Tools running in parallel show as siblings. Checked through the real `POST /agent/run` route with a fake Claude client: [trace](https://aria-lahacks.sentry.io/explore/traces/trace/f824894c560e44a392e468f43a886340) (env `verify`) shows `/agent/run` → `invoke_agent` → two `execute_tool` spans. **Still to see:** a live run with real Claude `gen_ai.chat` spans under `invoke_agent` (`ANTHROPIC_API_KEY` is empty in `apps/api/.env`).
3. ~~**No `tunnelRoute` in the web app.**~~ **Fixed in `7e7239a`.** `tunnelRoute: "/aria-relay"` in `apps/web/next.config.ts`. Checked locally: the browser posts every Sentry envelope to `/aria-relay?o=…&p=…&r=us` (200) and nothing goes straight to `sentry.io`. There's no `proxy.ts`/`middleware.ts`; if one is added, exclude `/aria-relay` in its `matcher`.
4. ~~**Cloud environment tags.**~~ **Fixed.** `SENTRY_ENVIRONMENT=cloud` on Railway and `NEXT_PUBLIC_SENTRY_ENVIRONMENT=cloud` on Vercel; `cloud` events now show on both `aria-api` and `aria-web`.

## Recommended Sentry-side setup

Recommendations only, written Sat for the flood-era agent. Nothing here has been changed in Sentry; Lincoln decides.

- **Alerts:** an issue alert on each project for new issues (to email or Discord), and a metric alert when the agent run's p95 duration goes over a threshold. Alerts that fire during the build are moments too.
- **A dashboard "Aria pre-plan":** agent run p95 duration, Claude calls and tokens per run, engine sim duration, error count by project, and web page-load p75. Screenshot it once at the start and once near the end for a before/after.
- **Uptime monitor** on the cloud agents' health endpoint (once they're on the cloud host), checking every minute, with an alert to the team.
- **Releases:** keep the git SHA as the release (it already is) so moments can say "fixed in `<sha>`".

## Devpost: "How Sentry shaped Aria"

Filled from the moments log (Sun Oct 18, ~11 AM). Every number comes from Sentry or git. Keep "about
2.2 s p95" and avoid live totals: request counts keep growing while the site is up. Add the three
screenshots once they're saved.

> We set up Sentry in the first hours of LA Hacks on both halves of Aria:
>
> - `aria-web`: the Next.js viewer and console on Vercel.
> - `aria-api`: FastAPI on Railway, which also runs the fire engine and the CREAO live layer.
>
> Beyond error monitoring we use four products:
>
> - **Tracing:** browser → Vercel → API, 100% sampled, with `sentry-trace` and `baggage` passed to the API.
> - **Session Replay:** every session, with text unmasked because the viewer holds no personal data.
> - **Logs:** the API's Python logging goes to Sentry Logs.
> - **Profiling:** continuous profiling on the API, including the engine routes.
>
> Browser events go through our own `/aria-relay` tunnel so ad blockers don't drop them. While fixing
> bugs, Claude Code read our issues, logs and traces through the Sentry MCP.
>
> **1. Logs: the live layer couldn't hear the database, and Sentry showed when it could again.**
> At 3:04 AM Sunday, Sentry Logs started filling with one API log line: `TigerData LISTEN dropped
> (parameter "ssl" cannot be changed now); reconnecting`. It repeated every few seconds, 832 times in
> 33 minutes, on the laptop and on Railway. It meant the live hub never subscribed to database
> events, so nothing reached the CREAO Incident Commander or the dispatcher console's live stream.
>
> The cause was the database URL's `ssl=require`, which raw asyncpg sends to Tiger Cloud as a server
> setting. The fix (`6aa8385`) translates it to `sslmode` and adds a test. The last one in Sentry
> is at 3:37 AM, and none has come since.
>
> **2. Session Replay + Errors: a refactor caught mid-move.**
> While restyling the building page, we moved the fire-start picker and the fire timeline out of the
> 3D scan into a shared provider. In 44 seconds Sentry recorded five errors for names the scan still
> used after the move (ARIA-WEB-6 to -A). They came from the browser and from the server render, and the
> replay (a0fc532d) shows the page while they happened. The commit that finished the move
> (`e94f964`) removes every one of those names, and none of the five has come back.
>
> **3. Session Replay: a broken search and a missing file.**
> The place search crashed on its first submit (ARIA-WEB-3), and the replay shows the click and the
> crash. The feature shipped five minutes later (`67ab53c`).
>
> Separately, the building page failed to compile 12 times across the morning (ARIA-WEB-4, `Can't
> resolve './ScanSelectionCard'`, with 3 replays). We moved the card into the scan component; the last error was
> at 8:22 AM, and the fix is in `311bf95`.
>
> **4. Tracing: one false alarm, one real find.**
> Sentry flagged "N+1 API Call" on the building page. The trace showed the repeated calls are `blob:`
> URLs, which is three.js unpacking the textures inside our scan file in memory, about 20 ms each.
> That isn't a network problem, so we left it.
>
> The same traces showed a real one. On Railway, the console's situation call runs up to 15 database
> queries one after another, about 2.2 s at p95. We found it Sunday morning and didn't fix it before
> the code freeze.
>
> **What we'd add next:** batch the situation queries, add an Uptime monitor on the Railway API, and
> set alerts for new issues.

Not claimed: AI agent monitoring (the Claude agent and its `gen_ai` spans were deleted), Uptime (not
set up), web Logs (none in Sentry). The messenger (`apps/messenger`) has no Sentry; the engine has no
SDK of its own and is traced and profiled through the API's `/engine/*` routes.
