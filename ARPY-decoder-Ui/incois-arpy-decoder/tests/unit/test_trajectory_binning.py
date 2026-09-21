"""Unit tests for trajectory binning (M5)."""

from __future__ import annotations

import numpy as np

from argo_decoder.trajectory.binning import MeasurementCodes, bin_cycle_samples


def test_ascent_only_profile_is_asc_bin():
    """A monotonically-shallowing (already ascending) acquisition with
    the deepest sample first -> everything after first sample is ASC."""
    p = np.linspace(4000.0, 10.0, 50)  # deepest first, shallowest last
    bins = bin_cycle_samples(pres=p, park_pressure=1000.0)
    assert len(bins[MeasurementCodes.PROFILE_ASCENT]) == 49
    # the deepest sample itself goes to PARK_DRIFT (deepest_acq == k)
    assert len(bins[MeasurementCodes.PARK_DRIFT]) == 1


def test_full_mission_bins():
    """Simulate descent 0→1000 (park) 1000→2000 (profile descent) 2000→10
    (ascent). Samples below air threshold at end are in-air."""
    n_each = 20
    p_surface = np.array([5.0])  # start at surface
    p_desc_park = np.linspace(10.0, 1000.0, n_each)
    p_drift = np.full(5, 1000.0)
    p_desc_prof = np.linspace(1000.0, 2000.0, n_each)
    p_ascent = np.linspace(2000.0, 5.0, n_each)
    p = np.concatenate([p_surface, p_desc_park, p_drift, p_desc_prof, p_ascent])
    bins = bin_cycle_samples(pres=p, park_pressure=1000.0)
    # surface sample goes SURFACE
    assert len(bins[MeasurementCodes.SURFACE]) >= 1
    # descent-to-park bucket non-empty
    assert len(bins[MeasurementCodes.PARK_DESCENT]) >= 1
    # drift-at-park bucket non-empty
    assert len(bins[MeasurementCodes.PARK_DRIFT]) >= 5
    # ascent samples present
    assert len(bins[MeasurementCodes.PROFILE_ASCENT]) >= 1
    # in-air / surface tail exists
    assert len(bins[MeasurementCodes.IN_AIR]) + len(bins[MeasurementCodes.SURFACE]) >= 1


def test_fill_samples_excluded():
    p = np.array([100.0, 9999.9, 200.0, 9999.9])
    bins = bin_cycle_samples(pres=p)
    total = sum(len(b) for b in bins.values())
    assert total == 2


def test_emergency_ascent_detection():
    """A sudden shoaling of >50 dbar before the deepest bin is flagged."""
    p = np.array([100.0, 200.0, 50.0, 800.0, 1000.0, 500.0, 100.0])
    bins = bin_cycle_samples(pres=p)
    assert len(bins[MeasurementCodes.EMERGENCY_ASCENT]) >= 1


def test_no_park_pressure_groups_all_descent():
    """When park_pressure is unknown, all pre-deepest samples go to a
    descent bin (either PARK_DESCENT or PROFILE_DESCENT)."""
    p_desc = np.linspace(10.0, 2000.0, 30)
    p_asc = np.linspace(2000.0, 10.0, 30)
    p = np.concatenate([p_desc, p_asc])
    bins = bin_cycle_samples(pres=p)
    n_descent = len(bins[MeasurementCodes.PARK_DESCENT]) + len(
        bins[MeasurementCodes.PROFILE_DESCENT]
    )
    assert n_descent == 29  # deepest is PARK_DRIFT
    assert len(bins[MeasurementCodes.PROFILE_ASCENT]) >= 20


def test_measurement_codes_constants():
    assert MeasurementCodes.PROFILE_ASCENT == 294
    assert MeasurementCodes.SURFACE == 290
    assert MeasurementCodes.IN_AIR == 295
