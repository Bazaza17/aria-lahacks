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
