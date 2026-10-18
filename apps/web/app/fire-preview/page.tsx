"use client";

import { BuildingCenterPane } from "@/components/building/BuildingCenterPane";

// Local preview of the fire layer over the venue scan, no Supabase needed.
export default function FirePreviewPage() {
  return (
    <main className="h-screen bg-page">
      <BuildingCenterPane buildingId="venue" scanUrl="/scans/venue_4rooms_web.glb" />
    </main>
  );
}
