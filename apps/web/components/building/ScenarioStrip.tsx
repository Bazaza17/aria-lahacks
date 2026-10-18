"use client";

import { formatClock } from "@/lib/scan-fire";

import { FIRE_HORIZON_S, FIRE_STEP_S } from "./ScenarioProvider";

export function ScenarioStrip({
  fireTime,
  onFireTimeChange,
  playing,
  onPlayingChange,
}: {
  fireTime: number;
  onFireTimeChange: (s: number) => void;
  playing: boolean;
  onPlayingChange: (p: boolean) => void;
}) {
  const togglePlay = () => {
    if (!playing && fireTime >= FIRE_HORIZON_S) onFireTimeChange(0);
    onPlayingChange(!playing);
  };

  return (
    <div className="border-t border-[#ff6b00]/30 bg-gradient-to-r from-[#0a0a0a] via-[#080808] to-[#060606]">
      <div className="flex items-center justify-between border-b border-white/[0.04] px-4 py-1.5 font-mono text-[10px] tracking-[0.25em]">
        <span className="text-[#ff6b00]/80">SCENARIO</span>
        <span className="text-white/70">FIRE · T+{formatClock(fireTime)}</span>
      </div>

      <div className="flex items-center gap-4 px-4 py-3">
        <span className="w-28 shrink-0 font-mono text-[10px] tracking-[0.25em] text-[#ff6b00]/80">
          FIRE TIMELINE
        </span>

        <button
          type="button"
          onClick={togglePlay}
          aria-label={playing ? "Pause fire timeline" : "Play fire timeline"}
          className="shrink-0 rounded-sm border border-[#ff6b00]/40 px-2.5 py-1 font-mono text-[10px] tracking-[0.2em] text-[#ff6b00] hover:bg-[#ff6b00]/10"
        >
          {playing ? "PAUSE" : "PLAY"}
        </button>

        <div className="flex-1">
          <div className="relative h-4">
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
              className="aria-range absolute inset-0 w-full"
              aria-label="Fire timeline"
            />
          </div>
          <div className="mt-1 flex justify-between font-mono text-[9px] tracking-[0.15em] text-white/40">
            <span>00:00</span>
            <span>05:00</span>
            <span>10:00</span>
            <span>15:00</span>
          </div>
        </div>

        <div className="flex w-24 shrink-0 items-center justify-end font-mono text-[11px] text-white">
          {formatClock(fireTime)}
        </div>
      </div>
    </div>
  );
}
