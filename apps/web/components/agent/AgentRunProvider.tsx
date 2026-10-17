"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import type { AgentEvent, PreplanReport, ScenarioParams } from "@/lib/types";

import type { AgentRunMode, AgentRunSource } from "./useAgentStream";
import { useAgentStream } from "./useAgentStream";

const DEFAULT_SCENARIO: ScenarioParams = {
  wind_mph: 130,
  surge_ft: 6,
  rainfall_in: 4,
};

type AgentRunCtx = {
  events: AgentEvent[];
  report: PreplanReport | null;
  running: boolean;
  error: string | null;
  elapsedMs: number | null;
  source: AgentRunSource;
  mode: AgentRunMode;
  setMode: (m: AgentRunMode) => void;
  run: () => void;
  address: string;
  buildingId: string | null;
};

const Ctx = createContext<AgentRunCtx | null>(null);

export function useAgentRun(): AgentRunCtx {
  const value = useContext(Ctx);
  if (!value) throw new Error("useAgentRun must be used within <AgentRunProvider>");
  return value;
}

export function AgentRunProvider({
  address,
  buildingId = null,
  children,
}: {
  address: string;
  buildingId?: string | null;
  children: ReactNode;
}) {
  const stream = useAgentStream();
  const [elapsedMs, setElapsedMs] = useState<number | null>(null);
  const [mode, setMode] = useState<AgentRunMode>("auto");
  const startedAtRef = useRef<number | null>(null);

  useEffect(() => {
    if (stream.running && startedAtRef.current === null) {
      startedAtRef.current = Date.now();
      setElapsedMs(null);
    } else if (!stream.running && startedAtRef.current !== null) {
      setElapsedMs(Date.now() - startedAtRef.current);
      startedAtRef.current = null;
    }
  }, [stream.running]);

  const value = useMemo<AgentRunCtx>(
    () => ({
      events: stream.events,
      report: stream.report,
      running: stream.running,
      error: stream.error,
      source: stream.source,
      elapsedMs,
      address,
      buildingId,
      mode,
      setMode,
      run: () => {
        void stream.run(address, DEFAULT_SCENARIO, {
          buildingId: buildingId ?? undefined,
          mode,
        });
      },
    }),
    [
      stream.events,
      stream.report,
      stream.running,
      stream.error,
      stream.source,
      stream.run,
      elapsedMs,
      address,
      buildingId,
      mode,
    ],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
