"use client";

import { useState, type FormEvent } from "react";

import { placeTag, type PlaceResult } from "@/lib/scan-places";

import type { PlacePin } from "./scanSceneLayers";

export type PlaceFound = { result: PlaceResult; pins: PlacePin[] };

type Props = {
  found: PlaceFound | null;
  onSearch: (query: string) => void;
  onClear: () => void;
};

/** "Find a place": a query box over the scan and the places it pinned. */
export function PlaceSearch({ found, onSearch, onClear }: Props) {
  const [query, setQuery] = useState("");

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (query.trim()) onSearch(query.trim());
  };
  const handleClear = () => {
    setQuery("");
    onClear();
  };

  const result = found?.result;
  const count = result?.matches.length ?? 0;
  const hidden = count - (found?.pins.length ?? 0);
  const summary =
    `${count} MATCH${count === 1 ? "" : "ES"}` +
    (result?.ambiguous ? " · AMBIGUOUS" : "") +
    (result?.storey ? ` · ${result.storey}` : "");

  return (
    <div className="w-[260px] rounded-md border border-white/[0.08] bg-black/80 p-1 font-mono text-[9px] tracking-[0.12em] backdrop-blur">
      <form role="search" onSubmit={handleSubmit} className="flex items-center gap-1">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="FIND A PLACE · MAIN ENTRANCE"
          aria-label="Find a place in the venue"
          className="min-w-0 flex-1 rounded-sm bg-white/[0.04] px-2 py-1 text-white/85 outline-none placeholder:text-white/30 focus:bg-white/[0.08]"
        />
        <button
          type="submit"
          className="rounded-sm px-2 py-1 text-[#ff6b00] transition-colors hover:bg-[#ff6b00]/20"
        >
          FIND
        </button>
        {found && (
          <button
            type="button"
            onClick={handleClear}
            aria-label="Clear place pins"
            className="rounded-sm px-1.5 py-1 text-white/45 transition-colors hover:bg-white/[0.06] hover:text-white/80"
          >
            ✕
          </button>
        )}
      </form>

      {found && result && (
        <div className="space-y-0.5 px-2 pb-1 pt-1.5 leading-relaxed">
          {count > 0 && <p className="text-[#ffb27a]">{summary}</p>}
          {found.pins.map((pin) => (
            <div key={pin.match.id} className="flex justify-between gap-2">
              <span className="truncate text-white/85" title={pin.match.label}>
                {pin.match.label}
              </span>
              <span className={pin.onScan ? "shrink-0 text-fuchsia-300" : "shrink-0 text-white/40"}>
                {placeTag(pin.match, pin.onScan)}
              </span>
            </div>
          ))}
          {hidden > 0 && <p className="text-white/40">+{hidden} MORE NOT PINNED</p>}
          {result.note && <p className="tracking-normal text-white/40">{result.note}</p>}
        </div>
      )}
    </div>
  );
}
