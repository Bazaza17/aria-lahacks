import Link from "next/link";
import { notFound } from "next/navigation";

import { BuildingCenterPane } from "@/components/building/BuildingCenterPane";
import { getServerSupabase, type Building } from "@/lib/supabase";

export const dynamic = "force-dynamic";

export default async function BuildingPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const supabase = getServerSupabase();
  const { data, error } = await supabase.from("buildings").select("*").eq("id", id).maybeSingle();

  if (error || !data) notFound();
  const building = data as Building;

  return (
    <main className="flex h-screen flex-col overflow-hidden bg-black text-white">
      <header className="flex items-center justify-between border-b border-white/[0.08] px-8 py-5">
        <div className="flex items-center gap-6">
          <Link
            href="/dashboard"
            className="font-mono text-xs tracking-[0.3em] text-white/40 transition-colors hover:text-white"
          >
            ← DASHBOARD
          </Link>
          <span className="font-mono text-xs tracking-[0.3em] text-white/30">/</span>
          <div className="flex items-center gap-3">
            <span className="h-1.5 w-1.5 rounded-full bg-[#ff6b00]" />
            <h1 className="text-sm font-medium tracking-wide">{building.address}</h1>
          </div>
        </div>
        <div className="flex items-center gap-4 font-mono text-[10px] tracking-[0.25em] text-white/40">
          <span>
            {building.lat.toFixed(4)}, {building.lng.toFixed(4)}
          </span>
          <span className="hidden md:inline">·</span>
          <span className="hidden md:inline">ID {building.id.slice(0, 8).toUpperCase()}</span>
          {/* The live dispatch console, served by the API through this app's /live proxy. */}
          <a
            href="/live/view"
            className="rounded border border-[#ff6b00]/40 px-3 py-1.5 text-[#ff6b00] transition-colors hover:bg-[#ff6b00]/10"
          >
            LIVE CONSOLE →
          </a>
        </div>
      </header>

      <section className="flex min-h-0 flex-1 bg-white/[0.06]">
        <div className="min-h-0 flex-1">
          <BuildingCenterPane buildingId={building.id} scanUrl={building.scan_url} />
        </div>
      </section>
    </main>
  );
}
