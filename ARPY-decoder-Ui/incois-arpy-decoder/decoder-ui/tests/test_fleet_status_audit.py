"""Float Status correctness regressions.

The cache-record tests read the repository's existing, unmodified cache; they do
not claim it is a live upstream check. Edge-case NetCDF files below are small,
explicitly synthetic test inputs, written only to pytest temporary directories.
Live 2026-09-21 verification and its independent evidence are in the audit report.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Point runtime state (the forward-test log) at a temporary directory *before*
# importing the service: importing it first fixes DATA_DIR to the repository's
# data directory for the whole process. The repository cache this module audits is
# still read from its real path below.
_TMP = tempfile.mkdtemp(prefix="decoder-ui-audit-test-")
os.environ["ARGO_UI_DATA_DIR"] = _TMP

import fleet_status as fs  # noqa: E402
import netCDF4
import numpy as np
import pytest
from test_fleet_status import NOW, _fake_gdac, _juld, _reg, _write_profile, _write_rtraj

CACHE = json.loads(
    (Path(__file__).resolve().parents[1] / "data/fleet_status/cache.json").read_text()
)
AS_OF = datetime(2026, 9, 21, tzinfo=UTC)
UNITS = "days since 1950-01-01 00:00:00 UTC"


def _row(rtraj=None, profile=None, now=NOW):
    return {
        "wmo": 2909999,
        "in_incois_dac": True,
        "parser_version": fs.PARSER_VERSION,
        "checked_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "rtraj": rtraj or {},
        "profile_aggregate": dict(profile, file="2909999_prof.nc") if profile else None,
        "profile_aggregate_fp": "test",
        "profiles": {
            "max_cycle": 25,
            "missing": [22],
            "available_cycles": 24,
            "latest": {"file": "R2909999_025.nc", "prefix": "R", "cycle": 25},
            "latest_parse": profile,
        },
    }


def _multi_profile(path, lat, lon, loc, juld=None, qc=None, cycles=None):
    n = len(lat)
    with netCDF4.Dataset(path, "w") as d:
        d.createDimension("N_PROF", n)
        d.createDimension("STRING8", 8)
        pn = d.createVariable("PLATFORM_NUMBER", "S1", ("N_PROF", "STRING8"))
        for i in range(n):
            pn[i, :] = np.frombuffer(b"2909999 ", dtype="S1")
        for name, values in {
            "JULD": juld or loc,
            "JULD_LOCATION": loc,
            "LATITUDE": lat,
            "LONGITUDE": lon,
        }.items():
            v = d.createVariable(name, "f8", ("N_PROF",), fill_value=999999.0)
            v[:] = values
            if name.startswith("JULD"):
                v.units = UNITS
        d.createVariable("POSITION_QC", "S1", ("N_PROF",))[:] = np.array(
            qc or ["1"] * n, dtype="S1"
        )
        d.createVariable("CYCLE_NUMBER", "i4", ("N_PROF",))[:] = cycles or [25] * n
    return path.read_bytes()


def test_runtime_state_is_isolated_from_the_repository_data_directory():
    """Regression guard for a real leak.

    This module (and ``test_profile_recency.py``) used to import the service before
    redirecting ``ARGO_UI_DATA_DIR``. Because ``event_bus.DATA_DIR`` is resolved at
    import time, test runs then appended forward-test records for synthetic floats
    into the repository's ``data/fleet_status/prediction_forward_log.jsonl`` - a file
    a deployment started without the variable would serve as its own history.
    """
    import event_bus
    from prediction.forward_test import default_log_path

    repo_data = (Path(__file__).resolve().parents[1] / "data").resolve()
    assert Path(event_bus.DATA_DIR).resolve() != repo_data
    assert repo_data not in Path(default_log_path()).resolve().parents

@pytest.mark.parametrize("wmo", sorted(CACHE["rows"], key=int))
def test_all_32_existing_float_cache_records(wmo):
    """Availability and identity remain honest even before a live re-check."""
    r = CACHE["rows"][wmo]
    got = fs.FleetSyncRegistry._serve_row(int(wmo), r, {}, {}, AS_OF)
    assert got["wmo"] == int(wmo)
    assert got["stale"]  # Version 1 cannot masquerade as a new verified sync.
    # The old committed cache has no full *_prof.nc history. Neither its
    # trajectory timestamps nor its latest individual profile may be used.
    assert got["data_status"] == "NO DATA"
    for key in (
        "last_profile_iso",
        "expected_next_profile_iso",
        "days_since_last_profile",
        "approx_profiles_missed",
    ):
        assert got[key] is None
    assert got["profile_date_error"]
    p = r.get("profiles")
    if p and p.get("max_cycle") is not None:
        assert got["prof_num"] == p["max_cycle"]
        assert got["profiles_missing_list"] == p["missing"]
        assert got["profile_count"] == p["max_cycle"] - len(p["missing"])
    else:
        assert got["profile_count"] is None
        assert got["profiles_missing"] is None


def test_actual_cache_total_is_available_cycles_not_sum_of_maxima():
    rows = [
        fs.FleetSyncRegistry._serve_row(int(w), r, {}, {}, AS_OF) for w, r in CACHE["rows"].items()
    ]
    assert sum(r["profile_count"] or 0 for r in rows) == 5625
    assert sum(r["prof_num"] or 0 for r in rows) == 5647
    assert sum(r["profiles_missing"] or 0 for r in rows) == 22
    # Every cached record is older than the version-1 contract, so all of them
    # report NO DATA until a verified re-check. 30 = the INCOIS fleet after the
    # Coriolis decArgo_demo floats were removed.
    assert sum(r["data_status"] == "NO DATA" for r in rows) == 30


@pytest.mark.parametrize("wmo", [2901304, 2901305, 2902086, 2902222, 2902223, 2902224])
def test_actual_cache_does_not_override_good_traj_with_older_or_bad_profile(wmo):
    row = CACHE["rows"][str(wmo)]
    got = fs.FleetSyncRegistry._serve_row(wmo, row, {}, {}, AS_OF)
    fix = row["rtraj"]["last_fix"]
    assert (got["lat"], got["lon"]) == (fix["lat"], fix["lon"])
    assert got["pos_source"] == "traj"
    assert got["stale"]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0, -0.00001])
def test_nonfinite_and_negative_elapsed_days_are_not_active(value):
    assert fs.profile_data_status(value) == "NO DATA"


@pytest.mark.parametrize(
    "days,want",
    [
        (9.999999, "ACTIVE / RECENT PROFILE"),
        (10, "ACTIVE / RECENT PROFILE"),
        (10.000001, "PROFILE OVERDUE"),
        (59.999999, "PROFILE OVERDUE"),
        (60, "PROFILE OVERDUE"),
        (79.999999, "PROFILE OVERDUE"),
        (80, "NO RECENT PROFILE DATA 80+ DAYS"),
    ],
)
def test_status_boundaries_and_elapsed_days_do_not_round_early(days, want):
    date = AS_OF - timedelta(days=days)
    r = _row(profile={"platform_number": "2909999", "juld": _juld(date)}, now=AS_OF)
    got = fs.FleetSyncRegistry._serve_row(2909999, r, {}, {}, AS_OF)
    assert got["data_status"] == want
    assert got["days_since_last_profile"] == pytest.approx(days, abs=1e-8)


@pytest.mark.parametrize(
    "value", [None, "bad", float("nan"), float("inf"), 999999, -1, _juld(AS_OF + timedelta(days=1))]
)
def test_bad_and_future_cached_profile_values_are_unavailable(value):
    row = _row(profile={"platform_number": "2909999", "juld": value}, now=AS_OF)
    got = fs.FleetSyncRegistry._serve_row(2909999, row, {}, {}, AS_OF)
    assert got["last_profile_iso"] is None and got["data_status"] == "NO DATA"


def test_profile_epoch_output_is_utc():
    date = datetime.fromisoformat("2026-09-11T05:30:00+05:30")
    row = _row(profile={"platform_number": "2909999", "juld": _juld(date)}, now=AS_OF)
    got = fs.FleetSyncRegistry._serve_row(2909999, row, {}, {}, AS_OF)
    assert got["last_profile_iso"] == "2026-09-11T00:00:00+00:00"
    assert got["expected_next_profile_iso"] == AS_OF.isoformat()
    assert got["data_status"] == fs.STATUS_RECENT
    assert got["approx_profiles_missed"] == 1  # Exact day 10 is still recent.


def test_floating_juld_roundoff_does_not_shift_a_utc_minute():
    value = _juld(datetime(2026, 9, 1, 12, 30, tzinfo=UTC)) - 1e-10
    assert fs.juld_to_iso(value) == "2026-09-01T12:30:00+00:00"


def test_future_communication_within_old_one_day_grace_is_rejected(tmp_path):
    raw = _write_rtraj(tmp_path / "future.nc", 2909999, [_juld(NOW + timedelta(hours=1))])
    assert fs.parse_rtraj(raw, 2909999, NOW)["last_tx_iso"] is None


def test_communication_units_and_dimension_are_verified(tmp_path):
    file = tmp_path / "units.nc"
    _write_rtraj(file, 2909999, [_juld(NOW - timedelta(days=1))])
    with netCDF4.Dataset(file, "a") as d:
        d["JULD_LAST_MESSAGE"].units = "hours since 1970-01-01"
    with pytest.raises(fs.FloatSyncError, match="time units"):
        fs.parse_rtraj(file.read_bytes(), 2909999, NOW)
    _write_rtraj(file, 2909999, [_juld(NOW - timedelta(days=1))])
    with netCDF4.Dataset(file, "a") as d:
        d.renameDimension("N_CYCLE", "not_cycle")
    with pytest.raises(fs.FloatSyncError, match="per-cycle"):
        fs.parse_rtraj(file.read_bytes(), 2909999, NOW)


def test_masked_integer_cycles_do_not_drop_good_values_or_promote_fill(tmp_path):
    file = tmp_path / "mask.nc"
    _write_rtraj(file, 2909999, [_juld(NOW - timedelta(days=2)), _juld(NOW - timedelta(days=1))])
    with netCDF4.Dataset(file, "a") as d:
        d["CYCLE_NUMBER_INDEX"].missing_value = 99999
        d["CYCLE_NUMBER_INDEX"][:] = [7, 99999]
    got = fs.parse_rtraj(file.read_bytes(), 2909999, NOW)
    assert got["traj_max_cycle"] == 7
    assert got["last_tx_cycle"] is None


def test_profile_foreign_wmo_is_rejected(tmp_path):
    raw = _write_profile(tmp_path / "foreign.nc", wmo=1900000)
    with pytest.raises(fs.FloatSyncError, match="PLATFORM_NUMBER"):
        fs.parse_profile(raw, 2909999, 7, NOW)


def test_profile_position_never_combines_separate_n_prof_rows(tmp_path):
    j = _juld(NOW)
    raw = _multi_profile(
        tmp_path / "multi.nc", [1, 999999, 3], [999999, 2, 4], [j - 3, j - 2, j - 1]
    )
    got = fs.parse_profile(raw, 2909999, 25, NOW)
    assert (got["lat"], got["lon"], got["position_index"]) == (3, 4, 2)
    assert got["pos_qc"] == "1"  # Not the concatenation "111".


def test_location_time_is_not_profile_measurement_time(tmp_path):
    j = _juld(NOW)
    raw = _multi_profile(tmp_path / "loc.nc", [8], [65], [j - 1], juld=[j - 30])
    profile = fs.parse_profile(raw, 2909999, 25, NOW)
    traj = {
        "last_tx_field": "JULD_LAST_MESSAGE",
        "last_tx_iso": (NOW - timedelta(days=5)).isoformat(),
        "last_fix": {
            "juld_iso": (NOW - timedelta(days=2)).isoformat(),
            "lat": 7,
            "lon": 64,
            "pos_qc": "1",
        },
    }
    got = fs.FleetSyncRegistry._serve_row(2909999, _row(traj, profile), {}, {}, NOW)
    assert got["pos_source"] == "profile"
    assert got["position_time_field"] == "JULD_LOCATION"
    assert got["days_since_last_profile"] == pytest.approx(
        30
    )  # JULD, not location or trajectory time.
    assert datetime.fromisoformat(profile["juld_iso"]) < datetime.fromisoformat(got["position_iso"])


@pytest.mark.parametrize("qc", ["0", "3", "4", "8", "9", " "])
def test_nonapproved_profile_position_qc_not_plotted(tmp_path, qc):
    raw = _write_profile(
        tmp_path / "qc.nc", juld=_juld(NOW - timedelta(days=1)), lat=10, lon=65, qc=qc
    )
    got = fs.parse_profile(raw, 2909999, 7, NOW)
    assert got["lat"] is None and got["lon"] is None
    assert got["juld_iso"] is not None
    assert got["position_error"]


def test_profile_measurement_cannot_stand_in_for_missing_juld_location(tmp_path):
    raw = _write_profile(
        tmp_path / "loc.nc",
        juld=_juld(NOW - timedelta(days=1)),
        lat=10,
        lon=65,
        with_location=False,
    )
    got = fs.parse_profile(raw, 2909999, 7, NOW)
    assert got["position_iso"] is None and got["lat"] is None
    assert got["juld_iso"] is not None


def test_profile_cycles_include_descent_four_digits_and_deduplicate_families():
    files = [
        "D2909999_000.nc",
        "R2909999_001D.nc",
        "BD2909999_001.nc",
        "R2909999_1000D.nc",
        "ZZ2909999_999.nc",
    ]
    got = fs.summarize_profiles(files + files, 2909999)
    assert got["max_cycle"] == 1000 and got["available_cycles"] == 2
    assert len(got["missing"]) == 998 and 0 not in got["missing"]
    assert got["latest"]["file"] == "R2909999_1000D.nc"
    assert got["n_files"] == 4


def test_unchanged_upstream_renews_check_time_without_observation_changes(tmp_path, monkeypatch):
    fake, reg = _fake_gdac(tmp_path), _reg(tmp_path)
    monkeypatch.setattr(reg, "_connect", lambda: fake)
    monkeypatch.setattr(fs, "_utcnow", lambda: NOW)
    reg.sync_now()
    old = copy.deepcopy(reg._rows["2909999"])
    monkeypatch.setattr(fs, "_utcnow", lambda: NOW + timedelta(hours=1))
    fake.downloads.clear()
    result = reg.sync_now()
    new = reg._rows["2909999"]
    assert result["counts"]["unchanged"] == 2 and fake.downloads == []
    assert new["checked_at"] != old["checked_at"]
    assert new["updated_at"] == old["updated_at"]
    assert new["rtraj"] == old["rtraj"]
    assert reg.payload()["sync"]["stale"] is False


def test_parser_revision_forces_revalidation_of_same_fingerprints(tmp_path, monkeypatch):
    fake, reg = _fake_gdac(tmp_path), _reg(tmp_path)
    monkeypatch.setattr(reg, "_connect", lambda: fake)
    reg.sync_now()
    reg._rows["2909999"]["parser_version"] = 1
    reg._rows["2909999"]["rtraj"]["last_tx_field"] = "JULD (measurement max)"
    fake.downloads.clear()
    reg.sync_now()
    assert fake.downloads == ["2909999_prof.nc", "2909999_Rtraj.nc", "R2909999_025.nc"]
    assert reg._rows["2909999"]["parser_version"] == fs.PARSER_VERSION
    assert reg._rows["2909999"]["rtraj"]["last_tx_field"] == "JULD_LAST_MESSAGE"


def test_no_comms_is_valid_cached_data_not_endless_failed_download(tmp_path, monkeypatch):
    fake, reg = _fake_gdac(tmp_path), _reg(tmp_path)
    fake.rtraj[2909999] = _write_rtraj(tmp_path / "vintage.nc", 2909999, [999999.0])
    monkeypatch.setattr(reg, "_connect", lambda: fake)
    assert reg.sync_now()["status"] == "ok"
    fake.downloads.clear()
    assert reg.sync_now()["counts"]["unchanged"] == 2
    assert fake.downloads == []
    row = next(r for r in reg.payload()["floats"] if r["wmo"] == 2909999)
    assert row["data_status"] == fs.STATUS_RECENT and row["profile_count"] == 24
    assert row["approx_profiles_missed"] == 0
    assert row["stale"] is False


def test_failed_partial_refresh_does_not_advance_last_success(tmp_path, monkeypatch):
    fake, reg = _fake_gdac(tmp_path), _reg(tmp_path)
    monkeypatch.setattr(reg, "_connect", lambda: fake)
    reg.sync_now()
    old, success = copy.deepcopy(reg._rows["2909999"]), reg.payload()["sync"]["last_success_at"]
    fake.profiles_lists = {}
    assert reg.sync_now()["status"] == "degraded"
    assert reg.payload()["sync"]["last_success_at"] == success
    assert reg._rows["2909999"]["checked_at"] == old["checked_at"]
    assert reg._rows["2909999"]["rtraj"] == old["rtraj"]
    assert reg._rows["2909999"]["profiles"] == old["profiles"]
    assert reg.payload()["sync"]["stale"] is True


@pytest.mark.parametrize("bad_members", [[], ["unexpected-response"]])
def test_empty_or_malformed_dac_membership_cannot_erase_valid_rows(
    tmp_path, monkeypatch, bad_members
):
    fake, reg = _fake_gdac(tmp_path), _reg(tmp_path)
    monkeypatch.setattr(reg, "_connect", lambda: fake)
    reg.sync_now()
    old = copy.deepcopy(reg._rows)
    fake.members = bad_members
    assert reg.sync_now()["status"] == "error"
    assert reg._rows == old


def test_unparsed_profile_listing_cannot_turn_available_profiles_into_missing(
    tmp_path, monkeypatch
):
    fake, reg = _fake_gdac(tmp_path), _reg(tmp_path)
    monkeypatch.setattr(reg, "_connect", lambda: fake)
    reg.sync_now()
    old = copy.deepcopy(reg._rows["2909999"]["profiles"])
    fake.profiles_lists[2909999] = ["not a valid FTP listing"]
    assert reg.sync_now()["status"] == "degraded"
    assert reg._rows["2909999"]["profiles"] == old


def test_atomic_write_failure_is_visible_and_keeps_previous_disk_cache(tmp_path, monkeypatch):
    fake, reg = _fake_gdac(tmp_path), _reg(tmp_path)
    monkeypatch.setattr(reg, "_connect", lambda: fake)
    reg.sync_now()
    before = reg.state_path.read_bytes()
    success = reg.payload()["sync"]["last_success_at"]
    original = Path.replace

    def fail_cache_replace(path, target):
        if path.name == "cache.json.tmp":
            raise PermissionError("simulated cache commit failure")
        return original(path, target)

    monkeypatch.setattr(Path, "replace", fail_cache_replace)
    assert reg.sync_now()["status"] == "degraded"
    assert reg.state_path.read_bytes() == before
    assert reg.payload()["sync"]["last_success_at"] == success
    assert "commit failure" in reg.payload()["sync"]["persistence_error"]


def test_old_success_and_disabled_sync_do_not_look_fresh(tmp_path, monkeypatch):
    fake, reg = _fake_gdac(tmp_path), _reg(tmp_path)
    monkeypatch.setattr(reg, "_connect", lambda: fake)
    monkeypatch.setattr(fs, "_utcnow", lambda: NOW)
    reg.sync_now()
    monkeypatch.setattr(fs, "_utcnow", lambda: NOW + timedelta(hours=7))
    assert reg.payload()["sync"]["status"] == "ok"
    assert reg.payload()["sync"]["stale"] is True
    reg._enabled = False
    assert reg.payload()["sync"]["status"] == "disabled"
    assert reg.payload()["sync"]["stale"] is True


def test_scheduler_immediate_and_next_cycle_persist_and_use_effective_interval(
    tmp_path, monkeypatch
):
    fake, reg = _fake_gdac(tmp_path), _reg(tmp_path, interval_s=1)
    monkeypatch.setattr(reg, "_connect", lambda: fake)
    sleeps = []
    clock = [NOW]
    monkeypatch.setattr(fs, "_utcnow", lambda: clock[0])

    async def virtual_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise asyncio.CancelledError
        clock[0] += timedelta(seconds=seconds)

    monkeypatch.setattr(asyncio, "sleep", virtual_sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(reg._poll_loop())
    assert len(sleeps) == 2 and all(299 < delay <= 300 for delay in sleeps)
    cache = json.loads(reg.state_path.read_text())
    assert cache["rows"]["2909999"]["checked_at"] == clock[0].isoformat()
    assert cache["sync"]["counts"]["unchanged"] == 2
    assert reg.payload()["sync"]["interval_s"] == 300


def test_current_fleet_does_not_include_removed_cache_only_wmos(tmp_path):
    reg = _reg(tmp_path)
    reg._rows["1234567"] = {"wmo": 1234567}
    assert {r["wmo"] for r in reg.payload()["floats"]} == {2909999, 6900000}


def test_sanitized_internal_identity_is_not_reconstructed():
    got = fs.FleetSyncRegistry._serve_row(
        2902086, None, {"platform_type": "PROVOR_III"}, {"ptt": "", "imei": "REDACTED_001"}, NOW
    )
    assert got["internal_id"] is None
    assert got["float_type"] == "PROVOR_III"


def test_full_profile_history_uses_dates_not_highest_cycle(tmp_path):
    j = _juld(NOW)
    raw = _multi_profile(
        tmp_path / "all.nc", [1, 2, 3], [60, 61, 62], [j - 10, j - 1, j - 2], cycles=[100, 2, 3]
    )
    got = fs.parse_profile(raw, 2909999, None, NOW)
    assert got["cycle"] == 2 and got["position_index"] == 1
    assert (got["lat"], got["lon"]) == (2, 61)
    assert got["cycle_mismatch"] is False


def test_full_history_can_supply_newer_good_position_when_latest_cycle_is_bad(
    tmp_path, monkeypatch
):
    fake, reg = _fake_gdac(tmp_path), _reg(tmp_path)
    j = _juld(NOW)
    aggregate = _multi_profile(
        tmp_path / "all.nc", [5, 6], [66, 67], [j - 1, j - 0.5], qc=["1", "3"], cycles=[24, 25]
    )
    fake.profile_files["2909999_prof.nc"] = aggregate
    original_size = fake.size
    fake.size = lambda path: (
        len(aggregate) if path.endswith("2909999_prof.nc") else original_size(path)
    )
    fake.mdtms["2909999_prof.nc"] = "20260920090000"
    monkeypatch.setattr(reg, "_connect", lambda: fake)
    assert reg.sync_now()["status"] == "ok"
    row = next(r for r in reg.payload()["floats"] if r["wmo"] == 2909999)
    assert (row["lat"], row["lon"]) == (5, 66)
    assert row["position_file"] == "2909999_prof.nc"
    assert row["prof_num"] == 25  # Position provenance does not redefine Prof#.
    assert row["profile_count"] == 24
    old = copy.deepcopy(reg._rows["2909999"])
    fake.size = original_size
    del fake.mdtms["2909999_prof.nc"]
    del fake.profile_files["2909999_prof.nc"]
    assert reg.sync_now()["status"] == "degraded"
    assert reg._rows["2909999"]["profile_aggregate"] == old["profile_aggregate"]
