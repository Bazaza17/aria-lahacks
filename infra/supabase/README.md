# infra/supabase

Supabase holds the venue row the web app reads and the public `scans` storage bucket with the
LiDAR mesh. The live incident data (CREAO layer) is in Tiger Data, not here.

## Setting up a fresh project

Run these in the SQL editor, in order:

| File | What it does |
|---|---|
| `migrations/0001_init.sql` | `buildings`, `preplans`, `tool_calls` tables. Also inserts a Miami placeholder row from the original build; it is unused (0005 clears its `is_demo`). |
| `migrations/0002_cached_runs.sql` | `cached_runs` table (from the old replay cache; nothing writes to it now) |
| `migrations/0004_rls.sql` | Row level security: anon can read `buildings` and `preplans` only |
| `migrations/0005_venue.sql` | Upserts the venue row `547b5ec5-30c5-4f76-8080-012a52e90bd9` (James West Alumni Center). Replace `YOUR-PROJECT-REF` in its `scan_url` first. |

There is no `0003`: it pointed at the original Aria's storage and was removed.

Then create a public bucket named `scans` and upload the mesh to
`scans/james_west/venue_4rooms_web.glb`. Meshes (USDZ, GLB) never go in git.

The web app finds the row through `NEXT_PUBLIC_VENUE_BUILDING_ID` in `apps/web/.env.local`.
