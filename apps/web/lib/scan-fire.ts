// Fire timeline from packages/engine, drawn over the scan. Live: the API runs the engine
// (GET /engine/viewer?start=…, proxied by next.config.ts). Fallback file for the default start,
// the same JSON with each room's geometry_source (cd apps/api):
// uv run python -c "from pathlib import Path; from app.routes import engine as e;
//   Path('../web/public/fire/venue.json').write_bytes(e._run('140', 'fast')['viewer'])"

export type FireRoomState = "clear" | "smoke" | "untenable" | "burning" | "flashover" | "burnt_out";

export type FireFrameRoom = {
  layer_height_m: number;
  /** Smoke below the room's own ceiling (m). */
  smoke_depth_m?: number;
  layer_temp_c: number;
  hrr_kw: number;
  state: FireRoomState;
};

export type FireFrame = {
  t_s: number;
  rooms: Record<string, FireFrameRoom>;
  blocked: string[];
  /** Past the first flashover: the screening zone model's numbers are indicative only. */
  beyond_screening?: boolean;
};

/** Where a room's outline comes from (venue.json geometry_source): only "scan" is scanned. */
export type GeometrySource = "scan" | "plan_traced" | "plan_bbox" | string;

export type FireRoom = {
  name: string;
  floor: number;
  storey?: string | null;
  event_name?: string | null;
  geometry_source?: GeometrySource;
  /** True only for rooms outlined from the LiDAR scan (added by the API's /engine/viewer). */
  scanned?: boolean;
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
  /** The engine's own flag: false = a screening model, not a verified fire engineering study. */
  verified?: boolean;
  /** What was scanned and what comes from the floor plan. */
  provenance?: string;
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

// The venue's Supabase row id, if known; the engine runs for it (and public/fire/venue.json is
// the fallback for the default start).
const VENUE_BUILDING_ID = process.env.NEXT_PUBLIC_VENUE_BUILDING_ID;

export function isVenue(buildingId: string): boolean {
  return buildingId === "venue" || buildingId === VENUE_BUILDING_ID;
}

export function fireTimelineUrl(buildingId: string): string {
  const key = isVenue(buildingId) ? "venue" : buildingId;
  return `/fire/${encodeURIComponent(key)}.json`;
}

/** A space the engine can start a fire in (GET /engine/starts). */
export type FireStart = {
  id: string;
  name: string;
  /** Clean picker label from the plan name ("Room 126", not "126 (could read 128)"). */
  label?: string;
  storey: string | null;
  kind: string | null;
  occupant_load: number;
};

export type FireStarts = { default: string; starts: FireStart[] };

async function fetchJson<T>(url: string): Promise<T | null> {
  try {
    const res = await fetch(url);
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

/** The venue's possible fire starts, from the API's engine (proxied at /engine). */
export async function loadFireStarts(buildingId: string): Promise<FireStarts | null> {
  return isVenue(buildingId) ? fetchJson<FireStarts>("/engine/starts") : null;
}

/** The engine's run for this start, live from the API; for the default start the committed
 *  public/fire file stands in when the API is down. */
export async function loadFireTimeline(
  buildingId: string,
  start?: string,
): Promise<FireTimeline | null> {
  if (isVenue(buildingId)) {
    const query = start ? `?start=${encodeURIComponent(start)}` : "";
    const live = await fetchJson<FireTimeline>(`/engine/viewer${query}`);
    if (live || start) return live;
  }
  return fetchJson<FireTimeline>(fireTimelineUrl(buildingId));
}

/** The responder size-up for one scenario (GET /engine/summary → sizeup). */
export type SizeUpPlace = { t_s: number; space: string | null; name: string };
export type SizeUpExit = { exit: string; label: string; from?: string; lost_s?: number };
/** at_risk counts modelled people (assumed capacities); the UI shows rooms_at_risk. */
export type SizeUpOutcome = { at_risk: number; rooms_at_risk: number; last_out_s: number | null };
export type SizeUpDeparture = {
  t0_s: number;
  occupants: number;
  /** Occupied rooms at this departure. */
  rooms: number;
  plan: SizeUpOutcome;
  self: SizeUpOutcome;
};
export type SizeUpStair = {
  stair: string;
  label: string;
  from: string;
  to: string;
  outdoors: boolean;
};

export type SizeUp = {
  verified: boolean;
  origin: {
    space: string;
    name: string;
    storey: string | null;
    growth: string;
    untenable_s: number | null;
  };
  first_smoke_beyond_origin: SizeUpPlace | null;
  first_untenable_beyond_origin: SizeUpPlace | null;
  first_flashover_s: number | null;
  exits_total: number;
  exits_lost: SizeUpExit[];
  exits_kept: SizeUpExit[];
  departures: SizeUpDeparture[];
  ways_down: Record<string, SizeUpStair[]>;
  check_on_site: { opening: string; between: [string, string]; note: string }[];
  best_moment: {
    t0_s: number;
    plan_rooms_at_risk: number;
    self_rooms_at_risk: number;
    rooms_saved: number;
    rooms: number;
  } | null;
  assumptions: string[];
  provenance: string;
};

/** The engine's size-up for this start (API default when none is picked). */
export async function loadSizeUp(
  buildingId: string,
  start?: string | null,
): Promise<SizeUp | null> {
  if (!isVenue(buildingId)) return null;
  const query = start ? `?start=${encodeURIComponent(start)}` : "";
  const body = await fetchJson<{ sizeup?: SizeUp }>(`/engine/summary${query}`);
  return body?.sizeup ?? null;
}

/** The latest size-up departure at or before t, or the first one. */
export function sizeUpDepartureAt(sizeUp: SizeUp, tS: number): SizeUpDeparture | null {
  let best: SizeUpDeparture | null = sizeUp.departures[0] ?? null;
  for (const d of sizeUp.departures) {
    if (d.t0_s <= tS) best = d;
    else break;
  }
  return best;
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
