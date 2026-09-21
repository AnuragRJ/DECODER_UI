"""Derived oceanographic variables.

Phase 3 M3 adds electrical conductivity (CNDC) derived from in-situ
temperature, practical salinity and pressure using TEOS-10
(:func:`gsw.C_from_SP`).  The MATLAB reference computes CNDC the same way
in :file:`compute_rt_adjusted_param.m` (calls ``gsw_C_from_SP(SP, t, p)``),
so this is the authoritative formula for real-time products.

Design notes
-----------
* Routines in this module are **pure functions over numpy arrays**. They
  do not read files, do not touch xarray Datasets, and do not carry any
  module-level state (Guardrails §7).  The sensor/decoder layers call in
  to apply the derivation and attach the resulting variable to the
  profile dataset.
* Fill-value samples (``NaN`` / Argo fill sentinels) propagate through
  as ``NaN`` so they round-trip through the NetCDF writer.
* ``gsw`` is imported lazily so that importing ``argo_decoder`` on a
  minimal install (without the ``[gsw]`` extra) does not fail at import
  time; we raise a clear :class:`MissingDependencyError` if CNDC is
  requested without the library installed.
"""

from __future__ import annotations

from typing import Any

import numpy as np

# Argo reference fill values for CNDC.  The MATLAB writer uses
# single(99999) as the _FillValue but stores CNDC in S/m with ~1e-4
# resolution; we mirror that with a float fill so downstream writers
# can encode it at the right NetCDF type.
CNDC_FILL = 99.9999
"""Argo fill value for CNDC (S/m)."""


class MissingDependencyError(RuntimeError):
    """Raised when a derived-variable routine needs an optional dependency
    (e.g. ``gsw``) that isn't installed."""


def _require_gsw() -> Any:
    try:
        import gsw  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - exercised only without gsw
        raise MissingDependencyError(
            "Computing CNDC requires the 'gsw' package. "
            "Install with `pip install argo-decoder[gsw]`."
        ) from exc
    return gsw


def conductivity_from_sp(
    salinity_psu: np.ndarray,
    temperature_c: np.ndarray,
    pressure_dbar: np.ndarray,
) -> np.ndarray:
    """Compute electrical conductivity (S/m) from SP, in-situ T, and P.

    Wraps :func:`gsw.C_from_SP` with NaN/fill propagation and unit
    conversion: TEOS-10 ``gsw_C_from_SP`` returns mS/cm (per its docstring
    and the embedded MATLAB copy in ``sub_foreign/gsw_C_from_SP.m``) while
    the Argo reference (``get_netcdf_param_attributes.m`` for ``CNDC``)
    uses S/m (mhos/m) with validMax 8.5 S/m.  The conversion factor is
    0.1 (1 mS/cm = 0.1 S/m), consistent with CF/Argo practice and with
    what MATLAB writes out to mono-profile files.

    Any sample where any input is NaN or at its Argo fill value yields
    NaN on output so the caller can mask consistently.  Inputs are
    coerced to float64 numpy arrays.
    """
    gsw = _require_gsw()
    sp = np.asarray(salinity_psu, dtype=np.float64)
    t = np.asarray(temperature_c, dtype=np.float64)
    p = np.asarray(pressure_dbar, dtype=np.float64)
    if not (sp.shape == t.shape == p.shape):
        raise ValueError(f"P/T/S shape mismatch: sp={sp.shape} t={t.shape} p={p.shape}")
    # Identify invalid samples: NaNs or Argo fill sentinels.
    invalid = (
        ~np.isfinite(sp)
        | ~np.isfinite(t)
        | ~np.isfinite(p)
        | (sp >= 99.0)  # PSAL_FILL = 99.999
        | (t >= 99.0)  # TEMP_FILL = 99.999
        | (p >= 9999.0)  # PRES_FILL = 9999.9
    )
    # Work on copies so we don't mutate the caller's arrays; pass only
    # valid samples to gsw to avoid warnings on NaNs.
    sp_work = np.where(invalid, 35.0, sp)
    t_work = np.where(invalid, 15.0, t)
    p_work = np.where(invalid, 0.0, p)
    c_ms_cm = gsw.C_from_SP(sp_work, t_work, p_work)
    c = np.asarray(c_ms_cm, dtype=np.float64) * 0.1  # mS/cm -> S/m
    c[invalid] = np.nan
    return c


__all__ = [
    "CNDC_FILL",
    "MissingDependencyError",
    "conductivity_from_sp",
]
