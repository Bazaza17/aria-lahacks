"use client";

import { X } from "lucide-react";
import { useEffect } from "react";

import { BRAND_WORDMARK, COPYRIGHT_NOTICE } from "@/lib/brand";
import type { PreplanReport as PreplanReportData } from "@/lib/types";

import { ActionsSection, HazardCard } from "./PreplanReport";
import type { ActionItem } from "./actions";

export function FullscreenReport({
  preplan,
  actions,
  dispatched,
  onDispatch,
  onClose,
}: {
  preplan: PreplanReportData;
  actions: ActionItem[];
  dispatched: Record<string, string>;
  onDispatch: (id: string) => void;
  onClose: () => void;
}) {
  // ESC closes
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 backdrop-blur"
      onClick={onClose}
      aria-modal
      role="dialog"
      style={{ animation: "ariaFadeIn 200ms ease-out" }}
    >
      <div
        className="relative h-full w-full overflow-y-auto px-12 py-10 lg:px-20 lg:py-14"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="Close fullscreen report"
          className="fixed right-6 top-6 z-10 rounded-md border border-white/[0.08] bg-black/70 p-2 text-white/60 transition-colors hover:border-[#ff6b00]/40 hover:text-[#ff6b00]"
        >
          <X className="h-4 w-4" />
        </button>

        <div className="mx-auto max-w-6xl">
          <div className="mb-2 font-mono text-[11px] tracking-[0.4em] text-[#ff6b00]">
            {BRAND_WORDMARK} · PRE-INCIDENT PLAN
          </div>
          <div className="mb-10 flex items-baseline gap-4 font-mono text-[11px] tracking-[0.25em] text-white/50">
            <span>{preplan.building_profile.address}</span>
            <span className="text-white/20">·</span>
            <span>{preplan.context.flood_zone}</span>
            <span className="text-white/20">·</span>
            <span>{preplan.context.surge_zone}</span>
          </div>

          {/* Headline + size-up — hero typography */}
          <section className="mb-12">
            <div className="mb-3 font-mono text-[11px] tracking-[0.3em] text-[#ff6b00]">
              HEADLINE RISK
            </div>
            <h1 className="mb-10 font-mono text-2xl font-medium leading-tight tracking-tight text-white lg:text-3xl">
              {preplan.summary.headline_risk}
            </h1>

            <div className="mb-3 font-mono text-[11px] tracking-[0.3em] text-white/60">
              30-SECOND SIZE-UP
            </div>
            <p className="text-base leading-relaxed text-white/85 lg:text-[17px]">
              {preplan.summary["30_second_size_up"]}
            </p>
          </section>

          <div className="mb-12 grid gap-12 lg:grid-cols-2">
            <div>
              <ActionsSection actions={actions} dispatched={dispatched} onDispatch={onDispatch} />
            </div>
            <div>
              <ProfileGrid preplan={preplan} />
            </div>
          </div>

          <section>
            <div className="mb-4 font-mono text-[11px] tracking-[0.3em] text-[#ff6b00]">
              HAZARD ANALYSIS
            </div>
            <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
              <HazardCard name="WIND" hazard={preplan.hazards.wind} />
              <HazardCard name="SURGE" hazard={preplan.hazards.surge} />
              <HazardCard name="FLOOD" hazard={preplan.hazards.flood} />
            </div>
          </section>

          <footer className="mt-12 border-t border-white/[0.06] pt-6 font-mono text-[10px] tracking-[0.15em] text-white/30">
            {COPYRIGHT_NOTICE}
          </footer>
        </div>
      </div>
    </div>
  );
}

function ProfileGrid({ preplan }: { preplan: PreplanReportData }) {
  const b = preplan.building_profile;
  const c = preplan.context;
  const rows: Array<[string, string]> = [
    ["TYPE", b.type],
    ["CONSTRUCTION", b.construction],
    ["HEIGHT", `${b.estimated_height_ft} ft`],
    ["OCCUPANCY", b.estimated_occupancy],
    ["BUILT", b.year_built_estimate],
    ["FLOOD ZONE", c.flood_zone],
    ["SURGE ZONE", c.surge_zone],
    ["HOSPITAL", `${c.nearest_hospital.name} · ${c.nearest_hospital.distance_mi} mi`],
    ["SHELTER", `${c.nearest_shelter.name} · ${c.nearest_shelter.distance_mi} mi`],
  ];
  return (
    <section>
      <div className="mb-3 font-mono text-[11px] tracking-[0.3em] text-[#ff6b00]">
        BUILDING PROFILE
      </div>
      <dl className="grid grid-cols-1 gap-x-6 gap-y-2 font-mono text-[12px] leading-snug sm:grid-cols-2">
        {rows.map(([k, v]) => (
          <div key={k} className="flex flex-col gap-1 border-b border-white/[0.04] pb-2">
            <dt className="text-[10px] tracking-[0.25em] text-[#ff6b00]/70">{k}</dt>
            <dd className="text-white">{v}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
