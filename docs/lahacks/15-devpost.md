# Devpost submission text

> Paste-ready text for each Devpost field, written Sun Oct 18 ~11:15 AM. Placeholder to swap
> before submitting: `https://www.youtube.com/watch?v=XaDfIjDk314`. Everything below is checked against the code, git or Sentry. The UI and this
> text report rooms, not headcounts: crowds are modelled at each room's assumed capacity (NFPA).

## Project name

Aria

## Elevator pitch (200 characters max)

Aria turns a phone scan of a building into a fire pre-plan, then runs the drill: CREAO agents
triage texts and calls, propose safer routes, and a dispatcher approves before anyone is told.

## Inspiration

When fire crews pull up to a building, they may never have been inside it. And during an
evacuation, the people inside get one alarm and no idea which exit is still safe.

We wanted to know the building before the truck arrives: scan it with a phone, work out how a fire
would spread and which exits would go first, and then use that same model to guide people out and
keep the dispatcher in control while it happens.

## What it does

Aria has three parts.

1. **Scan.** We scanned four rooms of the James West Alumni Center at UCLA with a phone (LiDAR,
   Polycam) and joined them with the building's fire plan into one building model: 63 spaces,
   99 openings, 14 exits.
2. **Engine.** Pick where a fire starts. The engine works out how smoke fills each room over time,
   when flashover could happen, which exits are lost and when, and a capacity-aware route out for
   every occupied room. It compares those routes with the way people would pick themselves. The
   building page draws it all on the 3D scan with a fire clock you can scrub, and a size-up panel
   gives responders the short version: first exit lost, exits lost, rooms at risk.
3. **Live response.** A dispatcher declares a drill on the live console. People who registered by
   texting our line get an alert by text (Photon), and can ask for a call from an ElevenLabs voice
   agent. Every text and call line goes into TigerData, and reports of trouble, hazards and handoffs wake
   a staff of six CREAO agents (we built them on agent.creao.ai), led by an Incident Commander. They triage what people say, pin hazards on the map,
   propose route changes, keep the roll call, ask Aria to call people who haven't answered, brief
   arriving crews and keep a signed incident report. Every route change waits for the dispatcher
   to approve it before anyone is texted. When the drill ends, the CREAO Incident Scribe writes the
   after-action report.

## How we built it

- **Engine** (`packages/engine`, plain Python): a zone model of the building from `venue.json`.
  Fire grows on a t² curve capped by fuel and air, smoke fills each room as one layer and spills
  through doors, and flashover comes when the fire's heat release reaches Thomas's threshold for the room's size
  and openings. A space becomes
  untenable when its smoke layer drops below 2 m or passes 200 °C (ISO 13571-style limits), and
  that is when its exits are lost. It is a worst-case pre-plan: no sprinklers or smoke control.
  Routes are capacity-aware, so a crowd doesn't all get sent to one door. The API serves it on demand (`/engine/starts`,
  `/engine/viewer`, `/engine/summary`).
- **Scan and model:** four Polycam scans joined into one GLB in the venue's frame, room geometry
  snapped to the scan, the rest of the building read from the fire plan. The GLB lives in Supabase
  Storage.
- **Web** (Next.js 16, React 19, Tailwind 4, Three.js, Mapbox GL, on Vercel): the map, the 3D scan
  with the fire timeline, smoke, lost exits and routes, the fire-start picker, place search and the
  size-up panel. The web app proxies the live console from the API.
- **Live layer** (FastAPI on Railway, TigerData): every event is a row in a TigerData hypertable,
  and a trigger fires `pg_notify`. The API listens, streams each event to the console and the
  messenger, and starts the CREAO Incident Commander through its API Trigger with the new events
  and a snapshot of the situation. The Commander hands work to five specialists. Each agent ends
  its reply with an `aria-actions` block, and the API runs those actions through the same tools
  `/mcp` serves, after Aria's safety rules check them.
- **Messenger** (Node, `apps/messenger`): Photon for texts, an ElevenLabs voice agent for calls on
  the Photon voice number. Trigger words hand a call to the dispatcher. Every text and call line
  goes back to the live layer.
- **Observability:** Sentry on the web app and the API (Tracing, Session Replay, Logs, Profiling).
- **Tests:** engine and API tests with pytest, and Playwright smoke tests that run against the
  deployed site without ever declaring a drill.

## Challenges we ran into

- **CREAO can't attach a custom MCP connector to an agent.** We had built `/mcp` for the staff to
  call. Instead, each run's inputs carry a snapshot of the situation, and each agent ends its reply
  with an `aria-actions` block. When CREAO calls our webhook, the API runs those actions through
  the same tool functions `/mcp` serves (`66f7c6b`).
- **Late replies.** A CREAO reply can land after a drill has ended. We made those replies write
  only reports and notes, so a late route change can't reach anyone (`870401a`).
- **The live hub couldn't hear the database.** Tiger Cloud rejected the `ssl` setting asyncpg sent,
  so LISTEN kept dropping and nothing reached the CREAO staff. Sentry Logs showed the warning 832
  times in 33 minutes; translating it to `sslmode` fixed it (`6aa8385`).
- **The live event stream through the Next.js proxy** was held back by gzip. We turned compression
  off for the proxy so events reach the console as they happen (`94772fa`).
- **The console's 3D view wouldn't move.** OrbitControls were bound to the label layer, which has
  `pointer-events: none`. They now listen on the WebGL canvas (`66ff696`).
- **The exit-names toggle did nothing.** CSS2DRenderer rewrites each label's `display` every frame
  from the object's visibility, so hiding by style was undone at once. The toggle now sets the
  object's `visible` flag (`a051a6d`).
- **Honest numbers.** Our first version showed people counts that were really assumed room
  capacities. We changed the UI and the agents' inputs to report rooms, not headcounts (`1f96b62`).

## Accomplishments that we're proud of

- A real building: our own phone scans of the venue, fitted to its fire plan, drive the whole demo.
- The engine and the live response use the same model, so the console, the size-up and the CREAO
  staff agree on what the fire is doing.
- Six CREAO agents run a real drill end to end, from the first text to the after-action report,
  and the dispatcher stays in control of every route change.
- Real texts and real phone calls during a drill, with a handoff to a human on trigger words.
- Everything is deployed, and the Playwright smoke tests pass against the live site.

## What we learned

- Agents are most useful when they hand off to people at the right moment. Making every route change
  a proposal for the dispatcher kept the agents useful and the system safe.
- Give agents a snapshot and a small set of actions, and check every action before it runs. When
  the platform couldn't call our tools, putting actions in the reply worked just as well.
- Observability set up in the first hours paid off: Sentry recorded a dead database stream and a
  half-finished refactor, with logs and a replay, and confirmed each fix.
- Be careful with numbers in a safety product. A modelled number shown as a real one is worse than
  no number.

## What's next for Aria

- Scan the whole building, every floor.
- Batch the console's situation queries (Sentry tracing showed up to 15 sequential queries,
  about 2.2 s at p95 on Railway).
- An Uptime monitor on the API, and alerts for new Sentry issues.
- Pre-plans for more buildings, starting with the ones fire departments ask for.
- A run with a real fire department during a planned drill.

## Built with

`python` `fastapi` `typescript` `next.js` `react` `tailwindcss` `three.js` `mapbox`
`supabase` `postgresql` `timescaledb` `tigerdata` `creao` `photon` `elevenlabs` `sentry`
`vercel` `railway` `docker` `polycam` `playwright`

## Built at LA Hacks

Hacking started Sat Oct 17 at 12:00 PM PDT. The first commit is Sat 1:37 PM.

**Built at the event**

- The building engine (`packages/engine`): the venue model of James West from our scans and the
  fire plan, fire and smoke over time, exits lost over time, capacity-aware evacuation routes and a
  size-up. Served by `/engine/*` on the API.
- The four-room venue scan, joined into one model. The viewer shows fire spread, smoke, lost exits
  and routes; you pick where the fire starts; place search; the size-up panel.
- The CREAO live layer: six CREAO agents (an Incident Commander and five specialists) run a drill
  from TigerData events, act through our tools, and write the live report and the after-action
  report. A dispatcher approves route changes.
- TigerData live event store with hypertables, continuous aggregates and LISTEN/NOTIFY streaming.
- The messenger: Photon texts and ElevenLabs voice calls that carry the dispatcher-approved routes.
- Sentry on the web app and the API; a new Supabase project; the Vercel and Railway deploys; the
  restyle; Playwright smoke tests.

**From before the event** (Aria, our earlier project, Oct 6 2026)

- The Next.js shell, the landing page and globe, the Mapbox dashboard, a basic Three.js scan
  viewer, the FastAPI skeleton and three Supabase migrations.
- That project's flood agent and flood UI were deleted at the event and are not part of this
  submission.

## CREAO

Six agents built on agent.creao.ai run Aria's live incident command: they triage callers' and
texters' words, pin hazards, propose route changes the dispatcher approves, run the roll call and
request calls, brief responders, and keep the signed live incident report and the after-action
report. The API starts them through each agent's API Trigger from TigerData events, and applies
the `aria-actions` in their replies through the same tools `/mcp` serves.

- **Run share link (Incident Commander):** https://agent.creao.ai/share/46bf0fc2477da75e00d139e9eafbfb0e
- **Aria run id:** `fb19956e68d744059d8773a3c300a26e`
- **Agent IDs:**

| Role | Agent ID |
|---|---|
| Incident Commander | `ef349685-a692-4a0d-ae20-eb2e1f524624` |
| Intake Analyst | `113efaf2-fd95-4ca2-9e84-3f3481309423` |
| Evacuation Coordinator | `e433f077-c48d-4080-8d6f-4ff771633c06` |
| Accountability Officer | `2d6f125c-13a4-4872-a54d-0471491485f8` |
| Responder Liaison | `20ca703a-c164-48af-8752-69887706dd04` |
| Incident Scribe | `db6d854b-42ed-4df9-be21-90131c53ec3e` |

Public links for all six: https://github.com/Bazaza17/aria-lahacks#the-agents. In the demo, the
agents run on the live console (the CREAO strip, the agent steps in the log, the CREAO incident
report drawer and the CREAO after-action report), with a cut to the same Incident Commander run on
agent.creao.ai.

## How Sentry shaped Aria

We set up Sentry in the first hours of LA Hacks on both halves of Aria:

- `aria-web`: the Next.js viewer and console on Vercel.
- `aria-api`: FastAPI on Railway, which also runs the fire engine and the CREAO live layer.

Beyond error monitoring we use four products:

- **Tracing:** browser → Vercel → API, 100% sampled, with `sentry-trace` and `baggage` passed to
  the API.
- **Session Replay:** every session, with text unmasked because the viewer holds no personal data.
- **Logs:** the API's Python logging goes to Sentry Logs.
- **Profiling:** continuous profiling on the API, including the engine routes.

Browser events go through our own `/aria-relay` tunnel so ad blockers don't drop them. While fixing
bugs, Claude Code read our issues, logs and traces through the Sentry MCP.

**1. Logs: the live layer couldn't hear the database, and Sentry showed when it could again.**
At 3:04 AM Sunday, Sentry Logs started filling with one API log line: `TigerData LISTEN dropped
(parameter "ssl" cannot be changed now); reconnecting`. It repeated every few seconds, 832 times in
33 minutes, on the laptop and on Railway. It meant the live hub never subscribed to database
events, so nothing reached the CREAO Incident Commander or the dispatcher console's live stream.
The cause was the database URL's `ssl=require`, which raw asyncpg sends to Tiger Cloud as a server
setting. The fix (`6aa8385`) translates it to `sslmode` and adds a test. The last one in Sentry
is at 3:37 AM, and none has come since.

**2. Session Replay + Errors: a refactor caught mid-move.**
While restyling the building page, we moved the fire-start picker and the fire timeline out of the
3D scan into a shared provider. In 44 seconds Sentry recorded five errors for names the scan still
used after the move (ARIA-WEB-6 to -A). They came from the browser and from the server render, and the
replay (a0fc532d) shows the page while they happened. The commit that finished the move
(`e94f964`) removes every one of those names, and none of the five has come back.

**3. Session Replay: a broken search and a missing file.**
The place search crashed on its first submit (ARIA-WEB-3), and the replay shows the click and the
crash. The feature shipped five minutes later (`67ab53c`). Separately, the building page failed to
compile 12 times across the morning (ARIA-WEB-4, `Can't resolve './ScanSelectionCard'`, with 3
replays). We moved the card into the scan component; the last error was at 8:22 AM, and the fix is in `311bf95`.

**4. Tracing: one false alarm, one real find.**
Sentry flagged "N+1 API Call" on the building page. The trace showed the repeated calls are `blob:`
URLs, which is three.js unpacking the textures inside our scan file in memory, about 20 ms each.
That isn't a network problem, so we left it. The same traces showed a real one. On Railway, the
console's situation call runs up to 15 database queries one after another, about 2.2 s at p95. We
found it Sunday morning and didn't fix it before the code freeze.

**What we'd add next:** batch the situation queries, add an Uptime monitor on the Railway API, and
set alerts for new issues.

## Prize tracks to opt into

| Track | Why Aria qualifies | Human action on the form |
|---|---|---|
| **Applied Intelligence** (main track) | A fire pre-plan from a phone scan, and a live response run by AI agents with a human approving | Select it as the main track |
| **CREAO** | Six CREAO agents run the live incident command; the README has the agent IDs and a run share link; the video shows them running | Opt in and pick one category: Disruptor or Team Empowerment (we're a team of three). Swap in the run share link first |
| **Sentry: Best Use of Sentry** | Tracing, Session Replay, Logs and Profiling, with real moments above | Opt in; add the screenshots (Sentry links only work for org members) |
| **Photon: Messaging/Calling Agent** | Drill alerts and replies over Photon, voice calls on the Photon number, a dispatcher in the loop, canned fallback | Opt in (iMessage and/or Best Voice); the messenger must be running at judging |
| **ElevenLabs** (MLH) | The voice agent that calls people during a drill and hands trigger-word calls to the dispatcher | Opt in |
| **Tiger Data** (MLH) | The live layer's database: hypertables, continuous aggregates, `pg_notify` streaming that wakes the CREAO staff | Opt in |
| **Paper: Best Designed Hack** | The web app follows our locked Paper design ("Aria — LA Hacks design") | Opt in if we want it; add screenshots of the design next to the live pages |
| **Commit Fellowship** (MLH) | A working prototype built by a team of three | Opt in at submission and fill in the supplemental form |

Not entering: Fetch.ai / Agentverse (that code was removed), Even Realities (its brief bans
emergency-routing apps).

## Links

- Repo: https://github.com/Bazaza17/aria-lahacks
- Live site: https://aria-lahacks.vercel.app
- Live dispatcher console: https://aria-lahacks.vercel.app/live/view
- API health: https://aria-lahacks-production.up.railway.app/health
- Video: https://www.youtube.com/watch?v=XaDfIjDk314

---

## Editor notes (don't paste)

- **Run share link.** The Commander run `e3b669dc…` started at 18:02:02 UTC, about 1.5 minutes after
  the 10:58–11:00 AM drill ended, so only 3 of its 7 actions applied (by design, a late reply only
  writes reports and notes). A Commander run from during a drill, such as the one recorded for the
  video, is a stronger share. The Scribe's after-action run `cdc8a443-b769-4ef7-90db-f90988747cc0`
  (agent ID `db6d854b-42ed-4df9-be21-90131c53ec3e`) applied 2 of 2. Whichever run is shared, the
  agent ID next to it must be that agent's, and the run id line must match.
- **Phone numbers.** The Commander's task text in a CREAO run may carry unmasked phone numbers.
  Check the run page before sharing it.
- **Agent page ID.** Check that the ID shown on the Commander's agent.creao.ai page matches
  `ef349685-a692-4a0d-ae20-eb2e1f524624`.
- **Repo visibility.** The repo is private; it has to be public for judging. The earlier Aria
  repo the ported code came from is private too, and the event rules allow pre-existing work only
  if it is open source. The team needs to decide how to handle that.
- **Challenges not included** because nothing in git or the docs confirms them: Vercel refusing to
  deploy commits from authors outside the Vercel team, and the dispatcher handoff failing when the
  test caller's phone was the dispatcher's number. Add them if they happened.
- **Sentry screenshots:** the "LISTEN dropped" Logs search ending at 3:37 AM, replay a0fc532d with
  its error list, and trace 899c8c47 with the situation span and its database children.
