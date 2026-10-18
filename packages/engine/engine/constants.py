"""Every physical constant and modelling assumption, in one place.

Sources:
- SFPE: SFPE Handbook of Fire Protection Engineering, 5th ed. (t-squared fires,
  plumes, vent flows). The alpha values also appear in NFPA 72 Annex B and NFPA 92.
- Thomas: P.H. Thomas, "Testing products and materials for their contribution to
  flashover in rooms", Fire and Materials 5 (1981).
- NFPA 92: Standard for Smoke Control Systems (2021), axisymmetric plume equations.
- EN 1991-1-2: Eurocode 1, Part 1-2, Annex E (design fire load and heat release
  rate per m² by occupancy).
- ISO 13571: Life-threatening components of fire, guidance for estimating time
  available for escape (tenability limits for heat and visibility).
Values marked ASSUMPTION are Aria's engineering choices, not from a standard.
"""

# --- Fire growth: Q = alpha * t^2 (kW, t in s). SFPE / NFPA 72 Annex B. ---
# Each class is the time to reach 1055 kW (1000 BTU/s): 600, 300, 150, 75 s.
ALPHA_KW_S2 = {
    "slow": 0.00293,
    "medium": 0.01172,
    "fast": 0.0469,
    "ultrafast": 0.1876,
}

# --- Flashover threshold, Thomas (1981): Q_fo = 7.8*A_T + 378*A_v*sqrt(H_v) (kW). ---
THOMAS_SURFACE_KW_M2 = 7.8  # per m² of internal surface area A_T (walls+floor+ceiling-vents)
THOMAS_VENT_KW = 378.0  # per m^(5/2) of ventilation factor A_v*sqrt(H_v)

# --- Ventilation-limited burning (Kawagoe / SFPE): ~1500 kW per m^(5/2) of A_v*sqrt(H_v). ---
# Air inflow ~0.5*A_v*sqrt(H_v) kg/s times ~3000 kJ released per kg of air.
VENT_LIMIT_KW = 1500.0

# --- Fuel by occupancy: (peak heat release rate per m² floor, kW/m²; fire load, MJ/m²). ---
# EN 1991-1-2 Annex E, Tables E.4 (80% fractile fire load) and E.5 (RHR_f).
FUEL_CLASSES = {
    "assembly": (500.0, 365.0),  # EN: theatre / cinema
    "office": (250.0, 420.0),  # EN: office
    "kitchen": (500.0, 780.0),  # ASSUMPTION: dwelling fire load, theatre-level RHR
    "storage": (500.0, 1180.0),  # ASSUMPTION: library-like fire load
    "circulation": (250.0, 100.0),  # EN: transport (public space); corridors, lobbies
    "restroom": (250.0, 50.0),  # ASSUMPTION: very low fuel
    "stair": (250.0, 20.0),  # ASSUMPTION: protected stair, almost no fuel
}
# EN 1991-1-2 E.4: the decay phase starts once 70% of the fire load is consumed.
DECAY_START_FRACTION = 0.7

# --- Plume and smoke layer (NFPA 92 / SFPE). ---
CONVECTIVE_FRACTION = 0.7  # NFPA 92: convective share of the total heat release rate
WALL_LOSS_FRACTION = 0.6  # ASSUMPTION: share of convective heat lost to the ceiling/walls
AMBIENT_K = 293.15  # 20 °C
CP_KJ_KG_K = 1.0  # specific heat of air/smoke
RHO_T = 353.0  # ideal gas at 1 atm: rho [kg/m³] = 353 / T [K]
G = 9.81
DOOR_DISCHARGE_COEF = 0.7  # SFPE vent flows (Emmons), sharp-edged opening
POST_FLASHOVER_K = 1100.0  # ~830 °C, typical fully developed compartment gas temperature
MAX_LAYER_K = 1300.0

# --- Spill plumes: smoke leaving a burning room under a soffit into a taller space. ---
# Below the soffit the doorway jet is the door flow alone (SFPE vent flow). Above it the smoke
# rises as a spill plume through the taller room's clear air and entrains it, so far more
# (cooler) mass reaches that room's layer: the atrium case of NFPA 92 (2021) 5.5.2 and
# CIBSE Guide E / BRE 368. Applied only while the source room burns and has not flashed over,
# and only while the destination's layer is above the soffit. The fire's heat is shared
# between the openings it spills through in proportion to their flow. Modes:
# - "balcony" (default): NFPA 92 (2021) eq. 5.5.2.1, m = 0.36 (Q W²)^(1/3) (z_b + 0.25 H),
#   Q the fire's heat release rate (kW), W the opening width (no balcony: W = opening),
#   z_b the rise above the soffit, H the soffit above the fire. It treats the opening as a
#   line source, which suits the James West openings (3.3 m and 9.3 m wide archways). The
#   standard's design equation, conservative for life safety; an adhered plume (one that
#   clings to the wall above a door) entrains somewhat less.
# - "axisymmetric": the fire's own point-source plume (NFPA 92 5.5.1.1) carries on above the
#   soffit, m_p(Qc, H + z_b) - m_p(Qc, H). Ignores the opening width; the lower estimate.
# - "off": no entrainment above the soffit (the engine before 18 Oct; under-predicts).
SPILL_ENTRAINMENT = "balcony"
SPILL_MODES = ("balcony", "axisymmetric", "off")
BALCONY_SPILL_COEF = 0.36  # NFPA 92 eq. 5.5.2.1 (kg/s per (kW·m²)^(1/3) per m)
BALCONY_SPILL_EDGE_FACTOR = 0.25  # NFPA 92 eq. 5.5.2.1: weight on H, soffit height above the fire

# --- Tenability (ISO 13571-style limits, used as simple zone-model criteria). ---
# Untenable when the smoke layer interface is below 2 m above the occupied floor
# (visibility and toxic gases at head height), or when the hot layer is hot enough to
# give ~2.5 kW/m² radiant flux at head height (ISO 13571 limit), which is ~200 °C.
TENABLE_LAYER_HEIGHT_M = 2.0
TENABLE_LAYER_TEMP_K = 200.0 + 273.15
SMOKE_PRESENT_DEPTH_M = 0.05  # report "smoke enters" once the layer is 5 cm deep

# --- Openings and spread. ---
DEFAULT_DOOR_HEIGHT_M = 2.1
SPREAD_OPEN_DOOR_DELAY_S = 180.0  # ASSUMPTION: flashed-over room ignites neighbor via open door
UNRATED_CLOSED_DOOR_HOLD_S = 300.0  # ASSUMPTION: closed unrated door burns through in ~5 min
SECONDARY_GROWTH = "ultrafast"  # ASSUMPTION: a room ignited by a neighbor is pre-heated

TIME_STEP_S = 1.0
