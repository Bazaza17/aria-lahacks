"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";

import {
  formatClock,
  loadSizeUp,
  sizeUpDepartureAt,
  type SizeUp,
  type SizeUpExit,
  type SizeUpOutcome,
} from "@/lib/scan-fire";

import { useScenario } from "./ScenarioProvider";

type ExitGroup = { label: string; from?: string; lost_s: number; ids: string[] };

/** Exits lost at the same moment through the same doorway (pairs of leaves) read as one row. */
function groupLost(exits: SizeUpExit[]): ExitGroup[] {
  const groups: ExitGroup[] = [];
  for (const e of exits) {
    const lost = e.lost_s ?? 0;
    const same = groups.find((g) => g.label === e.label && g.lost_s === lost);
    if (same) same.ids.push(e.exit);
    else groups.push({ label: e.label, from: e.from, lost_s: lost, ids: [e.exit] });
  }
  return groups;
}

/** The responder size-up for the venue: follows the "Fire starts in" picker and the fire clock. */
export function SizeUpPanel({ buildingId }: { buildingId: string }) {
  const { fireTime, setFireTime, setPlaying, fireStart } = useScenario();
  const [sizeUp, setSizeUp] = useState<SizeUp | null>(null);
  const [busy, setBusy] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setBusy(true);
    void loadSizeUp(buildingId, fireStart).then((s) => {
      if (cancelled) return;
      if (s) setSizeUp(s);
      setFailed(!s);
      setBusy(false);
    });
    return () => {
      cancelled = true;
    };
  }, [buildingId, fireStart]);

  const lostGroups = useMemo(() => groupLost(sizeUp?.exits_lost ?? []), [sizeUp]);

  if (!sizeUp) {
    return (
      <PanelShell busy={busy}>
        <p className="px-4 py-6 font-mono text-[10px] leading-relaxed tracking-[0.2em] text-white/40">
          {failed ? "ENGINE OFFLINE · SIZE-UP UNAVAILABLE" : "RUNNING THE ENGINE…"}
        </p>
      </PanelShell>
    );
  }

  const dep = sizeUpDepartureAt(sizeUp, fireTime);
  const lostNow = sizeUp.exits_lost.filter((e) => (e.lost_s ?? Infinity) <= fireTime).length;
  const best = sizeUp.best_moment;
  const jumpTo = (t: number) => {
    setPlaying(false);
    setFireTime(t);
  };
  const flashedOver = sizeUp.first_flashover_s !== null && fireTime >= sizeUp.first_flashover_s;

  return (
    <PanelShell busy={busy} verified={sizeUp.verified}>
      <Section title="FIRE">
        <div className="text-[13px] text-white">
          {sizeUp.origin.name} <span className="text-white/40">· {sizeUp.origin.space}</span>
        </div>
        <div className="mt-0.5 text-white/50">
          {sizeUp.origin.storey ?? "?"} · {sizeUp.origin.growth.toUpperCase()} t² GROWTH
        </div>
        <ul className="mt-2 space-y-0.5">
          <Moment t={sizeUp.origin.untenable_s} now={fireTime} label="Room of origin untenable" />
          <Moment
            t={sizeUp.first_smoke_beyond_origin?.t_s ?? null}
            now={fireTime}
            label={`First smoke beyond it · ${sizeUp.first_smoke_beyond_origin?.name ?? ""}`}
          />
          <Moment
            t={sizeUp.first_untenable_beyond_origin?.t_s ?? null}
            now={fireTime}
            label={`First untenable beyond it · ${sizeUp.first_untenable_beyond_origin?.name ?? ""}`}
          />
          <Moment t={sizeUp.first_flashover_s} now={fireTime} label="First flashover" />
        </ul>
        {flashedOver && (
          <div className="mt-2 rounded-sm border border-amber-300/30 px-2 py-1 text-[9px] tracking-[0.15em] text-amber-200">
            INDICATIVE AFTER FLASHOVER
          </div>
        )}
      </Section>

      <Section
        title={`EXITS · ${lostNow} OF ${sizeUp.exits_total} LOST BY T+${formatClock(fireTime)}`}
      >
        {lostGroups.length === 0 && <div className="text-white/50">No exit lost in 15 min.</div>}
        <ul className="space-y-1">
          {lostGroups.map((g) => {
            const gone = g.lost_s <= fireTime;
            return (
              <li key={g.ids.join(",")} className="flex gap-2">
                <span className={`w-10 shrink-0 ${gone ? "text-red-400" : "text-white/40"}`}>
                  {formatClock(g.lost_s)}
                </span>
                <span className={gone ? "text-white/85" : "text-white/50"}>
                  {g.label}
                  {g.ids.length > 1 ? ` ×${g.ids.length}` : ""}
                </span>
              </li>
            );
          })}
        </ul>
        {sizeUp.exits_kept.length > 0 && (
          <div className="mt-2 text-white/40">
            Never lost: {sizeUp.exits_kept.map((e) => e.label).join(" · ")}
          </div>
        )}
      </Section>

      {dep && (
        <Section title={`IF EVERYONE LEAVES AT T+${formatClock(dep.t0_s)}`}>
          <div className="mb-2 text-white/50">{dep.occupants.toLocaleString()} people inside</div>
          <div className="grid grid-cols-2 gap-2">
            <Outcome title="ARIA'S PLAN" o={dep.plan} t0={dep.t0_s} tone="text-sky-300" />
            <Outcome title="SELF-CHOSEN" o={dep.self} t0={dep.t0_s} tone="text-red-300" />
          </div>
        </Section>
      )}

      {best && (
        <Section title="WHERE ARIA'S PLAN MATTERS MOST">
          <p className="leading-relaxed text-white/70">
            Leaving at T+{formatClock(best.t0_s)}, Aria&apos;s routes leave {best.plan_at_risk} at
            risk against {best.self_at_risk} on self-chosen routes: {best.saved} more people out.
          </p>
          <button
            type="button"
            onClick={() => jumpTo(best.t0_s)}
            className="mt-2 rounded-sm border border-[#ff6b00]/40 px-2 py-1 text-[9px] tracking-[0.2em] text-[#ff6b00] hover:bg-[#ff6b00]/10"
          >
            SHOW T+{formatClock(best.t0_s)}
          </button>
        </Section>
      )}

      <Section title="WAYS DOWN">
        {Object.entries(sizeUp.ways_down).map(([storey, stairs]) => (
          <div key={storey} className="mb-1.5">
            <span className="text-[#ff6b00]/80">{storey}</span>{" "}
            <span className="text-white/40">· {stairs.length}</span>
            <ul className="mt-0.5 space-y-0.5 text-white/65">
              {stairs.map((w) => (
                <li key={w.stair}>
                  {w.stair}: {w.from} → {w.to}
                  {w.outdoors ? " (outdoors)" : ""}
                </li>
              ))}
            </ul>
          </div>
        ))}
        <div className="text-white/40">Elevators are not used in an evacuation.</div>
      </Section>

      {sizeUp.check_on_site.length > 0 && (
        <Section title="CHECK ON SITE">
          <div className="mb-1 text-white/40">Modelled open; the venue data is unsure.</div>
          <ul className="space-y-1">
            {sizeUp.check_on_site.map((c) => (
              <li key={c.opening} className="text-white/70" title={c.note}>
                {c.between[0]} ↔ {c.between[1]} <span className="text-white/35">{c.opening}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="ASSUMPTIONS">
        <ul className="list-disc space-y-1 pl-3 text-white/50">
          {sizeUp.assumptions.map((a) => (
            <li key={a}>{a}</li>
          ))}
        </ul>
        <p className="mt-2 text-white/40">{sizeUp.provenance}</p>
      </Section>
    </PanelShell>
  );
}

function PanelShell({
  busy,
  verified,
  children,
}: {
  busy: boolean;
  verified?: boolean;
  children: ReactNode;
}) {
  return (
    <aside className="flex h-full min-h-0 flex-col bg-black font-mono text-[10px]">
      <div className="flex items-center justify-between border-b border-white/[0.08] px-4 py-2.5 tracking-[0.3em]">
        <span className="text-[#ff6b00]">SIZE-UP</span>
        <span className="text-white/40">
          {busy ? "RUNNING…" : verified === false ? "SCREENING · UNVERIFIED" : ""}
        </span>
      </div>
      <div className="min-h-0 flex-1 divide-y divide-white/[0.06] overflow-y-auto">{children}</div>
    </aside>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="px-4 py-3">
      <h3 className="mb-2 text-[9px] tracking-[0.25em] text-[#ff6b00]/80">{title}</h3>
      {children}
    </section>
  );
}

function Moment({ t, now, label }: { t: number | null; now: number; label: string }) {
  if (t === null) return null;
  const passed = t <= now;
  return (
    <li className="flex gap-2">
      <span className={`w-10 shrink-0 ${passed ? "text-[#ff6b00]" : "text-white/40"}`}>
        {formatClock(t)}
      </span>
      <span className={passed ? "text-white/85" : "text-white/50"}>{label}</span>
    </li>
  );
}

function Outcome({
  title,
  o,
  t0,
  tone,
}: {
  title: string;
  o: SizeUpOutcome;
  t0: number;
  tone: string;
}) {
  const out = o.last_out_s === null ? "—" : `T+${formatClock(o.last_out_s)}`;
  const took = o.last_out_s === null ? "" : ` (${formatClock(o.last_out_s - t0)} after leaving)`;
  return (
    <div className="rounded-sm border border-white/[0.08] bg-white/[0.02] p-2">
      <div className={`mb-1 text-[9px] tracking-[0.2em] ${tone}`}>{title}</div>
      <div className={`text-lg ${o.at_risk > 0 ? "text-red-300" : "text-emerald-300"}`}>
        {o.at_risk}
      </div>
      <div className="text-white/45">at risk</div>
      <div className="mt-1 text-white/70">
        {o.at_risk > 0 ? "Rest out by" : "All out by"} {out}
        <span className="text-white/40">{took}</span>
      </div>
    </div>
  );
}
