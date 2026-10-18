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
