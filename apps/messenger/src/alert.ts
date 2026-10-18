import { sendText } from "./photon.ts";
import { resetAgent, type AgentContext } from "./eleven.ts";
import { venue, routeFor, renderVenue } from "./venue.ts";

export type Contact = { handle: string; spaceId: string; agentId: string };

// Who can be reached. A free shared line can't send the first message, so a
// person must text the line once before we can alert them. Moves to Supabase later.
export const contacts = new Map<string, Contact>();

export type AlertInput = {
  phone: string; // E.164, e.g. +14155551234
  name?: string;
  floor?: number; // the person's floor; picks their route from venue.ts
  originFloor?: number; // where the fire is
  route?: string; // override the venue route
  drill?: boolean;
};

type SentAlert = { name: string; floor?: number; originFloor: number; route: string; drill: boolean; text: string };

export function buildAlertText(a: Omit<SentAlert, "text">) {
  const prefix = a.drill ? "DRILL: " : "";
  return `${prefix}Fire reported on floor ${a.originFloor} at ${venue.name}. ${a.route} Reply SAFE, HELP, or CALL. If you're in danger, call 911.`;
}

// The last alert each person got; it's the agent's context for their replies and calls.
const lastAlert = new Map<string, SentAlert>();

/** Everything the agent is told about this person and the building. */
export function agentContext(phone: string): AgentContext {
  const a = lastAlert.get(phone);
  return {
    building: venue.name,
    venue: renderVenue(),
    name: a?.name ?? "there",
    floor: a?.floor === undefined ? "unknown" : String(a.floor),
    incident: a ? `fire reported on floor ${a.originFloor}` : "no active incident",
    is_drill: String(a?.drill ?? true),
    route: a?.route ?? routeFor(undefined),
    last_instruction: a?.text ?? "none yet",
    summary: a ? `Alerted by text about a fire on floor ${a.originFloor}.` : "No alert sent yet.",
  };
}

export class NotRegisteredError extends Error {}

export async function sendAlert(input: AlertInput) {
  const contact = contacts.get(input.phone);
  if (!contact) {
    throw new NotRegisteredError(`${input.phone} hasn't texted the line yet, so Photon can't message them first`);
  }
  const alert = {
    name: input.name ?? "there",
    floor: input.floor,
    originFloor: input.originFloor ?? 1,
    route: input.route ?? routeFor(input.floor),
    drill: input.drill ?? true,
  };
  const text = buildAlertText(alert);
  const sent = await sendText(contact, text);
  lastAlert.set(input.phone, { ...alert, text });
  resetAgent(input.phone); // next reply starts a fresh agent session with this alert as context
  return { to: input.phone, text, status: sent.status };
}
