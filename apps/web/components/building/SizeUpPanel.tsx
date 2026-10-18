"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";

import { FireStartPicker } from "@/components/scan/FireStartPicker";
import {
  formatClock,
  loadSizeUp,
  sizeUpDepartureAt,
  type FireEvent,
  type SizeUp,
  type SizeUpExit,
} from "@/lib/scan-fire";

import { useScenario } from "./ScenarioProvider";

// Exits listed before "↳ n more exits"; events listed around the clock before "↳ all n events".
const EXITS_SHOWN = 5;
const EVENTS_SHOWN = 6;
const EVENTS_PASSED_SHOWN = 2;

/** lost_s is null for a kept exit; a lost exit with no time keeps undefined. */
type ExitGroup = { label: string; lost_s: number | null | undefined; ids: string[] };

/** Exits lost at the same moment through the same doorway (pairs of leaves) read as one row. */
function groupExits(exits: SizeUpExit[], kept: boolean): ExitGroup[] {
  const groups: ExitGroup[] = [];
  for (const e of exits) {
    const lost = kept ? null : e.lost_s;
    const same = groups.find((g) => g.label === e.label && g.lost_s === lost);
    if (same) same.ids.push(e.exit);
    else groups.push({ label: e.label, lost_s: lost, ids: [e.exit] });
  }
  return groups;
}

/** A few events around the clock: the latest that have passed, then the next ones. */
function eventsAround(events: FireEvent[], now: number): FireEvent[] {
  const passed = events.filter((e) => e.t_s <= now).length;
  const start = Math.max(0, Math.min(passed - EVENTS_PASSED_SHOWN, events.length - EVENTS_SHOWN));
  return events.slice(start, start + EVENTS_SHOWN);
}

/** The responder size-up for the venue: follows the "Fire starts in" picker and the fire clock. */
export function SizeUpPanel({ buildingId }: { buildingId: string }) {
  const {
    fireTime,
    setFireTime,
    setPlaying,
    fireStart,
    setFireStart,
    fireStarts,
    fireTimeline,
    fireTimelineBusy,
    fireTimelineFailed,
  } = useScenario();
  const [sizeUp, setSizeUp] = useState<SizeUp | null>(null);
  const [busy, setBusy] = useState(true);
  const [failed, setFailed] = useState(false);
  const [allExits, setAllExits] = useState(false);
  const [allEvents, setAllEvents] = useState(false);

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

  const exitGroups = useMemo(
    () => [
      ...groupExits(sizeUp?.exits_lost ?? [], false),
      ...groupExits(sizeUp?.exits_kept ?? [], true),
    ],
    [sizeUp],
  );

  const pickerValue =
    fireStart ?? sizeUp?.origin.space ?? fireTimeline?.start_room ?? fireStarts?.default ?? "";
  const running = busy || fireTimelineBusy;
  const status = running
    ? "Running the engine…"
    : fireTimelineFailed
      ? "Fire timeline unavailable"
      : sizeUp?.verified === false
        ? "Screening · unverified"
        : null;
  const flashedOver = sizeUp?.first_flashover_s != null && fireTime >= sizeUp.first_flashover_s;

  const fireSection = (
    <Section title="Fire starts in" n={1}>
      {fireStarts && (
        <FireStartPicker
          starts={fireStarts.starts}
          value={pickerValue}
          disabled={running}
          onChange={setFireStart}
        />
      )}
      {sizeUp && (
        <Caption>
          {sizeUp.origin.growth} growth · {sizeUp.origin.storey ?? "?"}
          {status ? ` · ${status}` : ""}
        </Caption>
      )}
      {flashedOver && <p className="caps text-[10px] text-fire">Indicative after flashover</p>}
    </Section>
  );

  if (!sizeUp) {
    return (
      <PanelShell>
        {fireSection}
        <p className="caps px-5 py-6 text-[11px] leading-relaxed text-dim">
          {failed ? "Engine offline · size-up unavailable" : "Running the engine…"}
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
  const exitsShown = allExits ? exitGroups : exitGroups.slice(0, EXITS_SHOWN);
  const exitsHidden = exitGroups.length - EXITS_SHOWN;
  const events = fireTimeline?.events ?? [];
  const eventsShown = allEvents ? events : eventsAround(events, fireTime);

  return (
    <PanelShell>
      {fireSection}

      {dep && (
        <Section title="Evacuation" meta={`Leave at T+${formatClock(dep.t0_s)}`} n={2}>
          <div>
            <Row label="People in the building" value={dep.occupants.toLocaleString()} />
            <Row
              label={
                <>
                  <Swatch className="bg-fg" />
                  At risk following Aria&apos;s routes
                </>
              }
              value={dep.plan.at_risk}
            />
            <Row
              label={
                <>
                  <Swatch className="bg-fire" />
                  At risk finding their own way
                </>
              }
              value={dep.self.at_risk}
              valueClass="text-fire"
            />
            <Row
              label="Exits open"
              value={`${sizeUp.exits_total - lostNow} / ${sizeUp.exits_total}`}
            />
          </div>
        </Section>
      )}

      <Section title="Exits" meta={`${lostNow} of ${sizeUp.exits_total} lost`} n={3}>
        <div>
          {exitsShown.map((g) => {
            const gone = g.lost_s != null && g.lost_s <= fireTime;
            return (
              <div
                key={g.ids.join(",")}
                className="flex min-h-8 items-center justify-between gap-3 border-b border-rule py-1"
              >
                <span className="min-w-0 truncate text-[13px] text-soft" title={g.ids.join(", ")}>
                  {g.label}
                  {g.ids.length > 1 ? ` ×${g.ids.length}` : ""}
                </span>
                {g.lost_s === null ? (
                  <span className="caps shrink-0 text-[10px] text-dim">Open</span>
                ) : g.lost_s === undefined ? (
                  <span className="shrink-0 text-[14px] text-quiet">—</span>
                ) : (
                  <span
                    className={`shrink-0 text-[14px] tabular-nums ${gone ? "text-fire" : "text-quiet"}`}
                  >
                    {formatClock(g.lost_s)}
                  </span>
                )}
              </div>
            );
          })}
        </div>
        {exitsHidden > 0 && (
          <MoreButton onClick={() => setAllExits((a) => !a)}>
            {allExits ? "↳ Fewer exits" : `↳ ${exitsHidden} more exits`}
          </MoreButton>
        )}
      </Section>

      {events.length > 0 && (
        <Section title="Timeline" meta={`${events.length} events`} n={4}>
          <ul>
            {eventsShown.map((e, i) => {
              const passed = e.t_s <= fireTime;
              return (
                <li key={`${i}-${e.t_s}-${e.id}`} className="flex h-7 items-center gap-3">
                  <span
                    className={`w-[38px] shrink-0 text-[12.5px] tabular-nums ${passed ? "text-fg" : "text-quiet"}`}
                  >
                    {formatClock(e.t_s)}
                  </span>
                  <span
                    className={`h-[5px] w-[5px] shrink-0 ${passed ? "bg-fire" : "bg-faint"}`}
                    aria-hidden
                  />
                  <span
                    className={`min-w-0 truncate text-[12.5px] ${passed ? "text-fg" : "text-quiet"}`}
                    title={e.detail}
                  >
                    {e.detail}
                  </span>
                </li>
              );
            })}
          </ul>
          {events.length > EVENTS_SHOWN && (
            <MoreButton onClick={() => setAllEvents((a) => !a)}>
              {allEvents ? "↳ Around the clock" : `↳ All ${events.length} events`}
            </MoreButton>
          )}
        </Section>
      )}

      {best && (
        <Section title="Where Aria's plan matters most" n={5}>
          <p className="text-[13px] leading-[20px] text-soft">
            Leaving at T+{formatClock(best.t0_s)}, Aria&apos;s routes leave {best.plan_at_risk} at
            risk against {best.self_at_risk} on self-chosen routes: {best.saved} more people out.
          </p>
          <button
            type="button"
            onClick={() => jumpTo(best.t0_s)}
            className="caps h-[30px] self-start border border-control px-3 text-[11px] text-fg transition-colors hover:bg-white/[0.06]"
          >
            Show T+{formatClock(best.t0_s)}
          </button>
        </Section>
      )}

      <Section title="Ways down" n={6}>
        {Object.entries(sizeUp.ways_down).map(([storey, stairs]) => (
          <div key={storey}>
            <div className="caps pb-1 text-[10px] text-quiet">
              {storey} · {stairs.length}
            </div>
            {stairs.map((w) => (
              <div
                key={w.stair}
                className="flex min-h-8 items-center justify-between gap-3 border-b border-rule py-1.5"
              >
                <span className="shrink-0 text-[13px] text-soft">{w.stair}</span>
                <span className="min-w-0 text-right text-[12px] text-dim">
                  {w.from} → {w.to}
                  {w.outdoors ? " (outdoors)" : ""}
                </span>
              </div>
            ))}
          </div>
        ))}
        <Note>Elevators are not used in an evacuation.</Note>
      </Section>

      {sizeUp.check_on_site.length > 0 && (
        <Section title="Check on site" n={7}>
          <Note>Modelled open; the venue data is unsure.</Note>
          <div>
            {sizeUp.check_on_site.map((c) => (
              <div
                key={c.opening}
                className="flex min-h-8 items-center justify-between gap-3 border-b border-rule py-1.5"
                title={c.note}
              >
                <span className="min-w-0 text-[13px] text-soft">
                  {c.between[0]} ↔ {c.between[1]}
                </span>
                <span className="caps shrink-0 text-[10px] text-dim">{c.opening}</span>
              </div>
            ))}
          </div>
        </Section>
      )}

      <Section title="Assumptions" n={8}>
        <ul>
          {sizeUp.assumptions.map((a) => (
            <li
              key={a}
              className="border-b border-rule py-2 text-[12.5px] leading-[18px] text-soft"
            >
              {a}
            </li>
          ))}
        </ul>
        <Note>{sizeUp.provenance}</Note>
      </Section>
    </PanelShell>
  );
}

function PanelShell({ children }: { children: ReactNode }) {
  return (
    <aside className="flex h-full min-h-0 flex-col bg-page font-sans">
      <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
    </aside>
  );
}

function Section({
  title,
  meta,
  n,
  children,
}: {
  title: string;
  meta?: string;
  n: number;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-3.5 border-b border-rule px-5 pb-5 pt-[18px]">
      <h3 className="caps flex items-baseline justify-between gap-3 text-[11px] text-quiet">
        <span>
          {title}
          {meta && (
            <>
              {" · "}
              <span>{meta}</span>
            </>
          )}
        </span>
        <span className="text-faint">/0.{n}</span>
      </h3>
      {children}
    </section>
  );
}

function Row({
  label,
  value,
  valueClass = "text-fg",
}: {
  label: ReactNode;
  value: ReactNode;
  valueClass?: string;
}) {
  return (
    <div className="flex h-8 items-center justify-between gap-3 border-b border-rule">
      <span className="flex min-w-0 items-center gap-2 truncate text-[13px] text-quiet">
        {label}
      </span>
      <span className={`shrink-0 text-[14px] tabular-nums ${valueClass}`}>{value}</span>
    </div>
  );
}

function Swatch({ className }: { className: string }) {
  return <span className={`inline-block h-[1.5px] w-3 shrink-0 ${className}`} aria-hidden />;
}

function Caption({ children }: { children: ReactNode }) {
  return <p className="caps text-[10px] text-faint">{children}</p>;
}

function Note({ children }: { children: ReactNode }) {
  return <p className="text-[12px] leading-[18px] text-dim">{children}</p>;
}

function MoreButton({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="caps self-start text-[10px] text-dim transition-colors hover:text-fg"
    >
      {children}
    </button>
  );
}
