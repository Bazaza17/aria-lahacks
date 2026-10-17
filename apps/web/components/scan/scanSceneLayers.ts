import * as THREE from "three";
import { CSS2DObject } from "three/examples/jsm/renderers/CSS2DRenderer.js";

import type { MeshSize } from "@/lib/scan-coords";
import type { ResolvedExit, ResolvedRoute } from "@/lib/scan-evac-paths";
import { exitWorldPosition } from "@/lib/scan-evac-paths";
import { waterWorldY } from "@/lib/scan-flood";

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
