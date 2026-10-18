import math

import pytest

from engine import physics


def test_t_squared_classes_reach_1055_kw_at_their_growth_time():
    # SFPE classes are defined by the time to reach 1055 kW.
    for growth, t_g in [("slow", 600), ("medium", 300), ("fast", 150), ("ultrafast", 75)]:
        assert physics.t_squared_hrr_kw(growth, t_g) == pytest.approx(1055, rel=0.01)


def test_thomas_flashover_for_iso_9705_room_is_about_1_mw():
    # ISO 9705 room: 3.6 x 2.4 x 2.4 m, one 0.8 x 2.0 m door. Tests flash over near 1 MW.
    a_v, h_v = physics.vent_factor([(0.8 * 2.0, 2.0)])
    a_t = physics.internal_surface_m2(3.6 * 2.4, 2 * (3.6 + 2.4), 2.4, a_v)
    q_fo = physics.thomas_flashover_kw(a_t, a_v, h_v)
    assert 900 < q_fo < 1400


def test_vent_limit_is_1500_kw_per_ventilation_factor():
    a_v, h_v = 1.6, 2.0
    assert physics.vent_limited_kw(a_v, h_v) == pytest.approx(1500 * 1.6 * math.sqrt(2.0))


def test_plume_mass_is_continuous_at_flame_height():
    q_c = 1000.0
    flame = 0.166 * q_c**0.4
    below = physics.plume_mass_kg_s(q_c, flame * 0.999)
    above = physics.plume_mass_kg_s(q_c, flame * 1.001)
    assert below == pytest.approx(above, rel=0.05)
    assert physics.plume_mass_kg_s(q_c, 5.0) > physics.plume_mass_kg_s(q_c, 2.0)


def test_door_spill_needs_smoke_in_the_opening():
    assert physics.door_spill_kg_s(0.9, 0.0, 500.0) == 0.0
    assert physics.door_spill_kg_s(0.9, 0.5, 500.0) > 0.0


def test_tenability_limits():
    assert not physics.is_untenable(2.5, 320.0, 1.0)  # clear at head height, warm layer
    assert physics.is_untenable(1.9, 320.0, 1.0)  # smoke below 2 m
    assert physics.is_untenable(3.0, 480.0, 1.0)  # hot layer above ~200 °C
    assert not physics.is_untenable(1.0, 480.0, 0.0)  # no layer yet
