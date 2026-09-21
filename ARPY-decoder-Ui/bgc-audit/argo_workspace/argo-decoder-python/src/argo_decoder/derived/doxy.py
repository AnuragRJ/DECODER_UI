"""Aanderaa 4330 optode dissolved-oxygen derivation.

Implements the Stern-Volmer + salinity/pressure corrections used by the
Coriolis MATLAB chain for NKE Provor/Arvor floats (decoder_ids 201-232,
including ARVOR_D 5.67 / decId 221 = WMO 6902892).

The chain is:

1. Convert raw 16-bit C1/C2-phase and TEMP_DOXY counts to physical units
   (degrees for phase, °C for optode thermistor) using the linear
   on-board scalings from
   :file:`sensor_2_value_for_C1C2phase_ir_sbd_2xx.m` and
   :file:`sensor_2_value_for_temp_doxy_ir_sbd_2xx.m`.
2. Compute MOLAR_DOXY (μmol/L) via the Aanderaa 4330 Stern-Volmer
   equation (``calcoxy_aanderaa4330_sternvolmer.m``).
3. Apply the Garcia & Gordon salinity correction
   (``calcoxy_salcomp.m``).
4. Apply the Enns et al. pressure correction (``calcoxy_prescomp.m``).
5. Convert μmol/L → μmol/kg by dividing by potential density (kg/L) at
   0 dbar reference pressure, computed from in-situ T/S/P and the
   float's profile location via TEOS-10
   (``potential_density_gsw.m`` → ``gsw_rho(SA, CT, 0)`` / 1000).

All routines are pure functions over numpy arrays (Guardrails §7: no
module-level globals, no file I/O). Fill-value samples propagate as
NaN; the caller is responsible for writing the Argo fill sentinel.

Calibration coefficients come from the float meta JSON
(``CALIBRATION_COEFFICIENT[0].OPTODE``): ``PhaseCoef0..3`` and
``SVUFoilCoef0..6`` (2-by-7 ``TabDoxyCoef`` matrix). The additional
pressure/salinity coefficients (``pCoef1..3``, ``d0..d3``, ``b0..b3``,
``c0``, ``sPreset``) are universal constants taken verbatim from
``init_default_values.m`` (global ``g_decArgo_doxy_202_205_304_*``).

References
----------
* Aanderaa Data Instruments, "TD 269 Operating Manual: Oxygen Optode
  4330/4835/4831".
* Garcia, H.E. & Gordon, L.I. (1992). "Oxygen solubility in seawater:
  Better fitting equations". *Limnol. Oceanogr.* 37(6).
* Enns, T., Scholander, P.F. & Bradstreet, E.D. (1965). "Effect of
  hydrostatic pressure on gases dissolved in water". *J. Phys. Chem.*
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

# --------------------------------------------------------------------------
# Universal constants (init_default_values.m for the 202/205/304 optode family)
# --------------------------------------------------------------------------

_PCOEF1 = 0.1
_PCOEF2 = 0.00022
_PCOEF3 = 0.0419
_SPRESET = 0.0
_D0 = 24.4543
_D1 = -67.4509
_D2 = -4.8489
_D3 = -0.000544
_B0 = -0.00624523
_B1 = -0.00737614
_B2 = -0.0103410
_B3 = -0.00817083
_C0 = -4.88682e-07

# Count-scaling sentinels (used to detect fill samples before scaling)
PHASE_COUNTS_FILL = 99999
TEMP_DOXY_COUNTS_FILL = 99999
CTD_COUNTS_FILL = 99999

# Argo fill value for DOXY (μmol/kg)
DOXY_FILL = 9999.999


@dataclass(frozen=True)
class OptodeCalibration:
    """Per-float optode calibration coefficients.

    ``phase_coef`` (length 4) and ``sve_coef`` (length 7) come from the
    float meta JSON (``PhaseCoef0..3`` and ``SVUFoilCoef0..6`` under
    ``CALIBRATION_COEFFICIENT[0].OPTODE``).  They correspond to the
    two rows of MATLAB's ``tabDoxyCoef``.
    """

    phase_coef: tuple[float, float, float, float] = (-1.496, 1.0, 0.0, 0.0)
    sve_coef: tuple[float, float, float, float, float, float, float] = (
        0.002800564,
        0.0001196874,
        2.444862e-06,
        187.5869,
        -0.2333455,
        -45.40582,
        3.7045,
    )

    @classmethod
    def from_meta_dict(cls, optode_cal: dict[str, Any] | None) -> OptodeCalibration:
        if optode_cal is None:
            return cls()
        pc_list = [float(optode_cal.get(f"PhaseCoef{i}", d)) for i, d in enumerate(cls.phase_coef)]
        sc_list = [float(optode_cal.get(f"SVUFoilCoef{i}", d)) for i, d in enumerate(cls.sve_coef)]
        pc = (pc_list[0], pc_list[1], pc_list[2], pc_list[3])
        sc = (
            sc_list[0],
            sc_list[1],
            sc_list[2],
            sc_list[3],
            sc_list[4],
            sc_list[5],
            sc_list[6],
        )
        return cls(phase_coef=pc, sve_coef=sc)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _as_f64(*arrays: np.ndarray | list[float]) -> list[np.ndarray]:
    return [np.asarray(a, dtype=np.float64) for a in arrays]


def _phase_from_counts(counts: np.ndarray) -> np.ndarray:
    """Convert C1/C2 PHASE_DOXY counts → degrees: ``(c-20000)*2/1000``.

    Returns NaN for fill samples (``PHASE_COUNTS_FILL``).
    """
    out = (counts.astype(np.float64) - 20000.0) * 2.0 / 1000.0
    out[counts == PHASE_COUNTS_FILL] = np.nan
    return out


def _temp_doxy_from_counts(counts: np.ndarray) -> np.ndarray:
    """Convert TEMP_DOXY counts → optode thermistor °C: ``(c-5000)/1000``.

    Returns NaN for fill samples.
    """
    out = (counts.astype(np.float64) - 5000.0) / 1000.0
    out[counts == TEMP_DOXY_COUNTS_FILL] = np.nan
    return out


# --------------------------------------------------------------------------
# Stern-Volmer (MOLAR_DOXY, μmol/L)
# --------------------------------------------------------------------------


def _stern_volmer(
    t_phase: np.ndarray,
    pres: np.ndarray,
    temp_doxy: np.ndarray,
    cal: OptodeCalibration,
) -> np.ndarray:
    pc0, pc1, pc2, pc3 = cal.phase_coef
    c0, c1, c2, c3, c4, c5, c6 = cal.sve_coef
    phase_pcorr = t_phase + _PCOEF1 * pres / 1000.0
    cal_phase = pc0 + pc1 * phase_pcorr + pc2 * phase_pcorr**2 + pc3 * phase_pcorr**3
    ksv = c0 + c1 * temp_doxy + c2 * temp_doxy**2
    molar = (((c3 + c4 * temp_doxy) / (c5 + c6 * cal_phase)) - 1.0) / ksv
    return np.asarray(molar, dtype=np.float64)


# --------------------------------------------------------------------------
# Salinity correction (Garcia & Gordon vapour pressure / Benson-Krause)
# --------------------------------------------------------------------------


def _salinity_correction(
    molar: np.ndarray,
    temp_ctd: np.ndarray,
    psal: np.ndarray,
) -> np.ndarray:
    # vapour pressure (pH2O in mbar), scaled to atm ratio
    tk = temp_ctd + 273.15
    ph2o_s = 1013.25 * np.exp(_D0 + _D1 * (100.0 / tk) + _D2 * np.log(tk / 100.0) + _D3 * psal)
    ph2o_0 = 1013.25 * np.exp(_D0 + _D1 * (100.0 / tk) + _D2 * np.log(tk / 100.0) + _D3 * _SPRESET)
    a = (1013.25 - ph2o_0) / (1013.25 - ph2o_s)
    ts = np.log((298.15 - temp_ctd) / (273.15 + temp_ctd))
    corr = np.exp(
        (psal - _SPRESET) * (_B0 + _B1 * ts + _B2 * ts**2 + _B3 * ts**3)
        + _C0 * (psal**2 - _SPRESET**2)
    )
    return np.asarray(molar * a * corr, dtype=np.float64)


# --------------------------------------------------------------------------
# Pressure correction (Enns et al.)
# --------------------------------------------------------------------------


def _pressure_correction(
    molar_sal: np.ndarray,
    pres: np.ndarray,
    temp_ctd: np.ndarray,
) -> np.ndarray:
    return np.asarray(
        molar_sal * (1.0 + ((_PCOEF2 * temp_ctd) + _PCOEF3) * pres / 1000.0),
        dtype=np.float64,
    )


# --------------------------------------------------------------------------
# Potential density (kg/L) via TEOS-10 for the μmol/L → μmol/kg conversion
# --------------------------------------------------------------------------


def _potential_density_kg_l(
    pres: np.ndarray,
    temp_ctd: np.ndarray,
    psal: np.ndarray,
    lat: float,
    lon: float,
) -> np.ndarray:
    """Return potential density (kg/L) referenced to 0 dbar.

    Thin wrapper around :func:`argo_decoder.derived.density.potential_density`
    so the DOXY module does not need to know about pressure-clamp
    semantics — they live in one place.
    """
    from argo_decoder.derived.density import potential_density

    # potential_density returns kg/m³; divide by 1000 for kg/L.
    return np.asarray(
        potential_density(pres, temp_ctd, psal, ref_pres=0.0, lon=lon, lat=lat) / 1000.0,
        dtype=np.float64,
    )


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def decode_optode_phase(c1phase_counts: np.ndarray, c2phase_counts: np.ndarray) -> np.ndarray:
    """Return TPHASE_DOXY = C1-C2 phase difference (degrees) from raw counts."""
    c1, c2 = _as_f64(c1phase_counts, c2phase_counts)
    return np.asarray(_phase_from_counts(c1) - _phase_from_counts(c2), dtype=np.float64)


def compute_doxy(
    *,
    c1phase_counts: np.ndarray,
    c2phase_counts: np.ndarray,
    temp_doxy_counts: np.ndarray,
    pres: np.ndarray,
    temp_ctd: np.ndarray,
    psal: np.ndarray,
    latitude: float,
    longitude: float,
    cal: OptodeCalibration | None = None,
) -> np.ndarray:
    """Compute dissolved oxygen (μmol/kg) from raw optode + CTD measurements.

    Parameters
    ----------
    c1phase_counts, c2phase_counts, temp_doxy_counts:
        Raw 16-bit optode counts as delivered by CTDO packets.
    pres, temp_ctd, psal:
        CTD in-situ values (dbar, °C, psu) on the same levels.
    latitude, longitude:
        Profile position used for the Absolute Salinity conversion
        (TEOS-10 SA depends on location via delta-SA climatology).
    cal:
        Optode calibration coefficients; defaults match the demo WMO
        6902892 optode for convenience, but production code should
        always pass the per-float values read from meta JSON.

    Returns
    -------
    np.ndarray
        DOXY in μmol/kg; fill samples propagate as NaN.
    """
    if cal is None:
        cal = OptodeCalibration()
    c1, c2, tdo, p, t, s = _as_f64(
        c1phase_counts, c2phase_counts, temp_doxy_counts, pres, temp_ctd, psal
    )
    # raw → physical units
    tphase = _phase_from_counts(c1) - _phase_from_counts(c2)
    topt = _temp_doxy_from_counts(tdo)
    # invalid mask: any NaN in inputs or counts at their fill sentinel
    invalid = (
        ~np.isfinite(tphase)
        | ~np.isfinite(topt)
        | ~np.isfinite(p)
        | ~np.isfinite(t)
        | ~np.isfinite(s)
    )

    # Stern-Volmer MOLAR_DOXY (μmol/L)
    molar = _stern_volmer(
        np.where(invalid, 0.0, tphase),
        np.where(invalid, 0.0, p),
        np.where(invalid, 15.0, topt),
        cal,
    )
    # Salinity correction
    molar_s = _salinity_correction(molar, np.where(invalid, 15.0, t), np.where(invalid, 35.0, s))
    # Pressure correction
    molar_p = _pressure_correction(molar_s, np.where(invalid, 0.0, p), np.where(invalid, 15.0, t))
    # μmol/L → μmol/kg via potential density (referenced to 0 dbar)
    rho = _potential_density_kg_l(
        np.where(invalid, 0.0, p),
        np.where(invalid, 15.0, t),
        np.where(invalid, 35.0, s),
        latitude,
        longitude,
    )
    doxy = np.asarray(molar_p / rho, dtype=np.float64)
    doxy[invalid] = np.nan
    return doxy


__all__ = [
    "DOXY_FILL",
    "OptodeCalibration",
    "compute_doxy",
    "decode_optode_phase",
]
