"""Profile-only Float Status contract. Network-free regression tests.

Real-WMO fixture values were independently extracted from public Ifremer
<WMO>_prof.nc products; edge-case NetCDF data is explicitly synthetic and
written only into pytest's temporary directories. No decoder core is changed.
"""

from __future__ import annotations

import copy
import json
import math
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

# See tests/conftest.py: runtime state must be redirected before the service is
# imported, otherwise this module writes into the repository's data directory.
_TMP = tempfile.mkdtemp(prefix="decoder-ui-recency-test-")
os.environ["ARGO_UI_DATA_DIR"] = _TMP

import fleet_status as fs  # noqa: E402
import netCDF4
import pytest
from test_fleet_status import _fake_gdac, _juld, _reg, _write_profile
from test_fleet_status_audit import _multi_profile

NOW = datetime(2026, 9, 21, 12, tzinfo=UTC)
FIXTURE = json.loads((Path(__file__).parent / "fixtures/fleet_profile_recency.json").read_text())
MONITOR_FIELDS = (
    "last_profile_iso",
    "last_profile_juld",
    "expected_next_profile_iso",
    "days_since_last_profile",
    "approx_profiles_missed",
    "data_status",
)


def history(juld, wmo=2909999):
    return {
        "platform_number": str(wmo),
        "file": f"{wmo}_prof.nc",
        "juld": juld,
        "measurement_index": 0,
        "measurement_cycle": 2,
    }


def row(aggregate=None, wmo=2909999):
    return {
        "wmo": wmo,
        "in_incois_dac": True,
        "parser_version": fs.PARSER_VERSION,
        "profile_recency_version": fs.PROFILE_RECENCY_VERSION,
        "checked_at": NOW.isoformat(),
        "profile_checked_at": NOW.isoformat(),
        "profile_aggregate": aggregate,
        "profile_aggregate_fp": "test",
        "rtraj": {},
        "profiles": {"max_cycle": 25, "available_cycles": 24, "missing": [22]},
    }


def serve(source, wmo=2909999):
    return fs.FleetSyncRegistry._serve_row(wmo, source, {"platform_type": "APEX"}, {}, NOW)


@pytest.mark.parametrize("entry", FIXTURE["floats"], ids=lambda r: str(r["wmo"]))
def test_real_published_profile_chain_all_30_wmos(entry):
    w = entry["wmo"]
    aggregate = history(entry["juld"], w) if entry["http_status"] == 200 else None
    source = row(aggregate, w)
    source["profiles"] = {
        "max_cycle": entry["inventory_max_cycle"],
        "missing": entry["inventory_gap_cycles"],
    }
    source["rtraj"] = {
        "last_tx_iso": entry["recorded_rtraj_date"],
        "last_tx_field": "JULD_LAST_MESSAGE",
    }
    if entry["http_status"] == 404:
        source["in_incois_dac"] = False
    got = serve(source, w)
    assert got["last_profile_iso"] == entry["expected_iso"]
    if entry["expected_iso"] is None:
        assert got["data_status"] == "NO DATA"
        assert all(got[k] is None for k in MONITOR_FIELDS if k != "data_status")
        return
    date = datetime.fromisoformat(entry["expected_iso"])
    days = (NOW - date).total_seconds() / 86400
    assert got["expected_next_profile_iso"] == (date + timedelta(days=10)).isoformat()
    assert got["days_since_last_profile"] == days
    assert got["approx_profiles_missed"] == math.floor(days / 10)
    expected_status = (
        fs.STATUS_RECENT
        if days <= 10
        else fs.STATUS_OVERDUE
        if days < 60
        else fs.STATUS_NO_RECENT_60
    )
    assert got["data_status"] == expected_status
    # Exact published gaps remain independent internal inventory information.
    assert got["profiles_missing_list"] == entry["inventory_gap_cycles"]
    assert "last_tx_iso" not in got and "days_since_last_tx" not in got


@pytest.mark.parametrize(
    "days,status,missed",
    [
        (0, fs.STATUS_RECENT, 0),
        (9.999999, fs.STATUS_RECENT, 0),
        (10, fs.STATUS_RECENT, 1),
        (10.000001, fs.STATUS_OVERDUE, 1),
        (19.999999, fs.STATUS_OVERDUE, 1),
        (20, fs.STATUS_OVERDUE, 2),
        (59.999999, fs.STATUS_OVERDUE, 5),
        (60, fs.STATUS_NO_RECENT_60, 6),
        (120, fs.STATUS_NO_RECENT_60, 12),
    ],
)
def test_exact_boundaries_unrounded_days_and_floor_estimate(days, status, missed):
    got = serve(row(history(_juld(NOW - timedelta(days=days)))))
    assert got["data_status"] == status
    assert got["days_since_last_profile"] == pytest.approx(days, abs=1e-8)
    assert got["approx_profiles_missed"] == missed


@pytest.mark.parametrize(
    "message", [None, "1950-01-01T00:00:00Z", "2026-09-21T12:00:00Z", "2099-01-01T00:00:00Z"]
)
def test_trajectory_message_never_drives_profile_monitoring(message):
    source = row(history(_juld(NOW - timedelta(days=12))))
    expected = serve(source)
    source["rtraj"] = {
        "last_tx_field": "JULD_LAST_MESSAGE",
        "last_tx_iso": message,
        "last_tx_juld": _juld(NOW),
        "last_tx_status_rt19": "4",
    }
    got = serve(source)
    assert {k: got[k] for k in MONITOR_FIELDS} == {k: expected[k] for k in MONITOR_FIELDS}
    assert got["data_status"] == fs.STATUS_OVERDUE


def test_no_fallback_to_individual_profile_location_or_processing_date():
    source = row()
    source["updated_at"] = NOW.isoformat()
    source["rtraj"] = {"last_tx_field": "JULD_LAST_MESSAGE", "last_tx_iso": NOW.isoformat()}
    source["profiles"].update(
        latest={"file": "R2909999_025.nc", "cycle": 25},
        latest_parse={"juld": _juld(NOW), "juld_iso": NOW.isoformat()},
    )
    got = serve(source)
    assert got["data_status"] == "NO DATA"
    assert got["last_profile_iso"] is None
    assert got["expected_next_profile_iso"] is None
    assert got["days_since_last_profile"] is None
    assert got["approx_profiles_missed"] is None
    source["profile_aggregate"] = dict(
        history(None), position_juld=_juld(NOW), position_iso=NOW.isoformat()
    )
    assert serve(source)["data_status"] == "NO DATA"


@pytest.mark.parametrize(
    "override",
    [
        {"file": "R2909999_025.nc"},
        {"file": "2909999_Rtraj.nc"},
        {"platform_number": "1900000"},
        {"platform_number": ""},
    ],
)
def test_cached_profile_product_identity_must_match(override):
    h = history(_juld(NOW - timedelta(days=1)))
    h.update(override)
    assert serve(row(h))["data_status"] == "NO DATA"


def test_maximum_juld_is_not_last_array_entry_or_largest_cycle(tmp_path):
    j = _juld(NOW)
    raw = _multi_profile(
        tmp_path / "history.nc",
        [1] * 6,
        [65] * 6,
        [j - 20] * 6,
        juld=[j - 30, 999999, j - 2, j + 30, float("nan"), j - 10],
        cycles=[100, 101, 2, 102, 103, 99],
    )
    parsed = fs.parse_profile(raw, 2909999, None, NOW)
    assert parsed["juld"] == j - 2 and parsed["measurement_index"] == 2
    assert parsed["measurement_cycle"] == 2
    parsed["file"] = "2909999_prof.nc"
    got = serve(row(parsed))
    assert got["data_status"] == fs.STATUS_RECENT
    assert got["approx_profiles_missed"] == 0
    assert got["prof_num"] == 25  # Inventory remains independent.


def test_all_missing_juld_does_not_clear_independently_verified_coordinates(tmp_path):
    j = _juld(NOW)
    raw = _multi_profile(tmp_path / "fill.nc", [10], [65], [j - 1], juld=[999999])
    parsed = fs.parse_profile(raw, 2909999, None, NOW)
    parsed["file"] = "2909999_prof.nc"
    got = serve(row(parsed))
    assert got["last_profile_iso"] is None and got["data_status"] == "NO DATA"
    assert (got["lat"], got["lon"]) == (10, 65)


def test_profile_date_does_not_depend_on_position_quality(tmp_path):
    raw = _multi_profile(tmp_path / "bad-location.nc", [10], [65], [_juld(NOW) - 1], qc=["4"])
    parsed = fs.parse_profile(raw, 2909999, None, NOW)
    parsed["file"] = "2909999_prof.nc"
    got = serve(row(parsed))
    assert got["data_status"] == fs.STATUS_RECENT and got["lat"] is None


def test_invalid_location_time_units_do_not_destroy_valid_profile_date(tmp_path):
    file = tmp_path / "loc-units.nc"
    _write_profile(file, juld=_juld(NOW) - 1, lat=10, lon=65)
    with netCDF4.Dataset(file, "a") as ds:
        ds["JULD_LOCATION"].units = "wrong unit"
    parsed = fs.parse_profile(file.read_bytes(), 2909999, None, NOW)
    parsed["file"] = "2909999_prof.nc"
    got = serve(row(parsed))
    assert got["data_status"] == fs.STATUS_RECENT
    assert got["lat"] is None and "unsupported time units" in got["position_error"]


def test_profile_time_units_and_dimension_are_checked(tmp_path):
    file = tmp_path / "units.nc"
    _write_profile(file, juld=_juld(NOW) - 1)
    with netCDF4.Dataset(file, "a") as ds:
        ds["JULD"].units = "hours since 1970-01-01"
    with pytest.raises(fs.FloatSyncError, match="time units"):
        fs.parse_profile(file.read_bytes(), 2909999, None, NOW)
    _write_profile(file, juld=_juld(NOW) - 1)
    with netCDF4.Dataset(file, "a") as ds:
        ds.renameDimension("N_PROF", "N_OTHER")
    with pytest.raises(fs.FloatSyncError, match="N_PROF"):
        fs.parse_profile(file.read_bytes(), 2909999, None, NOW)


def test_profile_units_missing_is_not_assumed_to_be_unix_or_local_time(tmp_path):
    file = tmp_path / "missing-units.nc"
    _write_profile(file, juld=_juld(NOW) - 1)
    with netCDF4.Dataset(file, "a") as ds:
        ds["JULD"].delncattr("units")
    with pytest.raises(fs.FloatSyncError, match="time units"):
        fs.parse_profile(file.read_bytes(), 2909999, None, NOW)


def test_primary_profile_refresh_succeeds_when_rtraj_is_absent(tmp_path, monkeypatch):
    fake, reg = _fake_gdac(tmp_path), _reg(tmp_path)
    fake.rtraj = {}
    fake.mdtms.pop("2909999_Rtraj.nc")
    monkeypatch.setattr(reg, "_connect", lambda: fake)
    assert reg.sync_now()["status"] == "degraded"  # Position source failure is visible.
    got = next(r for r in reg.payload()["floats"] if r["wmo"] == 2909999)
    assert got["data_status"] == fs.STATUS_RECENT
    assert got["last_profile_file"] == "2909999_prof.nc"
    assert got["profile_checked_at"] is not None
    assert got["stale"]


def test_new_profile_refresh_not_blocked_by_trajectory_or_inventory_outage(tmp_path, monkeypatch):
    fake, reg = _fake_gdac(tmp_path), _reg(tmp_path)
    monkeypatch.setattr(reg, "_connect", lambda: fake)
    reg.sync_now()
    old = copy.deepcopy(reg._rows["2909999"])
    success = reg.payload()["sync"]["last_success_at"]
    new = _write_profile(tmp_path / "new.nc", juld=_juld(NOW) - 0.5, lat=11, lon=66, cycle=26)
    fake.profile_files["2909999_prof.nc"] = new
    fake.mdtms["2909999_prof.nc"] = "20260921100000"
    fake.rtraj = {}
    fake.profiles_lists = {}
    fake.mdtms.pop("2909999_Rtraj.nc")
    monkeypatch.setattr(fs, "_utcnow", lambda: NOW)
    assert reg.sync_now()["status"] == "degraded"
    got = next(r for r in reg.payload()["floats"] if r["wmo"] == 2909999)
    assert got["days_since_last_profile"] == 0.5
    assert got["approx_profiles_missed"] == 0
    assert reg._rows["2909999"]["rtraj"] == old["rtraj"]
    assert reg._rows["2909999"]["profiles"] == old["profiles"]
    assert reg.payload()["sync"]["last_success_at"] == success


def test_missing_aggregate_means_no_data_even_with_recent_other_products(tmp_path, monkeypatch):
    fake, reg = _fake_gdac(tmp_path), _reg(tmp_path)
    del fake.profile_files["2909999_prof.nc"]
    del fake.mdtms["2909999_prof.nc"]
    monkeypatch.setattr(reg, "_connect", lambda: fake)
    assert reg.sync_now()["status"] == "degraded"
    got = next(r for r in reg.payload()["floats"] if r["wmo"] == 2909999)
    assert got["data_status"] == "NO DATA" and got["approx_profiles_missed"] is None
    assert got["prof_num"] == 25 and got["lat"] is not None


def test_failed_profile_refresh_retains_valid_cached_profile_with_stale_warning(
    tmp_path, monkeypatch
):
    fake, reg = _fake_gdac(tmp_path), _reg(tmp_path)
    monkeypatch.setattr(reg, "_connect", lambda: fake)
    reg.sync_now()
    before = next(r for r in reg.payload()["floats"] if r["wmo"] == 2909999)
    del fake.profile_files["2909999_prof.nc"]
    del fake.mdtms["2909999_prof.nc"]
    assert reg.sync_now()["status"] == "degraded"
    after = next(r for r in reg.payload()["floats"] if r["wmo"] == 2909999)
    assert after["last_profile_iso"] == before["last_profile_iso"]
    assert after["profile_checked_at"] == before["profile_checked_at"]
    assert after["stale"] and "Profile history refresh failed" in after["error"]


def test_new_verified_all_fill_product_replaces_old_date_with_no_data(tmp_path, monkeypatch):
    fake, reg = _fake_gdac(tmp_path), _reg(tmp_path)
    monkeypatch.setattr(reg, "_connect", lambda: fake)
    assert reg.sync_now()["status"] == "ok"
    fake.profile_files["2909999_prof.nc"] = _write_profile(tmp_path / "fill.nc", juld=None)
    fake.mdtms["2909999_prof.nc"] = "20260921110000"
    assert reg.sync_now()["status"] == "ok"
    got = next(r for r in reg.payload()["floats"] if r["wmo"] == 2909999)
    assert got["last_profile_iso"] is None and got["data_status"] == "NO DATA"
    assert got["approx_profiles_missed"] is None


def test_estimate_does_not_count_inventory_gaps_or_decoder_failures():
    source = row(history(_juld(NOW - timedelta(days=79))))
    source["profiles"]["missing"] = [4, 17]
    source["rtraj"] = {"traj_max_cycle": 900, "last_tx_iso": NOW.isoformat()}
    source["local_failed_decodes"] = 200  # Explicitly irrelevant test-only field.
    got = serve(source)
    assert got["approx_profiles_missed"] == 7
    assert got["profiles_missing"] == 2
    assert got["prof_num"] == 25


def test_empty_unavailable_fleet_summary_estimate_is_not_zero(tmp_path):
    payload = _reg(tmp_path).payload()
    assert payload["summary"]["approx_profiles_missed_total"] is None
    assert payload["summary"]["profile_dates_known"] == 0


def test_source_contract_names_profile_history_not_trajectory(tmp_path):
    info = _reg(tmp_path).source_info
    assert info["product"] == "dac/incois/<wmo>/<wmo>_prof.nc"
    assert info["monitoring"] == "profile-recency"
    assert info["field"] == "JULD (maximum valid value over N_PROF)"
    # 10 days is now the documented FALLBACK interval, not an assumption: the
    # expected next profile follows each float's observed cycle interval.
    assert info["expected_profile_interval_days"] == 10
    assert (
        info["approximation_note"]
        == "Approximate estimate based on each float's observed profile cycle "
        "(10-day nominal cycle when no sufficient history exists)."
    )
    assert "observed cycle interval" in info["interval_policy"]


def test_expected_next_profile_uses_the_observed_interval_when_history_exists(tmp_path):
    """A 5-day float must not be treated as a 10-day float."""
    source = row(history(_juld(NOW - timedelta(days=6))))
    source["profile_aggregate"]["juld_intervals"] = {"n": 40, "median_days": 5.0}
    got = serve(source)
    assert got["expected_interval_days"] == 5.0
    assert got["expected_interval_source"] == "profile history"
    assert got["expected_interval_samples"] == 40
    assert got["expected_next_profile_iso"] == (NOW - timedelta(days=1)).isoformat()
    assert got["approx_profiles_missed"] == 1
    # Six days after the last profile a 5-day float is overdue, not recent.
    assert got["data_status"] == fs.STATUS_OVERDUE
    assert "observed 5.0-day profile cycle" in got["interval_note"]


def test_trajectory_cycle_spacing_is_the_second_interval_source(tmp_path):
    source = row(history(_juld(NOW - timedelta(days=11))))
    source["profile_aggregate"]["juld_intervals"] = {"n": 1, "median_days": None}
    source["rtraj"] = {"cycle_intervals": {"n": 9, "median_days": 12.0}}
    got = serve(source)
    assert got["expected_interval_days"] == 12.0
    assert got["expected_interval_source"] == "trajectory history"
    assert got["approx_profiles_missed"] == 0
    assert got["data_status"] == fs.STATUS_RECENT
    assert "trajectory cycles" in got["interval_note"]


def test_without_history_the_documented_10_day_fallback_is_used(tmp_path):
    source = row(history(_juld(NOW - timedelta(days=11))))
    got = serve(source)  # no juld_intervals, no cycle_intervals
    assert got["expected_interval_days"] == 10.0
    assert got["expected_interval_source"] == "default 10-day cycle"
    assert got["expected_next_profile_iso"] == (NOW - timedelta(days=1)).isoformat()
    assert got["approx_profiles_missed"] == 1
    assert "10-day" in got["interval_note"]


def test_newer_individual_profile_is_notice_only_not_monitoring_fallback():
    source = row(history(_juld(NOW - timedelta(days=15))))
    source["profiles"].update(
        latest={"file": "R2909999_026.nc", "cycle": 26},
        latest_parse={
            "juld": _juld(NOW - timedelta(days=1)),
            "juld_iso": (NOW - timedelta(days=1)).isoformat(),
        },
    )
    got = serve(source)
    assert got["profile_history_lagging_latest_file"] is True
    assert got["data_status"] == fs.STATUS_OVERDUE
    assert got["days_since_last_profile"] == 15
    assert got["approx_profiles_missed"] == 1
