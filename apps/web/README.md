# Web app (`apps/web`)

Frontend for the [project](../../README.md) — the dashboard, building page, agent log, 3D scan viewer with storm-surge slider, and pre-incident report panel.

## Stack

- **Next.js 16** (App Router, React Server Components, Turbopack)
- **TypeScript strict**, no `any`
- **Tailwind CSS v4** (CSS-first config, no `tailwind.config.ts`)
- **framer-motion** for the cinematic landing fade-in
- **Mapbox GL JS** for the 3D dashboard
- **Three.js** + `USDZLoader` + `OrbitControls` for in-browser USDZ rendering
- **lucide-react** for icons
- **@supabase/supabase-js** for buildings / preplans / tool_calls

The frontend never calls Anthropic directly. All agent traffic flows through the FastAPI backend so the live tool-use log can stream as SSE.

## Folder structure

```
apps/web/
├── app/
│   ├── page.tsx                      # / — cinematic landing
│   ├── dashboard/                    # /dashboard — 3D Mapbox + activity panel
│   ├── building/[id]/                # /building/:id — three-column workbench
│   ├── globals.css                   # design tokens + slider styles + fade keyframes
│   └── layout.tsx
├── components/
│   ├── agent/
│   │   ├── useAgentStream.ts         # POST /agent/run, parse SSE off the body stream
│   │   ├── AgentRunProvider.tsx      # Context: events, report, running, elapsedMs, run()
│   │   ├── AgentLog.tsx              # Cinematic terminal renderer
│   │   └── AgentLogPane.tsx          # Thin pane wrapper
│   ├── scan/
│   │   └── BuildingScan.tsx          # Three.js USDZ viewer + metadata overlay
│   ├── building/
│   │   ├── BuildingCenterPane.tsx    # 3D scan + scenario strip
│   │   ├── ScenarioProvider.tsx      # Context: storm-surge level shared with the scan
│   │   ├── ScenarioStrip.tsx         # Surge slider, risk badge, scenario label
│   │   └── scenario.ts               # Surge stops, risk + label helpers
│   └── report/
│       ├── PreplanReport.tsx         # Right-column panel + actions + fullscreen toggle
│       ├── FullscreenReport.tsx      # "Give this to the chief" overlay
│       └── actions.ts                # Generate immediate-action cards from agent output
├── lib/
│   ├── types.ts                      # Shared types — mirrors the Pydantic schema
│   ├── supabase.ts                   # Server + browser Supabase client helpers
│   ├── brand.ts                      # Product name / tagline (rename here)
│   ├── scan-evac-paths.ts            # Evacuation graph + surge-linked exit blocking
│   ├── scan-flood.ts                 # Surge height → water plane
│   ├── time.ts                       # formatRelative()
│   └── design.ts                     # Color tokens
├── public/                           # static files only — scans live in Supabase Storage
├── tests/e2e/                        # Playwright specs
├── types/model-viewer.d.ts           # JSX declaration (kept for future use)
└── playwright.config.ts
```

## Key components

- **`MapDashboard`** — Mapbox GL on the `/dashboard` route. Dark v11 style at pitch 60°, custom `building-extrusion` fill-extrusion layer (the style's built-in `building` layer is `type: fill`, we hide it and add our own), pulsing-circle GeoJSON source for the primary venue, plus smaller dots for other demo buildings. Click handler proximity-matches the click against `buildings`, opens a popover with `VIEW BUILDING` routing.
- **`BuildingCenterPane`** — the 3D scan with the storm-surge scenario strip underneath; surge level is shared via `ScenarioProvider` so the scan's flood plane and evacuation exits react to it.
- **`BuildingScan`** — Three.js scene with `USDZLoader`, `OrbitControls`, auto-rotate until first interaction. Camera distance derived from the model's bounding box for a tight cinematic 3/4 framing. Real vertex count is computed from the loaded geometry and shown in the metadata overlay.
- **`AgentLog`** — reads SSE events from `useAgentStream` via `AgentRunProvider` context. Reasoning events run through `stripReportBlock()` to drop the final ` ```json ``` ` dump (the report panel renders that as structured cards). Footer collapses to `✓ AGENT COMPLETE · N TOOLS · N ITERATIONS · Xs` on completion.
- **`PreplanReport`** — `HEADLINE RISK` hero text → `IMMEDIATE ACTIONS` (generated from agent output, sortable by severity, click-to-dispatch with timestamp) → `BUILDING PROFILE` → three hazard cards. `Maximize2` icon opens a fullscreen modal with dramatic typography for the "give this to the chief" view.

## Environment variables

`.env.local` (see `.env.example`):

```
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_SUPABASE_URL=https://<project>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=...
NEXT_PUBLIC_MAPBOX_TOKEN=pk....
```

Backend keys (Anthropic, Supabase service role) live in `apps/api/.env`. The frontend never sees them.

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
