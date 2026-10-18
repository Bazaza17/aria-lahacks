// The building the agent knows about, as plain layout facts (no routes: the route for a person
// always comes from Aria's live instruction, approved by the dispatcher).
//
// Live: renderVenue() returns the API's building brief (GET /live/buildings/{id}/brief, built from
// the engine's packages/engine/venue.json), refreshed every 5 minutes by followBrief().
// Fallback: the static facts below, copied by hand from packages/engine/venue.json. Keep them in
// step with it. Every fact here is in that file; nothing is invented.

export const BUILDING_ID = process.env.ARIA_BUILDING_ID ?? "547b5ec5-30c5-4f76-8080-012a52e90bd9"; // James West Alumni Center

export type Exit = {
  id: string; // the venue.json opening id
  label: string; // what we tell people
  floor: number;
  location: string;
};

export type Venue = {
  name: string;
  floors: string[];
  exits: Exit[];
  stairs: string[];
  elevators: string;
  assembly: string;
  stepFree: string;
  notes: string[];
};

export const ASSEMBLY = "Outside, away from the building, where staff direct you.";
export const NO_ROUTE =
  "Follow the nearest lit exit sign that is clear of smoke, and staff and responders' directions.";

export const venue: Venue = {
  name: "James West Alumni Center, UCLA",
  floors: [
    "Floor 1 (the Galleria, entrance, Founders' Room and Collins Room are scanned; the rest is from the floor plan): Entrance & Check-in (covered entry plaza), the Galleria (main lobby and its far end with the curved open stair), Restrooms, Founders' Room, Collins Room (Collins Conference Room). Outdoors: Founders' Patio, Collins Patio (food area).",
    "Floor 2 (from the floor plan, not the scan): indoor rooms where the event's Networking and Workshops are (room 210 and rooms 219, 210A and 200), plus an outdoor terrace by the round tower.",
    "Floor 3 (from the floor plan): only the small tower room 330.",
  ],
  exits: [
    { id: "D-110-OUT-1", label: "Main entrance", floor: 1, location: "a pair of doors from the Galleria lobby out to Entrance & Check-in" },
    { id: "D-110-OUT-2", label: "Main entrance (second pair of doors)", floor: 1, location: "beside the first pair, Galleria lobby to Entrance & Check-in" },
    { id: "D-galleria_far_end-OUT-1", label: "Galleria far-end doors", floor: 1, location: "glass doors at the Galleria's far end, by the curved open stair, out to the porch" },
    { id: "D-galleria_far_end-OUT-2", label: "Galleria far-end doors (second pair)", floor: 1, location: "beside the first pair, out to the porch" },
    { id: "D-120-OUT-1", label: "Founders' Room patio door", floor: 1, location: "Founders' Room corner door by the covered arcade, out to Founders' Patio" },
    { id: "D-120-OUT-2", label: "Founders' Room second patio door", floor: 1, location: "Founders' Room, out to Founders' Patio" },
    { id: "D-140-OUT", label: "Collins Room patio doors (restroom end)", floor: 1, location: "double door from the Collins Room's restroom end out to Collins Patio" },
    { id: "D-150-OUT-1", label: "Collins Room patio doors (food-area end)", floor: 1, location: "double door from the Collins Room out to Collins Patio, food area" },
    { id: "D-150-OUT-2", label: "Collins Room corner door", floor: 1, location: "single door in the Collins Room's far corner, out to Collins Patio" },
    { id: "D-170-OUT", label: "Room 170 patio doors", floor: 1, location: "room 170's double door out to the back patio (not an event area)" },
    { id: "D-192-OUT", label: "Room 192 patio door", floor: 1, location: "room 192's corner door out to the back patio" },
    { id: "D-190-OUT", label: "Room 190 door", floor: 1, location: "room 190's door into the yard beside the lobby (may be indoors; unconfirmed)" },
    { id: "D-100-OUT", label: "Office suite 100 door", floor: 1, location: "the door in office suite 100's far wall to outside" },
    { id: "ST-W", label: "Outside stairs (\"Stairs to 2nd floor\")", floor: 2, location: "the open-air stair from the 2nd-floor terrace down to the fenced area beside Collins Patio; reached from room 210 through its doors onto the terrace" },
  ],
  stairs: [
    "Outside stairs (\"Stairs to 2nd floor\"): open-air, from the 2nd-floor terrace down to the fenced area beside Collins Patio. The 2nd floor's only way down that does not pass through the Galleria.",
    "Curved open stair in the Galleria's far end: indoors, between floor 1 and the 2nd-floor landing by room 210. Open to the Galleria, so smoke there reaches it.",
    "Indoor stair by the office corridor: from room 200 on floor 2 down to the corridor that opens into the Galleria lobby (its door into the lobby may be a locked staff door).",
  ],
  elevators: "There is an elevator, but elevators are not used in an evacuation.",
  assembly: ASSEMBLY,
  stepFree: "No exit is confirmed step-free. Anyone who can't use stairs or steps should reply HELP (or call 911) and say exactly where they are.",
  notes: [
    "Floors 2 and 3 come from the floor plan, not the scan.",
    "Which way is north is not verified; never give compass directions.",
    "Routes are not fixed: the route for a person comes from Aria's live instruction. If there isn't one, say: " + NO_ROUTE,
  ],
};

/** The generic route when Aria's live layer hasn't given one (no fixed per-floor routes). */
export function routeFor(_floor: number | undefined): string {
  return NO_ROUTE;
}

function staticVenue(): string {
  return [
    `Building: ${venue.name}`,
    ...venue.floors,
    "Exterior exits:",
    ...venue.exits.map((e) => `- ${e.label} [${e.id}] (floor ${e.floor}): ${e.location}`),
    "Stairs:",
    ...venue.stairs.map((s) => `- ${s}`),
    `Elevators: ${venue.elevators}`,
    `Assembly: ${venue.assembly}`,
    `Step-free: ${venue.stepFree}`,
    ...venue.notes.map((n) => `Note: ${n}`),
  ].join("\n");
}

// ---------------------------------------------------------------- the API's building brief

const BRIEF_EVERY_MS = 5 * 60_000;
const BRIEF_TIMEOUT_MS = 8_000;

let brief: { text: string; updatedAt?: string } | null = null;

/** Fetch the building brief from Aria's API. Keeps the last good one if the API is down. */
export async function refreshBrief(): Promise<boolean> {
  const { ARIA_LIVE_URL, ARIA_TOOL_SECRET } = process.env;
  if (!ARIA_LIVE_URL) return false;
  const url = `${ARIA_LIVE_URL.replace(/\/$/, "")}/live/buildings/${encodeURIComponent(BUILDING_ID)}/brief`;
  try {
    const res = await fetch(url, {
      headers: ARIA_TOOL_SECRET ? { "x-tool-secret": ARIA_TOOL_SECRET } : {},
      signal: AbortSignal.timeout(BRIEF_TIMEOUT_MS),
    });
    if (!res.ok) {
      console.error(`[venue] brief -> ${res.status}; ${brief ? "keeping the last one" : "using the static venue"}`);
      return false;
    }
    const body = (await res.json()) as { text?: unknown; updated_at?: unknown };
    if (typeof body.text !== "string" || !body.text.trim()) {
      console.error("[venue] brief had no text; ignoring it");
      return false;
    }
    brief = { text: body.text.trim(), ...(typeof body.updated_at === "string" ? { updatedAt: body.updated_at } : {}) };
    return true;
  } catch (err) {
    console.error("[venue] brief failed:", err instanceof Error ? err.message : err);
    return false;
  }
}

/** Load the brief now and every 5 minutes (only when ARIA_LIVE_URL is set). */
export function followBrief() {
  if (!process.env.ARIA_LIVE_URL) return;
  void refreshBrief().then((ok) => console.log(`[venue] ${ok ? "using the API's building brief" : "using the static venue for now"}`));
  setInterval(() => void refreshBrief(), BRIEF_EVERY_MS).unref();
}

/** The layout as plain text for the agent's {{venue}} variable: the API's brief, or the static facts. */
export function renderVenue(): string {
  if (brief) {
    return [
      brief.text,
      `Assembly: ${ASSEMBLY}`,
      "Elevators are not used in an evacuation.",
      "Routes are not fixed: the route for a person comes from Aria's live instruction.",
    ].join("\n");
  }
  return staticVenue();
}
