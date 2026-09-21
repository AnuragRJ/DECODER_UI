"""Unit tests for derived.density (TEOS-10 potential / in-situ density)."""

from __future__ import annotations

import numpy as np
import pytest

from argo_decoder.derived.density import (
    DENSITY_FILL,
    in_situ_density,
    potential_density,
    sigma0,
)


def test_potential_density_tropical_surface_is_physical():
    """Tropical surface water: SA ~35, T ~25°C -> sigma0 ≈ 23 kg/m³."""
    rho = potential_density(
        np.array([0.0]),
        np.array([25.0]),
        np.array([35.0]),
        ref_pres=0.0,
        lon=-30.0,
        lat=10.0,
    )
    # sigma0 ~= 23.2 -> rho ~= 1023.2 kg/m³
    assert 1020.0 < float(rho[0]) < 1026.0


def test_sigma0_deep_water():
    """Cold, salty deep water is denser."""
    s = sigma0(
        np.array([2000.0]),
        np.array([2.0]),
        np.array([34.9]),
        lon=-30.0,
        lat=40.0,
    )
    # North-Atlantic-deep-Water-ish sigma0 ~ 27.8
    assert 27.0 < float(s[0]) < 28.5


def test_potential_density_round_trip_in_situ_at_ref_pres():
    """When ref_pres == pres for every level, potential == in-situ density."""
    p = np.linspace(0.0, 4000.0, 20)
    t = np.linspace(20.0, 2.0, 20)
    s = np.linspace(35.5, 34.9, 20)
    rho_pot = potential_density(p, t, s, ref_pres=p, lon=-25.0, lat=35.0)
    rho_ins = in_situ_density(p, t, s, lon=-25.0, lat=35.0)
    np.testing.assert_allclose(rho_pot, rho_ins, rtol=1e-10)


def test_pressure_clamp_negative_pres_near_surface():
    """-5 <= p < 0 is clamped to 0 (MATLAB parity)."""
    rho_neg = potential_density(
        np.array([-2.0]),
        np.array([15.0]),
        np.array([35.0]),
        ref_pres=0.0,
        lon=0.0,
        lat=45.0,
    )
    rho_zero = potential_density(
        np.array([0.0]),
        np.array([15.0]),
        np.array([35.0]),
        ref_pres=0.0,
        lon=0.0,
        lat=45.0,
    )
    np.testing.assert_allclose(rho_neg, rho_zero, rtol=1e-10)


def test_invalid_pressure_propagates_nan():
    """p < -5 or p > 11000 -> NaN density."""
    rho = potential_density(
        np.array([-10.0, 12000.0, 100.0]),
        np.array([15.0, 15.0, 15.0]),
        np.array([35.0, 35.0, 35.0]),
        ref_pres=0.0,
        lon=0.0,
        lat=45.0,
    )
    assert np.isnan(rho[0])
    assert np.isnan(rho[1])
    assert np.isfinite(rho[2])


def test_fill_and_nan_inputs_propagate_nan():
    """NaN/fill T/S produce NaN density without crashing."""
    rho = potential_density(
        np.array([10.0, 10.0, 10.0]),
        np.array([np.nan, 99.999, 15.0]),
        np.array([35.0, 99.999, np.nan]),
        ref_pres=0.0,
        lon=0.0,
        lat=45.0,
    )
    assert np.isnan(rho[0])
    assert np.isnan(rho[1])
    assert np.isnan(rho[2])


def test_potential_density_shape_mismatch_raises():
    with pytest.raises(ValueError):
        potential_density(
            np.array([0.0, 100.0]),
            np.array([15.0, 10.0]),
            np.array([35.0, 35.0]),
            ref_pres=np.array([0.0]),
            lon=0.0,
            lat=45.0,
        )


def test_density_fill_constant():
    # Constant should match the Argo-idiomatic sentinel (large, > real values).
    assert DENSITY_FILL > 1000.0
