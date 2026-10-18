"use client";

import { useEffect, useState, type ReactNode } from "react";

import { formatClock, isVenue, loadSizeUp, type SizeUp } from "@/lib/scan-fire";
import type { Building } from "@/lib/supabase";

/** One docked-panel section: caps label left, /0.n marker right. */
export function PanelSection({
  label,
  n,
  children,
}: {
  label: string;
  n: number;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-3.5 border-b border-rule px-5 pt-[18px] pb-5">
      <div className="caps flex items-center justify-between text-[11px]">
        <span className="text-quiet">{label}</span>
        <span className="text-faint">/0.{n}</span>
      </div>
      {children}
    </section>
  );
}

function Row({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="flex h-8 items-center justify-between gap-3 border-b border-rule">
      <span className="flex items-center gap-2 text-[13px] text-quiet">{label}</span>
      <span className="text-right text-[14px] tabular-nums text-soft">{children}</span>
    </div>
  );
}

/** The selected building's pre-plan, straight from the engine's default scenario. */
export function VenuePreplanCard({ building }: { building: Building }) {
  const venue = isVenue(building.id);
  const [sizeUp, setSizeUp] = useState<SizeUp | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!venue) return;
    let cancelled = false;
    void loadSizeUp(building.id).then((s) => {
      if (cancelled) return;
      setSizeUp(s);
      setFailed(!s);
    });
    return () => {
      cancelled = true;
    };
  }, [building.id, venue]);

  const firstLost = sizeUp?.exits_lost[0];
  const atStart = sizeUp?.departures[0];
  // Only the venue has an engine run; /0.1 already says "Pre-plan pending" for the rest.
  if (!venue) return null;

  const status = sizeUp
    ? `Leaving at once · Engine`
    : failed
      ? "Engine offline"
      : "Running the engine…";

  return (
    <PanelSection label="Pre-plan" n={2}>
      {sizeUp && (
        <div className="flex flex-col">
          <Row label="Fire in">{sizeUp.origin.name.split(" (")[0]}</Row>
          <Row label="First exit lost">
            {firstLost?.lost_s != null ? (
              <span className="text-fire">T+{formatClock(firstLost.lost_s)}</span>
            ) : (
              "None"
            )}
          </Row>
          <Row label="Exits lost in 15 min">
            {sizeUp.exits_lost.length} / {sizeUp.exits_total}
          </Row>
          {atStart && (
            <>
              <Row
                label={
                  <>
                    <span aria-hidden className="h-[2px] w-3.5 bg-white" />
                    Rooms at risk on Aria&apos;s routes
                  </>
                }
              >
                {atStart.plan.rooms_at_risk} / {atStart.rooms}
              </Row>
              <Row
                label={
                  <>
                    <span aria-hidden className="h-[2px] w-3.5 bg-fire" />
                    Rooms at risk finding their own way
                  </>
                }
              >
                <span className="text-fire">
                  {atStart.self.rooms_at_risk} / {atStart.rooms}
                </span>
              </Row>
            </>
          )}
        </div>
      )}
      {failed && (
        <p className="text-[12px] text-dim">The engine runs in the API; it is not reachable.</p>
      )}
      <div className="caps text-[10px] text-dim">{status}</div>
    </PanelSection>
  );
}
