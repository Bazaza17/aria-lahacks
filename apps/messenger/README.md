# messenger

Aria Alert's texting service, on the Photon 2.0 API (`@photon-ai/api`, docs: https://photon.codes/docs/beta). Design: `docs/lahacks/08-alert-design.md`.

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

Replies: "CALL" starts an ElevenLabs voice call through the Photon voice number; anything else goes to the ElevenLabs agent (chat mode) with the venue layout (`src/venue.ts`, sample data) and the knowledge base (`knowledge/`).

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
  agent fails.


## Going live (real Photon and ElevenLabs)

Everything below was tested end to end against local fakes of both APIs (same endpoints and
shapes), so these are the only steps left:

1. **Keys** in `.env`: `PHOTON_PROJECT_ID`, `PHOTON_API_KEY`, `ELEVENLABS_API_KEY`,
   `ELEVENLABS_AGENT_ID`, `ELEVENLABS_PHONE_NUMBER_ID` (the Photon voice number imported into
   ElevenLabs as a SIP-trunk number).
2. **Dispatcher number:** set `DISPATCHER_PHONE` (E.164), then run `npm run agent:sync`. That
   pushes the prompt, the trigger words and the agent's `transfer_to_number` + `end_call` tools
   into the ElevenLabs agent. Calls only move to the dispatcher once this has run.
3. **Aria:** `ARIA_LIVE_URL` (the API's URL), `ARIA_TOOL_SECRET` (the API's `CREAO_TOOL_SECRET`)
   and `ARIA_PUBLIC_URL` (the API's public URL, as ElevenLabs reaches it).
4. **Live call updates:** `npm run agent:sync` with `ARIA_PUBLIC_URL` set registers the
   `update_aria` webhook (`POST /live/tools/update-evacuee`) and stores the tool secret in
   ElevenLabs' secret store. ElevenLabs only returns a call's transcript after hang-up, so this tool
   is what puts where the caller is, how they are and any trigger word into TigerData mid-call, and
   it answers with the dispatcher-approved route for that spot. Re-sync whenever that URL changes
   (a quick tunnel's URL does on every restart).
5. **Start** with `npm start` (it reads `.env`). People register by texting the line once.
6. **Optional, for calls people make to the number:** add the API's
   `POST /live/tools/log-incident-details` server tool in the agent (header `X-Tool-Secret`).

For local tests, `ELEVENLABS_BASE_URL` points the messenger at a fake ElevenLabs and
`PHOTON_BASE_URL` at a fake Photon.
