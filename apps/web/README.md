# Web app (`apps/web`)

Frontend for the [project](../../README.md): the landing page, the dashboard map, and the venue's fire pre-plan (3D scan with the engine's fire, smoke and routes, a fire clock, and the responder size-up). The live dispatch console is served by the API at `/live/view` through this app's proxy.

## Stack

- **Next.js 16** (App Router, React Server Components, Turbopack)
- **TypeScript strict**, no `any`
- **Tailwind CSS v4** (CSS-first config, no `tailwind.config.ts`)
- **framer-motion** for the cinematic landing fade-in
- **Mapbox GL JS** for the 3D dashboard
- **Three.js** + `USDZLoader` + `OrbitControls` for in-browser USDZ rendering
- **@supabase/supabase-js** for the buildings table

The fire engine runs in the API (`GET /engine/starts`, `/engine/viewer`, `/engine/summary`), proxied at `/engine/*` by `next.config.ts`.

## Folder structure

```
apps/web/
├── app/
│   ├── page.tsx                      # / — cinematic landing
│   ├── dashboard/                    # /dashboard — 3D Mapbox + venue pre-plan card
│   ├── building/[id]/                # /building/:id — fire pre-plan workbench
│   ├── fire-preview/                 # local preview over the stitched venue GLB
│   ├── globals.css                   # design tokens + slider styles + place pins
│   └── layout.tsx
├── components/
│   ├── scan/
│   │   ├── BuildingScan.tsx          # Three.js scan viewer + fire layer + metadata overlay
│   │   ├── scanSceneLayers.ts        # fire/smoke rooms (dashed = from floor plan), routes, place pins
│   │   ├── FireStartPicker.tsx       # "Fire starts in"
│   │   └── PlaceSearch.tsx           # find a place on the scan
│   └── building/
│       ├── BuildingCenterPane.tsx    # scan + size-up panel + fire clock strip
│       ├── ScenarioProvider.tsx      # Context: fire clock, play state, fire start
│       ├── ScenarioStrip.tsx         # fire timeline slider
│       └── SizeUpPanel.tsx           # responder size-up from /engine/summary
├── lib/
│   ├── scan-fire.ts                  # FireTimeline + SizeUp types and loaders
│   ├── scan-places.ts                # places.json search
│   ├── supabase.ts                   # Server Supabase client
│   └── brand.ts                      # Product name / tagline (rename here)
├── public/                           # static files only — scans live in Supabase Storage
├── tests/e2e/                        # Playwright specs
├── types/model-viewer.d.ts           # JSX declaration (kept for future use)
└── playwright.config.ts
```

## Key components

- **`MapDashboard`** — Mapbox GL on `/dashboard`: dark style at pitch 60°, a custom building extrusion layer, a pulsing marker for the venue. Clicking the venue opens a popover that links to its pre-plan; `VenuePreplanCard` shows the engine's headline numbers for the default scenario.
- **`BuildingScan`** — Three.js scene (GLB or USDZ), auto-rotate until first interaction. Draws the engine's rooms over the scan: scanned rooms with a solid outline, rooms from the floor plan (the rest of the 1F and all upper floors) dashed and fainter. Smoke fills each room to its layer depth; exits turn red when lost. Shows "INDICATIVE AFTER FLASHOVER" once the clock passes the first flashover (frames carry `beyond_screening`).
- **`SizeUpPanel`** — follows the fire start and the fire clock: origin and growth, key fire moments, exits lost and when, people at risk and time until everyone is out with Aria's plan vs self-chosen routes, where the plan matters most, ways down per floor, connections to check on site, and the assumptions (worst case: no sprinklers, smoke control or fire service).

## Environment variables

`.env.local` (see `.env.example`):

```
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_SUPABASE_URL=https://<project>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=...
NEXT_PUBLIC_MAPBOX_TOKEN=pk....
```

Backend secrets (CREAO, TigerData, the tool secret, Sentry) live in `apps/api/.env`. The frontend never sees them.

## Dev

```bash
pnpm install            # first time only
pnpm dev                # frontend only on :3000
pnpm dev:all            # frontend + backend (concurrently)
pnpm build              # production build
pnpm check              # lint + format check + typecheck + unit tests (what CI runs)
pnpm test:e2e           # Playwright e2e (needs pnpm dev running)
```

## Notes

- **React strict mode is intentionally disabled** in `next.config.ts` because Mapbox GL's tile worker conflicts with strict mode's double-effect-invocation under React 19, leaving the remounted instance without tiles. Re-enable when mapbox-gl ships a fix.
- **Three.js imports are top-level**, not lazy. Turbopack 16 chokes on dynamic chunks under `three/examples/jsm/*` when its dev cache goes stale. The tradeoff is ~150 KB extra in the initial `/building/[id]` bundle.
