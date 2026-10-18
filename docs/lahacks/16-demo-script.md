# Demo video script (2–3 minutes)

> For the Devpost video and the live judging walk-through. Target 2:45. Every claim in the
> voice-over is in the code; say "rooms", never a people count. The CREAO beat at 1:05–1:55 is
> what satisfies CREAO rule 03 ("show the agent running in your demo"); don't cut it.

## Pre-recording checklist

Declaring a drill on the live console texts and calls real phones. Only teammates' phones should
be registered, and a human on the team runs every step below.

- [ ] **One messenger running only**, on Sai's machine, pointed at the Railway API. Two running
      would send every text and call twice.
- [ ] **`DISPATCHER_PHONE` set on Railway** (the API's Join call) and in the messenger's env
      (the voice agent's transfer). Run `npm run agent:sync` after changing it.
- [ ] **The test caller's phone is not the dispatcher's phone.** A call can't be handed to the
      number it is already on.
- [ ] **The test phone is registered:** it has texted the line once.
- [ ] **Clear stale handoffs:** with no drill running, press **Clear** on the console so leftover
      incidents, hazards and handoffs from earlier drills are gone. Check that "Needs you" is empty.
- [ ] **Drill mode only.** Never use live mode (it needs a dispatcher key; leave it unset).
- [ ] **CREAO run page (required: CREAO rule 03):** Aayush is logged in to agent.creao.ai with the
      Incident Commander's runs open. Never show the
      `capi_` key or the API Trigger settings. Blur any phone numbers in the run's inputs.
- [ ] Screen recording at 1080p or higher, browser zoom 100%, notifications off.
- [ ] Phone screen mirrored or a second camera on the phone, so the text and the call show.
- [ ] Tabs open in order: landing, dashboard, building page, live console, agent.creao.ai
      (Aayush's account), Sentry (Logs search, replay a0fc532d).
- [ ] After recording, swap the real Commander run id from "Show agent steps" into the README, the
      Devpost and docs/creao-layer.md ("Agent links") if it differs from `e3b669dc-2e26-4529-a669-db8e787a160d`, and use that run's
      share link for `CREAO_RUN_SHARE_LINK`.

## Script and shot list

| Time | Shot | Voice-over |
|---|---|---|
| 0:00–0:20 | Each teammate on camera, one at a time | **Lincoln:** "I'm Lincoln. I built Aria's fire engine, the building scan and the web app." **Aayush:** "I'm Aayush. I built the live layer: six CREAO agents on TigerData." **Sai:** "I'm Sai. I built the messenger: Photon texts and ElevenLabs calls." |
| 0:20–0:30 | Landing page (`/`), then click Open Dashboard | **Lincoln:** "When fire crews arrive, they may never have been inside the building. Aria gives them a pre-plan from a phone scan, and helps run the evacuation." |
| 0:30–0:40 | Dashboard: the map centred on the James West Alumni Center; the pre-plan panel | "This is the building we're in. We scanned it with a phone and joined the scans to its fire plan." |
| 0:40–1:05 | Building page. Pick the fire start (Collins Room). Scrub the fire clock: smoke fills rooms, exits turn red, white routes vs red "own way" routes. Point at the size-up panel | "Pick where the fire starts. Our engine works out how smoke fills each room, which exits are lost and when, and a route out for every occupied room. White is Aria's route; red is the way people would pick themselves. The size-up tells responders when the first exit goes and how many rooms are at risk." |
| 1:05–1:15 | Click the live response card → live console (`/live/view`). Pick the fire origin, press **Declare** (drill), confirm | **Aayush:** "Now a drill. The dispatcher declares it here. From this moment six CREAO agents run the incident command." |
| 1:15–1:30 | Phone: the drill text arrives (Photon). Reply CALL (or 2); the ElevenLabs call rings; say where you are | **Sai:** "Everyone who registered gets a text. Reply CALL and our ElevenLabs voice agent calls you and gives you the approved route for where you are." |
| 1:30–1:45 | Console: the CREAO strip's dots light up. Press **Show agent steps**: "Woken by Aria…", "Started in CREAO (run id)", "Aria ran N of M action(s) from the reply". Press **6 agents · details** | **Aayush:** "Every text and call lands in TigerData, and anything that needs a decision wakes the CREAO Incident Commander. It hands work to five specialists. Here are their runs, live." |
| 1:45–1:55 | **CREAO rule 03 beat.** Cut to agent.creao.ai: the Incident Commander's page for 2 s (its agent ID visible, matching the README), then the run with the same run id as the console's "Started in CREAO" line, still running. A Commander run takes about a minute, so open it as soon as that line appears; record this tab as its own take and cut it in. Then back to the console: click the pin → **CREAO incident report** drawer with signed sections | "This is that same run on CREAO. Back in the console, the incident report is written and signed by the agents: hazards, the roll call, the briefing for fire crews." |
| 1:55–2:10 | "Needs you": a route-change card, "Proposed by the coordinator". Press **Approve**. The phone gets the new route | **Lincoln:** "The agents never text anyone themselves. When the Evacuation Coordinator wants to move people, the dispatcher approves it, and only then does the text go out." |
| 2:10–2:20 | Press **End**, confirm. The **CREAO after-action report** opens | "End the drill, and the CREAO Incident Scribe writes the after-action report from TigerData." |
| 2:20–2:35 | **Sentry beat.** Sentry Logs: the "TigerData LISTEN dropped" burst ending at 3:37 AM. Then replay a0fc532d with its errors | **Aayush:** "Sentry ran on everything from the first hours. At 3 AM its logs showed our database stream dropping 832 times in half an hour, so the agents heard nothing. One fix, and it stopped. Replays caught a half-finished refactor the same night." |
| 2:35–2:50 | Architecture diagram from the README, then the building page | **Lincoln:** "Under the hood: a Python fire engine served by FastAPI on Railway, Next.js and Three.js on Vercel, TigerData streaming every event, CREAO for the command staff, Photon and ElevenLabs for people. The hardest parts: CREAO couldn't attach our MCP tools, so the agents' actions ride in their replies and we check every one; and keeping every number honest, so Aria reports rooms, not guesses at people. Aria: know the building before the truck arrives." |

## If something fails while recording

- **No text arrives:** check that only one messenger is running and that the phone has texted the
  line once. Don't declare again until the first drill has ended (it also ends itself after 20
  minutes).
- **The CREAO dots stay grey:** open https://aria-lahacks-production.up.railway.app/live/health
  and check `creao_staff` lists all six and LISTEN is connected. Record the console part again
  after the next agent step.
- **A route proposal arrives after End:** that's by design. Late replies only write reports and
  notes. Record the approval beat in the next drill.
- **Call doesn't transfer to the dispatcher:** check that the caller's phone isn't the dispatcher's
  number, and that `DISPATCHER_PHONE` is set.

## Live judging (in person, 12:30 PM, Collins Conference Room)

Use the same order without the video cuts: building page → console → declare a drill on a
teammate's phone → show the agent steps and the CREAO run page → approve a route → End → the
after-action report. Keep the Sentry tab and the README's CREAO section open for questions.
