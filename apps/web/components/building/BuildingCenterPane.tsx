"use client";

import { BuildingScan } from "@/components/scan/BuildingScan";
import { isVenue } from "@/lib/scan-fire";

import { ScenarioProvider, useScenario } from "./ScenarioProvider";
import { ScenarioStrip } from "./ScenarioStrip";
import { SizeUpPanel } from "./SizeUpPanel";

type Props = {
  buildingId: string;
  scanUrl?: string | null;
  /** The building's name for the headline over the scan; optional on the local preview. */
  buildingName?: string;
};

export function BuildingCenterPane({ buildingId, scanUrl, buildingName }: Props) {
  return (
    <ScenarioProvider buildingId={buildingId}>
      <BuildingCenterPaneInner
        buildingId={buildingId}
        scanUrl={scanUrl}
        buildingName={buildingName}
      />
    </ScenarioProvider>
  );
}

function BuildingCenterPaneInner({ buildingId, scanUrl, buildingName }: Props) {
  const { fireTime, setFireTime, playing, setPlaying, fireTimeline } = useScenario();
  const hasSizeUp = isVenue(buildingId);

  return (
    <div className="flex h-full min-h-0 bg-page">
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="relative min-h-0 flex-1">
          <BuildingScan buildingId={buildingId} scanUrl={scanUrl} buildingName={buildingName} />
        </div>
        <ScenarioStrip
          fireTime={fireTime}
          onFireTimeChange={setFireTime}
          playing={playing}
          onPlayingChange={setPlaying}
          events={fireTimeline?.events}
        />
      </div>
      {hasSizeUp && (
        <div className="min-h-0 w-[360px] shrink-0 border-l border-rule">
          <SizeUpPanel buildingId={buildingId} />
        </div>
      )}
    </div>
  );
}
