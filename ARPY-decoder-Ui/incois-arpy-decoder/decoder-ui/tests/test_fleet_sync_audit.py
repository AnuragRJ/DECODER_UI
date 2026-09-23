"""Comprehensive audit and end-to-end sync verification tests.

Validates the complete pipeline:
Ifremer (GdacHttpsClient / GdacFtpClient) -> download/sync -> cache -> parser -> /api/fleet-status payload -> UI freshness.

Tests:
1. Updated existing float (fingerprint mismatch triggers download, advances cycle/date, updates cache & API).
2. Newly discovered float (new WMO detected, downloaded, parsed, added to cache & API).
3. Failed sync (upstream connection failure surfaces error, sets stale=True, preserves prior cache).
4. Parser version invalidation (parser version mismatch triggers re-download even with same MDTM).
5. GdacHttpsClient transport unit tests (membership, file_stat with MDTM conversion, list_entries, retrieve, 404 handling).
"""

from __future__ import annotations

import ftplib
import json
import os
import tempfile
import urllib.error
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import netCDF4
import numpy as np
import pytest

_TMP = tempfile.mkdtemp(prefix="decoder-ui-sync-audit-")
os.environ["ARGO_UI_DATA_DIR"] = _TMP

import fleet_status as fs
from fleet_status import (
    PARSER_VERSION,
    PROFILE_RECENCY_VERSION,
    FleetSyncRegistry,
    FloatSyncError,
    GdacFtpClient,
    GdacHttpsClient,
)

NOW = datetime.now(UTC)
EPOCH = datetime(1950, 1, 1, tzinfo=UTC)


def _juld(dt: datetime) -> float:
    return (dt - EPOCH).total_seconds() / 86400.0


def _build_test_profile(
    path: Path,
    wmo: int,
    cycle: int,
    juld: float,
    lat: float = 12.34,
    lon: float = 65.43,
) -> bytes:
    """Build a compliant synthetic Argo profile NetCDF."""
    ds = netCDF4.Dataset(str(path), "w", format="NETCDF4")
    try:
        ds.createDimension("N_PROF", 1)
        ds.createDimension("N_PARAM", 3)
        ds.createDimension("N_LEVELS", 10)
        ds.createDimension("STRING8", 8)

        pn = ds.createVariable("PLATFORM_NUMBER", "S1", ("N_PROF", "STRING8"))
        pn[:] = np.frombuffer(f"{wmo:<8}"[:8].encode(), dtype="S1")

        j = ds.createVariable("JULD", "f8", ("N_PROF",))
        j.units = "days since 1950-01-01 00:00:00 UTC"
        j[:] = [juld]

        loc = ds.createVariable("JULD_LOCATION", "f8", ("N_PROF",))
        loc.units = "days since 1950-01-01 00:00:00 UTC"
        loc[:] = [juld]

        la = ds.createVariable("LATITUDE", "f8", ("N_PROF",))
        la[:] = [lat]

        lo = ds.createVariable("LONGITUDE", "f8", ("N_PROF",))
        lo[:] = [lon]

        c = ds.createVariable("CYCLE_NUMBER", "i4", ("N_PROF",))
        c[:] = [cycle]

        qc = ds.createVariable("POSITION_QC", "S1", ("N_PROF",))
        qc[:] = [b"1"]
    finally:
        ds.close()
    return path.read_bytes()


def _build_test_rtraj(
    path: Path, wmo: int, cycle: int, juld: float, lat: float = 12.34, lon: float = 65.43
) -> bytes:
    """Build a compliant synthetic Argo trajectory NetCDF."""
    ds = netCDF4.Dataset(str(path), "w", format="NETCDF4")
    try:
        ds.createDimension("N_CYCLE", 1)
        ds.createDimension("N_MEASUREMENT", 1)
        ds.createDimension("ST8", 8)

        pn = ds.createVariable("PLATFORM_NUMBER", "S1", ("ST8",))
        pn[:] = np.frombuffer(f"{wmo:<8}"[:8].encode(), dtype="S1")

        lm = ds.createVariable("JULD_LAST_MESSAGE", "f8", ("N_CYCLE",), fill_value=999999.0)
        lm.units = "days since 1950-01-01 00:00:00 UTC"
        lm[:] = [juld]

        ci = ds.createVariable("CYCLE_NUMBER_INDEX", "i4", ("N_CYCLE",))
        ci[:] = [cycle]

        j = ds.createVariable("JULD", "f8", ("N_MEASUREMENT",), fill_value=999999.0)
        j.units = "days since 1950-01-01 00:00:00 UTC"
        j[:] = [juld]

        la = ds.createVariable("LATITUDE", "f8", ("N_MEASUREMENT",), fill_value=999999.0)
        la[:] = [lat]

        lo = ds.createVariable("LONGITUDE", "f8", ("N_MEASUREMENT",), fill_value=999999.0)
        lo[:] = [lon]

        cyc = ds.createVariable("CYCLE_NUMBER", "i4", ("N_MEASUREMENT",))
        cyc[:] = [cycle]

        mc = ds.createVariable("MEASUREMENT_CODE", "i4", ("N_MEASUREMENT",))
        mc[:] = [703]

        qc = ds.createVariable("POSITION_QC", "S1", ("N_MEASUREMENT",))
        qc[:] = [b"1"]
    finally:
        ds.close()
    return path.read_bytes()


class MockGdacClient:
    """Configurable in-memory GDAC client implementing the GdacClient interface."""

    def __init__(self) -> None:
        self.members: set[str] = set()
        self.files: dict[str, bytes] = {}  # path -> bytes
        self.stats: dict[str, tuple[int | None, str | None]] = {}  # path -> (size, mdtm)
        self.entries: dict[str, list[tuple[str, int, float]]] = {}  # dir_path -> entries
        self.downloads: list[str] = []
        self.should_fail: str | None = None

    def membership(self, dac_dir: str) -> set[str]:
        if self.should_fail:
            raise FloatSyncError(self.should_fail)
        return set(self.members)

    def file_stat(self, path: str) -> tuple[int | None, str | None]:
        if self.should_fail:
            raise FloatSyncError(self.should_fail)
        for key, stat in self.stats.items():
            if path.endswith(key):
                return stat
        return None, None

    def list_entries(self, path: str) -> list[tuple[str, int, float]]:
        if self.should_fail:
            raise FloatSyncError(self.should_fail)
        for key, entry_list in self.entries.items():
            if path.endswith(key):
                return entry_list
        return []

    def retrieve(self, path: str) -> bytes:
        if self.should_fail:
            raise FloatSyncError(self.should_fail)
        self.downloads.append(path.rsplit("/", 1)[-1])
        for key, data in self.files.items():
            if path.endswith(key):
                return data
        raise FloatSyncError(f"404 not found: {path}")

    def close(self) -> None:
        pass


# ===========================================================================
# 1. Test Updated Existing Float
# ===========================================================================


def test_updated_existing_float_advances_cycle_and_date(tmp_path):
    """Test 1: An existing float gets an updated profile upstream.

    Fingerprint change triggers download and parse, advances last_profile_iso,
    updates updated_at, saves to cache, and serves updated data in the API.
    """
    wmo = 2909001
    wmo_str = str(wmo)
    state_file = tmp_path / "cache.json"

    # Initial state: Cycle 10 from 5 days ago
    juld_v1 = _juld(NOW - timedelta(days=5))
    prof_v1 = _build_test_profile(tmp_path / "prof_v1.nc", wmo, cycle=10, juld=juld_v1, lat=10.0, lon=60.0)
    rtraj_v1 = _build_test_rtraj(tmp_path / "rtraj_v1.nc", wmo, cycle=10, juld=juld_v1)

    mock = MockGdacClient()
    mock.members.add(wmo_str)
    mock.files[f"{wmo}_prof.nc"] = prof_v1
    mock.files[f"{wmo}_Rtraj.nc"] = rtraj_v1
    mock.stats[f"{wmo}_prof.nc"] = (len(prof_v1), "20260910120000")
    mock.stats[f"{wmo}_Rtraj.nc"] = (len(rtraj_v1), "20260910120000")
    mock.entries[f"{wmo}/profiles"] = [
        (f"R{wmo}_010.nc", len(prof_v1), (NOW - timedelta(days=5)).timestamp())
    ]
    mock.files[f"R{wmo}_010.nc"] = prof_v1

    reg = FleetSyncRegistry(
        state_path=state_file,
        fleet_fn=lambda: [{"wmo": wmo, "platform_type": "APEX", "transmission_type": "IRIDIUM_SBD"}],
    )
    reg._connect = lambda: mock

    # Initial sync
    res1 = reg.sync_now()
    assert res1["status"] == "ok"
    assert res1["counts"]["updated"] == 1
    assert f"{wmo}_prof.nc" in mock.downloads

    payload1 = reg.payload()
    float_v1 = next(f for f in payload1["floats"] if f["wmo"] == wmo)
    assert float_v1["prof_num"] == 10
    assert float_v1["data_status"] == "ACTIVE / RECENT PROFILE"
    v1_updated_at = float_v1["updated_at"]
    v1_profile_iso = float_v1["last_profile_iso"]

    # Upstream publishes Cycle 11 from 1 day ago
    mock.downloads.clear()
    juld_v2 = _juld(NOW - timedelta(days=1))
    prof_v2 = _build_test_profile(tmp_path / "prof_v2.nc", wmo, cycle=11, juld=juld_v2, lat=11.5, lon=62.5)
    mock.files[f"{wmo}_prof.nc"] = prof_v2
    # New MDTM & size invalidates profile_aggregate_fp
    mock.stats[f"{wmo}_prof.nc"] = (len(prof_v2), "20260914120000")
    mock.entries[f"{wmo}/profiles"] = [
        (f"R{wmo}_010.nc", len(prof_v1), (NOW - timedelta(days=5)).timestamp()),
        (f"R{wmo}_011.nc", len(prof_v2), (NOW - timedelta(days=1)).timestamp()),
    ]
    mock.files[f"R{wmo}_011.nc"] = prof_v2

    # Second sync: should detect update
    res2 = reg.sync_now()
    assert res2["status"] == "ok"
    assert res2["counts"]["updated"] == 1
    assert f"{wmo}_prof.nc" in mock.downloads

    # Check API payload
    payload2 = reg.payload()
    float_v2 = next(f for f in payload2["floats"] if f["wmo"] == wmo)
    assert float_v2["prof_num"] == 11
    assert float_v2["lat"] == 11.5
    assert float_v2["lon"] == 62.5
    assert float_v2["last_profile_iso"] > v1_profile_iso
    assert float_v2["updated_at"] > v1_updated_at
    assert payload2["sync"]["status"] == "ok"
    assert payload2["sync"]["stale"] is False

    # Verify cache persistence on disk
    assert state_file.is_file()
    disk_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert disk_data["rows"][wmo_str]["profiles"]["latest"]["cycle"] == 11


# ===========================================================================
# 2. Test Newly Discovered Float
# ===========================================================================


def test_newly_discovered_float_reaches_api(tmp_path):
    """Test 2: A newly discovered float is added to the fleet.

    Detected by membership, downloaded, parsed, written to cache,
    and served on the /api/fleet-status endpoint.
    """
    state_file = tmp_path / "cache.json"
    wmo1 = 2909001
    wmo2 = 2909002  # Newly discovered float

    juld = _juld(NOW - timedelta(days=2))
    prof1 = _build_test_profile(tmp_path / "prof1.nc", wmo1, cycle=5, juld=juld)
    rtraj1 = _build_test_rtraj(tmp_path / "rtraj1.nc", wmo1, cycle=5, juld=juld)
    prof2 = _build_test_profile(tmp_path / "prof2.nc", wmo2, cycle=8, juld=juld, lat=5.0, lon=75.0)
    rtraj2 = _build_test_rtraj(tmp_path / "rtraj2.nc", wmo2, cycle=8, juld=juld, lat=5.0, lon=75.0)

    mock = MockGdacClient()
    mock.members.update([str(wmo1), str(wmo2)])
    mock.files[f"{wmo1}_prof.nc"] = prof1
    mock.files[f"{wmo1}_Rtraj.nc"] = rtraj1
    mock.stats[f"{wmo1}_prof.nc"] = (len(prof1), "20260910000000")
    mock.stats[f"{wmo1}_Rtraj.nc"] = (len(rtraj1), "20260910000000")

    mock.files[f"{wmo2}_prof.nc"] = prof2
    mock.files[f"{wmo2}_Rtraj.nc"] = rtraj2
    mock.stats[f"{wmo2}_prof.nc"] = (len(prof2), "20260910000000")
    mock.stats[f"{wmo2}_Rtraj.nc"] = (len(rtraj2), "20260910000000")
    mock.entries[f"{wmo2}/profiles"] = [
        (f"R{wmo2}_008.nc", len(prof2), (NOW - timedelta(days=2)).timestamp())
    ]
    mock.files[f"R{wmo2}_008.nc"] = prof2

    # Start with only Float 1 in fleet_fn
    current_fleet = [{"wmo": wmo1, "platform_type": "APEX", "transmission_type": "IRIDIUM_SBD"}]
    reg = FleetSyncRegistry(state_path=state_file, fleet_fn=lambda: current_fleet)
    reg._connect = lambda: mock

    res1 = reg.sync_now()
    assert res1["status"] == "ok"
    assert reg.payload()["summary"]["total"] == 1

    # New float is discovered in fleet_fn
    current_fleet.append(
        {"wmo": wmo2, "platform_type": "PROVOR_III", "transmission_type": "IRIDIUM_SBD"}
    )
    mock.downloads.clear()

    res2 = reg.sync_now()
    assert res2["status"] == "ok"
    assert f"{wmo2}_prof.nc" in mock.downloads

    payload2 = reg.payload()
    assert payload2["summary"]["total"] == 2

    new_float = next(f for f in payload2["floats"] if f["wmo"] == wmo2)
    assert new_float["in_incois_dac"] is True
    assert new_float["prof_num"] == 8
    assert new_float["data_status"] == "ACTIVE / RECENT PROFILE"
    assert new_float["lat"] == 5.0 and new_float["lon"] == 75.0
    assert new_float["float_type"] == "PROVOR_III"


# ===========================================================================
# 3. Test Failed Sync & Stale-Cache Surfacing
# ===========================================================================


def test_failed_sync_surfaces_stale_cache_and_preserves_rows(tmp_path):
    """Test 3: Upstream network/GDAC outage marks sync as error + stale,
    preserves previous verified cache rows, and surfaces the failure reason.
    """
    state_file = tmp_path / "cache.json"
    wmo = 2909001

    juld = _juld(NOW - timedelta(days=3))
    prof = _build_test_profile(tmp_path / "prof.nc", wmo, cycle=15, juld=juld)
    rtraj = _build_test_rtraj(tmp_path / "rtraj.nc", wmo, cycle=15, juld=juld)

    mock = MockGdacClient()
    mock.members.add(str(wmo))
    mock.files[f"{wmo}_prof.nc"] = prof
    mock.files[f"{wmo}_Rtraj.nc"] = rtraj
    mock.stats[f"{wmo}_prof.nc"] = (len(prof), "20260910000000")
    mock.stats[f"{wmo}_Rtraj.nc"] = (len(rtraj), "20260910000000")
    mock.entries[f"{wmo}/profiles"] = [
        (f"R{wmo}_015.nc", len(prof), (NOW - timedelta(days=3)).timestamp())
    ]
    mock.files[f"R{wmo}_015.nc"] = prof

    reg = FleetSyncRegistry(
        state_path=state_file,
        fleet_fn=lambda: [{"wmo": wmo, "platform_type": "APEX", "transmission_type": "IRIDIUM_SBD"}],
    )
    reg._connect = lambda: mock

    # Successful first sync
    res1 = reg.sync_now()
    assert res1["status"] == "ok"
    payload1 = reg.payload()
    assert payload1["sync"]["status"] == "ok"
    assert payload1["sync"]["stale"] is False
    last_success = payload1["sync"]["last_success_at"]
    assert last_success is not None

    # Simulate upstream network failure
    mock.should_fail = "Connection refused by GDAC upstream mirror"

    res2 = reg.sync_now()
    assert res2["status"] == "error"
    assert "Connection refused" in res2["error"]

    payload2 = reg.payload()
    sync2 = payload2["sync"]
    assert sync2["status"] == "error"
    assert sync2["stale"] is True
    assert "Connection refused" in (sync2["error"] or "")
    assert "Connection refused" in (sync2["stale_reason"] or "")
    # Last success time is preserved
    assert sync2["last_success_at"] == last_success

    # Prior float observations are safely retained (no data wiped!)
    assert len(payload2["floats"]) == 1
    float_row = payload2["floats"][0]
    assert float_row["wmo"] == wmo
    assert float_row["prof_num"] == 15
    assert float_row["data_status"] == "ACTIVE / RECENT PROFILE"


# ===========================================================================
# 4. Test Parser Version Invalidation
# ===========================================================================


def test_parser_version_invalidation_triggers_redownload(tmp_path, monkeypatch):
    """Test 4: Cache version / parser version bump invalidates cache even when
    upstream MDTM and file size have not changed.
    """
    state_file = tmp_path / "cache.json"
    wmo = 2909001

    juld = _juld(NOW - timedelta(days=2))
    prof = _build_test_profile(tmp_path / "prof.nc", wmo, cycle=10, juld=juld)
    rtraj = _build_test_rtraj(tmp_path / "rtraj.nc", wmo, cycle=10, juld=juld)

    mock = MockGdacClient()
    mock.members.add(str(wmo))
    mock.files[f"{wmo}_prof.nc"] = prof
    mock.files[f"{wmo}_Rtraj.nc"] = rtraj
    mock.stats[f"{wmo}_prof.nc"] = (len(prof), "20260910000000")
    mock.stats[f"{wmo}_Rtraj.nc"] = (len(rtraj), "20260910000000")

    reg = FleetSyncRegistry(
        state_path=state_file,
        fleet_fn=lambda: [{"wmo": wmo, "platform_type": "APEX", "transmission_type": "IRIDIUM_SBD"}],
    )
    reg._connect = lambda: mock

    res1 = reg.sync_now()
    assert res1["status"] == "ok"
    assert len(mock.downloads) > 0

    # Sync again without change: downloads should be skipped (0 updated)
    mock.downloads.clear()
    res2 = reg.sync_now()
    assert res2["counts"]["updated"] == 0
    assert mock.downloads == []

    # Now bump PARSER_VERSION
    monkeypatch.setattr(fs, "PARSER_VERSION", PARSER_VERSION + 1)
    res3 = reg.sync_now()
    assert res3["counts"]["updated"] == 1
    assert f"{wmo}_prof.nc" in mock.downloads


# ===========================================================================
# 5. GdacHttpsClient Unit Tests
# ===========================================================================


def test_gdac_https_client_membership(monkeypatch):
    """Verify membership parsing from Apache autoindex HTML."""
    sample_html = """
    <!DOCTYPE HTML>
    <html><head><title>Index of /dac/incois</title></head><body>
    <table>
    <tr><td><a href="1900042/">1900042/</a></td></tr>
    <tr><td><a href="2901304/">2901304/</a></td></tr>
    <tr><td><a href="6900000/">6900000/</a></td></tr>
    <tr><td><a href="junk_folder/">junk/</a></td></tr>
    </table></body></html>
    """

    class MockResponse:
        def read(self):
            return sample_html.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=30: MockResponse())

    client = GdacHttpsClient()
    members = client.membership("/dac/incois")
    assert members == {"1900042", "2901304", "6900000"}


def test_gdac_https_client_file_stat(monkeypatch):
    """Verify HTTP HEAD parsing of Last-Modified (to MDTM) and Content-Length."""
    headers = {
        "Content-Length": "124116",
        "Last-Modified": "Fri, 05 Apr 2019 12:55:23 GMT",
    }

    class MockHeadResponse:
        def __init__(self):
            self.headers = headers

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=30: MockHeadResponse())

    client = GdacHttpsClient()
    size, mdtm = client.file_stat("/dac/incois/2901304/2901304_prof.nc")
    assert size == 124116
    assert mdtm == "20190405125523"


def test_gdac_https_client_file_stat_404(monkeypatch):
    """Verify 404 returns (None, None) gracefully."""
    def _mock_404(req, timeout=30):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", _mock_404)

    client = GdacHttpsClient()
    size, mdtm = client.file_stat("/dac/incois/9999999/9999999_prof.nc")
    assert size is None and mdtm is None


def test_gdac_https_client_list_entries(monkeypatch):
    """Verify Apache autoindex HTML table parsing into (name, size, epoch)."""
    sample_html = """
    <table>
    <tr><td><a href="D2901304_001.nc">D2901304_001.nc</a></td><td align="right">2013-09-16 11:03  </td><td align="right"> 19K</td></tr>
    <tr><td><a href="D2901304_002.nc">D2901304_002.nc</a></td><td align="right">2014-02-01 18:13  </td><td align="right"> 22K</td></tr>
    </table>
    """

    class MockResponse:
        def read(self):
            return sample_html.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=30: MockResponse())

    client = GdacHttpsClient()
    entries = client.list_entries("/dac/incois/2901304/profiles")
    assert len(entries) == 2
    names = [e[0] for e in entries]
    assert names == ["D2901304_001.nc", "D2901304_002.nc"]
    assert entries[0][1] == 19 * 1024
