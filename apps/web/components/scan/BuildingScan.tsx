"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { CSS2DObject, CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import { USDZLoader } from "three/examples/jsm/loaders/USDZLoader.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js";

import { useAgentRun } from "@/components/agent/AgentRunProvider";
import { useScenario } from "@/components/building/ScenarioProvider";
import {
  anchorToWorld,
  createPinElement,
  filterPins,
  hazardPinCounts,
  pinsFromReport,
  type HazardFilter,
  type ScanHazardPin,
} from "@/lib/scan-hazard-pins";
import { hasEvacPlan, openExitCount, resolveEvacPlan } from "@/lib/scan-evac-paths";
import {
  departureAt,
  formatClock,
  frameAt,
  latestEvent,
  loadFireStarts,
  loadFireTimeline,
  type FireStarts,
  type FireTimeline,
} from "@/lib/scan-fire";
import { loadPlaceIndex, searchPlaces, type PlaceIndex } from "@/lib/scan-places";

import { FireStartPicker } from "./FireStartPicker";
import { HazardPinFilter } from "./HazardPinFilter";
import { PlaceSearch, type PlaceFound } from "./PlaceSearch";
import { ScanViewToolbar } from "./ScanViewToolbar";
import {
  buildEvacLayer,
  buildFireLayer,
  buildFireRouteLayer,
  buildPlacePinLayer,
  resolvePlacePin,
  type EvacLayerObjects,
  type FireLayerObjects,
  type FireRouteLayerObjects,
  type PlacePinLayerObjects,
} from "./scanSceneLayers";

export type ScanViewMode = "default" | "evac" | "hazards";

// Scan meshes are too large for git, so The Dock's USDZ is served from the
// public `scans` bucket in Supabase Storage (derived from the same
// NEXT_PUBLIC_SUPABASE_URL the rest of the app uses). The legacy buildings
// keep their local public/ USDZ paths.
const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL?.replace(/\/$/, "");

function storageUrl(path: string): string | undefined {
  return SUPABASE_URL ? `${SUPABASE_URL}/storage/v1/object/public/${path}` : undefined;
}

const SCANS: Record<string, string | undefined> = {
  "014b39a9-09b8-432b-9b62-363e06383d1f": "/scans/building_a/scan.usdz",
  "870d979d-6eaf-4d7f-894a-8ca34e527237": "/scans/building_b/scan.usdz",
  "e5a3fddc-e22c-431c-a5d3-ee29ef8604d1": storageUrl("scans/the_dock/scan.usdz"),
  // Local preview (/fire-preview): the four venue scans stitched in the venue frame, the same
  // frame as public/fire/venue.json. The GLB is gitignored under public/scans.
  venue: "/scans/venue_4rooms_web.glb",
};

// Scan floor height in GLB coordinates, if the timeline doesn't give one.
const DEFAULT_FLOOR_Y = -0.85;

const PIN_REVEAL_MS = 180;
// A vague query ("door") can tie many places; pin this many and list the rest as a count.
const MAX_PLACE_PINS = 8;
// Camera pitch when it moves to a found place (radians above the horizon).
const PLACE_FOCUS_PITCH = 0.9;
const SEVERITY_GLOW: Record<string, number> = {
  LOW: 0.35,
  MODERATE: 0.55,
  HIGH: 0.75,
  SEVERE: 1,
};

type SceneBundle = {
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  renderer: THREE.WebGLRenderer;
  labelRenderer: CSS2DRenderer;
  controls: OrbitControls;
  pinRoot: THREE.Group;
  evacRoot: THREE.Group;
  fireRoot: THREE.Group;
  placeRoot: THREE.Group;
  /** The loaded scan itself, for snapping place pins onto its floor. */
  scan: THREE.Object3D;
  meshSize: THREE.Vector3;
  meshCenter: THREE.Vector3;
  dispose: () => void;
};

export function BuildingScan({
  buildingId,
  scanUrl: scanUrlProp,
}: {
  buildingId: string;
  scanUrl?: string | null;
}) {
  // Prefer the hardcoded map (kept in sync with Supabase Storage) over the DB
  // value so a stale buildings.scan_url can't override the working asset.
  const scanUrl = SCANS[buildingId] ?? scanUrlProp ?? null;
  const mountRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<SceneBundle | null>(null);
  const pinObjectsRef = useRef<THREE.Object3D[]>([]);
  const evacLayerRef = useRef<EvacLayerObjects | null>(null);
  const fireLayerRef = useRef<FireLayerObjects | null>(null);
  const routeLayerRef = useRef<FireRouteLayerObjects | null>(null);
  const placeLayerRef = useRef<PlacePinLayerObjects | null>(null);
  const animatedPinIdsRef = useRef(new Set<string>());
  const viewModeRef = useRef<ScanViewMode>("default");

  const { report, running } = useAgentRun();
  const { surge, fireTime } = useScenario();
  const [fireTimeline, setFireTimeline] = useState<FireTimeline | null>(null);
  const [fireStarts, setFireStarts] = useState<FireStarts | null>(null);
  const [fireStart, setFireStart] = useState<string | null>(null);
  const [fireBusy, setFireBusy] = useState(false);
  const [fireFailed, setFireFailed] = useState(false);
  const [placeIndex, setPlaceIndex] = useState<PlaceIndex | null>(null);
  const [placeFound, setPlaceFound] = useState<PlaceFound | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const [interacted, setInteracted] = useState(false);
  const [vertexCount, setVertexCount] = useState<number | null>(null);
  const [hazardFilter, setHazardFilter] = useState<HazardFilter>("all");
  const [revealedCount, setRevealedCount] = useState(0);
  const [indexing, setIndexing] = useState(false);
  const [viewMode, setViewMode] = useState<ScanViewMode>(() =>
    hasEvacPlan(buildingId) ? "evac" : "default",
  );

  viewModeRef.current = viewMode;

  const allPins = useMemo(
    () => (report ? pinsFromReport(report, buildingId) : []),
    [report, buildingId],
  );
  const pinCounts = useMemo(() => hazardPinCounts(allPins), [allPins]);
  const visiblePins = useMemo(() => filterPins(allPins, hazardFilter), [allPins, hazardFilter]);

  const evacPlan = useMemo(() => {
    if (!loaded || !hasEvacPlan(buildingId) || !sceneRef.current) return null;
    const size = sceneRef.current.meshSize;
    return resolveEvacPlan(buildingId, surge, {
      x: size.x,
      y: size.y,
      z: size.z,
    });
  }, [buildingId, surge, loaded]);

  useEffect(() => {
    let cancelled = false;
    void loadFireStarts(buildingId).then((s) => {
      if (!cancelled) setFireStarts(s);
    });
    return () => {
      cancelled = true;
    };
  }, [buildingId]);

  // The engine's run for the chosen start (the API's default until one is picked). The last
  // timeline stays on screen while a new start runs.
  useEffect(() => {
    let cancelled = false;
    setFireBusy(true);
    void loadFireTimeline(buildingId, fireStart ?? undefined).then((t) => {
      if (cancelled) return;
      if (t) setFireTimeline(t);
      setFireFailed(!t);
      setFireBusy(false);
    });
    return () => {
      cancelled = true;
    };
  }, [buildingId, fireStart]);

  useEffect(() => {
    let cancelled = false;
    void loadPlaceIndex(buildingId).then((index) => {
      if (!cancelled) setPlaceIndex(index);
    });
    return () => {
      cancelled = true;
    };
  }, [buildingId]);

  const clearPlacePins = () => {
    const layer = placeLayerRef.current;
    if (!layer) return;
    sceneRef.current?.placeRoot.remove(layer.group);
    layer.dispose();
    placeLayerRef.current = null;
  };

  // One search: run it, snap each match onto the scan floor (one raycast pass), pin, focus.
  const findPlace = (query: string) => {
    const bundle = sceneRef.current;
    if (!bundle || !placeIndex) return;
    clearPlacePins();
    const result = searchPlaces(placeIndex, query);
    const floorY = fireTimeline?.scan.floor_y ?? placeIndex.frame.floor_y ?? DEFAULT_FLOOR_Y;
    const pins = result.matches
      .slice(0, MAX_PLACE_PINS)
      .map((m) => resolvePlacePin(m, bundle.scan, bundle.meshCenter, floorY));
    if (pins.length > 0) {
      const layer = buildPlacePinLayer(pins, bundle.meshCenter);
      bundle.placeRoot.add(layer.group);
      placeLayerRef.current = layer;
      focusCamera(
        bundle,
        pins.map((p) => p.at),
      );
    }
    setPlaceFound({ result, pins });
  };

  const handlePlaceClear = () => {
    clearPlacePins();
    setPlaceFound(null);
  };

  const fireEvent = fireTimeline ? latestEvent(fireTimeline, fireTime) : null;
  const departure = fireTimeline ? departureAt(fireTimeline, fireTime) : null;

  useEffect(() => {
    if (!report || allPins.length === 0) {
      setRevealedCount(0);
      setIndexing(false);
      return;
    }

    animatedPinIdsRef.current = new Set();
    setIndexing(true);
    setRevealedCount(allPins.length > 0 ? 1 : 0);

    if (allPins.length <= 1) {
      setIndexing(false);
      return;
    }

    let count = 1;
    const interval = window.setInterval(() => {
      count += 1;
      setRevealedCount(count);
      if (count >= allPins.length) {
        setIndexing(false);
        window.clearInterval(interval);
      }
    }, PIN_REVEAL_MS);

    return () => window.clearInterval(interval);
  }, [report, allPins.length]);

  useEffect(() => {
    if (!scanUrl) return;
    const mount = mountRef.current;
    if (!mount) return;

    let cancelled = false;
    let raf = 0;
    let cleanupScene: (() => void) | null = null;

    void (async () => {
      const width = mount.clientWidth || 400;
      const height = mount.clientHeight || 230;

      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(45, width / height, 0.05, 500);
      camera.position.set(0, 0.4, 2.2);

      const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.setSize(width, height);
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.0;
      mount.appendChild(renderer.domElement);

      const labelRenderer = new CSS2DRenderer();
      labelRenderer.setSize(width, height);
      labelRenderer.domElement.style.position = "absolute";
      labelRenderer.domElement.style.inset = "0";
      labelRenderer.domElement.style.pointerEvents = "none";
      mount.appendChild(labelRenderer.domElement);

      // Bright, even lighting so the scan reads well from every auto-rotate
      // angle (no dark side).
      scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 1.6));
      scene.add(new THREE.AmbientLight(0xffffff, 0.7));
      const key = new THREE.DirectionalLight(0xffffff, 1.1);
      key.position.set(3, 4, 2);
      scene.add(key);
      const fill = new THREE.DirectionalLight(0xffffff, 0.9);
      fill.position.set(-3, 2, -3);
      scene.add(fill);

      const controls = new OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      controls.dampingFactor = 0.08;
      controls.autoRotate = true;
      controls.autoRotateSpeed = 0.8;
      controls.addEventListener("start", () => {
        controls.autoRotate = false;
        setInteracted(true);
      });

      const pinRoot = new THREE.Group();
      const evacRoot = new THREE.Group();
      const fireRoot = new THREE.Group();
      const placeRoot = new THREE.Group();
      scene.add(fireRoot, evacRoot, pinRoot, placeRoot);

      const isGltf = /\.(glb|gltf)(\?|$)/i.test(scanUrl);
      try {
        const group = isGltf
          ? (await new GLTFLoader().setMeshoptDecoder(MeshoptDecoder).loadAsync(scanUrl)).scene
          : await new USDZLoader().loadAsync(scanUrl);
        if (cancelled) return;

        const box = new THREE.Box3().setFromObject(group);
        const center = box.getCenter(new THREE.Vector3());
        const size = box.getSize(new THREE.Vector3());
        group.position.sub(center);
        scene.add(group);

        const maxDim = Math.max(size.x, size.y, size.z) || 1;
        const fov = (camera.fov * Math.PI) / 180;
        const aspect = mount.clientWidth / mount.clientHeight;
        const distH = maxDim / (2 * Math.tan(fov / 2));
        const distW = distH / aspect;
        const dist = 1.15 * Math.max(distH, distW);

        const cinematic = new THREE.Vector3(0.55, 0.4, 1).normalize();
        camera.position.copy(cinematic.multiplyScalar(dist));
        camera.near = Math.max(0.001, dist / 500);
        camera.far = dist * 50;
        camera.updateProjectionMatrix();
        camera.lookAt(0, 0, 0);
        controls.target.set(0, 0, 0);
        controls.minDistance = dist * 0.3;
        controls.maxDistance = dist * 4;
        controls.update();

        let verts = 0;
        group.traverse((obj) => {
          if ((obj as THREE.Mesh).isMesh) {
            const attr = (obj as THREE.Mesh).geometry?.attributes?.position;
            if (attr) verts += attr.count;
          }
        });
        setVertexCount(verts);
        setLoaded(true);

        sceneRef.current = {
          scene,
          camera,
          renderer,
          labelRenderer,
          controls,
          pinRoot,
          evacRoot,
          fireRoot,
          placeRoot,
          scan: group,
          meshSize: size.clone(),
          meshCenter: center.clone(),
          dispose: () => {
            cancelAnimationFrame(raf);
            ro.disconnect();
            evacLayerRef.current?.dispose();
            fireLayerRef.current?.dispose();
            placeLayerRef.current?.dispose();
            controls.dispose();
            renderer.dispose();
            pinRoot.clear();
            evacRoot.clear();
            fireRoot.clear();
            placeRoot.clear();
            scene.clear();
            if (renderer.domElement.parentNode === mount) {
              mount.removeChild(renderer.domElement);
            }
            if (labelRenderer.domElement.parentNode === mount) {
              mount.removeChild(labelRenderer.domElement);
            }
          },
        };
      } catch (err) {
        console.error("[building-scan] USDZ load failed", err);
        if (!cancelled) setFailed(true);
        renderer.dispose();
        if (renderer.domElement.parentNode === mount) {
          mount.removeChild(renderer.domElement);
        }
        if (labelRenderer.domElement.parentNode === mount) {
          mount.removeChild(labelRenderer.domElement);
        }
        return;
      }

      const onResize = () => {
        const w = mount.clientWidth;
        const h = mount.clientHeight;
        if (w === 0 || h === 0) return;
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
        renderer.setSize(w, h);
        labelRenderer.setSize(w, h);
      };
      const ro = new ResizeObserver(onResize);
      ro.observe(mount);

      const tick = () => {
        controls.update();
        renderer.render(scene, camera);
        labelRenderer.render(scene, camera);
        raf = requestAnimationFrame(tick);
      };
      tick();

      cleanupScene = () => {
        sceneRef.current?.dispose();
        sceneRef.current = null;
      };
    })();

    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      cleanupScene?.();
      pinObjectsRef.current = [];
      evacLayerRef.current = null;
      fireLayerRef.current = null;
      placeLayerRef.current = null;
      while (mount.firstChild) mount.removeChild(mount.firstChild);
    };
  }, [scanUrl]);

  // Evac routes + exit markers
  useEffect(() => {
    const bundle = sceneRef.current;
    if (!bundle || !loaded || viewMode !== "evac") {
      evacLayerRef.current?.dispose();
      evacLayerRef.current = null;
      bundle?.evacRoot.clear();
      return;
    }

    const plan = resolveEvacPlan(buildingId, surge, {
      x: bundle.meshSize.x,
      y: bundle.meshSize.y,
      z: bundle.meshSize.z,
    });
    if (!plan) return;

    evacLayerRef.current?.dispose();
    bundle.evacRoot.clear();

    const layer = buildEvacLayer(plan.routes, plan.exits, {
      x: bundle.meshSize.x,
      y: bundle.meshSize.y,
      z: bundle.meshSize.z,
    });
    bundle.evacRoot.add(layer.group);
    evacLayerRef.current = layer;
  }, [buildingId, surge, loaded, viewMode]);

  // Fire layer: built once per timeline, updated as fireTime changes
  useEffect(() => {
    const bundle = sceneRef.current;
    if (!bundle || !loaded || !fireTimeline) return;
    const floorY = fireTimeline.scan.floor_y ?? DEFAULT_FLOOR_Y;
    const layer = buildFireLayer(fireTimeline, bundle.meshCenter, floorY);
    const routes = buildFireRouteLayer(fireTimeline, bundle.meshCenter, floorY);
    bundle.fireRoot.add(layer.group, routes.group);
    fireLayerRef.current = layer;
    routeLayerRef.current = routes;
    return () => {
      bundle.fireRoot.remove(layer.group, routes.group);
      layer.dispose();
      routes.dispose();
      if (fireLayerRef.current === layer) fireLayerRef.current = null;
      if (routeLayerRef.current === routes) routeLayerRef.current = null;
    };
  }, [loaded, fireTimeline]);

  useEffect(() => {
    if (!fireTimeline) return;
    fireLayerRef.current?.update(frameAt(fireTimeline, fireTime));
    routeLayerRef.current?.show(departureAt(fireTimeline, fireTime));
  }, [fireTimeline, fireTime, loaded]);

  // Hazard pins (hazards mode only)
  useEffect(() => {
    const bundle = sceneRef.current;
    if (!bundle || !loaded) return;

    for (const obj of pinObjectsRef.current) {
      bundle.pinRoot.remove(obj);
      disposePinObject(obj);
    }
    pinObjectsRef.current = [];

    if (viewMode !== "hazards" || !report || allPins.length === 0) return;

    const revealedIds = new Set(allPins.slice(0, revealedCount).map((p) => p.id));
    const size = {
      x: bundle.meshSize.x,
      y: bundle.meshSize.y,
      z: bundle.meshSize.z,
    };

    visiblePins.forEach((pin) => {
      const isRevealed = revealedIds.has(pin.id);
      const shouldAnimate = isRevealed && !animatedPinIdsRef.current.has(pin.id);
      if (shouldAnimate) animatedPinIdsRef.current.add(pin.id);

      const world = anchorToWorld(pin.anchor, size);
      const pinGroup = buildPinObject(pin, world, size, isRevealed, shouldAnimate);
      bundle.pinRoot.add(pinGroup);
      pinObjectsRef.current.push(pinGroup);
    });
  }, [loaded, report, allPins, visiblePins, revealedCount, viewMode]);

  const pinBadge =
    allPins.length > 0 && viewMode === "hazards"
      ? `${allPins.length} HAZARD PIN${allPins.length === 1 ? "" : "S"}`
      : running
        ? "AGENT RUNNING"
        : null;

  const evacOpen = evacPlan ? openExitCount(evacPlan) : 0;
  const evacTotal = evacPlan?.exits.length ?? 0;

  if (!scanUrl) {
    return (
      <section className="relative flex h-full flex-col gap-2 bg-[#0a0a0a] p-3">
        <div className="flex flex-1 items-center justify-center rounded-sm border border-red-500/30 bg-black/60 p-6 text-center font-mono text-[10px] leading-relaxed tracking-[0.2em]">
          <div>
            <p className="text-red-300/90">NO LIDAR SCAN · WRONG BUILDING ID</p>
            <p className="mt-3 text-white/40">
              upload the scan to the scans bucket
              <br />
              add its URL for this building in BuildingScan.tsx
              <br />
              open the venue from dashboard
            </p>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="relative flex h-full flex-col gap-2 bg-[#0a0a0a] p-3">
      <div className="flex items-center justify-between font-mono text-[10px] tracking-[0.3em]">
        <div className="flex items-center gap-2 text-[#ff6b00]/80">
          <span className="h-1 w-1 bg-[#ff6b00]" />
          3D SCAN · LIDAR CAPTURE
        </div>
        <div className="flex items-center gap-3">
          {pinBadge && (
            <span className={allPins.length > 0 ? "text-[#ffb27a]" : "animate-pulse text-white/40"}>
              {pinBadge}
            </span>
          )}
          {fireTimeline && (
            <span className="text-[#ffb27a]">
              FIRE T+{formatClock(fireTime)}
              {fireEvent ? ` · ${fireEvent.detail.toUpperCase()}` : ""}
            </span>
          )}
          {departure && (
            <span className="text-sky-300/90">
              LEAVE AT T+{formatClock(departure.t0_s)} · AT RISK {departure.at_risk.plan} ARIA /{" "}
              {departure.at_risk.reactive} SELF-CHOSEN
            </span>
          )}
          {viewMode === "evac" && evacPlan && (
            <span className="text-emerald-300/90">
              EVAC · {evacOpen}/{evacTotal} OPEN
            </span>
          )}
          <span className="text-white/30">
            {failed ? "PROCESSING" : loaded ? "READY" : "LOADING"}
          </span>
        </div>
      </div>

      <div className="relative min-h-0 flex-1 overflow-hidden rounded-sm border border-[#ff6b00]/20 bg-black/60">
        <div
          ref={mountRef}
          className="absolute inset-0"
          style={{
            transition: "opacity 400ms ease-out",
            opacity: loaded ? 1 : 0,
          }}
        />

        {!loaded && !failed && (
          <div className="absolute inset-0 flex items-center justify-center font-mono text-[10px] tracking-[0.3em] text-white/30">
            DECODING SCAN…
          </div>
        )}
        {failed && (
          <div className="absolute inset-0 flex items-center justify-center font-mono text-[10px] tracking-[0.3em] text-white/40">
            SCAN PROCESSING…
          </div>
        )}

        {loaded && !failed && (
          <ScanViewToolbar
            mode={viewMode}
            onModeChange={setViewMode}
            buildingId={buildingId}
            evacOpenCount={evacOpen}
            evacTotal={evacTotal}
          >
            {fireStarts && (
              <FireStartPicker
                starts={fireStarts.starts}
                value={fireStart ?? fireTimeline?.start_room ?? fireStarts.default}
                busy={fireBusy}
                failed={fireFailed}
                onChange={setFireStart}
              />
            )}
            {placeIndex && (
              <PlaceSearch found={placeFound} onSearch={findPlace} onClear={handlePlaceClear} />
            )}
          </ScanViewToolbar>
        )}

        {loaded && !failed && viewMode === "hazards" && allPins.length > 0 && (
          <HazardPinFilter
            filter={hazardFilter}
            onFilterChange={setHazardFilter}
            counts={pinCounts}
            indexing={indexing}
          />
        )}

        {loaded && !failed && (
          <ScanMetadata
            vertexCount={vertexCount}
            pinCount={viewMode === "hazards" ? allPins.length : 0}
            revealedCount={revealedCount}
            evacPlan={viewMode === "evac" ? evacPlan : null}
          />
        )}

        {loaded && !interacted && !failed && (
          <div className="pointer-events-none absolute bottom-3 right-4 font-mono text-[9px] tracking-[0.3em] text-white/40">
            DRAG TO ROTATE · SCROLL TO ZOOM
          </div>
        )}
      </div>
    </section>
  );
}

function buildPinObject(
  pin: ScanHazardPin,
  world: { x: number; y: number; z: number },
  size: { x: number; y: number; z: number },
  visible: boolean,
  animate: boolean,
): THREE.Group {
  const group = new THREE.Group();
  group.position.set(world.x, world.y, world.z);

  const markerScale = Math.max(size.x, size.y, size.z) * 0.006 || 0.012;
  const glow = SEVERITY_GLOW[pin.severity] ?? 0.5;
  const dotGeo = new THREE.SphereGeometry(markerScale, 10, 10);
  const dotMat = new THREE.MeshBasicMaterial({
    color: severityHex(pin.severity),
    transparent: true,
    opacity: 0.95,
  });
  group.add(new THREE.Mesh(dotGeo, dotMat));

  const ringGeo = new THREE.RingGeometry(markerScale * 1.5, markerScale * 2.3, 24);
  const ringMat = new THREE.MeshBasicMaterial({
    color: severityHex(pin.severity),
    transparent: true,
    opacity: 0.35 * glow,
    side: THREE.DoubleSide,
  });
  const ring = new THREE.Mesh(ringGeo, ringMat);
  ring.rotation.x = -Math.PI / 2;
  group.add(ring);

  const labelEl = createPinElement(pin, {
    hidden: !visible,
    animate: visible && animate,
  });
  const label = new CSS2DObject(labelEl);
  label.position.set(0, markerScale * 5, 0);
  group.add(label);

  return group;
}

/** Look down at a set of points from the current heading, close enough to see them all. */
function focusCamera({ camera, controls }: SceneBundle, points: THREE.Vector3[]) {
  const box = new THREE.Box3().setFromPoints(points);
  const target = box.getCenter(new THREE.Vector3());
  const spread = box.getSize(new THREE.Vector3()).length();
  const dist = THREE.MathUtils.clamp(spread * 1.5 + 12, controls.minDistance, controls.maxDistance);
  const heading = camera.position.clone().sub(controls.target).setY(0).normalize();
  const dir = heading.multiplyScalar(Math.cos(PLACE_FOCUS_PITCH)).setY(Math.sin(PLACE_FOCUS_PITCH));
  controls.autoRotate = false;
  controls.target.copy(target);
  camera.position.copy(target).addScaledVector(dir, dist);
  controls.update();
}

function disposePinObject(obj: THREE.Object3D) {
  obj.traverse((child) => {
    if ((child as THREE.Mesh).isMesh) {
      const mesh = child as THREE.Mesh;
      mesh.geometry?.dispose();
      const mat = mesh.material;
      if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
      else mat?.dispose();
    }
  });
}

function severityHex(severity: ScanHazardPin["severity"]): number {
  const map: Record<ScanHazardPin["severity"], number> = {
    LOW: 0xd1d5db,
    MODERATE: 0xfbbf24,
    HIGH: 0xff6b00,
    SEVERE: 0xef4444,
  };
  return map[severity];
}

function ScanMetadata({
  vertexCount,
  pinCount,
  revealedCount,
  evacPlan,
}: {
  vertexCount: number | null;
  pinCount: number;
  revealedCount: number;
  evacPlan: ReturnType<typeof resolveEvacPlan> | null;
}) {
  const vertsLabel = vertexCount
    ? vertexCount >= 1_000_000
      ? `${(vertexCount / 1_000_000).toFixed(1)}M VERTICES`
      : `${Math.round(vertexCount / 1000)}K VERTICES`
    : "180K VERTICES";

  return (
    <div className="pointer-events-none absolute bottom-3 left-3 max-w-[280px] rounded-md border border-white/[0.08] bg-black/70 px-3 py-2 font-mono text-[10px] leading-relaxed backdrop-blur">
      <Row label="CAPTURE" value="PHONE LIDAR · 5 MIN" />
      <Row label="MESH" value={vertsLabel} />
      {pinCount > 0 && (
        <Row label="HAZARDS" value={`${Math.min(revealedCount, pinCount)}/${pinCount} INDEXED`} />
      )}
      {evacPlan && (
        <Row label="EVAC" value={`${openExitCount(evacPlan)}/${evacPlan.exits.length} EXITS`} />
      )}
      <Row label="ACCURACY" value="±5CM" />
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-3 whitespace-nowrap">
      <span className="w-20 shrink-0 tracking-[0.2em] text-[#ff6b00]/70">{label}</span>
      <span className="text-white/85">{value}</span>
    </div>
  );
}
