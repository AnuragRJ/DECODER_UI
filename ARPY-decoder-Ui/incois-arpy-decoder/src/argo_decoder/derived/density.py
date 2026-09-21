"""Derived seawater density (TEOS-10, via ``gsw``).

Implements potential density (referenced to an arbitrary pressure) and
in-situ density following the Coriolis MATLAB helper
:file:`sub_foreign/potential_density_gsw.m`.  The routines are pure
numpy functions so they can be reused by RTQC (TEST014 density
inversion), the DOXY μmol/L → μmol/kg conversion, and any future
delayed-mode adjustments.

Pressure validity matches MATLAB exactly:

* ``-5 ≤ pres < 0`` is clamped to ``0`` (near-surface sensor noise);
* ``pres < -5`` or ``pres > 11000`` produces NaN (invalid).

Fill-value samples propagate as NaN.  The ``gsw`` package is imported
lazily so that minimal CI environments (without the TEOS-10 toolbox)
can still import this module; a ``MissingDependencyError`` is raised if
a caller actually invokes a density computation without ``gsw``.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from argo_decoder.derived.cndc import MissingDependencyError

# Argo fill value for potential density anomaly (sigma-0) - matches the
# convention used elsewhere for derived scalar variables.
DENSITY_FILL = 9999.999


def _require_gsw() -> Any:
    try:
        import gsw  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover
        raise MissingDependencyError(
            "Computing in-situ/potential density requires the 'gsw' package. "
            "Install with `pip install argo-decoder[gsw]`."
        ) from exc
    return gsw


def _valid_pressure_mask(pres: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (clamped_pres, valid_mask) following MATLAB's gating rules."""
    p = np.asarray(pres, dtype=np.float64).copy()
    valid = np.isfinite(p)
    # clamp near-surface slightly-negative pressures to 0
    near_surface = valid & (p >= -5.0) & (p < 0.0)
    p[near_surface] = 0.0
    # truly invalid pressure window
    invalid_p = (~np.isfinite(p)) | (p < -5.0) | (p > 11000.0)
    p[invalid_p] = 0.0  # avoid feeding NaN/extremes to gsw; we NaN the output anyway
    valid = valid & (~invalid_p)
    return p, valid


def potential_density(
    pres: np.ndarray,
    temp: np.ndarray,
    psal: np.ndarray,
    ref_pres: np.ndarray | float,
    lon: float,
    lat: float,
) -> np.ndarray:
    """Potential density (kg/m³) referenced to ``ref_pres``.

    Mirrors ``potential_density_gsw.m``: clamps ``pres`` in [-5,0) → 0,
    NaNs out-of-range pressures, computes
    ``gsw_rho(SA_from_SP(psal, pres, lon, lat), CT_from_t(SA, temp, pres), ref_pres)``.

    ``ref_pres`` may be scalar (constant reference level, e.g. 0 dbar for
    surface-referenced sigma-0 or the mid-point pressure for the TEST014
    two-point density-inversion check) or array-like with the same
    length as ``pres``.
    """
    gsw = _require_gsw()
    p = np.asarray(pres, dtype=np.float64)
    t = np.asarray(temp, dtype=np.float64)
    s = np.asarray(psal, dtype=np.float64)
    scalar_ref = np.isscalar(ref_pres)
    ref = np.asarray(ref_pres, dtype=np.float64)
    if not scalar_ref and ref.shape != p.shape:
        raise ValueError(f"ref_pres shape {ref.shape} must match pres shape {p.shape} when array")
    p_valid, mask = _valid_pressure_mask(p)
    # mask out NaN inputs and obviously bogus fill values (Argo T/S fills
    # are 99.999 which is far outside any physical oceanographic range;
    # gsw would happily compute a nonsensical density from them).
    inp_valid = (
        mask & np.isfinite(t) & np.isfinite(s) & (t > -2.5) & (t < 42.0) & (s > 2.0) & (s < 41.0)
    )
    sa = gsw.SA_from_SP(np.where(inp_valid, s, 35.0), p_valid, lon, lat)
    ct = gsw.CT_from_t(sa, np.where(inp_valid, t, 15.0), p_valid)
    if scalar_ref:
        rho = np.asarray(gsw.rho(sa, ct, float(ref)), dtype=np.float64)
    else:
        rho = np.asarray(gsw.rho(sa, ct, np.where(inp_valid, ref, 0.0)), dtype=np.float64)
    rho[~inp_valid] = np.nan
    return rho


def in_situ_density(
    pres: np.ndarray,
    temp: np.ndarray,
    psal: np.ndarray,
    lon: float,
    lat: float,
) -> np.ndarray:
    """In-situ density (kg/m³): potential density referenced to each level's pressure."""
    p = np.asarray(pres, dtype=np.float64)
    return potential_density(p, temp, psal, ref_pres=p, lon=lon, lat=lat)


def sigma0(
    pres: np.ndarray,
    temp: np.ndarray,
    psal: np.ndarray,
    lon: float,
    lat: float,
) -> np.ndarray:
    """Potential density anomaly sigma-0 (kg/m³ - 1000), referenced to 0 dbar."""
    return potential_density(pres, temp, psal, ref_pres=0.0, lon=lon, lat=lat) - 1000.0


__all__ = [
    "DENSITY_FILL",
    "in_situ_density",
    "potential_density",
    "sigma0",
]
