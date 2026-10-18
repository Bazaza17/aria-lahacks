"use client";

import { formatClock, type FireEvent } from "@/lib/scan-fire";

import { FIRE_HORIZON_S, FIRE_STEP_S } from "./ScenarioProvider";

// The range thumb is 10px wide, so its centre runs from 5px to (width - 5px).
const THUMB_HALF_PX = 5;
const LOUD_EVENTS = new Set(["ignition", "flashover"]);
const TICK_LABELS = ["00:00", "05:00", "10:00", "15:00"];

type Props = {
  fireTime: number;
  onFireTimeChange: (s: number) => void;
  playing: boolean;
  onPlayingChange: (p: boolean) => void;
  /** The engine's fire events, drawn as ticks above the track. */
  events?: FireEvent[];
};

function tickLeft(tS: number): string {
  const frac = Math.min(1, Math.max(0, tS / FIRE_HORIZON_S));
  return `calc(${THUMB_HALF_PX}px + (100% - ${THUMB_HALF_PX * 2}px) * ${frac})`;
}

export function ScenarioStrip({
  fireTime,
  onFireTimeChange,
  playing,
  onPlayingChange,
  events,
}: Props) {
  const togglePlay = () => {
    if (!playing && fireTime >= FIRE_HORIZON_S) onFireTimeChange(0);
    onPlayingChange(!playing);
  };

  return (
    <div className="flex h-14 shrink-0 items-center gap-4 border-t border-rule bg-page px-5">
      <button
        type="button"
        onClick={togglePlay}
        aria-label={playing ? "Pause fire timeline" : "Play fire timeline"}
        className="flex h-[30px] w-[34px] shrink-0 items-center justify-center border border-control text-[11px] text-fg transition-colors hover:bg-white/[0.06]"
      >
        {playing ? "❚❚" : "▶"}
      </button>

      <span className="w-[84px] shrink-0 text-[16px] tabular-nums text-fg">
        T+{formatClock(fireTime)}
      </span>

      <div className="relative min-w-0 flex-1 pt-2.5">
        <div className="pointer-events-none absolute inset-x-0 top-0 h-2" aria-hidden>
          {(events ?? []).map((e, i) => (
            <span
              key={`${i}-${e.type}-${e.id}`}
              className={`absolute top-0 h-2 w-[1.5px] ${LOUD_EVENTS.has(e.type) ? "bg-fire" : "bg-control"}`}
              style={{ left: tickLeft(e.t_s) }}
            />
          ))}
        </div>
        <input
          type="range"
          min={0}
          max={FIRE_HORIZON_S}
          step={FIRE_STEP_S}
          value={fireTime}
          onChange={(e) => {
            onPlayingChange(false);
            onFireTimeChange(Number(e.target.value));
          }}
          className="aria-range block w-full"
          aria-label="Fire timeline"
        />
        <div className="caps mt-0.5 flex justify-between text-[10px] text-faint">
          {TICK_LABELS.map((label) => (
            <span key={label}>{label}</span>
          ))}
        </div>
      </div>
    </div>
  );
}
