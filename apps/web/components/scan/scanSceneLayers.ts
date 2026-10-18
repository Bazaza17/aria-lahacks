import * as THREE from "three";
import { CSS2DObject } from "three/examples/jsm/renderers/CSS2DRenderer.js";

import type { FireFrame, FireRoom, FireRouteDeparture, FireTimeline } from "@/lib/scan-fire";
import { placeTag, placeToWorld, SPACE_TYPES, type PlaceMatch } from "@/lib/scan-places";

const SMOKE_GREY = 0x6b7280;
const FLOOR_BURNING = 0xff6b00;
const FLOOR_FLASHOVER = 0xef4444;
const FLOOR_BURNT = 0x1c1917;
const DOOR_OPEN = 0x22c55e;
const DOOR_BLOCKED = 0xef4444;
const DEFAULT_CEILING_M = 3;
// Scanned rooms get a solid outline. Rooms from the floor plan (the rest of the 1F and every upper
// floor) get a fainter dashed one, so nothing plan-derived passes for scanned.
const OUTLINE_OPACITY = 0.35;
const PLAN_OUTLINE_OPACITY = 0.22;
const UPPER_OUTLINE_OPACITY = 0.16;
const PLAN_DASH_M = 0.6;
const PLAN_GAP_M = 0.4;

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

/** Rooms the API marks as outlined from the scan. Anything else, including rooms in an older
 *  file without the flag, is drawn as plan-derived. */
function isScanned(room: FireRoom): boolean {
  if (room.scanned !== undefined) return room.scanned;
  return room.geometry_source === "scan";
}

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
    const scanned = isScanned(room);
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
    const outlineOpacity = scanned
      ? OUTLINE_OPACITY
      : upper
        ? UPPER_OUTLINE_OPACITY
        : PLAN_OUTLINE_OPACITY;
    const outlineMat = scanned
      ? new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: outlineOpacity })
      : new THREE.LineDashedMaterial({
          color: 0xffffff,
          transparent: true,
          opacity: outlineOpacity,
          dashSize: PLAN_DASH_M,
          gapSize: PLAN_GAP_M,
        });
    const outlineLine = new THREE.LineLoop(outlineGeo, outlineMat);
    if (!scanned) outlineLine.computeLineDistances();

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

// Fuchsia, so a found place stands apart from fire orange, smoke grey and the route colors.
const PLACE_PIN = 0xe879f9;
const PIN_BEAM_M = 6;
// Snap to the scan: cast down from this far above the plan floor, and take the hit closest to
// the plan floor within the tolerance (the first hit can be a table or a stair rail).
const SNAP_FROM_M = 1.6;
const SNAP_TOL_M = 0.35;
// A space whose point lands on a hole in the scan tries rings of points inside its outline.
const SNAP_RING_RADII_M = [0.6, 1.2, 1.8];
const SNAP_RING_STEPS = 8;
const DOWN = new THREE.Vector3(0, -1, 0);

export type PlacePin = {
  match: PlaceMatch;
  /** Marker position in the scene: on the scanned floor when snapped, else at the plan height. */
  at: THREE.Vector3;
  /** Whether a scanned floor was found under the place. */
  onScan: boolean;
};

export type PlacePinLayerObjects = {
  group: THREE.Group;
  dispose: () => void;
};

function insidePolygon(x: number, z: number, poly: [number, number][]): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, zi] = poly[i];
    const [xj, zj] = poly[j];
    if (zi > z !== zj > z && x < ((xj - xi) * (z - zi)) / (zj - zi) + xi) inside = !inside;
  }
  return inside;
}

function scanFloorAt(
  raycaster: THREE.Raycaster,
  scan: THREE.Object3D,
  x: number,
  planY: number,
  z: number,
): number | null {
  raycaster.set(new THREE.Vector3(x, planY + SNAP_FROM_M, z), DOWN);
  raycaster.far = SNAP_FROM_M + SNAP_TOL_M;
  let best: number | null = null;
  for (const hit of raycaster.intersectObject(scan, true)) {
    const d = Math.abs(hit.point.y - planY);
    if (d <= SNAP_TOL_M && (best === null || d < Math.abs(best - planY))) best = hit.point.y;
  }
  return best;
}

/**
 * Where a place goes in the scene: its venue-frame point (the fire layer's transform), snapped
 * down onto the scanned floor. Plan-only places aren't cast; they stay at the plan height.
 */
export function resolvePlacePin(
  match: PlaceMatch,
  scan: THREE.Object3D,
  center: ScanCenter,
  floorY: number,
): PlacePin {
  const world = placeToWorld(match.point, center, floorY);
  const tries: [number, number][] = [[world.x, world.z]];
  if (match.polygon) {
    for (const r of SNAP_RING_RADII_M) {
      for (let k = 0; k < SNAP_RING_STEPS; k++) {
        const a = (2 * Math.PI * k) / SNAP_RING_STEPS;
        const [x, z] = [match.point[0] + r * Math.cos(a), match.point[2] + r * Math.sin(a)];
        if (insidePolygon(x, z, match.polygon)) tries.push([x - center.x, z - center.z]);
      }
    }
  }
  const raycaster = new THREE.Raycaster();
  for (const [x, z] of match.scanned ? tries : []) {
    const y = scanFloorAt(raycaster, scan, x, world.y, z);
    if (y !== null) return { match, at: new THREE.Vector3(x, y, z), onScan: true };
  }
  return { match, at: new THREE.Vector3(world.x, world.y, world.z), onScan: false };
}

/**
 * Found places: a dot, a floor ring, a beam and a label, drawn through walls, plus the outline
 * when the place is a space. Pins off the scan (plan-only) are hollow and say how far off they
 * may be.
 */
export function buildPlacePinLayer(pins: PlacePin[], center: ScanCenter): PlacePinLayerObjects {
  const group = new THREE.Group();
  const disposables: Array<THREE.BufferGeometry | THREE.Material> = [];
  const labelEls: HTMLElement[] = [];
  const track = <T extends THREE.BufferGeometry | THREE.Material>(d: T): T => {
    disposables.push(d);
    return d;
  };
  const overlay = (opacity: number, wireframe = false) =>
    track(
      new THREE.MeshBasicMaterial({
        color: PLACE_PIN,
        transparent: true,
        opacity,
        wireframe,
        depthTest: false,
        depthWrite: false,
        side: THREE.DoubleSide,
      }),
    );

  for (const pin of pins) {
    const pinGroup = new THREE.Group();
    pinGroup.position.copy(pin.at);

    const dot = new THREE.Mesh(
      track(new THREE.SphereGeometry(0.35, 16, 12)),
      overlay(pin.onScan ? 1 : 0.8, !pin.onScan),
    );
    dot.position.y = 0.35;
    const ring = new THREE.Mesh(
      track(new THREE.RingGeometry(0.55, 0.8, 40)),
      overlay(pin.onScan ? 0.85 : 0.4),
    );
    ring.rotation.x = -Math.PI / 2;
    ring.position.y = 0.04;
    const beam = new THREE.Mesh(
      track(new THREE.CylinderGeometry(0.05, 0.05, PIN_BEAM_M, 6)),
      overlay(0.55),
    );
    beam.position.y = PIN_BEAM_M / 2;
    for (const m of [dot, ring, beam]) m.renderOrder = 10;

    const el = document.createElement("div");
    el.className = "scan-place-pin";
    el.dataset.onScan = String(pin.onScan);
    el.textContent = `${pin.match.label} · ${placeTag(pin.match, pin.onScan)}`;
    const label = new CSS2DObject(el);
    label.center.set(0.5, 1);
    label.position.y = PIN_BEAM_M;
    labelEls.push(el);

    pinGroup.add(dot, ring, beam, label);
    group.add(pinGroup);

    if (pin.match.polygon && SPACE_TYPES.includes(pin.match.type)) {
      // The space itself: a faint fill and its outline, laid like the fire layer's floors.
      const shape = roomShape(pin.match.polygon, center);
      const area = new THREE.Group();
      area.rotation.x = -Math.PI / 2;
      area.position.y = pin.at.y + 0.05;
      const fill = new THREE.Mesh(track(new THREE.ShapeGeometry(shape)), overlay(0.16));
      const outline = new THREE.LineLoop(
        track(new THREE.BufferGeometry().setFromPoints(shape.getPoints())),
        track(
          new THREE.LineBasicMaterial({ color: PLACE_PIN, depthTest: false, transparent: true }),
        ),
      );
      fill.renderOrder = outline.renderOrder = 10;
      area.add(fill, outline);
      group.add(area);
    }
  }

  return {
    group,
    dispose: () => {
      for (const d of disposables) d.dispose();
      for (const el of labelEls) el.remove();
      group.clear();
    },
  };
}
