"use client";

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

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
};

const Ctx = createContext<ScenarioCtx | null>(null);

/** The fire clock shared by the scan, the size-up panel and the timeline strip. */
export function ScenarioProvider({ children }: { children: ReactNode }) {
  const [fireTime, setFireTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [fireStart, setFireStart] = useState<string | null>(null);

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

  const value = useMemo(
    () => ({ fireTime, setFireTime, playing, setPlaying, fireStart, setFireStart }),
    [fireTime, playing, fireStart],
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
