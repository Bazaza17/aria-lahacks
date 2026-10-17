// Mirror of apps/api/app/agent/prompts.py PreplanReport schema.

export type RiskScore = "LOW" | "MODERATE" | "HIGH" | "SEVERE";

export type BuildingProfile = {
  address: string;
  type: string;
  estimated_height_ft: number;
  estimated_occupancy: string;
  construction: string;
  year_built_estimate: string;
};

export type NearbyAsset = {
  name: string;
  distance_mi: number;
};

export type Context = {
  flood_zone: string;
  surge_zone: string;
  nearest_hospital: NearbyAsset;
  nearest_shelter: NearbyAsset;
  nearby_hazards: string[];
};

export type OperationalGuidance = {
  approach_direction: string;
  access_concerns: string[];
  equipment_recommendations: string[];
  evacuation_priority: string;
};

export type Annotation3D = {
  label: string;
  severity: RiskScore;
  anchor_description: string;
};

export type HazardAnalysis = {
  risk_score: RiskScore;
  reasoning: string;
  vulnerable_features: string[];
  failure_modes: string[];
  operational_guidance: OperationalGuidance;
  annotations_3d: Annotation3D[];
};

export type HazardsBlock = {
  wind: HazardAnalysis;
  surge: HazardAnalysis;
  flood: HazardAnalysis;
};

export type Summary = {
  headline_risk: string;
  "30_second_size_up": string;
};

export type PreplanReport = {
  building_profile: BuildingProfile;
  context: Context;
  hazards: HazardsBlock;
  summary: Summary;
};

export type ScenarioParams = {
  wind_mph: number;
  surge_ft: number;
  rainfall_in: number;
};

// SSE event shapes from apps/api/app/agent/streaming.py
export type AgentEvent =
  | { type: "thinking"; iteration: number; stop_reason: string | null }
  | { type: "reasoning"; text: string }
  | {
      type: "tool_call";
      id: string;
      name: string;
      input: Record<string, unknown>;
    }
  | {
      type: "tool_result";
      tool_use_id: string;
      name: string;
      result: unknown;
    }
  | { type: "complete"; report: PreplanReport }
  | { type: "error"; message: string };
