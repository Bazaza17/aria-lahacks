"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { formatClock, loadSizeUp, type SizeUp } from "@/lib/scan-fire";
import type { Building } from "@/lib/supabase";

/** The venue's pre-plan headline, straight from the engine's default scenario. */
export function VenuePreplanCard({ building }: { building: Building }) {
  const [sizeUp, setSizeUp] = useState<SizeUp | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void loadSizeUp(building.id).then((s) => {
      if (cancelled) return;
      setSizeUp(s);
      setFailed(!s);
    });
    return () => {
      cancelled = true;
    };
  }, [building.id]);

  const firstLost = sizeUp?.exits_lost[0];
  const atStart = sizeUp?.departures[0];

  return (
    <aside className="absolute bottom-5 left-5 z-10 w-[360px] rounded-md border border-white/[0.08] bg-black/85 font-mono backdrop-blur">
      <div className="flex items-center justify-between border-b border-white/[0.08] px-4 py-2.5 text-[10px] tracking-[0.3em]">
        <span className="text-white/70">VENUE PRE-PLAN</span>
        <span className="text-white/35">
          {sizeUp ? "ENGINE" : failed ? "ENGINE OFFLINE" : "RUNNING…"}
        </span>
      </div>

      <div className="px-4 py-3 text-[11px] leading-relaxed">
        <div className="text-white/85">{building.address}</div>
        {sizeUp && (
          <ul className="mt-2 space-y-1 text-white/60">
            <li>
              <span className="text-[#ff6b00]">►</span> Fire in {sizeUp.origin.name},{" "}
              {sizeUp.origin.growth} growth
            </li>
            {firstLost && (
              <li>
                <span className="text-[#ff6b00]">►</span> First exit lost at{" "}
                {formatClock(firstLost.lost_s ?? 0)} · {sizeUp.exits_lost.length} of{" "}
                {sizeUp.exits_total} lost in 15 min
              </li>
            )}
            {atStart && (
              <li>
                <span className="text-[#ff6b00]">►</span>{" "}
                {`Leaving at once: ${atStart.plan.at_risk} at risk on Aria's routes, ${atStart.self.at_risk} on self-chosen routes`}
              </li>
            )}
          </ul>
        )}
        {failed && (
          <div className="mt-2 text-white/40">The engine runs in the API; it is not reachable.</div>
        )}
      </div>

      <Link
        href={`/building/${building.id}`}
        className="flex items-center justify-between border-t border-white/[0.08] px-4 py-2 text-[10px] tracking-[0.2em] text-[#ff6b00] transition-colors hover:bg-[#ff6b00]/10"
      >
        OPEN PRE-PLAN <span aria-hidden>→</span>
      </Link>
    </aside>
  );
}
