import * as THREE from "three";
import { CSS2DObject } from "three/examples/jsm/renderers/CSS2DRenderer.js";

import type {
  FireFrame,
  FireRoom,
  FireRoute,
  FireRouteDeparture,
  FireTimeline,
} from "@/lib/scan-fire";
import { placeTag, placeToWorld, SPACE_TYPES, type PlaceMatch } from "@/lib/scan-places";

type ScanCenter = { x: number; y: number; z: number };

const FIRE_RED = 0xff5a48;
const DEFAULT_CEILING_M = 3;
// Scanned rooms get a solid outline. Rooms from the floor plan (the rest of the 1F and every upper
// floor) get a fainter dashed one, so nothing plan-derived passes for scanned.
const OUTLINE_OPACITY = 0.3;
const PLAN_OUTLINE_OPACITY = 0.2;
const UPPER_OUTLINE_OPACITY = 0.12;
const SELECTED_OUTLINE_OPACITY = 0.95;
const PLAN_DASH_M = 0.6;
const PLAN_GAP_M = 0.4;

// ---------------------------------------------------------------------------------------------
// Scan crop: a box around the scanned rooms, so the LiDAR's ragged edges (glimpses through
// doors and windows, floor noise) don't frame the building.

const CROP_MARGIN_M = 1.2;
const CROP_BELOW_FLOOR_M = 0.35;
const CROP_ABOVE_FLOOR_M = 9;

/** Scene-space box around the scanned ground-floor rooms (venue frame bounds + a margin). */
export function scanCropBox(
  timeline: FireTimeline,
  center: ScanCenter,
  floorY: number,
): THREE.Box3 | null {
  let [x0, x1, z0, z1] = [Infinity, -Infinity, Infinity, -Infinity];
  for (const room of Object.values(timeline.rooms)) {
    if (room.floor !== 1 || !isScanned(room)) continue;
    for (const [x, z] of roomOutline(room) ?? []) {
      x0 = Math.min(x0, x);
      x1 = Math.max(x1, x);
      z0 = Math.min(z0, z);
      z1 = Math.max(z1, z);
    }
  }
  if (!Number.isFinite(x0)) return null;
  const y0 = floorY - center.y;
  return new THREE.Box3(
    new THREE.Vector3(
      x0 - CROP_MARGIN_M - center.x,
      y0 - CROP_BELOW_FLOOR_M,
      z0 - CROP_MARGIN_M - center.z,
    ),
    new THREE.Vector3(
      x1 + CROP_MARGIN_M - center.x,
      y0 + CROP_ABOVE_FLOOR_M,
      z1 + CROP_MARGIN_M - center.z,
    ),
  );
}

/** Six clipping planes that keep what's inside `box` (update in place; no allocation). */
export function setCropPlanes(planes: THREE.Plane[], box: THREE.Box3): void {
  const { min, max } = box;
  planes[0].set(new THREE.Vector3(1, 0, 0), -min.x);
  planes[1].set(new THREE.Vector3(-1, 0, 0), max.x);
  planes[2].set(new THREE.Vector3(0, 1, 0), -min.y);
  planes[3].set(new THREE.Vector3(0, -1, 0), max.y);
  planes[4].set(new THREE.Vector3(0, 0, 1), -min.z);
  planes[5].set(new THREE.Vector3(0, 0, -1), max.z);
}

// ---------------------------------------------------------------------------------------------
// Fire layer: smoke layers, burning glow, charring, room outlines.

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

const NOISE_GLSL = /* glsl */ `
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x),
             mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x), f.y);
}`;

// Unit-depth room extrusions: position.z is the height fraction (0 = bottom, 1 = top); caps
// have a ±z normal.
const VOLUME_VERT = /* glsl */ `
varying float vH;
varying float vCap;
varying vec3 vWorld;
void main() {
  vH = position.z;
  vCap = abs(normal.z);
  vec4 world = modelMatrix * vec4(position, 1.0);
  vWorld = world.xyz;
  gl_Position = projectionMatrix * viewMatrix * world;
}`;

// Smoke: densest at the ceiling, thinning to a soft edge at the layer interface, drifting slowly.
const SMOKE_FRAG = /* glsl */ `
uniform vec3 uColor;
uniform float uOpacity;
uniform float uTime;
varying float vH;
varying float vCap;
varying vec3 vWorld;
${NOISE_GLSL}
void main() {
  float profile = mix(0.1, 1.0, smoothstep(0.0, 1.0, vH));
  float drift = noise(vWorld.xz * 0.32 + vec2(uTime * 0.05, uTime * 0.035));
  float curl = noise(vWorld.xz * 0.85 + vec2(vWorld.y * 0.6 - uTime * 0.04, uTime * 0.03));
  float a = uOpacity * profile * (0.7 + 0.45 * (0.6 * drift + 0.4 * curl));
  a *= mix(1.0, 0.75, vCap);
  gl_FragColor = vec4(uColor, clamp(a, 0.0, 1.0));
  #include <colorspace_fragment>
}`;

// Burning: a warm tint on the floor (fading from the room's middle) and up the lower walls.
const GLOW_FRAG = /* glsl */ `
uniform vec3 uColor;
uniform float uOpacity;
uniform float uTime;
uniform vec2 uCenter;
uniform float uRadius;
varying float vH;
varying float vCap;
varying vec3 vWorld;
${NOISE_GLSL}
void main() {
  float rise = pow(1.0 - vH, 1.8);
  float radial = 1.0 - smoothstep(0.15 * uRadius, uRadius, distance(vWorld.xz, uCenter));
  float flicker = 0.75 + 0.5 * noise(vWorld.xz * 0.6 + vec2(uTime * 0.8, -uTime * 0.6));
  float a = uOpacity * rise * flicker * mix(1.0, radial, vCap);
  gl_FragColor = vec4(uColor, clamp(a, 0.0, 1.0));
  #include <colorspace_fragment>
}`;

const SMOKE_THIN = new THREE.Color(0xa3a8ae);
const SMOKE_THICK = new THREE.Color(0x45494f);
const SMOKE_UNTENABLE = new THREE.Color(0x2c2e32);
const GLOW_BURNING = new THREE.Color(FIRE_RED);
const GLOW_FLASHOVER = new THREE.Color(0xff7a3c);
const FLOOR_BURNT = 0x16130f;
const GLOW_BAND_M = 1.3;
// Upper floors float above the scan: their smoke is a faint haze (so the ground floor still
// reads) and their outline carries the state instead (grey with smoke, red once untenable).
const UPPER_SMOKE_SCALE = 0.12;
const UPPER_SMOKE_OUTLINE = 0x9ea2a7;
const UPPER_SMOKE_OUTLINE_OPACITY = 0.4;
const UPPER_UNTENABLE_OUTLINE_OPACITY = 0.6;

type VolumeUniforms = {
  uColor: { value: THREE.Color };
  uOpacity: { value: number };
  uTime: { value: number };
};

function volumeMaterial(
  frag: string,
  uniforms: Record<string, THREE.IUniform>,
): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    vertexShader: VOLUME_VERT,
    fragmentShader: frag,
    uniforms,
    transparent: true,
    depthWrite: false,
    side: THREE.DoubleSide,
  });
}

type FireRoomMeshes = {
  ceilingM: number;
  upper: boolean;
  smoke: THREE.Mesh;
  smokeU: VolumeUniforms;
  glow: THREE.Mesh;
  glowU: VolumeUniforms;
  floor: THREE.Mesh;
  floorMat: THREE.MeshBasicMaterial;
  outlineMat: THREE.LineBasicMaterial | THREE.LineDashedMaterial;
  outlineOpacity: number;
};

export type FireLayerObjects = {
  group: THREE.Group;
  update: (frame: FireFrame) => void;
  /** Advance the smoke drift / glow flicker (seconds). */
  tick: (timeS: number) => void;
  setSelected: (roomId: string | null) => void;
  /** The room under a ray: the scanned ground floor wins over upper floors drawn above it. */
  pick: (raycaster: THREE.Raycaster) => string | null;
  dispose: () => void;
};

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
  const floors: THREE.Mesh[] = [];
  const time = { value: 0 };
  const y0 = floorY - center.y;
  const firstFrame = timeline.frames[0];
  let selected: string | null = null;

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

    // One unit-depth extrusion, shared by the smoke layer and the burning glow; each is scaled.
    const volumeGeo = new THREE.ExtrudeGeometry(shape, { depth: 1, bevelEnabled: false });
    const smokeU: VolumeUniforms = {
      uColor: { value: SMOKE_THIN.clone() },
      uOpacity: { value: 0 },
      uTime: time,
    };
    const smokeMat = volumeMaterial(SMOKE_FRAG, smokeU);
    const smoke = new THREE.Mesh(volumeGeo, smokeMat);
    smoke.visible = false;
    smoke.renderOrder = 3;

    const xs = outline.map(([x]) => x);
    const zs = outline.map(([, z]) => z);
    const [mx0, mx1, mz0, mz1] = [
      Math.min(...xs),
      Math.max(...xs),
      Math.min(...zs),
      Math.max(...zs),
    ];
    const glowU: VolumeUniforms & Record<string, THREE.IUniform> = {
      uColor: { value: GLOW_BURNING.clone() },
      uOpacity: { value: 0 },
      uTime: time,
      uCenter: { value: new THREE.Vector2((mx0 + mx1) / 2 - center.x, (mz0 + mz1) / 2 - center.z) },
      uRadius: { value: Math.max(2, 0.5 * Math.hypot(mx1 - mx0, mz1 - mz0)) },
    };
    const glowMat = volumeMaterial(GLOW_FRAG, glowU);
    const glow = new THREE.Mesh(volumeGeo, glowMat);
    glow.visible = false;
    glow.renderOrder = 2;

    const floorGeo = new THREE.ShapeGeometry(shape);
    const floorMat = new THREE.MeshBasicMaterial({
      color: FLOOR_BURNT,
      transparent: true,
      opacity: 0,
      side: THREE.DoubleSide,
      depthWrite: false,
      toneMapped: false,
    });
    const floor = new THREE.Mesh(floorGeo, floorMat);
    floor.position.z = 0.03;
    floor.renderOrder = 1;
    floor.userData = { roomId: id, upper };
    floors.push(floor);

    const outlineGeo = new THREE.BufferGeometry().setFromPoints(
      shape.getPoints().map((pt) => new THREE.Vector3(pt.x, pt.y, 0.04)),
    );
    const outlineOpacity = scanned
      ? OUTLINE_OPACITY
      : upper
        ? UPPER_OUTLINE_OPACITY
        : PLAN_OUTLINE_OPACITY;
    const outlineMat = scanned
      ? new THREE.LineBasicMaterial({
          color: 0xffffff,
          transparent: true,
          opacity: outlineOpacity,
          toneMapped: false,
        })
      : new THREE.LineDashedMaterial({
          color: 0xffffff,
          transparent: true,
          opacity: outlineOpacity,
          dashSize: PLAN_DASH_M,
          gapSize: PLAN_GAP_M,
          toneMapped: false,
        });
    const outlineLine = new THREE.LineLoop(outlineGeo, outlineMat);
    if (!scanned) outlineLine.computeLineDistances();

    roomGroup.add(glow, smoke, floor, outlineLine);
    group.add(roomGroup);
    disposables.push(volumeGeo, smokeMat, glowMat, floorGeo, floorMat, outlineGeo, outlineMat);
    rooms.set(id, {
      ceilingM,
      upper,
      smoke,
      smokeU,
      glow,
      glowU,
      floor,
      floorMat,
      outlineMat,
      outlineOpacity,
    });
  }

  const paintFloor = (id: string, meshes: FireRoomMeshes, burnt: boolean) => {
    if (burnt) {
      meshes.floorMat.color.setHex(FLOOR_BURNT);
      meshes.floorMat.opacity = 0.78;
    } else if (id === selected) {
      meshes.floorMat.color.setHex(0xffffff);
      meshes.floorMat.opacity = 0.08;
    } else {
      meshes.floorMat.opacity = 0;
    }
  };
  const burntRooms = new Set<string>();
  const upperState = new Map<string, FireFrame["rooms"][string]["state"]>();

  const paintUpperOutline = (
    id: string,
    m: FireRoomMeshes,
    state: FireFrame["rooms"][string]["state"],
  ) => {
    upperState.set(id, state);
    const smoky = state === "smoke";
    const untenable = state !== "clear" && !smoky;
    m.outlineMat.color.setHex(untenable ? FIRE_RED : smoky ? UPPER_SMOKE_OUTLINE : 0xffffff);
    m.outlineMat.opacity =
      id === selected
        ? SELECTED_OUTLINE_OPACITY
        : untenable
          ? UPPER_UNTENABLE_OUTLINE_OPACITY
          : smoky
            ? UPPER_SMOKE_OUTLINE_OPACITY
            : m.outlineOpacity;
  };

  const update = (frame: FireFrame) => {
    burntRooms.clear();
    for (const [id, m] of rooms) {
      const state = frame.rooms[id];
      if (!state) continue;

      // Smoke: from the ceiling down to the layer height.
      const bottom = Math.max(0, Math.min(state.layer_height_m, m.ceilingM));
      const depth = m.ceilingM - bottom;
      if (depth < 0.05) {
        m.smoke.visible = false;
      } else {
        const frac = depth / m.ceilingM;
        const heat = Math.min(1, Math.max(0, (state.layer_temp_c - 20) / 500));
        const untenable = state.state !== "clear" && state.state !== "smoke";
        m.smoke.visible = true;
        m.smoke.scale.z = depth;
        m.smoke.position.z = bottom;
        const color = m.smokeU.uColor.value
          .copy(SMOKE_THIN)
          .lerp(SMOKE_THICK, Math.max(frac, heat));
        if (untenable) color.lerp(SMOKE_UNTENABLE, 0.5);
        const opacity = 0.3 + 0.45 * frac + 0.15 * heat + (untenable ? 0.12 : 0);
        m.smokeU.uOpacity.value = Math.min(0.8, opacity) * (m.upper ? UPPER_SMOKE_SCALE : 1);
      }

      // Burning: a restrained glow low in the room; flashover fills it to the ceiling.
      if (state.state === "burning" || state.state === "flashover") {
        const flashover = state.state === "flashover";
        m.glow.visible = true;
        m.glow.scale.z = flashover ? m.ceilingM : Math.min(GLOW_BAND_M, m.ceilingM);
        m.glowU.uColor.value.copy(flashover ? GLOW_FLASHOVER : GLOW_BURNING);
        m.glowU.uOpacity.value = flashover ? 0.85 : 0.3 + 0.4 * Math.min(1, state.hrr_kw / 8000);
      } else {
        m.glow.visible = false;
      }
      if (m.upper) paintUpperOutline(id, m, state.state);
      if (state.state === "burnt_out") burntRooms.add(id);
      paintFloor(id, m, state.state === "burnt_out");
    }
  };

  const setSelected = (roomId: string | null) => {
    selected = roomId;
    for (const [id, m] of rooms) {
      const upper = upperState.get(id);
      if (upper) paintUpperOutline(id, m, upper);
      else m.outlineMat.opacity = id === roomId ? SELECTED_OUTLINE_OPACITY : m.outlineOpacity;
      paintFloor(id, m, burntRooms.has(id));
    }
  };

  const pick = (raycaster: THREE.Raycaster): string | null => {
    const hits = raycaster.intersectObjects(floors, false);
    const ground = hits.find((h) => !h.object.userData.upper);
    const hit = ground ?? hits[0];
    return hit ? (hit.object.userData.roomId as string) : null;
  };

  if (firstFrame) update(firstFrame);

  return {
    group,
    update,
    tick: (timeS) => {
      time.value = timeS;
    },
    setSelected,
    pick,
    dispose: () => {
      for (const d of disposables) d.dispose();
      group.clear();
    },
  };
}

// ---------------------------------------------------------------------------------------------
// Exits: one marker per exit door, one label per group of same-named doors side by side.

const EXIT_OPEN = 0xd7dadd;
const EXIT_SELECTED = 0xffffff;
const EXIT_GROUP_M = 5;
const EXIT_LABEL_LIFT_M = 2.6;
const EXIT_HIT_M = 1.4;

export type ExitGroup = {
  key: string;
  label: string;
  doors: string[];
  /** When the engine has the group lost (earliest door), or null if it stays open. */
  blockedS: number | null;
  /** Venue frame [x, elevation, z] of each door. */
  points: [number, number, number][];
};

/** m:ss, as the exit labels read it. */
export function formatLostClock(tS: number): string {
  const m = Math.floor(tS / 60);
  const s = Math.floor(tS % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** An exit's elevation: where a route passes through its door, else its drawn room's floor. */
function exitElevation(timeline: FireTimeline, doorId: string, x: number, z: number): number {
  for (const departure of timeline.routes?.departures ?? []) {
    for (const route of departure.routes) {
      for (const [px, pz, e] of route.points) {
        if (Math.abs(px - x) < 0.2 && Math.abs(pz - z) < 0.2) return e;
      }
    }
  }
  const door = timeline.doors[doorId];
  for (const side of door?.connects ?? []) {
    const room = timeline.rooms[side];
    if (room) return room.floor_elevation_m ?? 0;
  }
  return 0;
}

/** The venue's exits grouped for labels: same name, same loss time, within a few metres. */
export function groupExits(timeline: FireTimeline): ExitGroup[] {
  const groups: ExitGroup[] = [];
  for (const exit of timeline.exits) {
    const pos = timeline.doors[exit.door]?.position;
    if (!pos) continue;
    const point: [number, number, number] = [
      pos.x,
      exitElevation(timeline, exit.door, pos.x, pos.z),
      pos.z,
    ];
    const near = groups.find(
      (g) =>
        g.label === exit.label &&
        g.blockedS === exit.blocked_s &&
        g.points.some(([x, , z]) => Math.hypot(x - point[0], z - point[2]) < EXIT_GROUP_M),
    );
    if (near) {
      near.doors.push(exit.door);
      near.points.push(point);
    } else {
      groups.push({
        key: exit.id,
        label: exit.label,
        doors: [exit.door],
        blockedS: exit.blocked_s,
        points: [point],
      });
    }
  }
  return groups;
}

export function exitGroupName(group: ExitGroup): string {
  return group.doors.length > 1 ? `${group.label} ×${group.doors.length}` : group.label;
}

export type ExitLayerObjects = {
  group: THREE.Group;
  update: (tS: number) => void;
  setSelected: (key: string | null) => void;
  pick: (raycaster: THREE.Raycaster) => string | null;
  dispose: () => void;
};

type ExitMarker = {
  group: ExitGroup;
  meshes: THREE.Mesh[];
  fills: THREE.Mesh[];
  holders: THREE.Group[];
  label: HTMLElement;
  status: HTMLElement;
  lost: boolean | null;
};

const LABEL_BASE =
  "caps flex max-w-[220px] items-center gap-1.5 whitespace-nowrap border bg-scan/85 px-1.5 py-[3px] text-[9px] leading-none";

export function buildExitLayer(
  timeline: FireTimeline,
  center: ScanCenter,
  floorY: number,
): ExitLayerObjects {
  const root = new THREE.Group();
  const y0 = floorY - center.y;
  const overlay = (color: number, opacity: number) =>
    new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity,
      depthTest: false,
      depthWrite: false,
      side: THREE.DoubleSide,
      toneMapped: false,
    });
  const openMat = overlay(EXIT_OPEN, 0.9);
  const lostMat = overlay(FIRE_RED, 1);
  const selectedMat = overlay(EXIT_SELECTED, 1);
  const hitMat = new THREE.MeshBasicMaterial({ visible: false });
  const ringGeo = new THREE.RingGeometry(0.42, 0.6, 32);
  const fillGeo = new THREE.CircleGeometry(0.42, 24);
  const postGeo = new THREE.CylinderGeometry(0.045, 0.045, 2.1, 6);
  const hitGeo = new THREE.SphereGeometry(EXIT_HIT_M, 8, 6);
  const disposables = [openMat, lostMat, selectedMat, hitMat, ringGeo, fillGeo, postGeo, hitGeo];
  const hits: THREE.Mesh[] = [];
  const markers: ExitMarker[] = [];
  let selected: string | null = null;

  for (const g of groupExits(timeline)) {
    const meshes: THREE.Mesh[] = [];
    const fills: THREE.Mesh[] = [];
    const holders: THREE.Group[] = [];
    const mid = new THREE.Vector3();
    for (const [x, e, z] of g.points) {
      const holder = new THREE.Group();
      holder.position.set(x - center.x, y0 + e, z - center.z);
      mid.add(holder.position);
      const ring = new THREE.Mesh(ringGeo, openMat);
      ring.rotation.x = -Math.PI / 2;
      ring.position.y = 0.06;
      const fill = new THREE.Mesh(fillGeo, lostMat);
      fill.rotation.x = -Math.PI / 2;
      fill.position.y = 0.06;
      fill.visible = false;
      const post = new THREE.Mesh(postGeo, openMat);
      post.position.y = 1.05;
      const hit = new THREE.Mesh(hitGeo, hitMat);
      hit.position.y = 0.8;
      hit.userData = { exitKey: g.key };
      for (const m of [ring, fill, post]) m.renderOrder = 12;
      holder.add(ring, fill, post, hit);
      root.add(holder);
      meshes.push(ring, post);
      fills.push(fill);
      holders.push(holder);
      hits.push(hit);
    }
    mid.divideScalar(g.points.length);

    const el = document.createElement("div");
    el.className = `${LABEL_BASE} border-rule text-soft`;
    const name = document.createElement("span");
    name.className = "min-w-0 truncate";
    name.textContent = exitGroupName(g);
    name.title = exitGroupName(g);
    const status = document.createElement("span");
    status.className = "shrink-0 text-dim";
    el.append(name, status);
    const label = new CSS2DObject(el);
    label.center.set(0.5, 1);
    label.position.set(mid.x, mid.y + EXIT_LABEL_LIFT_M, mid.z);
    root.add(label);
    markers.push({ group: g, meshes, fills, holders, label: el, status, lost: null });
  }

  const paint = (m: ExitMarker) => {
    const isSelected = m.group.key === selected;
    const mat = m.lost ? lostMat : isSelected ? selectedMat : openMat;
    for (const mesh of m.meshes) mesh.material = mat;
    for (const fill of m.fills) fill.visible = Boolean(m.lost);
    for (const h of m.holders) h.scale.setScalar(isSelected ? 1.35 : 1);
    const border = isSelected ? "border-fg" : m.lost ? "border-fire/70" : "border-rule";
    const text = m.lost ? "text-fire" : isSelected ? "text-fg" : "text-soft";
    m.label.className = `${LABEL_BASE} ${border} ${text}`;
    m.status.className = m.lost ? "shrink-0 text-fire" : "shrink-0 text-dim";
  };

  const update = (tS: number) => {
    for (const m of markers) {
      const lost = m.group.blockedS !== null && tS >= m.group.blockedS;
      if (lost === m.lost) continue;
      m.lost = lost;
      m.status.textContent =
        lost && m.group.blockedS !== null
          ? `· lost ${formatLostClock(m.group.blockedS)}`
          : "· open";
      paint(m);
    }
  };

  update(0);

  return {
    group: root,
    update,
    setSelected: (key) => {
      if (key === selected) return;
      selected = key;
      for (const m of markers) paint(m);
    },
    pick: (raycaster) => {
      const hit = raycaster.intersectObjects(hits, false)[0];
      return hit ? (hit.object.userData.exitKey as string) : null;
    },
    dispose: () => {
      for (const d of disposables) d.dispose();
      for (const m of markers) m.label.remove();
      root.clear();
    },
  };
}

// ---------------------------------------------------------------------------------------------
// Routes: by default only the walks that leave people at risk; a selected room or exit shows
// its own. Aria's plan is white, a self-chosen route is red.

const ROUTE_PLAN = 0xeceef1;
const ROUTE_REACTIVE = FIRE_RED;
const ROUTE_LIFT_M = 0.3;
const ROUTE_PLAN_OPACITY = 0.95;
const ROUTE_REACTIVE_OPACITY = 0.9;
// Where a plan and a self-chosen route share a path, the red one runs alongside.
const ROUTE_TWIN_OFFSET_M = 0.32;
// Routes end at their exit plus a short stub outside, not at the engine's far-off safe point.
const EXIT_STUB_M = 1.8;
const ROUTE_FADE_MS = 600;

export type RouteFilter =
  { kind: "at_risk" } | { kind: "room"; id: string } | { kind: "exit"; doors: string[] };

export function routeMatches(route: FireRoute, filter: RouteFilter): boolean {
  if (filter.kind === "room") return route.space === filter.id;
  if (filter.kind === "exit") return route.exit !== null && filter.doors.includes(route.exit);
  return route.at_risk > 0;
}

/** The route's points up to its exit door, plus a short stub beyond it. */
function trimAtExit(timeline: FireTimeline, route: FireRoute): [number, number, number][] {
  const pts = route.points;
  const door = route.exit ? timeline.doors[route.exit]?.position : null;
  if (!door) return pts;
  const i = pts.findIndex(([x, z]) => Math.hypot(x - door.x, z - door.z) < 0.25);
  if (i < 0 || i >= pts.length - 1) return pts;
  const [x0, z0, e0] = pts[i];
  const [x1, z1, e1] = pts[i + 1];
  const k = Math.min(1, EXIT_STUB_M / (Math.hypot(x1 - x0, z1 - z0) || 1));
  return [...pts.slice(0, i + 1), [x0 + (x1 - x0) * k, z0 + (z1 - z0) * k, e0 + (e1 - e0) * k]];
}

export type FireRouteLayerObjects = {
  group: THREE.Group;
  show: (departure: FireRouteDeparture | null, filter: RouteFilter) => void;
  /** Fade a newly shown departure in (ms clock). */
  tick: (nowMs: number) => void;
  dispose: () => void;
};

type RouteObject = { departure: number; route: FireRoute; object: THREE.Group };

export function buildFireRouteLayer(
  timeline: FireTimeline,
  center: ScanCenter,
  floorY: number,
): FireRouteLayerObjects {
  const group = new THREE.Group();
  const y0 = floorY - center.y;
  const material = (color: number) =>
    new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: 0,
      depthTest: false,
      depthWrite: false,
      toneMapped: false,
    });
  const planMat = material(ROUTE_PLAN);
  const reactiveMat = material(ROUTE_REACTIVE);
  const arrowGeo = new THREE.ConeGeometry(0.3, 0.8, 12);
  const startGeo = new THREE.SphereGeometry(0.22, 12, 8);
  const disposables: Array<THREE.BufferGeometry | THREE.Material> = [
    planMat,
    reactiveMat,
    arrowGeo,
    startGeo,
  ];
  const objects: RouteObject[] = [];
  const up = new THREE.Vector3(0, 1, 0);

  for (const departure of timeline.routes?.departures ?? []) {
    const planPaths = new Set(
      departure.routes.filter((r) => r.kind === "plan").map((r) => JSON.stringify(r.points)),
    );
    for (const route of departure.routes) {
      const raw = trimAtExit(timeline, route);
      if (raw.length < 2) continue;
      const plan = route.kind === "plan";
      const twin = !plan && planPaths.has(JSON.stringify(route.points));
      const off = twin ? ROUTE_TWIN_OFFSET_M : 0;
      const pts = raw.map(
        ([x, z, e]) =>
          new THREE.Vector3(x - center.x + off, y0 + e + ROUTE_LIFT_M, z - center.z + off),
      );
      const path = new THREE.CurvePath<THREE.Vector3>();
      for (let i = 1; i < pts.length; i++) path.add(new THREE.LineCurve3(pts[i - 1], pts[i]));
      const geo = new THREE.TubeGeometry(
        path,
        Math.max(16, pts.length * 12),
        plan ? 0.08 : 0.065,
        6,
      );
      const mat = plan ? planMat : reactiveMat;
      const tube = new THREE.Mesh(geo, mat);
      const end = pts[pts.length - 1];
      const dir = end
        .clone()
        .sub(pts[pts.length - 2])
        .normalize();
      const arrow = new THREE.Mesh(arrowGeo, mat);
      arrow.position.copy(end);
      arrow.quaternion.setFromUnitVectors(up, dir);
      const start = new THREE.Mesh(startGeo, mat);
      start.position.copy(pts[0]);
      for (const m of [tube, arrow, start]) m.renderOrder = plan ? 9 : 8;
      const holder = new THREE.Group();
      holder.add(tube, arrow, start);
      holder.visible = false;
      group.add(holder);
      disposables.push(geo);
      objects.push({ departure: departure.t0_s, route, object: holder });
    }
  }

  let shownDeparture: number | null = null;
  let fadeFrom = 0;
  let fading = false;

  return {
    group,
    show: (departure, filter) => {
      const t0 = departure?.t0_s ?? null;
      if (t0 !== shownDeparture) {
        shownDeparture = t0;
        fading = true;
        fadeFrom = performance.now();
      }
      for (const o of objects) {
        o.object.visible = t0 !== null && o.departure === t0 && routeMatches(o.route, filter);
      }
    },
    tick: (nowMs) => {
      if (!fading) return;
      const k = Math.min(1, (nowMs - fadeFrom) / ROUTE_FADE_MS);
      planMat.opacity = ROUTE_PLAN_OPACITY * k;
      reactiveMat.opacity = ROUTE_REACTIVE_OPACITY * k;
      if (k >= 1) fading = false;
    },
    dispose: () => {
      for (const d of disposables) d.dispose();
      group.clear();
    },
  };
}

// White, so a found place stands apart from the red fire, grey smoke and the route colours.
const PLACE_PIN = 0xffffff;
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
