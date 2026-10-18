"use client";

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import {
  loadFireStarts,
  loadFireTimeline,
  type FireStarts,
  type FireTimeline,
} from "@/lib/scan-fire";

export const FIRE_HORIZON_S = 900;
export const FIRE_STEP_S = 10;
const FIRE_TICK_MS = 100;

type ScenarioCtx = {
  fireTime: number;
  setFireTime: (s: number) => void;
  playing: boolean;
  setPlaying: (p: boolean) => void;
  /** The space the fire starts in; null = the engine default. */
  fireStart: string | null;
  setFireStart: (id: string) => void;
  /** The spaces the engine can start a fire in (null until loaded, or off the venue). */
  fireStarts: FireStarts | null;
  /** The engine's run for the chosen start; the last one stays while a new start runs. */
  fireTimeline: FireTimeline | null;
  fireTimelineBusy: boolean;
  fireTimelineFailed: boolean;
};

const Ctx = createContext<ScenarioCtx | null>(null);

/** The fire clock, start and engine run shared by the scan, the panel and the timeline strip. */
export function ScenarioProvider({
  buildingId,
  children,
}: {
  buildingId: string;
  children: ReactNode;
}) {
  const [fireTime, setFireTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [fireStart, setFireStart] = useState<string | null>(null);
  const [fireStarts, setFireStarts] = useState<FireStarts | null>(null);
  const [fireTimeline, setFireTimeline] = useState<FireTimeline | null>(null);
  const [fireTimelineBusy, setFireTimelineBusy] = useState(false);
  const [fireTimelineFailed, setFireTimelineFailed] = useState(false);

  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => {
      setFireTime((t) => {
        const next = Math.min(FIRE_HORIZON_S, t + FIRE_STEP_S);
        if (next >= FIRE_HORIZON_S) setPlaying(false);
        return next;
      });
    }, FIRE_TICK_MS);
    return () => window.clearInterval(id);
  }, [playing]);

  useEffect(() => {
    let cancelled = false;
    void loadFireStarts(buildingId).then((s) => {
      if (!cancelled) setFireStarts(s);
    });
    return () => {
      cancelled = true;
    };
  }, [buildingId]);

  // The engine's run for the chosen start (the API's default until one is picked).
  useEffect(() => {
    let cancelled = false;
    setFireTimelineBusy(true);
    void loadFireTimeline(buildingId, fireStart ?? undefined).then((t) => {
      if (cancelled) return;
      if (t) setFireTimeline(t);
      setFireTimelineFailed(!t);
      setFireTimelineBusy(false);
    });
    return () => {
      cancelled = true;
    };
  }, [buildingId, fireStart]);

  const value = useMemo(
    () => ({
      fireTime,
      setFireTime,
      playing,
      setPlaying,
      fireStart,
      setFireStart,
      fireStarts,
      fireTimeline,
      fireTimelineBusy,
      fireTimelineFailed,
    }),
    [fireTime, playing, fireStart, fireStarts, fireTimeline, fireTimelineBusy, fireTimelineFailed],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useScenario(): ScenarioCtx {
  const value = useContext(Ctx);
  if (!value) {
    throw new Error("useScenario must be used within <ScenarioProvider>");
  }
  return value;
}
