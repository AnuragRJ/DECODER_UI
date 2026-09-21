"""Real-time QC (RTQC) tests for vertical-profile parameters.

Implements the "non-density" RTQC tests that do not require in-situ
density (density inversion TEST014 is implemented in a later slice once
CNDC is integrated with SA/CT).  Tests operate on plain numpy arrays
(PRES ascending, shallowest first; any NaN / fill samples are ignored
and flagged BAD through the global-range test).

Each test returns an integer numpy array of :class:`QcFlag` values with
the same length as the input pressure vector, using Argo reference
table 2 flag values (1=good, 3=probably bad, 4=bad).  The caller merges
per-test flags via :func:`argo_decoder.domain.qc.merge_qc_results` at
the profile level.

Thresholds follow the Argo RTQC manual and the Coriolis MATLAB
implementation (``add_rtqc_to_profile_file.m``).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from argo_decoder.domain.qc import QcFlag

#: Per-level flag contract (aligned with the Coriolis MATLAB tests, which
#: judge *defined values only*, ``idNoDef``): a level a test cannot judge
#: -- fill / non-finite -- receives ``NO_QC`` (0), never BAD. The RTQC
#: merge is a per-level maximum, so untouched fill levels keep their
#: pre-RTQC representation instead of being escalated artificially.

# Argo RTQC manual global ranges (physical plausibility). TEMP upper
# bound 40.0 degC per QC Manual v3.9 Test 6 and the current Coriolis
# MATLAB test6ParameterList (add_rtqc_to_profile_file.m); the previous
# 42.0 was a transcription artifact.
GLOBAL_RANGE: dict[str, tuple[float, float]] = {
    "PRES": (-5.0, 12000.0),
    "TEMP": (-2.5, 40.0),
    "PSAL": (2.0, 41.0),
    "CNDC": (0.0, 8.5),  # S/m
}
# Spike thresholds (QC Manual v3.9 Test 9 / current Coriolis MATLAB
# test9ParameterList): triplicate form with a 500-dbar split. CNDC has
# no manual/MATLAB spike thresholds and is not spike-tested.
SPIKE_THRESHOLD_SHALLOW: dict[str, float] = {
    "TEMP": 6.0,  # degC, PRES < 500 dbar
    "PSAL": 0.9,  # psu, PRES < 500 dbar
}
SPIKE_THRESHOLD_DEEP: dict[str, float] = {
    "TEMP": 2.0,  # degC, PRES >= 500 dbar
    "PSAL": 0.3,  # psu, PRES >= 500 dbar
}
SPIKE_PRESSURE_SPLIT_DBAR = 500.0
# Gradient thresholds (QC Manual v3.9 Test 11, obsolete-but-retained for
# INCOIS parity): |V2 - (V1+V3)/2| with a 500-dbar split. CNDC has no
# manual gradient thresholds and is not gradient-tested.
GRADIENT_THRESHOLD_SHALLOW: dict[str, float] = {
    "TEMP": 9.0,  # degC, PRES < 500 dbar
    "PSAL": 1.5,  # psu, PRES < 500 dbar
}
GRADIENT_THRESHOLD_DEEP: dict[str, float] = {
    "TEMP": 3.0,  # degC, PRES >= 500 dbar
    "PSAL": 0.5,  # psu, PRES >= 500 dbar
}
GRADIENT_PRESSURE_SPLIT_DBAR = 500.0
# Stuck-value (TEST013) is a whole-profile test in the specification, so
# no run-length screen is applied by default. See ``stuck_value_test``.
STUCK_RUN_LENGTH = 0

# TEST012 digit rollover: difference between adjacent pressures above
# which the stored value is assumed to have wrapped (QC Manual v3.9).
ROLLOVER_THRESHOLD: dict[str, float] = {
    "TEMP": 10.0,  # degC
    "PSAL": 5.0,  # psu
}

# TEST019 deepest pressure: tolerance added to CONFIG_ProfilePressure_dbar.
# The manual allows 10%, widening to a flat 100 dbar for shallow targets
# because floats stabilise less precisely near the surface.
DEEPEST_PRESSURE_FRACTION = 0.10
DEEPEST_PRESSURE_MIN_TOL_DBAR = 100.0

# TEST006 near-surface pressure bands (QC Manual v3.9 Test 6 action).
PRES_BAD_BELOW_DBAR = -5.0
PRES_SUSPECT_BELOW_DBAR = -2.4
# Pressure-inversion tolerance (PRES_reversal). QC Manual v3.9 Test 8
# (revised 07-Feb-2024) and the current Coriolis MATLAB both use 20 dbar;
# the previous 2 dbar predated the revision.
PRESSURE_INVERSION_TOL_DB = 20.0


@dataclass
class QcTestOutcome:
    """One test's per-level flags plus a test-level flag (worst case)."""

    test_name: str
    per_level: np.ndarray
    profile_flag: QcFlag
    n_flagged: int


def _as_masked(pres: np.ndarray, values: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return boolean mask of valid samples and copies of arrays."""
    p = np.asarray(pres, dtype=np.float64)
    v = np.asarray(values, dtype=np.float64)
    valid = np.isfinite(p) & np.isfinite(v)
    return p, v, valid


def global_range_test(
    name: str,
    pres: np.ndarray,
    values: np.ndarray,
    *,
    vmin: float | None = None,
    vmax: float | None = None,
) -> QcTestOutcome:
    """TEST006: flag samples outside the physical range."""
    if vmin is None or vmax is None:
        if name not in GLOBAL_RANGE:
            return QcTestOutcome(
                f"global_range[{name}]",
                np.full(len(values), int(QcFlag.GOOD), dtype=np.int8),
                QcFlag.GOOD,
                0,
            )
        vmin, vmax = GLOBAL_RANGE[name]
    _, v, valid = _as_masked(pres, values)
    flags = np.full(len(v), int(QcFlag.NO_QC), dtype=np.int8)
    flags[valid] = int(QcFlag.GOOD)
    bad = valid & ((v < vmin) | (v > vmax))
    flags[bad] = int(QcFlag.BAD)
    n_flagged = int(np.sum(flags == int(QcFlag.BAD)))
    profile_flag = QcFlag.BAD if n_flagged else QcFlag.GOOD
    return QcTestOutcome(f"global_range[{name}]", flags, profile_flag, n_flagged)


def pressure_increasing_test(pres: np.ndarray) -> QcTestOutcome:
    """TEST008: pressure must be monotonically non-decreasing.

    Flags any level k where ``pres[k] + tol < pres[k-1]`` (reversed
    order) as BAD, and also the neighbouring bin when the reversal is
    large.  The first level cannot be flagged by this test (no prior
    reference).
    """
    p = np.asarray(pres, dtype=np.float64)
    flags = np.full(len(p), int(QcFlag.NO_QC), dtype=np.int8)
    valid = np.isfinite(p)
    flags[valid] = int(QcFlag.GOOD)
    for k in range(1, len(p)):
        if not (valid[k] and valid[k - 1]):
            continue
        if p[k] < p[k - 1] - PRESSURE_INVERSION_TOL_DB:
            flags[k] = int(QcFlag.BAD)
            flags[k - 1] = int(QcFlag.BAD)
    n_flagged = int(np.sum(flags == int(QcFlag.BAD)))
    return QcTestOutcome(
        "pressure_increasing", flags, QcFlag.BAD if n_flagged else QcFlag.GOOD, n_flagged
    )


def spike_test(
    name: str,
    pres: np.ndarray,
    values: np.ndarray,
    *,
    shallow: float | None = None,
    deep: float | None = None,
) -> QcTestOutcome:
    """TEST009: spike test, QC Manual v3.9 / current Coriolis MATLAB form.

    Test value ``|V2 - (V3 + V1)/2| - |(V3 - V1)/2|`` over triples of
    *consecutive defined* levels (the MATLAB walks continuous defined
    slices), with the manual's split thresholds: TEMP 6.0/2.0 degC and
    PSAL 0.9/0.3 psu either side of 500 dbar. A failing V2 is flagged
    BAD ('4') per the manual's action. CNDC carries no manual/MATLAB
    spike thresholds and is not spike-tested.
    """
    if shallow is None:
        shallow = SPIKE_THRESHOLD_SHALLOW.get(name)
    if deep is None:
        deep = SPIKE_THRESHOLD_DEEP.get(name)
    if shallow is None or deep is None:
        return QcTestOutcome(
            f"spike[{name}]",
            np.full(len(values), int(QcFlag.NO_QC), dtype=np.int8),
            QcFlag.GOOD,
            0,
        )
    p, v, valid = _as_masked(pres, values)
    flags = np.full(len(v), int(QcFlag.NO_QC), dtype=np.int8)
    flags[valid] = int(QcFlag.GOOD)
    idx = np.where(valid)[0]
    for j in range(1, len(idx) - 1):
        i0, i1, i2 = int(idx[j - 1]), int(idx[j]), int(idx[j + 1])
        if i1 != i0 + 1 or i2 != i1 + 1:
            continue  # only triples inside one continuous defined slice
        test_val = abs(v[i1] - (v[i2] + v[i0]) / 2.0) - abs((v[i2] - v[i0]) / 2.0)
        threshold = shallow if p[i1] < SPIKE_PRESSURE_SPLIT_DBAR else deep
        if test_val > threshold:
            flags[i1] = int(QcFlag.BAD)
    n_flagged = int(np.sum(flags == int(QcFlag.BAD)))
    profile_flag = QcFlag.BAD if n_flagged else QcFlag.GOOD
    return QcTestOutcome(f"spike[{name}]", flags, profile_flag, n_flagged)


def gradient_test(
    name: str,
    pres: np.ndarray,
    values: np.ndarray,
    *,
    shallow: float | None = None,
    deep: float | None = None,
) -> QcTestOutcome:
    """TEST011 (obsolete in v3.9, retained for INCOIS GDAC parity).

    QC Manual v3.9 Test 11 formulation: test value ``|V2 - (V3 + V1)/2|``
    over consecutive defined levels, with TEMP 9.0/3.0 degC and PSAL
    1.5/0.5 psu either side of 500 dbar; a failing V2 is flagged BAD
    ('4'). INCOIS still executes and reports test 11 on core parameters
    (proven by the QCP$ masks and the QCF$ failures on this fleet's
    reference files), so the engine keeps it in the applied set. CNDC
    carries no manual gradient thresholds and is not gradient-tested.
    """
    if shallow is None:
        shallow = GRADIENT_THRESHOLD_SHALLOW.get(name)
    if deep is None:
        deep = GRADIENT_THRESHOLD_DEEP.get(name)
    if shallow is None or deep is None:
        return QcTestOutcome(
            f"gradient[{name}]",
            np.full(len(values), int(QcFlag.NO_QC), dtype=np.int8),
            QcFlag.GOOD,
            0,
        )
    p, v, valid = _as_masked(pres, values)
    flags = np.full(len(v), int(QcFlag.NO_QC), dtype=np.int8)
    flags[valid] = int(QcFlag.GOOD)
    idx = np.where(valid)[0]
    for j in range(1, len(idx) - 1):
        i0, i1, i2 = int(idx[j - 1]), int(idx[j]), int(idx[j + 1])
        if i1 != i0 + 1 or i2 != i1 + 1:
            continue  # only triples inside one continuous defined slice
        test_val = abs(v[i1] - (v[i2] + v[i0]) / 2.0)
        threshold = shallow if p[i1] < GRADIENT_PRESSURE_SPLIT_DBAR else deep
        if test_val > threshold:
            flags[i1] = int(QcFlag.BAD)
    n_flagged = int(np.sum(flags == int(QcFlag.BAD)))
    profile_flag = QcFlag.BAD if n_flagged else QcFlag.GOOD
    return QcTestOutcome(f"gradient[{name}]", flags, profile_flag, n_flagged)


def stuck_value_test(
    pres: np.ndarray,
    values: np.ndarray,
    *,
    run_length: int = STUCK_RUN_LENGTH,
) -> QcTestOutcome:
    """TEST013: the *whole* profile reading one constant value.

    QC Manual v3.9, Test 13: "This test looks for measurements of
    temperature and salinity in a profile being identical. Action: If
    this occurs, all the values of the affected parameter should be
    flagged as bad data ('4')."

    The test is deliberately about the entire profile, not a run within
    it. A previous implementation flagged any run of eight equal samples,
    which is a different -- and much weaker -- claim: a genuinely stuck
    sensor cannot recover mid-profile, whereas a real ocean can easily
    hold one value to four decimals across a well-mixed layer. On WMO
    2901304 that cost 37 wrongly-flagged levels, all inside isothermal
    layers where the reference flags the data good.

    ``run_length`` is retained for callers that want the older
    run-based screen, but the default is now the specification's
    whole-profile rule (``run_length=0`` disables the run screen; any
    positive value re-enables it).
    """
    _, v, valid = _as_masked(pres, values)
    flags = np.full(len(v), int(QcFlag.NO_QC), dtype=np.int8)
    flags[valid] = int(QcFlag.GOOD)
    n = len(v)
    rounded = np.round(v, 4)

    # Specification rule: every valid level identical -> whole parameter bad.
    present = rounded[valid]
    if present.size >= 2 and np.all(present == present[0]):
        flags[valid] = int(QcFlag.BAD)
    elif run_length > 0:
        i = 0
        while i < n:
            if not valid[i]:
                i += 1
                continue
            j = i + 1
            while j < n and valid[j] and rounded[j] == rounded[i]:
                j += 1
            if j - i >= run_length:
                flags[i:j] = int(QcFlag.BAD)
            i = j
    n_flagged = int(np.sum(flags == int(QcFlag.BAD)))
    return QcTestOutcome("stuck_value", flags, QcFlag.BAD if n_flagged else QcFlag.GOOD, n_flagged)


def digit_rollover_test(
    name: str,
    pres: np.ndarray,
    values: np.ndarray,
) -> QcTestOutcome:
    """TEST012: detect a stored value wrapping past its bit range.

    QC Manual v3.9 Test 12: a temperature difference between adjacent
    pressures greater than 10 degC, or a salinity difference greater than
    5 psu, indicates the transmitted integer rolled over. Both members of
    the pair that reveals the jump are flagged bad.
    """
    threshold = ROLLOVER_THRESHOLD.get(name)
    _, v, valid = _as_masked(pres, values)
    flags = np.full(len(v), int(QcFlag.NO_QC), dtype=np.int8)
    flags[valid] = int(QcFlag.GOOD)
    if threshold is None:
        return QcTestOutcome("digit_rollover", flags, QcFlag.GOOD, 0)
    for k in range(len(v) - 1):
        if not (valid[k] and valid[k + 1]):
            continue
        if abs(v[k + 1] - v[k]) > threshold:
            flags[k] = int(QcFlag.BAD)
            flags[k + 1] = int(QcFlag.BAD)
    n_flagged = int(np.sum(flags == int(QcFlag.BAD)))
    return QcTestOutcome(
        "digit_rollover", flags, QcFlag.BAD if n_flagged else QcFlag.GOOD, n_flagged
    )


def deepest_pressure_test(
    pres: np.ndarray,
    profile_pressure_dbar: float | None,
) -> QcTestOutcome:
    """TEST019: no level may sit below the programmed profile pressure.

    QC Manual v3.9 Test 19: the threshold is
    ``CONFIG_ProfilePressure_dbar`` plus 10%, and levels beyond it are
    flagged *probably bad* ('3') -- not bad -- along with their TEMP and
    PSAL. Returns all-good when the configuration is unknown, rather
    than inventing a limit.
    """
    p = np.asarray(pres, dtype=np.float64)
    flags = np.full(len(p), int(QcFlag.NO_QC), dtype=np.int8)
    finite = np.isfinite(p)
    flags[finite] = int(QcFlag.GOOD)
    if profile_pressure_dbar is None or not np.isfinite(profile_pressure_dbar):
        # Unknown configuration pressure: the test cannot judge anything,
        # so every level keeps NO_QC rather than an invented verdict.
        return QcTestOutcome("deepest_pressure", flags, QcFlag.GOOD, 0)
    tolerance = max(
        profile_pressure_dbar * DEEPEST_PRESSURE_FRACTION, DEEPEST_PRESSURE_MIN_TOL_DBAR
    )
    limit = float(profile_pressure_dbar) + tolerance
    over = finite & (p > limit)
    flags[over] = int(QcFlag.PROBABLY_BAD)
    n_flagged = int(np.sum(over))
    return QcTestOutcome(
        "deepest_pressure", flags, QcFlag.PROBABLY_BAD if n_flagged else QcFlag.GOOD, n_flagged
    )


def near_surface_pressure_test(pres: np.ndarray) -> QcTestOutcome:
    """TEST006 (pressure branch): negative pressures near the surface.

    QC Manual v3.9 Test 6 action: ``PRES < -5 dbar`` is bad ('4');
    ``-5 <= PRES <= -2.4 dbar`` is probably bad ('3'). Small negative
    pressures just above the surface are ordinary sensor offset and stay
    good. The generic global-range test cannot express this because it is
    a two-band rule rather than a single limit.
    """
    p = np.asarray(pres, dtype=np.float64)
    flags = np.full(len(p), int(QcFlag.NO_QC), dtype=np.int8)
    finite = np.isfinite(p)
    flags[finite] = int(QcFlag.GOOD)
    flags[finite & (p < PRES_BAD_BELOW_DBAR)] = int(QcFlag.BAD)
    suspect = finite & (p >= PRES_BAD_BELOW_DBAR) & (p <= PRES_SUSPECT_BELOW_DBAR)
    flags[suspect] = int(QcFlag.PROBABLY_BAD)
    n_flagged = int(np.sum(flags > int(QcFlag.GOOD)))
    worst = QcFlag.GOOD
    if n_flagged:
        worst = QcFlag.BAD if np.any(flags == int(QcFlag.BAD)) else QcFlag.PROBABLY_BAD
    return QcTestOutcome("near_surface_pressure", flags, worst, n_flagged)


# Argo reference table 11 test numbers for the tests implemented here.
# ``stuck_value_test`` is TEST013; the others follow their docstrings.
NON_DENSITY_TEST_NUMBERS: dict[str, int] = {
    "global_range": 6,
    "near_surface_pressure": 6,  # Test 6's pressure-band branch
    "pressure_increasing": 8,
    "spike": 9,
    "gradient": 11,
    "digit_rollover": 12,
    "stuck_value": 13,
    "deepest_pressure": 19,
}


def run_non_density_tests(
    *,
    pres: np.ndarray,
    temp: np.ndarray,
    psal: np.ndarray,
    cndc: np.ndarray | None = None,
    failed_tests: set[int] | None = None,
    profile_pressure_dbar: float | None = None,
) -> dict[str, np.ndarray]:
    """Run every non-density RTQC test and return per-parameter QC arrays.

    Returns a dict mapping variable name → np.ndarray of int8 QC flags,
    worst-flag wins across tests.

    When ``failed_tests`` is supplied it is populated in place with the
    Argo reference table 11 numbers of the tests that flagged at least
    one level. This is the provenance the ADMT ``HISTORY_QCTEST``
    ``QCF$`` record requires; it is opt-in so existing callers are
    unaffected.
    """
    p = np.asarray(pres, dtype=np.float64)
    n = len(p)
    # Baselines start at NO_QC: only levels a test actually judges may be
    # raised, so fill levels survive the worst-flag merge as NO_QC ('0').
    good = np.full(n, int(QcFlag.NO_QC), dtype=np.int8)

    def _record(key: str, outcome: QcTestOutcome) -> np.ndarray:
        if failed_tests is not None and int(np.max(outcome.per_level, initial=1)) > 1:
            failed_tests.add(NON_DENSITY_TEST_NUMBERS[key])
        return outcome.per_level

    # TEST019 runs first in the manual's order and degrades PRES, TEMP and
    # PSAL together, so it is computed once and merged into all three.
    deepest = _record("deepest_pressure", deepest_pressure_test(p, profile_pressure_dbar))

    pres_flags = good.copy()
    for key, outcome in (
        ("global_range", global_range_test("PRES", p, p)),
        ("near_surface_pressure", near_surface_pressure_test(p)),
        ("pressure_increasing", pressure_increasing_test(p)),
    ):
        pres_flags = np.maximum(pres_flags, _record(key, outcome))
    pres_flags = np.maximum(pres_flags, deepest)

    def _param_flags(name: str, values: np.ndarray) -> np.ndarray:
        fl = good.copy()
        for key, outcome in (
            ("global_range", global_range_test(name, p, values)),
            ("spike", spike_test(name, p, values)),
            ("gradient", gradient_test(name, p, values)),
            ("digit_rollover", digit_rollover_test(name, p, values)),
            ("stuck_value", stuck_value_test(p, values)),
        ):
            fl = np.maximum(fl, _record(key, outcome))
        # TEST019 applies to the hydrographic parameters at the offending
        # level as well as to PRES itself -- but only where the parameter
        # itself is defined: its all-good baseline must not lift fill
        # levels out of NO_QC (the Prompt-8 fill contract).
        defined = np.isfinite(np.asarray(values, dtype=np.float64))
        deepest_here = np.where(defined, deepest, int(QcFlag.NO_QC)).astype(np.int8)
        fl = np.maximum(fl, deepest_here)
        # Manual 2.1.4(c): PRES_QC = '4' at a level makes every parameter
        # bad there; Test 6's action additionally degrades the parameters
        # to '3' where PRES itself is only suspect (the -5..-2.4 dbar
        # band). Fill levels (NO_QC) propagate nothing.
        pres_degraded = np.where(
            pres_flags >= int(QcFlag.PROBABLY_BAD), pres_flags, int(QcFlag.NO_QC)
        )
        merged: np.ndarray = np.maximum(fl, pres_degraded).astype(np.int8)
        return merged

    temp_flags = _param_flags("TEMP", np.asarray(temp, dtype=np.float64))
    psal_flags = _param_flags("PSAL", np.asarray(psal, dtype=np.float64))

    # Manual section 2.2.4(b): salinity is derived from conductivity and
    # temperature, so a bad or probably-bad TEMP propagates to PSAL at the
    # same level. The converse does not hold -- a stuck conductivity cell
    # says nothing about the thermistor -- which is why this is one-way.
    degraded = temp_flags >= int(QcFlag.PROBABLY_BAD)
    psal_flags = np.where(degraded, np.maximum(psal_flags, temp_flags), psal_flags).astype(np.int8)

    out: dict[str, np.ndarray] = {
        "PRES": pres_flags,
        "TEMP": temp_flags,
        "PSAL": psal_flags,
    }
    if cndc is not None:
        # Manual section 2.2.4(b): "For floats where CNDC values are
        # reported, CNDC_QC = PSAL_QC."
        cndc_flags = _param_flags("CNDC", np.asarray(cndc, dtype=np.float64))
        out["CNDC"] = np.maximum(cndc_flags, psal_flags).astype(np.int8)
    return out


__all__ = [
    "DEEPEST_PRESSURE_FRACTION",
    "DEEPEST_PRESSURE_MIN_TOL_DBAR",
    "GLOBAL_RANGE",
    "GRADIENT_PRESSURE_SPLIT_DBAR",
    "GRADIENT_THRESHOLD_DEEP",
    "GRADIENT_THRESHOLD_SHALLOW",
    "NON_DENSITY_TEST_NUMBERS",
    "PRESSURE_INVERSION_TOL_DB",
    "ROLLOVER_THRESHOLD",
    "SPIKE_PRESSURE_SPLIT_DBAR",
    "SPIKE_THRESHOLD_DEEP",
    "SPIKE_THRESHOLD_SHALLOW",
    "STUCK_RUN_LENGTH",
    "QcTestOutcome",
    "deepest_pressure_test",
    "digit_rollover_test",
    "global_range_test",
    "gradient_test",
    "near_surface_pressure_test",
    "pressure_increasing_test",
    "run_non_density_tests",
    "spike_test",
    "stuck_value_test",
]
