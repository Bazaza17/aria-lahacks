// Fire timeline from packages/engine, drawn over the scan.
// Produced by: cd packages/engine && python -m engine.fire > ../../apps/web/public/fire/venue.json

export type FireRoomState = "clear" | "smoke" | "untenable" | "burning" | "flashover" | "burnt_out";

export type FireFrameRoom = {
  layer_height_m: number;
  layer_temp_c: number;
  hrr_kw: number;
  state: FireRoomState;
};

export type FireFrame = {
  t_s: number;
  rooms: Record<string, FireFrameRoom>;
  blocked: string[];
};

export type FireRoom = {
  name: string;
  floor: number;
  footprint: { x: [number, number]; z: [number, number] } | null;
  /** Room outline [x, z] in the scan frame; preferred over `footprint` when present. */
  polygon?: [number, number][] | null;
  ceiling_height_m?: number;
  /** Floor height above the scan floor (m); upper storeys are drawn this far up. */
  floor_elevation_m?: number | null;
};

export type FireRouteKind = "plan" | "reactive";

/** One group's walk from its space to safety; points are [x, z, elevation_m]. */
export type FireRoute = {
  space: string;
  occupants: number;
  kind: FireRouteKind;
  status: string;
  at_risk: number;
  exit: string | null;
  points: [number, number, number][];
};

export type FireRouteDeparture = {
  t0_s: number;
  at_risk: { plan: number; reactive: number };
  routes: FireRoute[];
};

export type FireDoor = {
  name: string;
  position: { x: number; z: number } | null;
  connects: [string, string];
};

export type FireEvent = { t_s: number; type: string; id: string; detail: string };

export type FireTimeline = {
  venue: string;
  start_room: string;
  growth: string;
  horizon_s: number;
  rooms: Record<string, FireRoom>;
  doors: Record<string, FireDoor>;
  exits: Array<{ id: string; label: string; door: string; blocked_s: number | null }>;
  events: FireEvent[];
  frames: FireFrame[];
  scan: { floor_y?: number };
  /** Evacuation routes per departure time (Aria engine output); absent in older files. */
  routes?: { departures: FireRouteDeparture[] };
};

// The venue's Supabase row id, if known; it then uses public/fire/venue.json.
const VENUE_BUILDING_ID = process.env.NEXT_PUBLIC_VENUE_BUILDING_ID;

export function fireTimelineUrl(buildingId: string): string {
  const key = buildingId === VENUE_BUILDING_ID ? "venue" : buildingId;
  return `/fire/${encodeURIComponent(key)}.json`;
}

export async function loadFireTimeline(buildingId: string): Promise<FireTimeline | null> {
  try {
    const res = await fetch(fireTimelineUrl(buildingId));
    if (!res.ok) return null;
    return (await res.json()) as FireTimeline;
  } catch {
    return null;
  }
}

export function frameAt(timeline: FireTimeline, tS: number): FireFrame {
  const frames = timeline.frames;
  let best = frames[0];
  for (const f of frames) {
    if (f.t_s <= tS) best = f;
    else break;
  }
  return best;
}

/** The latest departure time at or before t ("if everyone left at ..."), or the first one. */
export function departureAt(timeline: FireTimeline, tS: number): FireRouteDeparture | null {
  const departures = timeline.routes?.departures ?? [];
  let best: FireRouteDeparture | null = departures[0] ?? null;
  for (const d of departures) {
    if (d.t0_s <= tS) best = d;
    else break;
  }
  return best;
}

/** Latest event at or before t, for the status line. */
export function latestEvent(timeline: FireTimeline, tS: number): FireEvent | null {
  let last: FireEvent | null = null;
  for (const e of timeline.events) {
    if (e.t_s <= tS) last = e;
    else break;
  }
  return last;
}

export function formatClock(tS: number): string {
  const m = Math.floor(tS / 60);
  const s = Math.floor(tS % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}
