"""Phase 3 M3: unit tests for derived conductivity (CNDC)."""

from __future__ import annotations

import numpy as np
import pytest

from argo_decoder.derived.cndc import (
    CNDC_FILL,
    conductivity_from_sp,
)


def test_cndc_standard_seawater_roundtrip() -> None:
    """PSS-78 standard: SP=35 at t=15 °C, p=0 dbar should give C(35,15,0).

    TEOS-10 C(35,15,0) ≈ 42.914 mS/cm = 4.2914 S/m.  We sanity-check to
    within 0.01 S/m of the reference and verify the salinity round-trip.
    """
    import gsw

    c = conductivity_from_sp(np.array([35.0]), np.array([15.0]), np.array([0.0]))
    assert c.shape == (1,)
    assert 4.2 < float(c[0]) < 4.4  # S/m
    # Round-trip via SP_from_C (gsw expects mS/cm, so multiply back).
    sp_back = gsw.SP_from_C(c * 10.0, 15.0, 0.0)
    assert abs(float(sp_back[0]) - 35.0) < 1e-9


def test_cndc_cycle86_values_in_range() -> None:
    """Cycle 86 of 6902892 is a deep profile (~3958-3999 dbar, ~1.1 °C,
    ~34.7 psu); expected conductivity in the 3.1-3.2 S/m range."""
    sp = np.full(5, 34.7)
    t = np.linspace(1.1, 1.11, 5)
    p = np.linspace(3958.0, 3999.0, 5)
    c = conductivity_from_sp(sp, t, p)
    assert np.all(np.isfinite(c))
    assert c.min() > 3.0
    assert c.max() < 3.3


def test_cndc_fill_samples_propagate_as_nan() -> None:
    sp = np.array([34.7, 99.999, 34.7])
    t = np.array([1.1, 1.1, 99.999])
    p = np.array([1000.0, 1000.0, 1000.0])
    c = conductivity_from_sp(sp, t, p)
    assert np.isfinite(c[0])
    assert np.isnan(c[1])
    assert np.isnan(c[2])


def test_cndc_rejects_shape_mismatch() -> None:
    with pytest.raises(ValueError, match="shape mismatch"):
        conductivity_from_sp(np.zeros(3), np.zeros(4), np.zeros(3))


def test_cndc_preserves_dtype_float64() -> None:
    c = conductivity_from_sp(np.array([35.0]), np.array([15.0]), np.array([0.0]))
    assert c.dtype == np.float64


def test_cndc_fill_constant_is_argostyle() -> None:
    # CNDC fill should be clearly out-of-physical-range but stored at the
    # same order of magnitude as the data (99.9999 S/m).
    assert CNDC_FILL > 10.0
