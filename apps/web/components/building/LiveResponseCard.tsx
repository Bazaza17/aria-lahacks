"use client";

import { useEffect, useState } from "react";

import { formatClock } from "@/lib/scan-fire";

// How often the panel re-reads the live layer (public situation through the /live proxy).
const POLL_MS = 8000;

type RollCall = {
  total: number;
  unconfirmed: number;
  contacted: number;
  needs_help: number;
  confirmed_safe: number;
};

type LiveSituation = {
  evacuation: { mode: string; minute_now?: number; description?: string | null } | null;
  roll_call?: RollCall;
};

/** The live response (CREAO agents, texts and calls, the dispatcher console) at the top of the
 *  building panel: what's happening now, and a drill that starts where the fire model does. */
export function LiveResponseCard({
  buildingId,
  fireStart,
  fireLabel,
}: {
  buildingId: string;
  fireStart: string | null;
  fireLabel: string | null;
}) {
  const [live, setLive] = useState<LiveSituation | null>(null);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const read = async () => {
      try {
        const res = await fetch(`/live/buildings/${encodeURIComponent(buildingId)}/situation`);
        if (!res.ok) throw new Error(String(res.status));
        const data = (await res.json()) as LiveSituation;
        if (!cancelled) {
          setLive(data);
          setOffline(false);
        }
      } catch {
        if (!cancelled) setOffline(true);
      }
    };
    void read();
    const timer = window.setInterval(() => void read(), POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [buildingId]);

  const ev = live?.evacuation ?? null;
  const rc = live?.roll_call;
  const params = new URLSearchParams({ building: buildingId });
  if (fireStart && !ev) params.set("origin", fireStart);
  const href = `/live/view?${params.toString()}`;
  const place = fireLabel ? fireLabel.split(" (")[0] : null;

  return (
    <section className="flex flex-col gap-3.5 border-b border-rule bg-[#14171a] px-5 pb-5 pt-[18px]">
      <h3 className="caps flex items-baseline justify-between gap-3 text-[11px] text-quiet">
        <span className="flex items-center gap-2">
          <span className={`h-1.5 w-1.5 ${ev ? "bg-fire" : "bg-quiet"}`} aria-hidden />
          Live response
          {ev && <span className="text-fire">· {ev.mode} running</span>}
        </span>
        <span className="text-faint">/0.0</span>
      </h3>

      {ev ? (
        <dl className="grid grid-cols-4 gap-2 text-[12.5px]">
          <Stat label="Safe" value={rc?.confirmed_safe} />
          <Stat label="Moving" value={rc?.contacted} />
          <Stat label="Need help" value={rc?.needs_help} fire />
          <Stat label="No reply" value={rc?.unconfirmed} />
        </dl>
      ) : (
        <p className="text-[13px] leading-[19px] text-quiet">
          Declare a drill and the CREAO agents text and call everyone inside with the engine&apos;s
          routes, while the dispatcher watches and approves.
        </p>
      )}

      <a
        href={href}
        className="flex h-[38px] items-center justify-between bg-white px-3.5 text-[14px] text-ink transition-colors hover:bg-rule-light"
      >
        <span className="truncate">
          {ev
            ? `Open live response · T+${formatClock((ev.minute_now ?? 0) * 60)}`
            : place
              ? `Run a drill: fire in ${place}`
              : "Open live response"}
        </span>
        <span aria-hidden>→</span>
      </a>
      {offline && <p className="caps text-[10px] text-dim">Live layer unreachable</p>}
    </section>
  );
}

function Stat({ label, value, fire }: { label: string; value?: number; fire?: boolean }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="caps text-[10px] text-dim">{label}</dt>
      <dd className={`text-[18px] tabular-nums ${fire && value ? "text-fire" : "text-fg"}`}>
        {value ?? "–"}
      </dd>
    </div>
  );
}
