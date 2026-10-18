import { createServer } from "node:http";
import { setTimeout as sleep } from "node:timers/promises";
import { listInbound, sendText, type Inbound } from "./photon.ts";
import { contacts, sendAlert, agentContext, NotRegisteredError, type AlertInput } from "./alert.ts";
import { askAgent } from "./eleven.ts";
import { startCall, CallingNotConfiguredError } from "./voice.ts";

const PORT = Number(process.env.PORT ?? 8787);
const POLL_MS = 2_000;

function remember(m: Inbound) {
  const isNew = !contacts.has(m.from);
  contacts.set(m.from, { handle: m.from, spaceId: m.spaceId, agentId: m.agentId });
  return isNew;
}

async function handleInbound(m: Inbound) {
  console.log(`[messenger] in  from ${m.from}: ${m.text === null ? "(non-text)" : `${m.text.length} chars`}`);
  const isNew = remember(m);
  if (m.text === null) return;

  if (isNew) {
    await sendText(m, "You're registered for Aria emergency alerts at James West Alumni Center. We'll text you here if there's an incident.");
    console.log(`[messenger] out registration to ${m.from}`);
    return;
  }

  // Rules run before the AI (design doc §4). SAFE/HELP come next.
  if (/^\s*call\b/i.test(m.text)) {
    await callPerson(m);
    return;
  }

  let reply: string;
  const started = Date.now();
  try {
    reply = await askAgent(m.from, m.text, agentContext(m.from));
    console.log(`[messenger] agent replied in ${Date.now() - started}ms`);
  } catch (err) {
    console.error("[messenger] agent failed, using fallback:", err instanceof Error ? err.message : err);
    reply = "Follow the nearest lit exit sign and responders' directions. Reply HELP if you need a person, or call 911 if you're in danger.";
  }
  await sendText(m, reply);
  console.log(`[messenger] out reply to ${m.from}`);
}

async function callPerson(m: Inbound) {
  try {
    await sendText(m, "Calling you now from Aria. Pick up and we'll talk you through it.");
    const { conversationId } = await startCall(m.from, agentContext(m.from));
    console.log(`[messenger] call started to ${m.from} (${conversationId})`);
  } catch (err) {
    console.error("[messenger] call failed:", err instanceof Error ? err.message : err);
    const why = err instanceof CallingNotConfiguredError ? "Calling isn't set up yet." : "We couldn't place the call.";
    await sendText(m, `${why} Keep texting here, or call 911 if you're in danger.`);
  }
}

// Rebuild who's reachable from the last week of messages, without replying to them.
const seen = new Set<string>();
for (const m of await listInbound(new Date(Date.now() - 7 * 24 * 3600_000))) {
  seen.add(m.id);
  remember(m);
}
console.log(`[messenger] connected to Photon; ${contacts.size} registered contact(s)`);

createServer(async (req, res) => {
  const reply = (status: number, body: unknown) => {
    res.writeHead(status, { "content-type": "application/json", "access-control-allow-origin": "*" });
    res.end(JSON.stringify(body));
  };
  if (req.method === "GET" && req.url === "/health") return reply(200, { ok: true });
  if (req.method === "GET" && req.url === "/contacts") return reply(200, { contacts: [...contacts.keys()] });
  const ctx = req.method === "GET" && req.url?.match(/^\/context\/(\+\d+)$/);
  if (ctx) return reply(200, agentContext(ctx[1]!));
  if (req.method !== "POST" || req.url !== "/alert") return reply(404, { error: "not found" });

  try {
    let raw = "";
    for await (const chunk of req) raw += chunk;
    const input = JSON.parse(raw || "{}") as AlertInput;
    const sent = await sendAlert(input);
    console.log(`[messenger] out alert to ${sent.to} (${sent.status})`);
    reply(200, { ok: true, ...sent });
  } catch (err) {
    console.error("[messenger] alert failed:", err instanceof Error ? err.message : err);
    reply(err instanceof NotRegisteredError ? 409 : 400, { ok: false, error: err instanceof Error ? err.message : String(err) });
  }
}).listen(PORT, () => console.log(`[messenger] http on :${PORT} (POST /alert, GET /contacts)`));

// Poll for new inbound messages.
let since = new Date(Date.now() - 5_000);
while (true) {
  try {
    for (const m of await listInbound(since)) {
      if (seen.has(m.id)) continue;
      seen.add(m.id);
      since = new Date(Math.max(since.getTime(), Date.parse(m.createdAt) - 5_000));
      await handleInbound(m).catch((err) => console.error("[messenger] failed to handle message:", err));
    }
  } catch (err) {
    console.error("[messenger] poll failed:", err instanceof Error ? err.message : err);
  }
  await sleep(POLL_MS);
}
