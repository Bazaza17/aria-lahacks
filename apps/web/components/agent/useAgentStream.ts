"use client";

import { useCallback, useRef, useState } from "react";

import type { AgentEvent, PreplanReport, ScenarioParams } from "@/lib/types";

const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export type AgentRunMode = "auto" | "cached" | "live";
export type AgentRunSource = "cached" | "live" | null;

export type AgentStream = {
  events: AgentEvent[];
  report: PreplanReport | null;
  running: boolean;
  error: string | null;
  /** What the last (or current) run actually used. */
  source: AgentRunSource;
  run: (
    address: string,
    scenarioParams: ScenarioParams,
    opts?: { buildingId?: string; mode?: AgentRunMode },
  ) => Promise<void>;
};

export function useAgentStream(): AgentStream {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [report, setReport] = useState<PreplanReport | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [source, setSource] = useState<AgentRunSource>(null);
  const abortRef = useRef<AbortController | null>(null);

  const run = useCallback(
    async (
      address: string,
      scenarioParams: ScenarioParams,
      opts: { buildingId?: string; mode?: AgentRunMode } = {},
    ) => {
      setEvents([]);
      setReport(null);
      setError(null);
      setSource(null);
      setRunning(true);
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      const mode: AgentRunMode = opts.mode ?? "auto";
      const buildingId = opts.buildingId;

      try {
        let res: Response | null = null;
        let chosenSource: AgentRunSource = null;

        // Try cached replay first in auto/cached modes
        if (buildingId && (mode === "auto" || mode === "cached")) {
          const replayRes = await fetch(`${API_BASE}/agent/replay/${buildingId}`, {
            method: "POST",
            headers: { Accept: "text/event-stream" },
            signal: controller.signal,
          });
          if (replayRes.ok && replayRes.body) {
            res = replayRes;
            chosenSource = "cached";
          } else if (mode === "cached") {
            throw new Error(`no cached run for this building (HTTP ${replayRes.status})`);
          }
          // auto mode silently falls through to live on 404
        }

        // Live fallback / explicit live mode
        if (!res) {
          res = await fetch(`${API_BASE}/agent/run`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Accept: "text/event-stream",
            },
            body: JSON.stringify({
              address,
              scenario_params: scenarioParams,
              building_id: buildingId,
            }),
            signal: controller.signal,
          });
          chosenSource = "live";
          if (!res.ok || !res.body) {
            throw new Error(`Agent request failed: HTTP ${res.status}`);
          }
        }

        setSource(chosenSource);

        const reader = res.body!.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          let idx: number;
          while ((idx = buffer.indexOf("\n\n")) >= 0) {
            const raw = buffer.slice(0, idx);
            buffer = buffer.slice(idx + 2);
            const ev = parseSseBlock(raw);
            if (!ev) continue;
            setEvents((prev) => [...prev, ev]);
            if (ev.type === "complete") setReport(ev.report);
            if (ev.type === "error") setError(ev.message);
          }
        }
      } catch (e) {
        if (!(e instanceof DOMException && e.name === "AbortError")) {
          setError(e instanceof Error ? e.message : String(e));
        }
      } finally {
        setRunning(false);
      }
    },
    [],
  );

  return { events, report, running, error, source, run };
}

function parseSseBlock(raw: string): AgentEvent | null {
  let type = "";
  const dataLines: string[] = [];
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) {
      type = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }
  if (!type || dataLines.length === 0) return null;
  try {
    const payload = JSON.parse(dataLines.join("\n"));
    return { type, ...payload } as AgentEvent;
  } catch {
    return null;
  }
}
