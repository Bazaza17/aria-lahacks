"use client";

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import type { SurgeValue } from "./scenario";

export const FIRE_HORIZON_S = 900;
export const FIRE_STEP_S = 10;
const FIRE_TICK_MS = 100;

type ScenarioCtx = {
  surge: SurgeValue;
  setSurge: (v: SurgeValue) => void;
  fireTime: number;
  setFireTime: (s: number) => void;
  playing: boolean;
  setPlaying: (p: boolean) => void;
};

const Ctx = createContext<ScenarioCtx | null>(null);

export function ScenarioProvider({ children }: { children: ReactNode }) {
  // Surge stays at 0: the report and agent still read it.
  const [surge, setSurge] = useState<SurgeValue>(0);
  const [fireTime, setFireTime] = useState(0);
  const [playing, setPlaying] = useState(false);

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
    () => ({ surge, setSurge, fireTime, setFireTime, playing, setPlaying }),
    [surge, fireTime, playing],
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
