# 12: Handoff, Sat Oct 17 ~11:20 PM

The state of the engine and scan work, in case a session ends mid-task. Newest first.

## In flight when this was written

**Engine slice 1, fix pass** (a background run in Lincoln's Claude session).
- **What it was doing:** applying the reviewers' fixes to the slice-1 code: splitting `engine/aria_venue.py` into `engine/geometry.py` and `engine/route_graph.py`, editing the teammate's `engine/fire.py`, and writing example outputs to `packages/engine/examples/`.
- **The slice-1 code as first built is already committed** in `95cb9e7` ("Packages at last"): `engine/aria_venue.py`, `engine/routes.py`, `engine/demo.py` and `tests/test_aria_venue.py` / `tests/test_routes.py`.
- **Check whether the fix pass finished cleanly:**
  ```bash
  cd packages/engine
  uv run pytest -q
  uv run ruff check .
  uv run python -m engine.demo --start 140 --summary
  uv run python -m engine.fire --events
  ```
  The last command is the teammate's CLI; it must still work.
- **If it was cut off and those fail,** go back to the committed slice 1. This keeps `venue.json`, which has the Collins update below and should be kept:
  ```bash
  git checkout -- packages/engine/engine/aria_venue.py packages/engine/engine/fire.py
  git clean -n packages/engine/engine/
  ```
  `git clean -n` is a dry run that lists untracked files. Once the list shows only `geometry.py` and `route_graph.py`, delete those two.
- **Review the `fire.py` diff before committing.** It's the teammate's file, so tell them what changed.

## Not committed yet (reminders)

1. **`packages/engine/venue.json`:** the Collins Room scan values (140 at +0.16, 150 at +0.70, a 0.54 m step, 3.3 m and 9.3 m Galleria openings, ceilings 3.7 / 3.15 m, arcade levels). A 34-line diff, with a `changelog` entry. All engine tests pass with it.
2. **The slice-1 fix-pass diff,** once it's checked as above.
3. **`docs/lahacks/img/scans_combined_4rooms.png`** and this file.

## Done

- **Venue graph** `packages/engine/venue.json` v0.1:
  - 63 spaces, 99 openings, 1,866 people, in the venue frame (room 2's scan frame, metres).
  - Field docs are in `VENUE.md`; the diagram is `docs/lahacks/img/venue_graph.png`.
  - Finding: the 2nd floor has only one way down that avoids the Galleria atrium (terrace → west exterior stair ST-W).
- **Four-room combined model:**
  - Rooms 1–4 (Galleria far end, lobby 110 + entrance, Founders' Room + patio, Collins Room) stitched in the venue frame.
  - Saved, gitignored, at `apps/web/public/scans/venue_4rooms_web.glb` (10.3 MB: meshopt, WebP, metallic 0) and `venue_4rooms_full.glb` (73 MB).
  - Validator: 0 errors, 0 warnings. Preview: `docs/lahacks/img/scans_combined_4rooms.png`.
  - The full file is over Supabase Free's 50 MB cap; upload the web one.
  - Before uploading to the public `scans` bucket, decide about the attendees visible in the lobby textures.
- **Scanning:** finished (dark). The 1st floor is scanned in four rooms; everything else comes from the annunciator plan. Docs: `10-scan-room1.md` and `11-venue-plan-and-scans.md`.
- **Collins Room transform** into the venue frame:
  `x2 = −0.120·x4 − 0.993·z4 + 23.58 ; z2 = 0.993·x4 − 0.120·z4 − 12.93 ; Y2 = Y4 − 0.26`.
  - About 6–7° off the lobby grid, inherited from room 1.
  - The other rooms' transforms are in doc 11.

## Next

1. **Finish and commit slice 1** (above).
2. **Read the merged `fire-viewer` branch** (`a105ec9`) before building any viewer integration. It may already draw the teammate's fire output (`apps/web/public/fire/venue.json`).
3. **Wire the engine into the API** (a FastAPI route that runs `engine.demo`'s pipeline) and the viewer (fire spread plus predictive vs reactive routes on the four-room scan).
4. **Upload the four-room web GLB** and set the venue's `scan_url` (venue id `547b5ec5-30c5-4f76-8080-012a52e90bd9`). The viewer needs no code change: it uses the database `scan_url` for the venue.
