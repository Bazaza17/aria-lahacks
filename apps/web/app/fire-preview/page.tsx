"use client";

import { AgentRunProvider } from "@/components/agent/AgentRunProvider";
import { BuildingCenterPane } from "@/components/building/BuildingCenterPane";

// Local preview of the fire layer over the venue scan, no Supabase needed.
export default function FirePreviewPage() {
  return (
    <main className="h-screen bg-[#0a0a0a]">
      <AgentRunProvider address="James West Alumni Center" buildingId="venue">
        <BuildingCenterPane buildingId="venue" scanUrl="/scans/venue/scan.glb" />
      </AgentRunProvider>
    </main>
  );
}
