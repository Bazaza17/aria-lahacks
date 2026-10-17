"use client";

import { useEffect, useRef } from "react";

import { BRAND, BRAND_WORDMARK } from "@/lib/brand";
import type { AgentEvent } from "@/lib/types";

import { useAgentRun } from "./AgentRunProvider";

export function AgentLog() {
  const { events, running, elapsedMs } = useAgentRun();
  const scrollerRef = useRef<HTMLDivElement>(null);
  const hasCompleted = events.some((e) => e.type === "complete");
  const iterations = events.filter((e) => e.type === "thinking").length;
  const toolsCalled = events.filter((e) => e.type === "tool_call").length;

  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [events.length]);

  return (
    <div className="flex h-full min-h-0 flex-col bg-[#0a0a0a]">
      <div className="flex items-center justify-between gap-3 border-b border-white/[0.08] px-5 py-3 font-mono text-[10px] tracking-[0.3em]">
        <div className="flex items-center gap-2">
          <span className="h-1 w-1 bg-[#ff6b00]" />
          <span className="text-white/70">AGENT · {BRAND_WORDMARK}</span>
        </div>

        {running && (
          <span className="inline-flex items-center gap-2 text-[#ff6b00]">
            <span className="relative inline-flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#ff6b00] opacity-60" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-[#ff6b00]" />
            </span>
            RUNNING
          </span>
        )}
      </div>

      <div
        ref={scrollerRef}
        className="flex-1 overflow-y-auto px-4 py-3 font-mono text-[12px] leading-relaxed"
      >
        {events.length === 0 ? (
          <div className="text-white/30">{`> ${BRAND.name.toLowerCase()}.agent ready`}</div>
        ) : (
          <div className="flex flex-col gap-1">
            {events.map((ev, i) => (
              <EventLine key={i} ev={ev} />
            ))}
          </div>
        )}
      </div>

      {hasCompleted && !running && (
        <div className="aria-fade-in border-t border-white/[0.08] px-4 py-2.5 font-mono text-[10px] tracking-[0.18em] text-[#ff6b00]">
          ✓ AGENT COMPLETE · {toolsCalled} TOOL CALL
          {toolsCalled === 1 ? "" : "S"} · {iterations} ITERATION
          {iterations === 1 ? "" : "S"}
          {typeof elapsedMs === "number" ? ` · ${Math.max(1, Math.round(elapsedMs / 1000))}s` : ""}
        </div>
      )}
    </div>
  );
}

function EventLine({ ev }: { ev: AgentEvent }) {
  const fade = "aria-fade-in";
  switch (ev.type) {
    case "thinking":
      return (
        <div className={`${fade} mt-3 flex items-center gap-2 text-white/30`}>
          <span>──</span>
          <span className="tracking-wider">iteration {ev.iteration}</span>
          <span className="h-px flex-1 bg-white/[0.08]" />
        </div>
      );
    case "reasoning": {
      // Strip the ```json {...} ``` report dump — the right column renders
      // it as structured cards, the log shouldn't double-print it.
      const text = stripReportBlock(ev.text);
      if (!text) return null;
      return <div className={`${fade} whitespace-pre-wrap pl-2 text-white/85`}>{text}</div>;
    }
    case "tool_call":
      return (
        <div className={fade}>
          <div className="text-[#ff6b00]">→ {ev.name}</div>
          <div className="pl-4 text-white/40">{formatToolInput(ev.input)}</div>
        </div>
      );
    case "tool_result":
      return (
        <div className={`${fade} pl-4 text-white/40`}>✓ {summarizeResult(ev.name, ev.result)}</div>
      );
    case "complete":
      return (
        <div className={`${fade} mt-3 flex flex-col gap-1 font-medium text-[#ff6b00]`}>
          <span className="h-px w-full bg-[#ff6b00]/40" />
          <span className="tracking-[0.2em]">✓ PRE-INCIDENT PLAN READY</span>
        </div>
      );
    case "error":
      return <div className={`${fade} text-red-400`}>✗ ERROR: {ev.message}</div>;
  }
}

function formatToolInput(input: Record<string, unknown>): string {
  const entries = Object.entries(input);
  if (entries.length === 0) return "—";
  return entries
    .map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join(" · ");
}

function summarizeResult(name: string, result: unknown): string {
  if (Array.isArray(result)) {
    if (name === "fetch_street_view") return "image fetched";
    if (name === "fetch_satellite") return "satellite fetched";
    return `${result.length} block${result.length === 1 ? "" : "s"}`;
  }
  if (result && typeof result === "object") {
    const r = result as Record<string, unknown>;
    if (name === "lookup_flood_zone") {
      return `zone: ${r.zone} · bfe: ${r.bfe_ft}ft`;
    }
    if (name === "lookup_surge_zone") {
      return `zone: ${r.zone} · priority: ${r.evacuation_order_priority}`;
    }
    if (name === "lookup_nearby" && Array.isArray(r.results)) {
      const arr = r.results as Array<{ name: string; distance_mi: number }>;
      if (arr.length === 0) return "no results";
      const first = arr[0];
      const more = arr.length > 1 ? ` (+${arr.length - 1})` : "";
      return `${first.name} · ${first.distance_mi}mi${more}`;
    }
    return truncate(JSON.stringify(r), 80);
  }
  return truncate(String(result), 80);
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

function stripReportBlock(text: string): string {
  // Removes fenced ```json {...} ``` blocks (the final report dump) so the
  // log shows only Claude's prose. If the entire reasoning event is the
  // fence, returns an empty string and the line is skipped.
  return text
    .replace(/```json[\s\S]*?```/g, "")
    .replace(/\s+\n/g, "\n")
    .trim();
}
