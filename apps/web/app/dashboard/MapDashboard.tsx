"use client";

import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { BRAND_WORDMARK } from "@/lib/brand";
import type { Building } from "@/lib/supabase";

import { AgentActivity, type PreplanRow } from "./AgentActivity";

type PopoverState = {
  lngLat: [number, number];
  screen: { x: number; y: number };
  building: Building | null; // matched building, or null = unknown structure
} | null;

const VENUE_MATCH_DEG = 0.0005; // ~55m at this latitude
// James West Alumni Center, UCLA. Used until the venue row loads from Supabase.
const VENUE_FALLBACK_CENTER: [number, number] = [-118.44520289359974, 34.07026948117506];

export function MapDashboard({
  buildings,
  preplans,
  preplanCount,
  mapboxToken,
}: {
  buildings: Building[];
  preplans: PreplanRow[];
  preplanCount: number;
  mapboxToken: string;
}) {
  const primary = buildings[0] ?? null;
  const secondary = buildings.slice(1);
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const rafRef = useRef<number>(0);
  const popoverLngLatRef = useRef<[number, number] | null>(null);
  const [popover, setPopover] = useState<PopoverState>(null);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    if (!mapboxToken) return;

    mapboxgl.accessToken = mapboxToken;
    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: "mapbox://styles/mapbox/dark-v11",
      center: primary ? [primary.lng, primary.lat] : VENUE_FALLBACK_CENTER,
      zoom: 17,
      pitch: 60,
      bearing: -20,
      antialias: true,
      logoPosition: "top-right",
    });
    mapRef.current = map;

    map.addControl(new mapboxgl.NavigationControl({ visualizePitch: true }), "bottom-right");

    map.on("error", (e) => {
      console.error("[mapbox-error]", e?.error?.message ?? e);
    });

    const closePopover = () => {
      popoverLngLatRef.current = null;
      setPopover(null);
    };

    const onStyleReady = () => {
      try {
        // dark-v11 includes a flat `building` fill layer. Hide it and add our
        // own 3D extrusion layer on top.
        if (map.getLayer("building")) {
          map.setLayoutProperty("building", "visibility", "none");
        }
        if (!map.getLayer("building-extrusion")) {
          map.addLayer({
            id: "building-extrusion",
            source: "composite",
            "source-layer": "building",
            type: "fill-extrusion",
            minzoom: 14,
            paint: {
              "fill-extrusion-color": [
                "interpolate",
                ["linear"],
                ["get", "height"],
                0,
                "#2f2f2f",
                40,
                "#3b3b3b",
                120,
                "#4d4d4d",
                250,
                "#5f5f5f",
              ],
              "fill-extrusion-height": ["coalesce", ["get", "height"], 12],
              "fill-extrusion-base": ["coalesce", ["get", "min_height"], 0],
              "fill-extrusion-opacity": 0.95,
            },
          });
        }

        // Primary venue: pulsing ring + bright dot. Other demo buildings get
        // a smaller, solid orange dot (no pulse) so the primary stays dominant.
        if (primary) {
          if (!map.getSource("venue-primary")) {
            map.addSource("venue-primary", {
              type: "geojson",
              data: {
                type: "FeatureCollection",
                features: [
                  {
                    type: "Feature",
                    geometry: {
                      type: "Point",
                      coordinates: [primary.lng, primary.lat],
                    },
                    properties: { id: primary.id, address: primary.address },
                  },
                ],
              },
            });
          }
          if (!map.getLayer("venue-pulse")) {
            map.addLayer({
              id: "venue-pulse",
              source: "venue-primary",
              type: "circle",
              paint: {
                "circle-radius": 26,
                "circle-color": "#ff6b00",
                "circle-opacity": 0.2,
                "circle-stroke-color": "#ff6b00",
                "circle-stroke-width": 1,
                "circle-stroke-opacity": 0.5,
              },
            });
          }
          if (!map.getLayer("venue-dot")) {
            map.addLayer({
              id: "venue-dot",
              source: "venue-primary",
              type: "circle",
              paint: {
                "circle-radius": 6,
                "circle-color": "#ff6b00",
                "circle-stroke-color": "#000",
                "circle-stroke-width": 2,
              },
            });
          }

          let phase = 0;
          const tick = () => {
            phase = (phase + 0.025) % (Math.PI * 2);
            const t = (Math.sin(phase) + 1) / 2;
            const pulseLayer = map.getLayer("venue-pulse") as { type?: string } | undefined;
            if (pulseLayer && pulseLayer.type === "circle") {
              try {
                map.setPaintProperty("venue-pulse", "circle-radius", 22 + t * 28);
                map.setPaintProperty("venue-pulse", "circle-opacity", 0.32 - t * 0.27);
              } catch {
                // ignore — map may be in a transitional state during HMR
              }
            }
            rafRef.current = requestAnimationFrame(tick);
          };
          rafRef.current = requestAnimationFrame(tick);
        }

        if (secondary.length > 0) {
          if (!map.getSource("venue-secondary")) {
            map.addSource("venue-secondary", {
              type: "geojson",
              data: {
                type: "FeatureCollection",
                features: secondary.map((b) => ({
                  type: "Feature",
                  geometry: { type: "Point", coordinates: [b.lng, b.lat] },
                  properties: { id: b.id, address: b.address },
                })),
              },
            });
          }
          if (!map.getLayer("venue-secondary-dot")) {
            map.addLayer({
              id: "venue-secondary-dot",
              source: "venue-secondary",
              type: "circle",
              paint: {
                "circle-radius": 4,
                "circle-color": "#ff6b00",
                "circle-opacity": 0.85,
                "circle-stroke-color": "#000",
                "circle-stroke-width": 1.5,
              },
            });
          }
        }
      } catch (err) {
        console.error("[mapbox-load-handler]", err);
      }
    };
    if (map.isStyleLoaded()) onStyleReady();
    else map.once("style.load", onStyleReady);

    map.on("click", (e) => {
      const layerIds = [
        "venue-dot",
        "venue-pulse",
        "venue-secondary-dot",
        "building-extrusion",
      ].filter((id) => map.getLayer(id));
      const features = layerIds.length
        ? map.queryRenderedFeatures(e.point, { layers: layerIds })
        : [];
      if (features.length === 0) {
        closePopover();
        return;
      }

      const lngLat: [number, number] = [e.lngLat.lng, e.lngLat.lat];
      const matched = findClosestBuilding(buildings, lngLat, VENUE_MATCH_DEG);
      const anchor: [number, number] = matched ? [matched.lng, matched.lat] : lngLat;
      const p = map.project(anchor);

      popoverLngLatRef.current = anchor;
      setPopover({
        lngLat: anchor,
        screen: { x: p.x, y: p.y },
        building: matched,
      });
    });

    const onMove = () => {
      const ll = popoverLngLatRef.current;
      if (!ll) return;
      const p = map.project(ll);
      setPopover((prev) => (prev ? { ...prev, screen: { x: p.x, y: p.y } } : prev));
    };
    map.on("move", onMove);

    return () => {
      cancelAnimationFrame(rafRef.current);
      map.off("move", onMove);
      map.remove();
      mapRef.current = null;
    };
  }, [mapboxToken, primary, secondary, buildings]);

  // Escape closes popover
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        popoverLngLatRef.current = null;
        setPopover(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <main className="fixed inset-0 overflow-hidden bg-black text-white">
      <div
        ref={containerRef}
        className="absolute inset-0"
        style={{ width: "100%", height: "100%" }}
      />

      {/* Top chrome */}
      <div className="pointer-events-none absolute inset-x-0 top-0 z-10 flex items-start justify-between p-5">
        <div className="pointer-events-auto flex items-center gap-3 rounded-md border border-white/[0.08] bg-black/75 px-4 py-2 font-mono text-xs tracking-[0.3em] backdrop-blur">
          <Link href="/" className="text-white transition-colors hover:text-[#ff6b00]">
            {BRAND_WORDMARK}
          </Link>
          <span className="text-white/25">·</span>
          <span className="text-white/60">DASHBOARD</span>
          <span className="text-white/25">·</span>
          <span className="text-white/60">LOS ANGELES</span>
        </div>
      </div>

      {/* Popover */}
      {popover && (
        <div
          className="pointer-events-none absolute z-20"
          style={{
            left: popover.screen.x,
            top: popover.screen.y,
            transform: "translate(-50%, calc(-100% - 22px))",
          }}
        >
          <div className="pointer-events-auto relative w-72 rounded-md border border-white/[0.1] bg-black/95 p-4 shadow-[0_20px_60px_-15px_rgba(0,0,0,0.95)] backdrop-blur">
            <div className="mb-2 flex items-center justify-between gap-2">
              <span className="font-mono text-[10px] tracking-[0.3em] text-white/40">
                BUILDING · {popover.lngLat[1].toFixed(4)}, {popover.lngLat[0].toFixed(4)}
              </span>
              <button
                onClick={() => {
                  popoverLngLatRef.current = null;
                  setPopover(null);
                }}
                aria-label="Close"
                className="font-mono text-base leading-none text-white/40 transition-colors hover:text-white"
              >
                ×
              </button>
            </div>
            <div className="mb-4 text-sm font-medium leading-snug text-white">
              {popover.building?.address ?? "UNKNOWN STRUCTURE"}
            </div>
            {popover.building ? (
              <Link
                href={`/building/${popover.building.id}`}
                className="group/cta inline-flex w-full items-center justify-between rounded-sm bg-[#ff6b00] px-3 py-2 font-mono text-[11px] font-medium tracking-[0.2em] text-black transition-colors hover:bg-[#ff7f1f]"
              >
                VIEW BUILDING
                <span aria-hidden className="transition-transform group-hover/cta:translate-x-0.5">
                  →
                </span>
              </Link>
            ) : (
              <div className="inline-flex w-full items-center justify-between rounded-sm border border-white/[0.06] bg-white/[0.02] px-3 py-2 font-mono text-[11px] tracking-[0.2em] text-white/30">
                PRE-PLAN PENDING
                <span aria-hidden>—</span>
              </div>
            )}

            <div className="absolute left-1/2 top-full -translate-x-1/2">
              <div className="h-0 w-0 border-x-[8px] border-t-[8px] border-x-transparent border-t-black/95" />
            </div>
          </div>
        </div>
      )}

      <AgentActivity preplans={preplans} preplanCount={preplanCount} />
    </main>
  );
}

function findClosestBuilding(
  buildings: Building[],
  lngLat: [number, number],
  maxDegDelta: number,
): Building | null {
  let best: { b: Building; d: number } | null = null;
  for (const b of buildings) {
    const dLng = lngLat[0] - b.lng;
    const dLat = lngLat[1] - b.lat;
    if (Math.abs(dLng) > maxDegDelta || Math.abs(dLat) > maxDegDelta) continue;
    const d = dLng * dLng + dLat * dLat;
    if (!best || d < best.d) best = { b, d };
  }
  return best?.b ?? null;
}
