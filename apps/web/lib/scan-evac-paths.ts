import { anchorToWorld, floorAnchor, type MeshSize, type NormalizedAnchor } from "./scan-coords";

/** Matches SURGE_STOPS in components/building/scenario.ts */
export type SurgeFeet = 0 | 1 | 3 | 6 | 10;

export type EvacExit = {
  id: string;
  label: string;
  viewpointId: string;
  anchor: NormalizedAnchor;
  /** null = assembly / remains designated rally point */
  blockedAtSurgeFt: SurgeFeet | null;
  /** Audit trail — walkthrough annotation or capture note */
  source: string;
};

export type EvacRoute = {
  id: string;
  label: string;
  waypointViewpoints: string[];
  targetExitId: string;
  source: "walkthrough_navigation";
};

export type ResolvedRoute = {
  id: string;
  label: string;
  points: Array<{ x: number; y: number; z: number }>;
  status: "open" | "blocked" | "partial";
  targetExitId: string;
  /** Index in points where the path becomes impassable (partial routes). */
  blockedFromIndex: number | null;
};

export type ResolvedExit = EvacExit & {
  blocked: boolean;
};

export type EvacPlan = {
  buildingId: string;
  calibrationSource: string;
  routes: ResolvedRoute[];
  exits: ResolvedExit[];
  assemblyExitId: string;
};

const BUILDING_A_ID = "014b39a9-09b8-432b-9b62-363e06383d1f";
const BUILDING_B_ID = "870d979d-6eaf-4d7f-894a-8ca34e527237";
const THE_DOCK_ID = "e5a3fddc-e22c-431c-a5d3-ee29ef8604d1";

/**
 * Viewpoint → mesh anchors calibrated against LiDAR walkthrough capture order.
 * Viewpoint ids come from the original walkthrough capture's navigation graph.
 *
 * The Dock is a single-story open bay: long axis is Z (~38 m depth), width is
 * X (~26 m), floor at the mesh bottom (ny ≈ 0.05). nz ≈ 0.85 is the street-side
 * bay door; nz ≈ 0.08 is the far end / outdoor assembly.
 */
const VIEWPOINT_ANCHORS: Record<string, Record<string, NormalizedAnchor>> = {
  // Calibrated to the scan's main floor footprint (nx 0.08–0.6, nz 0.1–0.6).
  // Approximate until the walkthrough photos pin exact door positions.
  [THE_DOCK_ID]: {
    bay_entrance: floorAnchor(0.45, 0.12, 0.05),
    bay_main: floorAnchor(0.4, 0.26, 0.05),
    bay_center: floorAnchor(0.35, 0.4, 0.05),
    bay_rear: floorAnchor(0.3, 0.54, 0.05),
    side_north: floorAnchor(0.12, 0.42, 0.05),
    dock_threshold: floorAnchor(0.28, 0.66, 0.05),
    street_assembly: floorAnchor(0.3, 0.9, 0.04),
  },
  [BUILDING_A_ID]: {
    hall_start: floorAnchor(0.46, 0.76, 0.09),
    hall_concourse: floorAnchor(0.5, 0.58, 0.09),
    hall_corner: floorAnchor(0.4, 0.42, 0.09),
    exit_outside: floorAnchor(0.44, 0.26, 0.06),
    yard_open: floorAnchor(0.32, 0.16, 0.05),
    court_play: floorAnchor(0.26, 0.06, 0.04),
  },
  [BUILDING_B_ID]: {
    exterior_approach: floorAnchor(0.42, 0.74, 0.05),
    entry_door_a: floorAnchor(0.44, 0.6, 0.06),
    entry_door_b: floorAnchor(0.5, 0.5, 0.07),
    interior_main: floorAnchor(0.48, 0.38, 0.08),
    interior_open: floorAnchor(0.46, 0.28, 0.08),
    interior_rear: floorAnchor(0.54, 0.18, 0.08),
    interior_workstation: floorAnchor(0.58, 0.1, 0.09),
  },
};

const EVAC_DATA: Record<
  string,
  {
    calibrationSource: string;
    assemblyExitId: string;
    exits: EvacExit[];
    routes: EvacRoute[];
  }
> = {
  [THE_DOCK_ID]: {
    calibrationSource: "LiDAR scan · The Dock open-bay capture · single-story 26×38 m",
    assemblyExitId: "exit_assembly_street",
    exits: [
      {
        id: "exit_main_bay",
        label: "MAIN BAY DOOR",
        viewpointId: "bay_entrance",
        anchor: floorAnchor(0.45, 0.12, 0.05),
        blockedAtSurgeFt: 1,
        source: "annotation: GRADE-LEVEL ROLL-UP · SURGE ENTRY",
      },
      {
        id: "exit_loading_dock",
        label: "LOADING DOCK",
        viewpointId: "bay_main",
        anchor: floorAnchor(0.58, 0.3, 0.05),
        blockedAtSurgeFt: 3,
        source: "annotation: SIDE LOADING DOCK · SECONDARY EGRESS",
      },
      {
        id: "exit_side_north",
        label: "NORTH SIDE EGRESS",
        viewpointId: "side_north",
        anchor: floorAnchor(0.1, 0.42, 0.05),
        blockedAtSurgeFt: 6,
        source: "annotation: PERSONNEL DOOR · RAISED THRESHOLD",
      },
      {
        id: "exit_dock_threshold",
        label: "DOCK THRESHOLD",
        viewpointId: "dock_threshold",
        anchor: floorAnchor(0.28, 0.66, 0.05),
        blockedAtSurgeFt: 3,
        source: "annotation: REAR THRESHOLD · LOW GRADE",
      },
      {
        id: "exit_assembly_street",
        label: "ASSEMBLY · STREET",
        viewpointId: "street_assembly",
        anchor: floorAnchor(0.3, 0.9, 0.04),
        blockedAtSurgeFt: null,
        source: "annotation: NW 26TH ST · EVAC ASSEMBLY POINT",
      },
    ],
    routes: [
      {
        id: "primary_to_street",
        label: "PRIMARY · BAY TO STREET",
        waypointViewpoints: [
          "bay_entrance",
          "bay_main",
          "bay_center",
          "bay_rear",
          "dock_threshold",
          "street_assembly",
        ],
        targetExitId: "exit_assembly_street",
        source: "walkthrough_navigation",
      },
      {
        id: "alternate_side",
        label: "ALTERNATE · NORTH SIDE EGRESS",
        waypointViewpoints: ["bay_center", "side_north"],
        targetExitId: "exit_side_north",
        source: "walkthrough_navigation",
      },
      {
        id: "staging_dock",
        label: "STAGING · LOADING DOCK",
        waypointViewpoints: ["bay_entrance", "bay_main"],
        targetExitId: "exit_loading_dock",
        source: "walkthrough_navigation",
      },
    ],
  },
  [BUILDING_A_ID]: {
    calibrationSource: "LiDAR walkthrough graph · Miami Senior High hall capture · 6 viewpoints",
    assemblyExitId: "exit_assembly_court",
    exits: [
      {
        id: "exit_hall_ingress",
        label: "HALL INGRESS",
        viewpointId: "hall_start",
        anchor: floorAnchor(0.46, 0.76, 0.06),
        blockedAtSurgeFt: 3,
        source: "annotation: GROUND-LEVEL EGRESS · SURGE ENTRY",
      },
      {
        id: "exit_auditorium",
        label: "AUDITORIUM EXIT",
        viewpointId: "hall_concourse",
        anchor: floorAnchor(0.5, 0.58, 0.08),
        blockedAtSurgeFt: 3,
        source: "annotation: AUDITORIUM EXIT · PRIMARY EVAC",
      },
      {
        id: "exit_grade_transition",
        label: "GRADE TRANSITION",
        viewpointId: "exit_outside",
        anchor: floorAnchor(0.44, 0.26, 0.05),
        blockedAtSurgeFt: 1,
        source: "annotation: GRADE-LEVEL THRESHOLD · SURGE INTRUSION",
      },
      {
        id: "exit_yard",
        label: "YARD EGRESS",
        viewpointId: "yard_open",
        anchor: floorAnchor(0.32, 0.16, 0.04),
        blockedAtSurgeFt: 6,
        source: "annotation: LOW-LYING DRAINAGE · STANDING WATER",
      },
      {
        id: "exit_assembly_court",
        label: "ASSEMBLY · COURT",
        viewpointId: "court_play",
        anchor: floorAnchor(0.26, 0.06, 0.03),
        blockedAtSurgeFt: null,
        source: "annotation: OPEN COURT · EVAC ASSEMBLY POINT",
      },
    ],
    routes: [
      {
        id: "primary_to_assembly",
        label: "PRIMARY · INTERIOR TO COURT",
        waypointViewpoints: [
          "hall_start",
          "hall_concourse",
          "hall_corner",
          "exit_outside",
          "yard_open",
          "court_play",
        ],
        targetExitId: "exit_assembly_court",
        source: "walkthrough_navigation",
      },
      {
        id: "interior_shelter",
        label: "ALTERNATE · INTERIOR SHELTER",
        waypointViewpoints: ["hall_start", "hall_concourse", "hall_corner"],
        targetExitId: "exit_auditorium",
        source: "walkthrough_navigation",
      },
    ],
  },
  [BUILDING_B_ID]: {
    calibrationSource: "LiDAR walkthrough graph · Innovation Center capture · 7 viewpoints",
    assemblyExitId: "exit_side_egress",
    exits: [
      {
        id: "exit_main_facade",
        label: "MAIN FACADE",
        viewpointId: "exterior_approach",
        anchor: floorAnchor(0.42, 0.74, 0.04),
        blockedAtSurgeFt: 1,
        source: "annotation: GRADE-LEVEL ENTRY · SURGE EXPOSURE",
      },
      {
        id: "exit_glass_vestibule",
        label: "GLASS VESTIBULE",
        viewpointId: "entry_door_a",
        anchor: floorAnchor(0.44, 0.6, 0.05),
        blockedAtSurgeFt: 1,
        source: "annotation: GLASS DOOR · IMPACT NOT RATED",
      },
      {
        id: "exit_side_egress",
        label: "SIDE EGRESS",
        viewpointId: "entry_door_b",
        anchor: floorAnchor(0.5, 0.5, 0.06),
        blockedAtSurgeFt: 3,
        source: "annotation: SECONDARY EGRESS · UNOBSTRUCTED",
      },
      {
        id: "exit_rear",
        label: "REAR WORKSTATION",
        viewpointId: "interior_workstation",
        anchor: floorAnchor(0.58, 0.1, 0.08),
        blockedAtSurgeFt: 6,
        source: "walkthrough: interior rear capture",
      },
    ],
    routes: [
      {
        id: "interior_to_side",
        label: "PRIMARY · INTERIOR TO SIDE DOOR",
        waypointViewpoints: ["interior_main", "interior_open", "interior_rear", "entry_door_b"],
        targetExitId: "exit_side_egress",
        source: "walkthrough_navigation",
      },
      {
        id: "interior_shelter_in_place",
        label: "ALTERNATE · SHELTER IN PLACE",
        waypointViewpoints: ["interior_main", "interior_open"],
        targetExitId: "exit_rear",
        source: "walkthrough_navigation",
      },
      {
        id: "front_approach",
        label: "STAGING · FRONT APPROACH",
        waypointViewpoints: ["exterior_approach", "entry_door_a"],
        targetExitId: "exit_glass_vestibule",
        source: "walkthrough_navigation",
      },
    ],
  },
};

export function hasEvacPlan(buildingId: string): boolean {
  return buildingId in EVAC_DATA && buildingId in VIEWPOINT_ANCHORS;
}

export function resolveEvacPlan(
  buildingId: string,
  surgeFt: SurgeFeet,
  meshSize: MeshSize,
): EvacPlan | null {
  const data = EVAC_DATA[buildingId];
  const anchors = VIEWPOINT_ANCHORS[buildingId];
  if (!data || !anchors) return null;

  const exits: ResolvedExit[] = data.exits.map((exit) => ({
    ...exit,
    blocked: isExitBlocked(exit.blockedAtSurgeFt, surgeFt),
  }));

  const exitById = new Map(exits.map((e) => [e.id, e]));

  const routes: ResolvedRoute[] = data.routes.map((route) => {
    const target = exitById.get(route.targetExitId);
    const points = route.waypointViewpoints
      .map((vpId) => anchors[vpId] ?? null)
      .filter((a): a is NormalizedAnchor => a !== null)
      .map((a) => anchorToWorld(a, meshSize));

    const blockedIdx = findFirstBlockedWaypointIndex(route.waypointViewpoints, exits, surgeFt);

    let status: ResolvedRoute["status"] = "open";
    if (blockedIdx !== -1) {
      status = blockedIdx === 0 ? "blocked" : "partial";
    } else if (target?.blocked) {
      status = "blocked";
    }

    return {
      id: route.id,
      label: route.label,
      points,
      status,
      targetExitId: route.targetExitId,
      blockedFromIndex: blockedIdx === -1 ? null : blockedIdx,
    };
  });

  return {
    buildingId,
    calibrationSource: data.calibrationSource,
    routes,
    exits,
    assemblyExitId: data.assemblyExitId,
  };
}

export function isExitBlocked(blockedAtSurgeFt: SurgeFeet | null, surgeFt: SurgeFeet): boolean {
  if (blockedAtSurgeFt === null) return false;
  return surgeFt >= blockedAtSurgeFt;
}

function findFirstBlockedWaypointIndex(
  viewpointIds: string[],
  exits: ResolvedExit[],
  surgeFt: SurgeFeet,
): number {
  for (let i = 0; i < viewpointIds.length; i += 1) {
    const vpId = viewpointIds[i];
    const matching = exits.find((e) => e.viewpointId === vpId);
    if (matching && isExitBlocked(matching.blockedAtSurgeFt, surgeFt)) {
      return i;
    }
  }
  return -1;
}

export function exitWorldPosition(
  exit: EvacExit,
  meshSize: MeshSize,
): { x: number; y: number; z: number } {
  return anchorToWorld(exit.anchor, meshSize);
}

/** Open routes sorted for display — active paths first. */
export function activeRoutes(plan: EvacPlan): ResolvedRoute[] {
  return [...plan.routes].sort((a, b) => {
    const rank = { open: 0, partial: 1, blocked: 2 };
    return rank[a.status] - rank[b.status];
  });
}

export function openExitCount(plan: EvacPlan): number {
  return plan.exits.filter((e) => !e.blocked).length;
}
