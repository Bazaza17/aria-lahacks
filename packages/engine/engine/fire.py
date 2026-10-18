"""Zone-model fire timeline on the building graph.

Each room has one smoke layer under the ceiling (mass + temperature). The burning room
feeds it through a plume; once a layer drops below a door's top, smoke spills through
open (or burnt-through) doors. Where a burning room's smoke spills up into a taller space
(the atrium), it rises as a spill plume and entrains that space's air (NFPA 92 5.5.2).
Flashover follows Thomas; after flashover, fire crosses open doors after a delay and
closed doors when they burn through. Walls never pass fire.

Run: python -m engine.fire --venue engine/data/james_west_sample.json --start f1-main-hall
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field

from engine import physics
from engine.constants import (
    ALPHA_KW_S2,
    AMBIENT_K,
    CONVECTIVE_FRACTION,
    CP_KJ_KG_K,
    DECAY_START_FRACTION,
    FUEL_CLASSES,
    MAX_LAYER_K,
    POST_FLASHOVER_K,
    RHO_T,
    SECONDARY_GROWTH,
    SMOKE_PRESENT_DEPTH_M,
    SPILL_ENTRAINMENT,
    SPILL_MODES,
    SPREAD_OPEN_DOOR_DELAY_S,
    TENABLE_LAYER_HEIGHT_M,
    TIME_STEP_S,
    UNRATED_CLOSED_DOOR_HOLD_S,
    WALL_LOSS_FRACTION,
)
from engine.venue import OUTSIDE, SAMPLE_VENUE, Door, Room, Venue, load_venue


@dataclass
class _Fire:
    ignition_s: float
    growth: str
    energy_kj: float = 0.0
    decay_from_s: float | None = None
    decay_q_kw: float = 0.0
    decay_len_s: float = 0.0
    out: bool = False


@dataclass
class _RoomState:
    mass_kg: float = 0.0
    temp_k: float = AMBIENT_K
    fire: _Fire | None = None
    flashover_s: float | None = None
    smoke_enters_s: float | None = None
    untenable_s: float | None = None
    peak_kw: float = 0.0
    max_temp_k: float = AMBIENT_K
    flashover_threshold_kw: float | None = None
    hrr_kw: float = 0.0  # this step's heat release


@dataclass
class Timeline:
    venue: str
    verified: bool
    start_room: str
    growth: str
    horizon_s: float
    rooms: dict[str, dict]
    doors: dict[str, dict]
    exits: list[dict]
    events: list[dict] = field(default_factory=list)
    frames: list[dict] = field(default_factory=list)  # snapshots every frame_step_s
    scan: dict = field(default_factory=dict)

    def blocked_at(self, t_s: float) -> set[str]:
        """Ids of rooms and doors that can't be used for escape at time t."""
        blocked = set()
        for group in (self.rooms, self.doors):
            for item_id, row in group.items():
                if row["blocked_s"] is not None and row["blocked_s"] <= t_s:
                    blocked.add(item_id)
        return blocked

    def to_dict(self) -> dict:
        return {
            "venue": self.venue,
            "verified": self.verified,
            "start_room": self.start_room,
            "growth": self.growth,
            "horizon_s": self.horizon_s,
            "rooms": self.rooms,
            "doors": self.doors,
            "exits": self.exits,
            "events": self.events,
            "scan": self.scan,
            "frames": self.frames,
        }


_Spill = tuple[Door, str, str, float, float]  # door, source, destination, kg this step, soffit z


def _min(*values: float | None) -> float | None:
    present = [v for v in values if v is not None]
    return min(present) if present else None


def _round(v: float | None) -> int | None:
    return None if v is None else int(round(v))


class _Sim:
    def __init__(
        self,
        venue: Venue,
        horizon_s: float,
        frame_step_s: float = 0.0,
        flashover_layer_k: float | None = None,
        spill_mode: str = SPILL_ENTRAINMENT,
    ):
        if spill_mode not in SPILL_MODES:
            raise ValueError(f"unknown spill entrainment {spill_mode!r}; use one of {SPILL_MODES}")
        self.spill_mode = spill_mode
        self.v = venue
        self.horizon = horizon_s
        self.frame_step = frame_step_s
        # Optional second flashover criterion: upper layer at or above this temperature.
        self.flashover_layer_k = flashover_layer_k
        self.frames: list[dict] = []
        self.state = {rid: _RoomState() for rid in venue.rooms}
        self.door_failed_s: dict[str, float] = {}
        self.door_fail_at: dict[str, float] = {}  # scheduled burn-through
        self.fire_passes_s: dict[str, float] = {}
        self.ignite_at: dict[str, tuple[float, str]] = {}  # room -> (time, via door)
        self.events: list[dict] = []

    # --- geometry ---
    def floor_z(self, room: Room) -> float:
        return self.v.elevation(room.floor)

    def occupied_z(self, room: Room) -> float:
        # A stair is untenable once smoke reaches head height at its highest landing.
        if room.kind == "stair" and room.floors_served:
            return max(self.v.elevation(f) for f in room.floors_served)
        return self.floor_z(room)

    def layer_depth(self, rid: str) -> float:
        room, st = self.v.rooms[rid], self.state[rid]
        volume = st.mass_kg * st.temp_k / RHO_T
        return min(volume / room.area_m2, room.ceiling_height_m)

    def interface_z(self, rid: str) -> float:
        room = self.v.rooms[rid]
        return self.floor_z(room) + room.ceiling_height_m - self.layer_depth(rid)

    def door_passable(self, door: Door, t: float) -> bool:
        return door.open or door.id in self.door_failed_s

    def vents(self, room: Room, t: float) -> tuple[float, float]:
        openings = [
            (d.width_m * d.height_m, d.height_m)
            for d in self.v.doors_of(room.id)
            if self.door_passable(d, t)
        ]
        if room.window_area_m2 > 0:
            openings.append((room.window_area_m2, room.window_height_m))
        return physics.vent_factor(openings)

    def flashover_kw(self, room: Room, t: float) -> tuple[float, float]:
        a_v, h_v = self.vents(room, t)
        a_t = physics.internal_surface_m2(
            room.area_m2, room.perimeter, room.ceiling_height_m, a_v
        )
        q_fo = physics.thomas_flashover_kw(a_t, a_v, h_v)
        hrrpua, _ = FUEL_CLASSES[room.fuel_class]
        q_cap = min(hrrpua * room.area_m2, physics.vent_limited_kw(a_v, h_v))
        return q_fo, q_cap

    # --- events ---
    def event(self, t: float, kind: str, item: str, detail: str) -> None:
        self.events.append({"t_s": _round(t), "type": kind, "id": item, "detail": detail})

    def name(self, item: str) -> str:
        if item in self.v.rooms:
            return self.v.rooms[item].name
        return self.v.doors[item].name or item

    def ignite(self, rid: str, t: float, growth: str, via: str | None) -> None:
        st = self.state[rid]
        st.fire = _Fire(ignition_s=t, growth=growth)
        st.flashover_threshold_kw = self.flashover_kw(self.v.rooms[rid], t)[0]
        how = f"fire spreads in via {self.name(via)}" if via else f"fire starts ({growth} growth)"
        self.event(t, "ignition", rid, f"{self.name(rid)}: {how}")

    def on_flashover(self, rid: str, t: float) -> None:
        st = self.state[rid]
        st.flashover_s = t
        self.event(t, "flashover", rid, f"{self.name(rid)} flashes over")
        for door in self.v.doors_of(rid):
            other = door.other(rid)
            if self.door_passable(door, t):
                fail = t
            else:
                hold = door.fire_rating_min * 60.0 or UNRATED_CLOSED_DOOR_HOLD_S
                fail = t + hold
                self.door_fail_at[door.id] = min(self.door_fail_at.get(door.id, fail), fail)
            if other == OUTSIDE or self.state[other].fire is not None:
                continue
            passes = max(t + SPREAD_OPEN_DOOR_DELAY_S, fail)
            if other not in self.ignite_at or passes < self.ignite_at[other][0]:
                self.ignite_at[other] = (passes, door.id)

    # --- one step ---
    def hrr(self, rid: str, t: float) -> float:
        room, st = self.v.rooms[rid], self.state[rid]
        fire = st.fire
        if fire is None or fire.out:
            return 0.0
        _, q_cap = self.flashover_kw(room, t)
        if fire.decay_from_s is not None:
            frac = 1.0 - (t - fire.decay_from_s) / fire.decay_len_s
            if frac <= 0:
                fire.out = True
                self.event(t, "burnout", rid, f"{self.name(rid)} burns out")
                return 0.0
            return fire.decay_q_kw * frac
        if st.flashover_s is not None:
            q = q_cap
        else:
            q = min(physics.t_squared_hrr_kw(fire.growth, t - fire.ignition_s), q_cap)
        _, mj_m2 = FUEL_CLASSES[room.fuel_class]
        total_kj = mj_m2 * room.area_m2 * 1000.0
        if fire.energy_kj >= DECAY_START_FRACTION * total_kj and q > 0:
            fire.decay_from_s, fire.decay_q_kw = t, q
            fire.decay_len_s = 2.0 * (1.0 - DECAY_START_FRACTION) * total_kj / q
        return q

    def step(self, t: float, dt: float) -> None:
        for door_id, fail in list(self.door_fail_at.items()):
            if fail <= t and door_id not in self.door_failed_s:
                self.door_failed_s[door_id] = fail
                detail = f"{self.name(door_id)} burns through"
                self.event(fail, "door_burn_through", door_id, detail)
        for rid, (when, via) in list(self.ignite_at.items()):
            if when <= t and self.state[rid].fire is None:
                self.ignite(rid, when, SECONDARY_GROWTH, via)
                self.fire_passes_s[via] = when
                del self.ignite_at[rid]

        # Fires feed their own room's layer.
        for rid, room in self.v.rooms.items():
            st = self.state[rid]
            q = self.hrr(rid, t)
            st.hrr_kw = q
            if st.fire is None:
                continue
            st.peak_kw = max(st.peak_kw, q)
            st.fire.energy_kj += q * dt
            q_fo, _ = self.flashover_kw(room, t)
            hot = self.flashover_layer_k is not None and st.temp_k >= self.flashover_layer_k
            if st.flashover_s is None and q > 0 and (q >= q_fo or hot):
                self.on_flashover(rid, t)
            if st.flashover_s is not None and not st.fire.out:
                # Fully developed: the whole room is hot gas.
                st.temp_k = POST_FLASHOVER_K
                st.mass_kg = room.area_m2 * room.ceiling_height_m * RHO_T / POST_FLASHOVER_K
                continue
            q_conv = CONVECTIVE_FRACTION * q
            z = self.interface_z(rid) - self.floor_z(room)
            m_p = physics.plume_mass_kg_s(q_conv, z) * dt
            if m_p > 0:
                t_in = AMBIENT_K + q_conv * (1 - WALL_LOSS_FRACTION) * dt / (m_p * CP_KJ_KG_K)
                self.mix(rid, m_p, t_in)

        # Smoke spills through passable doors, from the deeper layer to the shallower one.
        delta: dict[str, list[float]] = {rid: [0.0, 0.0] for rid in self.v.rooms}  # mass, m*T
        spills: list[_Spill] = []
        for door in self.v.doors.values():
            if not self.door_passable(door, t):
                continue
            bottom = self.v.elevation(door.floor)
            top = bottom + door.height_m

            def depth_in_door(side: str, top=top, bottom=bottom) -> float:
                if side == OUTSIDE or self.state[side].mass_kg <= 0:
                    return 0.0
                return max(0.0, top - max(self.interface_z(side), bottom))

            da, db = depth_in_door(door.a), depth_in_door(door.b)
            if da == db:
                continue
            src, dst = (door.a, door.b) if da > db else (door.b, door.a)
            st = self.state[src]
            m = physics.door_spill_kg_s(door.width_m, abs(da - db), st.temp_k) * dt
            m = min(m, 0.25 * st.mass_kg)
            delta[src][0] -= m
            delta[src][1] -= m * st.temp_k
            if dst != OUTSIDE and m > 0:
                spills.append((door, src, dst, m, top))
        rising = self.rising_spill_kg(spills)
        for door, src, dst, m, top in spills:
            # The doorway jet loses heat to the new room's boundaries; above the soffit it
            # also entrains that room's clear air (spill plume), which cools it further.
            excess = (self.state[src].temp_k - AMBIENT_K) * (1 - WALL_LOSS_FRACTION)
            m_in = m + self.spill_entrained_kg(door, src, dst, m, top, rising.get(src, 0.0), dt)
            delta[dst][0] += m_in
            delta[dst][1] += m_in * (AMBIENT_K + excess * m / m_in)
        for rid, (dm, dmt) in delta.items():
            st = self.state[rid]
            if dm > 0:
                self.mix(rid, dm, dmt / dm)
            elif dm < 0:
                st.mass_kg = max(st.mass_kg + dm, 0.0)

        for rid, room in self.v.rooms.items():
            st = self.state[rid]
            st.max_temp_k = max(st.max_temp_k, st.temp_k)
            depth = self.layer_depth(rid)
            if st.smoke_enters_s is None and depth >= SMOKE_PRESENT_DEPTH_M:
                st.smoke_enters_s = t
                self.event(t, "smoke_enters", rid, f"smoke reaches {room.name}")
            head = self.interface_z(rid) - self.occupied_z(room)
            if st.untenable_s is None and physics.is_untenable(head, st.temp_k, depth):
                st.untenable_s = t
                why = (
                    f"smoke below {TENABLE_LAYER_HEIGHT_M:g} m"
                    if head < TENABLE_LAYER_HEIGHT_M
                    else f"hot layer {st.temp_k - 273.15:.0f} °C"
                )
                self.event(t, "untenable", rid, f"{room.name} untenable ({why})")

    # --- spill plumes (constants.SPILL_ENTRAINMENT) ---
    def spill_source_kw(self, src: str) -> float:
        """Heat release driving a spill plume: only a burning room that hasn't flashed over."""
        st = self.state[src]
        if st.fire is None or st.fire.out or st.flashover_s is not None:
            return 0.0
        return st.hrr_kw

    def spill_rise_m(self, dst: str, top: float) -> float:
        """How far a spill plume climbs in `dst` above the soffit before it meets the layer."""
        return self.interface_z(dst) - top

    def rising_spill_kg(self, spills: list[_Spill]) -> dict[str, float]:
        """Per burning source room, this step's door flow into spaces where the smoke rises."""
        total: dict[str, float] = {}
        for _, src, dst, m, top in spills:
            if self.spill_source_kw(src) > 0 and self.spill_rise_m(dst, top) > 0:
                total[src] = total.get(src, 0.0) + m
        return total

    def spill_entrained_kg(
        self, door: Door, src: str, dst: str, m: float, top: float, rising: float, dt: float
    ) -> float:
        """Clear air a spill plume pulls in between the soffit and the destination's layer.

        The fire plume's flow at soffit height is shared between the doors it leaves by, in
        proportion to their flow; each door's spill plume gets that share of the fire.
        """
        q = self.spill_source_kw(src)
        rise = self.spill_rise_m(dst, top)
        if self.spill_mode == "off" or q <= 0 or rise <= 0 or m <= 0:
            return 0.0
        edge = top - self.floor_z(self.v.rooms[src])  # soffit above the fire, H
        q_conv = CONVECTIVE_FRACTION * q
        plume_at_edge = physics.plume_mass_kg_s(q_conv, edge) * dt
        share = m / max(rising, plume_at_edge, m)
        if self.spill_mode == "balcony":
            m_b = physics.balcony_spill_plume_kg_s(share * q, door.width_m, rise, edge) * dt
            return max(m_b - m, 0.0)
        return physics.axisymmetric_spill_entrainment_kg_s(share * q_conv, edge, rise) * dt

    def mix(self, rid: str, mass: float, temp_k: float) -> None:
        room, st = self.v.rooms[rid], self.state[rid]
        total = st.mass_kg + mass
        st.temp_k = min((st.mass_kg * st.temp_k + mass * temp_k) / total, MAX_LAYER_K)
        st.mass_kg = total
        # A full room can't hold more; the excess leaks out through gaps.
        full = room.area_m2 * room.ceiling_height_m * RHO_T / st.temp_k
        st.mass_kg = min(st.mass_kg, full)

    def room_state(self, st: _RoomState) -> str:
        if st.fire is not None and st.fire.out:
            return "burnt_out"
        if st.flashover_s is not None:
            return "flashover"
        if st.fire is not None:
            return "burning"
        if st.untenable_s is not None:
            return "untenable"
        if st.smoke_enters_s is not None:
            return "smoke"
        return "clear"

    def snapshot(self, t: float) -> None:
        rooms = {}
        for rid, room in self.v.rooms.items():
            st = self.state[rid]
            rooms[rid] = {
                "layer_height_m": round(self.interface_z(rid) - self.floor_z(room), 2),
                "layer_temp_c": round(st.temp_k - 273.15),
                "hrr_kw": round(st.hrr_kw),
                "state": self.room_state(st),
            }
        self.frames.append({"t_s": _round(t), "rooms": rooms})

    def run(self) -> None:
        steps = int(self.horizon / TIME_STEP_S)
        every = max(1, round(self.frame_step / TIME_STEP_S)) if self.frame_step > 0 else 0
        for i in range(steps + 1):
            self.step(i * TIME_STEP_S, TIME_STEP_S)
            if every and (i % every == 0 or i == steps):
                self.snapshot(i * TIME_STEP_S)


def simulate(
    venue: Venue,
    start_room: str,
    growth: str = "fast",
    horizon_s: float = 900.0,
    frame_step_s: float = 10.0,
    flashover_layer_c: float | None = None,
    spill_entrainment: str = SPILL_ENTRAINMENT,
) -> Timeline:
    """flashover_layer_c (default None: Thomas only): also flash a burning room over once its
    upper layer reaches this temperature (600 °C is the usual zone-model criterion).
    spill_entrainment: "balcony" (default, NFPA 92 eq. 5.5.2.1), "axisymmetric" (the lower
    estimate) or "off"; see constants.SPILL_ENTRAINMENT."""
    if start_room not in venue.rooms:
        raise ValueError(f"unknown start room {start_room!r}; rooms: {sorted(venue.rooms)}")
    if growth not in ALPHA_KW_S2:
        raise ValueError(f"unknown growth {growth!r}; use one of {sorted(ALPHA_KW_S2)}")
    layer_k = None if flashover_layer_c is None else flashover_layer_c + 273.15
    sim = _Sim(venue, horizon_s, frame_step_s, layer_k, spill_entrainment)
    sim.ignite(start_room, 0.0, growth, None)
    sim.run()

    rooms = {}
    for rid, room in venue.rooms.items():
        st = sim.state[rid]
        ignition = st.fire.ignition_s if st.fire else None
        reached_by_fire = ignition if rid != start_room else None
        rooms[rid] = {
            "name": room.name,
            "floor": room.floor,
            "footprint": _footprint(room),
            "smoke_enters_s": _round(st.smoke_enters_s),
            "smoke_untenable_s": _round(st.untenable_s),
            "ignition_s": _round(ignition),
            "flashover_s": _round(st.flashover_s),
            "blocked_s": _round(_min(st.untenable_s, st.flashover_s, reached_by_fire)),
            "flashover_threshold_kw": _round(st.flashover_threshold_kw),
            "peak_hrr_kw": _round(st.peak_kw) if st.fire else None,
            "max_layer_temp_c": round(st.max_temp_k - 273.15),
            "layer_height_at_horizon_m": round(sim.interface_z(rid) - sim.floor_z(room), 2),
        }
    doors = {}
    for did, door in venue.doors.items():
        sides = [s for s in (door.a, door.b) if s != OUTSIDE]
        passes = sim.fire_passes_s.get(did)
        doors[did] = {
            "name": door.name,
            "connects": [door.a, door.b],
            "position": {"x": door.position[0], "z": door.position[1]} if door.position else None,
            "open": door.open,
            "fire_rating_min": door.fire_rating_min,
            "smoke_untenable_s": _min(*(rooms[s]["smoke_untenable_s"] for s in sides)),
            "flashover_s": _min(*(rooms[s]["flashover_s"] for s in sides)),
            "burn_through_s": _round(sim.door_failed_s.get(did)) if not door.open else None,
            "fire_passes_s": _round(passes),
            "blocked_s": _min(*(rooms[s]["blocked_s"] for s in sides), _round(passes)),
        }
    exits = [
        {"id": e.id, "label": e.label, "door": e.door, "blocked_s": doors[e.door]["blocked_s"]}
        for e in venue.exits
    ]
    events = sorted(sim.events, key=lambda e: e["t_s"])
    for ex in exits:
        if ex["blocked_s"] is not None:
            events.append(
                {"t_s": ex["blocked_s"], "type": "exit_blocked", "id": ex["id"],
                 "detail": f"{ex['label']} no longer usable"}
            )
    events.sort(key=lambda e: e["t_s"])
    timeline = Timeline(
        venue=venue.name,
        verified=venue.verified,
        start_room=start_room,
        growth=growth,
        horizon_s=horizon_s,
        rooms=rooms,
        doors=doors,
        exits=exits,
        events=events,
        frames=sim.frames,
        scan=venue.scan,
    )
    for frame in timeline.frames:
        frame["blocked"] = sorted(timeline.blocked_at(frame["t_s"]))
    return timeline


def _footprint(room: Room) -> dict | None:
    if room.footprint is None:
        return None
    x0, x1, z0, z1 = room.footprint
    return {"x": [x0, x1], "z": [z0, z1]}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m engine.fire", description=__doc__.split("\n")[0])
    p.add_argument("--venue", default=str(SAMPLE_VENUE), help="venue JSON (default: sample)")
    p.add_argument("--start", default="f1-main-hall", help="room id where the fire starts")
    p.add_argument("--growth", default="fast", choices=sorted(ALPHA_KW_S2))
    p.add_argument("--horizon", type=float, default=900.0, help="seconds to simulate")
    p.add_argument(
        "--frame-step", type=float, default=10.0, help="seconds between frames (0: none)"
    )
    p.add_argument("--events", action="store_true", help="print only the event list as text")
    p.add_argument(
        "--spill", default=SPILL_ENTRAINMENT, choices=SPILL_MODES,
        help="spill-plume entrainment above door soffits (default: %(default)s)",
    )
    args = p.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    timeline = simulate(
        load_venue(args.venue), args.start, args.growth, args.horizon, args.frame_step,
        spill_entrainment=args.spill,
    )
    if args.events:
        for e in timeline.events:
            print(f"{e['t_s'] // 60:3d}:{e['t_s'] % 60:02d}  {e['type']:<18} {e['detail']}")
    else:
        json.dump(timeline.to_dict(), sys.stdout, indent=2, ensure_ascii=False)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
