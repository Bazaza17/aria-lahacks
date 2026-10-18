// Outbound calls: ElevenLabs places the call through Photon's SIP trunk
// (Photon SMS & Voice number imported into ElevenLabs as a SIP-trunk number).
import type { AgentContext } from "./eleven.ts";
import type { CallState } from "./aria-live.ts";

const { ELEVENLABS_API_KEY, ELEVENLABS_AGENT_ID, ELEVENLABS_PHONE_NUMBER_ID } = process.env;
const BASE = process.env.ELEVENLABS_BASE_URL ?? "https://api.elevenlabs.io"; // a local fake for testing

export class CallingNotConfiguredError extends Error {}

export async function startCall(phone: string, context: AgentContext) {
  if (!ELEVENLABS_PHONE_NUMBER_ID) {
    throw new CallingNotConfiguredError("ELEVENLABS_PHONE_NUMBER_ID is not set; import the Photon voice number into ElevenLabs first");
  }
  const drill = context.is_drill === "true" ? "This is a drill. " : "";
  const res = await fetch(`${BASE}/v1/convai/sip-trunk/outbound-call`, {
    method: "POST",
    headers: { "xi-api-key": ELEVENLABS_API_KEY!, "content-type": "application/json" },
    body: JSON.stringify({
      agent_id: ELEVENLABS_AGENT_ID,
      agent_phone_number_id: ELEVENLABS_PHONE_NUMBER_ID,
      to_number: phone,
      conversation_initiation_client_data: {
        dynamic_variables: { ...context, channel: "voice" },
        conversation_config_override: {
          agent: { first_message: `${drill}Hi ${context.name}, this is Aria, calling about the fire alert. Where are you right now?` },
        },
      },
    }),
  });
  const body = (await res.json()) as { success?: boolean; message?: string; conversation_id?: string | null };
  if (!res.ok || !body.success) throw new Error(`ElevenLabs call failed (${res.status}): ${body.message ?? JSON.stringify(body).slice(0, 300)}`);
  return { conversationId: body.conversation_id ?? null };
}

/** A call's status and transcript so far (forwarded to Aria's live layer when ARIA_LIVE_URL is set). */
export async function getConversation(conversationId: string): Promise<CallState> {
  const res = await fetch(`${BASE}/v1/convai/conversations/${conversationId}`, {
    headers: { "xi-api-key": ELEVENLABS_API_KEY! },
  });
  if (!res.ok) throw new Error(`ElevenLabs conversation ${res.status}`);
  const body = (await res.json()) as {
    status: string;
    transcript?: CallState["transcript"];
    metadata?: { termination_reason?: string; start_time_unix_secs?: number };
  };
  return {
    status: body.status,
    transcript: body.transcript ?? [],
    terminationReason: body.metadata?.termination_reason || undefined,
    startedAt: body.metadata?.start_time_unix_secs,
  };
}
