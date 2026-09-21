"""Phase 3 M4: unit tests for Aanderaa optode DOXY derivation."""

from __future__ import annotations

import numpy as np
import pytest

from argo_decoder.derived.doxy import (
    DOXY_FILL,
    OptodeCalibration,
    _potential_density_kg_l,
    _pressure_correction,
    _salinity_correction,
    _stern_volmer,
    compute_doxy,
    decode_optode_phase,
)

# Default calibration matches the demo WMO 6902892 optode.
_CAL = OptodeCalibration()


def test_doxy_fill_constant_sane() -> None:
    assert DOXY_FILL > 500.0  # clearly out of physical range (<600)


def test_optode_phase_from_counts() -> None:
    # (c - 20000) * 2 / 1000 degrees; c=20000 -> 0, c=25000 -> 10
    c1 = np.array([20000, 25000, 99999])
    c2 = np.array([20000, 20000, 20000])
    tphase = decode_optode_phase(c1, c2)
    assert np.isnan(tphase[2])
    assert tphase[0] == pytest.approx(0.0)
    assert tphase[1] == pytest.approx(10.0)


def test_stern_volmer_reduces_with_phase() -> None:
    """Higher (quenched) phase -> lower oxygen (Stern-Volmer)."""
    cal = _CAL
    p = np.array([0.0])
    t_opt = np.array([15.0])
    ph_lo = np.array([20.0])
    ph_hi = np.array([40.0])
    o2_lo = _stern_volmer(ph_lo, p, t_opt, cal)
    o2_hi = _stern_volmer(ph_hi, p, t_opt, cal)
    # both positive; higher phase (more quenching delay) -> lower O2
    assert o2_lo[0] > 0
    assert o2_hi[0] < o2_lo[0]


def test_pressure_correction_increases_doxy() -> None:
    molar = np.array([300.0])
    p = np.array([0.0, 2000.0])
    t = np.array([5.0, 5.0])
    out = _pressure_correction(np.tile(molar, 2), p, t)
    assert out[0] == pytest.approx(300.0)
    assert out[1] > out[0]


def test_salinity_correction_reduces_solubility() -> None:
    """Higher salinity -> lower dissolved oxygen (Garcia & Gordon)."""
    molar = np.array([300.0, 300.0])
    t = np.array([5.0, 5.0])
    s = np.array([0.0, 35.0])
    out = _salinity_correction(molar, t, s)
    assert out[0] > out[1]


def test_potential_density_positive() -> None:
    rho = _potential_density_kg_l(
        np.array([0.0, 1000.0]),
        np.array([15.0, 2.0]),
        np.array([35.0, 34.7]),
        lat=-47.0,
        lon=-47.0,
    )
    # surface density ~1.026 kg/L; deep ~1.035 kg/L
    assert 1.02 < rho[0] < 1.04
    assert 1.02 < rho[1] < 1.04
    assert rho[1] > rho[0]


def test_compute_doxy_full_chain_cycle86_recovery() -> None:
    """For the cycle-86 deep CTDO packet of WMO 6902892 (P≈3959-3999 dbar,
    T≈1.07-1.11 °C, S≈34.706 psu, observed optode counts from the demo
    corpus) DOXY should fall in the 180-220 μmol/kg range consistent with
    Southern Ocean deep waters.
    """
    doxy = compute_doxy(
        c1phase_counts=np.array([44219, 44234, 44238, 44242, 44242, 44244, 44244]),
        c2phase_counts=np.array([22032, 22035, 22035, 22037, 22034, 22035, 22034]),
        temp_doxy_counts=np.array([6084, 6088, 6092, 6099, 6103, 6113, 6119]),
        pres=np.array([3999.1, 3993.5, 3986.3, 3979.6, 3972.3, 3965.4, 3958.6]),
        temp_ctd=np.array([1.074, 1.078, 1.082, 1.089, 1.095, 1.103, 1.110]),
        psal=np.array([34.706, 34.706, 34.706, 34.706, 34.707, 34.707, 34.707]),
        latitude=-47.0,
        longitude=-47.12,
        cal=_CAL,
    )
    assert np.all(np.isfinite(doxy))
    # deep Southern Ocean oxygen is typically 180-220 μmol/kg in this
    # density class; assert a generous range that would catch obvious
    # scaling bugs without being overly prescriptive.
    assert doxy.min() > 150.0
    assert doxy.max() < 250.0
    # values should be roughly monotonic (decreasing pressure → higher O2)
    assert np.all(np.diff(doxy) > -5.0)


def test_compute_doxy_fill_samples_propagate_nan() -> None:
    doxy = compute_doxy(
        c1phase_counts=np.array([20000, 99999, 20000, 20000]),
        c2phase_counts=np.array([20000, 20000, 20000, 20000]),
        temp_doxy_counts=np.array([6000, 6000, 99999, 6000]),
        pres=np.array([10.0, 10.0, 10.0, 99999]),
        temp_ctd=np.array([10.0, 10.0, 10.0, 10.0]),
        psal=np.array([35.0, 35.0, 35.0, 35.0]),
        latitude=0.0,
        longitude=0.0,
    )
    assert np.isnan(doxy[1])
    assert np.isnan(doxy[2])
    assert np.isnan(doxy[3])
    assert np.isfinite(doxy[0])


def test_compute_doxy_rejects_length_mismatch() -> None:
    with pytest.raises(ValueError):
        compute_doxy(
            c1phase_counts=np.zeros(3),
            c2phase_counts=np.zeros(4),
            temp_doxy_counts=np.zeros(3),
            pres=np.zeros(3),
            temp_ctd=np.zeros(3),
            psal=np.zeros(3),
            latitude=0.0,
            longitude=0.0,
        )
