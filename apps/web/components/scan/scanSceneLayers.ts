import * as THREE from "three";
import { CSS2DObject } from "three/examples/jsm/renderers/CSS2DRenderer.js";

import type { MeshSize } from "@/lib/scan-coords";
import type { ResolvedExit, ResolvedRoute } from "@/lib/scan-evac-paths";
import { exitWorldPosition } from "@/lib/scan-evac-paths";
import { waterWorldY } from "@/lib/scan-flood";
import type { FireFrame, FireRoom, FireRouteDeparture, FireTimeline } from "@/lib/scan-fire";

const ROUTE_GREEN = 0x22c55e;
const ROUTE_RED = 0xef4444;
const EXIT_OPEN = 0x22c55e;
const EXIT_BLOCKED = 0xef4444;

export type EvacLayerObjects = {
  group: THREE.Group;
  dispose: () => void;
};

export function buildEvacLayer(
  routes: ResolvedRoute[],
  exits: ResolvedExit[],
  meshSize: MeshSize,
): EvacLayerObjects {
  const group = new THREE.Group();
  const disposables: Array<THREE.BufferGeometry | THREE.Material> = [];
  const labelEls: HTMLElement[] = [];

  for (const route of routes) {
    if (route.points.length < 2) continue;

    const splitIdx =
      route.status === "partial" && route.blockedFromIndex !== null
        ? Math.max(1, route.blockedFromIndex)
        : route.points.length;

    if (route.status === "open" || route.status === "partial") {
      const openPoints = route.points.slice(0, splitIdx);
      if (openPoints.length >= 2) {
        const line = makeRouteLine(openPoints, ROUTE_GREEN, 0.92);
        group.add(line);
        disposables.push(line.geometry, line.material as THREE.Material);
      }
    }

    if (route.status === "blocked" || route.status === "partial") {
      const blockedStart = route.status === "blocked" ? 0 : splitIdx - 1;
      const blockedPoints = route.points.slice(blockedStart);
      if (blockedPoints.length >= 2) {
        const line = makeRouteLine(blockedPoints, ROUTE_RED, 0.75);
        group.add(line);
        disposables.push(line.geometry, line.material as THREE.Material);
      }
    }
  }

  const markerScale = Math.max(meshSize.x, meshSize.y, meshSize.z) * 0.008;

  for (const exit of exits) {
    const pos = exitWorldPosition(exit, meshSize);
    const exitGroup = new THREE.Group();
    exitGroup.position.set(pos.x, pos.y, pos.z);

    const color = exit.blocked ? EXIT_BLOCKED : EXIT_OPEN;
    const ringGeo = new THREE.RingGeometry(markerScale * 2, markerScale * 3.2, 32);
    const ringMat = new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: exit.blocked ? 0.85 : 0.7,
      side: THREE.DoubleSide,
    });
    const ring = new THREE.Mesh(ringGeo, ringMat);
    ring.rotation.x = -Math.PI / 2;
    exitGroup.add(ring);
    disposables.push(ringGeo, ringMat);

    if (exit.blocked) {
      const barGeo = new THREE.BoxGeometry(markerScale * 4, markerScale * 0.5, markerScale * 0.5);
      const barMat = new THREE.MeshBasicMaterial({ color: EXIT_BLOCKED });
      const barA = new THREE.Mesh(barGeo, barMat);
      barA.rotation.y = Math.PI / 4;
      const barB = new THREE.Mesh(barGeo, barMat);
      barB.rotation.y = -Math.PI / 4;
      exitGroup.add(barA, barB);
      disposables.push(barGeo, barMat);
    } else {
      const dotGeo = new THREE.SphereGeometry(markerScale * 1.2, 12, 12);
      const dotMat = new THREE.MeshBasicMaterial({ color: EXIT_OPEN });
      exitGroup.add(new THREE.Mesh(dotGeo, dotMat));
      disposables.push(dotGeo, dotMat);
    }

    const labelEl = document.createElement("div");
    labelEl.className = "scan-evac-exit-label";
    labelEl.dataset.blocked = exit.blocked ? "true" : "false";
    labelEl.textContent = exit.blocked ? `${exit.label} · BLOCKED` : exit.label;
    const label = new CSS2DObject(labelEl);
    label.position.set(0, markerScale * 6, 0);
    exitGroup.add(label);
    labelEls.push(labelEl);

    group.add(exitGroup);
  }

  return {
    group,
    dispose: () => {
      for (const d of disposables) d.dispose();
      // CSS2D labels are DOM nodes appended by the renderer — removing the
      // Object3D doesn't remove the element, so clear them explicitly or they
      // pile up every time the layer is rebuilt (e.g. on surge change).
      for (const el of labelEls) el.remove();
      group.clear();
    },
  };
}

function makeRouteLine(
  points: Array<{ x: number; y: number; z: number }>,
  color: number,
  opacity: number,
): THREE.Line {
  const verts = points.map((p) => new THREE.Vector3(p.x, p.y + 0.002, p.z));
  const geo = new THREE.BufferGeometry().setFromPoints(verts);
  const mat = new THREE.LineBasicMaterial({
    color,
    transparent: true,
    opacity,
    linewidth: 3,
  });
  return new THREE.Line(geo, mat);
}

export type FloodLayerObjects = {
  mesh: THREE.Mesh;
  dispose: () => void;
};

export function buildFloodLayer(waterNy: number, meshSize: MeshSize): FloodLayerObjects {
  const padding = 1.08;
  const w = meshSize.x * padding;
  const d = meshSize.z * padding;
  const geo = new THREE.PlaneGeometry(w, d);
  const mat = new THREE.MeshBasicMaterial({
    color: 0x1e6fd9,
    transparent: true,
    opacity: 0.42,
    side: THREE.DoubleSide,
    depthWrite: false,
  });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.rotation.x = -Math.PI / 2;
  mesh.position.y = waterWorldY(waterNy, meshSize);
  mesh.renderOrder = 1;

  return {
    mesh,
    dispose: () => {
      geo.dispose();
      mat.dispose();
    },
  };
}

export function lerpFloodY(
  mesh: THREE.Mesh,
  targetNy: number,
  meshSize: MeshSize,
  alpha: number,
): void {
  const targetY = waterWorldY(targetNy, meshSize);
  mesh.position.y = THREE.MathUtils.lerp(mesh.position.y, targetY, alpha);
}

/** Tube variant for thicker routes on large meshes */
export function routeTubeRadius(meshSize: MeshSize): number {
  return Math.max(meshSize.x, meshSize.y, meshSize.z) * 0.004;
}

const SMOKE_GREY = 0x6b7280;
const FLOOR_BURNING = 0xff6b00;
const FLOOR_FLASHOVER = 0xef4444;
const FLOOR_BURNT = 0x1c1917;
const DOOR_OPEN = 0x22c55e;
const DOOR_BLOCKED = 0xef4444;
const DEFAULT_CEILING_M = 3;
// Upper storeys have no scan under them, so they are drawn as faint outlines that fill with smoke.
const OUTLINE_OPACITY = 0.35;
const UPPER_OUTLINE_OPACITY = 0.18;

export type FireLayerObjects = {
  group: THREE.Group;
  update: (frame: FireFrame) => void;
  dispose: () => void;
};

type FireRoomMeshes = {
  ceilingM: number;
  smoke: THREE.Mesh;
  smokeMat: THREE.MeshBasicMaterial;
  floorMat: THREE.MeshBasicMaterial;
};

type ScanCenter = { x: number; y: number; z: number };

function roomOutline(room: FireRoom): [number, number][] | null {
  if (room.polygon && room.polygon.length >= 3) return room.polygon;
  if (!room.footprint) return null;
  const [x0, x1] = room.footprint.x;
  const [z0, z1] = room.footprint.z;
  return [
    [x0, z0],
    [x1, z0],
    [x1, z1],
    [x0, z1],
  ];
}

/**
 * Room outline as a THREE.Shape for a group rotated -90° about X: local (x, y, z) lands at
 * world (x, z, -y), so plan z goes in as -y and extrusion depth becomes height.
 */
function roomShape(outline: [number, number][], center: ScanCenter): THREE.Shape {
  return new THREE.Shape(outline.map(([x, z]) => new THREE.Vector2(x - center.x, -(z - center.z))));
}

/**
 * Engine fire timeline drawn over the scan. Room outlines are in the scan's frame; the viewer
 * shifts the mesh by -center, so we do the same. Rooms on upper floors sit at their
 * floor_elevation_m above the scan floor.
 */
export function buildFireLayer(
  timeline: FireTimeline,
  center: ScanCenter,
  floorY: number,
): FireLayerObjects {
  const group = new THREE.Group();
  const disposables: Array<THREE.BufferGeometry | THREE.Material> = [];
  const rooms = new Map<string, FireRoomMeshes>();
  const roomElevation = new Map<string, number>();
  const doors = new Map<string, THREE.MeshBasicMaterial>();
  const y0 = floorY - center.y;
  const firstFrame = timeline.frames[0];

  for (const [id, room] of Object.entries(timeline.rooms)) {
    const outline = roomOutline(room);
    if (!outline) continue;
    const upper = room.floor !== 1;
    const elevation = room.floor_elevation_m ?? 0;
    const ceilingM =
      room.ceiling_height_m ?? firstFrame?.rooms[id]?.layer_height_m ?? DEFAULT_CEILING_M;
    const shape = roomShape(outline, center);

    const roomGroup = new THREE.Group();
    roomGroup.rotation.x = -Math.PI / 2;
    roomGroup.position.y = y0 + elevation;

    // Smoke volume: a unit-depth extrusion scaled to the layer depth each frame.
    const smokeGeo = new THREE.ExtrudeGeometry(shape, { depth: 1, bevelEnabled: false });
    const smokeMat = new THREE.MeshBasicMaterial({
      color: SMOKE_GREY,
      transparent: true,
      opacity: 0,
      depthWrite: false,
      side: THREE.DoubleSide,
    });
    const smoke = new THREE.Mesh(smokeGeo, smokeMat);
    smoke.visible = false;
    smoke.renderOrder = 2;

    const floorGeo = new THREE.ShapeGeometry(shape);
    const floorMat = new THREE.MeshBasicMaterial({
      color: FLOOR_BURNING,
      transparent: true,
      opacity: 0,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const floor = new THREE.Mesh(floorGeo, floorMat);
    floor.position.z = 0.02;
    floor.renderOrder = 1;

    const outlineGeo = new THREE.BufferGeometry().setFromPoints(
      shape.getPoints().map((pt) => new THREE.Vector3(pt.x, pt.y, 0.03)),
    );
    const outlineMat = new THREE.LineBasicMaterial({
      color: 0xffffff,
      transparent: true,
      opacity: upper ? UPPER_OUTLINE_OPACITY : OUTLINE_OPACITY,
    });
    const outlineLine = new THREE.LineLoop(outlineGeo, outlineMat);

    roomGroup.add(smoke, floor, outlineLine);
    group.add(roomGroup);
    disposables.push(smokeGeo, smokeMat, floorGeo, floorMat, outlineGeo, outlineMat);
    rooms.set(id, { ceilingM, smoke, smokeMat, floorMat });
    roomElevation.set(id, elevation);
  }

  const exitDoors = new Set(timeline.exits.map((e) => e.door));
  for (const [id, door] of Object.entries(timeline.doors)) {
    if (!door.position) continue;
    const drawnSide = door.connects.find((r) => rooms.has(r));
    if (!drawnSide) continue;
    const r = exitDoors.has(id) ? 0.45 : 0.25;
    const geo = new THREE.SphereGeometry(r, 16, 16);
    const mat = new THREE.MeshBasicMaterial({ color: DOOR_OPEN });
    const mesh = new THREE.Mesh(geo, mat);
    const elevation = roomElevation.get(drawnSide) ?? 0;
    mesh.position.set(door.position.x - center.x, y0 + elevation + 1, door.position.z - center.z);
    group.add(mesh);
    disposables.push(geo, mat);
    doors.set(id, mat);
  }

  const update = (frame: FireFrame) => {
    for (const [id, meshes] of rooms) {
      const state = frame.rooms[id];
      if (!state) continue;
      const bottom = Math.max(0, Math.min(state.layer_height_m, meshes.ceilingM));
      const depth = meshes.ceilingM - bottom;
      if (depth < 0.02) {
        meshes.smoke.visible = false;
      } else {
        meshes.smoke.visible = true;
        meshes.smoke.scale.z = depth;
        meshes.smoke.position.z = bottom;
        const depthFrac = depth / meshes.ceilingM;
        const heat = Math.min(1, Math.max(0, (state.layer_temp_c - 20) / 600));
        meshes.smokeMat.opacity = Math.min(0.85, 0.15 + 0.45 * depthFrac + 0.25 * heat);
      }

      if (state.state === "burnt_out") {
        meshes.floorMat.color.setHex(FLOOR_BURNT);
        meshes.floorMat.opacity = 0.8;
      } else if (state.state === "flashover") {
        meshes.floorMat.color.setHex(FLOOR_FLASHOVER);
        meshes.floorMat.opacity = 0.75;
      } else if (state.state === "burning") {
        meshes.floorMat.color.setHex(FLOOR_BURNING);
        meshes.floorMat.opacity = 0.25 + 0.5 * Math.min(1, state.hrr_kw / 10000);
      } else {
        meshes.floorMat.opacity = 0;
      }
    }

    const blocked = new Set(frame.blocked);
    for (const [id, mat] of doors) {
      mat.color.setHex(blocked.has(id) ? DOOR_BLOCKED : DOOR_OPEN);
    }
  };

  if (firstFrame) update(firstFrame);

  return {
    group,
    update,
    dispose: () => {
      for (const d of disposables) d.dispose();
      group.clear();
    },
  };
}

const ROUTE_PLAN = 0x38bdf8;
const ROUTE_PLAN_AT_RISK = 0xf59e0b;
const ROUTE_REACTIVE = 0xef4444;
const ROUTE_LIFT_M = 0.25;

export type FireRouteLayerObjects = {
  group: THREE.Group;
  show: (departure: FireRouteDeparture | null) => void;
  dispose: () => void;
};

/**
 * Evacuation routes from the engine, one group per departure time. Aria's plan is blue (amber
 * where people are still at risk); a self-chosen route that fails is red.
 */
export function buildFireRouteLayer(
  timeline: FireTimeline,
  center: ScanCenter,
  floorY: number,
): FireRouteLayerObjects {
  const group = new THREE.Group();
  const disposables: Array<THREE.BufferGeometry | THREE.Material> = [];
  const byDeparture = new Map<number, THREE.Group>();
  const y0 = floorY - center.y;

  for (const departure of timeline.routes?.departures ?? []) {
    const departureGroup = new THREE.Group();
    departureGroup.visible = false;
    for (const route of departure.routes) {
      if (route.points.length < 2) continue;
      const pts = route.points.map(
        ([x, z, elevation]) =>
          new THREE.Vector3(x - center.x, y0 + elevation + ROUTE_LIFT_M, z - center.z),
      );
      const path = new THREE.CurvePath<THREE.Vector3>();
      for (let i = 1; i < pts.length; i++) path.add(new THREE.LineCurve3(pts[i - 1], pts[i]));
      const plan = route.kind === "plan";
      const geo = new THREE.TubeGeometry(path, Math.max(8, pts.length * 6), plan ? 0.12 : 0.09, 6);
      const color = !plan ? ROUTE_REACTIVE : route.at_risk > 0 ? ROUTE_PLAN_AT_RISK : ROUTE_PLAN;
      const mat = new THREE.MeshBasicMaterial({
        color,
        transparent: true,
        opacity: plan ? 0.9 : 0.75,
        depthWrite: false,
      });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.renderOrder = 3;
      departureGroup.add(mesh);
      disposables.push(geo, mat);
    }
    group.add(departureGroup);
    byDeparture.set(departure.t0_s, departureGroup);
  }

  return {
    group,
    show: (departure) => {
      for (const [t0, g] of byDeparture) g.visible = departure !== null && t0 === departure.t0_s;
    },
    dispose: () => {
      for (const d of disposables) d.dispose();
      group.clear();
    },
  };
}
