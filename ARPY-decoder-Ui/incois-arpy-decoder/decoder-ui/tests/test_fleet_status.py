"""Unit tests for Float Status — Ifremer/Argo GDAC communication monitoring.

Contract under test (see decoder-ui/FLEET_STATUS.md):

* Status rule boundaries: ACTIVE (<=10d), OVERDUE (10-80d),
  NO PROFILE DATA 80+ DAYS (>=80d), NO DATA (no timestamp; never "dead").
* JULD anchor math (days since 1950-01-01 UTC).
* FTP LIST parsing (real captured line shapes) and listing fingerprints.
* Profile summary from filenames only (Prof#, gaps, latest-file preference).
* Rtraj parsing from real-format synthetic NetCDF: JULD_LAST_MESSAGE
  selection, JULD_TRANSMISSION_END fallback, future-date rejection,
  last-fix selection, platform guard.
* Latest-profile parsing with missing-variable tolerance.
* Registry end-to-end against a FakeFTP GDAC: initial sync populates rows,
  unchanged fingerprints skip downloads, MDTM change re-downloads, outage
  keeps the cache and records the error, non-member floats get an explicit
  unavailable state, disabled mode is a no-op.
* build_wmo_identity_map reads real registry identities (PTT/IMEI).

No test touches the network. Run with:
    cd decoder-ui && PYTHONPATH=service:../src python -m pytest tests/test_fleet_status.py -q
"""

from __future__ import annotations

import ftplib
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

_TMP = tempfile.mkdtemp(prefix="decoder-ui-fleet-test-")
os.environ["ARGO_UI_DATA_DIR"] = _TMP

import fleet_status as fs  # noqa: E402
import netCDF4  # noqa: E402
import numpy as np  # noqa: E402
from fleet_status import FleetSyncRegistry, FloatSyncError  # noqa: E402

NOW = datetime.now(UTC)
EPOCH = datetime(1950, 1, 1, tzinfo=UTC)


def _juld(dt: datetime) -> float:
    return (dt - EPOCH).total_seconds() / 86400.0


# ---------------------------------------------------------------------------
# Synthetic NetCDF builders (real Argo shapes, tiny)
# ---------------------------------------------------------------------------


def _write_rtraj(
    path: Path,
    wmo: int,
    last_messages: list,
    tx_ends: list | None = None,
    statuses: list | None = None,
    meas: list | None = None,
    omit_cycle_msgs: bool = False,
) -> bytes:
    """N_CYCLE=len(last_messages); meas rows = (juld, lat, lon, cyc, mc, qc).

    omit_cycle_msgs reproduces vintage files whose per-cycle JULD message
    fields are absent entirely (observed: 2012-era Rtraj on live GDAC)."""
    n_cyc = len(last_messages)
    meas = meas or []
    ds = netCDF4.Dataset(str(path), "w", format="NETCDF4")
    try:
        ds.createDimension("N_CYCLE", n_cyc)
        ds.createDimension("N_MEASUREMENT", len(meas))
        ds.createDimension("ST8", 8)
        pn = ds.createVariable("PLATFORM_NUMBER", "S1", ("ST8",))
        pn[:] = np.frombuffer(f"{wmo:<8}"[:8].encode(), dtype="S1")
        if not omit_cycle_msgs:
            lm = ds.createVariable("JULD_LAST_MESSAGE", "f8", ("N_CYCLE",), fill_value=999999.0)
            lm[:] = np.array(last_messages, dtype=float)
            st = ds.createVariable("JULD_LAST_MESSAGE_STATUS", "S1", ("N_CYCLE",))
            st[:] = np.array(list(statuses or ["1"] * n_cyc), dtype="S1")
            te = ds.createVariable("JULD_TRANSMISSION_END", "f8", ("N_CYCLE",), fill_value=999999.0)
            te[:] = np.array(tx_ends if tx_ends is not None else [999999.0] * n_cyc, dtype=float)
        ci = ds.createVariable("CYCLE_NUMBER_INDEX", "i4", ("N_CYCLE",))
        ci[:] = np.arange(n_cyc, dtype=np.int32)
        if meas:
            ds.createVariable("JULD", "f8", ("N_MEASUREMENT",), fill_value=999999.0)[:] = np.array(
                [m[0] for m in meas], dtype=float
            )
            ds.createVariable("LATITUDE", "f8", ("N_MEASUREMENT",), fill_value=99999.0)[:] = (
                np.array([m[1] for m in meas], dtype=float)
            )
            ds.createVariable("LONGITUDE", "f8", ("N_MEASUREMENT",), fill_value=99999.0)[:] = (
                np.array([m[2] for m in meas], dtype=float)
            )
            ds.createVariable("CYCLE_NUMBER", "i4", ("N_MEASUREMENT",))[:] = np.array(
                [m[3] for m in meas], dtype=np.int32
            )
            ds.createVariable("MEASUREMENT_CODE", "i4", ("N_MEASUREMENT",))[:] = np.array(
                [m[4] for m in meas], dtype=np.int32
            )
            ds.createVariable("POSITION_QC", "S1", ("N_MEASUREMENT",))[:] = np.array(
                [m[5] for m in meas], dtype="S1"
            )
        for name, var in ds.variables.items():
            if name.startswith("JULD") and var.dtype.kind == "f":
                var.units = "days since 1950-01-01 00:00:00 UTC"
    finally:
        ds.close()
    return path.read_bytes()


def _write_profile(
    path: Path,
    juld=None,
    lat=None,
    lon=None,
    qc="1",
    cycle=7,
    with_pos=True,
    with_juld=True,
    with_location=True,
    wmo=2909999,
) -> bytes:
    ds = netCDF4.Dataset(str(path), "w", format="NETCDF4")
    try:
        ds.createDimension("N_PROF", 1)
        ds.createDimension("STRING8", 8)
        ds.createVariable("PLATFORM_NUMBER", "S1", ("N_PROF", "STRING8"))[:] = np.frombuffer(
            f"{wmo:<8}".encode(), dtype="S1"
        ).reshape(1, 8)
        if with_juld:
            v = ds.createVariable("JULD", "f8", ("N_PROF",), fill_value=999999.0)
            v[0] = 999999.0 if juld is None else float(juld)
            v.units = "days since 1950-01-01 00:00:00 UTC"
        if with_location:
            v = ds.createVariable("JULD_LOCATION", "f8", ("N_PROF",), fill_value=999999.0)
            v[0] = 999999.0 if juld is None else float(juld)
            v.units = "days since 1950-01-01 00:00:00 UTC"
        if with_pos:
            la = ds.createVariable("LATITUDE", "f8", ("N_PROF",), fill_value=99999.0)
            lo = ds.createVariable("LONGITUDE", "f8", ("N_PROF",), fill_value=99999.0)
            la[0] = 99999.0 if lat is None else float(lat)
            lo[0] = 99999.0 if lon is None else float(lon)
            ds.createVariable("POSITION_QC", "S1", ("N_PROF",))[:] = np.array([qc], dtype="S1")
        ds.createVariable("CYCLE_NUMBER", "i4", ("N_PROF",))[:] = np.array([cycle], dtype=np.int32)
    finally:
        ds.close()
    return path.read_bytes()


# ---------------------------------------------------------------------------
# 1. Status rule + JULD math
# ---------------------------------------------------------------------------


def test_status_boundaries():
    assert fs.profile_data_status(None) == "NO DATA"
    assert fs.profile_data_status(0) == "ACTIVE / RECENT PROFILE"
    assert fs.profile_data_status(10.0) == "ACTIVE / RECENT PROFILE"
    assert fs.profile_data_status(10.001) == "PROFILE OVERDUE"
    assert fs.profile_data_status(59.999) == "PROFILE OVERDUE"
    assert fs.profile_data_status(60.0) == "PROFILE OVERDUE"
    assert fs.profile_data_status(79.999) == "PROFILE OVERDUE"
    assert fs.profile_data_status(80.0) == "NO RECENT PROFILE DATA 80+ DAYS"
    assert fs.profile_data_status(4000.0) == "NO RECENT PROFILE DATA 80+ DAYS"
    assert "dead" not in fs.profile_data_status(4000.0).lower()


def test_juld_anchors():
    assert fs.juld_to_datetime(0.0) == datetime(1950, 1, 1, tzinfo=UTC)
    assert fs.juld_to_datetime(1.5) == datetime(1950, 1, 2, 12, 0, tzinfo=UTC)
    iso = fs.juld_to_iso(_juld(datetime(2026, 5, 4, 12, 0, tzinfo=UTC)))
    assert iso.startswith("2026-05-04T12:00")


# ---------------------------------------------------------------------------
# 2. LIST parsing + fingerprints
# ---------------------------------------------------------------------------


def test_parse_list_line_shapes():
    # Captured shapes from ftp.ifremer.fr (mtime year vs. time forms).
    a = fs.parse_list_line(
        "-rw-r--r--    1 ftp      ftp        210112 Jun 16 14:14 1902844_Rtraj.nc", NOW
    )
    assert a is not None and a[0] == "1902844_Rtraj.nc" and a[1] == 210112 and a[3] is False
    b = fs.parse_list_line(
        "-rw-r--r--    1 ftp      ftp         22192 Feb 04  2026 R1902844_001.nc", NOW
    )
    assert b is not None and b[0] == "R1902844_001.nc"
    assert datetime.fromtimestamp(b[2], tz=UTC).year == 2026
    d = fs.parse_list_line("drwxr-sr-x    3 ftp      ftp          4096 Sep 15 06:49 1902669", NOW)
    assert d is not None and d[3] is True
    assert fs.parse_list_line("total 1234", NOW) is None
    assert fs.parse_list_line("", NOW) is None
    assert fs.parse_list_line("garbage line", NOW) is None


def test_listing_fingerprint_stable_and_sensitive():
    e1 = [("a.nc", 10, 100.0), ("b.nc", 20, 200.0)]
    e2 = [("b.nc", 20, 200.0), ("a.nc", 10, 100.0)]
    assert fs.listing_fingerprint(e1) == fs.listing_fingerprint(e2)
    assert fs.listing_fingerprint(e1) != fs.listing_fingerprint([("a.nc", 10, 100.0)])
    assert fs.listing_fingerprint(e1) != fs.listing_fingerprint(
        [("a.nc", 11, 100.0), ("b.nc", 20, 200.0)]
    )


# ---------------------------------------------------------------------------
# 3. Profile summary from filenames
# ---------------------------------------------------------------------------


def test_summarize_profiles_gap_and_latest():
    files = [f"R1902844_{c:03d}.nc" for c in range(1, 26) if c != 22]
    s = fs.summarize_profiles(files, 1902844)
    assert s["max_cycle"] == 25
    assert s["missing"] == [22]
    assert s["latest"] == {"prefix": "R", "cycle": 25, "file": "R1902844_025.nc"}
    assert s["n_files"] == 24


def test_summarize_profiles_prefers_delayed_core_and_rejects_foreign_families():
    files = [
        "R2909999_010.nc",
        "D2909999_010.nc",
        "BR2909999_010.nc",
        "BD2909999_010.nc",
        "SR2909999_010.nc",
        "SD2909999_010.nc",
        "R2909999_001.nc",
        "ZZZ2909999_010.nc",
        "R1234567_010.nc",
    ]
    s = fs.summarize_profiles(files, 2909999)
    assert s["max_cycle"] == 10
    assert s["missing"] == list(range(2, 10))
    assert s["latest"]["prefix"] == "D"
    # Foreign-WMO and non-Argo-family files are ignored.
    assert s["n_files"] == 7
    assert s["available_cycles"] == 2


def test_summarize_profiles_empty():
    s = fs.summarize_profiles([], 2909999)
    assert s["max_cycle"] is None and s["latest"] is None and s["missing"] == []


# ---------------------------------------------------------------------------
# 4. Rtraj parsing
# ---------------------------------------------------------------------------


def test_parse_rtraj_selects_max_valid_last_message(tmp_path):
    raw = _write_rtraj(
        tmp_path / "t.nc",
        2909999,
        last_messages=[999999.0, _juld(NOW - timedelta(days=30)), _juld(NOW + timedelta(days=30))],
        statuses=[" ", "2", "1"],
        meas=[(_juld(NOW - timedelta(days=30)), 10.0, 65.0, 5, 703, "1")],
    )
    out = fs.parse_rtraj(raw, 2909999, NOW)
    assert out["last_tx_field"] == "JULD_LAST_MESSAGE"
    assert out["last_tx_status_rt19"] == "2"
    assert abs(out["last_tx_juld"] - _juld(NOW - timedelta(days=30))) < 1e-6
    assert out["last_fix"]["lat"] == 10.0
    assert out["last_fix"]["mc"] == 703


def test_parse_rtraj_falls_back_to_transmission_end(tmp_path):
    raw = _write_rtraj(
        tmp_path / "t.nc",
        2909999,
        last_messages=[999999.0, 999999.0],
        tx_ends=[999999.0, _juld(NOW - timedelta(days=5))],
        meas=[],
    )
    out = fs.parse_rtraj(raw, 2909999, NOW)
    assert out["last_tx_field"] == "JULD_TRANSMISSION_END"
    assert out["last_fix"] is None


def test_parse_rtraj_never_substitutes_measurement_max(tmp_path):
    now_j = _juld(NOW)
    raw = _write_rtraj(
        tmp_path / "t.nc",
        2909999,
        last_messages=[999999.0, now_j + 30.0],  # fill + future: unusable
        tx_ends=[999999.0, 999999.0],
        meas=[
            (now_j - 4000.0, 10.0, 65.0, 3, 703, "1"),
            (now_j - 3900.0, 10.5, 65.5, 4, 703, "1"),  # winner
            (now_j + 30.0, 10.5, 65.5, 5, 703, "1"),  # future: excluded
        ],
    )
    out = fs.parse_rtraj(raw, 2909999, NOW)
    assert out["last_tx_field"] is None
    assert out["last_tx_juld"] is None
    assert "not communication evidence" in out["communication_error"]
    assert out["last_fix"]["juld"] == pytest.approx(now_j - 3900.0)


def test_parse_rtraj_vintage_file_without_cycle_msgs(tmp_path):
    # 2012-era shape: per-cycle message variables absent entirely.
    now_j = _juld(NOW)
    raw = _write_rtraj(
        tmp_path / "t.nc",
        2909999,
        last_messages=[100.0],
        meas=[(now_j - 5000.0, -20.0, 70.0, 12, 703, "1")],
        omit_cycle_msgs=True,
    )
    out = fs.parse_rtraj(raw, 2909999, NOW)
    assert out["last_tx_field"] is None
    assert out["last_tx_iso"] is None
    assert out["last_fix"]["lat"] == -20.0


def test_parse_rtraj_rejects_unusable(tmp_path):
    raw = _write_rtraj(
        tmp_path / "t.nc",
        2909999,
        last_messages=[999999.0, _juld(NOW + timedelta(days=30))],
        tx_ends=[999999.0, 999999.0],
    )
    parsed = fs.parse_rtraj(raw, 2909999, NOW)
    assert parsed["last_tx_iso"] is None
    assert parsed["communication_error"]


def test_parse_rtraj_platform_guard(tmp_path):
    raw = _write_rtraj(tmp_path / "t.nc", 1111111, last_messages=[100.0])
    with pytest.raises(FloatSyncError):
        fs.parse_rtraj(raw, 2909999, NOW)


def test_parse_rtraj_last_fix_skips_bad_positions(tmp_path):
    now_j = _juld(NOW)
    raw = _write_rtraj(
        tmp_path / "t.nc",
        2909999,
        last_messages=[now_j - 9],
        meas=[
            (now_j - 10, 8.0, 65.0, 8, 703, "1"),  # latest usable fix
            (now_j - 9, 99999.0, 99999.0, 9, 703, "1"),  # fill position
            (now_j - 8, 95.0, 10.0, 9, 703, "1"),  # impossible latitude
            (now_j - 7, 9.0, 66.0, 9, 703, "4"),  # bad QC: excluded
            (now_j + 30, 9.0, 66.0, 9, 703, "1"),  # future JULD
        ],
    )
    out = fs.parse_rtraj(raw, 2909999, NOW)
    assert out["last_fix"]["lat"] == 8.0
    assert out["last_fix"]["pos_qc"] == "1"


# ---------------------------------------------------------------------------
# 5. Profile parsing
# ---------------------------------------------------------------------------


def test_parse_profile_values(tmp_path):
    raw = _write_profile(
        tmp_path / "p.nc", juld=_juld(NOW - timedelta(days=2)), lat=9.85, lon=66.0, qc="1", cycle=25
    )
    out = fs.parse_profile(raw, 2909999, 25, NOW)
    assert out["lat"] == 9.85 and out["lon"] == 66.0
    assert out["pos_qc"] == "1" and out["cycle"] == 25
    assert out["cycle_mismatch"] is False
    assert out["juld_iso"].startswith((NOW - timedelta(days=2)).strftime("%Y-%m-%d"))


def test_parse_profile_tolerates_missing_vars(tmp_path):
    raw = _write_profile(tmp_path / "p.nc", with_pos=False, with_juld=False, cycle=25)
    out = fs.parse_profile(raw, 2909999, 25, NOW)
    assert out["lat"] is None and out["juld"] is None and out["cycle"] == 25


def test_parse_profile_cycle_mismatch_flagged(tmp_path):
    raw = _write_profile(tmp_path / "p.nc", juld=_juld(NOW - timedelta(days=1)), cycle=24)
    out = fs.parse_profile(raw, 2909999, 25, NOW)
    assert out["cycle_mismatch"] is True


# ---------------------------------------------------------------------------
# 6. Registry end-to-end against a fake GDAC (no network)
# ---------------------------------------------------------------------------


class FakeFTP:
    """Minimal ftplib-compatible GDAC double."""

    def __init__(self, members, rtraj, profiles_lists, profile_files, mdtms):
        self.members = members
        self.rtraj = rtraj  # wmo -> bytes
        self.profiles_lists = profiles_lists  # wmo -> [LIST lines]
        self.profile_files = profile_files  # filename -> bytes
        self.mdtms = mdtms  # path suffix -> mdtm str
        self.downloads = []

    def nlst(self, path):
        assert path.endswith("/dac/incois")
        return list(self.members)

    def size(self, path):
        for wmo, raw in self.rtraj.items():
            if path.endswith(f"{wmo}_Rtraj.nc"):
                return len(raw)
        for name, raw in self.profile_files.items():
            if path.endswith(name):
                return len(raw)
        raise ftplib.error_perm("550 not found")

    def sendcmd(self, cmd):
        assert cmd.startswith("MDTM ")
        for suffix, mdtm in self.mdtms.items():
            if cmd[5:].endswith(suffix):
                return f"213 {mdtm}"
        raise ftplib.error_perm("550 not found")

    def retrlines(self, cmd, cb):
        assert cmd.startswith("LIST ")
        for wmo, lines in self.profiles_lists.items():
            if f"/{wmo}/profiles" in cmd:
                for ln in lines:
                    cb(ln)
                return
        raise ftplib.error_perm("550 not found")

    def retrbinary(self, cmd, cb, blocksize=1 << 20):
        assert cmd.startswith("RETR ")
        p = cmd[5:]
        self.downloads.append(p.rsplit("/", 1)[-1])
        for wmo, raw in self.rtraj.items():
            if p.endswith(f"{wmo}_Rtraj.nc"):
                cb(raw)
                return
        for name, raw in self.profile_files.items():
            if p.endswith(name):
                cb(raw)
                return
        raise ftplib.error_perm("550 not found")

    def quit(self):
        pass

    def close(self):
        pass


def _fleet_fn():
    return [
        {"wmo": 2909999, "platform_type": "PROVOR_III", "transmission_type": "IRIDIUM_SBD"},
        {"wmo": 6900000, "platform_type": "ARVOR", "transmission_type": "IRIDIUM_SBD"},
    ]


def _reg(tmp_path, **kw):
    kw.setdefault("fleet_fn", _fleet_fn)
    kw.setdefault("state_path", tmp_path / "cache.json")
    return FleetSyncRegistry(**kw)


def _fake_gdac(tmp_path, last_tx_days_ago=3):
    rtraj = _write_rtraj(
        tmp_path / "r.nc",
        2909999,
        last_messages=[_juld(NOW - timedelta(days=last_tx_days_ago))],
        meas=[(_juld(NOW - timedelta(days=last_tx_days_ago)), 10.0, 65.0, 9, 703, "1")],
    )
    prof = _write_profile(
        tmp_path / "p.nc", juld=_juld(NOW - timedelta(days=2)), lat=9.85, lon=66.0, cycle=25
    )
    lines = ["total 24"] + [
        f"-rw-r--r--    1 ftp      ftp         22228 Sep 09 06:14 R2909999_{c:03d}.nc"
        for c in range(1, 26)
        if c != 22
    ]
    return FakeFTP(
        members=["2909999"],
        rtraj={2909999: rtraj},
        profiles_lists={2909999: lines},
        profile_files={"R2909999_025.nc": prof, "2909999_prof.nc": prof},
        mdtms={"2909999_Rtraj.nc": "20260909061405", "2909999_prof.nc": "20260909061405"},
    )


def test_sync_initial_cycle_populates_rows(tmp_path, monkeypatch):
    fake = _fake_gdac(tmp_path)
    reg = _reg(tmp_path)
    monkeypatch.setattr(reg, "_connect", lambda: fake)
    monkeypatch.setattr(
        "datasources.local.build_wmo_identity_map", lambda: {2909999: {"ptt": "10255", "imei": ""}}
    )
    res = reg.sync_now()
    assert res["accepted"] is True and res["status"] == "ok"
    assert fake.downloads == ["2909999_prof.nc", "2909999_Rtraj.nc", "R2909999_025.nc"]
    payload = reg.payload()
    assert payload["summary"]["total"] == 2
    row = next(f for f in payload["floats"] if f["wmo"] == 2909999)
    assert row["data_status"] == "ACTIVE / RECENT PROFILE"
    assert row["internal_id"] == "10255"
    assert row["prof_num"] == 25
    assert row["profiles_missing"] == 1
    assert row["profiles_missing_list"] == [22]
    assert row["lat"] == 9.85 and row["pos_source"] == "profile"
    assert row["last_profile_field"] == "JULD"
    assert row["last_profile_file"] == "2909999_prof.nc"
    assert abs(row["days_since_last_profile"] - 2.0) < 0.05
    assert row["expected_next_profile_iso"] is not None
    assert row["approx_profiles_missed"] == 0  # inventory still has one exact gap
    assert "last_tx_iso" not in row
    ghost = next(f for f in payload["floats"] if f["wmo"] == 6900000)
    assert ghost["data_status"] == "NO DATA"
    assert ghost["in_incois_dac"] is False
    assert payload["sync"]["status"] == "ok"
    assert payload["sync"]["last_success_at"] is not None
    # Cache persisted and reloadable.
    assert (tmp_path / "cache.json").is_file()
    reg2 = _reg(tmp_path)
    assert len(reg2.payload()["floats"]) == 2


def test_sync_skips_unchanged_and_redownloads_on_mdtm_change(tmp_path, monkeypatch):
    fake = _fake_gdac(tmp_path)
    reg = _reg(tmp_path)
    monkeypatch.setattr(reg, "_connect", lambda: fake)
    assert reg.sync_now()["status"] == "ok"
    fake.downloads.clear()
    res = reg.sync_now()
    assert res["counts"] == {"total": 2, "updated": 0, "unchanged": 2, "failed": 0}
    assert fake.downloads == []
    # Upstream Rtraj touched -> re-downloaded and re-parsed.
    fake.mdtms["2909999_Rtraj.nc"] = "20260910061405"
    fake.downloads.clear()
    res = reg.sync_now()
    assert res["counts"]["updated"] == 1
    assert fake.downloads == ["2909999_Rtraj.nc"]


def test_sync_outage_keeps_cache_and_records_error(tmp_path, monkeypatch):
    fake = _fake_gdac(tmp_path)
    reg = _reg(tmp_path)
    monkeypatch.setattr(reg, "_connect", lambda: fake)
    assert reg.sync_now()["status"] == "ok"

    def _boom():
        raise ConnectionError("no route to host")

    monkeypatch.setattr(reg, "_connect", _boom)
    res = reg.sync_now()
    assert res["status"] == "error"
    payload = reg.payload()
    assert payload["sync"]["status"] == "error"
    assert "no route to host" in (payload["sync"]["error"] or "")
    # Last valid rows still serve.
    row = next(f for f in payload["floats"] if f["wmo"] == 2909999)
    assert row["data_status"] == "ACTIVE / RECENT PROFILE" and row["prof_num"] == 25
    assert payload["sync"]["last_success_at"] is not None


def test_sync_per_float_failure_degrades_and_retains_row(tmp_path, monkeypatch):
    fake = _fake_gdac(tmp_path)
    reg = _reg(tmp_path)
    monkeypatch.setattr(reg, "_connect", lambda: fake)
    assert reg.sync_now()["status"] == "ok"
    # Rtraj vanishes upstream for the known float.
    fake.rtraj = {}
    fake.mdtms = {}
    res = reg.sync_now()
    assert res["status"] == "degraded"
    payload = reg.payload()
    row = next(f for f in payload["floats"] if f["wmo"] == 2909999)
    assert row["data_status"] == "ACTIVE / RECENT PROFILE"  # retained row still derives
    assert row["error"] is not None
    assert row["in_incois_dac"] is True  # DAC membership still recorded


def test_sync_disabled_is_noop(tmp_path):
    reg = _reg(tmp_path, enabled=False)
    assert reg.sync_now() == {"accepted": False, "state": "disabled"}
    assert reg.payload()["sync"]["status"] == "disabled"


def test_sync_guard_rejects_concurrent_cycle(tmp_path):
    reg = _reg(tmp_path, enabled=True)
    assert reg.try_begin() is True
    assert reg.try_begin() is False
    reg._end()
    assert reg.try_begin() is True
    reg._end()


def test_serve_row_status_matrix():
    base = {
        "wmo": 1,
        "in_incois_dac": True,
        "parser_version": fs.PARSER_VERSION,
        "rtraj": {},
        "profiles": {},
        "error": None,
        "updated_at": None,
    }
    for days, want in [
        (3, fs.STATUS_RECENT),
        (30, fs.STATUS_OVERDUE),
        (200, fs.STATUS_NO_RECENT_60),
    ]:
        row = dict(
            base,
            profile_aggregate={
                "file": "1_prof.nc",
                "platform_number": "1",
                "juld": _juld(NOW - timedelta(days=days)),
            },
        )
        got = FleetSyncRegistry._serve_row(1, row, {"platform_type": "APEX"}, {}, NOW)
        assert got["data_status"] == want
        assert got["expected_next_profile_iso"] is not None
    nodata = FleetSyncRegistry._serve_row(1, base, {}, {}, NOW)
    assert nodata["data_status"] == "NO DATA"


# ---------------------------------------------------------------------------
# 7. Identity map from real registries
# ---------------------------------------------------------------------------


def test_build_wmo_identity_map_reads_real_registries():
    from datasources.local import build_wmo_identity_map

    m = build_wmo_identity_map()
    assert isinstance(m, dict)
    # registry_apf9.csv ships wmo/ptt/imei columns (no decoder import needed).
    assert m[2901304]["ptt"] == "102525"
    assert m[2901328]["ptt"] == "102507"
    assert m[2901328]["imei"] == ""  # no IMEI on record — never guessed
    assert all(set(v) == {"ptt", "imei"} for v in m.values())


def test_build_wmo_identity_map_includes_csv4_when_available():
    pytest.importorskip("argo_decoder")
    from datasources.local import build_wmo_identity_map

    m = build_wmo_identity_map()
    # config/metadata csv4 fleet carries real PTT identities.
    assert m[1902844]["ptt"] == "123230"
    assert m[2901304]["ptt"] == "102525"
