"use client";

import type { HazardFilter } from "@/lib/scan-hazard-pins";

const FILTERS: { id: HazardFilter; label: string }[] = [
  { id: "all", label: "ALL" },
  { id: "wind", label: "WIND" },
  { id: "surge", label: "SURGE" },
  { id: "flood", label: "FLOOD" },
];

export function HazardPinFilter({
  filter,
  onFilterChange,
  counts,
  indexing,
}: {
  filter: HazardFilter;
  onFilterChange: (f: HazardFilter) => void;
  counts: Record<HazardFilter, number>;
  indexing: boolean;
}) {
  return (
    <div className="pointer-events-auto absolute right-3 top-3 z-20 flex flex-col items-end gap-2">
      {indexing && (
        <div className="flex items-center gap-2 rounded-md border border-[#ff6b00]/30 bg-black/80 px-2.5 py-1.5 font-mono text-[9px] tracking-[0.2em] text-[#ffb27a] backdrop-blur">
          <span className="relative inline-flex h-1.5 w-1.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#ff6b00] opacity-60" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-[#ff6b00]" />
          </span>
          INDEXING HAZARDS…
        </div>
      )}

      <div
        className="flex items-center gap-1 rounded-md border border-white/[0.08] bg-black/80 p-1 backdrop-blur"
        role="group"
        aria-label="Filter hazard pins"
      >
        {FILTERS.map(({ id, label }) => {
          const count = counts[id];
          const active = filter === id;
          const disabled = count === 0 && id !== "all";
          return (
            <button
              key={id}
              type="button"
              disabled={disabled}
              aria-pressed={active}
              onClick={() => onFilterChange(id)}
              className={
                "rounded-sm px-2 py-1 font-mono text-[9px] tracking-[0.15em] transition-colors " +
                (active
                  ? "bg-[#ff6b00]/20 text-[#ff6b00]"
                  : disabled
                    ? "cursor-not-allowed text-white/20"
                    : "text-white/45 hover:bg-white/[0.06] hover:text-white/80")
              }
            >
              {label}
              {count > 0 && (
                <span className={active ? " text-[#ffb27a]" : " text-white/30"}> · {count}</span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
