// The building the agent knows about. Single source of truth for routes:
// the alert text, the agent's context and (later) the dashboard all read this.
//
// ⚠ SAMPLE DATA: placeholder layout, not verified against the real building.
// Replace with the real James West Alumni Center layout after walking the venue.

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
    { id: "west-main", label: "West main entrance", floor: 1, location: "west side, facing the lawn", accessible: true },
    { id: "east-side", label: "East side door", floor: 1, location: "east hallway, by the kitchen", accessible: true },
    { id: "north-patio", label: "North patio doors", floor: 1, location: "north side of the main hall", accessible: true },
  ],
  stairwells: [
    { id: "stair-a", label: "Stairwell A", floors: [1, 2], location: "west end, next to the main entrance" },
    { id: "stair-b", label: "Stairwell B", floors: [1, 2], location: "east end, by the restrooms" },
  ],
  elevators: ["Main elevator in the lobby. Do not use it during a fire."],
  assemblyPoint: "North lawn, across from Pauley Pavilion",
  refugeAreas: ["Floor 2 landing of Stairwell A"],
  routes: [
    { floor: 1, steps: ["Leave through the west main entrance", "Walk to the north lawn"], exitId: "west-main", backupExitId: "north-patio" },
    { floor: 2, steps: ["Take Stairwell B down to floor 1", "Exit through the east side door", "Walk to the north lawn"], exitId: "east-side", backupExitId: "west-main" },
  ],
  notes: ["The main hall can hold large events; expect crowds at the west entrance."],
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
    `Building: ${venue.name}${venue.verified ? "" : " (sample layout, unverified)"}`,
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
