"""Unit tests for Provor/Arvor mission configuration and ascent timing.

Phase 2 Slice 4: covers MissionConfig seeding, PARAM updates, transStart
date alignment, and the ascent-end offset formula.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from argo_decoder.platforms.provor_ir_sbd.mission import (
    MissionConfig,
    compute_ascent_end_offset_minutes,
    compute_profile_datetime,
    compute_trans_start_date,
)

# ---------------------------------------------------------------------------
# MissionConfig
# ---------------------------------------------------------------------------


def test_mission_config_defaults_match_cts4_fastpath() -> None:
    cfg = MissionConfig()
    # Default PT04=180s, no in-air (PT33=1 -> every cycle in air, but defaults
    # PT31=5 and PT32=330s produce the 25-min offset typical for CTS4).
    assert cfg.pt04_centisec == 18000
    assert cfg.pt31_min == 5
    assert cfg.pt32_centisec == 33000
    assert cfg.pt33_cycles == 1
    assert cfg.updates == 0


def test_mission_config_seed_from_meta_kv() -> None:
    cfg = MissionConfig()
    cfg.seed_from_meta(
        {
            "CONFIG_PT04_BuoyancyDur": "28000",
            "CONFIG_PT31_InAirDurMin": "5",
            "CONFIG_PT32_InAirBuoy": "33000",
            "CONFIG_PT33_InAirPeriod": "1",
            "IGNORED_KEY": "999",
        }
    )
    assert cfg.pt04_centisec == 28000
    assert cfg.pt31_min == 5
    assert cfg.pt32_centisec == 33000
    assert cfg.pt33_cycles == 1


def test_mission_config_seed_tolerates_bad_values() -> None:
    cfg = MissionConfig()
    cfg.seed_from_meta({"CONFIG_PT04": "nan", "CONFIG_PT31": None, "CONFIG_PT32": ""})
    # Defaults unchanged.
    assert cfg.pt04_centisec == 18000


def test_mission_config_apply_param1_last_wins() -> None:
    cfg = MissionConfig()
    cfg.apply_param1(pt04_centisec=22000, pt31_min=3, pt32_centisec=30000, pt33_cycles=10)
    assert cfg.pt04_centisec == 22000
    assert cfg.pt31_min == 3
    assert cfg.pt33_cycles == 10
    assert cfg.updates == 1
    cfg.apply_param1(pt04_centisec=None, pt31_min=4, pt32_centisec=None, pt33_cycles=None)
    # None leaves value unchanged.
    assert cfg.pt04_centisec == 22000
    assert cfg.pt31_min == 4
    assert cfg.updates == 2


# ---------------------------------------------------------------------------
# Trans-start date
# ---------------------------------------------------------------------------


def test_trans_start_date_hours_before_gps() -> None:
    gps = datetime(2021, 3, 15, 6, 11, 6, tzinfo=UTC)
    # trans hour 6 -> 06:00 on the same day, before GPS 06:11
    assert compute_trans_start_date(gps, 6) == datetime(2021, 3, 15, 6, 0, tzinfo=UTC)


def test_trans_start_date_wraps_to_previous_day() -> None:
    """If transHour/24 is after the GPS fix, MATLAB subtracts a day (the
    transmission hour refers to midnight prior to the fix)."""
    gps = datetime(2021, 3, 15, 1, 0, 0, tzinfo=UTC)
    # trans hour 23 -> 23:00 *previous* day (03-14)
    assert compute_trans_start_date(gps, 23) == datetime(2021, 3, 14, 23, 0, tzinfo=UTC)


def test_trans_start_date_invalid_hour_returns_none() -> None:
    gps = datetime(2021, 3, 15, 6, 0, tzinfo=UTC)
    assert compute_trans_start_date(gps, None) is None
    assert compute_trans_start_date(gps, 25) is None


# ---------------------------------------------------------------------------
# Ascent-end offset
# ---------------------------------------------------------------------------


def test_ascent_end_offset_no_inair() -> None:
    cfg = MissionConfig(pt04_centisec=18000, pt33_cycles=9999)  # never in-air
    off = compute_ascent_end_offset_minutes(1, cfg)
    # 10 min wait + round(18000/100/60) = 10 + 3 = 13 min
    assert off == pytest.approx(13.0)


def test_ascent_end_offset_inair_path() -> None:
    cfg = MissionConfig(
        pt04_centisec=18000,
        pt31_min=5,
        pt32_centisec=33000,
        pt33_cycles=1,
    )
    off = compute_ascent_end_offset_minutes(1, cfg)  # in-air cycle
    # 10 min + 2*5 + round(33000/100/60) = 10 + 10 + 6 = 26 min
    assert off == pytest.approx(26.0)


def test_ascent_end_offset_inair_periodicity() -> None:
    cfg = MissionConfig(pt31_min=5, pt32_centisec=33000, pt33_cycles=5, pt04_centisec=18000)
    # cycle 5 (mod 5 == 0) -> in-air path
    assert compute_ascent_end_offset_minutes(5, cfg) == pytest.approx(26.0)
    # cycle 4 (mod 5 != 0) -> PT04 path
    assert compute_ascent_end_offset_minutes(4, cfg) == pytest.approx(13.0)


# ---------------------------------------------------------------------------
# Profile datetime priority
# ---------------------------------------------------------------------------


def test_profile_datetime_prefers_ascent_end() -> None:
    cfg = MissionConfig(pt04_centisec=18000, pt33_cycles=9999)
    gps = datetime(2021, 3, 15, 6, 11, tzinfo=UTC)
    dt, source, qc = compute_profile_datetime(
        cycle_number=1,
        mission=cfg,
        gps_date=gps,
        trans_start_hour=6,
        email_session_dt=None,
        launch_date=datetime(2021, 3, 13, tzinfo=UTC),
    )
    assert source == "GPS_ASCENT_END"
    assert qc == b"1"
    # transStart = 06:00, offset 13 min -> ascentEnd = 05:47
    assert dt == datetime(2021, 3, 15, 5, 47, tzinfo=UTC)


def test_profile_datetime_falls_back_to_gps_when_trans_hour_unknown() -> None:
    cfg = MissionConfig()
    gps = datetime(2021, 3, 15, 6, 11, tzinfo=UTC)
    dt, source, qc = compute_profile_datetime(
        cycle_number=1,
        mission=cfg,
        gps_date=gps,
        trans_start_hour=None,
        email_session_dt=None,
        launch_date=datetime(2021, 1, 1, tzinfo=UTC),
    )
    assert source == "GPS_FIX"
    assert qc == b"1"
    assert dt == gps


def test_profile_datetime_iridium_fallback() -> None:
    cfg = MissionConfig()
    email = datetime(2021, 3, 15, 6, 11, 6, tzinfo=UTC)
    dt, source, qc = compute_profile_datetime(
        cycle_number=86,
        mission=cfg,
        gps_date=None,
        trans_start_hour=None,
        email_session_dt=email,
        launch_date=datetime(2021, 3, 13, tzinfo=UTC),
    )
    assert source == "IRIDIUM_SESSION"
    assert qc == b"0"
    assert dt == email


def test_profile_datetime_launch_fallback() -> None:
    cfg = MissionConfig()
    launch = datetime(2021, 3, 13, 2, 6, tzinfo=UTC)
    dt, source, qc = compute_profile_datetime(
        cycle_number=1,
        mission=cfg,
        gps_date=None,
        trans_start_hour=None,
        email_session_dt=None,
        launch_date=launch,
    )
    assert source == "LAUNCH_DATE"
    assert qc == b"0"
    assert dt == launch
