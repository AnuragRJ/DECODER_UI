"""Unit tests for RTQC TEST001/002/003 (profile-scalar checks)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from argo_decoder.rtqc.profile_scalar import run_profile_scalar_tests


def test_known_platform_valid_date_valid_location_passes():
    # Demo WMO 6902892 cycle 86 ~2021-03-15
    juld = 26006.2577
    r = run_profile_scalar_tests(
        juld=juld,
        latitude=-47.014,
        longitude=-47.060,
        platform_known=True,
        now_utc=datetime(2026, 7, 20, tzinfo=UTC),
    )
    assert r.juld_qc == b"1"
    assert r.position_qc == b"1"
    assert "TEST002_IMPOSSIBLE_DATE" not in r.tests_failed
    assert "TEST003_IMPOSSIBLE_LOCATION" not in r.tests_failed


def test_unknown_platform_is_recorded_but_does_not_downgrade_qc():
    r = run_profile_scalar_tests(juld=26006.0, latitude=0.0, longitude=0.0, platform_known=False)
    assert "TEST001_PLATFORM_IDENTIFICATION" in r.tests_failed
    # scalar QCs not affected by TEST001 failure (Argo convention)
    assert r.juld_qc == b"1"
    assert r.position_qc == b"1"


def test_juld_before_1997_is_bad():
    # 1996-01-01 in JULD days since 1950-01-01 ≈ 16801 days
    r = run_profile_scalar_tests(
        juld=16801.0,
        latitude=0.0,
        longitude=0.0,
        now_utc=datetime(2026, 7, 20, tzinfo=UTC),
    )
    assert r.juld_qc == b"4"
    assert "TEST002_IMPOSSIBLE_DATE" in r.tests_failed


def test_juld_in_future_is_bad():
    # year 2100 is well beyond any plausible float lifetime
    future_juld = (
        datetime(2100, 1, 1, tzinfo=UTC) - datetime(1950, 1, 1, tzinfo=UTC)
    ).total_seconds() / 86400.0
    r = run_profile_scalar_tests(
        juld=future_juld,
        latitude=0.0,
        longitude=0.0,
        now_utc=datetime(2026, 7, 20, tzinfo=UTC),
    )
    assert r.juld_qc == b"4"
    assert "TEST002_IMPOSSIBLE_DATE" in r.tests_failed


def test_missing_juld_is_missing_qc():
    r = run_profile_scalar_tests(juld=None, latitude=0.0, longitude=0.0)
    # Argo reference table 2 / MATLAB g_decArgo_qcStrMissing = '9'
    assert r.juld_qc == b"9"


def test_latitude_out_of_range_is_bad():
    r = run_profile_scalar_tests(juld=26006.0, latitude=91.0, longitude=0.0)
    assert r.position_qc == b"4"
    assert "TEST003_IMPOSSIBLE_LOCATION" in r.tests_failed


@pytest.mark.parametrize("lat,lon", [(91.0, 0.0), (-91.0, 0.0), (0.0, 181.0), (0.0, -181.0)])
def test_out_of_range_lat_lon_flagged(lat: float, lon: float) -> None:
    r = run_profile_scalar_tests(juld=26006.0, latitude=lat, longitude=lon)
    assert r.position_qc == b"4"
    assert "TEST003_IMPOSSIBLE_LOCATION" in r.tests_failed


def test_missing_location_is_missing_qc():
    r = run_profile_scalar_tests(juld=26006.0, latitude=None, longitude=None)
    assert r.position_qc == b"9"


def test_existing_bad_qc_preserved_worst_flag_wins():
    # If the position QC was already BAD for another reason we do not
    # downgrade it further; if it is GOOD we only promote to BAD.
    r = run_profile_scalar_tests(
        juld=26006.0,
        latitude=0.0,
        longitude=0.0,
        juld_qc_in=b"4",
        position_qc_in=b"3",
    )
    assert r.juld_qc == b"4"
    assert r.position_qc == b"3"


def test_tests_done_list_includes_all_three():
    r = run_profile_scalar_tests(juld=26006.0, latitude=0.0, longitude=0.0)
    assert set(r.tests_done) == {
        "TEST001_PLATFORM_IDENTIFICATION",
        "TEST002_IMPOSSIBLE_DATE",
        "TEST003_IMPOSSIBLE_LOCATION",
    }
