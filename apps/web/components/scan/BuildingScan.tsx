"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import { USDZLoader } from "three/examples/jsm/loaders/USDZLoader.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js";

import { useScenario } from "@/components/building/ScenarioProvider";
import { departureAt, frameAt, type FireStarts, type FireTimeline } from "@/lib/scan-fire";
import { loadPlaceIndex, searchPlaces, type PlaceIndex } from "@/lib/scan-places";

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

/** The start space's plan name up to the first " (": "Collins Room, part 140". */
function fireStartName(timeline: FireTimeline | null, starts: FireStarts | null): string | null {
  if (!timeline) return null;
  const id = timeline.start_room;
  const name = starts?.starts.find((s) => s.id === id)?.label ?? timeline.rooms[id]?.name ?? id;
  return name.split(" (")[0];
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
  const placeLayerRef = useRef<PlacePinLayerObjects | null>(null);

  const { fireTime, fireTimeline, fireStarts } = useScenario();
  const [placeIndex, setPlaceIndex] = useState<PlaceIndex | null>(null);
  const [placeFound, setPlaceFound] = useState<PlaceFound | null>(null);
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
      scene.add(new THREE.HemisphereLight(0xffffff, 0x4a4f55, 1.6));
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
            const mesh = obj as THREE.Mesh;
            const attr = mesh.geometry?.attributes?.position;
            if (attr) verts += attr.count;
            // Greyscale scan: only the routes and the fire carry colour.
            for (const mat of [mesh.material].flat() as THREE.MeshStandardMaterial[]) {
              if (!mat?.map) continue;
              mat.onBeforeCompile = (shader) => {
                shader.fragmentShader = shader.fragmentShader.replace(
                  "#include <map_fragment>",
                  `#include <map_fragment>
                   float lum = dot(diffuseColor.rgb, vec3(0.2126, 0.7152, 0.0722));
                   diffuseColor.rgb = vec3(lum) * 0.8;`,
                );
              };
              mat.needsUpdate = true;
            }
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

  const headline = (
    <h1 className="text-[44px] leading-[50px] tracking-[-0.03em]">
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

      <div className="pointer-events-none absolute left-8 top-9 z-20 flex flex-col gap-7 [text-shadow:0_0_16px_var(--color-scan),0_0_6px_var(--color-scan),0_0_2px_var(--color-scan)]">
        {headline}
        {loaded && !failed && placeIndex && (
          <PlaceSearch found={placeFound} onSearch={findPlace} onClear={handlePlaceClear} />
        )}
      </div>

      {loaded && !failed && (
        <ScanMetadata
          vertexCount={vertexCount}
          hasFire={Boolean(fireTimeline)}
          verified={fireTimeline?.verified ?? false}
        />
      )}

      {loaded && !failed && (
        <div className="caps pointer-events-none absolute bottom-5 right-5 flex flex-col items-end gap-2 text-[10px] text-dim [text-shadow:0_0_16px_var(--color-scan),0_0_6px_var(--color-scan),0_0_2px_var(--color-scan)]">
          {!interacted && <span className="text-faint">Drag to rotate · scroll to zoom</span>}
          <div className="flex items-center gap-5">
            <span className="flex items-center gap-2">
              <span className="h-0.5 w-3.5 bg-fg" aria-hidden />
              Aria plan
            </span>
            <span className="flex items-center gap-2">
              <span className="h-0.5 w-3.5 bg-fire" aria-hidden />
              At risk
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
  controls.autoRotate = false;
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
    // right-[200px] keeps the captions clear of the route key; on narrower screens they wrap upward.
    <div className="pointer-events-none absolute bottom-4 left-8 right-[200px] flex flex-wrap gap-x-8 gap-y-3 [text-shadow:0_0_16px_var(--color-scan),0_0_6px_var(--color-scan),0_0_2px_var(--color-scan)]">
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
