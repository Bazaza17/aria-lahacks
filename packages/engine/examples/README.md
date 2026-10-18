# Engine slice 1: example runs

Two full runs of `engine.demo` on `venue.json` as of Sat Oct 17, 22:53 (the Collins Room scan
update). Both use a fast t² fire, a 900 s horizon, departures at 0, 60, 120, 180 and 300 s,
frames every 30 s and the `--sensitivity` reruns:

```bash
cd packages/engine
uv run python -m engine.demo --start 140 --frame-step 30 --sensitivity --out examples/demo_140.json
uv run python -m engine.demo --start 110 --frame-step 30 --sensitivity --out examples/demo_110.json
```

Each file is one JSON (`schema_version: aria-engine-demo/2`, about 0.8 MB). The fields are listed
in `../README.md` under "Output". For the 3D viewer, `viewer` is already a `FireTimeline`
(`apps/web/lib/scan-fire.ts`) keyed by venue space and opening ids, in the venue frame
(`scan.floor_y` −3.91 for the four-room GLB); the routes to draw are
`routes.departures[i].spaces[id].predictive.points` and `.reactive.points` (`[x, z, elevation]`).
`geometry` has every polygon. Regenerate both files after any `venue.json` edit; the numbers
below will move.

**`demo_140.json`: fire in the Collins Room (140).** The room of origin is lost at 2:22, when the
fire reaches 942 kW (2.5 kW/m² at 3 m); the zone model alone would have kept it tenable until
8:15, because 140 and 150 are one room open to the atrium and the smoke drains away. Smoke is in
150 at 0:19 and through the skylight wells onto the 2F at 1:35; the 2F landing is smoke-logged
(layer below 2 m) at 4:20, and the Collins Room flashes over at 10:19 (upper layer at 600 °C). The
headline is people, not a single walker. If everyone leaves at once, Aria's plan gets all 1,346
people indoors out of the building, while the routes people would pick themselves leave 91 still
queued when a door closes. 88 of them are in 219, behind 0.78 people/s at the one 0.6 m terrace
door that all of the 2F's west side heads for; the plan sends 219 down the NE stair through 200A
instead. Leaving at 1:00 it is 0 against 155, and at 1:45 (the summary's best demo moment) 110
against 312. By 3:00 the two are close (471 against 476): 140 itself is untenable by then, and the
2F's ways down are too narrow for better routes to fix. Two more findings from this run: the 130
back-of-house cluster (9 people) has no drawn way out except through 140, so it is trapped by
3:00; and ST-W never burns, but after 4:45 only 230 and 330 can still reach it. The sensitivity reruns show that closing the uncertain Collins–Galleria opening
`O-galleria_far_end-150` changes the plan's numbers the most (217 instead of 137 at risk at 2:00):
check that opening on site.

**`demo_110.json`: fire in lobby 110 (the Galleria atrium).** This is the worst case for the 2F.
The atrium fills, and the 2F rooms around the wells are smoke-logged from 1:49 (landing_200st) to
about 2:40. Lobby 110 is lost at 2:22, and with it both main-entrance pairs, D-110-OUT-1 and -2;
the far end's doors go at 5:51. The 2F's ways down are ST-100 (it lands in the atrium), the NE
stair (it lands in 100G, whose only door opens into 110) and the terrace door to ST-W. After 2:30,
only 230 and 330 can still reach ST-W. Leaving at once, Aria's plan still leaves 293 people at risk
against 388 for the reactive routes. The biggest single save is the Founders' Room (120, 150
people): its reactive route heads for the main entrance and is caught in the queue when 110 is
lost, while the plan sends it out through its own patio doors (D-120-OUT-1/2). The best demo
moment is a departure at 1:45: 571 against 843. Closing the uncertain openings changes little
before 5:00. The atrium flashes over at 10:37, past the point where the zone model's numbers are
more than indicative.
