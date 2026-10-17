"use client";

import type { RiskScore } from "@/lib/types";

import { SURGE_STOPS, scenarioLabel, surgeRisk, type SurgeValue } from "./scenario";

const RISK_BADGE: Record<RiskScore, string> = {
  LOW: "bg-white/[0.06] text-white/60",
  MODERATE: "bg-amber-400/15 text-amber-200",
  HIGH: "bg-[#ff6b00]/15 text-[#ffb27a]",
  SEVERE: "bg-red-500/15 text-red-300",
};

export function ScenarioStrip({
  surge,
  onSurgeChange,
}: {
  surge: SurgeValue;
  onSurgeChange: (v: SurgeValue) => void;
}) {
  const surgeIdx = SURGE_STOPS.findIndex((s) => s.value === surge);
  const label = scenarioLabel(surge);
  const sRisk = surgeRisk(surge);

  return (
    <div className="border-t border-[#ff6b00]/30 bg-gradient-to-r from-[#0a0a0a] via-[#080808] to-[#060606]">
      <div className="flex items-center justify-between border-b border-white/[0.04] px-4 py-1.5 font-mono text-[10px] tracking-[0.25em]">
        <span className="text-[#ff6b00]/80">SCENARIO</span>
        <span className="text-white/70">{label}</span>
      </div>

      <SliderRow
        label="STORM SURGE"
        stops={SURGE_STOPS}
        idx={surgeIdx}
        onChange={(i) => onSurgeChange(SURGE_STOPS[i].value)}
        currentLabel={SURGE_STOPS[surgeIdx].label}
        risk={sRisk}
      />
    </div>
  );
}

function SliderRow({
  label,
  stops,
  idx,
  onChange,
  currentLabel,
  risk,
}: {
  label: string;
  stops: ReadonlyArray<{ value: number; label: string }>;
  idx: number;
  onChange: (i: number) => void;
  currentLabel: string;
  risk: RiskScore;
}) {
  const lastIdx = stops.length - 1;
  return (
    <div className="flex items-center gap-4 px-4 py-3">
      <span className="w-28 shrink-0 font-mono text-[10px] tracking-[0.25em] text-[#ff6b00]/80">
        {label}
      </span>

      <div className="flex-1">
        <div className="relative h-4">
          {stops.map((_, i) => (
            <div
              key={i}
              className="absolute top-1/2 h-2 w-px -translate-y-1/2 bg-white/20"
              style={{ left: `${(i / lastIdx) * 100}%` }}
            />
          ))}
          <input
            type="range"
            min={0}
            max={lastIdx}
            step={1}
            value={idx}
            onChange={(e) => onChange(Number(e.target.value))}
            className="aria-range absolute inset-0 w-full"
            aria-label={label}
          />
        </div>
        <div className="mt-1 flex justify-between font-mono text-[9px] tracking-[0.15em] text-white/40">
          {stops.map((s, i) => (
            <span key={s.value} className={i === idx ? "text-[#ff6b00]" : ""}>
              {s.label}
            </span>
          ))}
        </div>
      </div>

      <div className="flex w-56 shrink-0 items-center justify-end gap-2 font-mono text-[10px]">
        <span className="text-white/40">CURRENT:</span>
        <span className="text-white">{currentLabel}</span>
        <span className={"rounded-sm px-2 py-0.5 tracking-[0.2em] " + RISK_BADGE[risk]}>
          RISK: {risk}
        </span>
      </div>
    </div>
  );
}
