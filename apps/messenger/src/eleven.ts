// Text chat with the ElevenLabs agent (chat mode over its WebSocket).
// One open session per person, so the agent keeps the thread; reopened with fresh context if it drops.
const { ELEVENLABS_API_KEY, ELEVENLABS_AGENT_ID } = process.env;

const REPLY_TIMEOUT_MS = 15_000;

export type AgentContext = Record<string, string>;

type Session = {
  ws: WebSocket;
  ready: Promise<void>;
  pending: ((text: string) => void) | null;
};

const sessions = new Map<string, Session>();

async function signedUrl() {
  const res = await fetch(
    `https://api.elevenlabs.io/v1/convai/conversation/get-signed-url?agent_id=${ELEVENLABS_AGENT_ID}`,
    { headers: { "xi-api-key": ELEVENLABS_API_KEY! } },
  );
  if (!res.ok) throw new Error(`ElevenLabs signed URL ${res.status}`);
  return ((await res.json()) as { signed_url: string }).signed_url;
}

async function open(key: string, context: AgentContext): Promise<Session> {
  const ws = new WebSocket(await signedUrl());
  const session: Session = { ws, ready: Promise.resolve(), pending: null };

  session.ready = new Promise((resolve, reject) => {
    ws.addEventListener("open", () =>
      ws.send(
        JSON.stringify({
          type: "conversation_initiation_client_data",
          conversation_config_override: { conversation: { text_only: true } },
          dynamic_variables: context,
        }),
      ),
    );
    ws.addEventListener("error", () => reject(new Error("ElevenLabs socket error")));
    ws.addEventListener("message", (ev) => {
      const data = JSON.parse(String(ev.data));
      if (data.type === "conversation_initiation_metadata") resolve();
      if (data.type === "ping") {
        ws.send(JSON.stringify({ type: "pong", event_id: data.ping_event.event_id }));
      }
      if (data.type === "agent_response" && session.pending) {
        session.pending(data.agent_response_event.agent_response);
        session.pending = null;
      }
    });
  });
  ws.addEventListener("close", () => sessions.delete(key));

  sessions.set(key, session);
  await session.ready;
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
    session.pending = (reply) => {
      clearTimeout(timer);
      resolve(reply);
    };
    session.ws.send(JSON.stringify({ type: "user_message", text }));
  });
}

/** Close a person's session so the next message reopens it with fresh context. */
export function resetAgent(key: string) {
  sessions.get(key)?.ws.close();
  sessions.delete(key);
}
