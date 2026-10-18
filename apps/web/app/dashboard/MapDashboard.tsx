"use client";

import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { BRAND } from "@/lib/brand";
import type { Building } from "@/lib/supabase";

import { PanelSection, VenuePreplanCard } from "./VenuePreplanCard";

const VENUE_MATCH_DEG = 0.0005; // ~55m at this latitude
// James West Alumni Center, UCLA. Used until the venue row loads from Supabase.
const VENUE_FALLBACK_CENTER: [number, number] = [-118.44520289359974, 34.07026948117506];
const MAP_ZOOM = 17;
const MAP_PITCH = 60;
const MAP_BEARING = -20;

const NUMBER_WORDS = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"];

/** "One building scanned and ready." (numbers one to nine spelled out). */
function scannedLine(n: number): string {
  const count = NUMBER_WORDS[n] ?? String(n);
  return `${count} building${n === 1 ? "" : "s"} scanned and ready.`;
}

/** The address up to the first comma is the building's name; the rest is the street address. */
function splitAddress(address: string): { name: string; rest: string } {
  const i = address.indexOf(",");
  if (i < 0) return { name: address, rest: "" };
  return { name: address.slice(0, i), rest: address.slice(i + 1).trim() };
}

function formatLngLat([lng, lat]: [number, number]): string {
  return `${lat.toFixed(4)}, ${lng.toFixed(4)}`.replace(/-/g, "−");
}

export function MapDashboard({
  buildings,
  mapboxToken,
}: {
  buildings: Building[];
  mapboxToken: string;
}) {
  const primary = buildings[0] ?? null;
  // Memoised: a new array every render would sit in the map effect's deps and rebuild the map.
  const secondary = useMemo(() => buildings.slice(1), [buildings]);
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = buildings.find((b) => b.id === selectedId) ?? primary;
  const scannedCount = buildings.filter((b) => b.scan_url).length;
  const center: [number, number] = primary ? [primary.lng, primary.lat] : VENUE_FALLBACK_CENTER;

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    if (!mapboxToken) return;

    mapboxgl.accessToken = mapboxToken;
    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: "mapbox://styles/mapbox/dark-v11",
      center: primary ? [primary.lng, primary.lat] : VENUE_FALLBACK_CENTER,
      zoom: MAP_ZOOM,
      pitch: MAP_PITCH,
      bearing: MAP_BEARING,
      antialias: true,
      logoPosition: "top-right",
    });
    mapRef.current = map;

    map.addControl(new mapboxgl.NavigationControl({ visualizePitch: true }), "bottom-right");
    // The map sits in a flex row next to the panel: size it once the layout has settled.
    map.once("load", () => map.resize());

    map.on("error", (e) => {
      console.error("[mapbox-error]", e?.error?.message ?? e);
    });

    // The venue: a square marker with its name; clicking it selects it like a map click.
    let marker: mapboxgl.Marker | null = null;
    if (primary) {
      const el = document.createElement("button");
      el.type = "button";
      el.setAttribute("aria-label", `Select ${splitAddress(primary.address).name}`);
      el.className = "flex cursor-pointer items-center gap-3";
      el.innerHTML =
        '<span class="flex h-11 w-11 items-center justify-center border border-white/60 bg-page/60">' +
        '<span class="h-2.5 w-2.5 bg-white"></span></span>';
      const label = document.createElement("span");
      label.className = "caps text-[11px] text-fg";
      label.textContent = splitAddress(primary.address).name;
      el.appendChild(label);
      el.addEventListener("click", (ev) => {
        ev.stopPropagation();
        setSelectedId(primary.id);
      });
      // Anchor on the square's centre (22px in from the left edge).
      marker = new mapboxgl.Marker({ element: el, anchor: "left", offset: [-22, 0] })
        .setLngLat([primary.lng, primary.lat])
        .addTo(map);
      // Mapbox sets role="img" on marker elements; keep it announced as a button.
      el.setAttribute("role", "button");
    }

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

        // Primary venue: a thin white ring and a white dot. Other demo buildings get a
        // smaller grey dot so the primary stays dominant.
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
                // A faint ring around the 44px square marker, as on the Paper screen.
                "circle-radius": 46,
                "circle-color": "#ffffff",
                "circle-opacity": 0.03,
                "circle-stroke-color": "#ffffff",
                "circle-stroke-width": 1,
                "circle-stroke-opacity": 0.3,
              },
            });
          }
          if (!map.getLayer("venue-dot")) {
            map.addLayer({
              id: "venue-dot",
              source: "venue-primary",
              type: "circle",
              paint: {
                "circle-radius": 5,
                "circle-color": "#ffffff",
                "circle-stroke-color": "#0e1013",
                "circle-stroke-width": 2,
              },
            });
          }
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
                "circle-color": "#8e9196",
                "circle-stroke-color": "#0e1013",
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

    // Clicking a pre-planned building selects it in the panel; anything else leaves it be.
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
      if (features.length === 0) return;
      const matched = findClosestBuilding(buildings, [e.lngLat.lng, e.lngLat.lat], VENUE_MATCH_DEG);
      if (matched) setSelectedId(matched.id);
    });

    return () => {
      marker?.remove();
      map.remove();
      mapRef.current = null;
    };
  }, [mapboxToken, primary, secondary, buildings]);

  const selectedName = selected ? splitAddress(selected.address) : null;

  return (
    <main className="fixed inset-0 flex flex-col overflow-hidden bg-page text-fg">
      <header className="flex h-12 shrink-0 items-center gap-4 border-b border-rule bg-page pl-5 pr-3">
        <Link href="/" className="text-[17px] font-medium text-fg">
          {BRAND.name}
        </Link>
        <nav aria-label="Breadcrumb" className="caps flex items-center gap-3 text-[11px]">
          <span className="text-soft">Dashboard</span>
          <span className="text-faint">/</span>
          <span className="text-dim">Los Angeles</span>
        </nav>
        {/* The live dispatch console, served by the API through this app's /live proxy. */}
        <a
          href="/live/view"
          className="ml-auto flex h-[30px] shrink-0 items-center whitespace-nowrap bg-white px-4 text-[13px] text-ink transition-colors hover:bg-rule-light"
        >
          Live console ↗
        </a>
      </header>

      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <div className="relative min-h-[50vh] min-w-0 flex-1">
          {/* Inline: mapbox-gl.css sets .mapboxgl-map to position: relative, beating the utility. */}
          <div ref={containerRef} style={{ position: "absolute", inset: 0 }} />

          <div className="pointer-events-none absolute left-8 top-9 z-10">
            <h1 className="text-[28px] leading-[32px] tracking-[-0.03em] md:text-[44px] md:leading-[50px] text-fg">
              Los Angeles
            </h1>
            <p className="text-[28px] leading-[32px] tracking-[-0.03em] md:text-[44px] md:leading-[50px] text-dim">
              {scannedLine(scannedCount)}
            </p>
          </div>

          <dl className="caps pointer-events-none absolute bottom-4 left-8 z-10 flex gap-8 text-[10px]">
            <div>
              <dt className="text-faint">Centre</dt>
              <dd className="text-dim tabular-nums">{formatLngLat(center)}</dd>
            </div>
            <div>
              <dt className="text-faint">Zoom</dt>
              <dd className="text-dim tabular-nums">{MAP_ZOOM}</dd>
            </div>
            <div>
              <dt className="text-faint">Pitch</dt>
              <dd className="text-dim tabular-nums">
                {MAP_PITCH}° · Bearing {String(MAP_BEARING).replace("-", "−")}°
              </dd>
            </div>
          </dl>
        </div>

        <aside className="flex max-h-[50vh] w-full shrink-0 flex-col overflow-y-auto border-t border-rule bg-page md:max-h-none md:w-[360px] md:border-l md:border-t-0">
          <PanelSection label="Building" n={1}>
            {selected && selectedName ? (
              <div className="flex flex-col gap-4">
                <div>
                  <div className="text-[22px] leading-[30px] tracking-[-0.01em] text-fg">
                    {selectedName.name}
                  </div>
                  {selectedName.rest && (
                    <div className="mt-1 text-[13px] text-quiet">{selectedName.rest}</div>
                  )}
                </div>
                {selected.scan_url ? (
                  <Link
                    href={`/building/${selected.id}`}
                    className="flex h-[38px] items-center justify-between bg-white px-3.5 text-[14px] text-ink transition-colors hover:bg-rule-light"
                  >
                    View building <span aria-hidden>→</span>
                  </Link>
                ) : (
                  <div className="flex h-[38px] items-center border border-control px-3.5 text-[14px] text-quiet">
                    Pre-plan pending
                  </div>
                )}
              </div>
            ) : (
              <p className="caps text-[11px] text-dim">No buildings yet.</p>
            )}
          </PanelSection>

          {selected && <VenuePreplanCard key={selected.id} building={selected} />}
        </aside>
      </div>
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
