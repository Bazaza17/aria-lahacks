# Sentry moments

> The proof for Sentry's "Best Use of Sentry" track. Fill the log as you build; the Devpost section at the bottom comes from it.
> Org `aria-lahacks` (us.sentry.io). Projects: `aria-api` (Python: API, later agents and engine) and `aria-web` (Next.js).

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
| **Tracing** | One trace per pre-plan: viewer → API → engine → Claude, so the slow or failing step stands out. Web → API propagation is on (`sentry-trace` / `baggage`). | Explore → Traces, filter by `transaction` (e.g. the agent run route). Open one trace and screenshot the waterfall with the slow span selected and its duration showing. Copy the trace URL. |
| **AI agent monitoring** | (Flood-era agent deleted Sun Oct 18; nothing in the API calls Claude now.) The Anthropic integration recorded each Claude call: model, prompt, tool calls and tokens. | Insights → AI → Agents (or the trace's `gen_ai.*` spans). Screenshot the run showing the number of calls, tools used and tokens. Before/after: tokens or calls per pre-plan. |
| **Profiling** | Which functions are hot when the engine's fire sim or routing runs on the real building (continuous profiling, trace lifecycle, 100%). | Explore → Profiles, or "Profile" on a slow span in a trace. Screenshot the flame graph with the hot function highlighted. Before/after: the span's duration. |
| **Logs** | Structured logs from the API (and later engine and agents) through Python `logging`, searchable by field. | Explore → Logs, filter by message or attribute (building, hazard, run id). Screenshot the search with the line that pointed to the bug. Logs also show inside the trace. |
| **Session Replay** | A video-like replay of the viewer, with text unmasked, linked to errors and traces. | Explore → Replays, or the replay on an issue. Screenshot the moment it breaks (frame + console / network tab). Copy the replay URL with the timestamp. |
| **Errors** | Uncaught exceptions in the web app and API, with release and environment. | Issues. Screenshot the issue with stack trace and the linked replay/trace. Errors alone don't count toward the "2 beyond" rule, but they tie the others together. |
| **Uptime** *(later)* | Whether the cloud agents stay up after the event. | Alerts → Uptime, on the agents' health URL. Screenshot the uptime bar and any downtime incident. |
| **Sentry MCP** | Claude Code reads issues, traces and replays straight from Sentry while fixing bugs. This setup check was done through it. | Screenshot the Claude Code session where the MCP pulled the trace or issue that led to the fix, next to the fix itself. |

## Moments log

One row per time Sentry showed us something and we changed the code because of it. Only real moments; leave it empty until one happens. Screenshots go in `docs/lahacks/sentry/` (create it when the first one is saved).

| Time | Product | What Sentry showed | What we changed | Before → after | Screenshot | Sentry link |
|---|---|---|---|---|---|---|
| | | | | | | |

## Candidate moments to watch for

Places in Aria's pipeline where a moment is likely. None of these has happened yet.

- **Engine slow on the real building (Profiling).** The fire sim or routing on the venue's graph takes seconds; the flame graph shows which function, e.g. recomputing all-pairs paths on every tick.
- **Slow step in a full pre-plan (Tracing).** In a viewer → API → engine → Claude trace, one span dominates: the engine, a Supabase call, or a Claude turn. Fix it and show the trace before and after.
- **Wasted Claude calls (AI agent monitoring).** The agent calls the same tool twice, re-reads the whole building each turn, or burns tokens on a step a plain function could do. Show calls and tokens per pre-plan before and after.
- **Viewer fails on a big GLB scan (Session Replay).** The venue scan loads slowly or blank on a phone or a slow network. The replay shows what the user saw, and the trace shows how long the download took.
- **Errors swallowed in the agent stream (Errors + Logs).** A failing agent run shows up only as an `error` SSE event in the browser, with nothing in Sentry (the first known gap, fixed Sat evening). Catching a real failure now that it's fixed is the moment.
- **Cloud agents go down (Uptime).** The Railway host sleeps or crashes; the uptime monitor alerts before a judge finds it.

## Known gaps

1–3 fixed Sat Oct 17 evening; 4 is still open.

> **Sun Oct 18:** the flood-era Claude pre-plan agent (`app/agent/`, `app/tools/`, `routes/agent.py`) was deleted from the API. Items 1 and 2 below happened, and their Sentry links still work, but the routes and the `gen_ai.*` spans no longer exist, so the write-up must not promise AI agent monitoring of the live product.

1. ~~**Agent stream errors never reach Sentry.**~~ **Fixed in `d2f4743`.** `_captured_stream` in `apps/api/app/routes/agent.py` now calls `sentry_sdk.capture_exception(e)` before yielding the SSE `error` event. Checked with a synthetic failing run: it became [ARIA-API-2](https://aria-lahacks.sentry.io/issues/ARIA-API-2) (env `verify`, safe to resolve) and the browser still got the `error` event.
2. ~~**Tool executions aren't spans.**~~ **Fixed in `e1be8ed`.** `apps/api/app/agent/loop.py` wraps each run in a `gen_ai.invoke_agent` span (`invoke_agent Aria pre-plan`) and each tool call in a `gen_ai.execute_tool` span (`execute_tool <tool>`, with `gen_ai.tool.call.arguments` / `.result`), per the sentry-sdk 2.72 manual agent instrumentation. Tools running in parallel show as siblings. Checked through the real `POST /agent/run` route with a fake Claude client: [trace](https://aria-lahacks.sentry.io/explore/traces/trace/f824894c560e44a392e468f43a886340) (env `verify`) shows `/agent/run` → `invoke_agent` → two `execute_tool` spans. **Still to see:** a live run with real Claude `gen_ai.chat` spans under `invoke_agent` (`ANTHROPIC_API_KEY` is empty in `apps/api/.env`).
3. ~~**No `tunnelRoute` in the web app.**~~ **Fixed in `7e7239a`.** `tunnelRoute: "/aria-relay"` in `apps/web/next.config.ts`. Checked locally: the browser posts every Sentry envelope to `/aria-relay?o=…&p=…&r=us` (200) and nothing goes straight to `sentry.io`. There's no `proxy.ts`/`middleware.ts`; if one is added, exclude `/aria-relay` in its `matcher`.
4. **Cloud environment tags.** Set `SENTRY_ENVIRONMENT=cloud` on Railway and `NEXT_PUBLIC_SENTRY_ENVIRONMENT=cloud` on Vercel (plus both DSNs), or cloud events will be tagged `laptop`.

## Recommended Sentry-side setup

Recommendations only. Nothing here has been changed in Sentry; Lincoln decides.

- **Alerts:** an issue alert on each project for new issues (to email or Discord), and a metric alert when the agent run's p95 duration goes over a threshold. Alerts that fire during the build are moments too.
- **A dashboard "Aria pre-plan":** agent run p95 duration, Claude calls and tokens per run, engine sim duration, error count by project, and web page-load p75. Screenshot it once at the start and once near the end for a before/after.
- **Uptime monitor** on the cloud agents' health endpoint (once they're on the cloud host), checking every minute, with an alert to the team.
- **Releases:** keep the git SHA as the release (it already is) so moments can say "fixed in `<sha>`".

## Devpost: "How Sentry shaped Aria" (skeleton)

Fill from the moments log. Keep each moment to 2 to 3 sentences with a number and a screenshot.

> We set up Sentry at the start of LA Hacks, on both the API (`aria-api`, Python) and the web viewer (`aria-web`, Next.js), with [Tracing / AI agent monitoring / Profiling / Logs / Session Replay / Uptime]. It changed what we built in [N] ways:
>
> **1. [Product]: [short title]**
> [What Sentry showed.] [What we changed.] [Before → after.]
> ![screenshot](…) · [Sentry link]
>
> **2. [Product]: [short title]**
> [What Sentry showed.] [What we changed.] [Before → after.]
> ![screenshot](…) · [Sentry link]
>
> **3. [Product]: [short title]**
> [What Sentry showed.] [What we changed.] [Before → after.]
> ![screenshot](…) · [Sentry link]
>
> **How we used the Sentry MCP:** [how Claude Code read traces/issues while fixing bugs, with one example].
>
> **What we'd add next:** [e.g. uptime alerts after the event].
