"use client";

import type { FireStart } from "@/lib/scan-fire";

type Props = {
  starts: FireStart[];
  value: string;
  busy: boolean;
  failed: boolean;
  onChange: (id: string) => void;
};

/** "Fire starts in": picks the start space; the API reruns the engine for it. */
export function FireStartPicker({ starts, value, busy, failed, onChange }: Props) {
  const storeys = [...new Set(starts.map((s) => s.storey ?? "?"))];

  return (
    <label className="flex w-[260px] items-center gap-2 rounded-md border border-[#ff6b00]/30 bg-black/80 px-2 py-1 font-mono text-[9px] tracking-[0.12em] backdrop-blur">
      <span className="shrink-0 text-[#ff6b00]">FIRE STARTS IN</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={busy}
        aria-label="Space the fire starts in"
        className="min-w-0 flex-1 rounded-sm bg-white/[0.04] px-1 py-0.5 text-white/85 outline-none focus:bg-white/[0.08] disabled:opacity-50"
      >
        {storeys.map((storey) => (
          <optgroup key={storey} label={storey} className="bg-black">
            {starts
              .filter((s) => (s.storey ?? "?") === storey)
              .map((s) => (
                <option key={s.id} value={s.id} title={s.id} className="bg-black">
                  {s.label ?? s.name}
                </option>
              ))}
          </optgroup>
        ))}
      </select>
      {busy && <span className="shrink-0 animate-pulse text-white/40">RUNNING</span>}
      {failed && !busy && <span className="shrink-0 text-red-300/80">OFFLINE</span>}
    </label>
  );
}
