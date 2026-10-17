"use client";

import { BuildingScan } from "@/components/scan/BuildingScan";

import { ScenarioProvider, useScenario } from "./ScenarioProvider";
import { ScenarioStrip } from "./ScenarioStrip";

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
  const { surge, setSurge } = useScenario();

  return (
    <div className="flex h-full min-h-0 flex-col bg-[#0a0a0a]">
      <div className="flex items-center gap-2 border-b border-white/[0.08] px-5 py-2.5 font-mono text-[11px] tracking-[0.3em] text-[#ff6b00]">
        <PulsingDot />
        3D SCAN
      </div>

      <div className="relative min-h-0 flex-1">
        <BuildingScan buildingId={buildingId} scanUrl={scanUrl} />
      </div>

      <ScenarioStrip surge={surge} onSurgeChange={setSurge} />
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
