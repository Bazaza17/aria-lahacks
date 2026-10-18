// Thin wrapper over the Photon 2.0 API (https://photon.codes/docs/beta).
// The only file that talks to Photon directly.
import { randomUUID } from "node:crypto";
import { Photon } from "@photon-ai/api";

const { PHOTON_API_KEY, PHOTON_PROJECT_ID } = process.env;
if (!PHOTON_API_KEY || !PHOTON_PROJECT_ID) {
  const missing = [!PHOTON_PROJECT_ID && "PHOTON_PROJECT_ID", !PHOTON_API_KEY && "PHOTON_API_KEY"].filter(Boolean);
  console.error(`[messenger] missing env: ${missing.join(", ")} (set them in apps/messenger/.env)`);
  process.exit(1);
}

const photon = new Photon({
  ...(process.env.PHOTON_BASE_URL ? { baseUrl: process.env.PHOTON_BASE_URL } : {}), // local testing only
  headers: { Authorization: `Bearer ${PHOTON_API_KEY}` },
});
const project = { id: PHOTON_PROJECT_ID };

export type Inbound = {
  id: string;
  createdAt: string;
  from: string; // the person's handle, e.g. +14155551234
  spaceId: string;
  agentId: string; // our line's user id in that space; replies are sent as it
  text: string | null;
};

// The fields we read from a listMessages item (the generated union types are too loose under strict mode).
type RawMessage = {
  id: string;
  createdAt: string;
  sentBy: { kind: string; handle: string };
  receivedBy?: { id: string };
  space: { id: string; kind: string };
  content: { type: string; text?: string };
};

/** Received iMessages since `since`, oldest first. */
export async function listInbound(since: Date): Promise<Inbound[]> {
  const out: Inbound[] = [];
  let pageToken: string | undefined;
  do {
    const page = await photon.projects.listMessages({
      path: project,
      query: {
        createdSince: since.toISOString(),
        direction: "received",
        order: "asc",
        pageSize: 100,
        platform: "imessage",
        ...(pageToken ? { pageToken } : {}),
      },
    });
    for (const m of page.items as unknown as RawMessage[]) {
      if (m.sentBy.kind !== "human" || !m.receivedBy || m.space.kind !== "direct") continue;
      const c = m.content;
      out.push({
        id: m.id,
        createdAt: m.createdAt,
        from: m.sentBy.handle,
        spaceId: m.space.id,
        agentId: m.receivedBy.id,
        text: c.type === "text" ? (c.text ?? "") : null,
      });
    }
    pageToken = page.nextPageToken;
  } while (pageToken);
  return out;
}

// No parentMessageId: shared iMessage spaces reject threaded replies (SPACE_NOT_SENDABLE).
export async function sendText(to: { spaceId: string; agentId: string }, text: string) {
  return photon.projects.sendMessage({
    path: project,
    headers: { "idempotency-key": randomUUID() },
    body: {
      spaceId: to.spaceId,
      senderId: to.agentId,
      content: { type: "text", format: "plain", text },
    },
  });
}
