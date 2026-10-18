"use client";

import { useEffect, useMemo, useRef, useState } from "react";
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
  type FireRoute,
  type FireRouteDeparture,
  type FireStarts,
  type FireTimeline,
} from "@/lib/scan-fire";
import { loadPlaceIndex, searchPlaces, type PlaceIndex } from "@/lib/scan-places";

import { PlaceSearch, type PlaceFound } from "./PlaceSearch";
import {
  buildExitLayer,
  buildFireLayer,
  buildFireRouteLayer,
  buildPlacePinLayer,
  groupExits,
  resolvePlacePin,
  scanCropBox,
  setCropPlanes,
  exitGroupName,
  formatLostClock,
  type ExitGroup,
  type ExitLayerObjects,
  type FireLayerObjects,
  type FireRouteLayerObjects,
  type PlacePinLayerObjects,
  type RouteFilter,
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
// Default view: square to the venue frame (its axes run along the building's main walls),
// looking down at this pitch, close enough that the footprint fills the frame.
const VIEW_PITCH = 0.92;
const VIEW_FILL = 0.92;
const VIEW_TARGET_LIFT_M = 1.5;
// Aim a little past the middle so the building sits below the headline.
const VIEW_TARGET_FAR = 0.1;
// The phone scans are dim indoors; lift them a little (linear multiplier on the texture).
const SCAN_GAIN = 1.45;
// A click, not a drag: the pointer moved less than this and came up quickly.
const CLICK_SLOP_PX = 6;
const CLICK_MAX_MS = 600;

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
  /** Shared by every scan material; set to the crop box once the venue's rooms are known. */
  cropPlanes: THREE.Plane[];
  /** The box the default view frames (the crop box once known). */
  viewBox: THREE.Box3;
  viewFloorY: number;
  dispose: () => void;
};

/** What the viewer has clicked on the scan: a room (by venue id) or an exit group. */
type ScanSelection = { kind: "room"; id: string } | { kind: "exit"; key: string };

/** The start space's plan name up to the first " (": "Collins Room, part 140". */
function fireStartName(timeline: FireTimeline | null, starts: FireStarts | null): string | null {
  if (!timeline) return null;
  const id = timeline.start_room;
  const name = starts?.starts.find((s) => s.id === id)?.label ?? timeline.rooms[id]?.name ?? id;
  return name.split(" (")[0];
}

/** Square-on 3/4 view of a box: the building's walls run with the screen edges. */
function frameView({ camera, controls }: SceneBundle, box: THREE.Box3, floorY: number) {
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const target = new THREE.Vector3(
    center.x,
    floorY + VIEW_TARGET_LIFT_M,
    center.z - VIEW_TARGET_FAR * size.z,
  );
  const radius = 0.5 * Math.hypot(size.x, size.z);
  const vfov = (camera.fov * Math.PI) / 180;
  const hfov = 2 * Math.atan(Math.tan(vfov / 2) * camera.aspect);
  const dist = (VIEW_FILL * radius) / Math.tan(Math.min(vfov, hfov) / 2);
  const dir = new THREE.Vector3(0, Math.sin(VIEW_PITCH), Math.cos(VIEW_PITCH));
  controls.target.copy(target);
  camera.position.copy(target).addScaledVector(dir, dist);
  camera.near = Math.max(0.01, dist / 300);
  camera.far = dist * 30;
  camera.updateProjectionMatrix();
  controls.minDistance = dist * 0.12;
  controls.maxDistance = dist * 3;
  controls.update();
}

export function BuildingScan({
  buildingId,
  scanUrl: scanUrlProp,
  buildingName,
}: {
  buildingId: string;
  scanUrl?: string | null;
  buildingName?: string;
}) {
  const scanUrl = SCANS[buildingId] ?? scanUrlProp ?? null;
  const mountRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<SceneBundle | null>(null);
  const fireLayerRef = useRef<FireLayerObjects | null>(null);
  const routeLayerRef = useRef<FireRouteLayerObjects | null>(null);
  const exitLayerRef = useRef<ExitLayerObjects | null>(null);
  const placeLayerRef = useRef<PlacePinLayerObjects | null>(null);
  const interactedRef = useRef(false);

  const { fireTime, fireTimeline, fireStarts } = useScenario();
  const [placeIndex, setPlaceIndex] = useState<PlaceIndex | null>(null);
  const [placeFound, setPlaceFound] = useState<PlaceFound | null>(null);
  const [selection, setSelection] = useState<ScanSelection | null>(null);
  // Exit name labels: off by default to keep the scan calm; one button shows them all.
  const [showExitNames, setShowExitNames] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const [interacted, setInteracted] = useState(false);
  const [vertexCount, setVertexCount] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    void loadPlaceIndex(buildingId).then((index) => {
      if (!cancelled) setPlaceIndex(index);
    });
    return () => {
      cancelled = true;
    };
  }, [buildingId]);

  const exitGroups = useMemo(() => (fireTimeline ? groupExits(fireTimeline) : []), [fireTimeline]);
  const departure = fireTimeline ? departureAt(fireTimeline, fireTime) : null;

  // A selection that no longer exists in this run (a new start) is dropped.
  const liveSelection =
    selection &&
    ((selection.kind === "room" && fireTimeline?.rooms[selection.id]) ||
      (selection.kind === "exit" && exitGroups.some((g) => g.key === selection.key)))
      ? selection
      : null;

  const routeFilter = useMemo<RouteFilter>(() => {
    if (liveSelection?.kind === "room") return { kind: "room", id: liveSelection.id };
    if (liveSelection?.kind === "exit") {
      const doors = exitGroups.find((g) => g.key === liveSelection.key)?.doors ?? [];
      return { kind: "exit", doors };
    }
    return { kind: "at_risk" };
  }, [liveSelection, exitGroups]);

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

  const handleResetView = () => {
    const bundle = sceneRef.current;
    if (bundle) frameView(bundle, bundle.viewBox, bundle.viewFloorY);
  };

  const startName = fireStartName(fireTimeline, fireStarts);

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
      const camera = new THREE.PerspectiveCamera(40, width / height, 0.05, 500);
      camera.position.set(0, 0.4, 2.2);

      const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.setSize(width, height);
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      // The scan's textures carry their own (baked) light: show them as captured.
      renderer.toneMapping = THREE.NoToneMapping;
      renderer.localClippingEnabled = true;
      mount.appendChild(renderer.domElement);

      const labelRenderer = new CSS2DRenderer();
      labelRenderer.setSize(width, height);
      labelRenderer.domElement.style.position = "absolute";
      labelRenderer.domElement.style.inset = "0";
      labelRenderer.domElement.style.pointerEvents = "none";
      mount.appendChild(labelRenderer.domElement);

      const controls = new OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      controls.dampingFactor = 0.08;
      controls.maxPolarAngle = Math.PI * 0.48;
      controls.addEventListener("start", () => {
        interactedRef.current = true;
        setInteracted(true);
      });

      const fireRoot = new THREE.Group();
      const placeRoot = new THREE.Group();
      scene.add(fireRoot, placeRoot);

      // Nothing clipped until the venue's rooms give the crop box.
      const cropPlanes = Array.from(
        { length: 6 },
        () => new THREE.Plane(new THREE.Vector3(0, 1, 0), 1e6),
      );

      const isGltf = /\.(glb|gltf)(\?|$)/i.test(scanUrl);
      try {
        const group = isGltf
          ? (await new GLTFLoader().setMeshoptDecoder(MeshoptDecoder).loadAsync(scanUrl)).scene
          : await new USDZLoader().loadAsync(scanUrl);
        if (cancelled) return;

        const box = new THREE.Box3().setFromObject(group);
        const center = box.getCenter(new THREE.Vector3());
        group.position.sub(center);
        scene.add(group);

        // Full colour, unlit: the Polycam textures already hold the room's light.
        let verts = 0;
        group.traverse((obj) => {
          if (!(obj as THREE.Mesh).isMesh) return;
          const mesh = obj as THREE.Mesh;
          const attr = mesh.geometry?.attributes?.position;
          if (attr) verts += attr.count;
          const swap = (mat: THREE.Material) => {
            const src = mat as THREE.MeshStandardMaterial;
            const unlit = new THREE.MeshBasicMaterial({
              map: src.map ?? null,
              color: src.map
                ? new THREE.Color(SCAN_GAIN, SCAN_GAIN, SCAN_GAIN)
                : (src.color ?? new THREE.Color(0x888888)),
              side: src.side,
              clippingPlanes: cropPlanes,
              toneMapped: false,
            });
            mat.dispose();
            return unlit;
          };
          mesh.material = Array.isArray(mesh.material)
            ? mesh.material.map(swap)
            : swap(mesh.material);
        });

        const bundle: SceneBundle = {
          scene,
          camera,
          renderer,
          labelRenderer,
          controls,
          fireRoot,
          placeRoot,
          scan: group,
          meshCenter: center.clone(),
          cropPlanes,
          viewBox: box.clone().translate(center.clone().negate()),
          viewFloorY: box.min.y - center.y,
          dispose: () => {
            cancelAnimationFrame(raf);
            ro.disconnect();
            renderer.domElement.removeEventListener("pointerdown", onPointerDown);
            renderer.domElement.removeEventListener("pointerup", onPointerUp);
            fireLayerRef.current?.dispose();
            routeLayerRef.current?.dispose();
            exitLayerRef.current?.dispose();
            placeLayerRef.current?.dispose();
            controls.dispose();
            group.traverse((obj) => {
              const mesh = obj as THREE.Mesh;
              if (!mesh.isMesh) return;
              for (const m of [mesh.material].flat()) m.dispose();
            });
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
        frameView(bundle, bundle.viewBox, bundle.viewFloorY);
        sceneRef.current = bundle;
        setVertexCount(verts);
        setLoaded(true);
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

      // Click a room or an exit to see its routes; click empty space to clear.
      const down = { x: 0, y: 0, t: 0 };
      const raycaster = new THREE.Raycaster();
      const ndc = new THREE.Vector2();
      function onPointerDown(e: PointerEvent) {
        down.x = e.clientX;
        down.y = e.clientY;
        down.t = performance.now();
      }
      function onPointerUp(e: PointerEvent) {
        if (e.button !== 0) return;
        const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y);
        if (moved > CLICK_SLOP_PX || performance.now() - down.t > CLICK_MAX_MS) return;
        const rect = renderer.domElement.getBoundingClientRect();
        ndc.set(
          ((e.clientX - rect.left) / rect.width) * 2 - 1,
          -((e.clientY - rect.top) / rect.height) * 2 + 1,
        );
        raycaster.setFromCamera(ndc, camera);
        const exitKey = exitLayerRef.current?.pick(raycaster) ?? null;
        if (exitKey) {
          setSelection({ kind: "exit", key: exitKey });
          return;
        }
        const roomId = fireLayerRef.current?.pick(raycaster) ?? null;
        setSelection(roomId ? { kind: "room", id: roomId } : null);
      }
      renderer.domElement.addEventListener("pointerdown", onPointerDown);
      renderer.domElement.addEventListener("pointerup", onPointerUp);

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

      const tick = (now: number) => {
        controls.update();
        fireLayerRef.current?.tick(now / 1000);
        routeLayerRef.current?.tick(now);
        renderer.render(scene, camera);
        labelRenderer.render(scene, camera);
        raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);

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
      exitLayerRef.current = null;
      placeLayerRef.current = null;
      while (mount.firstChild) mount.removeChild(mount.firstChild);
    };
  }, [scanUrl]);

  // Fire, exits and routes: built once per timeline, updated as the clock moves. The venue's
  // rooms also give the scan its crop box and the default view.
  useEffect(() => {
    const bundle = sceneRef.current;
    if (!bundle || !loaded || !fireTimeline) return;
    const floorY = fireTimeline.scan.floor_y ?? DEFAULT_FLOOR_Y;
    const crop = scanCropBox(fireTimeline, bundle.meshCenter, floorY);
    if (crop) {
      setCropPlanes(bundle.cropPlanes, crop);
      bundle.viewBox = crop;
      bundle.viewFloorY = floorY - bundle.meshCenter.y;
      if (!interactedRef.current) frameView(bundle, crop, bundle.viewFloorY);
    }
    const layer = buildFireLayer(fireTimeline, bundle.meshCenter, floorY);
    const routes = buildFireRouteLayer(fireTimeline, bundle.meshCenter, floorY);
    const exits = buildExitLayer(fireTimeline, bundle.meshCenter, floorY);
    bundle.fireRoot.add(layer.group, routes.group, exits.group);
    fireLayerRef.current = layer;
    routeLayerRef.current = routes;
    exitLayerRef.current = exits;
    return () => {
      bundle.fireRoot.remove(layer.group, routes.group, exits.group);
      layer.dispose();
      routes.dispose();
      exits.dispose();
      if (fireLayerRef.current === layer) fireLayerRef.current = null;
      if (routeLayerRef.current === routes) routeLayerRef.current = null;
      if (exitLayerRef.current === exits) exitLayerRef.current = null;
    };
  }, [loaded, fireTimeline]);

  useEffect(() => {
    if (!fireTimeline) return;
    fireLayerRef.current?.update(frameAt(fireTimeline, fireTime));
    fireLayerRef.current?.setSelected(liveSelection?.kind === "room" ? liveSelection.id : null);
    exitLayerRef.current?.update(fireTime);
    exitLayerRef.current?.setSelected(liveSelection?.kind === "exit" ? liveSelection.key : null);
    exitLayerRef.current?.setLabelsVisible(showExitNames);
    routeLayerRef.current?.show(departureAt(fireTimeline, fireTime), routeFilter);
  }, [fireTimeline, fireTime, loaded, liveSelection, routeFilter, showExitNames]);

  const headline = (
    <h1 className="text-[36px] leading-[42px] tracking-[-0.03em]">
      {buildingName && <span className="block text-fg">{buildingName}</span>}
      {startName && <span className="block text-dim">Fire in {startName}.</span>}
    </h1>
  );

  if (!scanUrl) {
    return (
      <section className="relative h-full bg-scan">
        <div className="pointer-events-none absolute left-8 top-9">{headline}</div>
        <div className="caps absolute inset-0 flex items-center justify-center text-center text-[10px] leading-relaxed">
          <div>
            <p className="text-fire">No LiDAR scan for this building</p>
            <p className="mt-3 text-dim">
              Upload the scan to the scans bucket
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

  const ready = loaded && !failed;
  const routeScope =
    liveSelection === null
      ? "Routes with people at risk"
      : liveSelection.kind === "room"
        ? "Routes from the selected room"
        : "Routes to the selected exit";

  return (
    <section className="relative h-full overflow-hidden bg-scan">
      <div
        ref={mountRef}
        className="absolute inset-0"
        style={{
          transition: "opacity 400ms ease-out",
          opacity: loaded ? 1 : 0,
        }}
      />

      {!loaded && !failed && (
        <div className="caps pointer-events-none absolute inset-0 flex items-center justify-center text-[10px] text-faint">
          Decoding scan…
        </div>
      )}
      {failed && (
        <div className="caps pointer-events-none absolute inset-0 flex items-center justify-center text-[10px] text-dim">
          Scan could not load
        </div>
      )}

      <div className="pointer-events-none absolute left-8 top-9 z-20 flex flex-col gap-6 [text-shadow:0_0_16px_var(--color-scan),0_0_6px_var(--color-scan),0_0_2px_var(--color-scan)]">
        {headline}
        {ready && placeIndex && (
          <PlaceSearch found={placeFound} onSearch={findPlace} onClear={handlePlaceClear} />
        )}
        {ready && fireTimeline && (
          <button
            type="button"
            onClick={() => setShowExitNames((v) => !v)}
            aria-pressed={showExitNames}
            className="caps pointer-events-auto -mt-3 self-start border border-control px-2.5 py-1 text-[11px] text-soft transition-colors hover:border-white hover:text-fg"
          >
            {showExitNames ? "Hide exit names" : "Show exit names"}
          </button>
        )}
        {ready && fireTimeline && liveSelection && (
          <ScanSelectionCard
            selection={liveSelection}
            timeline={fireTimeline}
            fireTime={fireTime}
            departure={departure}
            exitGroups={exitGroups}
            onClear={() => setSelection(null)}
          />
        )}
      </div>

      {ready && (
        <ScanMetadata
          vertexCount={vertexCount}
          hasFire={Boolean(fireTimeline)}
          verified={fireTimeline?.verified ?? false}
        />
      )}

      {ready && (
        <div className="caps pointer-events-none absolute bottom-5 right-5 flex flex-col items-end gap-2 text-[10px] text-dim [text-shadow:0_0_16px_var(--color-scan),0_0_6px_var(--color-scan),0_0_2px_var(--color-scan)]">
          <span className="flex items-center gap-4">
            <span className="text-faint">
              {interacted ? "Click a room or exit" : "Drag to rotate · click a room or exit"}
            </span>
            {interacted && (
              <button
                type="button"
                onClick={handleResetView}
                className="caps pointer-events-auto text-[10px] text-quiet transition-colors hover:text-fg"
              >
                Reset view
              </button>
            )}
          </span>
          {departure && (
            <span key={departure.t0_s} className="text-soft">
              {routeScope} · leave at T+{formatClock(departure.t0_s)}
            </span>
          )}
          <div className="flex items-center gap-5">
            <span className="flex items-center gap-2">
              <span className="h-0.5 w-3.5 bg-fg" aria-hidden />
              Aria route
            </span>
            <span className="flex items-center gap-2">
              <span className="h-0.5 w-3.5 bg-fire" aria-hidden />
              Own way
            </span>
            <span className="flex items-center gap-2">
              <span className="size-2 rounded-full border border-soft" aria-hidden />
              Exit open
            </span>
            <span className="flex items-center gap-2">
              <span className="size-2 rounded-full bg-fire" aria-hidden />
              Lost
            </span>
          </div>
        </div>
      )}
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
  controls.target.copy(target);
  camera.position.copy(target).addScaledVector(dir, dist);
  controls.update();
}

function formatVertices(count: number | null): string {
  if (!count) return "—";
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M vertices`;
  return `${Math.round(count / 1000)}K vertices`;
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
    // right-[420px] keeps the captions clear of the route key; on narrower screens they wrap upward.
    <div className="pointer-events-none absolute bottom-4 left-8 right-[420px] flex flex-wrap gap-x-8 gap-y-3 [text-shadow:0_0_16px_var(--color-scan),0_0_6px_var(--color-scan),0_0_2px_var(--color-scan)]">
      <Caption label="Scan" value="Phone LiDAR · 4 rooms of 1F" />
      <Caption label="Stitch" value="±0.3 m at the joins" />
      <Caption label="Mesh" value={formatVertices(vertexCount)} />
      <Caption label="Rest" value="Floor plan · dashed" />
      {hasFire && (
        <Caption label="Fire" value={verified ? "Engine · verified" : "Engine · screening"} />
      )}
    </div>
  );
}

function Caption({ label, value }: { label: string; value: string }) {
  return (
    <div className="caps flex flex-col gap-1 whitespace-nowrap text-[10px]">
      <span className="text-faint">{label}</span>
      <span className="text-dim">{value}</span>
    </div>
  );
}

/** In words, not headcounts: crowds are modelled at each room's assumed capacity. */
function routeOutcome(route: FireRoute): string {
  if (route.at_risk > 0) return route.status === "trapped" ? "trapped" : "people at risk";
  return "all out";
}

/** The clicked room's or exit's routes at the current departure, in words. */
function ScanSelectionCard({
  selection,
  timeline,
  fireTime,
  departure,
  exitGroups,
  onClear,
}: {
  selection: ScanSelection;
  timeline: FireTimeline;
  fireTime: number;
  departure: FireRouteDeparture | null;
  exitGroups: ExitGroup[];
  onClear: () => void;
}) {
  const exitName = (door: string | null): string => {
    if (!door) return "no exit";
    const g = exitGroups.find((e) => e.doors.includes(door));
    return g ? g.label : door;
  };
  const routes = departure?.routes ?? [];
  let kicker: string;
  let title: string;
  let status: { text: string; fire: boolean };
  let shown: FireRoute[];

  if (selection.kind === "room") {
    const room = timeline.rooms[selection.id];
    const state = frameAt(timeline, fireTime).rooms[selection.id]?.state ?? "clear";
    kicker = `${room?.storey ?? `Floor ${room?.floor ?? "?"}`} · ${
      room?.scanned ? "scanned" : "from floor plan"
    }`;
    title = (room?.name ?? selection.id).split(" (")[0];
    status = { text: state.replace("_", " "), fire: state !== "clear" };
    shown = routes.filter((r) => r.space === selection.id);
  } else {
    const g = exitGroups.find((e) => e.key === selection.key);
    const lost = g?.blockedS != null && fireTime >= g.blockedS;
    kicker = "Exit";
    title = g ? exitGroupName(g) : selection.key;
    status = lost
      ? { text: `lost ${formatLostClock(g?.blockedS ?? 0)}`, fire: true }
      : {
          text: g?.blockedS != null ? `open · lost at ${formatLostClock(g.blockedS)}` : "open",
          fire: false,
        };
    shown = routes.filter((r) => r.exit !== null && (g?.doors ?? []).includes(r.exit));
  }

  return (
    <div className="pointer-events-auto -mx-2 w-[316px] bg-scan/80 px-2 py-2">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <span className="caps text-[10px] text-faint">{kicker}</span>
          <span className="truncate text-[15px] leading-[19px] text-fg" title={title}>
            {title}
          </span>
        </div>
        <button
          type="button"
          onClick={onClear}
          aria-label="Clear selection"
          className="shrink-0 px-1 text-[11px] text-dim transition-colors hover:text-fg"
        >
          ✕
        </button>
      </div>
      <p className={`caps mt-1.5 text-[10px] ${status.fire ? "text-fire" : "text-soft"}`}>
        {status.text}
      </p>
      <div className="caps mt-2 flex flex-col gap-1 border-t border-rule pt-2 text-[10px] leading-relaxed">
        {departure && <p className="text-faint">Leave at T+{formatClock(departure.t0_s)}</p>}
        {shown.length === 0 && <p className="text-dim">No one routed here at this time</p>}
        {shown.map((r, i) => (
          <div key={`${r.kind}-${r.space}-${i}`} className="flex justify-between gap-3">
            <span className="flex min-w-0 items-center gap-2">
              <span
                className={`h-0.5 w-3 shrink-0 ${r.kind === "plan" ? "bg-fg" : "bg-fire"}`}
                aria-hidden
              />
              <span className="truncate text-soft">
                {selection.kind === "room"
                  ? `→ ${exitName(r.exit)}`
                  : (timeline.rooms[r.space]?.name ?? r.space).split(" (")[0]}
              </span>
            </span>
            <span className={`shrink-0 ${r.at_risk > 0 ? "text-fire" : "text-dim"}`}>
              {routeOutcome(r)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
