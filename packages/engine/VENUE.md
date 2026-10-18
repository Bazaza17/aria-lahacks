# venue.json: the James West Alumni Center as a graph

`venue.json` is the engine's first building model (schema v0.1). It describes rooms and outdoor areas as **spaces** and every way between them as **openings**. Fire, routes and crowd all read it. It was built from:
- the checked annunciator-plan inventory (`docs/lahacks/venue-plan-inventory.json`);
- the first three scans (`docs/lahacks/10-scan-room1.md`, `11-venue-plan-and-scans.md`).

Where a scan and the plan disagree, the scan wins and the note says so. Values nobody has measured yet are placeholders and are marked as such. The file is meant to be edited by hand.

Today it holds 62 spaces (38 on 1F, 23 on 2F, 1 on 3F) and 96 openings: 15 exits, 5 stairs, 4 steps and a ramp. All 49 indoor spaces reach the outside.

## Frame and datum

- **Units:** metres and seconds.
- **Axes:** Y is up. Plan positions are `[x, z]` in **room 2's scan frame** (the lobby 110 scan), so `room2.glb` drops in with no transform.
- **Elevation 0.0** is lobby 110's finished floor, which is Y −3.91 in room 2's file. Any elevation is room 2's Y + 3.91.
- **Other scans:** rooms 1 and 3 map in with the transforms in `frame.scan_transforms`. They are good to about ±0.3 m near the junction of the three scans.
- **Plan positions:** anything read off the annunciator photo uses `frame.photo_to_venue`: x = −7.5 + (937 − X)/10.4 and z = (539 − Y)/10.4, where X and Y are photo pixels. For the 2F plan, subtract 578 from Y first. Expect ±1–2 m, because the photo was taken at an angle.
- **North is not verified.** If the compass's solid needle is north, north is −z and east is +x.
- **Polygons** run counter-clockwise in the `[x, z]` plane (positive shoelace area). In a true top view, which draws z pointing down, they look clockwise.

## Fields

**`storeys[]`**
- `id`: `1F`, `2F` or `3F`.
- `elevation`: in m. 2F (4.2) and 3F (7.8) are placeholders.
- `source`: where the value came from.

**`spaces[]`**

| Field | Meaning |
|---|---|
| `id` | See the ID rules below |
| `name`, `event_name` | Plain name; the LA Hacks map name, or `null` |
| `kind` | `room`, `lobby`, `corridor`, `restroom`, `elevator`, `closet`, `outdoor` or `open_to_below`. The schema also allows `stair` and `mech`; none are used yet |
| `storey`, `is_outdoor` | Storey id; true for courtyards, patios, plaza, lawn and terraces |
| `polygon` | `[[x, z], …]` in m, counter-clockwise |
| `area` | m², computed from the polygon |
| `floor_elevation` | m above the datum. Nonzero on 1F: the Galleria far end +0.62, 150 and the Collins Patio's south part +0.62 (unverified), the porch +0.62 (assumed), the Founders' lawn −0.6 |
| `height` | Ceiling above the floor, in m. A scan value where one was measured, else 3.0 (placeholder). `null` for open-sky outdoor spaces |
| `occupant_load`, `occupant_load_source` | People; see the load rules below |
| `detectors` | Alarm-device dots on the annunciator. One symbol covers all device types |
| `geometry_source` | `scan`: footprint measured by a scan. `plan_traced`: plan outline, nudged to scan walls where they exist. `plan_bbox`: rectangle from the plan |
| `scanned_by` | Which scans (`room1`, `room2`, `room3`) cover the space |
| `notes` | Free text |

**`openings[]`**

| Field | Meaning |
|---|---|
| `id` | See the ID rules below |
| `a`, `b` | Space ids. `b` may be `SAFE` |
| `kind` | `door`, `double_door`, `opening`, `gate`, `stair`, `ramp`, `step` or `elevator` |
| `position` | `[x, z]`: the centre of the opening, or the midpoint of the run for a stair or ramp |
| `clear_width` | m |
| `effective_width` | m. Clear width − 0.30 (0.15 m boundary layer each side, SFPE), never below 0. Fixed at **0** for elevators and floor voids: they carry smoke, not people |
| `width_source` | `scan`, `plan` or `placeholder` |
| `is_exit` | True when it leads from inside the building to outside, `SAFE` or a protected stair |
| `length` | m, for stairs and ramps; otherwise `null` |
| `rise` | m, for stairs, ramps and steps (also set on the elevator shaft); positive means `b` is higher. It matches b's floor minus a's floor to within 0.1 m: 100ST rises 3.58 m, from the far end's raised floor, and the lawn steps' −0.55 is the drop measured at the steps |
| `protected` | For stairs: true if interior smoke can't reach it (an enclosed rated stair, or the open-air west exterior stair); otherwise `null` |
| `notes` | Starts with `INFERRED` when no door is drawn and one was assumed to keep the graph connected, or `UNVERIFIED` for an opening that contradicts the annunciator |

**`unknowns[]`** lists what the plans and scans don't settle; treat each one conservatively.

Example:
```json
{"id": "S-110-galleria_far_end", "a": "110", "b": "galleria_far_end", "kind": "step",
 "position": [15.2, -12.2], "clear_width": 10.0, "effective_width": 9.7, "width_source": "scan",
 "is_exit": false, "length": null, "rise": 0.62, "protected": null, "notes": "Room 1: 4 risers ..."}
```

## IDs and special nodes

- **Space ids:**
  - the annunciator room number where there is one (`110`, `120`, `200G`);
  - otherwise a stable slug (`galleria_far_end`, `courtyard_north_lawn`, `well_over_110`);
  - for a numbered room the plan splits into parts, a suffix: `210_n`, `210_w`, `210_sw`.

  Never reuse or rename an id: routes and fire results key on it.
- **Opening ids:** `<prefix>-<a>-<b>[-n]`. The prefixes are `D` door, `O` opening, `G` gate, `S` step, `R` ramp, `ST` stair, `E` elevator and `V` vertical void or well edge. `OUT` replaces `b` on exits.
- **`SAFE`:** one sink node for the public way, never a space. Outdoor spaces reach it through `gate` or `opening` edges, sometimes via other outdoor spaces, and those edges are not exits. The exit is the building door into the outdoor space.
- **Skylight wells** (`well_over_110`, `well_mid`, `well_200st`) are 2F spaces of kind `open_to_below`. Their `V-` openings are floor voids down to the 1F space below, or well edges at 2F. Both are smoke-only. Routing must skip any edge with `effective_width` 0.

## Widths and occupant loads

**Widths.**
- Scan measurements are used where the docs give them. There are 8: the Founders' opening (4.5), the ANN door frame (1.7), D1 (1.2), the 100G door (1.05), the Galleria step (10.0), the ramp (1.5), the lawn steps (14.0) and the plaza's open court (13.5).
- Otherwise these placeholders are used: single door 0.9, double door 1.8, gate 1.5, cased opening 1.5 (or the corridor width if known), interior stair 1.1, exterior stair 1.5.
- `plan` widths (23) are used only where the drawing clearly shows the gap, such as open sides, passages between walls, well edges and the elevator shaft.
- 65 openings are still placeholders.

**Occupant loads.**
- Event capacities (standing, from the venue rental page), split by area where an event area spans several spaces:
  - Galleria 270: `110`, `galleria_far_end`, `corridor_core`
  - Collins Room 250: `140`, `150`
  - Collins Patio 320: both courtyard parts
  - Founders' Room 150: `120`
  - Founders' Patio 200: the paving and the lawn
- Everywhere else, NFPA 101-2021 Table 7.3.1.2:
  - business at 150 ft² (13.94 m²) gross per person, rounded up;
  - the 2F rooms the event map seems to use (`210_n`, `210_w`, `210_sw`, `219`, `210A`, `200`): assembly, less concentrated, at 15 ft² (1.39 m²) net per person.
- Zero for restrooms, closets, corridors, elevators, wells and non-event outdoor areas.
- Total: 1,236 on 1F, 627 on 2F, 3 on 3F.

## When a new scan arrives

1. Put it in the venue frame:
   - Align it to a scan it overlaps: click 2–3 shared points, then ICP.
   - Add its transform under `frame.scan_transforms`, with elevation = its Y + offset.
2. For each space it covers:
   - Replace `polygon` with the scan footprint, clipped to walls; recompute `area`.
   - Set `geometry_source: "scan"` and add the scan to `scanned_by`.
   - Replace placeholder `height` and `floor_elevation` values where the scan measures them.
   - Say in `notes` what changed.
3. For each opening it measures (tape beats scan; scan beats plan):
   - Set `clear_width`, recompute `effective_width`, and set `width_source: "scan"`.
   - Fix `kind` if needed, for example a "door" that is really a cased opening.
   - Drop the `INFERRED` or `UNVERIFIED` prefix once seen.
4. If the scan shows a door the plan lacks, add an opening. If it shows a drawn door is really wall, delete it. Then re-check that every indoor space still reaches `SAFE` (the validation lives with the generator, see below) and remove what is now settled from `unknowns`.
5. Keep ids stable. If a space must be split, give it new ids and say so in the notes.

**Highest-value next measurements:**
- the 2F elevation (count risers on the west stair);
- main entrance and porch door leaves;
- the Founders' opening;
- the ANN door frame;
- 100ST, the NE stair and the west stair widths;
- the 140/150 band;
- the Galleria–Collins openings;
- whether the terrace is outdoors.

## Current unknowns (short form; full list in the file)

- **North:** unverified.
- **Heights:** 2F/3F elevations and every 3.0 m height are placeholders.
- **Openings that may close:** the Founders' opening may be an operable wall. The ANN door frame may hold fire doors that close on alarm. D1 may be a bulkhead.
- **Galleria–Collins openings and the 140/150 step:** unverified.
- **Event 2F use:** unresolved. Loads assume the indoor 2F is the Networking/Workshops area.
- **Terrace:** assumed outdoor. Skylight-well edges at 2F are assumed open for smoke.
- **Stairs:** 100ST and the NE stair are treated as unprotected.
- **Inferred links:** several doors and links are assumed (notes start `INFERRED`). The space north of 130D is a dead end.
- **Outdoor routes:** the plaza's and patios' routes to the public way are only partly drawn.
- **Lawn access:** no step-free route to the lawn.

*Generator:* `make_venue.py` and `validate_venue.py` in Claude's session scratchpad, `venue_graph/`. Hand edits to `venue.json` are fine. Re-running the generator would overwrite them.
