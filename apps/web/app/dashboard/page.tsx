import { getServerSupabase, type Building } from "@/lib/supabase";

import { MapDashboard } from "./MapDashboard";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const supabase = getServerSupabase();
  const { data } = await supabase
    .from("buildings")
    .select("*")
    .order("created_at", { ascending: true });

  // The first building gets the prominent pulse on the map; others get a smaller marker.
  // Only buildings flagged is_demo are shown for now.
  const demoBuildings = ((data ?? []) as Building[]).filter((b) => b.is_demo);

  return (
    <MapDashboard
      buildings={demoBuildings}
      mapboxToken={process.env.NEXT_PUBLIC_MAPBOX_TOKEN ?? ""}
    />
  );
}
