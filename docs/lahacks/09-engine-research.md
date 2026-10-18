# 09: Engine research: what exists and what we build

*This is the search-first pass for `packages/engine`, done Sat Oct 17. Every top candidate was installed and smoke-tested on Lincoln's laptop (Windows 11, Python 3.12.15, uv 0.13.1) in throwaway venvs, which were then deleted. The repo was not touched. Registry facts come from the PyPI JSON API and from `gh` (authenticated). Nothing was run on Linux or in Docker. Anything marked "unverified" was not checked.*

## 1. Summary

1. **Max-depth stack:**
   - Door widths from trimesh + shapely slices of the scan.
   - Plan topology from Claude vision (in `apps/api`), aligned to the scan with Umeyama + small_gicp.
   - A networkx graph, fed to NIST CFAST 7.7.7 through pycfast.
   - SciPy routes plus a hand-written time-dependent Dijkstra, with an OR-Tools optimal-flow bound.
   - A hydraulic Monte Carlo RSET, plus JuPedSim agent playback and a PedPy ASET-RSET map.
2. **Safe stack:** a hand-drawn `venue.json` in the same schema, our own screening zone model (ofire correlations plus pyFDS-Evac's `fed.py` copied into the repo), SciPy/networkx routes, and a hydraulic flow model. It is all wheels with no binaries, about 185 MB on disk.
3. **Hours:** the safe stack alone is roughly 11–14 h of the ~16 h left. That is the sum of the estimates below: schema ~1 h plus tracing, zone model 5.5–7.5 h, routes ~2 h at minimum, hydraulic model 2–3 h. Every deep piece is an upgrade to add only when ahead. They all plug into the same schema.
4. **Biggest risks:**
   - CFAST has no official Linux binary. It needs a gfortran build in Docker, which is untested.
   - JuPedSim pulls about 413 MB of Qt/VTK into the Linux image unless a uv override goes in `apps/api/pyproject.toml`.
5. **No library does the core trick:** routes and crowd reacting to a fire timeline that closes doors over time. That glue is ours to write, and it is where the technical depth is.

### At the venue today
- **Tape-measure 3–5 door clear widths** and note which doors. They are the ground truth for the widths measured from the scan.
- **Scan the wall above each door head.** Door gaps only show where the wall above the head was captured.
- **Go slowly past glass, and expect furniture to show up.** Glass scans as holes. Furniture shows up in the 1.0 m slice.
- **Photograph the evacuation map with all four corners visible.** The rectification step needs four points.
- **Export the Polycam GLB; it is the main input.** Also get a USDZ or RoomPlan export if the app offers one, and ask whether a DXF or CAD plan exists.
- **Capture the stair between floors in the same session if you can** (my suggestion). Drift between floors is a listed risk.

## 2. Components

### 2.1 World model: scan + plan → building graph

| Candidate | What it gives us | License | Install (Win, py3.12) | Effort |
|---|---|---|---|---|
| **trimesh 5.1.1** (+ DracoPy, scipy, rtree) | Loads the GLB (Y-up, metres); Draco-compressed GLBs load with DracoPy. Floor levels come from a histogram of up-facing faces. Slices the mesh at fixed heights. Door clear width = slice above the head minus slice below. On a toy mesh a 0.90 m door measured exactly. | MIT (DracoPy Apache-2.0, scipy BSD-3) | OK in 4 s. ~185 MB on disk with scipy + numpy | 5–6 h on a real scan |
| **shapely 2.2 + networkx 3.7** | Operations on wall linework; the graph; shortest path; exit capacity from max-flow (verified) | BSD-3 | OK (6 MB + 14 MB) | 3–5 h |
| **Claude vision (anthropic, in apps/api) + opencv-python-headless 5.0** | Plan photo → rooms/doors/exits JSON. Rectification verified at 0.99/255 mean pixel error | MIT / Apache-2.0 | OK in 20 s; OpenCV is 113 MB on disk | 3.5–4.5 h (+2 h optional wall snapping) |
| **small_gicp 1.0.1** | ICP/GICP alignment of plan walls to the scan, numpy in and out. 13 iterations, 3.5 cm RMS on a noisy synthetic plan | MIT | OK, 0.7 MB | 1.5–2 h including the Umeyama seed |
| **usd-core 26.8** | Reads RoomPlan-style USDZ; door size from bounding boxes. The mechanics are verified; real prim names are not | TOST-1.0 | OK; 50 MB on disk | 3–4 h |
| Open3D 0.20 | RANSAC planes, ICP | MIT* | Not installed; the Linux CUDA wheel is 400 MB | 1.5–3 h |
| ezdxf 1.4.5 | DXF plan → shapely at real scale | MIT* | Not installed | 2–3 h, only if a DXF exists |
| IfcOpenShell | IFC export | LGPL-3.0+* | Not installed | 3–5 h, stretch goal |

\* Registry data from the first research pass, not re-checked.

**Verdict: Compose.** trimesh, shapely, networkx and small_gicp cover every geometric step; the schema and the glue are ours. Keep the LLM call in `apps/api` and have the engine take plan JSON only. The reason: anthropic 1.x pulls in httpx2/httpcore2 and would split from the API's locked 0.102.0.

**Build by hand:**
- **`Building` schema.** A pydantic model (storeys, spaces, openings) in the GLB frame: Y-up, metres, plan coordinates = scan x, z. Take the vocabulary from BOT (Rasmussen et al. 2021) and IndoorGML 1.1. About 1 h.
- **Floor detection.** An area-weighted histogram of face heights where normal.y > 0.9 (after Okorn et al. 2010; Turner & Zakhor 2014).
- **Alignment.**
  - Umeyama similarity from 2–3 clicked point pairs (TPAMI 1991; about 15 lines of numpy SVD).
  - Then ICP (Besl & McKay 1992) or GICP (Segal et al. 2009).
  - ICP is rigid, so apply the Umeyama scale first. Report the RMS.
- **Effective width and occupant load.** Effective width = clear width minus boundary layers (Pauls/Fruin, SFPE egress chapter). Occupant load from NFPA 101 Table 7.3.1.2 (check the edition).

**Verified slicing pattern for an open LiDAR surface:**
```python
sec = mesh.section(plane_origin=[0, y, 0], plane_normal=[0, 1, 0])
lines = [LineString(e.discrete(sec.vertices)[:, [0, 2]]) for e in sec.entities]
walls_y = shapely.unary_union(lines)
gaps = walls_at_2_2m.difference(walls_at_1_0m.buffer(eps))
widths = [g.length + 2 * eps for g in gaps.geoms]
```

**API traps:**
- Don't build walls with `Path2D.polygons_full`. It gave 0 polygons on an open slice and filled the whole room on a solid model.
- Don't use `Path3D.discrete`. It silently drops open polylines.
- Don't use `to_2D()`. It returns a local frame, not scan x, z.
- Use `Scene.to_geometry()`, not the deprecated `Scene.dump(concatenate=True)`.
- networkx max-flow and min-cut reject a MultiGraph. Project it to a DiGraph with a summed `capacity` in both directions (about 3 lines).
- OpenCV 5 `HoughLinesP` returns shape (N, 4), not (N, 1, 4). Binarize before running Hough. `createLineSegmentDetector` works without tuning.

**Unverified:**
- Whether Polycam GLBs use Draco. DracoPy handles it either way.
- RoomPlan prim names.
- Any Linux install.

### 2.2 Fire and smoke timeline

| Candidate | What it gives us | License | Install (Win, py3.12) | Effort |
|---|---|---|---|---|
| **NIST CFAST 7.7.7 via pycfast 0.2.2** | A validated multi-room two-zone fire model, built from Python. Room = Compartment (`hall=True` for corridors, `shaft=True` for stairs). Door = WallVent. Floor opening = CeilingFloorVent. Fire = an HRR table. One target per room at 1.6 m gives layer height, temperature, visibility and FED as DataFrames. Up to 101 rooms and 200 fire-table rows. | CFAST: NIST notice (keep the notice, mark changes, credit NIST). pycfast: MIT | pycfast OK in 1.5 s; it wrote a valid 3-room, 2-floor input. **The CFAST binary was not installed**: the official release is a Windows .exe only, and Linux needs a gfortran build | 5–8 h |
| **ofire 0.1.16** | Hand-calculation correlations with their source equation numbers (NUREG-1805 FDT, PD 7974-1, CIBSE Guide E, SFPE ch.50). Five were checked against hand formulas: all exact, 25 µs in total. **Not in the wheel:** SFPE ch.59 egress and the forward Alpert ceiling jet | MIT (on GitHub; PyPI has no license field) | OK, 187 KB, no dependencies | 0.5–1 h |
| **pyFDS-Evac 0.5.0, `fed.py` only** | Purser FED (as in FDS+Evac); ISO 13571 heat FED (clothed and unclothed); radiant helpers; time to a FED threshold; smoke walking-speed laws (Lund, Fridolf) | MIT | **Do not pip install it** (1.2 GB, PySide6 alone is 655 MB). `fed.py` from tag v0.5.0 copies in unchanged and runs on bare 3.12 | 0.5–1 h |
| **fsetools, `pd_7974_1_2019.py` only** | Forward Alpert ceiling-jet temperature and velocity (eq 26/27), heat-detector activation (eq 55), t² growth: the pieces needed for detection time | Apache-2.0 | **Install fails** on 3.12; copy the numpy-only functions | 0.5–1 h |
| FDS 6.11.1 + fdsreader | Gold-standard LES CFD | NIST / LGPL-3.0 | Not installed | 8–20 h plus hours of compute per run. Not this weekend |
| aamks | Reference design: CFAST plus agents | GPL-3.0 | n/a | About 1 h of reading; copy nothing |
| aset-rset-maps | The ASET-RSET map method (Schroeder 2020) | None declared | n/a | Concept only |

**Verdict: Compose, with one output schema and two backends.**
- **Backend A (Adopt):** CFAST via pycfast, 5–8 h. Only worth it if the binary runs in hour 1.
- **Backend B (Build):** our own screening zone model, 4–6 h, plus about 1.5 h for the detection and egress pieces ofire lacks.
- **Both:** about 10–13 h.

**Lean: build B first.**
- **Why:** it always runs, takes milliseconds and needs no binary.
- **CFAST test:** spend 30 minutes getting CFAST running on Windows. pycfast's CI extracts `cfast.exe` from the installer with `7z x`, with no admin rights. Then benchmark a 20–40 room run.
- **If CFAST works** (my suggestion, untested): run it for the venue's demo ignition rooms on the laptop and ship the results as JSON. That skips the Linux build entirely.

**Backend B equations.** These come from domain knowledge unless marked verified; re-check each against its source before quoting.

| Piece | Method |
|---|---|
| Fire growth | Q = αt². α (kW/s²): slow 0.00293, medium 0.01172, fast 0.0469, ultrafast 0.1876. Capped by fuel and by ventilation (~1500·A_o·√H_o kW). Convective part Q_c ≈ 0.7Q. Flashover: Thomas Q_fo = 7.8·A_T + 378·A_o·√H_o (**verified**, ofire PD 7974-1 eq 28) |
| Plume | Heskestad (NFPA 92 §5.5). z_l = 0.166·Q_c^(2/5). Above z_l: m_p = 0.071·Q_c^(1/3)·z^(5/3) + 0.0018·Q_c. Below z_l: m_p = 0.032·Q_c^(3/5)·z |
| Layer filling | Two-zone model per room (Karlsson & Quintiere): dz/dt = −m_in/(ρ_u·A), with ρ_u = 353/T_u. Hot-layer ΔT from MQH (**verified**, ofire FDT eq 2.1: 186.0 K for 1 MW in a 20×15×4.5 m room). Cross-check with Yamana-Tanaka (**verified**, eq 2.10: 2.55 m at 120 s) |
| Door transfer | Two-layer vent flow: m = (2/3)·C_d·W·ρ_0·√(2g(T_0/T_u)(1−T_0/T_u))·(H_d−H_N)^(3/2), with C_d ≈ 0.7. It carries mass, heat, soot and CO into the neighbour's upper layer. Stairs are vertical edges. Closed doors leak about 1e-4 × wall area. Integrate with explicit Euler at 0.5–1 s |
| Species, visibility | Soot = y_s·Q/ΔH_c, with y_s from 0.015 (wood) to 0.1 (PU foam). CO yield 0.004, up to 0.2 when under-ventilated. K = 8700 m²/kg × m_s. Visibility S = C/K, with C = 3 for reflective signs and 8 for lit signs (**verified**, ofire FDT eq 18-1) |
| Tenability (at head height) | Smoke layer below 1.8–2.0 m while hot or dense. Convective heat FED. Radiant flux q > 2.5 kW/m². Asphyxiant FED 0.3 (protects susceptible people) or 1.0 (median). Visibility < 10 m in large spaces, < 5 m in small rooms. A door is blocked when either side is untenable. An exit is lost at the minimum ASET of the rooms feeding it |
| Detection, RSET | t_det from the Alpert ceiling jet plus the RTI equation (fsetools eq 26/27/55). Pre-movement time is lognormal (PD 7974-6). RSET = t_det + t_alarm + t_pre + t_travel (+ t_queue) |

**Get these right on the slides:**
- **Convective heat.** The first pass swapped the labels. Correct:
  - clothed: 4.1e8·T^−3.61 min
  - unclothed: 5e7·T^−3.4 min
  - At 100 °C that is 24.7 vs 7.9 min.
- **Asphyxiant FED: pick one law and name it.** The two options:
  - ISO 13571:2012, the form CFAST uses: (CO/35000 + HCN^2.36/1.2e6) × exp(CO2%/5).
  - Purser as used by FDS+Evac (pyFDS-Evac `fed.py`).
- **CFAST's radiant heat FED looks mis-parenthesized.** It runs about 64× too fast. That is my reading of the Fortran, not confirmed with NIST. Use "q > 2.5 kW/m² = untenable" as a threshold instead.
- **Name the backends honestly.** Call B a "screening zone model" and A "NIST CFAST 7.7.7".

### 2.3 Routing

| Candidate | What it gives us | License | Install | Effort |
|---|---|---|---|---|
| **SciPy 1.18.1 `sparse.csgraph`** | `dijkstra(indices=exits, min_only=True, return_predecessors=True)` gives every room's next hop and nearest exit in one call. `yen` gives K alternate routes. `maximum_flow` needs integer capacities. 0.078 ms per step on a 192-node graph | BSD-3 | OK in 1.4 s. scipy + numpy are ~149 MB (Windows) / ~167 MB (Linux) | 2–3 h (+3–4 h for time-expanded flow) |
| **networkx 3.7** | The graph of record. A weight function that returns `None` closes an edge (verified: rerouted at t = 90 s, 35 m → 41 m). `network_simplex` gives min-cost flow. `node_link_data` exports JSON (the key is now `edges`, not `links`). 0.18 ms per multi-source Dijkstra on 192 nodes | BSD-3 | OK in 0.25 s, 2.1 MB | 1–2 h (+1 h for alternates) |
| **OR-Tools 9.15** | Min-cost flow on a time-expanded network: 23k nodes, 118k arcs, 400 people and 6 exits solved OPTIMAL in 19.3 ms | Apache-2.0 | OK in 14.5 s; adds ~120 MB (brings pandas). No protobuf clash with the API | 3–5 h |
| rustworkx 0.18.1 | Rust graph library | Apache-2.0 | Not installed (2.3 MB wheels) | Not needed; SciPy is already under 0.1 ms |
| scikit-fmm | Eikonal travel-time field on a grid | BSD | Not installed; **no Linux wheel** | 3–4 h + ~1 h of Docker work; only for a grid world |
| python-igraph | C graph library | **GPL** | Not installed | Skip |
| JuPedSim RoutingEngine | Navmesh routing | LGPL-3.0+ | See 2.4 | Only with the agent sim |

**Verdict: Extend.** Adopt SciPy for the hot loop and networkx as the graph of record and for JSON. Hand-write the time-dependent parts, because no library routes against a fire timeline.

**Build by hand.** About 8–10 h in total; a demoable minimum takes about 2 h.
1. **Edge state arrays.** Per edge: length, width, floor, is_stair, t_smoke, t_untenable. Cost c_e(t) = length / v(t) × (1 + α·hazard_e(t)), and ∞ once t ≥ t_untenable.
2. **Reactive field at 1 Hz.** SciPy Dijkstra from the exits. Build the CSR matrix once, then each step write `G.data[:] = cost[slot]`, with np.inf for closed edges.
3. **Predictive time-dependent Dijkstra (the differentiator).**
   - The label is arrival time. An edge entered at time t is usable only if t + τ_e(t) < t_untenable[e].
   - It is exact under FIFO (Cooke & Halsey 1966; Dreyfus 1969; Kaufman & Smith 1993; Orda & Rom 1990 for waiting). These citations are from memory.
   - About 40 lines of heapq, and about 22 ms for all sources (first-pass measurement).
4. **Safest instead of shortest.** Use a cumulative FED-exposure cost, or a minimax-hazard variant. Get K = 3 alternates via `yen`.
5. **Crew "safest way in".**
   - The same time-dependent Dijkstra, run from responder entry points.
   - It uses an SCBA cost model: edges close on temperature or flashover, not toxicity.
   - Start at dispatch plus response time. NFPA 1710's 240 s travel time is from memory.
6. **Optional capacity layer.** A time-expanded flow network (Ford & Fulkerson 1958; Hoppe & Tardos 2000; Tjandra 2001). Use CCRP (Lu, George & Shekhar 2005) for explicit per-group routes.

**Traps (verified in SciPy 1.18.1):**
- `csr_matrix((w, (rows, cols)))` **adds up** duplicate entries. Two doors between the same rooms, or an edge listed both ways and then symmetrized, doubles the cost. Keep only the minimum cost per pair first.
- An explicit 0.0 is a **free edge**, not a missing one. Close edges with np.inf.
- `maximum_flow` needs integer capacities, so scale people and seconds to integers.

### 2.4 Crowd egress

| Candidate | What it gives us | License | Install | Effort |
|---|---|---|---|---|
| **JuPedSim 1.4.2** (CFSM, agent-based) | Per-agent trajectories for Three.js. Verified: agents reroute mid-run when an exit closes (`switch_agent_journey`); `desired_speed` can be changed at runtime (for slowing in smoke); `RoutingEngine` assigns nearest exits. 800 agents and 78 s simulated took 2.5 s at dt = 0.05 (8.9 s at dt = 0.01) | LGPL-3.0+ | OK **with a uv override**: 5 packages, 50 MB. Without it, ~413 MB of Qt/VTK on Linux. No aarch64 wheel | 4.5–6.5 h for one floor; +2 h for two floors; +1 h calibration |
| **jupedsim-network 0.5.0** (hydraulic, SFPE) | Rooms, stairs and doors; Monte Carlo pre-movement; `node_occupancy[t, room]`, `link_flow[t, door]` and evacuation-time quantiles. The docs scenario reproduced exactly (323.0 s; 120 of 120 safe). About 65 ms per Monte Carlo run | LGPL-3.0+ | OK, 96 KB pure Python, needs only numpy | 2–3 h + 1–2 h of workarounds |
| **PedPy 1.5.1** | Per-door N-t curves and an RSET map (Schroeder et al. 2020) from JuPedSim output. Both verified on a real JuPedSim sqlite | MIT | OK, but adds ~206 MB (pandas, matplotlib, h5py), so offline use only | 1–2 h |
| **networkx time-expanded max-flow** (EVACNET) | A lower bound on evacuation time with perfect coordination. Closed doors are dropped after their closure time | BSD-3 | OK | 2–4 h. 0.51 s per solve at 3,632 nodes; 2.8 s for a full binary search |
| Mesa 3.5.1 | Agent-based modelling framework with no pedestrian dynamics | Apache-2.0 | Not installed | 5–8 h; only if JuPedSim fails (it didn't) |
| Vadere v4.0 | Java pedestrian simulator | LGPL-3.0 | Not tested; adds a ~200 MB JRE | 8–12 h; no |
| aamks | Smoke-slowdown pattern: v = max(0.1·v0, v0·(1 + β/α·K)), with K = 2.303 × optical density | GPL-3.0 | n/a | Re-implement from Ronchi et al. 2013; don't copy code |

**Verdict: Compose.** A library moves the people; our code couples them to the fire. Which library is the open decision in 3b.

**JuPedSim rules from the smoke tests:**
- **Put each exit polygon beyond the doorway**, at the end of a short corridor stub. An exit box inside a room drained 7.44 people/s, against 1.64 people/s through a 1.2 m door: 4.5× too fast.
- **Keep spawn areas clear of exits.** `removed_agents()` misses agents that spawned inside an exit, so cross-check with `agent_count()`.
- **Measured door flow is 30–40% high:** 1.82 people/s/m of SFPE effective width, against SFPE's 1.3. Calibrate it, or show both numbers.
- **Queues are slow to simulate.**
  - 400 agents through one door took 56 s at dt = 0.01, against 10 s at dt = 0.05.
  - The dt = 0.05 run gave a 9% longer evacuation time.
  - Use dt = 0.05, precompute, and never run it inside a request.
- **Pin the versions.**
  - `jupedsim==1.4.2`: the next release makes h5py and hdf5plugin hard dependencies.
  - `jupedsim-network==0.5.0`: it had 5 releases in 6 days.
- **jupedsim-network routes are static.** A whole room goes to one exit, and a lost exit means rebuilding the network without it.

## 3. The two open decisions

These are not decided here; my leans are labelled.

### 3a. How the floor plan becomes the graph

| Option | How | Effort | Good | Bad |
|---|---|---|---|---|
| **A. Hand-drawn `venue.json`** | Trace rooms, doors and exits into the schema by hand | ~1 h for the schema, plus tracing | Unblocks fire, routes and crowd straight away; no risk | No "from the scan" story on its own |
| **B. Vision LLM on the plan** | Rectify the photo with OpenCV; Claude extracts rooms, doors and exits as JSON; scale pixels to metres; fix by hand | 3.5–4.5 h (+2 h wall snapping) | Good live-demo moment; fits the agents/API owner | LLM coordinates are approximate; needs alignment to the scan |
| **C. Straight from the scan** | Slice the mesh; walls from linework; door gaps and widths from differencing slices | 5–6 h on real noise, plus a JSON file for manual corrections | Door widths measured from the LiDAR against tape ground truth; the most original option | Furniture, glass holes, drift between floors; gives no room names or exits on its own |
| **D. Hybrid** | Topology from the plan (A or B), geometry from the scan (C), aligned with Umeyama + small_gicp, RMS reported | ~8–13 h | Plan-vs-scan cross-check ("the map shows an exit the scan shows blocked") | Most hours |
| E. RoomPlan USDZ | Read the prims and bounding boxes with usd-core | 3–4 h | A second, independent measurement of the doors | Separate capture with its own frame; weak on large multi-floor spaces; prim names unverified |
| F. DXF | ezdxf layers → shapely | 2–3 h | Real scale for free | Only if a DXF exists |

**Lean: D, staged.**
- **First:** a hand-drawn `venue.json`, so the engine has a graph within an hour or two.
- **Then:** door widths measured from the scan (C) replace the hand values wherever the scan is clean.
- **Upgrades if time allows:** the alignment and the vision-LLM path. The LLM call belongs in `apps/api` anyway.
- **Why:** everything downstream needs only the graph, so this never blocks the engine. The measured door width is the most original number the world model can produce.

### 3b. Crowd sim style

| | A. Flow only | B. Agents only | C. Both, tiered |
|---|---|---|---|
| Tool | jupedsim-network, or our own time-dependent hydraulic model (~150 lines of numpy + networkx) | JuPedSim CFSM | Hydraulic + JuPedSim, plus an optional networkx/OR-Tools optimal bound and a PedPy RSET map |
| Effort | 2–3 h (+1–2 h of workarounds) | 5–8 h including two floors | A + B + 3–6 h of extras |
| What the viewer shows | Room heat and door-flow bars; no moving people | Moving dots that reroute when a door closes | Both |
| Report answers (clearance per exit, bottlenecks, people inside at minute N) | Yes, plus p50/p95 RSET from Monte Carlo | Yes, from the trajectories | Yes, three ways |
| Main risk | jupedsim-network routes are static | Calibration (30–40% fast), exit-stub geometry, the Docker override, slow queues | Hours |

**Lean: C, staged, with our own hydraulic model as tier 1.**
- **Why our own model:** jupedsim-network can't reroute when the fire closes a door mid-evacuation, and that is the whole point. Our ~150-line model re-runs Dijkstra on the open doors at each step.
- **jupedsim-network as a check:** its numbers reproduce exactly, so with no fire it checks our model.
- **Then JuPedSim:** add it for playback once fire and routes work.
- **Then the optimal bound,** only if there's time.
- **The insight is the gap between tiers.** For example: "with perfect coordination the building needs X s; with nearest-exit behaviour it takes Y s".

**Hand-built hydraulic model** (SFPE; Gwynne et al., SFPE Handbook 6th ed., ch. 67, 2026):
- **Speed.** Density D = N/A per room. Walking speed S = k(1 − 0.266·D).
  - k = 1.40 m/s on level ground.
  - k = 51.8·√(T/R) m/min on stairs.
  - Free speed below D = 0.54 people/m².
- **Flow.** Specific flow Fs = S·D, capped at 1.3 people/s/m for doors. Effective width We = clear width − 2 × 0.15 m. Door capacity = 1.3·We. Verified: a 0.9 m door gives 0.78 people/s, matching jupedsim-network.
- **Transitions.** Fs_out = Fs_in·We_in/We_out. Each door has an open(t) flag from the fire timeline.
- **Outputs.** Clearance per exit, occupancy[t, room], and queue-seconds per door; the door with the largest queue is the bottleneck.

## 4. How the pieces chain

Plain data passes between pure functions. Units are metres and seconds, in the GLB frame (Y-up; plan coordinates = x, z).

```
build_world(scan.glb, plan.json | venue.json)                                -> Building
fire_timeline(Building, ignition_room, fire_curve, backend="zone"|"cfast")    -> FireTimeline
route(Building, FireTimeline, mode="reactive"|"predictive"|"crew")           -> Routes
egress(Building, FireTimeline, Routes, occupants, mode="flow"|"agents")       -> Egress
package(Building, FireTimeline, Routes, Egress)                              -> report JSON + playback file
```

| Step | Returns (rough) |
|---|---|
| `Building` | storeys `[{id, elevation}]`; spaces `[{id, storey, polygon, area, height, occupant_load}]`; openings `[{id, a, b, kind: door/stair/opening, clear_width, effective_width, is_exit}]`; `align_rms` if aligned; the networkx graph and its JSON (`edges` key) |
| `FireTimeline` | `t[]`, HRR, flashover time. Per space: layer height, upper-layer temperature, visibility, gas and heat FED series, `untenable_at`. Per opening: `blocked_at`. Per exit: `lost_at`. Also the backend name and the FED law used |
| `Routes` | Per time step: next hop and target exit per space, plus distance and time. A predictive path per space; K = 3 alternates; crew entry paths; edge-cost and closure arrays |
| `Egress` | `occupancy[t, space]`, `door_flow[t, opening]`, clearance per exit, bottleneck doors (queue-seconds), RSET p50/p95, people inside at minute N. For agents: per-agent `exit, t_out, fed_max` and trajectories |
| `package` | The ASET − RSET margin per space (and a grid via PedPy if agents ran), and the report fields for `apps/api`. The playback file is `{dt: 0.5, floors: [{id, z}], agents: [{id, floor, exit, t_out, fed_max}], frames: Int16[frame][agent][x_cm, y_cm]}`, with a sentinel value once an agent is out. Store it in Supabase Storage (not the SSE stream) and draw it with one InstancedMesh |

The report schema in `apps/api/app/agent/prompts.py` is a shared contract. Tell the web and API owners before changing it.

## 5. What reads as technically impressive

| Moment | Carried by | Criterion |
|---|---|---|
| "Door widths measured from the LiDAR" next to tape-measured truth, with the error quantified | trimesh + shapely slice differencing | Technical Depth, Execution |
| Plan over scan, "aligned to N cm RMS" | Umeyama + small_gicp | Execution |
| "Timeline from NIST CFAST 7.7.7 on the scanned geometry", or every size-up number citing its equation (NUREG-1805 eq 2.10, PD 7974-1 eq 28) | pycfast, ofire, our zone model | Technical Depth |
| The reactive route walks into a corridor that closes before arrival; the predictive route avoids it | Hand-written time-dependent Dijkstra | Originality |
| Occupants build up a toxic and heat dose and slow down in smoke | Copied `fed.py` + Lund/Fridolf speed laws | Technical Depth |
| Three tiers: optimal bound, SFPE hydraulic p95, agent sim. The gap between them is the finding | networkx/OR-Tools + hydraulic model + JuPedSim | Product Thinking |
| A per-room ASET − RSET margin map over the scan | Fire timeline + PedPy (Schroeder et al. 2020) | Product Thinking, Originality |
| Crew "safest way in" | Time-dependent Dijkstra with an SCBA cost model | Product Thinking |

Being honest earns points with technical judges:
- Name the FED law you used.
- Call backend B a screening model.
- Label the flow bound as a bound.
- Don't present CFAST's heat FED as an ISO dose.

## 6. Risks and fallbacks

| Risk | What we know | Fallback |
|---|---|---|
| CFAST on Linux | No official Linux binary. It builds with gfortran (`gnu_linux` target) in the same base image, but that is untested (no Docker on this laptop). A CFAST 8 Beta Linux tarball exists (144 MB, beta) | Zone model (B), or run CFAST on Windows ahead of time and ship JSON |
| CFAST hangs, speed | Runs that don't converge hang forever. The 0.10 s per run was measured for one room only | Always pass `run(timeout=...)`; benchmark 20–40 rooms in hour 1 |
| pycfast validation | The default device `temperature_depth` of 0.5 m is thicker than the gypsum wall, which raises ValueError | Pass `temperature_depth=0.008` |
| pyFDS-Evac install | 1.2 GB | Copy `fed.py` from tag v0.5.0. If copying from main, replace the `HUMAN_SMOKE_HEIGHT_M` import with 1.6 |
| fsetools | Fails to install on 3.12 | Copy the numpy-only functions |
| ofire on Linux | manylinux_2_34 wheel only. Without `--only-binary`, uv silently falls back to the sdist, which needs Rust | python:3.12-slim (trixie, glibc 2.41) is fine; pin the version and use wheels |
| JuPedSim image size | ~413 MB of Qt/VTK on Linux | `[tool.uv] override-dependencies` in **`apps/api/pyproject.toml`** (the lock root). Verified that they then stay out of `uv sync` |
| JuPedSim architecture | No aarch64 wheel | Build with `--platform linux/amd64` |
| Young packages | jupedsim-network is a week old; pyFDS-Evac moves fast | Pin exact versions and tags |
| anthropic 1.x | Pulls httpx2/httpcore2; the API locks 0.102.0 | Keep the LLM call in `apps/api` |
| Dockerfile | `apps/api/Dockerfile` copies only `apps/api`, so a path dependency on `packages/engine` breaks | Move the build context to the repo root |
| Image size | trimesh stack ~185 MB, OpenCV 113 MB, usd-core 50 MB, OR-Tools +120 MB, PedPy +206 MB | Runtime: trimesh, shapely, networkx, scipy, small_gicp. Put OpenCV and usd-core in an `[ingest]` extra. PedPy offline only. OR-Tools only if picked |
| scikit-fmm | No Linux wheel | Skip it, or use SciPy Dijkstra on an 8-connected grid |
| Real data | Every test used synthetic geometry. Polycam Draco use and RoomPlan prim names are unknown | Hand-drawn `venue.json` plus a manual JSON override for door widths |
| Linux in general | Nothing was built in Docker. Linux support comes from wheel tags and a wheels-only `uv pip compile` | Do one Railway build early |

**Licenses inside a deployed service:**
- **MIT / BSD / Apache** (trimesh, shapely, networkx, scipy, small_gicp, pycfast, ofire, pyFDS-Evac, fsetools, OR-Tools, PedPy): fine. Keep the license notice on any copied file.
- **NIST notice** (CFAST, FDS): fine. Keep the notice, mark changes, credit NIST.
- **LGPL-3.0+** (JuPedSim, jupedsim-network, fdsreader): fine as unmodified dependencies. Don't copy their code into the repo.
- **GPL** (aamks, igraph): don't copy code or ship aamks's CFAST binaries. Skip igraph.
- **TOST-1.0** (usd-core): keep it in the offline ingest extra.
- **No license** (aset-rset-maps): cite the paper only.

**Left over from the test installs:**
- The global uv cache still holds the pyside6/vtk wheels. `uv cache clean pyside6 pyside6-addons pyside6-essentials vtk` frees the space.
- The routing test scripts are in the session scratchpad: `C:/Users/lincb/AppData/Local/Temp/claude/C--Users-lincb-Documents-GitHub-aria-lahacks/e2f99aa2-401a-4ad0-b372-88d27608a4ea/scratchpad/probe_routing/`.
