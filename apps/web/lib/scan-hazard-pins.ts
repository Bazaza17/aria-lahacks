import type { PreplanReport, RiskScore } from "@/lib/types";

import { anchorToWorld, type NormalizedAnchor } from "./scan-coords";

export type HazardKind = "wind" | "surge" | "flood";
export type HazardFilter = "all" | HazardKind;

export type { NormalizedAnchor };
export { anchorToWorld };

export type ScanHazardPin = {
  id: string;
  hazard: HazardKind;
  label: string;
  severity: RiskScore;
  anchorDescription: string;
  anchor: NormalizedAnchor;
};

const BUILDING_A_ID = "014b39a9-09b8-432b-9b62-363e06383d1f";
const BUILDING_B_ID = "870d979d-6eaf-4d7f-894a-8ca34e527237";
const THE_DOCK_ID = "e5a3fddc-e22c-431c-a5d3-ee29ef8604d1";

/** Building-specific anchor presets (tuned to each LiDAR capture orientation). */
const BUILDING_SLOTS: Record<string, Record<string, NormalizedAnchor>> = {
  [THE_DOCK_ID]: {
    roof: { nx: 0.35, ny: 0.9, nz: 0.35 },
    hvac: { nx: 0.5, ny: 0.85, nz: 0.45 },
    ground_egress: { nx: 0.45, ny: 0.06, nz: 0.12 },
    glass_facade: { nx: 0.45, ny: 0.4, nz: 0.1 },
    interior: { nx: 0.35, ny: 0.4, nz: 0.4 },
    open_court: { nx: 0.3, ny: 0.06, nz: 0.9 },
  },
  [BUILDING_A_ID]: {
    roof: { nx: 0.52, ny: 0.94, nz: 0.48 },
    hvac: { nx: 0.64, ny: 0.9, nz: 0.4 },
    ground_egress: { nx: 0.46, ny: 0.06, nz: 0.74 },
    glass_facade: { nx: 0.84, ny: 0.38, nz: 0.58 },
    interior: { nx: 0.5, ny: 0.52, nz: 0.5 },
    open_court: { nx: 0.28, ny: 0.1, nz: 0.22 },
  },
  [BUILDING_B_ID]: {
    roof: { nx: 0.5, ny: 0.93, nz: 0.42 },
    hvac: { nx: 0.58, ny: 0.88, nz: 0.35 },
    ground_egress: { nx: 0.44, ny: 0.05, nz: 0.68 },
    glass_facade: { nx: 0.78, ny: 0.4, nz: 0.62 },
    interior: { nx: 0.5, ny: 0.48, nz: 0.52 },
    open_court: { nx: 0.22, ny: 0.12, nz: 0.78 },
  },
};

const DEFAULT_DISTRIBUTED: NormalizedAnchor[] = [
  { nx: 0.5, ny: 0.92, nz: 0.5 },
  { nx: 0.18, ny: 0.14, nz: 0.72 },
  { nx: 0.82, ny: 0.22, nz: 0.38 },
  { nx: 0.35, ny: 0.55, nz: 0.18 },
  { nx: 0.68, ny: 0.62, nz: 0.84 },
  { nx: 0.5, ny: 0.35, nz: 0.5 },
  { nx: 0.12, ny: 0.48, nz: 0.5 },
  { nx: 0.88, ny: 0.5, nz: 0.5 },
];

function resolveAnchor(text: string, buildingId: string, index: number): NormalizedAnchor {
  const slots = BUILDING_SLOTS[buildingId];
  const t = text.toLowerCase();

  if (/roof|parapet|mechanical|hvac|unit|canopy|ridge/.test(t)) {
    return slots?.hvac && /hvac|mechanical|unit/.test(t)
      ? slots.hvac
      : (slots?.roof ?? DEFAULT_DISTRIBUTED[0]);
  }
  if (/ground|egress|entry|door|threshold|grade|floor|ingress|exit/.test(t)) {
    return slots?.ground_egress ?? DEFAULT_DISTRIBUTED[1];
  }
  if (/glass|facade|window|curtain|storefront|glazing/.test(t)) {
    return slots?.glass_facade ?? DEFAULT_DISTRIBUTED[2];
  }
  if (/court|playground|basketball|assembly|exterior open|outside/.test(t)) {
    return slots?.open_court ?? DEFAULT_DISTRIBUTED[3];
  }
  if (/interior|room|hall|auditorium|classroom|ceiling|span|concourse/.test(t)) {
    return slots?.interior ?? DEFAULT_DISTRIBUTED[4];
  }
  if (/west/.test(t)) return { nx: 0.06, ny: 0.52, nz: 0.5 };
  if (/east/.test(t)) return { nx: 0.94, ny: 0.52, nz: 0.5 };
  if (/north/.test(t)) return { nx: 0.5, ny: 0.5, nz: 0.06 };
  if (/south/.test(t)) return { nx: 0.5, ny: 0.5, nz: 0.94 };

  return DEFAULT_DISTRIBUTED[index % DEFAULT_DISTRIBUTED.length];
}

export function pinsFromReport(report: PreplanReport, buildingId: string): ScanHazardPin[] {
  const hazards: HazardKind[] = ["wind", "surge", "flood"];
  const pins: ScanHazardPin[] = [];
  let globalIndex = 0;

  for (const hazard of hazards) {
    const block = report.hazards[hazard];
    block.annotations_3d.forEach((a, i) => {
      const hint = `${a.anchor_description} ${a.label}`;
      pins.push({
        id: `${hazard}-${i}-${globalIndex}`,
        hazard,
        label: a.label,
        severity: a.severity,
        anchorDescription: a.anchor_description,
        anchor: resolveAnchor(hint, buildingId, globalIndex),
      });
      globalIndex += 1;
    });
  }

  return pins;
}

export function filterPins(pins: ScanHazardPin[], filter: HazardFilter): ScanHazardPin[] {
  if (filter === "all") return pins;
  return pins.filter((p) => p.hazard === filter);
}

export function hazardPinCounts(pins: ScanHazardPin[]): Record<HazardFilter, number> {
  return {
    all: pins.length,
    wind: pins.filter((p) => p.hazard === "wind").length,
    surge: pins.filter((p) => p.hazard === "surge").length,
    flood: pins.filter((p) => p.hazard === "flood").length,
  };
}

const SEVERITY_COLOR: Record<RiskScore, string> = {
  LOW: "#d1d5db",
  MODERATE: "#fbbf24",
  HIGH: "#ff6b00",
  SEVERE: "#ef4444",
};

export function createPinElement(
  pin: ScanHazardPin,
  opts: { hidden: boolean; animate: boolean },
): HTMLDivElement {
  const root = document.createElement("div");
  root.className = "scan-hazard-pin";
  root.dataset.severity = pin.severity;
  root.dataset.hazard = pin.hazard;
  if (opts.hidden) root.classList.add("scan-hazard-pin--hidden");
  if (opts.animate) root.classList.add("scan-hazard-pin--enter");

  const color = SEVERITY_COLOR[pin.severity];
  const label = pin.label.length > 34 ? `${pin.label.slice(0, 33)}…` : pin.label;

  root.innerHTML = `
    <div class="scan-hazard-pin__stack">
      <div class="scan-hazard-pin__label" style="border-color: ${color}40">
        <span class="scan-hazard-pin__hazard" style="color: ${color}">${pin.hazard.toUpperCase()}</span>
        <span class="scan-hazard-pin__text" title="${escapeAttr(pin.label)}">${escapeAttr(label)}</span>
      </div>
      <div class="scan-hazard-pin__stem" style="background: linear-gradient(to bottom, ${color}, transparent)"></div>
      <div class="scan-hazard-pin__dot" style="background: ${color}; box-shadow: 0 0 10px ${color}99"></div>
    </div>
  `;

  return root;
}

function escapeAttr(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
