import { getServerSupabase, type Building } from "@/lib/supabase";

import { MapDashboard } from "./MapDashboard";
import type { PreplanRow } from "./AgentActivity";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const supabase = getServerSupabase();

  const [buildingsRes, preplansRes, preplanCountRes] = await Promise.all([
    supabase.from("buildings").select("*").order("created_at", { ascending: true }),
    supabase
      .from("preplans")
      .select("id, created_at, scenario_params, building:buildings(address)")
      .order("created_at", { ascending: false })
      .limit(5),
    supabase.from("preplans").select("id", { count: "exact", head: true }),
  ]);

  const buildings: Building[] = buildingsRes.data ?? [];
  const preplans = (preplansRes.data ?? []) as unknown as PreplanRow[];

  // The first building gets the prominent pulse on the map; others get a
  // smaller marker. Only buildings flagged is_demo are shown for now.
  const demoBuildings = buildings.filter((b) => b.is_demo);

  return (
    <MapDashboard
      buildings={demoBuildings}
      preplans={preplans}
      preplanCount={preplanCountRes.count ?? 0}
      mapboxToken={process.env.NEXT_PUBLIC_MAPBOX_TOKEN ?? ""}
    />
  );
}
