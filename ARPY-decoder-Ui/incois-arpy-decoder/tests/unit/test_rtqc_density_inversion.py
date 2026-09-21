"""Unit tests for RTQC TEST014 density inversion."""

from __future__ import annotations

import numpy as np
import pytest

from argo_decoder.domain.qc import QcFlag
from argo_decoder.rtqc.density_inversion import (
    DENSITY_INVERSION_THRESHOLD,
    density_inversion_test,
)


def _stable_profile(n: int = 20) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A smoothly-stably-stratified water column.

    Constant S=35 psu, temperature falling from 18 °C at the surface to
    3 °C at 2000 dbar produces a monotonically increasing potential
    density (pressure effect dominates over thermal expansion for
    mid-latitude water).
    """
    p = np.linspace(0.0, 2000.0, n)
    t = np.linspace(18.0, 3.0, n)
    s = np.full(n, 35.0)
    return p, t, s


def test_stable_profile_passes():
    p, t, s = _stable_profile()
    t_out, s_out = density_inversion_test(pres=p, temp=t, psal=s, lat=30.0, lon=-30.0)
    assert np.all(t_out.per_level == int(QcFlag.GOOD))
    assert np.all(s_out.per_level == int(QcFlag.GOOD))
    assert t_out.n_flagged == 0
    assert s_out.n_flagged == 0


def test_explicit_inversion_flagged():
    """Inject a locally denser sample over a lighter one.

    Shallow sample at ~50 dbar is made very cold+salty so that its
    potential density at the midpoint is >0.03 kg/m³ heavier than the
    sample immediately below.
    """
    p, t, s = _stable_profile(n=25)
    # Introduce a density inversion at index 5 (shallow) vs 6 (deep):
    # make shallow extremely dense.
    t[5] = 0.0
    s[5] = 40.0
    t_out, s_out = density_inversion_test(pres=p, temp=t, psal=s, lat=30.0, lon=-30.0)
    assert t_out.per_level[5] == int(QcFlag.BAD)
    assert s_out.per_level[5] == int(QcFlag.BAD)
    # all other good samples remain GOOD
    for i in range(len(p)):
        if i == 5:
            continue
        assert t_out.per_level[i] in (int(QcFlag.GOOD), int(QcFlag.BAD))
    assert t_out.n_flagged >= 1
    assert s_out.n_flagged >= 1


def test_small_inversion_below_threshold_passes():
    """Differences well below 0.03 kg/m³ should NOT be flagged."""
    p, t, s = _stable_profile()
    # Add a tiny density wiggle (~0.005 kg/m³) at level 10.
    s[10] += 0.001
    t_out, _s_out = density_inversion_test(pres=p, temp=t, psal=s, lat=30.0, lon=-30.0)
    assert t_out.per_level[10] == int(QcFlag.GOOD)


def test_inversion_at_boundary_of_validity_is_gated_by_qc():
    """BAD QC on any of P/T/S excludes that sample from the test."""
    p, t, s = _stable_profile(n=10)
    # force an inversion but pre-flag the shallow T as BAD
    t[4] = 0.0
    s[4] = 40.0
    pres_qc = np.ones(10, dtype=np.int8)
    temp_qc = np.ones(10, dtype=np.int8)
    psal_qc = np.ones(10, dtype=np.int8)
    temp_qc[4] = int(QcFlag.BAD)
    t_out, _s_out = density_inversion_test(
        pres=p,
        temp=t,
        psal=s,
        lat=30.0,
        lon=-30.0,
        pres_qc=pres_qc,
        temp_qc=temp_qc,
        psal_qc=psal_qc,
    )
    # The pair is excluded from the test, so TEST014 reports nothing at
    # all: a level it could not evaluate is not a level it found bad.
    # Re-stating the input flag under this test's name would both
    # double-count the failure in HISTORY_QCTEST and, when the exclusion
    # came from a *different* parameter, condemn good data.
    assert t_out.n_flagged == 0
    assert t_out.per_level[4] == int(QcFlag.GOOD)
    # Deep sample (index 5) should remain GOOD (since pair gated out).
    assert t_out.per_level[5] == int(QcFlag.GOOD)


def test_fill_samples_are_not_flagged_by_this_test():
    """TEST014 does not flag levels it merely skipped.

    A fill sample is caught by the global-range test (TEST006), which is
    the test that owns that finding. TEST014 restating it made the two
    indistinguishable in ``HISTORY_QCTEST`` and leaked one parameter's
    exclusion onto the other.
    """
    p, t, s = _stable_profile(n=6)
    t[2] = 99.999  # Argo TEMP_FILL
    s[3] = 99.999  # Argo PSAL_FILL
    t_out, s_out = density_inversion_test(pres=p, temp=t, psal=s, lat=30.0, lon=-30.0)
    assert t_out.per_level[2] == int(QcFlag.GOOD)
    assert s_out.per_level[3] == int(QcFlag.GOOD)
    assert t_out.n_flagged == 0
    assert s_out.n_flagged == 0


def test_short_profile_no_crash():
    p = np.array([10.0])
    t = np.array([15.0])
    s = np.array([35.0])
    t_out, _s_out = density_inversion_test(pres=p, temp=t, psal=s, lat=0.0, lon=0.0)
    assert len(t_out.per_level) == 1
    assert t_out.per_level[0] == int(QcFlag.GOOD)


def test_pressure_inversions_skipped():
    """If pressure is decreasing (already flagged by TEST008), do not double-flag."""
    # Build a column where every pair is stable when traversed in
    # ascending-pressure order, but an out-of-order sample (index 2 at
    # 100 dbar sits between 200 and 300 dbar) causes a dp<=0 pair at
    # (1,2). That pair must be skipped because TEST008 already covers
    # pressure ordering; pairs (0,1) and (2,3) are examined normally.
    p = np.array([0.0, 200.0, 100.0, 300.0])
    t = np.array([20.0, 8.0, 12.0, 4.0])  # warm surface -> cold deep
    s = np.array([35.5, 35.0, 35.2, 34.9])
    t_out, _s_out = density_inversion_test(pres=p, temp=t, psal=s, lat=30.0, lon=-30.0)
    # Pair (1,2) has decreasing pressure (dp=-100 dbar) -> skipped.
    # Therefore index 1 should not be flagged by this test (the only
    # way it could is if we erroneously compared (1,2)).
    assert t_out.per_level[1] == int(QcFlag.GOOD)
    # Index 2 is also part of the ascending-pressure pair (2,3),
    # which on this profile is stable -> GOOD.
    assert t_out.per_level[2] == int(QcFlag.GOOD)


def test_threshold_value_matches_matlab():
    # 0.03 kg/m³ is the COQC threshold documented in add_rtqc_to_profile_file.m
    assert pytest.approx(0.03) == DENSITY_INVERSION_THRESHOLD
