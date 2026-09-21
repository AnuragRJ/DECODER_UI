"""Unit tests for the CTD sensor fast-path conversion (Phase 2 Slice 2).

Conversions are taken verbatim from the MATLAB reference for decoder_ids
201-232 (CTS4 Iridium SBD):
- Pressure : (twos_complement_16(count) + 30000) / 10
- Temperature: twos_complement_16(count) / 1000
- Salinity : (count + 10000) / 1000
- Count 99999 maps to the Argo fill value.
"""

from __future__ import annotations

import pytest

from argo_decoder.sensors import (
    COUNT_FILL,
    PRES_FILL,
    PSAL_FILL,
    TEMP_FILL,
    CtdCalibration,
    CtdProfile,
    convert_counts,
    decode_pres,
    decode_psal,
    decode_temp,
)


def test_calibration_defaults() -> None:
    cal = CtdCalibration()
    assert cal.p_a0 == 0.0
    assert cal.t_a0 == 0.0
    assert cal.c_g == 0.0
    assert cal.serial_number == ""


# --- scalar conversions -----------------------------------------------------


def test_pressure_surface() -> None:
    # Surface bin observed in the demo data: pres_cnt=35538
    # two's-complement: 35538 - 65536 = -29998; (-29998 + 30000)/10 = 0.2 dbar
    assert decode_pres(35538) == pytest.approx(0.2)


def test_pressure_deep() -> None:
    # 2500 dbar -> (p + 30000)/10 = 2500 -> p = -5000 -> unsigned = 60536
    assert decode_pres(60536) == pytest.approx(2500.0)


def test_pressure_fill_value() -> None:
    assert decode_pres(COUNT_FILL) == PRES_FILL


def test_temperature_surface() -> None:
    # Surface ~15.5 degC -> 15500 counts
    assert decode_temp(15500) == pytest.approx(15.5)


def test_temperature_negative() -> None:
    # -2 degC = -2000 signed -> unsigned = 63536
    assert decode_temp(63536) == pytest.approx(-2.0)


def test_temperature_fill() -> None:
    assert decode_temp(COUNT_FILL) == TEMP_FILL


def test_salinity() -> None:
    # 35.0 psu -> (s+10000)/1000 = 35 -> s = 25000
    assert decode_psal(25000) == pytest.approx(35.0)


def test_salinity_fill() -> None:
    assert decode_psal(COUNT_FILL) == PSAL_FILL


# --- vector conversion -----------------------------------------------------


def test_convert_counts_profile() -> None:
    # Simulate 3 bins: surface (~5 dbar, 15 degC, 35 psu), 500 dbar, fill.
    # 5 dbar -> signed = 5*10 - 30000 = -29950 -> unsigned 35586
    # 500 dbar -> signed = 500*10 - 30000 = -25000 -> unsigned 40536
    # 15 degC -> 15000 counts; 10 degC -> 10000 counts
    # 35 psu -> 25000; 34 psu -> 24000
    prof = convert_counts(
        pres_counts=[35586, 40536, COUNT_FILL],
        temp_counts=[15000, 10000, COUNT_FILL],
        sal_counts=[25000, 24000, COUNT_FILL],
    )
    assert isinstance(prof, CtdProfile)
    assert prof.pressure_dbar == pytest.approx([5.0, 500.0, PRES_FILL])
    assert prof.temperature_deg_c == pytest.approx([15.0, 10.0, TEMP_FILL])
    assert prof.salinity_psu == pytest.approx([35.0, 34.0, PSAL_FILL])


def test_convert_counts_no_salinity() -> None:
    prof = convert_counts(pres_counts=[35586], temp_counts=[15000], sal_counts=None)
    assert len(prof.salinity_psu) == 1
    assert prof.salinity_psu[0] == PSAL_FILL
