import type { HazardAnalysis, PreplanReport } from "@/lib/types";

export type ActionPriority = "SEVERE" | "HIGH" | "MODERATE";

export type ActionItem = {
  id: string;
  label: string;
  sublabel: string;
  priority: ActionPriority;
};

const PRIORITY_ORDER: Record<ActionPriority, number> = {
  SEVERE: 0,
  HIGH: 1,
  MODERATE: 2,
};

/** Derive 5–7 imperative dispatch actions from the agent's preplan. */
export function generateActions(report: PreplanReport): ActionItem[] {
  const out: ActionItem[] = [];

  // Surge zone → evac order
  const surge = report.context.surge_zone;
  if (surge) {
    const zone = extractZone(surge);
    out.push({
      id: `evac-${zone}`,
      label: `ISSUE MANDATORY EVAC ORDER · ${zone}`,
      sublabel: "Notify county OEM · broadcast WEA + reverse-911",
      priority: "SEVERE",
    });
    out.push({
      id: "stage-rescue",
      label: "STAGE HIGH-CLEARANCE RESCUE VEHICLES",
      sublabel: "Pre-position swift-water + brush trucks upwind",
      priority: "HIGH",
    });
  }

  // Flood zone AE/VE → sandbags
  const flood = report.context.flood_zone;
  if (/AE|VE|AO/i.test(flood)) {
    out.push({
      id: "sandbags",
      label: "PRE-POSITION SANDBAGS AT GROUND ENTRY",
      sublabel: `Flood zone ${flood.split(" ")[0]} · BFE breach likely under scenario`,
      priority: "MODERATE",
    });
  }

  // Per-hazard vulnerable features → mapped actions (skip LOW/MODERATE hazards)
  pushFeatureActions(out, "wind", report.hazards.wind);
  pushFeatureActions(out, "surge", report.hazards.surge);
  pushFeatureActions(out, "flood", report.hazards.flood);

  // Nearby assets
  const hosp = report.context.nearest_hospital;
  if (hosp?.name) {
    out.push({
      id: `hosp-${hosp.name}`,
      label: `COORDINATE WITH ${shortenFacility(hosp.name)} · ${hosp.distance_mi}MI`,
      sublabel: "Confirm trauma capacity + helo LZ availability",
      priority: "MODERATE",
    });
  }
  const shelter = report.context.nearest_shelter;
  if (shelter?.name) {
    out.push({
      id: `shelter-${shelter.name}`,
      label: `OPEN SHELTER · ${shortenFacility(shelter.name)} · ${shelter.distance_mi}MI`,
      sublabel: "Coordinate Red Cross staffing + transport",
      priority: "HIGH",
    });
  }

  // De-duplicate, sort by priority, cap at 7
  const seen = new Set<string>();
  const unique = out.filter((a) => {
    if (seen.has(a.label)) return false;
    seen.add(a.label);
    return true;
  });
  unique.sort((a, b) => PRIORITY_ORDER[a.priority] - PRIORITY_ORDER[b.priority]);
  const trimmed = unique.slice(0, 7);

  // Pad with neutral fallbacks if we have fewer than 5
  const fallbacks: ActionItem[] = [
    {
      id: "standby",
      label: "STANDBY · MONITOR CONDITIONS",
      sublabel: "Watch NHC advisories + Miami-Dade EOC updates",
      priority: "MODERATE",
    },
    {
      id: "comms",
      label: "MAINTAIN COMMS WITH MIAMI-DADE FIRE RESCUE",
      sublabel: "Tactical channel 7 · 5-minute check-ins",
      priority: "MODERATE",
    },
  ];
  for (const f of fallbacks) {
    if (trimmed.length >= 5) break;
    if (!seen.has(f.label)) {
      seen.add(f.label);
      trimmed.push(f);
    }
  }

  return trimmed;
}

function pushFeatureActions(
  out: ActionItem[],
  hazard: "wind" | "surge" | "flood",
  ha: HazardAnalysis,
): void {
  if (ha.risk_score !== "SEVERE" && ha.risk_score !== "HIGH") return;
  const prio: ActionPriority = ha.risk_score === "SEVERE" ? "SEVERE" : "HIGH";
  for (const feature of ha.vulnerable_features.slice(0, 3)) {
    const action = featureToAction(feature, hazard, prio);
    if (action) out.push(action);
  }
}

function featureToAction(
  feature: string,
  hazard: string,
  priority: ActionPriority,
): ActionItem | null {
  const f = feature.toLowerCase();
  if (/glass|glaz|curtain wall|window/.test(f)) {
    return {
      id: `glass-${hazard}`,
      label: "BOARD UP GROUND-FLOOR GLAZING",
      sublabel: "Plywood + impact film · prioritize south & east facades",
      priority,
    };
  }
  if (/hvac|rooftop|condenser|mechanical/.test(f)) {
    return {
      id: `hvac-${hazard}`,
      label: "SECURE OR REMOVE ROOFTOP HVAC",
      sublabel: "Anchor unanchored units · projectile risk above 110 mph",
      priority,
    };
  }
  if (/elevator|elev/.test(f)) {
    return {
      id: `elev-${hazard}`,
      label: "LOCK ELEVATORS · STAIR-ONLY EGRESS",
      sublabel: "Park cars at level 2 · seal pit + shaft penetrations",
      priority,
    };
  }
  if (/electric|switchgear|transformer|vault/.test(f)) {
    return {
      id: `elec-${hazard}`,
      label: "PLAN ELECTRICAL SHUTDOWN AT GRADE",
      sublabel: "Coordinate FPL · isolate ground-level vaults",
      priority,
    };
  }
  if (/stair/.test(f)) {
    return {
      id: `stair-${hazard}`,
      label: "INSPECT STAIRWELL INTEGRITY",
      sublabel: "Verify shelter-in-place route + emergency lighting",
      priority,
    };
  }
  if (/ground floor|ground-floor|occup|evac/.test(f)) {
    return {
      id: `evac-floor-${hazard}`,
      label: "EVACUATE GROUND FLOOR TO UPPER FLOORS",
      sublabel: "Move ambulatory occupants to floors 3+",
      priority,
    };
  }
  return null;
}

function extractZone(zoneText: string): string {
  // "B (Cat 3+ evacuation, priority 2)" → "ZONE B"
  const m = zoneText.match(/\b([A-E])\b/);
  return m ? `ZONE ${m[1]}` : "EVAC ZONE";
}

function shortenFacility(name: string): string {
  return name
    .toUpperCase()
    .replace(/MEMORIAL HOSPITAL/g, "MEMORIAL")
    .replace(/HOSPITAL/g, "")
    .replace(/HIGH SCHOOL SHELTER/g, "SR HIGH")
    .replace(/HIGH SCHOOL/g, "SR HIGH")
    .replace(/SHELTER/g, "")
    .replace(/\s+/g, " ")
    .trim();
}
