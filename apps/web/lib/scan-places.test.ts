import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import { searchPlaces, type PlaceIndex } from "./scan-places";

// The same cases engine/places.py is tested against, on the index the viewer loads.
type Case = {
  query: string;
  storey?: string;
  ambiguous: boolean;
  first: string | null;
  refs: string[];
  scanned?: boolean;
  note?: string;
};

const readJson = (rel: string) => JSON.parse(readFileSync(new URL(rel, import.meta.url), "utf8"));
const index = readJson("../public/fire/places.json") as PlaceIndex;
const { cases } = readJson("../../../packages/engine/tests/places_queries.json") as {
  cases: Case[];
};

describe("scan-places search (shared cases with engine.places)", () => {
  for (const c of cases) {
    it(c.query, () => {
      const res = searchPlaces(index, c.query);
      assert.equal(res.matches[0]?.id ?? null, c.first);
      assert.deepEqual([...new Set(res.matches.map((m) => m.ref))].sort(), [...c.refs].sort());
      assert.equal(res.ambiguous, c.ambiguous);
      if (c.storey) assert.equal(res.storey, c.storey);
      if (c.scanned !== undefined) assert.equal(res.matches[0]?.scanned, c.scanned);
      if (c.note) assert.ok(res.note?.includes(c.note), `note: ${res.note}`);
    });
  }
});
