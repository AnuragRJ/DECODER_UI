"""Unit tests for Provor/Arvor profile metadata assembly.

Phase 2 Slice 3: covers JULD conversion, pressure-offset decode, GPS
priority fallback, and fill-value preservation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from argo_decoder.platforms.provor_ir_sbd.profile import (
    ProfileMeta,
    assemble_profile_meta,
    datetime_to_juld,
    juld_to_datetime,
)

# ---------------------------------------------------------------------------
# JULD round-trip
# ---------------------------------------------------------------------------


def test_juld_epoch_is_1950_01_01() -> None:
    anchor = datetime(1950, 1, 1, tzinfo=UTC)
    assert datetime_to_juld(anchor) == 0.0


def test_juld_known_value_2021_03_15() -> None:
    # 2021-03-15 06:11:06 UTC -> ~26006.2577 days since 1950-01-01 (verified
    # against MATLAB's datenum convention: datenum - 712224 == JULD).
    dt = datetime(2021, 3, 15, 6, 11, 6, tzinfo=UTC)
    juld = datetime_to_juld(dt)
    assert juld == pytest.approx(26006.25770833, abs=1e-6)


def test_juld_round_trip() -> None:
    dt = datetime(2021, 6, 1, 12, 30, 45, tzinfo=UTC)
    back = juld_to_datetime(datetime_to_juld(dt))
    assert back == dt


def test_juld_accepts_naive_datetime_as_utc() -> None:
    aware = datetime(2021, 3, 15, 6, 11, 6, tzinfo=UTC)
    naive = datetime(2021, 3, 15, 6, 11, 6)
    assert datetime_to_juld(naive) == pytest.approx(datetime_to_juld(aware), abs=1e-9)


# ---------------------------------------------------------------------------
# Pressure offset application
# ---------------------------------------------------------------------------


def test_pres_offset_zero_is_noop() -> None:
    meta = ProfileMeta(pres_offset_dbar=0.0)
    out = meta.apply_pres_offset([100.0, 200.0, 9999.9])
    assert out == [100.0, 200.0, 9999.9]


def test_pres_offset_subtracts_and_preserves_fill() -> None:
    meta = ProfileMeta(pres_offset_dbar=0.6)
    out = meta.apply_pres_offset([0.0, 100.5, 200.0, 9999.9])
    assert out == [-0.6, 99.9, 199.4, 9999.9]


def test_pres_offset_negative_adds_pressure() -> None:
    # -6 counts (0xFA) => raw -6 => signed -6 => -0.6 dbar is already tested
    # above; here test an overpressure (positive signed 8-bit) scenario.
    meta = ProfileMeta(pres_offset_dbar=-1.2)
    out = meta.apply_pres_offset([100.0, 9999.9])
    assert out == [101.2, 9999.9]


# ---------------------------------------------------------------------------
# assemble_profile_meta fallbacks
# ---------------------------------------------------------------------------


@dataclass
class _FakeTech1:
    gps_lat: float | None = None
    gps_lon: float | None = None
    float_time_elapsed_s: float | None = None
    trans_start_hour: int | None = None
    gps_day: int | None = None
    gps_month: int | None = None
    gps_year_offset: int | None = None
    fields: list[int] | None = None


_REF_DAY = datetime(2021, 3, 13, tzinfo=UTC)
_LAUNCH = datetime(2021, 3, 13, 2, 6, 0, tzinfo=UTC)


def test_assemble_empty_packets_falls_back_to_launch_date() -> None:
    meta = assemble_profile_meta(
        cycle_number=1,
        launch_date=_LAUNCH,
        reference_day=_REF_DAY,
        tech1_packets=[],
        email_session_fixes=[],
    )
    assert meta.cycle_number == 1
    # Lat/lon unset -> encoded as NaN by writer.
    assert meta.latitude is None
    assert meta.longitude is None
    assert meta.position_qc == b"0"
    assert meta.position_system == "GPS"
    # JULD equals launch date.
    assert meta.juld == pytest.approx(datetime_to_juld(_LAUNCH), abs=1e-9)
    assert meta.pres_offset_dbar == 0.0


def test_assemble_prefers_tech1_gps_over_email_fallback() -> None:
    tech = _FakeTech1(gps_lat=-47.0, gps_lon=-47.5, float_time_elapsed_s=30646.0, fields=[0] * 50)
    email_dt = datetime(2021, 3, 15, 6, 11, 6, tzinfo=UTC)
    meta = assemble_profile_meta(
        cycle_number=5,
        launch_date=_LAUNCH,
        reference_day=_REF_DAY,
        tech1_packets=[tech],
        email_session_fixes=[(-40.0, -40.0, email_dt)],
    )
    assert meta.latitude == -47.0
    assert meta.longitude == -47.5
    assert meta.position_system == "GPS"
    assert meta.position_qc == b"1"
    # JULD computed from ref_day + 30646 s = 2021-03-13 08:30:46 UTC.
    expected = datetime_to_juld(datetime(2021, 3, 13, 8, 30, 46, tzinfo=UTC))
    assert meta.juld == pytest.approx(expected, abs=1e-9)


def test_assemble_email_fallback_when_no_tech1_gps() -> None:
    email_dt = datetime(2021, 3, 15, 6, 11, 6, tzinfo=UTC)
    meta = assemble_profile_meta(
        cycle_number=86,
        launch_date=_LAUNCH,
        reference_day=_REF_DAY,
        tech1_packets=[],
        email_session_fixes=[(-47.00071, -47.1211, email_dt)],
    )
    assert meta.latitude == pytest.approx(-47.00071)
    assert meta.longitude == pytest.approx(-47.1211)
    assert meta.position_system == "IRIDIUM"
    assert meta.position_qc == b"0"
    assert meta.juld == pytest.approx(26006.25770833, abs=1e-6)


def test_assemble_pressure_offset_signed_decode_0xfa() -> None:
    """tabTech1 field 44 = 0xFA (-6) should decode to -0.6 dbar."""
    fields = [0] * 50
    fields[44] = 0xFA  # =250; signed 8-bit = -6; offset -0.6 dbar
    tech = _FakeTech1(gps_lat=None, gps_lon=None, float_time_elapsed_s=None, fields=fields)
    meta = assemble_profile_meta(
        cycle_number=3,
        launch_date=_LAUNCH,
        reference_day=_REF_DAY,
        tech1_packets=[tech],
        email_session_fixes=[],
    )
    assert meta.pres_offset_dbar == pytest.approx(-0.6)


def test_assemble_pressure_offset_positive_signed() -> None:
    fields = [0] * 50
    fields[44] = 6  # raw +6 => +0.6 dbar (atmospheric overpressure)
    tech = _FakeTech1(gps_lat=None, gps_lon=None, float_time_elapsed_s=None, fields=fields)
    meta = assemble_profile_meta(
        cycle_number=4,
        launch_date=_LAUNCH,
        reference_day=_REF_DAY,
        tech1_packets=[tech],
        email_session_fixes=[],
    )
    assert meta.pres_offset_dbar == pytest.approx(0.6)


def test_assemble_picks_last_tech1_gps() -> None:
    """When multiple tech#1 packets are present the last GPS wins."""
    t1 = _FakeTech1(gps_lat=10.0, gps_lon=20.0, float_time_elapsed_s=100.0, fields=[0] * 50)
    t2 = _FakeTech1(gps_lat=11.0, gps_lon=21.0, float_time_elapsed_s=20000.0, fields=[0] * 50)
    meta = assemble_profile_meta(
        cycle_number=6,
        launch_date=_LAUNCH,
        reference_day=_REF_DAY,
        tech1_packets=[t1, t2],
        email_session_fixes=[],
    )
    assert meta.latitude == 11.0
    assert meta.longitude == 21.0
    # best_gps_time uses t2's elapsed seconds.
    expected = datetime_to_juld(_REF_DAY) + 20000.0 / 86400.0
    assert meta.juld == pytest.approx(expected, abs=1e-9)


def test_assemble_defaults_direction_data_mode() -> None:
    meta = assemble_profile_meta(
        cycle_number=1,
        launch_date=_LAUNCH,
        reference_day=_REF_DAY,
        tech1_packets=[],
        email_session_fixes=[],
    )
    assert meta.direction == "A"
    assert meta.data_mode == "A"
