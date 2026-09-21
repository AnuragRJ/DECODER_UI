"""CTD + BGC real-time QC for the PROVOR-Bio / CTS4 Iridium-SBD family.

This module is the CTS4-facing entry point of the common RTQC engine.  It
runs the real-time tests that are legitimately supported for this float
family and returns, per profile and per parameter, the Argo reference
table 2 flags that the writer publishes.

Design rules
------------

* **Every threshold has a named authority.**  No value in this module is
  fitted to GDAC data, and none is invented.  Each constant block below
  cites the manual section it comes from.
* **A raw channel that no test can judge stays ``0``** ("no QC was
  performed").  Decoding successfully is not a quality statement.
* **A derived channel earns ``1`` only when the real-time tests support
  it.**  DOXY and CHLA are explicitly denied ``1`` by their own manuals
  (tests 57 and 63), which mandate ``3``.
* **Real-time only.**  Nothing here performs a delayed-mode adjustment.
  Test 63's NPQ/quenching adjustment and the SAGEO2 DOXY gain are
  delayed-mode operations and are deliberately not implemented.

Authorities
-----------

CTD / trajectory
    Argo Quality Control Manual for CTD and Trajectory Data, v3.9
    (DOI 10.13155/33951).

DOXY
    Argo Quality Control Manual for Dissolved Oxygen Concentration, v2.2
    (archimer 00354/46542/123086), sections 2.2.1 and 2.2.2.

CHLA
    BGC-Argo Quality Control Manual for Chlorophyll-A concentration and
    Chlorophyll fluorescence, v3.0 (archimer 00243/35385/60181),
    sections 2.2.1 and 2.2.2.

BBP
    BGC Argo Quality Control Manual for particles backscattering, v1.0
    (DOI 10.13155/60262), section 2.2.2 (test 62, five sub-tests) and
    section 2.6 (flag application policy).

Implementation reference
    Coriolis ``add_rtqc_to_profile_file.m`` (v7.4), whose
    ``expectedTestList`` is the definitive catalogue of the 63 real-time
    tests, and whose tests 57/62/63 are the BGC-specific ones.

The per-test numeric engines for the tests shared with CTD data
(global range, pressure increasing, spike, gradient, digit rollover,
stuck value) live in :mod:`argo_decoder.rtqc.non_density` and are reused
here unchanged, so CTD and BGC cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from argo_decoder.domain.qc import QcFlag
from argo_decoder.rtqc.cross_cycle import (
    frozen_profile_test,
    gross_sensor_drift_test,
    impossible_speed_test,
)
from argo_decoder.rtqc.density_inversion import density_inversion_test
from argo_decoder.rtqc.medd import medd_test
from argo_decoder.rtqc.non_density import (
    digit_rollover_test,
    global_range_test,
    gradient_test,
    deepest_pressure_test,
    pressure_increasing_test,
    spike_test,
    stuck_value_test,
)

__all__ = [
    "BBP_BINS_LOWER_DBAR",
    "BBP_HIGH_DEEP_VALUE",
    "BBP_DEEP_VALUE_PRES_DBAR",
    "BBP_DEEP_VALUE_MIN_POINTS",
    "BBP_MEDIAN_FILTER_WIDTH",
    "BBP_NEGATIVE_PRES_DBAR",
    "BBP_MAX_PCT_BAD_POINTS",
    "BBP_NOISY_PRES_DBAR",
    "BBP_NOISY_RES",
    "BBP_MAX_PCT_OUTLIER",
    "BBP_NOISY_MIN_POINTS",
    "BBP_HOOK_DELTA_PRES0_DBAR",
    "BBP_HOOK_DELTA_PRES1_DBAR",
    "BBP_HOOK_DELTA_PRES2_DBAR",
    "BBP_HOOK_DEV",
    "BGC_GLOBAL_RANGE",
    "BGC_SPIKE_SHALLOW",
    "BGC_SPIKE_DEEP",
    "BGC_GRADIENT_SHALLOW",
    "BGC_GRADIENT_DEEP",
    "TEMP_DOXY_ROLLOVER_DELTA_C",
    "ParamRtqc",
    "ProfileRtqc",
    "median_filter",
    "run_cts4_rtqc",
]

# ---------------------------------------------------------------------------
# Global range (test 6)
# ---------------------------------------------------------------------------
#: DOXY manual v2.2 §2.2.1 test 6: DOXY in [-5, 600] umol/kg, TEMP_DOXY in
#: [-2.5, 40.0] degC.  CHLA manual v3.0 §2.2.1 test 6: CHLA in
#: [-0.2, 100] mg/m3, CHLA_FLUORESCENCE in [-0.2, 100] RU.
#:
#: C1PHASE_DOXY, C2PHASE_DOXY, FLUORESCENCE_CHLA and BETA_BACKSCATTERING700
#: have **no** published global range.  They are IB-Argo raw channels and no
#: manual defines one, so none is applied -- inventing a bound would be an
#: unfitted, unauthorised threshold.
BGC_GLOBAL_RANGE: dict[str, tuple[float, float]] = {
    "DOXY": (-5.0, 600.0),
    "TEMP_DOXY": (-2.5, 40.0),
    "CHLA": (-0.2, 100.0),
    "CHLA_FLUORESCENCE": (-0.2, 100.0),
}

# ---------------------------------------------------------------------------
# Spike (test 9) and gradient (test 11)
# ---------------------------------------------------------------------------
#: DOXY manual v2.2 §2.2.1 test 9.  Test value
#: ``|V2 - (V3+V1)/2| - |(V3-V1)/2|``.  DOXY 50 umol/kg below 500 dbar and
#: 25 umol/kg at or above; TEMP_DOXY 6 degC and 2 degC.
BGC_SPIKE_SHALLOW: dict[str, float] = {"DOXY": 50.0, "TEMP_DOXY": 6.0}
BGC_SPIKE_DEEP: dict[str, float] = {"DOXY": 25.0, "TEMP_DOXY": 2.0}

#: DOXY manual v2.2 §2.2.1 test 11.  Test value ``|V2 - (V3+V1)/2|``.
#: DOXY 50/25; TEMP_DOXY 9 degC and 3 degC.  Test 11 was declared obsolete
#: at ADMT20 but Coriolis still runs it and INCOIS parity depends on it.
BGC_GRADIENT_SHALLOW: dict[str, float] = {"DOXY": 50.0, "TEMP_DOXY": 9.0}
BGC_GRADIENT_DEEP: dict[str, float] = {"DOXY": 25.0, "TEMP_DOXY": 3.0}

#: Pressure split for tests 9 and 11, both manuals.
_BGC_SPLIT_DBAR = 500.0

#: DOXY manual v2.2 §2.2.1 test 12 (digit rollover): TEMP_DOXY difference
#: between adjacent pressures > 10 degC.  Both values used to detect the jump
#: take QC 4 and the rest of the profile takes QC 3.
TEMP_DOXY_ROLLOVER_DELTA_C = 10.0

# ---------------------------------------------------------------------------
# BBP test 62 (BGC BBP manual v1.0 §2.2.2)
# ---------------------------------------------------------------------------
#: Median filter window.  "a median filter is used in some of the proposed
#: tests with a window size (w = 11) (the window size around the first 5
#: points and last 5 points ... will be shrunk to the available points)."
BBP_MEDIAN_FILTER_WIDTH = 11

#: Test 1 (missing data): the upper 1000 dbar are divided into 10 bins with
#: these lower boundaries; MIN_N_PERBIN = 1.
BBP_BINS_LOWER_DBAR: tuple[float, ...] = (
    50.0, 156.0, 261.0, 367.0, 472.0, 578.0, 683.0, 789.0, 894.0, 1000.0,
)
_BBP_MIN_N_PERBIN = 1

#: Test 2 (high deep value).
BBP_HIGH_DEEP_VALUE = 0.0005      # m-1
BBP_DEEP_VALUE_PRES_DBAR = 700.0  # dbar
BBP_DEEP_VALUE_MIN_POINTS = 5

#: Test 3 (negative BBP).
BBP_NEGATIVE_PRES_DBAR = 5.0
BBP_MAX_PCT_BAD_POINTS = 10.0

#: Test 4 (noisy profile).
BBP_NOISY_PRES_DBAR = 100.0
BBP_NOISY_RES = 0.0005            # m-1
BBP_MAX_PCT_OUTLIER = 10.0
BBP_NOISY_MIN_POINTS = 10

#: Test 5 (parking hook).
BBP_HOOK_DELTA_PRES0_DBAR = 100.0
BBP_HOOK_DELTA_PRES1_DBAR = 50.0
BBP_HOOK_DELTA_PRES2_DBAR = 20.0
BBP_HOOK_DEV = 0.0002             # m-1


def median_filter(values: np.ndarray, width: int = BBP_MEDIAN_FILTER_WIDTH) -> np.ndarray:
    """Centre-aligned median filter with edge shrinkage.

    The BBP manual specifies a window of ``w = 11`` whose size is shrunk to
    the available points around the first and last 5 samples.  Non-finite
    entries are excluded from each window; a level whose window holds no
    finite value keeps NaN.
    """
    v = np.asarray(values, dtype=np.float64)
    out = np.full(v.shape, np.nan, dtype=np.float64)
    half = max(width // 2, 0)
    for i in range(v.size):
        lo, hi = max(0, i - half), min(v.size, i + half + 1)
        window = v[lo:hi]
        finite = window[np.isfinite(window)]
        if finite.size:
            out[i] = float(np.median(finite))
    return out


@dataclass
class ParamRtqc:
    """RTQC result for one parameter on one profile."""

    #: Per-level Argo reference table 2 flag, same length as the level array.
    #: ``0`` (no QC performed) where the level is missing or no test applied.
    levels: np.ndarray
    #: Whole-profile flag for ``PROFILE_<PARAM>_QC`` (Argo reference table 19
    #: letters are derived by the writer from this).
    profile: QcFlag = QcFlag.NO_QC
    #: Argo reference table 11 numbers of the tests that actually ran.
    tests_done: set[int] = field(default_factory=set)
    #: Table 11 numbers of the tests that failed.
    tests_failed: set[int] = field(default_factory=set)


@dataclass
class ProfileRtqc:
    """RTQC results for every parameter on one profile."""

    params: dict[str, ParamRtqc] = field(default_factory=dict)
    tests_done: set[int] = field(default_factory=set)
    tests_failed: set[int] = field(default_factory=set)
    #: Test 5 (impossible speed) judges the position, not a measurement
    #: level, so its verdict is a profile scalar.  ``None`` means the test
    #: did not run or did not fail.
    position_qc: bytes | None = None


def _level_flags(n: int) -> np.ndarray:
    return np.full(n, int(QcFlag.NO_QC), dtype=np.int8)


def _valid(values: np.ndarray) -> np.ndarray:
    v = np.asarray(values, dtype=np.float64)
    return np.isfinite(v) & (np.abs(v) < 90000.0)


def _worsen(current: np.ndarray, extra: np.ndarray) -> np.ndarray:
    """Argo flag application policy: a test cannot lower an earlier flag.

    BBP manual §2.6: "The QC flag value assigned by a test cannot override a
    higher value from a previous test."  Argo reference table 2 is ordered so
    that the numerically larger of two applicable codes is the more severe,
    which is the merge Coriolis performs in ``set_qc``.
    """
    return np.maximum(current, extra).astype(np.int8)


def _whole_profile(flags: np.ndarray, mask: np.ndarray, code: QcFlag) -> np.ndarray:
    out = flags.copy()
    out[mask] = _worsen(out[mask], np.full(int(mask.sum()), int(code), dtype=np.int8))
    return out


# ---------------------------------------------------------------------------
# CTD
# ---------------------------------------------------------------------------
def _run_ctd_param(name: str, pres: np.ndarray, values: np.ndarray) -> ParamRtqc:
    """Tests 6, 8, 9, 11, 12 and 13 on one CTD parameter.

    PRES additionally gets test 8 (pressure increasing / monotonicity).
    Thresholds come from :mod:`argo_decoder.rtqc.non_density`, which cites the
    CTD QC manual v3.9 and the Coriolis MATLAB parameter lists.
    """
    n = len(values)
    flags = _level_flags(n)
    ok = _valid(values)
    flags[ok] = int(QcFlag.GOOD)
    done: set[int] = set()
    failed: set[int] = set()

    outcome = global_range_test(name, pres, values)
    flags = _worsen(flags, outcome.per_level)
    done.add(6)
    if outcome.n_flagged:
        failed.add(6)

    if name == "PRES":
        outcome = pressure_increasing_test(pres)
        flags = _worsen(flags, outcome.per_level)
        done.add(8)
        if outcome.n_flagged:
            failed.add(8)
    else:
        for test_number, fn, shallow, deep in (
            (9, spike_test, None, None),
            (11, gradient_test, None, None),
        ):
            outcome = fn(name, pres, values)
            flags = _worsen(flags, outcome.per_level)
            done.add(test_number)
            if outcome.n_flagged:
                failed.add(test_number)
        outcome = digit_rollover_test(name, pres, values)
        flags = _worsen(flags, outcome.per_level)
        done.add(12)
        if outcome.n_flagged:
            failed.add(12)

    # Test 13, stuck value.  CHLA manual §2.2.1 and DOXY manual §2.2.1 both
    # list it for the BGC channels; the CTD manual lists it for PRES/TEMP/PSAL.
    outcome = stuck_value_test(pres, values)
    flags = _worsen(flags, outcome.per_level)
    done.add(13)
    if outcome.n_flagged:
        failed.add(13)

    # A level no test could judge stays 0 (no QC performed), never 1.
    flags[~ok] = int(QcFlag.NO_QC)
    worst = QcFlag(int(flags[ok].max())) if ok.any() else QcFlag.NO_QC
    return ParamRtqc(levels=flags, profile=worst, tests_done=done, tests_failed=failed)


# ---------------------------------------------------------------------------
# BGC: DOXY / TEMP_DOXY
# ---------------------------------------------------------------------------
def _run_doxy_like(
    name: str,
    pres: np.ndarray,
    values: np.ndarray,
    *,
    is_doxy: bool,
    temp_qc: np.ndarray | None = None,
    pres_qc: np.ndarray | None = None,
    psal_qc: np.ndarray | None = None,
) -> ParamRtqc:
    """Tests 6, 9, 11, 12, 13 and (for DOXY) 57 on one oxygen parameter.

    ``is_doxy`` selects test 57, the DOXY-specific rule.  DOXY manual v2.2
    §2.2.2 test 57: real-time unadjusted DOXY takes QC 3 on every defined
    value because Aanderaa optodes suffer predeployment storage drift
    (median sensitivity loss 7.6% across the array).  Then PRES_QC=4 or
    TEMP_QC=4 raises it to 4, while PSAL_QC=4 leaves it at 3.
    """
    n = len(values)
    ok = _valid(values)
    flags = _level_flags(n)
    flags[ok] = int(QcFlag.GOOD)
    done: set[int] = set()
    failed: set[int] = set()

    # stuck_value_test is the only test that does not take the parameter
    # name; the rest need it to look up their per-parameter table.
    for test_number, fn in ((6, global_range_test), (9, spike_test),
                            (11, gradient_test), (12, digit_rollover_test),
                            (13, stuck_value_test)):
        if fn is stuck_value_test:
            outcome = fn(pres, values)
        elif fn is global_range_test:
            # non_density.GLOBAL_RANGE only covers the CTD channels.  BGC
            # ranges must be supplied explicitly, otherwise global_range_test
            # returns GOOD for an unknown name and the test silently does
            # nothing -- which would publish out-of-range DOXY/CHLA as good.
            vmin, vmax = BGC_GLOBAL_RANGE.get(name, (None, None))
            outcome = fn(name, pres, values, vmin=vmin, vmax=vmax)
        else:
            outcome = fn(name, pres, values)
        flags = _worsen(flags, outcome.per_level)
        done.add(test_number)
        if outcome.n_flagged:
            failed.add(test_number)

    if is_doxy:
        done.add(57)
        failed.add(57)  # test 57 "fails" by construction: raw DOXY is not good
        flags[ok] = _worsen(flags[ok], np.full(int(ok.sum()),
                                               int(QcFlag.PROBABLY_BAD),
                                               dtype=np.int8))
        if pres_qc is not None or temp_qc is not None:
            bad_input = np.zeros(n, dtype=bool)
            for src in (pres_qc, temp_qc):
                if src is not None:
                    bad_input |= (np.asarray(src).astype(int) == int(QcFlag.BAD))
            promote = bad_input & ok
            if promote.any():
                flags[promote] = _worsen(flags[promote],
                                         np.full(int(promote.sum()),
                                                 int(QcFlag.BAD), dtype=np.int8))
        if psal_qc is not None:
            # PSAL_QC=4 keeps DOXY_QC at 3 -- already the floor from above.
            pass

    flags[~ok] = int(QcFlag.NO_QC)
    worst = QcFlag(int(flags[ok].max())) if ok.any() else QcFlag.NO_QC
    return ParamRtqc(levels=flags, profile=worst, tests_done=done, tests_failed=failed)


# ---------------------------------------------------------------------------
# BGC: CHLA
# ---------------------------------------------------------------------------
def _run_chla(
    pres: np.ndarray,
    values: np.ndarray,
    *,
    fluorescence_qc: np.ndarray | None = None,
) -> ParamRtqc:
    """Tests 6, 13 and 63 on CHLA.

    CHLA manual v3.0 §2.2.2 test 63: "it is not advisable to use the raw CHLA
    data and consequently, CHLA_QC should be set to '3'".  No gradient or
    spike test is specified for CHLA, so none is applied.

    Flag propagation (§2.6): CHLA is derived from FLUORESCENCE_CHLA, so a
    bad raw-fluorescence flag carries into CHLA.
    """
    n = len(values)
    ok = _valid(values)
    flags = _level_flags(n)
    flags[ok] = int(QcFlag.GOOD)
    done: set[int] = set()
    failed: set[int] = set()

    outcome = global_range_test("CHLA", pres, values,
                           vmin=BGC_GLOBAL_RANGE["CHLA"][0],
                           vmax=BGC_GLOBAL_RANGE["CHLA"][1])
    flags = _worsen(flags, outcome.per_level)
    done.add(6)
    if outcome.n_flagged:
        failed.add(6)

    outcome = stuck_value_test(pres, values)
    flags = _worsen(flags, outcome.per_level)
    done.add(13)
    if outcome.n_flagged:
        failed.add(13)

    done.add(63)
    failed.add(63)  # test 63 "fails" by construction: raw CHLA is not good
    flags[ok] = _worsen(flags[ok], np.full(int(ok.sum()),
                                           int(QcFlag.PROBABLY_BAD),
                                           dtype=np.int8))

    if fluorescence_qc is not None:
        src = np.asarray(fluorescence_qc).astype(int)
        carry = ok & (src >= int(QcFlag.BAD))
        if carry.any():
            flags[carry] = _worsen(flags[carry], src[carry].astype(np.int8))

    flags[~ok] = int(QcFlag.NO_QC)
    worst = QcFlag(int(flags[ok].max())) if ok.any() else QcFlag.NO_QC
    return ParamRtqc(levels=flags, profile=worst, tests_done=done, tests_failed=failed)


def _run_chla_fluorescence(pres: np.ndarray, values: np.ndarray) -> ParamRtqc:
    """Tests 6 and 13 on CHLA_FLUORESCENCE, then QC 1.

    CHLA manual v3.0 §2.2.2: CHLA_FLUORESCENCE is the raw derived optical
    product and test 63 explicitly sets ``CHLA_FLUORESCENCE_QC = 1`` -- unlike
    CHLA it carries no quenching/drift caveat.
    """
    n = len(values)
    ok = _valid(values)
    flags = _level_flags(n)
    flags[ok] = int(QcFlag.GOOD)
    done: set[int] = set()
    failed: set[int] = set()

    outcome = global_range_test("CHLA_FLUORESCENCE", pres, values,
                           vmin=BGC_GLOBAL_RANGE["CHLA_FLUORESCENCE"][0],
                           vmax=BGC_GLOBAL_RANGE["CHLA_FLUORESCENCE"][1])
    flags = _worsen(flags, outcome.per_level)
    done.add(6)
    if outcome.n_flagged:
        failed.add(6)

    outcome = stuck_value_test(pres, values)
    flags = _worsen(flags, outcome.per_level)
    done.add(13)
    if outcome.n_flagged:
        failed.add(13)

    done.add(63)
    flags[~ok] = int(QcFlag.NO_QC)
    worst = QcFlag(int(flags[ok].max())) if ok.any() else QcFlag.NO_QC
    return ParamRtqc(levels=flags, profile=worst, tests_done=done, tests_failed=failed)


# ---------------------------------------------------------------------------
# BGC: BBP700 (test 62, five sub-tests)
# ---------------------------------------------------------------------------
def _bbp_missing_data(pres: np.ndarray, values: np.ndarray, ok: np.ndarray,
                      flags: np.ndarray, failed: set[int]) -> np.ndarray:
    """BBP test 62.1, missing data."""
    edges = (0.0,) + BBP_BINS_LOWER_DBAR
    counts = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        in_bin = ok & (pres >= lo) & (pres < hi)
        counts.append(int(in_bin.sum()) >= _BBP_MIN_N_PERBIN)
    n_bins = sum(counts)
    if ok.sum() == 0:
        failed.add(62)
        return _whole_profile(flags, np.ones_like(ok), QcFlag.MISSING)
    if n_bins == 1:
        failed.add(62)
        return _whole_profile(flags, ok, QcFlag.BAD)
    if n_bins < len(BBP_BINS_LOWER_DBAR):
        failed.add(62)
        return _whole_profile(flags, ok, QcFlag.PROBABLY_BAD)
    return flags


def _bbp_high_deep_value(pres: np.ndarray, values: np.ndarray, ok: np.ndarray,
                         flags: np.ndarray, failed: set[int]) -> np.ndarray:
    """BBP test 62.2, high deep value."""
    deep = ok & (pres >= BBP_DEEP_VALUE_PRES_DBAR)
    if deep.sum() < BBP_DEEP_VALUE_MIN_POINTS:
        return flags
    medfilt = median_filter(values)
    deep_vals = medfilt[deep]
    deep_vals = deep_vals[np.isfinite(deep_vals)]
    if deep_vals.size == 0:
        return flags
    if float(np.median(deep_vals)) > BBP_HIGH_DEEP_VALUE:
        failed.add(62)
        return _whole_profile(flags, ok, QcFlag.PROBABLY_BAD)
    return flags


def _bbp_negative(pres: np.ndarray, values: np.ndarray, ok: np.ndarray,
                  flags: np.ndarray, failed: set[int]) -> np.ndarray:
    """BBP test 62.3, negative BBP."""
    shallow_neg = ok & (pres < BBP_NEGATIVE_PRES_DBAR) & (values < 0.0)
    if shallow_neg.any():
        failed.add(62)
        flags = _worsen(flags, np.where(
            shallow_neg, int(QcFlag.BAD), int(QcFlag.NO_QC)).astype(np.int8))
    deep_mask = ok & (pres >= BBP_NEGATIVE_PRES_DBAR)
    n_deep = int(deep_mask.sum())
    if n_deep:
        n_neg = int((deep_mask & (values < 0.0)).sum())
        pct = 100.0 * n_neg / n_deep
        if pct >= BBP_MAX_PCT_BAD_POINTS:
            failed.add(62)
            flags = _whole_profile(flags, ok, QcFlag.BAD)
        elif pct > 0.0:
            failed.add(62)
            flags = _whole_profile(flags, ok, QcFlag.PROBABLY_BAD)
    return flags


def _bbp_noisy(pres: np.ndarray, values: np.ndarray, ok: np.ndarray,
               flags: np.ndarray, failed: set[int]) -> np.ndarray:
    """BBP test 62.4, noisy profile."""
    if ok.sum() < BBP_NOISY_MIN_POINTS:
        return flags
    medfilt = median_filter(values)
    res = np.abs(medfilt - values)
    shallow = ok & (pres < BBP_NOISY_PRES_DBAR)
    n_shallow = int(shallow.sum())
    if n_shallow == 0:
        return flags
    n_out = int((shallow & (res > BBP_NOISY_RES)).sum())
    if 100.0 * n_out / n_shallow >= BBP_MAX_PCT_OUTLIER:
        failed.add(62)
        return _whole_profile(flags, ok, QcFlag.PROBABLY_BAD)
    return flags


def _bbp_parking_hook(pres: np.ndarray, values: np.ndarray, ok: np.ndarray,
                      flags: np.ndarray, failed: set[int],
                      park_pres: float | None) -> np.ndarray:
    """BBP test 62.5, parking hook (ascending profiles only)."""
    idx = np.where(ok)[0]
    if idx.size < 2:
        return flags
    max_pres = float(pres[idx].max())
    # "the nearest BBP measurement above max(PRES) is <= DELTA_PRES2 dbar away"
    near_deep = pres[idx] >= (max_pres - BBP_HOOK_DELTA_PRES2_DBAR)
    if not near_deep.any():
        return flags
    if park_pres is None:
        return flags
    if abs(max_pres - float(park_pres)) >= BBP_HOOK_DELTA_PRES0_DBAR:
        return flags
    band = ok & (pres >= max_pres - BBP_HOOK_DELTA_PRES1_DBAR) & (
        pres < max_pres - BBP_HOOK_DELTA_PRES2_DBAR)
    if not band.any():
        return flags
    baseline = float(np.median(values[band])) + BBP_HOOK_DEV
    hook = ok & (pres >= max_pres - BBP_HOOK_DELTA_PRES1_DBAR) & (values > baseline)
    if hook.any():
        failed.add(62)
        flags = _worsen(flags, np.where(
            hook, int(QcFlag.BAD), int(QcFlag.NO_QC)).astype(np.int8))
    return flags


def _run_bbp(pres: np.ndarray, values: np.ndarray, *,
             beta_qc: np.ndarray | None = None,
             park_pres: float | None = None,
             ascending: bool = True) -> ParamRtqc:
    """Test 62 on BBP700: the five sub-tests of the BBP manual.

    If every sub-test passes, BBP700_QC is ``1`` (BBP manual §2.2.2: "If the
    following tests are passed, BBP700_QC = 1").  This is the only derived BGC
    parameter the manuals allow to earn ``1`` in real time.

    Flag propagation (§2.6): BBP700 is derived from BETA_BACKSCATTERING700, so
    a bad raw-backscatter flag carries into BBP700.
    """
    n = len(values)
    ok = _valid(values)
    flags = _level_flags(n)
    flags[ok] = int(QcFlag.GOOD)
    done: set[int] = {62}
    failed: set[int] = set()

    # Test 13 (stuck value) applies to BBP via the common-test list.
    outcome = stuck_value_test(pres, values)
    flags = _worsen(flags, outcome.per_level)
    done.add(13)
    if outcome.n_flagged:
        failed.add(13)

    flags = _bbp_missing_data(pres, values, ok, flags, failed)
    flags = _bbp_high_deep_value(pres, values, ok, flags, failed)
    flags = _bbp_negative(pres, values, ok, flags, failed)
    flags = _bbp_noisy(pres, values, ok, flags, failed)
    if ascending:
        flags = _bbp_parking_hook(pres, values, ok, flags, failed, park_pres)

    if beta_qc is not None:
        src = np.asarray(beta_qc).astype(int)
        carry = ok & (src >= int(QcFlag.BAD))
        if carry.any():
            flags[carry] = _worsen(flags[carry], src[carry].astype(np.int8))

    flags[~ok] = int(QcFlag.NO_QC)
    worst = QcFlag(int(flags[ok].max())) if ok.any() else QcFlag.NO_QC
    return ParamRtqc(levels=flags, profile=worst, tests_done=done, tests_failed=failed)


# ---------------------------------------------------------------------------
# Raw IB-Argo channels
# ---------------------------------------------------------------------------
def _run_raw_channel(name: str, pres: np.ndarray, values: np.ndarray) -> ParamRtqc:
    """Test 13 only, on a raw IB-Argo channel.

    ``C1PHASE_DOXY``, ``C2PHASE_DOXY``, ``FLUORESCENCE_CHLA`` and
    ``BETA_BACKSCATTERING700`` are IB-Argo intermediate channels.  The only
    real-time test any manual specifies for them is test 13 (stuck value) --
    DOXY manual §2.2.1 and CHLA manual §2.2.1 both phrase it as applying to
    "all biogeochemical sensor outputs (i.e. 'i' and 'b' parameter
    measurements transmitted by the float)".

    No global range, spike or gradient test is published for these channels,
    so none is applied.  A channel that test 13 does not flag stays at ``0``
    ("no QC was performed") rather than being promoted to ``1``: passing the
    one test that exists is not the same as having passed quality control, and
    INCOIS publishes ``0`` on exactly these four channels.
    """
    n = len(values)
    ok = _valid(values)
    flags = _level_flags(n)
    done: set[int] = set()
    failed: set[int] = set()

    outcome = stuck_value_test(pres, values)
    # Merge only the test's *bad* verdicts.  stuck_value_test returns GOOD on
    # every level it does not flag, and merging that would promote the channel
    # to 1 -- a quality statement no manual authorises for a raw channel.
    bad = outcome.per_level == int(QcFlag.BAD)
    flags[bad] = _worsen(flags[bad], outcome.per_level[bad])
    done.add(13)
    if outcome.n_flagged:
        failed.add(13)

    flags[~ok] = int(QcFlag.NO_QC)
    worst = QcFlag(int(flags[ok].max())) if ok.any() else QcFlag.NO_QC
    return ParamRtqc(levels=flags, profile=worst, tests_done=done, tests_failed=failed)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Tests 21 / 22 -- near-surface sampling tests
# ---------------------------------------------------------------------------
#: Test 21 ("near-surface unpumped CTD salinity test") applies when the
#: profile's VERTICAL_SAMPLING_SCHEME declares near-surface sampling.
#: ``add_rtqc_to_profile_file.m:2421`` gates on
#: ``strncmp(vss, 'Near-surface sampling:', 22)``.
VSS_NEAR_SURFACE_PREFIX = "Near-surface sampling:"

#: Test 21 sets PSAL_QC (and DOXY_QC for SBE63 optodes) to '3' on every
#: defined level of such a profile: the CTD pump is off, so the conductivity
#: cell reads unflushed water.
TEST21_PARAMS = ("PSAL", "PSAL2", "PSAL_2", "DOXY", "DOXY2", "DOXY_2")

#: Test 22 ("near-surface mixed air/water test"), NKE branch
#: (``floatDecoderId < 1000``).  Averaged VSS uses a 1 dbar threshold; a
#: 'discrete' VSS uses 0.5 dbar.  PRES <= threshold -> TEMP_QC = '3'.
TEST22_THRESHOLD_AVERAGED_DBAR = 1.0
TEST22_THRESHOLD_DISCRETE_DBAR = 0.5


def is_near_surface_sampling(vss: str | None) -> bool:
    """True when the profile's VSS declares a near-surface sampling sequence.

    Coriolis matches the prefix of the whole VSS string, but a real CTS4 VSS
    begins with ``Primary sampling:`` and carries the near-surface section
    later in the same string, so the prefix is searched anywhere.
    """
    if not vss:
        return False
    return VSS_NEAR_SURFACE_PREFIX in str(vss)


def test21_unpumped_salinity(pres: np.ndarray, values: np.ndarray) -> tuple[np.ndarray, bool]:
    """Test 21: flag every defined level '3' on a near-surface-sampled profile.

    Returns the per-level flags and whether the test failed.
    """
    n = len(values)
    flags = _level_flags(n)
    ok = _valid(values)
    flags[ok] = int(QcFlag.PROBABLY_BAD)
    return flags, bool(ok.any())


def test22_near_surface_air_water(pres: np.ndarray, values: np.ndarray,
                                  vss: str | None) -> tuple[np.ndarray, bool]:
    """Test 22 (NKE branch): TEMP within the top 1 dbar is '3'.

    ``add_rtqc_to_profile_file.m:2561`` -- ``idToFlag = find(profPres <=
    threshold)`` with ``threshold = 0.5`` for a 'discrete' VSS and ``1`` for
    averaged or mixed VSS.  Only TEMP is flagged; PSAL is not touched by this
    test on NKE floats.
    """
    n = len(values)
    flags = _level_flags(n)
    ok = _valid(values) & np.isfinite(pres)
    discrete = bool(vss) and "discrete" in str(vss)
    threshold = (TEST22_THRESHOLD_DISCRETE_DBAR if discrete
                 else TEST22_THRESHOLD_AVERAGED_DBAR)
    hit = ok & (pres <= threshold)
    flags[hit] = int(QcFlag.PROBABLY_BAD)
    return flags, bool(hit.any())


def _apply_extra(r: "ParamRtqc", extra: np.ndarray, hit: bool,
                 test_number: int) -> "ParamRtqc":
    """Merge one more test's per-level verdict into an existing result."""
    levels = _worsen(r.levels, extra)
    done = r.tests_done | {test_number}
    failed = r.tests_failed | ({test_number} if hit else set())
    ok = levels != int(QcFlag.NO_QC)
    worst = QcFlag(int(levels[ok].max())) if ok.any() else QcFlag.NO_QC
    return ParamRtqc(levels=levels, profile=worst, tests_done=done,
                     tests_failed=failed)


def _measured(prof: dict, key: str) -> np.ndarray | None:
    """Return a parameter's samples, or None if the profile has none.

    An absent key, a ``None``, and a zero-length array all mean the same
    thing here: this profile did not measure that parameter.  A profile may
    legitimately carry only ``PRES`` (R_STATION_PARAMETERS_TEMPLATE publishes
    ``["PRES", "", ""]`` rows), so every parameter must tolerate that.
    Treating a zero-length array as data instead crashes the range test,
    which broadcasts ``pres`` against ``values``.
    """
    if key not in prof:
        return None
    raw = prof[key]
    if raw is None:
        return None
    arr = np.asarray(raw, dtype=np.float64)
    if arr.size == 0:
        return None
    return arr


def run_cts4_rtqc(
    profiles: list[dict],
    *,
    park_pres: float | None = None,
    profile_pressure_dbar: float | None = None,
    previous_profile: dict | None = None,
    previous_result: "ProfileRtqc | None" = None,
    enable_medd: bool = True,
) -> list[ProfileRtqc]:
    """Run every supported real-time test on a cycle's profile set.

    ``profiles`` is the same list of dicts handed to the writer: each carries
    ``pres`` plus whichever of ``temp``, ``psal``, ``doxy``, ``temp_doxy``,
    ``c1phase``, ``c2phase``, ``chla``, ``fluorescence``, ``beta``, ``bbp``
    that sensor produced for that profile.  Missing keys are simply absent --
    a profile never gains a parameter it did not measure.

    ``park_pres`` feeds BBP test 62.5 (parking hook).  When it is unknown the
    sub-test is skipped, per the manual's abort rule, rather than guessed.

    Tests run in the order the DOXY manual §2.2.3 prescribes: the common tests
    first, then the BGC-specific ones.  The merge is worst-flag-wins, so the
    order cannot lower a flag (BBP manual §2.6).
    """
    results: list[ProfileRtqc] = []
    for prof in profiles:
        pres = np.asarray(prof.get("pres", []), dtype=np.float64)
        n = pres.size
        res = ProfileRtqc()
        if n == 0:
            results.append(res)
            continue

        ascending = str(prof.get("direction", "A")).upper().startswith("A")

        # --- CTD -------------------------------------------------------
        vss = prof.get("vss")
        near_surface = is_near_surface_sampling(vss)

        # PRES is a measured parameter in its own right: it carries test 6
        # (global range, including the near-surface negative-pressure bands)
        # and test 8 (pressure increasing).  _run_ctd_param applies test 8
        # only when name == "PRES", so omitting PRES from this loop would
        # mean test 8 never ran at all.
        res.params["PRES"] = _run_ctd_param("PRES", pres, pres)

        for key, name in (("temp", "TEMP"), ("psal", "PSAL")):
            values = _measured(prof, key)
            if values is None or values.size != n:
                continue
            r = _run_ctd_param(name, pres, values)
            if near_surface:
                # Test 21 applies to PSAL; test 22 applies to TEMP.  Both
                # produce '3', and _worsen means neither can lower a '4'
                # already assigned by tests 6-13.
                if name in TEST21_PARAMS:
                    extra, hit = test21_unpumped_salinity(pres, values)
                    r = _apply_extra(r, extra, hit, 21)
                if name == "TEMP":
                    extra, hit = test22_near_surface_air_water(pres, values, vss)
                    r = _apply_extra(r, extra, hit, 22)
            res.params[name] = r

        pres_qc = (res.params["PRES"].levels if "PRES" in res.params else None)
        temp_qc = (res.params["TEMP"].levels if "TEMP" in res.params else None)
        psal_qc = (res.params["PSAL"].levels if "PSAL" in res.params else None)

        # --- TEST 19: deepest pressure --------------------------------
        # QC Manual v3.9 test 19.  Needs CONFIG_ProfilePressure_dbar; when it
        # is unknown the test aborts rather than inventing a limit.  Coriolis
        # skips the profile's near-surface rows (test19 excludes them), which
        # is why the near-surface profile is left alone.
        if profile_pressure_dbar is not None and not near_surface:
            t19 = deepest_pressure_test(pres, profile_pressure_dbar)
            if t19.n_flagged:
                for name in ("PRES", "TEMP", "PSAL"):
                    if name in res.params:
                        res.params[name] = _apply_extra(
                            res.params[name], t19.per_level, True, 19)
            else:
                for name in ("PRES", "TEMP", "PSAL"):
                    if name in res.params:
                        res.params[name].tests_done.add(19)

        # --- TEST 14: density inversion -------------------------------
        # QC Manual v3.9 test 14: sigma inversion >= 0.03 kg/m3 at the
        # mid-point reference, checked in both directions -> '4' on TEMP and
        # PSAL.  Skipped on a near-surface profile exactly as Coriolis does
        # (its test14 guard is `~strncmp(vss, 'Near-surface sampling:')`).
        temp_v = _measured(prof, "temp")
        psal_v = _measured(prof, "psal")
        if (temp_v is not None and psal_v is not None
                and temp_v.size == n and psal_v.size == n
                and not near_surface
                and prof.get("latitude") is not None
                and prof.get("longitude") is not None):
            t_out, s_out = density_inversion_test(
                pres=pres, temp=temp_v, psal=psal_v,
                lat=float(prof["latitude"]), lon=float(prof["longitude"]),
                pres_qc=pres_qc, temp_qc=temp_qc, psal_qc=psal_qc)
            res.params["TEMP"] = _apply_extra(
                res.params["TEMP"], t_out.per_level, bool(t_out.n_flagged), 14)
            res.params["PSAL"] = _apply_extra(
                res.params["PSAL"], s_out.per_level, bool(s_out.n_flagged), 14)

        # --- TEST 25: MEDD (median with a distance) ---------------------
        # QC Manual v3.9 replaces the obsolete gradient test (11) with MEDD in
        # the application order, and the INCOIS QCP$ masks on 2902093 R
        # profiles (prof0 and prof1, 9/9 cycles) carry bit 25 set.  BR files
        # do not: their BGC profiles carry no MEDD bit.  MEDD judges TEMP and
        # PSAL only, and flags '4'.
        if (enable_medd and temp_v is not None and psal_v is not None
                and temp_v.size == n and psal_v.size == n):
            medd_t, medd_s, medd_ran = medd_test(
                pres, temp_v, psal_v, None,
                float(prof["latitude"]) if prof.get("latitude") is not None else 0.0)
            # Coriolis discards MEDD's salinity output: it captures only
            # ``tempSpike`` from QTRT_spike_check_MEDD_main and applies that
            # alone (add_rtqc_to_profile_file.m:3636-3645).  PSAL is passed
            # in as an input -- it sets the temperature bounds -- but is
            # never itself flagged by this test.  The INCOIS QCP$/QCF$ masks
            # on 2902093 confirm it: MEDD ran on all 9 R cycles and failed
            # on none.
            if medd_ran:
                if "TEMP" in res.params:
                    extra = np.where(medd_t, int(QcFlag.BAD),
                                     int(QcFlag.NO_QC)).astype(np.int8)
                    res.params["TEMP"] = _apply_extra(
                        res.params["TEMP"], extra, bool(medd_t.any()), 25)
                if "PSAL" in res.params:
                    res.params["PSAL"].tests_done.add(25)
            else:
                for name in ("TEMP", "PSAL"):
                    if name in res.params:
                        res.params[name].tests_done.add(25)

        # --- raw IB-Argo channels (test 13 only) -----------------------
        for key, name in (("c1phase", "C1PHASE_DOXY"), ("c2phase", "C2PHASE_DOXY"),
                          ("fluorescence", "FLUORESCENCE_CHLA"),
                          ("beta", "BETA_BACKSCATTERING700")):
            values = _measured(prof, key)
            if values is None or values.size != n:
                continue
            res.params[name] = _run_raw_channel(name, pres, values)

        # --- TEMP_DOXY -------------------------------------------------
        temp_doxy = _measured(prof, "temp_doxy")
        if temp_doxy is not None and temp_doxy.size == n:
            res.params["TEMP_DOXY"] = _run_doxy_like(
                "TEMP_DOXY", pres, temp_doxy, is_doxy=False)

        # --- DOXY (test 57) --------------------------------------------
        doxy = _measured(prof, "doxy")
        if doxy is not None and doxy.size == n:
            res.params["DOXY"] = _run_doxy_like(
                "DOXY", pres, doxy,
                is_doxy=True, temp_qc=temp_qc, pres_qc=pres_qc, psal_qc=psal_qc)

        # --- CHLA_FLUORESCENCE then CHLA (test 63) ---------------------
        chla_fluo = _measured(prof, "chla_fluorescence")
        if chla_fluo is not None and chla_fluo.size == n:
            res.params["CHLA_FLUORESCENCE"] = _run_chla_fluorescence(
                pres, chla_fluo)
        chla = _measured(prof, "chla")
        if chla is not None and chla.size == n:
            fluo_qc = (res.params["CHLA_FLUORESCENCE"].levels
                       if "CHLA_FLUORESCENCE" in res.params
                       else (res.params["FLUORESCENCE_CHLA"].levels
                             if "FLUORESCENCE_CHLA" in res.params else None))
            res.params["CHLA"] = _run_chla(
                pres, chla, fluorescence_qc=fluo_qc)

        # --- BBP700 (test 62) ------------------------------------------
        bbp = _measured(prof, "bbp")
        if bbp is not None and bbp.size == n:
            beta_qc = (res.params["BETA_BACKSCATTERING700"].levels
                       if "BETA_BACKSCATTERING700" in res.params else None)
            res.params["BBP700"] = _run_bbp(
                pres, bbp,
                beta_qc=beta_qc, park_pres=park_pres, ascending=ascending)

        # --- TEST 16 / 18: cross-cycle CTD tests -----------------------
        # QC Manual v3.9 tests 16 and 18 compare a profile against the
        # previous good one.  Both are DISABLED in the current Coriolis
        # driver (testFlagList {0}, "designed for fixed-pressure floats, not
        # for Iridium floats whose mission can change at sea") but INCOIS
        # demonstrably runs both.  They are applied here because the input
        # genuinely exists in the CTS4 telemetry stream; when the previous
        # cycle is absent they abort rather than invent a comparison.
        if previous_profile is not None:
            _apply_cross_cycle_tests(
                prof, res, previous_profile, previous_result)

        for r in res.params.values():
            res.tests_done |= r.tests_done
            res.tests_failed |= r.tests_failed
        results.append(res)
    return results


def _apply_cross_cycle_tests(prof: dict, res: "ProfileRtqc",
                             previous_profile: dict,
                             previous_result: "ProfileRtqc | None") -> None:
    """Apply tests 5, 16 and 18 against the previous cycle.

    Test 5 (impossible speed) writes POSITION_QC, which is a profile scalar
    rather than a per-level array, so it is recorded on the profile result
    and published separately.  Tests 16 and 18 are per-level / whole-profile
    CTD tests and merge into TEMP and PSAL like the others.
    """
    pres = np.asarray(prof.get("pres", []), dtype=np.float64)
    n = pres.size
    if n == 0:
        return
    p_pres = np.asarray(previous_profile.get("pres", []), dtype=np.float64)
    if p_pres.size == 0:
        return

    # ---- TEST 5: impossible speed -----------------------------------
    speed_qc, ran = impossible_speed_test(
        juld=prof.get("juld"), latitude=prof.get("latitude"),
        longitude=prof.get("longitude"),
        previous_juld=previous_profile.get("juld"),
        previous_latitude=previous_profile.get("latitude"),
        previous_longitude=previous_profile.get("longitude"))
    if ran:
        # Record the test on the profile (it judges the position, so there is
        # no per-level array) and on every measured parameter, so a reader
        # inspecting one parameter's tests_done sees the whole battery that
        # actually ran on that profile.
        res.tests_done.add(5)
        failed5 = speed_qc is not None and bytes(speed_qc) == b"4"
        if failed5:
            res.tests_failed.add(5)
            res.position_qc = b"4"
        for r in res.params.values():
            r.tests_done.add(5)
            if failed5:
                r.tests_failed.add(5)

    # ---- TEST 16: gross sensor drift --------------------------------
    for key, name, thr in (("temp", "TEMP", 1.0), ("psal", "PSAL", 0.5)):
        cur = _measured(prof, key)
        prv = _measured(previous_profile, key)
        if cur is None or prv is None or cur.size != n:
            continue
        if name not in res.params:
            continue
        drift, ran16 = gross_sensor_drift_test(
            pres=pres, values=cur, previous_pres=p_pres,
            previous_values=prv, threshold=thr)
        if not ran16 or drift is None:
            continue
        extra = np.asarray(drift, dtype=np.int8)
        hit = bool(np.any(extra == int(QcFlag.PROBABLY_BAD)))
        res.params[name] = _apply_extra(res.params[name], extra, hit, 16)

    # ---- TEST 18: frozen profile ------------------------------------
    cur_t = _measured(prof, "temp")
    cur_s = _measured(prof, "psal")
    prv_t = _measured(previous_profile, "temp")
    prv_s = _measured(previous_profile, "psal")
    if (cur_t is not None and cur_s is not None
            and prv_t is not None and prv_s is not None
            and cur_t.size == n and cur_s.size == n):
        frozen, ran18 = frozen_profile_test(
            pres=pres, temp=cur_t, psal=cur_s,
            previous_pres=p_pres, previous_temp=prv_t, previous_psal=prv_s)
        if ran18:
            for name in ("TEMP", "PSAL"):
                if name not in res.params:
                    continue
                if frozen:
                    res.params[name] = _apply_extra(
                        res.params[name],
                        np.where(res.params[name].levels != int(QcFlag.NO_QC),
                                 int(QcFlag.BAD), int(QcFlag.NO_QC)).astype(np.int8),
                        True, 18)
                else:
                    res.params[name].tests_done.add(18)
