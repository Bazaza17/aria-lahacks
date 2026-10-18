// Optional bridge to Aria's live incident layer: apps/api /live (data in TigerData, the CREAO
// command staff on top). Off unless ARIA_LIVE_URL is set; then:
//   in:  every text received and sent, every call (and its transcript), every registered contact
//   out: alerts, approved route changes and re-texts to send, people to call, handoffs
// Never blocks texting: if the API is down, the messenger carries on as before.
// Contract: docs/creao-layer.md.

const { ARIA_LIVE_URL, ARIA_TOOL_SECRET } = process.env;
const BUILDING = process.env.ARIA_BUILDING_ID ?? "547b5ec5-30c5-4f76-8080-012a52e90bd9"; // James West Alumni Center

export const liveEnabled = Boolean(ARIA_LIVE_URL);

export type LiveReply = {
  status?: string;
  /** Aria's own answer to a reply to the alert (1, 2, HELP, SAFE): send it as is, no AI. */
  answer?: string | null;
  instruction?: { message?: string | null; exit_label?: string | null; exits?: string[] };
  route_change_pending?: boolean;
};

// Each person's dispatcher-approved route (what the agent may repeat) and the last thing Aria sent them.
const approved = new Map<string, string>();
const lastSent = new Map<string, string>();

const headers = () => ({ "content-type": "application/json", ...(ARIA_TOOL_SECRET ? { "x-tool-secret": ARIA_TOOL_SECRET } : {}) });

async function post(path: string, body: unknown): Promise<any | null> {
  if (!ARIA_LIVE_URL) return null;
  try {
    const res = await fetch(`${ARIA_LIVE_URL}${path}`, {
      method: "POST",
      headers: headers(),
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(8_000),
    });
    if (!res.ok) {
      console.error(`[aria-live] ${path} -> ${res.status}`);
      return null;
    }
    return await res.json();
  } catch (err) {
    console.error(`[aria-live] ${path} failed:`, err instanceof Error ? err.message : err);
    return null;
  }
}

let seq = 0;
const newId = () => `messenger-${Date.now()}-${++seq}`;

function event(eventType: string, payload: Record<string, unknown>, eventId = newId()) {
  return post("/live/intake/events", { eventId, eventType, source: "photon", payload: { buildingId: BUILDING, ...payload } });
}

/** A text someone sent us. Returns the approved instruction for them, if an evacuation is on. */
export async function reportText(phone: string, text: string, photonMessageId: string): Promise<LiveReply | null> {
  const res = await event("sms.received", { phone, text }, `photon:${photonMessageId}`);
  const reply = (res?.reply ?? null) as LiveReply | null;
  if (reply?.instruction?.message) approved.set(phone, reply.instruction.message);
  return reply;
}

/** A text we sent: by the ElevenLabs agent, by Aria's rules / an approved route, or a dispatcher re-send. */
export function reportSent(phone: string, text: string, by: "agent" | "aria" | "dispatcher" = "aria") {
  lastSent.set(phone, text);
  return event("sms.sent", { phone, text, by });
}

type CallEvent = "call.started" | "call.transcript" | "call.transferred" | "call.ended";
export function reportCall(kind: CallEvent, phone: string, conversationId: string, extra: Record<string, unknown> = {}) {
  return event(kind, { phone, conversationId, ...extra }, kind === "call.transcript" ? undefined : `${kind}:${conversationId}`);
}

export function registerOccupants(people: { phone: string; name?: string }[]) {
  if (!people.length) return Promise.resolve(null);
  return post(`/live/buildings/${BUILDING}/occupants`, { people });
}

/** Extra agent context from the live layer: the route the dispatcher approved for this person. */
export function liveContext(phone: string): Record<string, string> {
  const route = approved.get(phone), last = lastSent.get(phone);
  if (!route && !last) return {};
  return {
    ...(route ? { route } : {}),
    last_instruction: last ?? route!,
    incident: "fire reported (see last_instruction)",
  };
}

export function rememberApproved(phone: string, message: string) {
  approved.set(phone, message);
}

export type CallLine = {
  role: string;
  message: string | null;
  time_in_call_secs?: number;
  tool_calls?: { tool_name: string; params_as_json?: string }[] | null;
};
export type CallState = { status: string; transcript: CallLine[]; terminationReason?: string; startedAt?: number };

const POLL_MS = Number(process.env.ARIA_CALL_POLL_MS ?? 10_000);

/** Forward a call's transcript: polls the conversation until it ends. ElevenLabs only fills the
 *  transcript once the call is over, so each line carries when it was said (call start + time in call);
 *  live, mid-call updates come from the agent's update_aria tool instead. When the agent hands the call
 *  to a person (ElevenLabs transfer_to_number, on a trigger word), Aria is told. */
export async function followCall(phone: string, conversationId: string, fetchConversation: (id: string) => Promise<CallState>) {
  let sent = 0, transferred = false, reason: string | undefined;
  for (let i = 0; i < 120; i++) {
    await new Promise((r) => setTimeout(r, POLL_MS));
    try {
      const c = await fetchConversation(conversationId);
      for (const t of c.transcript.slice(sent)) {
        if (t.message) {
          await reportCall("call.transcript", phone, conversationId, {
            role: t.role === "user" ? "user" : "agent",
            text: t.message,
            timeInCallSecs: t.time_in_call_secs,
            ...(c.startedAt && t.time_in_call_secs !== undefined
              ? { at: new Date((c.startedAt + t.time_in_call_secs) * 1000).toISOString() }
              : {}),
          });
        }
        const transfer = t.tool_calls?.find((x) => x.tool_name === "transfer_to_number");
        if (transfer && !transferred) {
          transferred = true;
          let params: Record<string, unknown> = {};
          try { params = JSON.parse(transfer.params_as_json ?? "{}"); } catch { /* keep going */ }
          await reportCall("call.transferred", phone, conversationId, {
            to: params.transfer_number ?? params.phone_number ?? null,
            reason: String(params.reason ?? params.condition ?? "trigger word"),
          });
        }
      }
      sent = c.transcript.length;
      reason = c.terminationReason;
      if (c.status === "done" || c.status === "failed") break;
    } catch (err) {
      console.error("[aria-live] call transcript:", err instanceof Error ? err.message : err);
    }
  }
  await reportCall("call.ended", phone, conversationId, reason ? { reason } : {});
}

export type LiveHandlers = {
  /** Text this person this exact message (an alert, an approved route change, a dispatcher re-send). */
  text: (phone: string, message: string, by?: "aria" | "dispatcher") => Promise<void>;
  /** Call this person (they didn't reply, or a CREAO agent asked). */
  call: (phone: string, reason: string) => Promise<void>;
  /** A dispatcher took over this person's call or thread. */
  handoff: (phone: string, transferTo: string | null) => Promise<void>;
};

/** Listen to the live stream (streamed out of TigerData) and act on what's for us. */
export async function followLive(h: LiveHandlers) {
  if (!ARIA_LIVE_URL) return;
  const url = `${ARIA_LIVE_URL}/live/stream?building_id=${BUILDING}`;
  for (;;) {
    try {
      const res = await fetch(url, { headers: { ...headers(), accept: "text/event-stream" } });
      if (!res.ok || !res.body) throw new Error(`stream ${res.status}`);
      console.log("[aria-live] following the live stream");
      const decoder = new TextDecoder();
      let buf = "";
      for await (const chunk of res.body) {
        buf += decoder.decode(chunk as Uint8Array, { stream: true });
        let cut: number;
        while ((cut = buf.indexOf("\n\n")) >= 0) {
          const block = buf.slice(0, cut);
          buf = buf.slice(cut + 2);
          const data = block.split("\n").find((l) => l.startsWith("data: "))?.slice(6);
          if (data) await dispatch(JSON.parse(data), h).catch((err) => console.error("[aria-live] handler failed:", err));
        }
      }
    } catch (err) {
      console.error("[aria-live] stream dropped:", err instanceof Error ? err.message : err);
    }
    await new Promise((r) => setTimeout(r, 3_000));
  }
}

async function dispatch(msg: { type?: string; data?: any }, h: LiveHandlers) {
  const d = msg.data ?? {};
  if (msg.type === "evacuation.started" || msg.type === "route.approved") {
    for (const r of (d.recipients ?? []) as { phone: string; message: string; route?: string }[]) {
      approved.set(r.phone, r.route ?? r.message); // the alert asks a question; the route comes with the answer
      await h.text(r.phone, r.message);
    }
  } else if (msg.type === "occupant.message" && d.phone && d.message) {
    // One text per event: the fire alert, an approved route change, or a dispatcher's re-send.
    // The alert asks a question, so the route they may be told comes alongside it.
    approved.set(d.phone, d.route ?? d.message);
    await h.text(d.phone, d.message, d.by === "dispatcher" ? "dispatcher" : "aria");
  } else if (msg.type === "occupant.call_requested" && d.phone) {
    await h.call(d.phone, d.reason ?? "follow-up call");
  } else if (msg.type === "handoff.joined" && d.caller) {
    await h.handoff(d.caller, d.transfer_to ?? null);
  }
}
