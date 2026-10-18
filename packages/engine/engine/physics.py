"""Closed-form fire physics. Pure functions, SI units, kW for heat release rate."""

from __future__ import annotations

import math

from engine.constants import (
    ALPHA_KW_S2,
    AMBIENT_K,
    DOOR_DISCHARGE_COEF,
    G,
    RHO_T,
    SMOKE_PRESENT_DEPTH_M,
    TENABLE_LAYER_HEIGHT_M,
    TENABLE_LAYER_TEMP_K,
    THOMAS_SURFACE_KW_M2,
    THOMAS_VENT_KW,
    VENT_LIMIT_KW,
)


def t_squared_hrr_kw(growth: str, t_s: float) -> float:
    """Q = alpha * t^2 (SFPE)."""
    return ALPHA_KW_S2[growth] * max(t_s, 0.0) ** 2


def vent_factor(openings: list[tuple[float, float]]) -> tuple[float, float]:
    """(area, height) openings -> (A_v total area m², H_v area-weighted height m)."""
    a_v = sum(a for a, _ in openings)
    if a_v <= 0:
        return 0.0, 0.0
    return a_v, sum(a * h for a, h in openings) / a_v


def internal_surface_m2(floor_area: float, perimeter: float, height: float, a_v: float) -> float:
    """A_T for Thomas: floor + ceiling + walls, minus the openings."""
    return max(2.0 * floor_area + perimeter * height - a_v, 0.0)


def thomas_flashover_kw(a_t: float, a_v: float, h_v: float) -> float:
    """Thomas (1981): Q_fo = 7.8*A_T + 378*A_v*sqrt(H_v)."""
    return THOMAS_SURFACE_KW_M2 * a_t + THOMAS_VENT_KW * a_v * math.sqrt(h_v)


def vent_limited_kw(a_v: float, h_v: float) -> float:
    """Most a room can burn on the air its openings let in (Kawagoe)."""
    return VENT_LIMIT_KW * a_v * math.sqrt(h_v)


def plume_mass_kg_s(q_conv_kw: float, z_m: float) -> float:
    """Axisymmetric plume mass flow at height z above the fire (NFPA 92, 5.5.1.1)."""
    if q_conv_kw <= 0:
        return 0.0
    z = max(z_m, 0.1)
    flame_height = 0.166 * q_conv_kw**0.4
    if z <= flame_height:
        return 0.032 * q_conv_kw**0.6 * z
    return 0.071 * q_conv_kw ** (1 / 3) * z ** (5 / 3) + 0.0018 * q_conv_kw


def door_spill_kg_s(width_m: float, depth_m: float, layer_k: float) -> float:
    """Hot gas out of an opening whose top `depth_m` is in the smoke layer (SFPE vent flow).

    m = 2/3 * Cd * W * rho_s * sqrt(2 g (T_s/T_a - 1)) * d^1.5. A 5 K floor on the
    temperature difference lets cool smoke still drift.
    """
    if depth_m <= 0 or width_m <= 0:
        return 0.0
    t_s = max(layer_k, AMBIENT_K + 5.0)
    rho_s = RHO_T / t_s
    velocity = math.sqrt(2.0 * G * (t_s / AMBIENT_K - 1.0))
    return (2.0 / 3.0) * DOOR_DISCHARGE_COEF * width_m * rho_s * velocity * depth_m**1.5


def is_untenable(layer_height_above_floor_m: float, layer_k: float, layer_depth_m: float) -> bool:
    """ISO 13571-style: smoke at head height, or a hot layer radiating ~2.5 kW/m²."""
    if layer_depth_m < SMOKE_PRESENT_DEPTH_M:
        return False
    return layer_height_above_floor_m < TENABLE_LAYER_HEIGHT_M or layer_k >= TENABLE_LAYER_TEMP_K
