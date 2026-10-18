"""Spill-plume entrainment (task 4 in docs/lahacks/13-engine-plan.md).

Smoke spilling from a burning room up into the taller merged atrium entrains the atrium's
air (NFPA 92 2021, 5.5.2), so the atrium fills and the 2F goes untenable much sooner.
"""

import pytest

from engine import physics
from engine.aria_venue import load_aria_venue
from engine.constants import SPILL_ENTRAINMENT, SPILL_MODES
from engine.fire import simulate
from engine.venue import Room, Venue


def test_balcony_spill_plume_matches_nfpa_92_eq_5_5_2_1():
    # m = 0.36 (Q W²)^(1/3) (z_b + 0.25 H): 1000 kW, 3 m opening, 4 m rise, 3 m soffit.
    expected = 0.36 * (1000 * 3.0**2) ** (1 / 3) * (4.0 + 0.25 * 3.0)
    assert physics.balcony_spill_plume_kg_s(1000.0, 3.0, 4.0, 3.0) == pytest.approx(expected)
    assert physics.balcony_spill_plume_kg_s(1000.0, 3.0, 0.0, 3.0) == 0.0
    assert physics.balcony_spill_plume_kg_s(0.0, 3.0, 4.0, 3.0) == 0.0


def test_axisymmetric_spill_entrainment_is_the_plume_gain_above_the_soffit():
    gain = physics.plume_mass_kg_s(700.0, 7.0) - physics.plume_mass_kg_s(700.0, 3.0)
    assert physics.axisymmetric_spill_entrainment_kg_s(700.0, 3.0, 4.0) == pytest.approx(gain)
    assert physics.axisymmetric_spill_entrainment_kg_s(700.0, 3.0, 0.0) == 0.0


def test_default_mode_is_the_nfpa_92_spill_plume():
    assert SPILL_ENTRAINMENT == "balcony"
    assert set(SPILL_MODES) == {"balcony", "axisymmetric", "off"}


def test_unknown_mode_is_rejected():
    av = load_aria_venue(origin_space="140")
    with pytest.raises(ValueError):
        simulate(av.fire, av.fire_room("140"), "fast", 60, 0, spill_entrainment="nope")


def test_a_single_box_with_no_doors_is_unchanged():
    # The NFPA 92 filling hand checks use one room and no doors; spill modes can't touch them.
    room = Room(
        id="R",
        name="R",
        floor=1,
        area_m2=316.5,
        ceiling_height_m=8.0,
        fuel_class="assembly",
        window_area_m2=6.0,
        window_height_m=1.5,
    )
    venue = Venue(
        name="box",
        verified=False,
        floor_elevations_m={1: 0.0},
        rooms={"R": room},
        doors={},
        exits=[],
    )
    runs = [simulate(venue, "R", "fast", 400, 1.0, spill_entrainment=m) for m in SPILL_MODES]
    assert len({tl.rooms["R"]["smoke_untenable_s"] for tl in runs}) == 1
    assert runs[0].rooms["R"]["smoke_untenable_s"] == pytest.approx(251, abs=5)  # hand: 250 s


def _first_2f_untenable(mode: str) -> float:
    av = load_aria_venue(origin_space="140")
    tl = simulate(
        av.fire, av.fire_room("140"), "fast", 600, 0, flashover_layer_c=600, spill_entrainment=mode
    )
    times = [
        tl.rooms[av.room_of[sid]]["smoke_untenable_s"]
        for sid, space in av.spaces.items()
        if space.get("storey") == "2F" and sid in av.room_of
    ]
    return min(t for t in times if t is not None)


def test_collins_fire_spill_plume_brings_the_2f_untenable_time_into_range():
    # Audit hand estimate for a fast fire in 140: 2F untenable at about 1:00-1:45 once the
    # spill plume entrains atrium air, against 4:18 without it.
    t_balcony = _first_2f_untenable("balcony")
    t_axi = _first_2f_untenable("axisymmetric")
    t_off = _first_2f_untenable("off")
    assert 60 <= t_balcony <= 105, t_balcony
    assert t_balcony <= t_axi <= t_off  # NFPA 92 line plume >= point plume >= no entrainment
    assert t_off >= 200, t_off
