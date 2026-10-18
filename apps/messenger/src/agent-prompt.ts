// The ElevenLabs agent's config, versioned here. Push changes with `npm run agent:sync`.
// One agent serves texts (text-only override per session) and, later, voice calls.

import { renderVenue, NO_ROUTE, venue, BUILDING_ID } from "./venue.ts";

export const AGENT_NAME = "Aria Alert";
export const ARIA_TOOL_NAME = "update_aria"; // the live-update webhook (Aria's /live/tools/update-evacuee)
export const INCIDENT_TOOL_NAME = "log_incident_details"; // Aria's /live/tools/log-incident-details

// Words that move a call to a human dispatcher. Keep in step with LIFE_THREAT in
// apps/api/app/creao/rules.py, which flags the same words on texts and in call transcripts.
export const TRIGGER_WORDS = [
  "trapped", "stuck", "can't get out", "can't breathe", "passing out", "passed out", "unconscious",
  "not breathing", "on fire", "burned", "burning", "collapsed", "can't move",
];
const DISPATCHER_PHONE = process.env.DISPATCHER_PHONE; // E.164; the human who takes trigger-word calls

export const SYSTEM_PROMPT = `You are Aria, an emergency evacuation assistant for {{building}}. You are talking with {{name}}. Their floor: {{floor}}. What's happening: {{incident}}.
Drill: {{is_drill}}. If drill is "true": in text messages, begin every message with "DRILL:". On a phone call, never say "DRILL:" at the start of your turns; the greeting already said it's a drill, so just mention it again if they seem confused. If drill is "false", this is real: never call it a drill. If drill is "unknown", don't say whether it is a drill.

The building layout (the only layout facts you may use):
{{venue}}

About this person:
- Current route: {{route}}
- Last instruction they were given: {{last_instruction}}
- Notes so far: {{summary}}

Your knowledge base has general fire-safety guidance (smoke, hot doors, people who can't use stairs, injuries, what to do after getting out). It names no places in the building and does not say where equipment is. Use it for those questions, and keep the same rules: don't invent anything that isn't there. There is no area of refuge, evacuation chair or step-free exit you may mention, elevators are not used in an evacuation, and the meeting place is outside, away from the building, where staff direct them.

How to respond:
- Be calm, direct and brief. In text, stay under 300 characters. On a call, use one or two short sentences per turn. Give one instruction at a time.
- Only state routes, exits and stairs that appear in the layout or route above. Never invent one, and never give compass directions. If you don't know, say "${NO_ROUTE}"
- If they are hurt, trapped, can't move, can't breathe, or are with someone who can't walk: tell them to reply HELP so a responder is notified, and to call 911 if they can.
- If they want to talk by phone, tell them to reply CALL. On a call, ask where they are and stay with them until they're out.
- Ask where they are if it is unclear.
- Never say you have called 911 or that help is on the way unless the notes say so.
- If they say they are out and safe, tell them to reply SAFE.
- Do not discuss anything unrelated to getting them out safely.

On a phone call you carry the conversation yourself: find out where they are, give them the route, and stay with them until they're out. When they say they're out, tell them they're marked safe and end the call.
On a phone call, every time the caller tells you where they are, which way they're heading, that they're out, or that they're hurt or stuck, call ${ARIA_TOOL_NAME} first, with their words in "said". It returns approved_instruction: the dispatcher-approved route for where they are now. Give them that route in one or two short sentences; it replaces the route above. If it returns exit_warning, tell them to avoid that exit. Don't give a route before you know where they are. Never call ${ARIA_TOOL_NAME} in a text conversation.
Call direction: {{call_direction}}. Only if it is "inbound" (they called the number), also call ${INCIDENT_TOOL_NAME} once you know what's happening and where, and again when you learn something new (injuries, hazards, people with them). If it is "outbound" (Aria called them) or "none" (a text conversation), never call ${INCIDENT_TOOL_NAME}.
Only hand the call to a person when the caller says one of these, or asks for a person: ${TRIGGER_WORDS.join(", ")}. Then say "I'm connecting you to a dispatcher now. Stay on the line." and transfer the call right away.`;

// Defaults when a variable isn't passed: calls people make to the number, and "Test AI agent" in
// the dashboard. Neutral on purpose: no made-up floor, fire or drill.
export const DYNAMIC_VARIABLE_PLACEHOLDERS = {
  building: venue.name,
  name: "there",
  floor: "unknown",
  incident: "unknown; ask them what is happening and where they are",
  is_drill: "unknown",
  venue: renderVenue(),
  route: `No route yet: ask where they are. Until then: ${NO_ROUTE}`,
  last_instruction: "none yet",
  summary: "none",
  // Read by the tools, never shown to the model; the messenger passes the real ones. Empty on a call
  // someone made to the number: then Aria uses the caller id (system__caller_id) instead.
  phone: "",
  building_id: BUILDING_ID,
  channel: "voice",
  // Only calls people make to the number fall back to this; Aria's own calls pass "outbound", texts "none".
  call_direction: "inbound",
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
          // the API uses this when phone is empty (calls people make to the number)
          caller_id: fromCall("system__caller_id"),
          building_id: fromCall("building_id"),
          channel: fromCall("channel"),
          conversation_id: fromCall("system__conversation_id"),
        },
      },
    },
  };
}

/** The incident-details webhook, for calls people make to the number: what happened, where, who's
 *  hurt. The API pins it on the incident for that caller (by conversation and caller id). */
export function incidentTool(ariaUrl: string, secretId: string) {
  const fromCall = (variable: string) => ({ type: "string", dynamic_variable: variable });
  const said = (description: string) => ({ type: "string", description });
  return {
    type: "webhook",
    name: INCIDENT_TOOL_NAME,
    description:
      "On a call someone made to the number: log what is happening, where, and who is hurt, so Aria's dispatch sees it. Call it once you know what happened and where, and again when you learn more.",
    response_timeout_secs: 8,
    api_schema: {
      url: `${ariaUrl.replace(/\/$/, "")}/live/tools/log-incident-details`,
      method: "POST",
      request_headers: { "x-tool-secret": { secret_id: secretId } },
      request_body_schema: {
        type: "object",
        description: "What the caller has told you so far.",
        required: ["description"],
        properties: {
          description: said("One sentence: what is happening, in the caller's words."),
          category: said("fire, smoke, medical, trapped, or other."),
          location: said("Where it is or where they are: the room or area name if they said one."),
          floor: said("The floor number, if they said it."),
          injuries: said("Who is hurt and how, if anyone."),
          hazards: said("Fire, smoke, blocked doors or other dangers they mention, and where."),
          people_involved: said("How many people are with them, and anyone who can't move."),
          urgency: { type: "string", enum: ["critical", "high", "medium"], description: "critical = someone trapped, unconscious or not breathing; high = fire or smoke near people, or injuries; medium = otherwise." },
          caller_id: fromCall("system__caller_id"),
          called_number: fromCall("system__called_number"),
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
