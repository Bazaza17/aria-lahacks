# messenger — agent instructions

Aria Alert's texting service on the Photon 2.0 API (`@photon-ai/api`). Use the Beta docs only: https://photon.codes/docs/beta (not the Stable `spectrum-ts` docs).

- `src/photon.ts` is the only file that calls Photon.
- Secrets live in `.env` (gitignored). Do not read, write, or echo it.
- Shared iMessage lines: the person must text first, and threaded replies (`parentMessageId`) are rejected with SPACE_NOT_SENDABLE.
- Venue facts: the API's building brief, else `src/venue.ts` (copied from `packages/engine/venue.json`). Never invent places, exits, equipment or an assembly point. After changing the prompt, venue or `knowledge/`, the ElevenLabs agent needs `npm run agent:sync`.
