# What changes from the Miami version

The code came from Aria's Miami build: storm surge and flood, one hardcoded building (The Dock), a map centered on Miami, and Aria's own Supabase project. This weekend it moves to the venue and to fire. Below is where each Miami-specific piece lives.

## 1. New Supabase project

Done Sat Oct 17 (steps 1–4 below, except uploading the scan): project ref `sntyqjzoyjfgrjesguvs`, venue ID `547b5ec5-30c5-4f76-8080-012a52e90bd9`. Still to do: upload the scan to `scans` and set the venue row's `scan_url`, and put the secret key in `apps/api/.env`. The steps, for the record:

1. In the new project's SQL editor, run `infra/supabase/migrations/0001`, `0002` and `0004`, in that order. Skip `0003`: it seeds The Dock with a scan in Aria's own storage.
2. Create a public Storage bucket named `scans` and upload the venue scan there, not to git. The Free plan caps uploads at 50 MB per file, so export a lighter GLB from Polycam if the scan is bigger.
3. Seed the venue. `0001` also inserts a Miami placeholder marked as the demo building, so turn that off in the same step:

   ```sql
   update buildings set is_demo = false;

   insert into buildings (address, lat, lng, scan_url, is_demo)
   values (
     'James West Alumni Center, 325 Westwood Plaza, Los Angeles, CA 90095',
     <lat>, <lng>,
     'https://<project-ref>.supabase.co/storage/v1/object/public/scans/<path-to-scan>.glb',
     true
   )
   returning id;
   ```

   The returned `id` is the venue's ID. It takes The Dock's place in the files in section 2.
4. Environment variables. In the dashboard's API keys settings, the publishable key (`sb_publishable_…`) stands in for the old anon key and the secret key (`sb_secret_…`) for the service role key. The Supabase client libraries accept either kind, so the variable names stay:
   - `apps/web/.env.local`: `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY` (the publishable key)
   - `apps/api/.env`: `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` (the secret key)
   - The secret key never goes in the web app or in git.

## 2. The hardcoded building (The Dock → the venue)

Per-building data is keyed by hardcoded IDs: The Dock (`e5a3fddc-…`) and two older placeholder buildings (`014b39a9-…`, `870d979d-…`).

| File | What's hardcoded |
|---|---|
| `apps/web/lib/scan-evac-paths.ts` | Exits, routes and viewpoint anchors for each building |
| `apps/web/lib/scan-flood.ts` | Water height at each surge level for each building |
| `apps/web/lib/scan-hazard-pins.ts` | Hazard pin anchors for each building |
| `apps/web/components/scan/BuildingScan.tsx` | Scan URL for each building |
| `apps/web/lib/scan-evac-paths.test.ts`, `apps/web/tests/e2e/building.spec.ts` | Tests tied to those IDs |
| `apps/api/scripts/prewarm_cache.py` | Demo building list for the replay cache |
| `infra/supabase/migrations/0003_the_dock.sql` | Seed row for The Dock |

The engine (world model, routes, hazard timeline, crowd sim) is what should produce the venue's exits, routes and hazard timing, replacing these hand-placed tables.

## 3. The map

- `apps/web/app/dashboard/MapDashboard.tsx`, lines 45–51: Mapbox opens on a fixed Miami point (`center: [-80.2022, 25.8013]`, zoom 17, pitch 60, bearing -20). Center it on the venue, or better, on the buildings loaded from Supabase.
- `apps/web/app/page.tsx`, lines 39–48: the landing-page globe turns to face Miami and labels Miami, Tampa, New Orleans and Charleston.
- The token is `NEXT_PUBLIC_MAPBOX_TOKEN` in `apps/web/.env.local`. If you reuse Aria's token and it has URL restrictions, add `localhost` and the new deploy URL, or the map stays blank.
- For the venue's coordinates, right-click the building in Google Maps.

## 4. Flood → fire

The hazard model, the UI and the report are built around storm surge, flood and wind:

| Area | Files | Today |
|---|---|---|
| Agent prompt and report schema | `apps/api/app/agent/prompts.py`, mirrored by hand in `apps/web/lib/types.ts` | Hurricane, surge and flood in Miami-Dade; the report has `wind`, `surge` and `flood` sections |
| Agent tools | `apps/api/app/tools/registry.py`, `executors.py` | FEMA flood zone, Miami-Dade surge zone, nearby assets; all return fixed data |
| Scenario control | `apps/web/components/building/scenario.ts`, `ScenarioStrip.tsx`, `ScenarioProvider.tsx` | Surge slider: 0, 1, 3, 6 and 10 ft |
| Evac logic | `apps/web/lib/scan-evac-paths.ts` | Each exit blocks at a surge height |
| 3D layers | `apps/web/components/scan/BuildingScan.tsx`, `scanSceneLayers.ts` | Water plane; EVAC and hazard modes |
| Report UI | `apps/web/components/report/` | Wind, surge and flood cards and actions |
| Copy | `apps/web/app/page.tsx`, `apps/web/lib/brand.ts` (description) | Miami and hurricane language |

One way to do fire: swap surge height for time since ignition. The slider scrubs minutes, and rooms and exits block as smoke and fire reach them, using the hazard engine's timeline. That's an option, not a decision.
