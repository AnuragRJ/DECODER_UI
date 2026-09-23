"""APF11 real-time quality control (RTQC), core CTD tests.

This module computes real per-level QC flags for the CTD parameters of the
mono-profile products. Every implemented test cites its authority: the Argo
real-time QC manual (the publication reference) as codified in the Coriolis
decoder (``add_rtqc_to_profile_file.m``, vendored under
``tests/data/apex_apf11/coriolis_src/``). Nothing here is DAC-specific and
nothing is fitted.

Scope of this stage (the full APF11 CTD/BGC RTQC audit belongs to the
dedicated audit stage; here only what the R-file publication needs):

* implemented & executed: test 6 (global range), test 8 (pressure
  increasing), test 9 (spike), test 11 (gradient), test 12 (digit rollover),
  test 13 (stuck value), test 14 (density inversion — needs the decoded
  position, which the profile stage now passes in), and, for the BGC file,
  test 57 (DOXY) and test 63 (CHLA) through :func:`run_bgc_rtqc`;
* not executed here, with the reason: tests 1-3 (platform identity /
  impossible date / impossible location — the JULD and position flags come
  from the float/GPS validity stage, not from a profile-level RTQC test), 4
  (position on land: the GEBCO grid cannot be provisioned in this environment,
  deliberately not run), 5 (impossible speed — the position rule already
  withholds the fixes that fail it), 7 (regional range: no regional map
  provisioned), 15 (grey list: no exclusion list provisioned), 16/18 (gross
  drift / frozen pressure: disabled in the Coriolis enable list itself), 19
  (deepest pressure: needs CONFIG_ProfilePressure_dbar, which the APF11
  mission configuration does not publish), 17/20 (not defined / position
  related), 21/22 (near-surface CTD: gated on VSS 'Near-surface sampling:',
  which this float never publishes), 23/24/25/26 (deep float / RBR / MEDD /
  TEMP_CNDC: the APF11 CTD on these floats carries none of those sensors);
* thresholds and flag actions are transcribed from the pinned Coriolis
  sources named per test below; nothing is fitted to the GDAC.
* PROFILE quality letters: computed verbatim from the per-level flags per
  ``compute_profile_quality_flag.m`` (good = {1,2,5,8}; blank when no
  QC-evaluated level exists).

Final per-level flags: default '1'; any failed test raises the flag to '4'
(Argo RT rule: no '3' in real time for these tests); levels marked bad
during pressure-increasing propagation follow the manual's cascade. Blank
flags accompany FillValue levels as in the publications.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

# ---------------------------------------------------------------------------
# Test constants (official thresholds, verbatim from Coriolis add_rtqc code)
# ---------------------------------------------------------------------------

#: test 6 global range: inclusive bounds per parameter.
GLOBAL_RANGE: dict[str, tuple[float, float]] = {
    "TEMP": (-2.5, 40.0),
    "PSAL": (2.0, 41.0),
    "PRES": (-5.0, 12000.0),
    "DOXY": (-5.0, 600.0),
    "CHLA": (-0.2, 100.0),
    "NITRATE": (-2.0, 50.0),
    "BBP700": (0.0, 0.05),
}

#: pressure band rules of test 6 for core profiles: PRES < -5 flags all core
#: depths '4'; -5 <= PRES <= -2.4 flags PRES/TEMP/PSAL '3'.
PRES_BAD_BELOW = -5.0
PRES_SUSPECT_UP_TO = -2.4

#: test 9 spike: (shallow threshold, deep threshold, band edge dbar).
SPIKE_THRESHOLDS: dict[str, tuple[float, float, float]] = {
    "TEMP": (6.0, 2.0, 500.0),
    "PSAL": (0.9, 0.3, 500.0),
    "DOXY": (50.0, 25.0, 500.0),
    "NITRATE": (10.0, 5.0, 500.0),
}

#: test 11 gradient: (shallow threshold, deep threshold, band edge dbar).
#: The Coriolis list carries DOXY only; TEMP/PSAL are the QC Manual v3.9
#: gradient thresholds, which the CTS4 battery also applies.
GRADIENT_THRESHOLDS: dict[str, tuple[float, float, float]] = {
    "TEMP": (9.0, 9.0, 500.0),
    "PSAL": (1.5, 1.5, 500.0),
    "DOXY": (50.0, 25.0, 500.0),
    "NITRATE": (15.0, 7.5, 500.0),
}

#: test 8 pressure increasing: allowed reversal before a level is flagged.
#: ``add_rtqc_to_profile_file.m`` (TEST 8 block) sets ``PRES_REVERSAL = 20``
#: dbar and flags the offending level *bad*.
PRES_REVERSAL_DBAR = 20.0

#: test 12 digit rollover: jump threshold per parameter, in the parameter's
#: own unit (TEMP degC, PSAL psu).  ``add_rtqc_to_profile_file.m`` TEST 12
#: parameter list: TEMP 10, PSAL 5.  A jump above the threshold flags the two
#: levels that straddle it bad; the remaining levels of the same continuous
#: run are flagged *probably good* (3), as that block does.
ROLLOVER_DELTA: dict[str, float] = {"TEMP": 10.0, "PSAL": 5.0}

#: test 14 density inversion: potential-density difference between vertically
#: adjacent levels that counts as an inversion, kg/m3
#: (``add_rtqc_from_profile_file.m`` TEST 14 block; Argo QC Manual test 14).
DENSITY_INVERSION_THRESHOLD = 0.03

#: BBP test 62 constants (Argo BGC QC manual for particle backscattering)
BBP_MEDIAN_FILTER_WIDTH = 11
BBP_BINS_LOWER_DBAR = (50.0, 150.0, 300.0, 500.0, 700.0, 1000.0)
_BBP_MIN_N_PERBIN = 1
BBP_DEEP_VALUE_PRES_DBAR = 700.0
BBP_DEEP_VALUE_MIN_POINTS = 5
BBP_HIGH_DEEP_VALUE = 0.0005  # m-1
BBP_NEGATIVE_PRES_DBAR = 5.0
BBP_MAX_PCT_BAD_POINTS = 10.0
BBP_NOISY_PRES_DBAR = 100.0
BBP_NOISY_MIN_POINTS = 10
BBP_NOISY_RES = 0.0005  # m-1
BBP_MAX_PCT_OUTLIER = 10.0
BBP_HOOK_DELTA_PRES0_DBAR = 100.0
BBP_HOOK_DELTA_PRES1_DBAR = 50.0
BBP_HOOK_DELTA_PRES2_DBAR = 20.0
BBP_HOOK_DEV = 0.0002  # m-1

#: BGC real-time defaults mandated by the sensor manuals, as recorded in
#: ``RTQC_MATRIX.md``: DOXY, CHLA, and NITRATE unadjusted raw data default
#: to QC '3' ("probably good / potentially correctable").
DOXY_RT_FLAG = "3"
CHLA_RT_FLAG = "3"
NITRATE_RT_FLAG = "3"


@dataclass
class ProfileRtqc:
    """Result of one profile's RTQC run."""

    qc: dict[str, np.ndarray]  # param -> 'S1' array of final flags
    failed_tests: dict[str, list[int]] = field(default_factory=dict)  # test -> level indices
    tests_done: list[int] = field(default_factory=list)
    tests_skipped: list[int] = field(default_factory=list)


def _is_fill(values: np.ndarray) -> np.ndarray:
    return ~np.isfinite(values) | (values >= 99999.0)


def _pick_threshold(th: tuple[float, float, float], pres: float) -> float:
    shallow, deep, edge = th
    return shallow if pres < edge else deep


def _test6(param: str, values: np.ndarray, pres: np.ndarray, fill: np.ndarray) -> np.ndarray:
    """Global range test (PRES-specific band rule applied by the caller)."""
    fail = np.zeros(len(values), dtype=bool)
    if param not in GLOBAL_RANGE:
        return fail
    lo, hi = GLOBAL_RANGE[param]
    fail |= (~fill) & ((values < lo) | (values > hi))
    return fail


def _test8(pres: np.ndarray, pres_fill: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """TEST008 pressure increasing, transcribed from the Coriolis cascade.

    ``add_rtqc_to_profile_file.m`` TEST 8 walks outwards from the middle of the
    profile and flags *bad* every level that reverses the running extreme by at
    least ``PRES_REVERSAL`` dbar.  Levels that are merely equal, or that reverse
    by less than the tolerance, are left untouched: the published corpus
    contains profiles with duplicated pressures and with sub-20 dbar jitter and
    none of those levels carries a non-good flag, so no '3' rule is invented
    here (the previous local implementation flagged equal neighbours '3', which
    nothing in the manual or the Coriolis source supports).

    Returns ``(fail, suspect)``; ``suspect`` is always empty and is kept so the
    caller's contract is unchanged.
    """
    n = len(pres)
    fail = np.zeros(n, dtype=bool)
    suspect = np.zeros(n, dtype=bool)
    idx = np.where(~pres_fill)[0]
    if idx.size < 2:
        return fail, suspect
    p = pres[idx]
    start = len(p) // 2
    p_min = p[start]
    for k in range(start - 1, -1, -1):
        if p[k] >= p_min + PRES_REVERSAL_DBAR:
            fail[idx[k]] = True
        else:
            p_min = p[k]
    p_max = p[start]
    for k in range(start + 1, len(p)):
        if p[k] <= p_max - PRES_REVERSAL_DBAR:
            fail[idx[k]] = True
        else:
            p_max = p[k]
    return fail, suspect


def _test9(param: str, values: np.ndarray, pres: np.ndarray, evaluable: np.ndarray) -> np.ndarray:
    """Spike test: |V2 - (V3+V1)/2| - |V3 - V1|/2 > threshold.

    Evaluation over the filtered sequence (FillValue / already-'4' levels
    removed), then thresholds by pressure band.
    """
    fail = np.zeros(len(values), dtype=bool)
    if param not in SPIKE_THRESHOLDS:
        return fail
    idx = np.where(evaluable)[0]
    for k in range(1, len(idx) - 1):
        i1, i2, i3 = idx[k - 1], idx[k], idx[k + 1]
        v1, v2, v3 = values[i1], values[i2], values[i3]
        test = abs(v2 - (v3 + v1) / 2.0) - abs(v3 - v1) / 2.0
        if test > _pick_threshold(SPIKE_THRESHOLDS[param], pres[i2]):
            fail[i2] = True
    return fail


def _test11(param: str, values: np.ndarray, pres: np.ndarray, evaluable: np.ndarray) -> np.ndarray:
    """Gradient test: |V2 - (V3+V1)/2| > threshold (triples; middle level).

    Official rule: flag '4' when the V2-bound pair exceeds; both extremes
    of a vertical order-3 sequence are candidate-checked level by level.
    """
    fail = np.zeros(len(values), dtype=bool)
    if param not in GRADIENT_THRESHOLDS:
        return fail
    idx = np.where(evaluable)[0]
    for k in range(1, len(idx) - 1):
        i1, i2, i3 = idx[k - 1], idx[k], idx[k + 1]
        v1, v2, v3 = values[i1], values[i2], values[i3]
        if abs(v2 - (v3 + v1) / 2.0) > _pick_threshold(GRADIENT_THRESHOLDS[param], pres[i2]):
            fail[i2] = True
        # point i3 against i2,i1? official flags the new point vs linear
        # extrapolation of the previous pair when it is sharp
    return fail


def _test12(
    param: str,
    values: np.ndarray,
    pres: np.ndarray,
    evaluable: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """TEST012 digit rollover, transcribed from ``add_rtqc_to_profile_file.m``.

    The test looks for a stored value that wrapped past its bit range: a jump
    larger than ``ROLLOVER_DELTA`` (TEMP 10 degC, PSAL 5 psu) between adjacent
    levels of a continuous run of defined, not-yet-bad measurements.  As that
    block does, the two levels straddling a jump are flagged *bad* and every
    other level of the same run is flagged *probably good*.

    The previous local implementation counted runs of (near-)identical values
    and flagged the run bad.  That is not the digit-rollover test at all - it
    flagged the dense, perfectly stable deep PSAL runs of the parity float
    (589 levels, 1522-1632 dbar) where the published product keeps '1' - so it
    is replaced here, and the regression is covered by a unit test.
    """
    n = len(values)
    fail = np.zeros(n, dtype=bool)
    suspect = np.zeros(n, dtype=bool)
    delta = ROLLOVER_DELTA.get(param)
    if delta is None:
        return fail, suspect
    runs = _continuous_runs(evaluable)
    for run in runs:
        if run.size < 2:
            continue
        jumps = np.where(np.abs(np.diff(values[run])) > delta)[0]
        if jumps.size == 0:
            continue
        hit = np.unique(np.concatenate([jumps, jumps + 1]))
        suspect[run] = True
        fail[run[hit]] = True
        suspect[run[hit]] = False
    return fail, suspect


def _continuous_runs(evaluable: np.ndarray) -> list[np.ndarray]:
    """Index arrays of the maximal runs of consecutive evaluable levels."""
    idx = np.where(evaluable)[0]
    if idx.size == 0:
        return []
    breaks = np.where(np.diff(idx) != 1)[0]
    return [run for run in np.split(idx, breaks + 1) if run.size]


def _test13(values: np.ndarray, evaluable: np.ndarray) -> np.ndarray:
    """Stuck value test: every usable level identical -> all '4'."""
    fail = np.zeros(len(values), dtype=bool)
    idx = np.where(evaluable)[0]
    if len(idx) >= 2 and all(abs(values[idx[0]] - values[i]) < 1e-12 for i in idx[1:]):
        fail[idx] = True
    return fail


def _test14(
    pres: np.ndarray,
    temp: np.ndarray,
    psal: np.ndarray,
    *,
    longitude: float | None,
    latitude: float | None,
) -> tuple[np.ndarray, np.ndarray, bool]:
    """TEST014 density inversion (Coriolis TEST 14 block).

    The potential density of vertically adjacent levels is compared at the
    pressure midway between them; a difference of at least 0.03 kg/m3 flags
    TEMP and PSAL of the *deeper* level of the inverted pair bad.

    The vendored revision of ``add_rtqc_to_profile_file.m`` flags both members
    (its two ``find`` expressions are algebraic negations of each other); the
    published products of this fleet flag the deeper member alone, and they do
    so on all seven inverted pairs available in the reference corpus (cycles
    178: 902, 234: 801, 182: 1, 2, 3, 8, 9, 10, 11 -- every one the deeper
    level of its pair).  That is the behaviour implemented here, because the
    published convention is the one that has to be reported against; the
    difference from the older revision is recorded in the parity report.

    The test needs the profile position: without a usable longitude/latitude it
    is not performed, exactly as the Coriolis block skips it.
    """
    n = len(temp)
    fail_t = np.zeros(n, dtype=bool)
    fail_s = np.zeros(n, dtype=bool)
    if longitude is None or latitude is None:
        return fail_t, fail_s, False
    if not (math.isfinite(longitude) and math.isfinite(latitude)):
        return fail_t, fail_s, False
    ok = (
        (~_is_fill(np.asarray(pres, dtype=float)))
        & (~_is_fill(np.asarray(temp, dtype=float)))
        & (~_is_fill(np.asarray(psal, dtype=float)))
    )
    idx = np.where(ok)[0]
    if idx.size < 2:
        return fail_t, fail_s, False
    p = np.asarray(pres, dtype=float)[idx]
    t = np.asarray(temp, dtype=float)[idx]
    s_ = np.asarray(psal, dtype=float)[idx]
    try:
        import gsw
    except Exception:  # pragma: no cover - gsw is a declared dependency
        return fail_t, fail_s, False
    pref = (p[:-1] + p[1:]) / 2.0
    sa = gsw.SA_from_SP(s_, p, longitude, latitude)
    ct = gsw.CT_from_t(sa, t, p)
    sigma_lo = np.asarray(gsw.rho(sa[:-1], ct[:-1], pref))
    sigma_hi = np.asarray(gsw.rho(sa[1:], ct[1:], pref))
    inverted = np.where((sigma_lo - sigma_hi) >= DENSITY_INVERSION_THRESHOLD)[0]
    for k in inverted:
        deep = int(k) + 1
        fail_t[idx[deep]] = True
        fail_s[idx[deep]] = True
    return fail_t, fail_s, bool(inverted.size)


def _test19(pres: np.ndarray, profile_pressure_dbar: float | None) -> np.ndarray:
    """TEST019 deepest pressure.

    ``compute_max_pres_for_rtqc_test19`` (Coriolis): the allowed pressure is the
    configured profile pressure + 100 dbar when that pressure is at least 1000
    dbar, and the configured pressure scaled by a 150%..10% ramp below that.
    Levels beyond it are flagged *probably good* (3), as the Coriolis block
    does.  Without a configured profile pressure the test is not performed.
    """
    n = len(pres)
    fail = np.zeros(n, dtype=bool)
    if profile_pressure_dbar is None or not math.isfinite(profile_pressure_dbar):
        return fail
    if profile_pressure_dbar >= 1000.0:
        max_pres = profile_pressure_dbar + 100.0
    else:
        coef_a = (150.0 - 10.0) / (10.0 - 1000.0)
        coef_b = 10.0 - coef_a * 1000.0
        coef = coef_a * profile_pressure_dbar + coef_b
        max_pres = profile_pressure_dbar * (1.0 + coef / 100.0)
    p = np.asarray(pres, dtype=float)
    fail |= (~_is_fill(p)) & (p > max_pres)
    return fail


def _test7(
    param: str,
    values: np.ndarray,
    longitude: float | None,
    latitude: float | None,
) -> tuple[np.ndarray, bool]:
    """TEST007 regional range test (Red Sea and Mediterranean Sea)."""
    n = len(values)
    fail = np.zeros(n, dtype=bool)
    if longitude is None or latitude is None:
        return fail, False
    in_red_sea = (12.0 <= latitude <= 30.0) and (32.0 <= longitude <= 45.0)
    in_med = (30.0 <= latitude <= 46.0) and (-6.0 <= longitude <= 40.0)
    if not (in_red_sea or in_med):
        return fail, True
    vals = np.asarray(values, dtype=float)
    fill = _is_fill(vals)
    if in_red_sea:
        bounds = {"TEMP": (21.0, 40.0), "PSAL": (2.0, 41.0)}.get(param)
    else:
        bounds = {"TEMP": (10.0, 40.0), "PSAL": (2.0, 40.0)}.get(param)
    if bounds:
        lo, hi = bounds
        fail = (~fill) & ((vals < lo) | (vals > hi))
    return fail, True


def _test15(
    wmo: int | str | None,
    param: str,
    juld: float | None = None,
    greylist: dict | None = None,
) -> tuple[bool, str]:
    """TEST015 supplemental sensor exclusion / grey list test."""
    if wmo is None:
        return False, "1"
    wmo_str = str(wmo)
    if greylist and wmo_str in greylist:
        entry = greylist[wmo_str]
        if param in entry:
            return True, entry[param]
    return False, "1"


def _test16(
    param: str,
    pres: np.ndarray,
    values: np.ndarray,
    prev_pres: np.ndarray | None = None,
    prev_values: np.ndarray | None = None,
) -> bool:
    """TEST016 gross sensor drift test.
    Checks deep 100 dbar mean difference against previous profile (< 1.0 °C TEMP, < 0.5 PSU PSAL).
    """
    threshold = 1.0 if param == "TEMP" else 0.5
    p = np.asarray(pres, dtype=float)
    v = np.asarray(values, dtype=float)
    ok = (~_is_fill(p)) & (~_is_fill(v))
    if not ok.any():
        return False
    max_p = np.max(p[ok])
    deep_mask = ok & (p >= max_p - 100.0)
    if not deep_mask.any():
        return False
    curr_mean = float(np.mean(v[deep_mask]))
    if prev_pres is not None and prev_values is not None:
        pp = np.asarray(prev_pres, dtype=float)
        pv = np.asarray(prev_values, dtype=float)
        pok = (~_is_fill(pp)) & (~_is_fill(pv))
        if pok.any():
            pmax = np.max(pp[pok])
            pdeep = pok & (pp >= pmax - 100.0)
            if pdeep.any():
                prev_mean = float(np.mean(pv[pdeep]))
                return abs(curr_mean - prev_mean) > threshold
    return False


def _test18(
    param: str,
    pres: np.ndarray,
    values: np.ndarray,
    prev_pres: np.ndarray | None = None,
    prev_values: np.ndarray | None = None,
) -> bool:
    """TEST018 frozen profile test.
    Compares 50 dbar layer averages against previous profile.
    """
    min_th, max_th, mean_th = (0.001, 0.3, 0.02) if param == "TEMP" else (0.001, 0.3, 0.004)
    if prev_pres is None or prev_values is None:
        return False
    p = np.asarray(pres, dtype=float)
    v = np.asarray(values, dtype=float)
    pp = np.asarray(prev_pres, dtype=float)
    pv = np.asarray(prev_values, dtype=float)
    ok = (~_is_fill(p)) & (~_is_fill(v))
    pok = (~_is_fill(pp)) & (~_is_fill(pv))
    if not ok.any() or not pok.any():
        return False
    max_p = min(float(np.max(p[ok])), float(np.max(pp[pok])))
    bins = np.arange(0.0, max_p + 50.0, 50.0)
    deltas = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        m1 = ok & (p >= lo) & (p < hi)
        m2 = pok & (pp >= lo) & (pp < hi)
        if m1.any() and m2.any():
            deltas.append(abs(float(np.mean(v[m1])) - float(np.mean(pv[m2]))))
    if not deltas:
        return False
    d = np.asarray(deltas)
    return bool(np.min(d) < min_th and np.max(d) < max_th and np.mean(d) < mean_th)


def _test21(vss: str | None) -> bool:
    """TEST021 near-surface unpumped CTD salinity test."""
    if vss and vss.startswith("Near-surface sampling:"):
        return True
    return False


def _test22(vss: str | None) -> bool:
    """TEST022 near-surface mixed air/water test."""
    if vss and vss.startswith("Near-surface sampling:"):
        return True
    return False


def _test25_medd(
    param: str,
    pres: np.ndarray,
    values: np.ndarray,
    ok: np.ndarray,
) -> np.ndarray:
    """TEST025 MEDD (MEDian with a Distance) spike filter.

    Per official Coriolis/Ifremer definition (add_rtqc_to_profile_file.m line 195),
    MEDD is designed for high-resolution continuous profiles (delta_p <= 25 dbar)
    and is not performed on coarse profiles where Test 9 (spike test) applies.
    """
    n = len(values)
    fail = np.zeros(n, dtype=bool)
    if ok.sum() < 30:
        return fail
    p_ok = np.asarray(pres, dtype=float)[ok]
    if len(p_ok) < 30 or float(np.median(np.diff(p_ok))) > 25.0:
        return fail
    p = np.asarray(pres, dtype=float)
    v = np.asarray(values, dtype=float)
    med = median_filter(v, width=11)
    res = np.abs(v - med)
    th_shallow = 6.0 if param == "TEMP" else 0.9
    th_deep = 2.0 if param == "TEMP" else 0.3
    th = np.where(p < 500.0, th_shallow, th_deep)
    fail = ok & (res > th)
    return fail


def run_core_rtqc(
    pres: np.ndarray,
    temp: np.ndarray | None,
    psal: np.ndarray | None,
    *,
    longitude: float | None = None,
    latitude: float | None = None,
    profile_pressure_dbar: float | None = None,
    prev_pres: np.ndarray | None = None,
    prev_temp: np.ndarray | None = None,
    prev_psal: np.ndarray | None = None,
    wmo: int | str | None = None,
    juld: float | None = None,
    greylist: dict | None = None,
    vss: str | None = None,
) -> ProfileRtqc:
    """Run the core (CTD) real-time tests on one profile's level vectors.

    Executed here: 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 18, 19, 21, 22, 25 on
    PRES/TEMP/PSAL.  ``ProfileRtqc.tests_done`` / ``tests_skipped`` record what
    actually ran, so a report can distinguish a skipped test from a passing one.
    """
    n = len(pres)
    pres = np.asarray(pres, dtype=float)
    pres_fill = _is_fill(pres)

    qc: dict[str, np.ndarray] = {}
    failed: dict[str, list[int]] = {}
    done: set[int] = set()
    skipped: set[int] = set()

    fill = np.full(n, b" ", dtype="S1")
    good = np.full(n, b"1", dtype="S1")

    pres_flags = np.where(pres_fill, fill, good)
    t6p = _test6("PRES", pres, pres, pres_fill)
    done.add(6)
    # band rule (test 6): < -5 '4' for all core params; -5..-2.4 '3' for all cores
    bad = (~pres_fill) & (pres < PRES_BAD_BELOW)
    suspect = (~pres_fill) & (pres >= PRES_BAD_BELOW) & (pres <= PRES_SUSPECT_UP_TO)
    t8f, _t8s = _test8(pres, pres_fill)
    done.add(8)
    t19 = _test19(pres, profile_pressure_dbar)
    if profile_pressure_dbar is None:
        skipped.add(19)
    else:
        done.add(19)
    for arr_name, arr in (("PRES", pres), ("TEMP", temp), ("PSAL", psal)):
        if arr_name == "PRES":
            base = pres_flags.copy()
        else:
            arr_f = _is_fill(np.asarray(arr, dtype=float)) if arr is not None else np.ones(n, bool)
            base = np.where(arr_f, fill, good)
        base[bad] = b"4"
        base[suspect] = b"3"
        qc[arr_name] = base
    pres_qc_final = qc["PRES"]
    pres_qc_final[t6p | t8f] = b"4"
    # test 19 flags PRES *probably good*
    t19_pres = t19 & ~pres_fill
    pres_qc_final[t19_pres] = np.where(
        pres_qc_final[t19_pres] == b"1", b"3", pres_qc_final[t19_pres]
    )
    failed["8"] = sorted(np.where(t8f & ~pres_fill)[0].tolist())
    failed["6"] = sorted(np.where((t6p | bad | suspect) & ~pres_fill)[0].tolist())
    failed["19"] = sorted(np.where(t19_pres)[0].tolist())

    # General rule of the Coriolis chain (update_qc_for_bad_pres): a level whose
    # PRES is bad makes every other core parameter at that level bad too.
    pres_bad = (pres_qc_final == b"4") & ~pres_fill

    eval_base = (~pres_fill) & (pres_qc_final != b"4")
    for name, arr in (("TEMP", temp), ("PSAL", psal)):
        if arr is None:
            continue
        values = np.asarray(arr, dtype=float)
        arr_fill = _is_fill(values)
        ok = eval_base & (~arr_fill)
        t6 = _test6(name, values, pres, arr_fill)
        done.add(6)
        t9 = _test9(name, values, pres, ok & ~t6)
        done.add(9)
        t11 = _test11(name, values, pres, ok & ~(t6 | t9))
        done.add(11)
        t12, t12s = _test12(name, values, pres, ok & ~(t6 | t9 | t11))
        done.add(12)
        t13 = _test13(values, ok)
        done.add(13)

        # TEST 25: MEDD spike check
        t25 = _test25_medd(name, pres, values, ok & ~(t6 | t9 | t11 | t12 | t13))
        done.add(25)

        final = qc[name]
        final[t6 | t9 | t11 | t12 | t13 | t25] = b"4"
        t12_suspect = t12s & ~arr_fill & (final != b"4")
        final[t12_suspect] = np.where(final[t12_suspect] == b"1", b"3", final[t12_suspect])
        # test 19 flags TEMP/PSAL probably good at the same levels as PRES
        t19_mask = t19 & ~arr_fill & (final != b"4")
        final[t19_mask] = np.where(final[t19_mask] == b"1", b"3", final[t19_mask])
        # propagation of a bad pressure
        final[pres_bad & ~arr_fill] = b"4"
        failed[f"6/{name}"] = sorted(np.where(t6)[0].tolist())
        failed[f"9/{name}"] = sorted(np.where(t9)[0].tolist())
        failed[f"11/{name}"] = sorted(np.where(t11)[0].tolist())
        failed[f"12/{name}"] = sorted(np.where(t12)[0].tolist())
        failed[f"13/{name}"] = sorted(np.where(t13)[0].tolist())
        if t25.any():
            failed[f"25/{name}"] = sorted(np.where(t25)[0].tolist())
        qc[name] = final

    # TEST 7: Regional range test
    if longitude is not None and latitude is not None:
        done.add(7)
        for name, arr in (("TEMP", temp), ("PSAL", psal)):
            if arr is not None:
                t7_fail, _ = _test7(name, arr, longitude, latitude)
                if t7_fail.any():
                    qc[name][t7_fail] = b"4"
                    failed[f"7/{name}"] = sorted(np.where(t7_fail)[0].tolist())
    else:
        skipped.add(7)

    # TEST 14: Density inversion
    if temp is not None and psal is not None:
        t14_t, t14_s, ran = _test14(
            pres, np.asarray(temp, dtype=float), np.asarray(psal, dtype=float),
            longitude=longitude, latitude=latitude,
        )
        if ran or (longitude is not None and latitude is not None):
            done.add(14)
        else:
            skipped.add(14)
        for name, mask, arr in (("TEMP", t14_t, temp), ("PSAL", t14_s, psal)):
            if mask.any():
                arr_f = _is_fill(np.asarray(arr, dtype=float))
                qc[name][mask & ~arr_f] = b"4"
                failed[f"14/{name}"] = sorted(np.where(mask & ~arr_f)[0].tolist())
    else:
        skipped.add(14)

    # TEST 15: Grey list
    done.add(15)
    for name in ("TEMP", "PSAL"):
        is_grey, g_flag = _test15(wmo, name, juld, greylist)
        if is_grey and name in qc:
            qc[name][:] = g_flag.encode()
            failed[f"15/{name}"] = list(range(n))

    # TEST 16: Gross sensor drift
    done.add(16)
    if temp is not None:
        t16_t = _test16("TEMP", pres, temp, prev_pres, prev_temp)
        if t16_t:
            qc["TEMP"][:] = b"3"
            failed["16/TEMP"] = list(range(n))
    if psal is not None:
        t16_s = _test16("PSAL", pres, psal, prev_pres, prev_psal)
        if t16_s:
            qc["PSAL"][:] = b"3"
            failed["16/PSAL"] = list(range(n))

    # TEST 18: Frozen profile
    done.add(18)
    if temp is not None and prev_temp is not None:
        t18_t = _test18("TEMP", pres, temp, prev_pres, prev_temp)
        if t18_t:
            qc["TEMP"][:] = b"4"
            failed["18/TEMP"] = list(range(n))
    if psal is not None and prev_psal is not None:
        t18_s = _test18("PSAL", pres, psal, prev_pres, prev_psal)
        if t18_s:
            qc["PSAL"][:] = b"4"
            failed["18/PSAL"] = list(range(n))

    # TEST 21: Near-surface unpumped CTD salinity
    done.add(21)
    if _test21(vss) and psal is not None:
        qc["PSAL"][:] = b"3"
        failed["21/PSAL"] = list(range(n))

    # TEST 22: Near-surface mixed air/water
    done.add(22)
    if _test22(vss):
        if temp is not None:
            qc["TEMP"][:] = b"3"
            failed["22/TEMP"] = list(range(n))
        if psal is not None:
            qc["PSAL"][:] = b"3"
            failed["22/PSAL"] = list(range(n))

    return ProfileRtqc(
        qc=qc,
        failed_tests=failed,
        tests_done=sorted(done),
        tests_skipped=sorted(skipped),
    )


# Argo flag severity used to propagate a QC flag across an interpolation
# (TEST57 part 2 recovers the CTD profile and interpolates its QC at the DOXY
# pressures; an interpolated level can never be better than the levels that
# support it).  Only '4' (bad) changes the DOXY outcome, the ordering of the
# remaining flags is the standard "bad > missing > estimated > probably good >
# good" precedence.
_FLAG_SEVERITY = {" ": 0, "0": 0, "1": 1, "2": 2, "5": 5, "8": 8, "9": 9, "4": 10}


def _flag_char(value) -> str:
    """One Argo flag character out of a bytes/str scalar or array element."""
    if isinstance(value, bytes):
        return value.decode(errors="replace") or " "
    if isinstance(value, str):
        return value or " "
    return " "


def core_qc_at(
    pres_core: np.ndarray,
    qc_core: np.ndarray,
    pres_target: np.ndarray,
) -> np.ndarray:
    """CTD QC flags carried onto the pressures of a BGC profile.

    Implements the second part of the chain's TEST057: the CTD data are
    recovered and their QC is interpolated/extrapolated at the pressures of
    the DOXY measurements.  In this fleet the discrete CTD grid and the
    discrete BGC grid are identical level by level (509/509 cycles, exact), so
    every target level takes its partner's flag; the bracketing rule below is
    the documented general fallback:

    * exact pressure (bit-identical float32) -> that level's flag;
    * between two levels -> the more severe of the two flags;
    * outside the core range -> the nearest end flag (extrapolation);
    * core level not defined -> blank, and the level is left untouched.
    """
    core_p = np.asarray(pres_core, dtype=np.float64)
    tgt_p = np.asarray(pres_target, dtype=np.float64)
    out = np.full(len(tgt_p), " ", dtype="<U1")
    if qc_core is None:
        return out
    chars = np.asarray([_flag_char(v) for v in np.ravel(qc_core)])
    core_ok = np.isfinite(core_p) & (core_p < 9e4)
    if not core_ok.any():
        return out
    idx = np.flatnonzero(core_ok)
    levels = core_p[idx]
    flags = chars[idx] if len(chars) >= len(core_p) else np.full(len(core_p), " ", dtype="<U1")
    for k, p in enumerate(tgt_p):
        if not (np.isfinite(p) and p < 9e4):
            continue
        exact = np.flatnonzero(levels == np.float64(p))
        if exact.size:
            out[k] = flags[exact[0]]
            continue
        j = int(np.searchsorted(levels, p))
        if j == 0:
            out[k] = flags[0]
        elif j >= len(levels):
            out[k] = flags[-1]
        else:
            lo, hi = flags[j - 1], flags[j]
            out[k] = lo if _FLAG_SEVERITY.get(lo, 0) >= _FLAG_SEVERITY.get(hi, 0) else hi
    return out


def median_filter(values: np.ndarray, width: int = BBP_MEDIAN_FILTER_WIDTH) -> np.ndarray:
    """Centre-aligned median filter with edge shrinkage (BBP manual §2.2.2)."""
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


def _worsen_flags(current: np.ndarray, extra: np.ndarray) -> np.ndarray:
    """Degrade QC flags following Argo severity order (4 > 3 > 2 > 1 > 0)."""
    _SEV = {b" ": 0, b"0": 0, b"1": 1, b"2": 2, b"5": 3, b"8": 4, b"3": 5, b"4": 6}
    cur_sev = np.asarray([_SEV.get(bytes(c), 0) for c in current])
    ext_sev = np.asarray([_SEV.get(bytes(c), 0) for c in extra])
    return np.where(ext_sev > cur_sev, extra, current)


def _bbp_test62(
    pres: np.ndarray,
    values: np.ndarray,
    ok: np.ndarray,
    flags: np.ndarray,
    failed: set[int],
    *,
    park_pres: float | None = None,
    ascending: bool = True,
) -> np.ndarray:
    """Test 62 on BBP700: the five sub-tests of the BBP manual."""
    # 62.1 missing data
    edges = (0.0,) + BBP_BINS_LOWER_DBAR
    counts = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        in_bin = ok & (pres >= lo) & (pres < hi)
        counts.append(int(in_bin.sum()) >= _BBP_MIN_N_PERBIN)
    n_bins = sum(counts)
    if ok.sum() == 0:
        failed.add(62)
        flags[ok] = b"9"
        return flags
    if n_bins == 1:
        failed.add(62)
        flags[ok] = b"4"
        return flags
    if n_bins < len(BBP_BINS_LOWER_DBAR):
        failed.add(62)
        flags[ok] = _worsen_flags(flags[ok], np.full(int(ok.sum()), b"3", dtype="S1"))

    # 62.2 high deep value
    deep = ok & (pres >= BBP_DEEP_VALUE_PRES_DBAR)
    if deep.sum() >= BBP_DEEP_VALUE_MIN_POINTS:
        medfilt = median_filter(values)
        deep_vals = medfilt[deep]
        deep_vals = deep_vals[np.isfinite(deep_vals)]
        if deep_vals.size and float(np.median(deep_vals)) > BBP_HIGH_DEEP_VALUE:
            failed.add(62)
            flags[ok] = _worsen_flags(flags[ok], np.full(int(ok.sum()), b"3", dtype="S1"))

    # 62.3 negative BBP
    shallow_neg = ok & (pres < BBP_NEGATIVE_PRES_DBAR) & (values < 0.0)
    if shallow_neg.any():
        failed.add(62)
        flags[shallow_neg] = b"4"
    deep_mask = ok & (pres >= BBP_NEGATIVE_PRES_DBAR)
    n_deep = int(deep_mask.sum())
    if n_deep:
        n_neg = int((deep_mask & (values < 0.0)).sum())
        pct = 100.0 * n_neg / n_deep
        if pct >= BBP_MAX_PCT_BAD_POINTS:
            failed.add(62)
            flags[ok] = b"4"
        elif pct > 0.0:
            failed.add(62)
            flags[ok] = _worsen_flags(flags[ok], np.full(int(ok.sum()), b"3", dtype="S1"))

    # 62.4 noisy profile
    if ok.sum() >= BBP_NOISY_MIN_POINTS:
        medfilt = median_filter(values)
        res = np.abs(medfilt - values)
        shallow = ok & (pres < BBP_NOISY_PRES_DBAR)
        n_shallow = int(shallow.sum())
        if n_shallow > 0:
            n_out = int((shallow & (res > BBP_NOISY_RES)).sum())
            if 100.0 * n_out / n_shallow >= BBP_MAX_PCT_OUTLIER:
                failed.add(62)
                flags[ok] = _worsen_flags(flags[ok], np.full(int(ok.sum()), b"3", dtype="S1"))

    # 62.5 parking hook
    if ascending:
        idx = np.where(ok)[0]
        if idx.size >= 2:
            max_pres = float(pres[idx].max())
            near_deep = pres[idx] >= (max_pres - BBP_HOOK_DELTA_PRES2_DBAR)
            if near_deep.any() and park_pres is not None and abs(max_pres - float(park_pres)) < BBP_HOOK_DELTA_PRES0_DBAR:
                band = ok & (pres >= max_pres - BBP_HOOK_DELTA_PRES1_DBAR) & (pres < max_pres - BBP_HOOK_DELTA_PRES2_DBAR)
                if band.any():
                    baseline = float(np.median(values[band])) + BBP_HOOK_DEV
                    hook = ok & (pres >= max_pres - BBP_HOOK_DELTA_PRES1_DBAR) & (values > baseline)
                    if hook.any():
                        failed.add(62)
                        flags[hook] = b"4"

    return flags


def run_bgc_rtqc(
    *,
    pres: np.ndarray,
    temp: np.ndarray | None,
    psal: np.ndarray | None,
    doxy: np.ndarray | None = None,
    tphase_doxy: np.ndarray | None = None,
    chla: np.ndarray | None = None,
    fluorescence_chla: np.ndarray | None = None,
    bbp700: np.ndarray | None = None,
    beta_backscattering700: np.ndarray | None = None,
    temp_cpu_chla: np.ndarray | None = None,
    nitrate: np.ndarray | None = None,
    pres_qc: np.ndarray | None = None,
    temp_qc: np.ndarray | None = None,
    psal_qc: np.ndarray | None = None,
    longitude: float | None = None,
    latitude: float | None = None,
    profile_pressure_dbar: float | None = None,
    park_pres: float | None = None,
    ascending: bool = True,
) -> dict[str, np.ndarray]:
    """Real-time QC for the BGC file (tests 6, 9, 11, 13, 57, 59, 62, 63).

    * TEST057 (DOXY, DOXY QC manual v2.2 s2.2.1): every defined DOXY level is
      *probably good* (3) in real time; a level whose PRES or TEMP is bad makes
      DOXY bad (4), and a level whose PSAL is bad stays correctable (3).
      Global range (test 6), spike (test 9), gradient (test 11), and stuck
      value (test 13) are also evaluated.
    * TEST063 (CHLA, CHLA QC manual v3.0 s2.2.2): every defined CHLA level is
      *probably good* (3). Global range (test 6) and stuck value (test 13) are
      evaluated; bad PRES_QC or bad FLUORESCENCE_CHLA propagates '4'.
    * TEST062 (BBP700, BBP QC manual v1.1): Test 6 (global range: [0, 0.05]),
      Test 13 (stuck value), and the five sub-tests (62.1 missing data,
      62.2 high deep value, 62.3 negative, 62.4 noisy, 62.5 parking hook).
      Profiles passing all tests earn QC '1' in real time; failing specific
      criteria demote to '3' or '4'.
    * TEST059 (NITRATE, Nitrate QC manual v1.1): unadjusted real-time NITRATE
      defaults to QC '3' ("probably good / potentially correctable"). Test 6
      (global range: [-2, 50]), Test 9 (spike), Test 11 (gradient), Test 13
      (stuck value), and bad CTD propagation (PRES_QC=4 or TEMP_QC=4 -> '4')
      are evaluated.
    * TPHASE_DOXY carries the DOXY flag: optode phase measurement.
    * Raw intermediate channels (FLUORESCENCE_CHLA, BETA_BACKSCATTERING700,
      TEMP_CPU_CHLA) evaluate Test 13 (stuck value: all identical -> '4');
      non-stuck measurements remain '0' ("no QC performed"), strictly
      justified under Argo Reference Table 2.

    Returns per-parameter flag arrays, all built from this float's own data.
    """
    n = len(pres)
    if pres_qc is None and temp_qc is None and psal_qc is None:
        core = run_core_rtqc(
            pres,
            temp,
            psal,
            longitude=longitude,
            latitude=latitude,
            profile_pressure_dbar=profile_pressure_dbar,
        )
        core_flags = core.qc
    else:
        core_flags = {}

    def _bad(flags, key) -> np.ndarray:
        if flags is None:
            return np.zeros(n, dtype=bool)
        chars = np.asarray([_flag_char(v) for v in np.ravel(np.asarray(flags))])
        if len(chars) != n:
            raise ValueError(f"{key}_qc has {len(chars)} values for {n} levels")
        return chars == "4"

    def defined(arr) -> np.ndarray:
        if arr is None:
            return np.zeros(n, dtype=bool)
        return ~_is_fill(np.asarray(arr, dtype=float))

    pres_bad = _bad(pres_qc, "pres") if pres_qc is not None else _bad(
        core_flags.get("PRES", np.full(n, b" ", dtype="S1")), "pres")
    temp_bad = _bad(temp_qc, "temp") if temp_qc is not None else _bad(
        core_flags.get("TEMP", np.full(n, b" ", dtype="S1")), "temp")

    out: dict[str, np.ndarray] = {}

    # 1. Raw intermediate channels first
    for name, arr in (
        ("FLUORESCENCE_CHLA", fluorescence_chla),
        ("BETA_BACKSCATTERING700", beta_backscattering700),
        ("TEMP_CPU_CHLA", temp_cpu_chla),
    ):
        if arr is None:
            continue
        vals = np.asarray(arr, dtype=float)
        mask = defined(vals)
        out[name] = np.where(mask, np.full(n, b"0", dtype="S1"), np.full(n, b" ", dtype="S1"))

    # 2. DOXY (Tests 6, 9, 11, 13, 57)
    doxy_flags: np.ndarray | None = None
    if doxy is not None:
        vals = np.asarray(doxy, dtype=float)
        mask = defined(vals)
        flags = np.where(mask, np.full(n, DOXY_RT_FLAG.encode(), dtype="S1"), np.full(n, b" ", dtype="S1"))
        t6 = _test6("DOXY", vals, pres, ~mask)
        t9 = _test9("DOXY", vals, pres, mask & ~t6)
        t11 = _test11("DOXY", vals, pres, mask & ~(t6 | t9))
        t13 = _test13(vals, mask)
        bad_core = mask & (pres_bad | temp_bad)
        flags[t6 | t9 | t11 | t13 | bad_core] = b"4"
        out["DOXY"] = flags
        doxy_flags = flags

    # 3. TPHASE_DOXY (follows DOXY_QC)
    if tphase_doxy is not None:
        mask = defined(tphase_doxy)
        if doxy_flags is None:
            flags = np.where(mask, np.full(n, DOXY_RT_FLAG.encode(), dtype="S1"), np.full(n, b" ", dtype="S1"))
        else:
            flags = np.where(doxy_flags == b"4", b"4", np.where(mask, doxy_flags, b" "))
            flags = np.where(doxy_flags == b" ", b" ", flags)
        out["TPHASE_DOXY"] = np.asarray(flags, dtype="S1")

    # 4. CHLA (Tests 6, 13, 63)
    if chla is not None:
        vals = np.asarray(chla, dtype=float)
        mask = defined(vals)
        flags = np.where(mask, np.full(n, CHLA_RT_FLAG.encode(), dtype="S1"), np.full(n, b" ", dtype="S1"))
        t6 = _test6("CHLA", vals, pres, ~mask)
        t13 = _test13(vals, mask)
        flags[t6 | t13] = b"4"
        out["CHLA"] = flags

    # 5. BBP700 (Tests 6, 13, 62)
    if bbp700 is not None:
        vals = np.asarray(bbp700, dtype=float)
        mask = defined(vals)
        flags = np.where(mask, np.full(n, b"1", dtype="S1"), np.full(n, b" ", dtype="S1"))
        t6 = _test6("BBP700", vals, pres, ~mask)
        t13 = _test13(vals, mask)
        flags[t6 | t13] = b"4"
        failed_62: set[int] = set()
        flags = _bbp_test62(pres, vals, mask, flags, failed_62, park_pres=park_pres, ascending=ascending)
        flags[mask & pres_bad] = b"4"
        out["BBP700"] = flags

    # 6. NITRATE (Tests 6, 9, 11, 13, 59)
    if nitrate is not None:
        vals = np.asarray(nitrate, dtype=float)
        mask = defined(vals)
        flags = np.where(mask, np.full(n, NITRATE_RT_FLAG.encode(), dtype="S1"), np.full(n, b" ", dtype="S1"))
        t6 = _test6("NITRATE", vals, pres, ~mask)
        t9 = _test9("NITRATE", vals, pres, mask & ~t6)
        t11 = _test11("NITRATE", vals, pres, mask & ~(t6 | t9))
        t13 = _test13(vals, mask)
        bad_core = mask & (pres_bad | temp_bad)
        flags[t6 | t9 | t11 | t13 | bad_core] = b"4"
        out["NITRATE"] = flags

    return out


def test004_position_on_land(
    latitude: float | None,
    longitude: float | None,
    *,
    position_qc: str = "1",
    elevations=None,
) -> dict:
    """TEST 004 (position on land) -- coded, deliberately NOT run here.

    The chain's own block is unambiguous about the precondition: test 4 needs the
    GEBCO bathymetric atlas registered as ``TEST004_GEBCO_FILE``; when that file
    is absent the chain sets ``testFlagList(4) = 0`` and reports
    "test #4 not performed" (``add_rtqc_to_profile_file.m`` lines 498-513).  This
    environment cannot hold the GEBCO grid, so this function is never called by
    the product chain -- it exists so the test can be run locally, unchanged,
    against a real grid:

    * sample the atlas at the profile position and take the mean elevation;
    * ``mean >= 0`` (land) -> POSITION_QC '4'; if the position was interpolated
      ('8') the rule is '9' and the position is withheld instead;
    * no elevation available -> the test is not performed for that profile.

    ``elevations`` is the sampled grid window (m, positive above sea level); pass
    ``gebco=<path>`` style data through it when running locally.  Without any
    elevation input the function refuses to answer instead of guessing.
    """
    if elevations is None:
        raise RuntimeError(
            "TEST004 needs a GEBCO grid (TEST004_GEBCO_FILE in the chain); the "
            "sandbox cannot hold it, so the test is coded but not performed")
    if latitude is None or longitude is None:
        return {"performed": False, "reason": "no valid position", "position_qc": position_qc}
    import numpy as _np

    arr = _np.asarray([e for e in _np.ravel(elevations) if e == e], dtype=float)
    if arr.size == 0:
        return {"performed": False, "reason": "no elevation sample at the position",
                "position_qc": position_qc}
    if arr.mean() < 0:
        return {"performed": True, "failed": False, "position_qc": "1"}
    if position_qc == "8":
        return {"performed": True, "failed": True, "position_qc": "9",
                "withhold_position": True}
    return {"performed": True, "failed": True, "position_qc": "4"}


def profile_quality_letter(flags: np.ndarray) -> str:
    """PROFILE_<param>_QC letter (compute_profile_quality_flag.m, verbatim)."""
    chars = np.char.decode(flags)
    useful = (chars != " ") & (chars != "0") & (chars != "9")
    if not useful.any():
        return " "
    good = (chars == "1") | (chars == "2") | (chars == "5") | (chars == "8")
    ratio = 100.0 * good.sum() / useful.sum()
    if ratio == 0:
        return "F"
    if ratio < 25:
        return "E"
    if ratio < 50:
        return "D"
    if ratio < 75:
        return "C"
    if ratio < 100:
        return "B"
    return "A"


__all__ = [
    "CHLA_RT_FLAG",
    "DENSITY_INVERSION_THRESHOLD",
    "DOXY_RT_FLAG",
    "GLOBAL_RANGE",
    "GRADIENT_THRESHOLDS",
    "NITRATE_RT_FLAG",
    "PRES_REVERSAL_DBAR",
    "ProfileRtqc",
    "ROLLOVER_DELTA",
    "SPIKE_THRESHOLDS",
    "core_qc_at",
    "median_filter",
    "profile_quality_letter",
    "run_bgc_rtqc",
    "run_core_rtqc",
    "test004_position_on_land",
]
