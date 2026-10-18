# 13: Engine accuracy and place lookup: audit results and plan (Sun ~1:45 AM)

# Aria engine and place lookup: plan to the 9 AM freeze

This plan combines the alignment, fire and place-lookup audits. Nothing in the repo was changed. The effort figures are the audits' own estimates.

## 1. Verdict

- **Plan vs scan:** On the scanned ground floor, the floor plan already works as an invisible support under the scan.
  - 98.9% of the scanned floor falls inside a plan polygon, floor heights match to about 0.05 m, and walls sit a median 0.2-0.5 m from the plan edges.
  - The Collins Room (140/150) is the exception. It is still a plan rectangle (0.8 m median offset, 2.7 m worst), and its corridor door is drawn on solid wall 3.1 m from the real opening.
- **Fire model:** The core physics is right. 12 of 14 hand checks agree: t² growth and the 2:22 radiant limit exactly, NFPA 92 smoke filling within about 10%, Thomas flashover and door flow exactly.
  - Building-level results are too optimistic. Smoke spilling from a side room into the 8 m atrium pulls in no air.
  - Because of that, the 2F goes untenable at 4:20 instead of about 1:00-1:45, and "0 at risk if everyone leaves at ignition" becomes about 300.
  - Door and skylight states the data marks as uncertain move results by minutes.
- **"Ping a place":** Not built yet. There is no place index, alias list or search, and agent pins on the venue scan land essentially at random (`BUILDING_SLOTS` has no `venue` entry).
  - The data supports it. The viewer already uses the right plan-to-scan transform, and 12 of the 20 test pings the audit resolved manually land within 0.2-0.4 m.
  - The misses are the Collins doors, check-in (no landmark, 9 m off) and places off the scan: ST-W ("Stairs to 2nd floor") and all of 2F/3F.
- **Dashboard readiness:** The output is complete but buried in an 830 KB payload.
  - It has no per-space table of time available vs time needed, with a margin and a confidence level.
  - Its "first untenable" headline can be an empty landing.
  - The viewer draws lobby smoke at 7.6 m in a 3.6 m room.
  - Two bugs: `--no-origin-limit` crashes, and in a few 110 runs Aria's plan puts more people at risk than the reactive routes.

## 2. The plan

**Messages to send before you start (about 5 min):**
- **fire.py owner** (the audit says a teammate owns it): task 4 adds smoke entrainment to `_Sim.step`.
- **Web owner:** task 5 adds a place layer to `BuildingScan.tsx` and `scanSceneLayers.ts`.
- **Messenger owner:** `apps/messenger/src/venue.ts` is a fake sample layout ("Stairwell A next to the main entrance"). The text and voice agent could send people to stairs that don't exist. Point it at `places.json` once task 3 is done.
- **API and web owners:** task 8 adds optional `place_id` and `at` to `Annotation3D`, which is a shared contract. That change waits until the teammate's push lands.
- **You, at the venue:** where are the check-in desk, the stage and the sponsor rows? Please also confirm the ANN / YOU ARE HERE panel is at about (11.6, -0.9).

**Rules for every task:**
- After any engine or `venue.json` change, regenerate `apps/web/public/fire/venue.json` (`engine.demo --viewer-out`). Once task 3 exists, regenerate `places.json` in the same step.
- Run the engine pytest, and run `pnpm --dir apps/web build` before committing.
- Make one commit per task.
- Merge the teammate's push between tasks, never in the middle of one.

**1. Quick output fixes: 25 min (Lane A)**
- **`--no-origin-limit` crash:** `round(inf)` in `venue_timeline`, `packages/engine/engine/routes.py:157`. Use `None if math.isinf(origin_limit_kw) else round(origin_limit_kw)` and guard the `why` f-string. Add a test that calls `run_demo(origin_limit=False)`.
- **Smoke drawn above the ceiling:** in `outputs.frames` (`packages/engine/engine/outputs.py`), cap `layer_height_m` at `av.height(sid)` and add `smoke_depth_m`.
- **150 shows as burning:** `fire.spaces[150].ignition_s = 0`. Set it to null for every part of the origin room except the one where the fire starts.

**2. Snap the Collins Room to the scan: 40 min (A)**
- In `packages/engine/venue.json`, set the 140+150 outline to NW (19.1,-2.4), NE (33.65,-1.3), SE (33.6,-20.9), SW (21.55,-22.9).
- Split it along (20.5,-13.2)→(33.6,-10.9) and move S-140-150 to (27,-11.8).
- Move the doors:
  - D-140-corridor_core to (19.9,-6.5)
  - D-140-OUT to (33.6,-9.5)
  - D-150-OUT-1 to (33.6,-18.35)
  - D-150-OUT-2 to (21.5,-22.85)
  - D-130D-140 to (29.3,-1.6), or mark it UNVERIFIED
- Set `geometry_source=scan`, recompute the areas and keep the ids.
- The areas change, so re-run the closed-Collins NFPA 92 check (hand value 178-190 s).
- **Done when:** pytest passes and the doors sit in the scanned gaps.

**3. Place index in the engine: 60 min (A)**
- Write a new `packages/engine/engine/places.py`, stdlib only, ported from `scratchpad/audit_places/places_proto.py`. It needs `build_index`, `search`, `space_at` and a CLI. `--index --out ../../apps/web/public/fire/places.json` writes the index.
- Add to `venue.json`:
  - **`aliases`** on about 15 features:

    | Query | Resolves to |
    |---|---|
    | main entrance | D-110-OUT-1/2 |
    | stairs to 2nd floor | ST-W |
    | 100ST, open stair | ST-100 |
    | ramp | R-110-galleria_far_end |
    | FACP | 130C |
    | Collins Room | 140 + 150 |
    | food area | courtyard_sw_south |

  - **`ends`:** ST-100 at galleria_far_end [14.3,-20.2] and landing_200st [12.7,-18.8]; ST-W at w_stair_enclosure [47.8,-2.0] and terrace_landing [35.3,-2.4].
  - **`pin`** overrides for galleria_far_end, 120 and 150. Their default points land on furniture or holes in the scan.
  - **Landmark points**, but only where the position is actually known.
- Search rules:
  - Run the exact id/alias pass before parsing floor words, so "stairs to 2nd floor" finds ST-W instead of filtering to the 2F.
  - Never resolve compass words. The venue's "west" means +x, but `frame.north` says +x is east. Write this down in `VENUE.md`.
  - When several places match, return all of them and flag the result `ambiguous`. Examples: Collins Room, main entrance, "stairs first floor" (4 stairs), and "fire alarm panel" (the ANN panel or the control panel, about 20 m apart).
  - Fix "upstairs" on its own returning nothing.
- Tests: `tests/test_places.py`, plus a shared `tests/places_queries.json` fixture.
- **Lane A reaches T+2:05 here**, which unblocks Lane B.

**4. Smoke entrainment into the atrium (the largest accuracy gain): 60 min (A)**
- In the door-spill branch of `_Sim.step` in `packages/engine/engine/fire.py`: when smoke from a room that is burning but hasn't flashed over rises into a taller indoor space, and that space's smoke layer is above the door top, do two things:
  - add `plume_mass(Qc, h_edge+rise) - plume_mass(Qc, h_edge)` to the mass delivered;
  - mix the temperature accordingly.
- Add `SPILL_ENTRAINMENT = 'axisymmetric'` as the default, with `'balcony'` (the NFPA 92 upper bound) and `'off'` as options. Port it from `scratchpad/audit_fire/aud_spill_axi.py`.
- What to expect in a 140 fire, from the audit's scratch patch:

  | Result | Now | With the fix |
  |---|---|---|
  | 2F untenable | 4:20 | 1:42 |
  | 150 untenable | 7:11 | 5:03 |
  | Galleria untenable | 8:31 | 5:55 |
  | 110 untenable | 9:06 | 6:47 |
  | At risk, everyone leaving at ignition | 0 | 301 |

- Check that the single-box NFPA 92 cases don't change (they have no doors). Regenerate `examples/` and the viewer JSON.

**5. "Find a place" in the viewer, with pins snapped to the scan: 90 min (Lane B)**
- Start now against a stub `places.json`. Swap in the real file at about T+2:05, when task 3 lands.
- New files:
  - `apps/web/lib/scan-places.ts`: loading, a port of the ~40-line search, and `placeToWorld` = (x−c.x, −3.91+elevation−c.y, z−c.z). This is the same transform `buildFireLayer` already uses.
  - `components/scan/PlaceSearch.tsx`.
- In `scanSceneLayers.ts`, add `buildPlacePinLayer`: a dot, a floor ring, a beam that shows through walls, a label, and an outline when the match is a space.
- In `BuildingScan.tsx`:
  - Keep the scan group in `SceneBundle`.
  - Raycast down once per search. Take the hit within ±0.35 m of the plan elevation that is closest to it, not the first hit.
  - If there's no hit, search on rings inside the polygon. If that fails too, mark the pin as off the scan.
  - Focus the camera on the result.
- Draw plan-only pins hollow and tag them "plan ±1.5-2.5 m".
- **Done when:**
  - "stairs first floor" lands on the 100ST treads;
  - "Collins Room" outlines both parts;
  - "main entrance" shows both door pairs;
  - "room 219" shows as plan-only;
  - the build passes.

**6. Dashboard block, time available vs time needed: 105 min (A)**
- Add `outputs.dashboard(av, vt, deps, pre_movement_s)`. It writes `result['dashboard']` (about 10 KB) and the matching viewer block.
- For each occupied space, include:
  - occupants
  - time available (`aset_s` plus m:ss) and whether smoke or heat ends it (`untenable_by`)
  - time needed (`rset_s` = departure time + pre-movement + time the last person gets out)
  - margin
  - exit
  - bottleneck
  - status
  - confidence
- Confidence is low when the space sits within 0.25 m of the smoke-layer limit for more than 60 s. 150 does this for 197 s.
- Add `--pre-movement S` to `demo.py`, defaulting to 60-90 s for an assembly occupancy with an alarm (cite PD 7974-6). Show both "everyone moves now" and "realistic".

**7. Key moments, exit-loss reasons and bottlenecks: 45 min (A)**
- `summary.key_moments`: 5-8 entries of {t_s, mmss, severity, text, venue_ids}. Include each exit lost and why, and mark the first flashover "beyond screening".
- `summary.bottlenecks`: the top 3 openings for each departure time.
- Replace the headline with `first_occupied_untenable`, so it can't be an empty landing.
- **Lane A ends at about T+5:35.**

**Stretch tasks.** Lane A does these only if it's ahead of schedule. Lane B has time for 8 and 12.

**8. `locate_place` agent tool: 60 min (B, after the push lands)**
- Add the tool in `apps/api/app/tools/registry.py` and `executors.py`.
- Add optional `place_id` and `at {x, z, elevation}` to `Annotation3D` in both `apps/api/app/agent/prompts.py` and `apps/web/lib/types.ts`. Add one prompt line telling the agent to call the tool for every annotation.
- In `apps/web/lib/scan-hazard-pins.ts`, make `pinsFromReport` use `at` or `place_id`, falling back to `resolveAnchor`.
- For tonight, use the packaging fallback: generate `apps/api/app/data/places.json` and a vendored `search()` marked as generated, and keep it in sync with the shared fixture. Test the image build either way.

**9. Sensitivity ranges: 45 min (A)**
- In `demo._sensitivity`, add these cases: all skylight-well edges closed, both Collins openings closed, 2F ceilings at 2.7 m and 3.5 m, wall loss 0.4 and 0.8, and entrainment off vs balcony.
- Output the min and max time for each space, and the min and max at-risk count. Feed them into task 6's confidence flag.

**10. Plan never worse than the reactive routes: 25 min (A)**
- In `engine/evacuate.py`, use the reactive routes when they leave fewer people at risk, and record `plan.chosen='reactive_fallback'`.
- Test: start 110, medium growth, departure at 105 s (today the plan leaves 458 at risk vs 420 reactive).

**11. Small polygon and door corrections: 25 min (A)**
- In `venue.json`:
  - move the 110/galleria step edge to the scanned step;
  - move the 110/170 notch to x≈0.1;
  - move the 110 strip edge to about x=19.7;
  - close the nw_walkway sliver.
- Mark these as UNVERIFIED, because they are drawn on solid scanned wall: D-galleria_far_end-OUT-2, D-corridor_core-131, D-corridor_core-120 and G-courtyard_north-entry_plaza.
- Add room 4 to `frame.scan_transforms`.

**12. Pins for places off the scan: 30 min (B)**
- In `scanSceneLayers.ts`, draw a ghost footprint, a label and an arrow at the edge of the scan for ST-W, Collins Patio, the NE stairs and 2F rooms.
- A ground-floor ping on ST-W uses its foot at (47.8,-2.0).

**13. Validity flags: 25 min (A)**
- `fire.validity` lists what the result rests on:
  - the merged-room box (±20%)
  - the entrainment mode
  - "Thomas not applicable" for rooms open to the atrium
  - placeholder 2F heights
  - assumed door states
  - the occupant scenario
- Add `fire.spaces[id].marginal_window_s`: how long each space sits within 0.25 m of the limit.

| Lane | Order | Time |
|---|---|---|
| A: engine (you) | 1 → 2 → 3 → 4 → 6 → 7, then 9, 10, 11, 13 | about 5h35, plus stretch |
| B: a second session in its own worktree (web, then API) | 5 → 8 (once the push lands) → 12 | about 3h |

Lane A has only about 25 minutes of slack.

## 3. What to tell judges about accuracy

**Framing:** Aria is a zone-model screening tool, not CFD. Its physics is checked against the standard hand calculations. Every point and time it shows says where it came from (scan or plan) and how sure it is.

**What we validated: 12 of 14 hand checks agree, 1 agrees partly, and 1 is a missing term that task 4 fixes (if it lands):**

| Check | Engine | By hand | Agreement |
|---|---|---|---|
| Fast t² fire growth (SFPE / NFPA 72) | 1055 kW at 150 s, 4221 kW at 300 s | same | exact |
| Radiant limit, 2.5 kW/m² at 3 m (ISO 13571) | 942 kW at 2:22 | same, for every growth rate | exact |
| Smoke filling, atrium (NFPA 92 2021, eq. 5.5.2.2) | 251 s | 250 s | within 1% |
| Smoke filling, Founders' Room | 137 s | 134 s | +2% |
| Smoke filling, Collins Room with its openings closed | 168-173 s | 178-190 s | 6-9% early (conservative) |
| Smoke filling across 6 room shapes | | | −7% to +11% at medium growth; 5-20% early at ultrafast |
| Flashover, Collins with its openings closed (Thomas 1981) | 8.45 MW at 7:05 | same | exact |
| Flashover, Founders' Room | 16.6 MW at 9:55 | same | exact |
| Door vent flow (SFPE) | 8.17 kg/s | 8.17 kg/s | exact |
| Smoke-layer temperature (MQH 1981) | | | within range for Collins; 18-42% low for the Founders' Room |

Say the Founders' Room temperature gap out loud rather than leaving it out.

**How well the floor plan matches the scan:**
- 98.9% of the scanned floor lies inside a plan polygon. The rest is within 0.2 m of an edge, and no polygons overlap.
- Floor heights match within about 0.05 m.
- In scanned rooms, the plan's wall edges sit a median 0.2-0.5 m from the scanned walls.
- Ping accuracy: main entrance 0.2 m, ground-floor stairs 0.22 m, Founders' Room 0.25 m, elevator 0.35 m, restrooms 0.41 m.
- Re-measure Collins after task 2 before quoting a number for it.

**What to say up front:**
- **People at risk:** quote these as ranges from the final regenerated run, never as single numbers.
  - Before task 4, "nobody at risk if everyone leaves at ignition" was too optimistic. The audit's scratch patch gave about 300 at risk, and up to 391 with the NFPA 92 balcony bound.
  - The counts use the stress scenario, with 627 people on the 2F. Without pre-movement time (task 6) they are lower bounds.
- **Door states matter most.** One Collins opening moves the time 150 is lost from 7:11 to 2:16. Whether the skylight-well edges are railing or glass (unknown) decides whether the 2F goes untenable at all. Frame this as a feature: Aria tells responders which unknowns to check first.
- **2F/3F are plan-only.** They come from the annunciator photo (±1-2 m) and use placeholder heights (2F floor 5.0 m, ceilings 3.0 m). In a Collins fire, ceiling height alone moves the at-risk count at the 2-minute mark from 4 to 313.
- **The atrium is modeled as one merged box (±20%).** Results after flashover are indicative only; in today's fast Collins run flashover comes at 10:19.
- **Two scan rooms sit 4-9° off the plan grid** because of how the scans were registered. Their polygons are traced to the scan (Collins after task 2), so pings there still land.

**Evidence to show:** the audit's overlay images are in a temporary scratchpad, so copy them into `docs/lahacks/`:
- `audit_align/pings_top.png`
- `audit_align/reg2_collins.png`
- `audit_align/reg2_galleria.png`
- `audit_align/reg2_founders.png`

Put the hand-check table on one slide.

## 4. What not to do

- **Don't re-register rooms 1 and 4 or rebuild the combined GLB.** It takes about 2 hours, and room 4 is also warped by 4.8°, so 0.5-1 m errors would remain anyway. Rotating the plan-only neighbouring rooms to match can wait too.
- **Don't tune physics constants to get nicer numbers.** That includes the wall-loss fraction, the fuel-load table and well-edge heat loss. Each change means re-running the NFPA 92 checks (the engine must stay within ±15%), and none of it shows in the demo.
- **Don't add new physics.** That includes a peak heat-release cap, visibility or toxic-dose models, ceiling-jet travel time, or fire spreading through floors. These biases are documented, and each is small or conservative next to the missing entrainment.
- **Don't chase 150's exact time.** It sits within 0.25 m of the limit for 197 s, so any input change moves it by minutes. Flag it as low confidence instead.
- **Don't guess positions or labels you don't have.** That covers check-in, the stage, sponsor rows, restroom genders and the 2F "Networking/Workshops" labels. Leave them out or mark them uncertain.
- **Don't present 2F/3F pins or times as measured.**
- **Don't move the API's Docker build context to the repo root tonight.** Use the generated-JSON fallback. Don't touch `registry.py`, `executors.py`, `prompts.py` or `types.ts` until the teammate's push is merged.
- **Don't add Shapely/polylabel to the engine or a BVH library to the viewer.** Pin overrides plus the ring search cover the same cases, and one raycast per search is cheap enough. Never raycast every frame.
- **Don't style the dashboard or slim the 830 KB payload yet.** Ship the compact JSON block and let the UI catch up later.
