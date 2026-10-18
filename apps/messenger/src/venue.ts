// The building the agent knows about. Single source of truth for routes:
// the alert text, the agent's context and (later) the dashboard all read this.
//
// ⚠ FROM THE LA HACKS EVENT MAP: real rooms and doors, but not yet walked. Set verified: true
// once the exits, step-free access and the assembly point are confirmed at the venue.

export type Exit = {
  id: string;
  label: string; // what we tell people, e.g. "West main entrance"
  floor: number;
  location: string;
  accessible: boolean; // step-free
};

export type Stairwell = { id: string; label: string; floors: number[]; location: string };

export type FloorRoute = {
  floor: number;
  steps: string[]; // one instruction each, in order
  exitId: string;
  backupExitId?: string;
};

export type Venue = {
  name: string;
  verified: boolean;
  floors: number[];
  exits: Exit[];
  stairwells: Stairwell[];
  elevators: string[];
  assemblyPoint: string;
  refugeAreas: string[]; // where people who can't use stairs wait for responders
  routes: FloorRoute[];
  notes: string[];
};

export const venue: Venue = {
  name: "James West Alumni Center, UCLA",
  verified: false,
  floors: [1, 2],
  exits: [
    { id: "main-entrance", label: "Main entrance (check-in)", floor: 1, location: "the covered entry at Entrance & Check-in, by the lobby", accessible: false },
    { id: "galleria-back-doors", label: "Galleria back doors (south porch)", floor: 1, location: "glass back wall of the Galleria's far end, by the curved stair, out to the south porch", accessible: false },
    { id: "collins-patio-doors", label: "Collins Room patio doors", floor: 1, location: "east wall of the Collins Room, out to Collins Patio (food area)", accessible: false },
    { id: "founders-patio-doors", label: "Founders' Room patio doors", floor: 1, location: "east wall of the Founders' Room, out to Founders' Patio", accessible: false },
    { id: "stairs-down", label: "Stairs down to Collins Patio", floor: 2, location: "top of the outside stairs, at the terrace's edge by the round tower", accessible: false },
  ],
  stairwells: [
    { id: "outside-stairs", label: "Outside stairs", floors: [1, 2], location: "the west exterior stair: from Collins Patio up to the 2nd-floor terrace (the Northeast Patio on the event map)" },
  ],
  elevators: ["None marked on the event map. Do not use any elevator during a fire."],
  assemblyPoint: "North lawn, across from Pauley Pavilion",
  refugeAreas: ["None marked on the event map; confirm with venue staff. Until then, anyone who can't use the stairs stays put and replies HELP."],
  routes: [
    { floor: 1, steps: ["Leave through the main entrance by check-in", "Walk to the north lawn"], exitId: "main-entrance", backupExitId: "collins-patio-doors" },
    { floor: 2, steps: ["Take the outside stairs down to Collins Patio", "Walk away from the building to the north lawn"], exitId: "stairs-down" },
  ],
  notes: [
    "Floor 1 rooms: Entrance & check-in, Galleria (sponsor booths), Restrooms, Collins Room (hacking), Founders' Room (hacking).",
    "People at the back of the Galleria (the far end, by the curved stair) leave by the Galleria back doors to the south porch.",
    "Floor 1 outdoors: Collins Patio (food, hacking) and Founders' Patio (hacking). People there are already outside: send them away from the building to the north lawn.",
    "Floor 2 is the Northeast Patio, an outdoor terrace (networking and workshops). Its way down that avoids the Galleria is the outside stairs to Collins Patio.",
    "Source: LA Hacks event map and the scanned venue model (packages/engine/venue.json). Exits not yet walked, step-free access not confirmed, assembly point not confirmed.",
    "Keep in step with apps/api/app/creao/buildings/james_west.json.",
  ],
};

const exitLabel = (id: string) => venue.exits.find((e) => e.id === id)?.label ?? id;

/** One-line route for a floor, e.g. for the alert text. */
export function routeFor(floor: number | undefined): string {
  const r = venue.routes.find((x) => x.floor === floor);
  const lower = (s: string) => s.charAt(0).toLowerCase() + s.slice(1);
  return r ? `${r.steps.map((s, i) => (i ? lower(s) : s)).join(", then ")}.` :"Follow the nearest lit exit sign and responders' directions.";
}

/** The layout as plain text for the agent's {{venue}} variable. */
export function renderVenue(): string {
  const lines = [
    `Building: ${venue.name}${venue.verified ? "" : " (from the event map, not yet walked)"}`,
    `Floors: ${venue.floors.join(", ")}`,
    "Exits:",
    ...venue.exits.map((e) => `- ${e.label} (floor ${e.floor}, ${e.location}${e.accessible ? ", step-free" : ""})`),
    "Stairwells:",
    ...venue.stairwells.map((s) => `- ${s.label}: floors ${s.floors.join("-")}, ${s.location}`),
    `Elevators: ${venue.elevators.join(" ")}`,
    `Assembly point: ${venue.assemblyPoint}`,
    `Areas of refuge (for people who can't use stairs): ${venue.refugeAreas.join("; ")}`,
    "Default route by floor:",
    ...venue.routes.map(
      (r) =>
        `- Floor ${r.floor}: ${r.steps.join(" → ")}${r.backupExitId ? ` (backup exit: ${exitLabel(r.backupExitId)})` : ""}`,
    ),
    ...venue.notes.map((n) => `Note: ${n}`),
  ];
  return lines.join("\n");
}
