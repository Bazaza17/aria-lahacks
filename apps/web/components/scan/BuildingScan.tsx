"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import { USDZLoader } from "three/examples/jsm/loaders/USDZLoader.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js";

import { useScenario } from "@/components/building/ScenarioProvider";
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
import { PlaceSearch, type PlaceFound } from "./PlaceSearch";
import {
  buildFireLayer,
  buildFireRouteLayer,
  buildPlacePinLayer,
  resolvePlacePin,
  type FireLayerObjects,
  type FireRouteLayerObjects,
  type PlacePinLayerObjects,
} from "./scanSceneLayers";

// Scan meshes are too large for git: a building's scan comes from its buildings.scan_url
// (Supabase Storage). The local preview (/fire-preview) uses the four venue scans stitched in the
// venue frame, the same frame as the engine's output; that GLB is gitignored under public/scans.
const SCANS: Record<string, string | undefined> = {
  venue: "/scans/venue_4rooms_web.glb",
};

// Scan floor height in GLB coordinates, if the timeline doesn't give one.
const DEFAULT_FLOOR_Y = -0.85;

// A vague query ("door") can tie many places; pin this many and list the rest as a count.
const MAX_PLACE_PINS = 8;
// Camera pitch when it moves to a found place (radians above the horizon).
const PLACE_FOCUS_PITCH = 0.9;

type SceneBundle = {
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  renderer: THREE.WebGLRenderer;
  labelRenderer: CSS2DRenderer;
  controls: OrbitControls;
  fireRoot: THREE.Group;
  placeRoot: THREE.Group;
  /** The loaded scan itself, for snapping place pins onto its floor. */
  scan: THREE.Object3D;
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
  const scanUrl = SCANS[buildingId] ?? scanUrlProp ?? null;
  const mountRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<SceneBundle | null>(null);
  const fireLayerRef = useRef<FireLayerObjects | null>(null);
  const routeLayerRef = useRef<FireRouteLayerObjects | null>(null);
  const placeLayerRef = useRef<PlacePinLayerObjects | null>(null);

  const { fireTime, fireStart, setFireStart } = useScenario();
  const [fireTimeline, setFireTimeline] = useState<FireTimeline | null>(null);
  const [fireStarts, setFireStarts] = useState<FireStarts | null>(null);
  const [fireBusy, setFireBusy] = useState(false);
  const [fireFailed, setFireFailed] = useState(false);
  const [placeIndex, setPlaceIndex] = useState<PlaceIndex | null>(null);
  const [placeFound, setPlaceFound] = useState<PlaceFound | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const [interacted, setInteracted] = useState(false);
  const [vertexCount, setVertexCount] = useState<number | null>(null);

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
  const frame = fireTimeline ? frameAt(fireTimeline, fireTime) : null;
  const indicative = Boolean(frame?.beyond_screening);

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

      // Bright, even lighting so the scan reads well from every auto-rotate angle.
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

      const fireRoot = new THREE.Group();
      const placeRoot = new THREE.Group();
      scene.add(fireRoot, placeRoot);

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
          fireRoot,
          placeRoot,
          scan: group,
          meshCenter: center.clone(),
          dispose: () => {
            cancelAnimationFrame(raf);
            ro.disconnect();
            fireLayerRef.current?.dispose();
            routeLayerRef.current?.dispose();
            placeLayerRef.current?.dispose();
            controls.dispose();
            renderer.dispose();
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
        console.error("[building-scan] scan load failed", err);
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
      fireLayerRef.current = null;
      routeLayerRef.current = null;
      placeLayerRef.current = null;
      while (mount.firstChild) mount.removeChild(mount.firstChild);
    };
  }, [scanUrl]);

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

  if (!scanUrl) {
    return (
      <section className="relative flex h-full flex-col gap-2 bg-[#0a0a0a] p-3">
        <div className="flex flex-1 items-center justify-center rounded-sm border border-red-500/30 bg-black/60 p-6 text-center font-mono text-[10px] leading-relaxed tracking-[0.2em]">
          <div>
            <p className="text-red-300/90">NO LIDAR SCAN FOR THIS BUILDING</p>
            <p className="mt-3 text-white/40">
              upload the scan to the scans bucket
              <br />
              set buildings.scan_url for this building
              <br />
              open the venue from the dashboard
            </p>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="relative flex h-full flex-col gap-2 bg-[#0a0a0a] p-3">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 font-mono text-[10px] tracking-[0.3em]">
        <div className="flex items-center gap-2 text-[#ff6b00]/80">
          <span className="h-1 w-1 bg-[#ff6b00]" />
          1F SCANNED (4 ROOMS) · UPPER FLOORS FROM FLOOR PLAN
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {fireTimeline && (
            <span className="text-[#ffb27a]">
              FIRE T+{formatClock(fireTime)}
              {fireEvent ? ` · ${fireEvent.detail.toUpperCase()}` : ""}
            </span>
          )}
          {indicative && (
            <span className="rounded-sm border border-amber-300/40 px-1.5 text-amber-200">
              INDICATIVE AFTER FLASHOVER
            </span>
          )}
          {departure && (
            <span className="text-sky-300/90">
              LEAVE AT T+{formatClock(departure.t0_s)} · AT RISK {departure.at_risk.plan} ARIA /{" "}
              {departure.at_risk.reactive} SELF-CHOSEN
            </span>
          )}
          <span className="text-white/30">
            {failed ? "SCAN UNAVAILABLE" : loaded ? "READY" : "LOADING"}
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
            SCAN COULD NOT LOAD
          </div>
        )}

        {loaded && !failed && (
          <div className="pointer-events-auto absolute left-3 top-3 z-20 flex flex-col gap-2">
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
          </div>
        )}

        {loaded && !failed && (
          <ScanMetadata
            vertexCount={vertexCount}
            hasFire={Boolean(fireTimeline)}
            verified={fireTimeline?.verified ?? false}
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

function formatVertices(count: number | null): string {
  if (!count) return "—";
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M VERTICES`;
  return `${Math.round(count / 1000)}K VERTICES`;
}

/** What the model on screen is made of: true values only. */
function ScanMetadata({
  vertexCount,
  hasFire,
  verified,
}: {
  vertexCount: number | null;
  hasFire: boolean;
  verified: boolean;
}) {
  return (
    <div className="pointer-events-none absolute bottom-3 left-3 max-w-[320px] rounded-md border border-white/[0.08] bg-black/70 px-3 py-2 font-mono text-[10px] leading-relaxed backdrop-blur">
      <Row label="SCAN" value="PHONE LIDAR · 4 ROOMS OF THE 1F" />
      <Row label="STITCH" value="ABOUT ±0.3 M AT THE JOINS" />
      <Row label="MESH" value={formatVertices(vertexCount)} />
      <Row label="REST" value="FLOOR PLAN · DASHED OUTLINES" />
      {hasFire && (
        <Row label="FIRE" value={verified ? "ENGINE · VERIFIED" : "ENGINE · SCREENING MODEL"} />
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-3 whitespace-nowrap">
      <span className="w-16 shrink-0 tracking-[0.2em] text-[#ff6b00]/70">{label}</span>
      <span className="text-white/85">{value}</span>
    </div>
  );
}
