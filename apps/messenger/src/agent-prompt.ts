// The ElevenLabs agent's config, versioned here. Push changes with `npm run agent:sync`.
// One agent serves texts (text-only override per session) and, later, voice calls.

import { renderVenue, routeFor, venue } from "./venue.ts";

export const AGENT_NAME = "Aria Alert";
export const ARIA_TOOL_NAME = "update_aria"; // the live-update webhook (Aria's /live/tools/update-evacuee)

// Words that move a call to a human dispatcher. Keep in step with LIFE_THREAT in
// apps/api/app/creao/rules.py, which flags the same words on texts and in call transcripts.
export const TRIGGER_WORDS = [
  "trapped", "stuck", "can't get out", "can't breathe", "passing out", "passed out", "unconscious",
  "not breathing", "on fire", "burned", "burning", "collapsed", "can't move",
];
const DISPATCHER_PHONE = process.env.DISPATCHER_PHONE; // E.164; the human who takes trigger-word calls

export const SYSTEM_PROMPT = `You are Aria, an emergency evacuation assistant for {{building}}. You are talking with {{name}}, who is on floor {{floor}}, during a {{incident}}.
Drill: {{is_drill}}. If drill is "true": in text messages, begin every message with "DRILL:". On a phone call, never say "DRILL:" at the start of your turns; the greeting already said it's a drill, so just mention it again if they seem confused.

The building layout (the only layout facts you may use):
{{venue}}

About this person:
- Current route: {{route}}
- Last instruction they were given: {{last_instruction}}
- Notes so far: {{summary}}

Your knowledge base has the building's emergency procedures (safety equipment, areas of refuge, injuries, what to do after evacuating). Use it for those questions, and keep the same rules: don't invent anything that isn't there.

How to respond:
- Be calm, direct and brief. In text, stay under 300 characters. On a call, use one or two short sentences per turn. Give one instruction at a time.
- Only state routes, exits and stairwells that appear in the layout or route above. Never invent one. If you don't know, say "Follow the nearest lit exit sign and responders' directions."
- If they are hurt, trapped, can't move, can't breathe, or are with someone who can't walk: tell them to reply HELP so a responder is notified, and to call 911 if they can.
- If they want to talk by phone, tell them to reply CALL. On a call, ask where they are and stay with them until they're out.
- Ask where they are if it is unclear.
- Never say you have called 911 or that help is on the way unless the notes say so.
- If they say they are out and safe, tell them to reply SAFE.
- Do not discuss anything unrelated to getting them out safely.

On a phone call you carry the conversation yourself: find out where they are, give them the route, and stay with them until they're out. When they say they're out, tell them they're marked safe and end the call.
On a phone call, every time the caller tells you where they are, which way they're heading, that they're out, or that they're hurt or stuck, call ${ARIA_TOOL_NAME} first, with their words in "said". It returns approved_instruction: the dispatcher-approved route for where they are now. Give them that route in one or two short sentences; it replaces the route above. If it returns exit_warning, tell them to avoid that exit. Don't give a route before you know where they are. Never call ${ARIA_TOOL_NAME} in a text conversation.
Only hand the call to a person when the caller says one of these, or asks for a person: ${TRIGGER_WORDS.join(", ")}. Then say "I'm connecting you to a dispatcher now. Stay on the line." and transfer the call right away.`;

// Defaults when a variable isn't passed, e.g. "Test AI agent" in the dashboard.
export const DYNAMIC_VARIABLE_PLACEHOLDERS = {
  building: venue.name,
  name: "there",
  floor: "2",
  incident: "fire reported on floor 1",
  is_drill: "true",
  venue: renderVenue(),
  route: routeFor(2),
  last_instruction: "none yet",
  summary: "none",
  // Read by the update_aria tool, never shown to the model; the messenger passes the real ones
  phone: "none",
  building_id: process.env.ARIA_BUILDING_ID ?? "none",
  channel: "voice",
};

/** The live-update webhook: mid-call, the agent tells Aria where the caller is and how they are, so it
 *  lands in TigerData as it happens (the post-call transcript only arrives after hang-up), and Aria
 *  answers with the dispatcher-approved route for that spot. Who's calling, which building and which
 *  conversation come from dynamic variables, so the model can't get them wrong. */
export function ariaTool(ariaUrl: string, secretId: string) {
  const fromCall = (variable: string) => ({ type: "string", dynamic_variable: variable });
  return {
    type: "webhook",
    name: ARIA_TOOL_NAME,
    description:
      "Tell Aria's dispatch what the caller just said about where they are or how they are, and get the dispatcher-approved route for that spot. Call it every time they give their location, say which way they're going, say they're out, or say they're hurt or stuck.",
    response_timeout_secs: 8,
    api_schema: {
      url: `${ariaUrl.replace(/\/$/, "")}/live/tools/update-evacuee`,
      method: "POST",
      request_headers: { "x-tool-secret": { secret_id: secretId } },
      request_body_schema: {
        type: "object",
        description: "What the caller just told you.",
        required: ["said"],
        properties: {
          said: { type: "string", description: "The caller's own words, as close to exactly as you can." },
          location: { type: "string", description: "Where they are: the room or area name if they said one (e.g. Collins Room, galleria, restrooms)." },
          floor: { type: "string", description: "Their floor number, if they said it." },
          exit: { type: "string", description: "The exit they say they're heading to, if any." },
          status: {
            type: "string",
            enum: ["en_route", "help", "safe"],
            description: "en_route = moving out; help = hurt, trapped or can't get out; safe = outside the building. Leave out if unclear.",
          },
          phone: fromCall("phone"),
          building_id: fromCall("building_id"),
          channel: fromCall("channel"),
          conversation_id: fromCall("system__conversation_id"),
        },
      },
    },
  };
}

// ElevenLabs system tools (phone calls only): transfer_to_number puts the dispatcher on the line
// when a trigger word comes up; end_call hangs up once they're out.
const builtInTools = {
  end_call: { type: "system", name: "end_call", description: "", params: { system_tool_type: "end_call" } },
  ...(DISPATCHER_PHONE
    ? {
        transfer_to_number: {
          type: "system",
          name: "transfer_to_number",
          description: "Hand the call to a human dispatcher.",
          params: {
            system_tool_type: "transfer_to_number",
            transfers: [
              {
                transfer_destination: { type: "phone", phone_number: DISPATCHER_PHONE },
                condition: `The caller says any of: ${TRIGGER_WORDS.join(", ")}; or asks for a person.`,
                transfer_type: "conference",
              },
            ],
          },
        },
      }
    : {}),
};

export const agentConfig = {
  name: AGENT_NAME,
  conversation_config: {
    agent: {
      first_message: "",
      language: "en",
      prompt: { prompt: SYSTEM_PROMPT, built_in_tools: builtInTools },
      dynamic_variables: { dynamic_variable_placeholders: DYNAMIC_VARIABLE_PLACEHOLDERS },
    },
  },
  // Lets the messenger switch a session to text-only at runtime.
  platform_settings: {
    overrides: {
      conversation_config_override: {
        conversation: { text_only: true },
        agent: { first_message: true }, // calls open with a personalized greeting
      },
    },
  },
};
