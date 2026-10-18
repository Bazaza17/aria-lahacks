import { createServer } from "node:http";
import { setTimeout as sleep } from "node:timers/promises";
import { listInbound, sendText, type Inbound } from "./photon.ts";
import { contacts, sendAlert, sendInstruction, agentContext, NotRegisteredError, type AlertInput } from "./alert.ts";
import { askAgent } from "./eleven.ts";
import { startCall, getConversation, CallingNotConfiguredError } from "./voice.ts";
import { liveEnabled, reportText, reportSent, reportCall, registerOccupants, followLive, followCall } from "./aria-live.ts";

const PORT = Number(process.env.PORT ?? 8787);
const POLL_MS = 2_000;

function remember(m: Inbound) {
  const isNew = !contacts.has(m.from);
  contacts.set(m.from, { handle: m.from, spaceId: m.spaceId, agentId: m.agentId });
  return isNew;
}

// Send a text, and tell Aria's live layer what was said and who wrote it (when ARIA_LIVE_URL is set).
async function say(to: { from: string; spaceId: string; agentId: string }, text: string, by: "agent" | "aria" = "aria") {
  await sendText(to, text);
  if (liveEnabled) void reportSent(to.from, text, by);
}

async function handleInbound(m: Inbound) {
  console.log(`[messenger] in  from ${m.from}: ${m.text === null ? "(non-text)" : `${m.text.length} chars`}`);
  const isNew = remember(m);
  if (m.text === null) return;
  // Aria's live layer logs it, pins any hazard or place it names, and returns the approved route.
  const live = liveEnabled ? await reportText(m.from, m.text, m.id) : null;

  if (isNew) {
    if (liveEnabled) void registerOccupants([{ phone: m.from }]);
    await say(m, "You're registered for Aria emergency alerts at James West Alumni Center. We'll text you here if there's an incident.");
    console.log(`[messenger] out registration to ${m.from}`);
    return;
  }

  // Rules run before the AI (design doc §4).
  if (/^\s*call\b/i.test(m.text)) {
    if (liveEnabled) {
      // Aria queues the call (occupant.call_requested); placing it here too would ring them twice
      await say(m, "Calling you now from Aria. Pick up and we'll talk you through it.");
      return;
    }
    await callPerson(m);
    return;
  }
  // An answer to the alert (1 leaving, 2 needs help finding an exit, HELP, SAFE): Aria's rules reply
  // with the dispatcher-approved route, word for word. "2" also gets a guiding call from Aria.
  if (live?.answer) {
    await say(m, live.answer);
    console.log(`[messenger] out answer to ${m.from}`);
    return;
  }

  // Anything else: the ElevenLabs agent answers, with the approved route as its only layout facts.
  let reply: string, by: "agent" | "aria" = "agent";
  const started = Date.now();
  try {
    reply = await askAgent(m.from, m.text, agentContext(m.from));
    console.log(`[messenger] agent replied in ${Date.now() - started}ms`);
  } catch (err) {
    console.error("[messenger] agent failed, using fallback:", err instanceof Error ? err.message : err);
    by = "aria";
    reply =
      live?.instruction?.message ?? // the dispatcher-approved route, when an evacuation is on
      "Follow the nearest lit exit sign and responders' directions. Reply HELP if you need a person, or call 911 if you're in danger.";
  }
  await say(m, reply, by);
  console.log(`[messenger] out reply to ${m.from}`);
}

async function callPerson(m: Inbound) {
  try {
    await say(m, "Calling you now from Aria. Pick up and we'll talk you through it.");
    await placeCall(m.from);
  } catch (err) {
    console.error("[messenger] call failed:", err instanceof Error ? err.message : err);
    const why = err instanceof CallingNotConfiguredError ? "Calling isn't set up yet." : "We couldn't place the call.";
    await say(m, `${why} Keep texting here, or call 911 if you're in danger.`);
  }
}

async function placeCall(phone: string) {
  const { conversationId } = await startCall(phone, agentContext(phone));
  console.log(`[messenger] call started to ${phone} (${conversationId})`);
  if (liveEnabled && conversationId) {
    await reportCall("call.started", phone, conversationId);
    void followCall(phone, conversationId, getConversation); // the transcript flows into Aria's live layer
  }
}

// Rebuild who's reachable from the last week of messages, without replying to them.
const seen = new Set<string>();
for (const m of await listInbound(new Date(Date.now() - 7 * 24 * 3600_000))) {
  seen.add(m.id);
  remember(m);
}
console.log(`[messenger] connected to Photon; ${contacts.size} registered contact(s)`);

// Aria's live layer (opt-in): who's reachable, and what the dispatcher wants sent or called.
if (liveEnabled) {
  void registerOccupants([...contacts.keys()].map((phone) => ({ phone })));
  void followLive({
    text: async (phone, message, by = "aria") => {
      try {
        await sendInstruction(phone, message);
        void reportSent(phone, message, by);
        console.log(`[messenger] out instruction to ${phone}`);
      } catch (err) {
        console.error(`[messenger] couldn't text ${phone}:`, err instanceof Error ? err.message : err);
      }
    },
    call: async (phone, reason) => {
      console.log(`[messenger] call requested for ${phone}: ${reason}`);
      await placeCall(phone).catch((err) => console.error(`[messenger] call to ${phone} failed:`, err instanceof Error ? err.message : err));
    },
    handoff: async (phone) => {
      const c = contacts.get(phone);
      if (c) await say({ from: phone, ...c }, "A dispatcher is taking over now. Keep this line open; they'll reach you here or by phone.");
    },
  });
}

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
