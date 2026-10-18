"use client";

import type { ReactNode } from "react";

import type { ScanViewMode } from "@/components/scan/BuildingScan";
import { hasEvacPlan } from "@/lib/scan-evac-paths";

const MODES: { id: ScanViewMode; label: string }[] = [
  { id: "default", label: "MESH" },
  { id: "evac", label: "EVAC" },
  { id: "hazards", label: "HAZARDS" },
];

export function ScanViewToolbar({
  mode,
  onModeChange,
  buildingId,
  evacOpenCount,
  evacTotal,
  children,
}: {
  mode: ScanViewMode;
  onModeChange: (m: ScanViewMode) => void;
  buildingId: string;
  evacOpenCount: number;
  evacTotal: number;
  /** Extra controls stacked under the mode buttons. */
  children?: ReactNode;
}) {
  const hasEvac = hasEvacPlan(buildingId);

  return (
    <div className="pointer-events-auto absolute left-3 top-3 z-20 flex flex-col gap-2">
      <div
        className="flex items-center gap-1 rounded-md border border-white/[0.08] bg-black/80 p-1 backdrop-blur"
        role="group"
        aria-label="3D scan view mode"
      >
        {MODES.map(({ id, label }) => {
          const disabled = id === "evac" && !hasEvac;
          const active = mode === id;
          return (
            <button
              key={id}
              type="button"
              disabled={disabled}
              aria-pressed={active}
              onClick={() => onModeChange(id)}
              className={
                "rounded-sm px-2.5 py-1 font-mono text-[9px] tracking-[0.15em] transition-colors " +
                (active
                  ? "bg-[#ff6b00]/20 text-[#ff6b00]"
                  : disabled
                    ? "cursor-not-allowed text-white/20"
                    : "text-white/45 hover:bg-white/[0.06] hover:text-white/80")
              }
            >
              {label}
            </button>
          );
        })}
      </div>

      {mode === "evac" && hasEvac && (
        <div className="rounded-md border border-white/[0.08] bg-black/80 px-2.5 py-1.5 font-mono text-[9px] tracking-[0.12em] backdrop-blur">
          <span className={evacOpenCount === 0 ? "text-red-300" : "text-emerald-300"}>
            {evacOpenCount}/{evacTotal} EXITS OPEN
          </span>
        </div>
      )}

      {children}
    </div>
  );
}
