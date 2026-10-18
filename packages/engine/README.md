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
`VENUE.md`), and routes everyone out against the fire timeline. The modules beside the fire
model:

- `engine/aria_venue.py`: `venue.json` -> the fire model's `Venue`, with id maps both ways and
  the event-night door table.
- `engine/geometry.py`, `engine/route_graph.py`: polygon helpers and the routing graph
  (door-to-door legs at SFPE walking speeds, door and stair capacities).
- `engine/routes.py`: the timeline per venue space and opening id, the two extra fire rules, and
  single-walker predictive and reactive routes; exits lost and exit reach.
- `engine/evacuate.py`, `engine/flow.py`: whole groups. Aria's capacity-aware plan, and the
  queue check that counts who doesn't get through a door in time.
- `engine/demo.py`, `engine/summary.py`, `engine/outputs.py`: the CLI, the readable summary and
  the JSON's drawing blocks (`geometry`, `viewer`).

One change to `engine/fire.py`: `simulate()` takes an optional `flashover_layer_c` (default
`None`, which keeps the old behaviour). The demo passes 600 °C. See "Fire rules" below.

### Run it

```bash
cd packages/engine
uv run python -m engine.demo --start 140 --summary            # Collins Room fire (default start)
uv run python -m engine.demo --start 110 --summary            # Galleria lobby fire
uv run python -m engine.demo --start 140 --summary --sensitivity   # each uncertain opening closed
uv run python -m engine.demo --start 219 --departures 0,60,120 --out out.json
uv run python -m engine.demo --start 140 --door O-110-140=closed --summary
uv run pytest -q
```

Flags: `--growth` (slow, medium, fast, ultrafast), `--horizon` (s), `--departures` (s, comma
separated), `--frame-step` (s, 0 for no frames), `--scan-step` (s between scanned departures,
default 15), `--out` (JSON file; without `--out` or `--summary` the JSON goes to stdout),
`--door ID=open|closed` (repeatable; smoke and fire only, people can still walk through),
`--sensitivity`, `--keep-origin-doors`, `--no-origin-limit`, `--avoid-origin`, `--venue`.
`--start` takes any indoor space id except skylight wells and elevator cars.

A run takes about 1 s (1.5–2 s with `--sensitivity`). The summary ends with the **best demo
moment**: the departure time, before the first flashover, where Aria's plan saves the most people
compared with the reactive routes, and the `--departures` value that shows it. It is recomputed
on every run, so it follows `venue.json` edits. `examples/` holds two full runs and what they
show.

From Python:

```python
from engine.demo import run_demo, summary_text

result = run_demo(start="140", departures=(0, 60, 120, 180, 300))
print(summary_text(result))
```

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

**Merged fire rooms.** Two links join spaces into one fire room (one smoke layer):
- A skylight well (`open_to_below`) and the 1F space its floor void opens onto. Today:
  `atrium:110` = 110, galleria_far_end and the three wells.
- A `step` opening between two indoor spaces: a step band with no wall or door. Today:
  `room:140+150`, the Collins Room (140 and 150 across a 12.7 m band).

A merged room is a box with the true top and the true volume, so its floor area is
volume ÷ height (the atrium: 2540 m³ up to the skylights at 8.0 m). The 2F openings that face a
well are open doors of the atrium at the 2F level, so atrium smoke spills onto the 2F and 2F
smoke into the wells. `av.merged` reports what was merged; `av.room_of` and `av.spaces_of` map
ids both ways.

**Floor offsets.** Spaces inside a merged room are judged from their own floor and ceiling,
from the room's layer at 1 s steps: the Galleria far end (+0.62 m), 140 (+0.16 m) and 150
(+0.70 m). Smoke counts as reaching a space only once it is below that space's own ceiling, so
a thin layer up in a skylight well is not smoke in the lobby. Door tops sit at the real header
height above the higher floor (150's 9.3 m opening to the Galleria tops out at 3.7 m). The fire
model still has one floor elevation per storey.

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

Not in the fire model: openings inside a merged room, openings with no indoor side
(outdoor-to-outdoor, gates, `SAFE`), and the elevator hoistway. Each excluded opening carries its
reason in `av.fire_excluded`.

Other rules:
- **Door heights.** An explicit `head_height` field wins if `venue.json` ever gets one; then a
  lintel or header height in the notes; then full height for well edges, open stairs, steps,
  ramps and leafless openings whose notes say "no wall" or "at any height"; else 2.1 m.
- **Stairs.** An unprotected stair between two ordinary rooms becomes a stair shaft room (the
  fire model's `kind: "stair"`) with an open door at each end. One touching the atrium (100ST)
  becomes an open 2F door of the atrium.
- **A sealed room of origin.** If the room where the fire starts has no open opening at all (170,
  190, 192), its doors are opened (a door left open, a window broken); otherwise the zone model
  gives it no air and the fire starves at 0 kW. A room with an open connection keeps its doors as
  the table sets them. `--keep-origin-doors` turns this off.
- **Overrides.** `load_aria_venue(door_overrides={id: bool})` or `--door ID=open|closed`. An id
  with no fire-model door (an outdoor gate, ST-W) is an error.
- **Outdoor spaces and `SAFE`** are the fire model's `outside`: smoke vents there and they never
  block.

### Fire rules on top of the zone model

- **Flashover at 600 °C.** A room also flashes over when its upper layer reaches 600 °C (Peacock
  et al. 1999, the usual zone-model criterion), not only at Thomas's Q_fo. Thomas counts every
  open interior opening as a vent, so a room opening into a big neighbour (the Collins Room into
  the atrium) never reached Q_fo while its layer sat at 1000 °C. After flashover the fire spreads
  as `engine.fire` sets out. Frames after the first flashover carry `beyond_screening: true`.
- **Room of origin.** The space where the fire starts is untenable once the fire radiates
  2.5 kW/m² (ISO 13571) at 3 m: a point source with radiative fraction 0.3 gives 942 kW, 2:22 into
  a fast fire. The zone model alone kept 140 tenable to 8:15 because its smoke drained into the
  atrium. `--no-origin-limit` turns this off.

### Routing graph

Nodes are every space plus `SAFE`. Edges are the openings people can use (not elevators,
`effective_width > 0`), both ways, except that nobody walks back in from `SAFE` or from outdoors
into the building. A route starts at a point inside its space's polygon (the centroid, or the
middle of the widest run for L shapes), then walks door to door: straight from the opening it
came in by to the one it leaves by, or via the space's point when the straight line would leave
the polygon. An opening with no position sits midway between its two spaces
(`adapter.estimated_positions`). Walking speeds are the SFPE free speed, k·(1 − 0.266·0.54):

| Where | k (m/s) | Speed (m/s) | Max flow (people/s per m of effective width) |
|---|---|---|---|
| Level, doors | 1.40 | 1.20 | 1.3 |
| Stair (7/11, along the slope) | 1.08 | 0.92 | 1.01 |
| Ramp | ASSUMPTION: as level | 1.20 | 1.3 |

A stair or step run uses `length`, or `rise` ÷ 0.178 × 0.279 when there is no length.

### Routes and evacuation

Blocked times per venue id:
- A space: its fire room's untenable, flashover or fire-arrival time, judged on its own floor in
  merged rooms, and the origin limit for the start space.
- An opening: the earliest of its spaces' times, its stair shaft and fire passing its doors.
- Outdoor spaces and `SAFE` never block.

Single walker, per space and departure time t0:
- **predictive**: earliest-arrival time-dependent Dijkstra over (space, opening came in by)
  states. An opening is usable only if it is crossed before its `blocked_s`, and a space can't be
  entered at or after its `blocked_s`. Times are fixed and every constraint is a deadline (FIFO),
  so the search is exact.
- **reactive**: the shortest route over what is open at t0, walked in time. `cut_off` records
  where and when it fails.
- A space already blocked at t0 is untenable at departure. A trapped space whose only way out,
  even with no fire, is through the room of origin gets the reason "the only way out passes
  through the room of fire origin" (`*` in the summary).

Whole groups (`engine.evacuate`), per departure time:
- Each space's `occupant_load` moves as a group.
- **Reactive**: each group takes its reactive route; groups queue first come, first served.
- **Aria's plan** (the `predictive` mode in the output): groups take turns booking door and
  stair time. Each takes the earliest route that gets the whole group through before anything on
  it closes, following the last person along the route, and keeps out of the room of origin when
  there's a way round (a greedy capacity-constrained route planner, CCRP: Lu, George & Shekhar
  2005). Four candidates are tried (most urgent space first, nearest group first, everyone on
  the single-walker route, the reactive routes where they work) and the one leaving the fewest
  people at risk is kept (`plan.chosen`, `plan.at_risk`).
- **Queue check** (`engine.flow`): each opening passes at most Fs × We people per second. People
  still queued when an opening closes are at risk; a group with some at risk is `partial`.
- Cut-offs and margins under 10 s are flagged `marginal`: inside the models' timing error.

Exits: `lost_s` is when the opening itself is blocked; `reachable_until_s` is the last scanned
departure time at which any occupied space can still get out through it (an exit nobody can
reach is lost too, e.g. ST-W, whose own stair never burns), and `kept_by` lists the spaces that
can still reach it at the horizon.

### Output (`schema_version: aria-engine-demo/2`)

| Key | What |
|---|---|
| `building`, `frame`, `scenario` | From `venue.json` (the whole `frame`, with its scan transforms); start space, fire room, growth, horizon, departures, frame and scan steps, rule switches |
| `assumptions` | The notes, the event-night table, every opening's state (`door_states`: category, open, rating, why, `changed_by`), overrides, walking speeds and flows |
| `adapter` | `merged_rooms`, `space_to_fire_room`, `opening_to_fire_doors`, `stair_shafts`, `fire_excluded_openings`, `route_excluded_openings`, `estimated_positions`, counts |
| `geometry` | `storeys`, and per space and opening what drawing needs (polygon, storey, floor elevation, height, position, widths, `is_exit`), copied from `venue.json` |
| `fire.criteria`, `fire.validity`, `fire.origin` | The flashover temperature and origin limit; the first flashover (after it the numbers are indicative); the origin limit's time and the zone model's own time |
| `fire.spaces[id]` | `fire_room`, `floor_offset_m`, `smoke_enters_s`, `smoke_untenable_s`, `untenable_by` (`smoke_layer` or `heat`), `ignition_s`, `flashover_s`, `blocked_s` (and `origin_limit_s` on the start space) |
| `fire.openings[id]` | `category`, `open`, `fire_doors`, `shaft`, `burn_through_s`, `fire_passes_s`, `blocked_s` |
| `fire.exits` | Each `is_exit` opening: `lost_s`, `reachable_until_s`, `kept_by`, `reachable_counts` per scanned departure |
| `fire.events` | Venue-level events: ignition, flashover, burn-through, burnout from the fire model; smoke, untenable and exit lost per venue id |
| `fire.fire_rooms`, `fire.fire_doors` | The raw fire timeline, in fire-model ids |
| `viewer` | A `FireTimeline` (`apps/web/lib/scan-fire.ts`) keyed by venue ids: `rooms` (polygon bounding boxes, storey, ceiling), `doors` (every opening's position), `exits`, `events` and `frames` (per space: `layer_height_m` above its own floor, `layer_temp_c`, `hrr_kw`, `state`; plus `blocked` and `beyond_screening`). `scan.floor_y` is −3.91: the venue frame is room 2's scan frame, and the four-room GLB is in it |
| `routes.departures[]` | Per t0: `plan`, `counts` and `occupants_at_risk` per mode, `untenable_at_departure`, `trapped`, `trapped_by_origin_only`, `partial`, `reactive_cut_off`, `contrasts` (where the plan beats the reactive routes), `flow` per opening, and `spaces[id].predictive` / `.reactive` |
| `routes.scan[]` | Every `scan_step_s`: people at risk per mode, people saved (`saved_clear` leaves out marginal cases), the chosen plan, the top contrasts |
| `summary` | First smoke and untenable beyond the origin, flashovers, exits lost and their reach, ways down per storey, uncertain open connections, per-departure headlines, the scan, `best_moment` |
| `sensitivity` | With `--sensitivity`: people at risk per departure and the first exit lost, as modelled and with each uncertain open connection closed |

A route (`spaces[id].predictive` or `.reactive`) has:
- `status`: `ok`, `partial`, `cut_off` or `trapped`; `at_risk` (people); `reason` if trapped.
- `exit`: the `is_exit` opening it uses; failing that, the first door outdoors.
- `path`: space, opening, space, …, `SAFE`; `crossings`: `[opening, t]` for the first walker.
- `points`: `[x, z, elevation]` in the venue frame, for drawing on the scan.
- `distance_m`, `depart_s`, `exit_s`, `eta_s` (reaches `SAFE`), `travel_s`, `margin_s`,
  `marginal`. A cut-off route has `eta_s: null`, `planned_eta_s` and
  `cut_off: {opening, into, reach_s, blocked_s, late_by_s}`.
- `flow`: `people`, `cleared`, `at_risk`, `last_out_s` (the last person reaches `SAFE`),
  `bottleneck`, `limited_by`.

Times are seconds after ignition.

### Limits (slice 1)

- **Fire model.** Everything in "Assumptions and limits" above still applies. On top of that:
  - The merged-room box is a screening approximation: right in volume and top, not in shape
    (about ±20% on when smoke reaches a given height).
  - Outside merged rooms there is one floor elevation per storey.
  - Windows aren't in `venue.json`, so no room has window vents.
  - The 2F rooms around the wells go "untenable" when a cool layer drops below 2 m (labelled
    `smoke_layer`, "smoke-logged"): conservative, since there is no visibility or FED model yet.
  - After the first flashover, layer temperatures, HRR (up to the fuel limit, ~130 MW for the
    Collins Room) and spread are indicative only.
  - The ANN-corridor doors may be magnetic hold-opens, the Founders' opening an operable wall and
    the Collins–Galleria openings partly glazed. All are modelled open; the summary lists them
    and `--sensitivity` closes each in turn.
- **People.**
  - No pre-movement time: t0 is when people start moving.
  - A group takes one route; splitting a room across exits, merging-flow priority and slowing in
    dense rooms or smoke are not modelled. The plan is greedy, not optimal.
  - Reactive routes don't re-plan after a cut-off.
- **Data.** `venue.json` is still being edited. Most widths and all 2F/3F heights are
  placeholders, several links are `INFERRED`, and the 130 back-of-house cluster's only drawn way
  out is through 140. The adapter reads whatever is there. The tests check invariants (every
  opening mapped or excluded with a reason, merged rooms, door rules, the fire rules, `SAFE`
  reachable when nothing burns, queues on a toy graph), not exact counts.
