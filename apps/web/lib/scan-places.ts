// "Find a place" over the venue scan: a port of `search` in packages/engine/engine/places.py,
// run on public/fire/places.json (`uv run python -m engine.places --index --out ...`). The file
// carries the engine's words and weights (`vocab`) and each place's search keys, so the rules
// match: an exact id/alias wins before floor words are read, floor words filter by storey,
// compass words are dropped, and every place tied for best is returned. Shared test cases:
// packages/engine/tests/places_queries.json.

export type PlacePoint = [x: number, elevation: number, z: number];

export type Place = {
  id: string;
  ref: string;
  type: string;
  kind: string;
  label: string;
  storey: string;
  /** [x, elevation, z] in the venue frame (m); on the scan, y = floor_y + elevation. */
  point: PlacePoint;
  space: string;
  /** On the scanned ground floor; otherwise the point comes from the plan only. */
  scanned: boolean;
  approx_m: number;
  polygon?: [number, number][];
  note?: string | null;
  exact: string[];
  names: string[];
  terms: string[];
};

type PlaceVocab = {
  filler: string[];
  compass: string[];
  storeys: Record<string, string[]>;
  intents: Record<string, { words: string[]; types: Record<string, number> }>;
  weights: Record<
    "exact" | "name" | "terms" | "fuzzy" | "fuzzy_min" | "room_number" | "tie_margin",
    number
  >;
};

export type PlaceIndex = {
  venue: string | null;
  frame: { floor_y?: number };
  vocab: PlaceVocab;
  places: Place[];
};

export type PlaceMatch = Place & { score: number };

export type PlaceResult = {
  query: string;
  storey: string | null;
  /** More than one feature (venue.json id) among the matches. */
  ambiguous: boolean;
  matches: PlaceMatch[];
  note: string | null;
};

export const SPACE_TYPES = ["space", "restroom", "elevator", "outdoor"];
const EXACT_SCORE = 200;
const ROOM_NUMBER = /^\d{3}[a-z]{0,2}$/;

const VENUE_BUILDING_ID = process.env.NEXT_PUBLIC_VENUE_BUILDING_ID;

/** The venue's place index, or null for any other building. */
export async function loadPlaceIndex(buildingId: string): Promise<PlaceIndex | null> {
  if (buildingId !== "venue" && buildingId !== VENUE_BUILDING_ID) return null;
  try {
    const res = await fetch("/fire/places.json");
    if (!res.ok) return null;
    return (await res.json()) as PlaceIndex;
  } catch {
    return null;
  }
}

/** Venue-frame point -> scan scene, the same transform as the fire layer. */
export function placeToWorld(
  [x, elevation, z]: PlacePoint,
  center: { x: number; y: number; z: number },
  floorY: number,
): { x: number; y: number; z: number } {
  return { x: x - center.x, y: floorY + elevation - center.y, z: z - center.z };
}

/** How sure a pin is: on the scanned floor, or from the plan (and how far off it may be). */
export function placeTag(place: Place, onScan: boolean): string {
  if (onScan) return "SCAN";
  return `${place.scanned ? "OFF SCAN" : "PLAN"} ±${place.approx_m} M`;
}

function words(s: string): string[] {
  return s.split(" ").filter(Boolean);
}

function norm(s: string): string {
  return words(
    s
      .toLowerCase()
      .replace(/['’]/g, "")
      .replace(/[^a-z0-9]+/g, " "),
  ).join(" ");
}

function stem(t: string): string {
  return t.length > 3 && t.endsWith("s") && !t.endsWith("ss") ? t.slice(0, -1) : t;
}

/** difflib.SequenceMatcher(None, a, b).ratio() (no junk heuristic; place names are < 200 chars). */
function ratio(a: string, b: string): number {
  const total = a.length + b.length;
  return total ? (2 * matchingChars(a, b, 0, a.length, 0, b.length)) / total : 1;
}

/** Characters in difflib's matching blocks: the longest common run, then recurse either side. */
function matchingChars(
  a: string,
  b: string,
  alo: number,
  ahi: number,
  blo: number,
  bhi: number,
): number {
  let besti = alo;
  let bestj = blo;
  let size = 0;
  let prev = new Array<number>(bhi - blo + 1).fill(0);
  for (let i = alo; i < ahi; i++) {
    const cur = new Array<number>(bhi - blo + 1).fill(0);
    for (let j = blo; j < bhi; j++) {
      if (a[i] !== b[j]) continue;
      const k = prev[j - blo] + 1;
      cur[j - blo + 1] = k;
      if (k > size) [besti, bestj, size] = [i - k + 1, j - k + 1, k];
    }
    prev = cur;
  }
  if (size === 0) return 0;
  return (
    size +
    matchingChars(a, b, alo, besti, blo, bestj) +
    matchingChars(a, b, besti + size, ahi, bestj + size, bhi)
  );
}

/** Best places for a query; `storey` forces a floor. */
export function searchPlaces(index: PlaceIndex, query: string, storey?: string): PlaceResult {
  const { vocab, places } = index;
  const w = vocab.weights;
  const filler = new Set(vocab.filler);
  const compassWords = new Set(vocab.compass);
  const key = (s: string) =>
    words(norm(s))
      .filter((t) => !filler.has(t))
      .map(stem)
      .join(" ");
  const intentTokens = new Set(
    Object.values(vocab.intents).flatMap((i) => i.words.flatMap((x) => words(key(x)))),
  );
  const order = (a: PlaceMatch, b: PlaceMatch) =>
    b.score - a.score ||
    (a.storey < b.storey ? -1 : a.storey > b.storey ? 1 : 0) ||
    Number(b.scanned) - Number(a.scanned);
  const result = (s: string | null, tier: PlaceMatch[], notes: string[]): PlaceResult => {
    const matches = [...tier].sort(order);
    return {
      query,
      storey: s,
      ambiguous: new Set(matches.map((m) => m.ref)).size > 1,
      matches,
      note: notes.join(" ") || null,
    };
  };
  const onStorey = (p: Place, s: string | null) => s === null || p.storey === s;

  // An id, alias or event name said in full wins outright.
  const whole = key(query);
  const forced = storey ?? null;
  const exact = places.filter((p) => p.exact.includes(whole) && onStorey(p, forced));
  if (whole && exact.length) {
    return result(
      forced,
      exact.map((p) => ({ ...p, score: EXACT_SCORE })),
      [],
    );
  }

  // Floor words filter by storey; compass words are dropped.
  let q = ` ${norm(query)} `;
  let said: string | null = null;
  for (const [sid, storeyWords] of Object.entries(vocab.storeys)) {
    for (const sw of [...storeyWords].sort((x, y) => y.length - x.length)) {
      if (q.includes(` ${sw} `)) {
        said = said ?? sid;
        q = q.split(` ${sw} `).join(" ");
      }
    }
  }
  const compass = words(q).filter((t) => compassWords.has(t));
  let text = key(
    words(q)
      .filter((t) => !compassWords.has(t))
      .join(" "),
  );
  let boosts: Record<string, number> = {};
  for (const intent of Object.values(vocab.intents)) {
    if (!intent.words.some((x) => ` ${text} `.includes(` ${key(x)} `))) continue;
    for (const [t, wgt] of Object.entries(intent.types)) boosts[t] = Math.max(boosts[t] ?? 0, wgt);
  }
  const s = forced ?? said;
  const notes: string[] = [];
  if (compass.length) {
    notes.push(
      `Compass words not used (${compass.join(", ")}): north is unverified and the venue's own 'west' is +x (VENUE.md).`,
    );
  }
  if (!text && s) {
    text = "stair";
    boosts = vocab.intents.stair.types;
    notes.push(`A floor on its own: the stairs on ${s}.`);
  }

  const qt = new Set(words(text));
  const score = (p: Place): number => {
    let sc = p.exact.includes(text) ? w.exact : p.names.includes(text) ? w.name : 0;
    if (qt.size) {
      const terms = new Set(p.terms);
      sc += (w.terms * [...qt].filter((t) => terms.has(t)).length) / qt.size;
      const fuzzy = Math.max(0, ...p.names.map((n) => ratio(text, n)));
      if (fuzzy > w.fuzzy_min) sc += w.fuzzy * fuzzy;
    }
    if (Object.keys(boosts).length) {
      const b = boosts[p.type] ?? 0;
      // The query is only an intent ("stairs"): places of that type only.
      if (b === 0 && [...qt].every((t) => intentTokens.has(t))) return 0;
      sc += b;
    }
    if (ROOM_NUMBER.test(text) && SPACE_TYPES.includes(p.type)) sc += w.room_number;
    return Math.round(sc * 10) / 10;
  };

  const scored = places
    .filter((p) => onStorey(p, s))
    .map((p) => ({ ...p, score: score(p) }))
    .filter((p) => p.score > 0)
    .sort(order);
  if (!scored.length) return result(s, [], [...notes, "No place matches."]);
  const cut = scored[0].score - w.tie_margin;
  return result(
    s,
    scored.filter((p) => p.score >= cut),
    notes,
  );
}
