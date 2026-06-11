"""
processing.py
--------------
Hydraulic blowdown calculations (ported from LabVIEW G-code).
"""

from __future__ import annotations

from typing import Dict


def process_data(
    hp: float,
    lp: float,
    vel: float,
    last_hp: float,
    last_len: float,
    delta_t: float,
    parameters: Dict[str, float],
) -> Dict[str, float]:
    """
    Compute differential pressure and compressibility-corrected flow.

    Uses compressibility compensation (K_comp) to correct measured flow for
    pressure-transient effects in the hydraulic line between the actuator and
    the flow meter — a constraint imposed by the F18 test rig geometry.
    """
    if delta_t <= 0.0:
        delta_t = 0.00125  # prevent division-by-zero; smallest expected sample period

    # Integrate velocity to track piston position
    current_len = last_len - (vel * delta_t)

    # Compressibility correction coefficient
    k_comp = parameters["Area Attention"] / (delta_t * parameters["Beta"] * parameters["CIS/GPM"])
    q_comp = (hp - last_hp) * current_len * k_comp

    flow = (vel * parameters["Area Attention"]) / parameters["CIS/GPM"] - q_comp

    return {
        "last_hp_out":    hp,
        "last_len_out":   current_len,
        "delta_pressure": hp - lp,
        "flow":           flow,
    }
