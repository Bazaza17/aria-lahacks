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

/** "↳ Find a place": opens a query line under the headline and lists the places it pinned. */
export function PlaceSearch({ found, onSearch, onClear }: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (query.trim()) onSearch(query.trim());
  };
  const handleClose = () => {
    setQuery("");
    setOpen(false);
    onClear();
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="caps pointer-events-auto self-start text-[11px] text-quiet transition-colors hover:text-fg"
      >
        ↳ Find a place
      </button>
    );
  }

  const result = found?.result;
  const count = result?.matches.length ?? 0;
  const hidden = count - (found?.pins.length ?? 0);
  const summary =
    `${count} match${count === 1 ? "" : "es"}` +
    (result?.ambiguous ? " · ambiguous" : "") +
    (result?.storey ? ` · ${result.storey}` : "");

  return (
    <div className="pointer-events-auto -mx-2 w-[316px] bg-scan/80 px-2 py-1.5">
      <form
        role="search"
        onSubmit={handleSubmit}
        className="flex items-center gap-3 border-b border-control"
      >
        <span className="caps shrink-0 text-[11px] text-quiet">↳</span>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") handleClose();
          }}
          placeholder="Find a place · main entrance"
          aria-label="Find a place in the venue"
          autoFocus
          className="caps min-w-0 flex-1 bg-transparent py-1.5 text-[11px] text-fg outline-none placeholder:text-faint"
        />
        <button
          type="submit"
          className="caps shrink-0 text-[11px] text-soft transition-colors hover:text-fg"
        >
          Find
        </button>
        <button
          type="button"
          onClick={handleClose}
          aria-label="Clear place pins"
          className="shrink-0 text-[11px] text-dim transition-colors hover:text-fg"
        >
          ✕
        </button>
      </form>

      {found && result && (
        <div className="caps flex flex-col gap-1 pt-2 text-[10px] leading-relaxed">
          {count > 0 && <p className="text-soft">{summary}</p>}
          {found.pins.map((pin) => (
            <div key={pin.match.id} className="flex justify-between gap-3">
              <span className="truncate text-fg" title={pin.match.label}>
                {pin.match.label}
              </span>
              <span className={pin.onScan ? "shrink-0 text-soft" : "shrink-0 text-dim"}>
                {placeTag(pin.match, pin.onScan)}
              </span>
            </div>
          ))}
          {hidden > 0 && <p className="text-dim">+{hidden} more not pinned</p>}
          {result.note && <p className="normal-case text-[11px] text-dim">{result.note}</p>}
        </div>
      )}
    </div>
  );
}
