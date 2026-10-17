"use client";

import { useAgentRun } from "./AgentRunProvider";
import { AgentLog } from "./AgentLog";

// Thin wrapper kept so we can later add per-pane chrome (e.g. clear/copy
// controls). Right now it's just the log + an inline error line.
export function AgentLogPane() {
  const { error } = useAgentRun();

  return (
    <div className="flex h-full min-h-0 flex-col bg-[#0a0a0a]">
      <div className="min-h-0 flex-1">
        <AgentLog />
      </div>
      {error ? (
        <div className="border-t border-red-500/20 bg-red-500/5 px-4 py-2 font-mono text-[10px] tracking-[0.18em] text-red-400">
          ✗ {error}
        </div>
      ) : null}
    </div>
  );
}
