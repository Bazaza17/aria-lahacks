"use client";

import { useState } from "react";

import { BuildingScan } from "@/components/scan/BuildingScan";
import { isVenue } from "@/lib/scan-fire";

import { ScenarioProvider, useScenario } from "./ScenarioProvider";
import { ScenarioStrip } from "./ScenarioStrip";
import { SizeUpPanel } from "./SizeUpPanel";

export function BuildingCenterPane({
  buildingId,
  scanUrl,
}: {
  buildingId: string;
  scanUrl?: string | null;
}) {
  return (
    <ScenarioProvider>
      <BuildingCenterPaneInner buildingId={buildingId} scanUrl={scanUrl} />
    </ScenarioProvider>
  );
}

function BuildingCenterPaneInner({
  buildingId,
  scanUrl,
}: {
  buildingId: string;
  scanUrl?: string | null;
}) {
  const { fireTime, setFireTime, playing, setPlaying } = useScenario();
  const hasSizeUp = isVenue(buildingId);
  const [sizeUpOpen, setSizeUpOpen] = useState(true);

  return (
    <div className="flex h-full min-h-0 flex-col bg-[#0a0a0a]">
      <div className="flex items-center justify-between border-b border-white/[0.08] px-5 py-2.5 font-mono text-[11px] tracking-[0.3em] text-[#ff6b00]">
        <span className="flex items-center gap-2">
          <PulsingDot />
          FIRE PRE-PLAN
        </span>
        {hasSizeUp && (
          <button
            type="button"
            onClick={() => setSizeUpOpen((o) => !o)}
            aria-expanded={sizeUpOpen}
            className="rounded-sm border border-white/[0.1] px-2 py-0.5 text-[9px] tracking-[0.2em] text-white/50 hover:text-white"
          >
            {sizeUpOpen ? "HIDE SIZE-UP" : "SHOW SIZE-UP"}
          </button>
        )}
      </div>

      <div className="flex min-h-0 flex-1">
        <div className="relative min-h-0 min-w-0 flex-1">
          <BuildingScan buildingId={buildingId} scanUrl={scanUrl} />
        </div>
        {hasSizeUp && sizeUpOpen && (
          <div className="min-h-0 w-[340px] shrink-0 border-l border-white/[0.08]">
            <SizeUpPanel buildingId={buildingId} />
          </div>
        )}
      </div>

      <ScenarioStrip
        fireTime={fireTime}
        onFireTimeChange={setFireTime}
        playing={playing}
        onPlayingChange={setPlaying}
      />
    </div>
  );
}

function PulsingDot() {
  return (
    <span className="relative inline-flex h-1.5 w-1.5">
      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#ff6b00] opacity-60" />
      <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-[#ff6b00]" />
    </span>
  );
}
