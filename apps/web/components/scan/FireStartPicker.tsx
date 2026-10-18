"use client";

import type { FireStart } from "@/lib/scan-fire";

type Props = {
  starts: FireStart[];
  value: string;
  disabled: boolean;
  onChange: (id: string) => void;
};

/** "Fire starts in": picks the start space; the API reruns the engine for it. */
export function FireStartPicker({ starts, value, disabled, onChange }: Props) {
  const storeys = [...new Set(starts.map((s) => s.storey ?? "?"))];
  // "Founders' Room (120)" reads "Founders' Room"; the note stays only where two names collide.
  const short = (s: FireStart) => (s.label ?? s.name).split(" (")[0];
  const shortCounts = new Map<string, number>();
  for (const s of starts) shortCounts.set(short(s), (shortCounts.get(short(s)) ?? 0) + 1);
  const optionLabel = (s: FireStart) =>
    (shortCounts.get(short(s)) ?? 0) > 1 ? (s.label ?? s.name) : short(s);

  return (
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        aria-label="Space the fire starts in"
        className="h-[34px] w-full cursor-pointer appearance-none truncate border border-rule bg-transparent pl-3 pr-20 text-[14px] text-fg outline-none transition-colors hover:border-control focus-visible:border-control disabled:cursor-wait disabled:opacity-60"
      >
        {storeys.map((storey) => (
          <optgroup key={storey} label={storey} className="bg-page">
            {starts
              .filter((s) => (s.storey ?? "?") === storey)
              .map((s) => (
                <option key={s.id} value={s.id} title={s.id} className="bg-page">
                  {optionLabel(s)}
                </option>
              ))}
          </optgroup>
        ))}
      </select>
      <span
        className="caps pointer-events-none absolute inset-y-0 right-3 flex items-center gap-2.5 text-[10px] text-dim"
        aria-hidden
      >
        {value}
        <svg width="8" height="5" viewBox="0 0 8 5" className="text-quiet">
          <path d="M0.5 0.5 4 4 7.5 0.5" fill="none" stroke="currentColor" />
        </svg>
      </span>
    </div>
  );
}
