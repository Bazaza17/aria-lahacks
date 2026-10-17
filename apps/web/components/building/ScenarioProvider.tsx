"use client";

import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

import type { SurgeValue } from "./scenario";

type ScenarioCtx = {
  surge: SurgeValue;
  setSurge: (v: SurgeValue) => void;
};

const Ctx = createContext<ScenarioCtx | null>(null);

export function ScenarioProvider({ children }: { children: ReactNode }) {
  const [surge, setSurge] = useState<SurgeValue>(0);

  const value = useMemo(() => ({ surge, setSurge }), [surge]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useScenario(): ScenarioCtx {
  const value = useContext(Ctx);
  if (!value) {
    throw new Error("useScenario must be used within <ScenarioProvider>");
  }
  return value;
}
