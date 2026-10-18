// Text chat with the ElevenLabs agent (chat mode over its WebSocket).
// One open session per person, so the agent keeps the thread; reopened with fresh context if it drops.
// Every wait has a timeout, and a session that closes early fails at once, so one stuck session can
// never halt the inbound loop.
const { ELEVENLABS_API_KEY, ELEVENLABS_AGENT_ID } = process.env;
const BASE = process.env.ELEVENLABS_BASE_URL ?? "https://api.elevenlabs.io"; // a local fake for testing

const SIGNED_URL_TIMEOUT_MS = 8_000;
const READY_TIMEOUT_MS = 10_000;
const REPLY_TIMEOUT_MS = 15_000;

export type AgentContext = Record<string, string>;

type Pending = { resolve: (text: string) => void; reject: (err: Error) => void };

type Session = {
  ws: WebSocket;
  ready: Promise<void>;
  pending: Pending | null;
};

const sessions = new Map<string, Session>();

async function signedUrl() {
  const res = await fetch(`${BASE}/v1/convai/conversation/get-signed-url?agent_id=${ELEVENLABS_AGENT_ID}`, {
    headers: { "xi-api-key": ELEVENLABS_API_KEY! },
    signal: AbortSignal.timeout(SIGNED_URL_TIMEOUT_MS),
  });
  if (!res.ok) throw new Error(`ElevenLabs signed URL ${res.status}`);
  return ((await res.json()) as { signed_url: string }).signed_url;
}

function drop(key: string, session: Session) {
  if (sessions.get(key) === session) sessions.delete(key); // not a newer session for the same person
}

async function open(key: string, context: AgentContext): Promise<Session> {
  const ws = new WebSocket(await signedUrl());
  const session: Session = { ws, ready: Promise.resolve(), pending: null };

  session.ready = new Promise<void>((resolve, reject) => {
    let settled = false;
    const settle = (err?: Error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (err) reject(err);
      else resolve();
    };
    const timer = setTimeout(() => {
      settle(new Error("ElevenLabs session didn't start in time"));
      ws.close();
    }, READY_TIMEOUT_MS);

    ws.addEventListener("open", () =>
      ws.send(
        JSON.stringify({
          type: "conversation_initiation_client_data",
          conversation_config_override: { conversation: { text_only: true } },
          dynamic_variables: { ...context, channel: "sms", call_direction: "none" },
        }),
      ),
    );
    ws.addEventListener("error", () => settle(new Error("ElevenLabs socket error")));
    ws.addEventListener("close", (ev) => {
      settle(new Error(`ElevenLabs session closed before it started (${ev.code})`));
      drop(key, session);
      session.pending?.reject(new Error(`ElevenLabs session closed (${ev.code})`));
      session.pending = null;
    });
    ws.addEventListener("message", (ev) => {
      let data: any;
      try {
        data = JSON.parse(String(ev.data));
      } catch {
        return; // not JSON: ignore
      }
      if (data.type === "conversation_initiation_metadata") settle();
      if (data.type === "ping") {
        ws.send(JSON.stringify({ type: "pong", event_id: data.ping_event?.event_id }));
      }
      if (data.type === "agent_response" && session.pending) {
        session.pending.resolve(data.agent_response_event?.agent_response ?? "");
        session.pending = null;
      }
    });
  });

  sessions.set(key, session);
  try {
    await session.ready;
  } catch (err) {
    drop(key, session);
    ws.close();
    throw err;
  }
  return session;
}

/** Ask the agent; `context` is only used when a new session has to be opened. */
export async function askAgent(key: string, text: string, context: AgentContext): Promise<string> {
  if (!ELEVENLABS_API_KEY || !ELEVENLABS_AGENT_ID) throw new Error("ElevenLabs env not set");
  const existing = sessions.get(key);
  const session = existing && existing.ws.readyState === WebSocket.OPEN ? existing : await open(key, context);

  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      session.pending = null;
      reject(new Error("ElevenLabs reply timed out"));
    }, REPLY_TIMEOUT_MS);
    session.pending = {
      resolve: (reply) => {
        clearTimeout(timer);
        if (reply.trim()) resolve(reply);
        else reject(new Error("ElevenLabs sent an empty reply"));
      },
      reject: (err) => {
        clearTimeout(timer);
        reject(err);
      },
    };
    session.ws.send(JSON.stringify({ type: "user_message", text }));
  });
}

/** Close a person's session so the next message reopens it with fresh context. */
export function resetAgent(key: string) {
  sessions.get(key)?.ws.close();
  sessions.delete(key);
}
