# 14: Wiring the Paper restyle into apps/web

Sun Oct 18, ~5:50 AM. A plan, not code: nothing here is built yet.

**Source of truth:** the implementation brief `aria-web-restyle.md` (side-session notes, `paper-directions/`) and the locked Paper screens `building-landing-style.png`, `dashboard-landing-style.png`, `landing-1to1.png` (same folder; also at https://claude.ai/artifact/Q7DMN8gETi7touRFX1TEcc).

**Checked against `main` @ `840eca4`:** the brief was written at `a352f00`. Since then only `layout.tsx` (Vercel Analytics removed), `FireStartPicker.tsx` (shows the clean `label`) and `lib/scan-fire.ts` (`FireStart.label?`) changed in `apps/web`. Every line number the brief cites still points at the right code (a few are off by 1–2), and every data field it uses exists with that name. So: **build from the brief, plus the additions below.**

## Time and order

| Step | Files | Effort | Notes |
|---|---|---|---|
| 1. Tokens, fonts, CSS | `globals.css`, `layout.tsx` | ~20 min | Do first; everything else depends on it. |
| 2. Building page (the demo page) | page, BuildingCenterPane, BuildingScan, ScenarioProvider, SizeUpPanel, ScenarioStrip, scanSceneLayers, **FireStartPicker, PlaceSearch, fire-preview** | ~3.5–4 h | Most important. Event ticks +25 min (optional). |
| 3. Dashboard | MapDashboard, VenuePreplanCard, dashboard/page | ~1–1¼ h | Fix the map-remount bug first. |
| 4. Landing | app/page.tsx | ~1 h | Style only; keep today's copy. |
| Tests, greps, browser check | e2e spec, `pnpm check` | ~30 min | |

**Total about 6–7 hours of work.** With the freeze at 9 AM that doesn't fit one session. Recommended:

- **Step 1 first, here, then two sessions in parallel** (their files don't overlap after Step 1):
  - **Session A:** Step 2 (building page) + the e2e test. About 4 h.
  - **Session B:** Steps 3 and 4 (dashboard, landing). About 2¼ h.
- **Ship order:** each session commits per step on its own branch. Merge the building page to `main` as soon as it passes the demo check (Vercel deploys `main`); dashboard and landing follow. If time runs short, Step 2 alone is the win.

## Decisions for you (before we start)

1. **Red now means two things.** The brief turns Aria's routes that still leave people at risk red, the same red as self-chosen routes. In the venue data that happens from T+02:00. Options: (a) key reads "Aria plan" white / "At risk" red, so red always means danger *(recommended)*; (b) keep "Self-chosen" in the key and draw at-risk Aria routes dashed white.
2. **Headline wording.** Use the start's plan name up to the first " (": "Fire in Collins Room, part 140." matches the screen and never wraps onto the place search *(recommended)*. The raw room name can be 60+ characters (room 210_w).
3. **Timeline section (/0.4).** The screen lists the engine's events ("49 events": smoke reaches…, exit lost…); the brief uses the size-up's 4 moments. Events are richer but need the fire timeline lifted into the provider (+25 min, shared with the scrubber ticks). Moments are quick. *(Recommend events if Session A has time; moments otherwise.)*
4. **Dashboard /0.2.** The screen shows scan facts (1,346 people, 50 spaces, 3 floors, 14 exits) and an empty "Recent pre-plans". The brief replaces both with the pre-plan rows (fire in, first exit lost, exits lost in 15 min, at risk leaving at once). *(Recommend the brief: the screen's "Recent pre-plans" is the dead panel we removed.)*
5. **"1 building scanned"** vs the screen's "One building scanned and ready." *(Recommend spelling out one–nine.)*

## Additions to the brief, by step

### Step 1: tokens and CSS
- **Edit the Mapbox control CSS in place**; don't paste the brief's block over globals.css:125–153. Pasting drops the icon invert (dark icons vanish), the transparent buttons and the attribution styling.
- **Place pins:** besides the brief's two lines, set the radius to 0, the background to `rgb(14 16 19 / 0.88)`, remove `backdrop-filter`, use `--font-dm-mono` with 0.05em spacing; keep the dashed border for plan-only pins (globals.css:158–179).
- **Scrubber hit area:** a 1 px tall input can't be clicked to scrub. Keep the input ~12–16 px tall and draw the 1 px line as a centred background (or on the `-runnable-track`/`-range-track` pseudo-elements), thumb `margin-top: -4.5px`; keep the `:active` grabbing rule.
- Run `pnpm --dir apps/web format` before each commit: the brief's one-line CSS fails `prettier --check`.

### Step 2: building page
- **Files the brief leaves out:**
  - `FireStartPicker.tsx`: drop the orange box and "FIRE STARTS IN" label (:18–19), the `animate-pulse` RUNNING (:39) and `text-red-300/80` OFFLINE (:40). Keep `bg-page` on `<optgroup>`/`<option>` (Windows Chrome draws a white dropdown otherwise). Keep `aria-label="Space the fire starts in"`.
  - `PlaceSearch.tsx`: "↳ FIND A PLACE" needs an open/closed state; recolour :50 (FIND), :68 (`#ffb27a`), :74 (`text-fuchsia-300`); remove the box/blur (:39, :46, :59); `pointer-events-auto` on its wrapper (the headline box is `pointer-events-none`).
  - `app/fire-preview/page.tsx`: `bg-[#0a0a0a]` → `bg-page`; it renders BuildingCenterPane without a name, so make the new name prop optional.
  - `BuildingScan.tsx:368–385` no-scan state and :428–437 loading text: `bg-scan`, caps, `text-fire`, no border.
  - `SizeUpPanel.tsx:158` ways-down storey colour → `text-quiet`.
- **Lifting the picker into the panel:**
  - `ScenarioProvider` needs a `buildingId` prop (BuildingCenterPane passes it) and `fireStarts` in its context.
  - The picker's busy/failed come from SizeUpPanel's own `busy`/`failed`; its value is `fireStart ?? sizeUp.origin.space`. Then delete `fireBusy`/`fireFailed` from BuildingScan.
- **Headline:** pass the building name page → BuildingCenterPane → BuildingScan. Put the headline and the place search in one `absolute left-8 top-9 flex flex-col` box rather than a fixed `top-[208px]`. Make the headline the page's `<h1>` and the breadcrumb name a `<span>`.
- **After deleting the status row**, remove the now-unused `fireEvent`, `departure`, `indicative` and the imports `latestEvent`, `formatClock` in BuildingScan (keep `frameAt`, `departureAt`).
- **Times are seconds:** everything the brief writes as `T+{dep.t0_s}` or `lost_s` goes through `formatClock()`. `lost_s` is optional in the type: guard it.
- **Layout:** the left column keeps `min-h-0` or the canvas pushes the scrubber off screen. In SizeUpPanel drop `divide-y` (:215), which doubles the new section borders; keep `min-h-0 flex-1 overflow-y-auto`.
- **Captions vs route key:** five DM Mono captions are ~946 px wide in a 1080 px scan column and collide with the key. Shorten the values or drop the hint.
- **Scene:** the shader snippet goes inside the existing `isMesh` branch (BuildingScan:254–261). Change the HemisphereLight ground `0x445566` → `0x4a4f55` (:200) or the grey scan reads blue.
- **"↳ {n} more exits"** counts rows (a ×2 pair is one row).
- **Event ticks / events list:** `fireTimeline` lives in BuildingScan but ScenarioStrip is rendered by BuildingCenterPane; lift the timeline (or its `events`) into ScenarioProvider.
- Keep "Live console ↗" a plain `<a href="/live/view">`, not `next/link`: `/live/*` is a rewrite to the API.

### Step 3: dashboard
- **Fix first:** `const secondary = buildings.slice(1)` (MapDashboard.tsx:31) is a new array every render and sits in the map effect's deps (:252), so every state change destroys and rebuilds the map. It already happens on popover clicks; with a selected-building panel it would reset the camera on every click. `useMemo` it.
- `pointer-events-none` on the headline and captions so they don't block map drags.
- Removing the popover also removes `PopoverState`, `popover` state, `closePopover`, `onMove`/`map.off`, the Escape handler and (with the rAF pulse gone) `rafRef`. The click handler sets the selected building instead.
- VenuePreplanCard: keep a "Running…" state (the first `/engine/summary` is slow); show "Pre-plan pending" for non-venue buildings (the size-up only exists for the venue) instead of ENGINE OFFLINE. `T+{exits_lost[0].lost_s}` needs `formatClock` and an empty-list guard.
- If the optional square `mapboxgl.Marker` is built, give it its own click handler (it swallows the map click).

### Step 4: landing
- The done-grep misses the canvas oranges: `rgba(255,107,0,…)` (:105, :133–135, :202–239, :277), `rgba(255,120,20`/`rgba(255,90,0` (:125–127) and the warm `rgba(26,22,20` body (:145). Add them to the grep.
- Hero fade `from-black` (:369) → `from-page`; widen the hero container (:378) to match the screen's left edge.
- Move the SectionLabel rows for The problem (:448) and How it works (:509) above their grids so the rule runs full width; delete the step dividers (:489, :495, :501) and `space-y-8` (:483).
- Drop the infinite SCROLL bounce (:431–433). Canvas font weight 600 → 500 (DM Mono loads 400/500 only); read `--font-dm-mono` once, outside `draw`.
- `BRAND_WORDMARK` → `BRAND` in MapDashboard and page.tsx.

## Tests and checks
- **e2e `tests/e2e/building.spec.ts`:** :13, :14, :18, :21 and :30 assert text the restyle removes. Replace with: the headline by role, `"People in the building"`, the picker's value plus "Fire in Founders' Room", and `/leave at T\+07:00/i`. `caps` only uppercases in CSS, so match source case or use `/i`. :24 `getByLabel("Fire timeline")` probably already fails strict mode (it also matches "Play fire timeline"): use `getByRole("slider", { name: "Fire timeline" })`. This test has never run on this machine: `npx playwright install` first, and it needs the API.
- **Wider done-grep:** also `red-[0-9]|0xef4444|0xf59e0b|0xe879f9|255, ?107, ?0|255,120,20|255,90,0|#0a0a0a|bg-black|rounded-(sm|md|full)|shadow-\[|backdrop-blur`, plus `animate-ping|animate-pulse` and stray `tracking-[0.2em|0.3em]` next to `caps`.
- **Contrast:** `faint` (#5C6066) on the page is ~3:1, too low for 10 px text judges must read. Use `dim` or `soft` for anything important.
- **Check against the deployed API:** point the local web at the Railway API (`NEXT_PUBLIC_API_URL`), never a local API on the shared database. Without the API only the default fire timeline has a fallback; the panel and the dashboard card need it.

## Ignore in the screens
Stale text the screens still show: MESH / EVAC / HAZARDS tabs, "PHONE LIDAR · 5 MIN", "±5 CM", exit ids like D-110-OUT-2 with people counts (the size-up has labels and times, not per-exit counts), and the dashboard's "Recent pre-plans". Use today's captions (SCAN, STITCH, MESH, REST, FIRE) and data.
