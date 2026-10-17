"use client";

import { formatRelative } from "@/lib/time";

export type PreplanRow = {
  id: string;
  created_at: string;
  scenario_params: {
    wind_mph?: number;
    surge_ft?: number;
    rainfall_in?: number;
  } | null;
  building: { address: string } | null;
};

export function AgentActivity({
  preplans,
  preplanCount,
}: {
  preplans: PreplanRow[];
  preplanCount: number;
}) {
  // "LIVE" only when something has actually happened in the last 5 minutes;
  // otherwise the panel is just reading the database state.
  const isLive =
    preplans.length > 0 && Date.now() - new Date(preplans[0].created_at).getTime() < 5 * 60_000;

  return (
    <aside className="absolute bottom-5 left-5 z-10 w-[360px] rounded-md border border-white/[0.08] bg-black/85 backdrop-blur">
      <div className="flex items-center justify-between border-b border-white/[0.08] px-4 py-2.5">
        <span className="font-mono text-[10px] tracking-[0.3em] text-white/70">
          RECENT PRE-PLANS
        </span>
        {isLive ? (
          <span className="inline-flex items-center gap-2 font-mono text-[10px] tracking-[0.3em] text-[#ff6b00]">
            <span className="relative inline-flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#ff6b00] opacity-60" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-[#ff6b00]" />
            </span>
            LIVE
          </span>
        ) : null}
      </div>

      <div className="flex max-h-[55vh] flex-col divide-y divide-white/[0.06] overflow-y-auto px-4 py-1 font-mono text-[11px] leading-relaxed">
        {preplans.length === 0 && (
          <Entry title="No pre-plans yet" subtitle="Click a building to generate a pre-plan." dim />
        )}

        {preplans.slice(0, 3).map((p) => (
          <Entry
            key={p.id}
            title={`Pre-plan generated · ${formatRelative(p.created_at)}`}
            subtitle={`${p.building?.address ?? "Unknown"} · Cat ${categorize(
              p.scenario_params?.wind_mph,
            )} scenario`}
          />
        ))}
      </div>

      <div className="whitespace-nowrap border-t border-white/[0.08] px-4 py-2 font-mono text-[10px] tracking-[0.18em] text-white/40">
        {preplanCount} PRE-PLAN{preplanCount === 1 ? "" : "S"} · MIAMI-DADE
      </div>
    </aside>
  );
}

function Entry({
  title,
  subtitle,
  pulse,
  dim,
}: {
  title: string;
  subtitle: string;
  pulse?: boolean;
  dim?: boolean;
}) {
  return (
    <div className="flex items-start gap-2 py-2.5">
      <span className="mt-px font-mono text-[#ff6b00]">►</span>
      <div className="flex-1 min-w-0">
        <div
          className={
            "flex items-center gap-2 truncate " + (dim ? "text-white/60" : "text-white/85")
          }
        >
          <span className="truncate">{title}</span>
          {pulse && (
            <span className="relative inline-flex h-1.5 w-1.5 shrink-0">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#ff6b00] opacity-60" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-[#ff6b00]" />
            </span>
          )}
        </div>
        <div className="truncate text-white/40">{subtitle}</div>
      </div>
    </div>
  );
}

function categorize(mph?: number): string {
  if (!mph) return "?";
  if (mph >= 157) return "5";
  if (mph >= 130) return "4";
  if (mph >= 111) return "3";
  if (mph >= 96) return "2";
  if (mph >= 74) return "1";
  return "TS";
}
