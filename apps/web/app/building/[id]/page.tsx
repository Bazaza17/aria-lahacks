import Link from "next/link";
import { notFound } from "next/navigation";

import { BuildingCenterPane } from "@/components/building/BuildingCenterPane";
import { BRAND } from "@/lib/brand";
import { getServerSupabase, type Building } from "@/lib/supabase";

export const dynamic = "force-dynamic";

export default async function BuildingPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const supabase = getServerSupabase();
  const { data, error } = await supabase.from("buildings").select("*").eq("id", id).maybeSingle();

  if (error || !data) notFound();
  const building = data as Building;
  // "James West Alumni Center, 325 Westwood Plaza, …" → "James West Alumni Center"
  const name = building.address.split(",")[0].trim();

  return (
    <main className="flex h-screen flex-col overflow-hidden bg-page text-fg">
      <header className="flex h-12 shrink-0 items-center gap-4 border-b border-rule bg-page pl-5 pr-3">
        <Link href="/" className="text-[17px] font-medium text-fg">
          {BRAND.name}
        </Link>
        <nav className="caps flex min-w-0 items-center gap-3 text-[11px]" aria-label="Breadcrumb">
          <Link href="/dashboard" className="text-dim transition-colors hover:text-fg">
            Dashboard
          </Link>
          <span className="text-faint">/</span>
          <span className="truncate text-soft">{name}</span>
        </nav>
        <div className="ml-auto flex items-center gap-4">
          <span className="caps hidden text-[11px] tabular-nums text-faint md:inline">
            {building.lat.toFixed(4)}, {building.lng.toFixed(4)}
          </span>
          {/* The live dispatch console, served by the API through this app's /live proxy. */}
          <a
            href="/live/view"
            className="flex h-[30px] items-center bg-white px-4 text-[13px] text-ink transition-colors hover:bg-rule-light"
          >
            Live console ↗
          </a>
        </div>
      </header>

      <section className="flex min-h-0 flex-1 bg-page">
        <div className="min-h-0 flex-1">
          <BuildingCenterPane
            buildingId={building.id}
            scanUrl={building.scan_url}
            buildingName={name}
          />
        </div>
      </section>
    </main>
  );
}
