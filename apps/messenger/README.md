# messenger

Aria Alert's texting service, on the Photon 2.0 API (`@photon-ai/api`, docs: https://photon.codes/docs/beta). How it joins Aria's live layer: `docs/creao-layer.md` ("For Sai: the messenger bridge").

## Environment

Copy `.env.example` to `.env` and fill it in (see the comments there). Then create or update the ElevenLabs agent:

```sh
npm run agent:sync   # pushes src/agent-prompt.ts + knowledge/*.md to ElevenLabs
```

## Run

```sh
npm install
npm run start        # or: npm run dev
```

- `GET /health`, `GET /contacts`
- `GET /context/+1...` shows what the agent is told about a person
- `POST /alert` `{ "phone": "+1...", "name": "Sai", "floor": 2, "originFloor": 1, "drill": true }` texts one registered person.

Replies: "CALL" starts an ElevenLabs voice call through the Photon voice number; anything else goes to the ElevenLabs agent (chat mode) with the venue layout and the knowledge base (`knowledge/`).

**Venue facts.** With `ARIA_LIVE_URL` set, the layout the agent may use is the API's building brief
(`GET /live/buildings/{ARIA_BUILDING_ID}/brief`, header `X-Tool-Secret`, built from the engine's
`packages/engine/venue.json`), fetched at startup and every 5 minutes. Without it (or while the API
is down) the agent gets the static fallback in `src/venue.ts`, copied by hand from `venue.json`:
floors and rooms, the 14 exterior exits, the stairs, "elevators are not used in an evacuation" and
"outside, away from the building, where staff direct you". There are no fixed per-floor routes: a
person's route always comes from Aria's live (dispatcher-approved) instruction.
`knowledge/emergency-procedures.md` is general fire-safety guidance only; it names no places.

**After changing `src/agent-prompt.ts`, `src/venue.ts` or `knowledge/`, re-sync ElevenLabs:**
`npm run agent:sync`. The agent's prompt, placeholder variables (used for calls people make to the
number), tools and knowledge base only change in ElevenLabs when it runs; texts pick up the brief and
`src/venue.ts` on restart.

After a sync, check three things: the sync succeeds, a text still gets an agent reply (a chat session
starts), and a test call to the number reaches `/live/tools/update-evacuee`. The `phone` placeholder
is `""` and the tools read `system__caller_id` / `system__called_number`; if ElevenLabs rejects either,
texts fall back to the canned line. `call_direction` is `inbound` by default, `outbound` on calls Aria
places and `none` on texts; the agent only logs incidents (`log_incident_details`) on inbound calls.

A free shared iMessage line can't send the first message: each person texts the line once to register.

## Aria live layer (optional)

Set `ARIA_LIVE_URL` and `ARIA_TOOL_SECRET` and the messenger joins Aria's live incident layer
(`src/aria-live.ts`; contract in `docs/creao-layer.md`). Leave them empty and nothing changes.

- **In:** every text received and sent, every call and its transcript, and every registered
  contact go to the API, so the dispatcher and the CREAO staff see them (stored in TigerData).
- **Out:** the messenger listens to the live stream and texts each alert and each
  dispatcher-approved route change, and calls people who didn't reply.
- **Replies:** each text gets the dispatcher-approved instruction back. It goes into the
  ElevenLabs agent's context (`route`, `last_instruction`), and it's the fallback text if the
  agent fails. With no approved instruction, the canned fallback is logged as `by: "fallback"`,
  never as Aria.
- **First-time texters** during an evacuation get Aria's live instruction instead of the
  "we'll text you" registration line.
- **Who and what:** `occupant.message` events carry `name` (the agent greets them by it), `drill`
  (live-mode sessions never say "DRILL") and `by` (`"dispatcher"` sends are logged as the
  dispatcher's, with their initials).
- **Calls** are only placed to registered contacts (people who texted the line), never to a number
  that only appears in an event.


## Going live (real Photon and ElevenLabs)

To run it against the real Photon and ElevenLabs (the demo setup):

1. **Keys** in `.env`: `PHOTON_PROJECT_ID`, `PHOTON_API_KEY`, `ELEVENLABS_API_KEY`,
   `ELEVENLABS_AGENT_ID`, `ELEVENLABS_PHONE_NUMBER_ID` (the Photon voice number imported into
   ElevenLabs as a SIP-trunk number).
2. **Dispatcher number:** set `DISPATCHER_PHONE` (E.164), then run `npm run agent:sync`. That
   pushes the prompt, the trigger words and the agent's `transfer_to_number` + `end_call` tools
   into the ElevenLabs agent. Calls only move to the dispatcher once this has run.
3. **Aria:** `ARIA_LIVE_URL` (the API's URL), `ARIA_TOOL_SECRET` (the API's `CREAO_TOOL_SECRET`)
   and `ARIA_PUBLIC_URL` (the API's public URL, as ElevenLabs reaches it).
4. **Live call updates:** `npm run agent:sync` with `ARIA_PUBLIC_URL` set registers the
   `update_aria` webhook (`POST /live/tools/update-evacuee`; it sends the caller id when the
   `phone` variable is empty, so calls people make to the number reach the API too) and the
   `log_incident_details` webhook (`POST /live/tools/log-incident-details`), and stores the tool
   secret in ElevenLabs' secret store. ElevenLabs only returns a call's transcript after hang-up, so this tool
   is what puts where the caller is, how they are and any trigger word into TigerData mid-call, and
   it answers with the dispatcher-approved route for that spot. Re-sync whenever that URL changes
   (a quick tunnel's URL does on every restart).
5. **Start** with `npm start` (it reads `.env`). People register by texting the line once.
6. **Calls people make to the number:** they get the agent's neutral placeholder variables (no
   floor, no fire, drill unknown) and the `log_incident_details` tool from step 4.

For local tests, `ELEVENLABS_BASE_URL` points the messenger at a fake ElevenLabs and
`PHOTON_BASE_URL` at a fake Photon.
