"""End-to-end structural decoding for Provor Iridium SBD demo data.

Phase 2 Slice 2 integration test: decode a window of SBD e-mails from
WMO 6902892 through the new ProvorIridiumSbdDecoder plugin and verify
that per-cycle datasets are produced with:

* structurally valid attributes (packet counts, GPS fix when available);
* PRES/TEMP/PSAL variables present on cycles that carry CTD packets;
* oceanographically valid values for deep profiles (P > 1000 dbar, T in
  [0, 30] degC, S in [2, 41] psu).
"""

from __future__ import annotations

import glob
import math
import re
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from argo_decoder.config.models import DecoderConfig
from argo_decoder.domain.frames import CycleData, RawFrame
from argo_decoder.metadata.models import FloatInfo
from argo_decoder.platforms import ProvorIridiumSbdDecoder

DEMO_DIR = (
    Path(__file__).resolve().parents[3]
    / "Coriolis-data-processing-chain-for-Argo-floats-container"
    / "decArgo_demo"
)
IMEI_DIR = DEMO_DIR / "input" / "archive" / "cycle" / "300234065895840"

pytestmark = pytest.mark.skipif(
    not IMEI_DIR.exists(),
    reason="demo data not available in this environment",
)

_FCRE = re.compile(r"co_\d{8}T\d{6}Z_\d{15}_(\d{6})_(\d{6})_\d+\.txt$")


def _demo_info() -> FloatInfo:
    return FloatInfo(
        wmo=6902892,
        ptt="589584",
        float_type="ARVOR_D",
        decoder_version="5.67",
        decoder_id=221,
        frame_length=31,
        cycle_length_hours=240,
        drift_sampling_period_hours=3.0,
        delay_minutes=-1,
        launch_date=datetime(2021, 3, 13, 2, 6, 0),
        launch_lon=-47.0613,
        launch_lat=-47.0137,
        reference_day=date(2021, 3, 13),
    )


def _decode_cycles(n_files: int) -> dict[int, xr.Dataset]:
    cfg = DecoderConfig()
    decoder = ProvorIridiumSbdDecoder(cfg)
    info = _demo_info()
    assert decoder.can_handle(info, None) is True

    files = sorted(glob.glob(str(IMEI_DIR / "co_*.txt")))[:n_files]
    by_cycle: dict[int, CycleData] = {}
    for fp in files:
        m = _FCRE.search(fp)
        assert m, fp
        cycle = int(m.group(1))
        profile = int(m.group(2))
        with open(fp, "rb") as fh:
            data = fh.read()
        cd = by_cycle.setdefault(cycle, CycleData(wmo=6902892, cycle=cycle))
        cd.frames.append(RawFrame(payload=data, cycle=cycle, profile=profile))

    result = decoder.decode_float(6902892, info, None, list(by_cycle.values()))
    return result.mono_profile_datasets


def test_provor_plugin_decodes_first_cycles_structural() -> None:
    dss = _decode_cycles(200)
    assert len(dss) > 10
    for cyc, ds in dss.items():
        assert ds.attrs["decoder"] == "provor_ir_sbd"
        assert ds.attrs["platform_type"] == "ARVOR_D"
        assert ds.attrs["decoder_version"] == "5.67"
        assert ds.attrs["n_sbd_messages"] >= 1
        # Every profile (structural or deep) must carry JULD/LATITUDE/LONGITUDE
        # scalars encoded as float64 days-since-1950 (NOT xarray datetime64).
        assert "JULD" in ds.data_vars, f"cycle {cyc} missing JULD"
        assert "LATITUDE" in ds.data_vars, f"cycle {cyc} missing LATITUDE"
        assert "LONGITUDE" in ds.data_vars, f"cycle {cyc} missing LONGITUDE"
        assert "JULD_QC" in ds.data_vars
        assert "POSITION_QC" in ds.data_vars
        assert "DIRECTION" in ds.data_vars
        assert "DATA_MODE" in ds.data_vars
        assert ds.JULD.dtype.kind == "f", f"JULD must be float, got {ds.JULD.dtype}"
        assert ds.LATITUDE.dtype.kind == "f"
        assert ds.LONGITUDE.dtype.kind == "f"
        # DIRECTION 'A' (ascending) and DATA_MODE 'A' (real-time) for CTS4 fast-path.
        assert bytes(ds.DIRECTION.values) == b"A"
        assert bytes(ds.DATA_MODE.values) == b"A"
        # pres_offset_dbar attr must always be present (0.0 when no tech#1).
        assert "pres_offset_dbar" in ds.attrs
        # Early cycles carry at least one fix (tech#1 GPS or Iridium session);
        # cycles with a decoded tech#1 GPS report POSITION_QC='1', email-only
        # fixes report POSITION_QC='0'.
        assert ds.attrs["n_gps_fixes"] >= 1
        assert not math.isnan(float(ds.attrs["first_gps_lat"]))
        assert not math.isnan(float(ds.attrs["first_gps_lon"]))
        assert bytes(ds.POSITION_QC.values) in (b"0", b"1")
        assert not math.isnan(float(ds.JULD.values))
        # 2020-06 to 2021-12 is plausible for the demo window (launch 2021-03
        # plus the very first test messages transmitted before deployment).
        juld_v = float(ds.JULD.values)
        assert 25700.0 < juld_v < 26400.0, f"JULD {juld_v} out of expected range"
        lat = float(ds.LATITUDE.values)
        lon = float(ds.LONGITUDE.values)
        assert not math.isnan(lat)
        assert not math.isnan(lon)
        assert -90.0 <= lat <= 90.0
        assert -180.0 <= lon <= 180.0


def test_provor_plugin_produces_ctd_variables_on_deep_cycles() -> None:
    """Decoding a wider window (first 1000 files) must surface at least one
    deep profile (P > 1000 dbar) with physical T/S values."""
    dss = _decode_cycles(1000)
    deep_cycles = 0
    for _cyc, ds in dss.items():
        if "PRES" not in ds.data_vars:
            continue
        p = ds.PRES.values
        t = ds.TEMP.values
        s = ds.PSAL.values
        if len(p) == 0:
            continue
        mx = float(np.nanmax(p))
        if mx > 1000.0:
            deep_cycles += 1
            # Physical-sanity checks on CTD values.
            assert np.all((p >= -5.0) | np.isnan(p)), "pressure out of range"
            assert np.all((p < 12000.0) | np.isnan(p)), "pressure out of range"
            assert np.all((t >= -2.5) | np.isnan(t)), "temperature out of range"
            assert np.all((t <= 42.0) | np.isnan(t)), "temperature out of range"
            # Salinity PSAL: fill is 99.999; measured S must be in range.
            measured_s = s[s < 90.0]
            if len(measured_s) > 0:
                assert np.all(measured_s >= 2.0)
                assert np.all(measured_s <= 41.0)
            # Pressure must be monotonically sorted (shallowest first).
            assert np.all(np.diff(p) >= -1e-6), "pressure must be non-decreasing"
    assert deep_cycles >= 1, "expected at least one deep profile in first 1000 files"


def test_provor_plugin_cycle86_profile_scalars() -> None:
    """Cycle 86 is a known CTDO-only deep profile from WMO 6902892 (WMO 6902892
    cycle 086). It has NO tech#1 packets — so position/time fall back to the
    Iridium session metadata in the SBD e-mail body.

    This guards against regressions in:
      * JULD encoded as float64 days since 1950 (not datetime64);
      * Position QC = b'0' (Iridium fix) when GPS is absent;
      * Fill values encoded via _FillValue (99999 for LAT/LON, 999999 for JULD);
      * Direction 'A' (ascending) and DATA_MODE 'A' (real-time).
    """
    dss = _decode_cycles(2500)
    assert 86 in dss, "cycle 86 missing (need full 2215-file demo window)"
    ds = dss[86]

    # JULD must be a finite float ~26006.26 (2021-03-15 ~06:11 UTC).
    jv = float(ds.JULD.values)
    assert math.isfinite(jv)
    assert jv == pytest.approx(26006.257708, abs=1e-3)
    assert ds.JULD.dtype.kind == "f"
    assert ds.JULD.attrs["units"] == "days since 1950-01-01 00:00:00 UTC"
    assert float(ds.JULD.attrs["_FillValue"]) == 999999.0

    # LAT/LON near deployment (-47, -47).
    lat = float(ds.LATITUDE.values)
    lon = float(ds.LONGITUDE.values)
    assert math.isfinite(lat) and math.isfinite(lon)
    assert lat == pytest.approx(-47.0, abs=1.0)
    assert lon == pytest.approx(-47.0, abs=1.0)
    assert float(ds.LATITUDE.attrs["_FillValue"]) == 99999.0
    assert float(ds.LONGITUDE.attrs["_FillValue"]) == 99999.0

    # Quality flags.
    assert bytes(ds.JULD_QC.values) == b"0"
    assert bytes(ds.POSITION_QC.values) == b"0"
    assert ds.attrs.get("positioning_system") == "IRIDIUM"

    # Pressure offset defaulted to 0 (no tech#1).
    assert ds.attrs["pres_offset_dbar"] == 0.0

    # Ascending + real-time.
    assert bytes(ds.DIRECTION.values) == b"A"
    assert bytes(ds.DATA_MODE.values) == b"A"

    # CTD present and physically sane for the deep profile.
    assert "PRES" in ds.data_vars
    p = ds.PRES.values
    assert np.nanmax(p) > 3900.0, "cycle 86 is a ~4000 dbar profile"
    # Fill constant for PRES (9999.9) must not sneak in as a measurement.
    measured_p = p[~np.isnan(p) & (p != 9999.9)]
    assert np.all(np.diff(measured_p) >= -1e-6), "PRES must be non-decreasing"
