import type { RiskScore } from "@/lib/types";

export const SURGE_STOPS: ReadonlyArray<{ value: 0 | 1 | 3 | 6 | 10; label: string }> = [
  { value: 0, label: "DRY" },
  { value: 1, label: "1FT" },
  { value: 3, label: "3FT" },
  { value: 6, label: "6FT" },
  { value: 10, label: "10FT" },
];

export type SurgeValue = (typeof SURGE_STOPS)[number]["value"];

export function surgeRisk(surge: SurgeValue): RiskScore {
  if (surge === 0) return "LOW";
  if (surge === 1) return "MODERATE";
  if (surge === 10) return "SEVERE";
  return "HIGH";
}

export function scenarioLabel(surge: SurgeValue): string {
  if (surge >= 10) return "CATASTROPHIC FLOODING — RED TAG ZONE";
  if (surge >= 6) return "MAJOR SURGE — STORM CONDITIONS";
  if (surge >= 3) return "MODERATE SURGE — STORM CONDITIONS";
  if (surge >= 1) return "MINOR FLOODING — STORM CONDITIONS";
  return "BASELINE — CLEAR CONDITIONS";
}
