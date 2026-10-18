# engine

Aria's building engine: a plain Python library (no HTTP) that `apps/api` imports.
This first slice is the **building graph** and a **fire timeline**: from one start room, when
each room and door stops being usable for escape.

## Run it

```bash
cd packages/engine
python -m engine.fire --venue engine/data/james_west_sample.json --start f1-main-hall --growth fast --horizon 900
python -m engine.fire --start f1-main-hall --events   # readable event list
python -m engine.fire --start f1-main-hall --frame-step 5   # snapshots every 5 s (0: none)
python -m pytest -q                                    # physics and venue tests
```

With uv: `uv run python -m engine.fire ...` and `uv run pytest`. No runtime dependencies.

From Python:

```python
from engine.venue import load_venue
from engine.fire import simulate

tl = simulate(load_venue(), "f1-main-hall", growth="fast", horizon_s=900, frame_step_s=10)
tl.blocked_at(300)   # {"f1-main-hall", "d-north-patio", ...}: rooms and doors you can't use at t=300 s
tl.to_dict()         # the JSON the CLI prints
```

## The building graph

`engine/venue.py`, loaded from JSON:

- **Rooms** (nodes): id, name, floor, floor area (m²), ceiling height (m), fuel class, optional
  perimeter and window area, and an optional `footprint` on the scan (below). With a footprint,
  `area_m2` and `perimeter_m` can be left out; they're computed from the box. A stairwell is one tall room (`"kind": "stair"`) that spans the floors
  it serves.
- **Doors** (edges): the two rooms they join (or a room and `"outside"`), the floor they sit on,
  width, open or closed, fire rating in minutes, and an optional `position` on the scan.
- **Exits**: a label plus the door they use. Also refuge areas and the assembly point.

Room and door ids share one namespace, so `blocked_at` can return both.

### Footprints on the scan

So the web viewer can draw fire and smoke on the 3D scan (like the old flood plane), rooms and
doors can be placed in the scan's own coordinates. The venue's top-level `scan` block names the
mesh and the frame:

```json
"scan": { "file": "10_17_2026.glb", "frame": "GLB mesh coordinates, metres, Y up, no node transforms",
          "floor_y": -0.85, "note": "rough first pass traced from scan shape" }
```

- `"footprint": {"x": [x_min, x_max], "z": [z_min, z_max]}` on a room: an axis-aligned box on
  the floor plane, in mesh X and Z (metres, Y up, read straight off the GLB vertices with no node
  transforms applied).
- `"position": {"x": .., "z": ..}` on a door: a point on the shared wall. Both rooms a door joins
  touch at that point (a test checks this).
- `floor_y` is the floor 1 height in mesh Y. A room's floor in mesh Y is
  `floor_y + floor elevation`, and its smoke layer sits `layer_height_m` above that.

The sample footprints are a rough first pass traced from the scan's shape. Floor 2 isn't in the
scan, so its footprints are placeholders laid over floor 1.

### Sample venue (unverified)

`engine/data/james_west_sample.json` is **sample data**. Its exits, stairwells, refuge area and
assembly point match `apps/messenger/src/venue.ts`. The floor 1 sizes are rough reads of the
10/17 Polycam scan: about 34 × 22 m overall, a tall west section (5–6 m ceiling) taken as the
main hall, and 3–4 m ceilings elsewhere. Room areas come from the traced footprints. Floor 2 isn't in the scan, so its rooms are placeholders.
Door states assume an event night: hall doors propped open, exterior and stair doors closed.
Replace it with the traced floor plan when that exists.

## The fire model, in plain language

It's a **zone model**: each room is one box with a smoke layer under the ceiling, the standard
hand-calculation approach in fire engineering (what CFAST does, much simplified). It runs in
1 s steps. Every constant is in `engine/constants.py` with its source.

1. **The fire grows as Q = αt²** (SFPE t-squared fires; slow, medium, fast and ultrafast reach
   1 MW in 10, 5, 2.5 and 1.25 min). It stops growing at the smaller of two caps: the fuel limit
   (peak heat release per m² for the room's occupancy, from Eurocode EN 1991-1-2) and the air
   limit (about 1500 kW per unit of the openings' A√H). After 70% of the room's fire load has
   burned, it dies down linearly (Eurocode).
2. **Smoke fills the room from the ceiling down.** The plume above the fire pulls in air (NFPA 92
   plume equations). That mass collects under the ceiling, and the layer thickens. The layer's
   temperature comes from the plume, with 60% of its heat assumed lost to walls and ceiling.
   Cross-check: for the 220 m², 5.5 m main hall with a fast fire, NFPA 92's smoke-filling
   correlation puts the layer at 2 m after about 180 s; the model says 186 s.
3. **Smoke spreads through openings.** Once a room's layer drops below the top of an open door,
   hot gas spills through. The flow follows the standard buoyant vent-flow equation, from the
   deeper layer to the shallower one. Smoke through an open door to outside is lost. Closed doors
   pass no smoke until they burn through. Walls pass nothing.
4. **Untenable** (ISO 13571-style limits): the smoke layer is below 2 m above the floor (for a
   stairwell, above its top landing), or the layer is above about 200 °C, which radiates about
   2.5 kW/m² onto people below.
5. **Flashover** happens when the fire reaches the Thomas threshold
   Q_fo = 7.8·A_T + 378·A_v·√H_v (kW). After that, the room is fully involved (about 830 °C).
6. **Fire spreads only through doors.** A flashed-over room ignites a neighbor through an open
   door after 3 minutes. A closed door holds for its fire rating (an unrated closed door for
   5 minutes), then burns through. A neighbor that ignites grows ultrafast, because it's already
   pre-heated.

### What each room and door gets

| Field | Meaning |
|---|---|
| `smoke_enters_s` | Layer is at least 5 cm deep |
| `smoke_untenable_s` | Tenability limit crossed (doors: first adjacent room) |
| `flashover_s` | Room flashes over (doors: first adjacent room) |
| `ignition_s` | Fire reaches the room (0 for the start room) |
| `burn_through_s`, `fire_passes_s` | Doors: closed door fails; fire crosses the door |
| `blocked_s` | Can't be used for escape: untenable, flashed over, or reached by fire (doors: either side, or fire passing) |

Times are seconds from ignition. `null` means it never happens within the horizon. Rooms also
report the flashover threshold, peak heat release, peak layer temperature and the layer height
at the end of the run. `events` lists ignition, smoke, untenability, flashover, burn-through,
burnout and exit-blocked events in time order.

The JSON also carries everything a viewer needs in one payload: each room's `footprint`, each
door's `position`, the venue's `scan` block, and `frames`.

### Frames (for animation)

`frames` is a snapshot every `frame_step_s` (default 10 s, plus the last step), from 0 to the
horizon:

```json
{ "t_s": 190,
  "rooms": { "f1-main-hall": { "layer_height_m": 1.9, "layer_temp_c": 56, "hrr_kw": 1693, "state": "burning" }, ... },
  "blocked": ["d-hall-east", "d-lobby-hall", "d-north-patio", "f1-main-hall"] }
```

- `layer_height_m`: height of the smoke layer's bottom above the room's floor (equal to the
  ceiling height when there's no smoke, 0 when the room is full or has flashed over).
- `layer_temp_c`: smoke layer temperature. `hrr_kw`: the room's fire heat release at that time.
- `state`, by precedence: `burnt_out` > `flashover` > `burning` > `untenable` > `smoke` > `clear`.
- `blocked`: sorted room and door ids from `blocked_at(t_s)`.

At the 10 s default the sample run is about 90 frames and about 200 KB of indented JSON.

### Storage

The venue JSON lives in the repo (`engine/data/`). Timelines aren't stored: the API computes one
on request (a 900 s run takes milliseconds) and returns this JSON. Caching in Supabase can come
later if it's ever needed.

## Assumptions and limits

- One well-mixed layer per room and no ceiling-jet travel time, so smoke covers a big room
  instantly once it forms. Each room has one fire at floor level.
- Door states are fixed for the whole run. People opening doors while they escape isn't modelled
  yet.
- Windows count as openings for the flashover and air limits (the glass is assumed to break), but
  smoke doesn't vent through them.
- There's no leakage through closed doors and no spread through floors or walls. The only way
  between floors is the stairwells.
- No sprinklers, no smoke control and no fire service action. That makes this a worst-case
  pre-plan.
- Values marked ASSUMPTION in `constants.py` (wall heat loss, spread delay, unrated door hold,
  some fuel classes) are judgment calls, not values from a standard.
- This is a planning estimate for a hackathon demo, not a code-compliance analysis.

## Next slice

Time-dependent routes: shortest paths from every room to every exit over the graph, removing
whatever `Timeline.blocked_at(t)` returns.


## Aria venue.json, routes and demo (slice 1)

Slice 1 runs the fire model above on the real venue graph, `venue.json` (schema v0.1, see
`VENUE.md`), and routes everyone out against the fire timeline. Three modules sit beside the
fire model and don't change it:

- `engine/aria_venue.py`: `venue.json` -> the fire model's `Venue` plus a routing graph, with id
  maps both ways.
- `engine/routes.py`: the timeline per venue space and opening id, then predictive and reactive
  routes.
- `engine/demo.py`: the CLI that runs it all and writes one JSON.

### Run it

```bash
cd packages/engine
uv run python -m engine.demo --start 140 --summary            # Collins Room fire (default start)
uv run python -m engine.demo --start 110 --summary            # Galleria lobby fire
uv run python -m engine.demo --start 219 --departures 0,60,120,180,240,300,360 --out out.json
uv run python -m engine.demo --start 140 --door D-110-corridor_core=closed --summary
uv run pytest -q
```

Flags: `--growth` (slow, medium, fast, ultrafast), `--horizon` (s), `--departures` (s, comma
separated), `--frame-step` (s, 0 for no frames), `--out` (JSON file; without `--out` or
`--summary` the JSON goes to stdout), `--door ID=open|closed` (repeatable), `--keep-origin-doors`,
`--allow-origin-entry`, `--venue`. `--start` takes any indoor space id; a well id maps to the
atrium.

From Python:

```python
from engine.demo import run_demo

result = run_demo(start="140", departures=(0, 60, 120, 180, 300))
```

Good demo moments: with a Collins Room fire (`--start 140`), departures around 6:00–6:30
(`--departures 360,375,390`) show predictive routes taking 210_n, 219 and 210A down the NE stair
while their reactive routes walk into 2F smoke. With a Galleria fire (`--start 110`) at 2:00, the
2F's reactive routes all head for the terrace and are cut off within seconds.

### What the adapter assumes

**Spaces to fire rooms.** Each indoor space is a room on its storey (1F = 1, 2F = 2, 3F = 3),
with its polygon area, height (3.0 m if null), polygon perimeter and bounding-box footprint.
Fuel class by use:

| Space | Fuel class |
|---|---|
| room with an event name or an assembly occupant load | assembly |
| other room (business load) | office |
| lobby, corridor, elevator, well | circulation |
| restroom | restroom |
| closet, mech | storage |

The Galleria counts as a lobby (circulation fuel) even though it holds sponsor tables during the
event.

**Skylight wells.** Every `open_to_below` space is merged with the 1F spaces under it (found
through its floor-void openings) into ONE fire room. Today that is `atrium:110`: 110,
galleria_far_end and the three wells. The room's volume is the 1F rooms plus each well from the
1F ceiling up to its top. It is modelled as a box with the true top (the skylights) and that
volume, so its floor area is volume ÷ height. The 2F openings that face a well become open doors
of the atrium at the 2F level, at full 2F height, so atrium smoke spills onto the 2F once there's
any layer, and a 2F fire's smoke spills into the wells. `av.merged` reports what was merged;
`av.room_of` and `av.spaces_of` map ids both ways.

**Floor offsets.** The fire model uses one elevation per storey. Inside the merged atrium, a
member on a different level (the Galleria far end, +0.62 m) is judged untenable from its own
floor, using the room's layer at 1 s steps. Elsewhere the offsets (150 at +0.62 m, the lawn at
−0.6 m) stay in `venue.json` but aren't used.

**Event-night door table** (`EVENT_NIGHT_RULES`, the one place door states are set):

| Category | State | Egress |
|---|---|---|
| Exterior door | closed for smoke, unrated | yes |
| Opening to outdoors with no leaf | open | yes |
| Door between two event spaces | propped open | yes |
| Door to a closet, restroom, elevator or back-of-house room | closed, unrated | yes |
| Cased opening, gap, step, ramp | open | yes |
| Skylight-well edge | open for smoke | no |
| Unprotected stair (`protected: false`, e.g. 100ST, the NE stair) | open | yes |
| Protected interior stair | closed, 60 min | yes |
| Elevator landing door | closed, 60 min | no |

Not in the fire model: openings inside the merged atrium, openings with no indoor side
(outdoor-to-outdoor, gates, `SAFE`), and the elevator hoistway. Each excluded opening carries its
reason in `av.fire_excluded`.

Other rules:
- **Door heights.** 2.1 m by default. Where a note gives a lintel or header height, that height.
  Steps, ramps, well edges, open stairs and openings whose notes say "no wall" or "at any
  height" take the lower of the two rooms' heights.
- **Stairs.** An unprotected stair between two ordinary rooms becomes a stair shaft room (the
  fire model's `kind: "stair"`) with an open door at each end. One touching the atrium (100ST)
  becomes an open 2F door of the atrium.
- **Room of origin.** Its closed interior doors are opened (`--keep-origin-doors` to skip): worst
  case for spread, and a fire behind a shut door would starve in this model.
- **Overrides.** `load_aria_venue(door_overrides={id: bool})` or `--door ID=open|closed`.
- **Outdoor spaces and `SAFE`** are the fire model's `outside`: smoke vents there and they never
  block.

**Routing graph.** Nodes are every space plus `SAFE`. Edges are the openings people can use
(not elevators, `effective_width > 0`), both ways; nobody walks back in from `SAFE`. Each edge
runs from a point inside the first space's polygon (its centroid, or the middle of the widest run
for L shapes), to the opening's position, to a point inside the next space. Walking speeds come
from the SFPE hydraulic model at the free speed, k·(1 − 0.266·0.54):

| Where | k (m/s) | Speed (m/s) |
|---|---|---|
| Level | 1.40 | 1.20 |
| Stair (7/11, along the slope) | 1.08 | 0.92 |
| Ramp | ASSUMPTION: as level | 1.20 |

A stair or step run uses `length`, or `rise` ÷ 0.178 × 0.279 when there is no length. Edges carry
`effective_width` for the crowd slice.

### Routes

The fire model's room and door `blocked_s` are mapped back to venue ids:
- A space takes its fire room's time.
- An opening takes the earliest of its fire doors, its stair shaft and both its spaces.
- Outdoor spaces and `SAFE` never block.

Then, for every indoor space except wells and elevator cars, and each departure time t0:
- **predictive**: earliest-arrival time-dependent Dijkstra (`heapq`). The label is the arrival
  time. An opening is usable only if it is reached before its `blocked_s`, and a space can't be
  entered at or after its `blocked_s`. Times are fixed and every constraint is a deadline (FIFO),
  so the search is exact.
- **reactive**: the shortest route over what is open at t0, walked in time. `cut_off` records
  where and when it fails.
- **Room of fire origin.** Routes never enter it from outside, because the zone model keeps it
  tenable until its layer drops and a pre-plan doesn't send people past the fire. People already
  inside may leave through it. `--allow-origin-entry` turns this off. A trapped space whose only
  open way out is through that room is marked with `*` and the reason "every open route passes
  through the room of fire origin".
- **Trapped.** A space already blocked at t0 is trapped (untenable at departure).

### Output (`schema_version: aria-engine-demo/1`)

| Key | What |
|---|---|
| `building`, `frame`, `scenario` | From `venue.json`; start space, fire room, growth, horizon, departures, frame step |
| `assumptions` | The notes, the event-night table, every opening's state (`door_states`: category, open, rating, why, `changed_by`), overrides, walking speeds |
| `adapter` | `merged_rooms`, `space_to_fire_room`, `opening_to_fire_doors`, `stair_shafts`, `fire_excluded_openings`, `route_excluded_openings`, counts |
| `fire.spaces[id]` | `fire_room`, `floor_offset_m`, `smoke_enters_s`, `smoke_untenable_s`, `ignition_s`, `flashover_s`, `blocked_s` |
| `fire.openings[id]` | `category`, `open`, `fire_doors`, `shaft`, `burn_through_s`, `fire_passes_s`, `blocked_s` |
| `fire.exits` | Each `is_exit` opening and `lost_s` (`null`: never lost) |
| `fire.events` | The fire model's events, with `venue_ids` added |
| `fire.frames` | Every `frame_step_s`: per space `layer_height_m` (above that space's own floor), `layer_temp_c`, `hrr_kw` (the fire room's; members of a merged room share it) and `state`, plus the venue ids `blocked` at that time |
| `fire.fire_rooms`, `fire.fire_doors` | The raw fire timeline, in fire-model ids |
| `routes.departures[]` | Per t0: `counts` and `occupants_at_risk` per mode, `trapped`, `trapped_by_origin_only`, `reactive_fails`, `different_exit`, and `spaces[id].predictive` / `.reactive` |
| `summary` | First smoke, first untenable, flashovers, exits lost and kept, per-departure headlines |

A route has:
- `status`: `ok`, `cut_off` or `trapped`.
- `reason`, if trapped.
- `exit`: the `is_exit` opening it uses; failing that, the first door outdoors.
- `path`: space, opening, space, …, `SAFE`.
- `points`: `[x, z, elevation]` in the venue frame, for drawing on the scan.
- `distance_m`.
- `depart_s`, `exit_s`, `eta_s` (reaches `SAFE`) and `travel_s`.
- `cut_off`: `{opening, into, reach_s, blocked_s}`. For a cut-off route, `eta_s` is what it would
  have been.

Times are seconds after ignition. A 900 s run takes about 0.5 s.

### Limits (slice 1)

- **Fire model.** Everything in "Assumptions and limits" above still applies. On top of that:
  - The atrium box is a screening approximation. Its layer height is exact in volume but not in
    shape (about ±20% on when smoke reaches a given height).
  - Windows aren't in `venue.json`, so no room has window vents.
  - The ANN-corridor doors may be magnetic hold-opens that close on alarm, and the Founders'
    opening may be an operable wall. Both are modelled open; use `--door` to test them closed.
- **Routes.**
  - One walker per space: no crowd density, door queues, merging flows or pre-movement time.
    `effective_width` is carried for that next slice.
  - Reactive routes don't re-plan after a cut-off.
  - Untenability is a hard switch: no FED dose and no slower walking in smoke.
- **Data.** `venue.json` is still being edited. Most widths and all 2F/3F heights are
  placeholders, several links are `INFERRED`, and the 130 back-of-house cluster's only drawn way
  out is through 140. The adapter reads whatever is there. Its tests check the invariants (every
  opening mapped or excluded with a reason, the merged atrium, `SAFE` reachable from every indoor
  space when nothing burns), not exact counts.
