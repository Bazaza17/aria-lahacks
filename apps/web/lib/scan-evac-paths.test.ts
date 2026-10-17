import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { hasEvacPlan, isExitBlocked, openExitCount, resolveEvacPlan } from "./scan-evac-paths";
import { hasFloodProfile, waterSurfaceNy } from "./scan-flood";

const BUILDING_A = "014b39a9-09b8-432b-9b62-363e06383d1f";
const BUILDING_B = "870d979d-6eaf-4d7f-894a-8ca34e527237";
const UNKNOWN = "00000000-0000-0000-0000-000000000099";

/** Representative mesh bbox sizes from LiDAR captures (meters, centered). */
const MESH_A: { x: number; y: number; z: number } = { x: 42, y: 12, z: 28 };
const MESH_B: { x: number; y: number; z: number } = { x: 18, y: 8, z: 22 };

describe("scan-evac-paths", () => {
  it("returns null for buildings without calibrated walkthrough data", () => {
    assert.equal(hasEvacPlan(UNKNOWN), false);
    assert.equal(resolveEvacPlan(UNKNOWN, 0, MESH_A), null);
  });

  it("Building A — dry conditions keep grade and assembly exits open", () => {
    const plan = resolveEvacPlan(BUILDING_A, 0, MESH_A);
    assert.ok(plan);
    assert.equal(openExitCount(plan), plan.exits.length);
    assert.ok(plan.routes.some((r) => r.status === "open"));
    assert.ok(plan.exits.find((e) => e.id === "exit_assembly_court")?.blocked === false);
  });

  it("Building A — 1ft surge blocks grade-level exits", () => {
    const plan = resolveEvacPlan(BUILDING_A, 1, MESH_A);
    assert.ok(plan);
    const grade = plan.exits.find((e) => e.id === "exit_grade_transition");
    assert.ok(grade?.blocked);
    assert.ok(openExitCount(plan) < plan.exits.length);
    const primary = plan.routes.find((r) => r.id === "primary_to_assembly");
    assert.ok(primary);
    assert.notEqual(primary.status, "open");
  });

  it("Building A — 6ft surge blocks yard egress but assembly remains", () => {
    const plan = resolveEvacPlan(BUILDING_A, 6, MESH_A);
    assert.ok(plan);
    const yard = plan.exits.find((e) => e.id === "exit_yard");
    assert.ok(yard?.blocked);
    const assembly = plan.exits.find((e) => e.id === "exit_assembly_court");
    assert.ok(assembly);
    assert.equal(assembly.blocked, false);
  });

  it("Building B — 1ft surge blocks main facade and glass vestibule", () => {
    const plan = resolveEvacPlan(BUILDING_B, 1, MESH_B);
    assert.ok(plan);
    assert.ok(plan.exits.find((e) => e.id === "exit_main_facade")?.blocked);
    assert.ok(plan.exits.find((e) => e.id === "exit_glass_vestibule")?.blocked);
    assert.equal(plan.exits.find((e) => e.id === "exit_side_egress")?.blocked, false);
  });

  it("Building B — interior route stays viable at 1ft via side door", () => {
    const plan = resolveEvacPlan(BUILDING_B, 1, MESH_B);
    assert.ok(plan);
    const route = plan.routes.find((r) => r.id === "interior_to_side");
    assert.ok(route);
    assert.equal(route.status, "open");
    assert.ok(route.points.length >= 2);
  });

  it("route waypoints produce valid world coordinates for multiple mesh sizes", () => {
    const sizes = [MESH_A, MESH_B, { x: 30, y: 10, z: 30 }];
    for (const size of sizes) {
      const plan = resolveEvacPlan(BUILDING_A, 0, size);
      assert.ok(plan);
      for (const route of plan.routes) {
        for (const pt of route.points) {
          assert.ok(Number.isFinite(pt.x));
          assert.ok(Number.isFinite(pt.y));
          assert.ok(Number.isFinite(pt.z));
          assert.ok(Math.abs(pt.x) <= size.x * 0.6);
          assert.ok(Math.abs(pt.z) <= size.z * 0.6);
        }
      }
    }
  });

  it("isExitBlocked respects null assembly thresholds", () => {
    assert.equal(isExitBlocked(null, 10), false);
    assert.equal(isExitBlocked(1, 0), false);
    assert.equal(isExitBlocked(1, 1), true);
    assert.equal(isExitBlocked(3, 1), false);
  });
});

describe("scan-flood", () => {
  it("only exposes flood profiles for calibrated buildings", () => {
    assert.equal(hasFloodProfile(BUILDING_A), true);
    assert.equal(hasFloodProfile(BUILDING_B), true);
    assert.equal(hasFloodProfile(UNKNOWN), false);
  });

  it("water rises monotonically with surge for Building A", () => {
    const dry = waterSurfaceNy(BUILDING_A, 0);
    const one = waterSurfaceNy(BUILDING_A, 1);
    const three = waterSurfaceNy(BUILDING_A, 3);
    const six = waterSurfaceNy(BUILDING_A, 6);
    const ten = waterSurfaceNy(BUILDING_A, 10);
    assert.equal(dry, null);
    assert.ok(one !== null && three !== null && six !== null && ten !== null);
    assert.ok(one < three);
    assert.ok(three < six);
    assert.ok(six < ten);
  });
});
