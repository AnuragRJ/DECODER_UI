"""TEST014: density-inversion QC test.

Flags pairs of adjacent levels where a shallower sample is denser than
the deeper sample immediately below it — the classic static-stability
failure that almost always indicates a sensor glitch or a mis-routed
sample.

The algorithm mirrors the Coriolis MATLAB implementation in
``add_rtqc_to_profile_file.m`` (``testFlagList(14)``) exactly:

1. Restrict to valid samples with PRES_QC / TEMP_QC / PSAL_QC != BAD.
2. Compute potential density at the midpoint pressure between every
   adjacent valid pair, both for the shallow sample (sigma_shallow)
   and the deeper sample (sigma_deep), using TEOS-10 SA/CT.
3. When ``sigma_shallow - sigma_deep >= 0.03 kg/m³``, flag the shallow
   level (top→bottom pass).
4. When ``sigma_deep - sigma_shallow <= -0.03 kg/m³`` (the same
   condition viewed from below), flag the deep level (bottom→top pass).
5. Flagged levels get TEMP_QC = PSAL_QC = BAD (4). PRES_QC and CNDC_QC
   are left untouched because the density inversion test cannot tell
   which of P/T/S caused the instability.

Threshold 0.03 kg/m³ is the value used by the Coriolis COQC software
(reference table 2a in the Argo QC manual for CTD and Trajectory data,
v3.9).

This module does **not** touch DOXY_QC: DOXY QC propagation from
PRES/TEMP/PSAL failures is handled separately (TEST057 in MATLAB;
planned for a later slice once DOXY RTQC policy is settled).
"""

from __future__ import annotations

import numpy as np

from argo_decoder.domain.qc import QcFlag
from argo_decoder.rtqc.non_density import QcTestOutcome

# Density-difference threshold (kg/m³) for flagging an inversion.  A
# difference of 0.03 kg/m³ between levels separated by a few dbar is
# well outside natural fine structure and is the MATLAB/Argo default.
DENSITY_INVERSION_THRESHOLD = 0.03


def density_inversion_test(
    *,
    pres: np.ndarray,
    temp: np.ndarray,
    psal: np.ndarray,
    lat: float,
    lon: float,
    pres_qc: np.ndarray | None = None,
    temp_qc: np.ndarray | None = None,
    psal_qc: np.ndarray | None = None,
) -> tuple[QcTestOutcome, QcTestOutcome]:
    """Run TEST014.

    Inputs are in Argo order (PRES ascending, shallowest first).  The
    optional ``*_qc`` arrays are int8 QC flags; only samples that are
    not BAD (flag == 4) on all three inputs participate in the test,
    matching MATLAB's ``*Qc ~= g_decArgo_qcStrBad`` gating.

    Returns
    -------
    (temp_outcome, psal_outcome)
        Per-level flag arrays with BAD set at levels implicated in a
        density inversion.  PRES_QC/CNDC_QC are intentionally not
        modified by this test — the caller merges worst-case flags.
    """
    from argo_decoder.derived.density import potential_density

    p = np.asarray(pres, dtype=np.float64)
    t = np.asarray(temp, dtype=np.float64)
    s = np.asarray(psal, dtype=np.float64)
    n = len(p)

    temp_flags = np.full(n, int(QcFlag.GOOD), dtype=np.int8)
    psal_flags = np.full(n, int(QcFlag.GOOD), dtype=np.int8)

    if n < 2:
        return (
            QcTestOutcome("density_inversion[TEMP]", temp_flags, QcFlag.GOOD, 0),
            QcTestOutcome("density_inversion[PSAL]", psal_flags, QcFlag.GOOD, 0),
        )

    p_qc = np.ones(n, dtype=np.int8) if pres_qc is None else np.asarray(pres_qc, dtype=np.int8)
    t_qc = np.ones(n, dtype=np.int8) if temp_qc is None else np.asarray(temp_qc, dtype=np.int8)
    s_qc = np.ones(n, dtype=np.int8) if psal_qc is None else np.asarray(psal_qc, dtype=np.int8)

    # Valid-and-not-BAD mask.
    valid = (
        np.isfinite(p)
        & np.isfinite(t)
        & np.isfinite(s)
        & (p_qc != int(QcFlag.BAD))
        & (t_qc != int(QcFlag.BAD))
        & (s_qc != int(QcFlag.BAD))
    )
    # Exclude fill sentinels (PRES_FILL=9999.9 and friends).
    valid &= p < 9000.0
    valid &= (t > -2.5) & (t < 42.0)
    valid &= (s > 2.0) & (s < 41.0)

    # Levels excluded from the test are *not* flagged by it.
    #
    # ``valid`` is a participation mask, not a verdict: a level drops out
    # when any of PRES/TEMP/PSAL is non-finite, out of range, or already
    # BAD from an earlier test. Marking those levels BAD here made TEST014
    # re-state other tests' findings under its own name, and -- worse --
    # propagated a flag across parameters. On WMO 2901304 cycle 8 the
    # salinity sensor was stuck (33.822 repeated, correctly caught by
    # TEST013 on PSAL), which excluded those ten levels and so condemned a
    # perfectly good TEMP series varying 1.704 -> 1.707 degC. GDAC flags
    # TEMP good there, and it is right to.
    #
    # A test may only flag what it actually measured: the two members of
    # an adjacent pair whose potential densities invert. Levels it could
    # not evaluate keep the flag their own parameter's tests gave them,
    # which the caller merges with ``np.maximum``.

    # Walk adjacent valid pairs.  We need consecutive indices both valid
    # to perform the check (matches MATLAB's idNoDefAndGood filtering).
    for k in range(n - 1):
        if not (valid[k] and valid[k + 1]):
            continue
        dp = p[k + 1] - p[k]
        if dp <= 0:
            # pressure inversion already handled by TEST008; skip.
            continue
        p_ref = 0.5 * (p[k] + p[k + 1])
        pair_p = np.array([p[k], p[k + 1]], dtype=np.float64)
        pair_t = np.array([t[k], t[k + 1]], dtype=np.float64)
        pair_s = np.array([s[k], s[k + 1]], dtype=np.float64)
        try:
            sigma = potential_density(pair_p, pair_t, pair_s, ref_pres=p_ref, lon=lon, lat=lat)
        except Exception:  # pragma: no cover - defensive; gsw failures
            continue
        if not np.all(np.isfinite(sigma)):
            continue
        d_sigma = float(sigma[0] - sigma[1])
        if d_sigma >= DENSITY_INVERSION_THRESHOLD:
            # shallow denser than deep -> density inversion; flag BOTH
            # neighbours per MATLAB (shallow on the top→bottom pass, deep
            # on the bottom→top pass so both levels are marked BAD).
            temp_flags[k] = int(QcFlag.BAD)
            psal_flags[k] = int(QcFlag.BAD)
            temp_flags[k + 1] = int(QcFlag.BAD)
            psal_flags[k + 1] = int(QcFlag.BAD)

    n_temp = int(np.sum(temp_flags == int(QcFlag.BAD)))
    n_psal = int(np.sum(psal_flags == int(QcFlag.BAD)))
    return (
        QcTestOutcome(
            "density_inversion[TEMP]",
            temp_flags,
            QcFlag.BAD if n_temp else QcFlag.GOOD,
            n_temp,
        ),
        QcTestOutcome(
            "density_inversion[PSAL]",
            psal_flags,
            QcFlag.BAD if n_psal else QcFlag.GOOD,
            n_psal,
        ),
    )


__all__ = ["DENSITY_INVERSION_THRESHOLD", "density_inversion_test"]
