"""Phase-4 CTS4 real-time products — real-corpus integration (12170 group).

Runs the production pipeline once over the 517-file corpus subset (12170,
cycles 98-114, 63 files) and pins the float-level product contract:
layout, accumulating tech (95 rows/cycle), accumulating Rtraj (adjudicated
MC set, GDAC-anchored event JULDs), mono-cycle R/BR, gsw DOXY, no D/BD,
no fabrication. WMO 2902086 is the externally supplied COMPARISON-ONLY
hypothesis (FLBB serial 2663); the decoder never branches on it.
"""

from __future__ import annotations

from pathlib import Path

import netCDF4
import numpy as np
import pytest

from argo_decoder.platforms.provor_cts4_ir_sbd.cts4_realtime import (
    process_float,
)
from argo_decoder.platforms.provor_cts4_ir_sbd.external_meta_io import (
    build_external_meta_from_gdac,
)

WORKSPACE = Path(__file__).resolve().parents[2]
GROUP = WORKSPACE / "provor_bio_irsbd/raw_telemetry/SBD-BGC-raw/12170"
REF = WORKSPACE / "provor_bio_irsbd/ref/gdac_incois_301"
WMO = "2902086"
# The published CYCLE_NUMBER is the telemetry SubCyclesDoneSinceDeployment
# counter, which is what GDAC uses; the float-internal counter is one lower.
# So telemetry internal cycle 98 is published (and compared) as cycle 99.
TEL0 = GD0 = 99
INTERNAL0 = 98

pytestmark = pytest.mark.skipif(
    not GROUP.is_dir(), reason="12170 raw corpus not present"
)


@pytest.fixture(scope="module")
def products(tmp_path_factory) -> dict:
    out = tmp_path_factory.mktemp("cts4_products")
    em = build_external_meta_from_gdac(REF / "incois_2902086_meta.nc", WMO)
    res = process_float(GROUP, WMO, out, em)
    return {"res": res, "dir": out / WMO}


def test_layout_is_float_level(products) -> None:
    d = products["dir"]
    assert (d / f"{WMO}_meta.nc").is_file()
    assert (d / f"{WMO}_tech.nc").is_file()
    assert (d / f"{WMO}_Rtraj.nc").is_file()
    # exactly ONE meta/tech/Rtraj (no per-cycle duplicates)
    assert len(list(d.rglob("*_meta.nc"))) == 1
    assert len(list(d.rglob("*_tech.nc"))) == 1
    assert len(list(d.rglob("*_Rtraj.nc"))) == 1
    r = sorted(p.name for p in (d / "profiles").glob(f"R{WMO}_*.nc"))
    br = sorted(p.name for p in (d / "profiles").glob(f"BR{WMO}_*.nc"))
    # R: published cycles 99-114 minus 103 (no CTD); BR: 99-114
    assert len(r) == 15 and f"R{WMO}_099.nc" in r and f"R{WMO}_103.nc" not in r
    assert len(br) == 16
    assert not list(d.rglob(f"D{WMO}_*.nc"))
    assert not list(d.rglob(f"BD{WMO}_*.nc"))


def test_skips_are_data_coverage_only(products) -> None:
    skipped = products["res"].skipped
    assert 103 in skipped and "no CTD" in skipped[103]
    assert 115 in skipped and "tech-only" in skipped[115]
    assert set(skipped) <= {103, 115}


def test_tech_accumulates_95_rows_per_cycle(products) -> None:
    with netCDF4.Dataset(str(products["dir"] / f"{WMO}_tech.nc")) as ds:
        cyc = np.asarray(ds.variables["CYCLE_NUMBER"][:]).astype(int)
        names = [str(x).strip() for x in netCDF4.chartostring(
            ds.variables["TECHNICAL_PARAMETER_NAME"][:])]
    assert len(cyc) == 17 * 95
    for c in range(99, 116):
        assert int((cyc == c).sum()) == 95, c
    # GDAC-verified clock value (cycle 99 -> FloatTime 20140221035709)
    i = next(k for k, (n, c) in enumerate(zip(names, cyc))
             if c == TEL0 and n == "CLOCK_FloatTime_YYYYMMDDHHMMSS")
    with netCDF4.Dataset(str(products["dir"] / f"{WMO}_tech.nc")) as ds:
        vals = [str(x).strip() for x in netCDF4.chartostring(
            ds.variables["TECHNICAL_PARAMETER_VALUE"][:])]
    assert vals[i] == "20140221035709"


def test_rtraj_accumulates_adjudicated_structure(products) -> None:
    with netCDF4.Dataset(str(products["dir"] / f"{WMO}_Rtraj.nc")) as ds:
        assert len(ds.dimensions["N_CYCLE"]) == 18   # launch + 17 cycles
        assert len(ds.dimensions["N_PARAM"]) == 12
        mc = np.asarray(ds.variables["MEASUREMENT_CODE"][:]).astype(int)
        cy = np.asarray(ds.variables["CYCLE_NUMBER"][:]).astype(int)
        # Launch measurement is MC 0 on cycle 0 (the launch cycle), matching
        # CYCLE_NUMBER_INDEX[0] and the N_CYCLE launch row.
        assert int(((cy == 0) & (mc == 0)).sum()) == 1
        assert int((cy < 0).sum()) == 0
        # MC 703 count == valid-fix 253 count (>=1 per cycle)
        assert int((mc == 703).sum()) >= 17
        dm = ds.variables["DATA_MODE"][:].tobytes().decode()
        assert set(dm.strip()) <= {"R"}


def test_rtraj_event_julds_match_gdac(products) -> None:
    ours = netCDF4.Dataset(str(products["dir"] / f"{WMO}_Rtraj.nc"))
    gd = netCDF4.Dataset(str(REF / "incois_2902086_Rtraj.nc"))
    try:
        mc = np.asarray(ours.variables["MEASUREMENT_CODE"][:]).astype(int)
        cy = np.asarray(ours.variables["CYCLE_NUMBER"][:]).astype(int)
        ju = np.asarray(ours.variables["JULD"][:])
        gmc = np.asarray(gd.variables["MEASUREMENT_CODE"][:]).astype(int)
        gcy = np.asarray(gd.variables["CYCLE_NUMBER"][:]).astype(int)
        gju = np.asarray(gd.variables["JULD"][:])

        def one(c, code, m, y, j):
            s = np.where((y == c) & (m == code))[0]
            return float(j[s[0]])

        for code, tol_min in ((89, 2.0), (150, 2.0), (250, 2.0), (450, 2.0),
                              (500, 2.0), (600, 2.0)):
            d = abs(one(TEL0, code, mc, cy, ju)
                    - one(GD0, code, gmc, gcy, gju)) * 1440
            assert d <= tol_min, (code, d)
        # hydraulic series: counts equal (incl. GDAC's closing 589 row) and
        # JULDs within 1 minute
        for code in (189, 389, 589):
            so = np.where((cy == TEL0) & (mc == code))[0]
            sg = np.where((gcy == GD0) & (gmc == code))[0]
            assert len(so) == len(sg), (code, len(so), len(sg))
            jo = np.sort(ju[so]); jg = np.sort(gju[sg])
            assert float(np.abs(jo - jg).max()) * 1440 < 1.0
        # pressure extremes exact
        pres = np.asarray(ours.variables["PRES"][:])
        gpres = np.asarray(gd.variables["PRES"][:])
        for code, expect in ((198, 980.0), (297, 980.0), (298, 1000.0),
                             (398, 1980.0), (497, 1980.0), (498, 1980.0)):
            s = np.where((cy == TEL0) & (mc == code))[0]
            assert abs(float(pres[s[0]]) - expect) < 0.51, code
            sg = np.where((gcy == GD0) & (gmc == code))[0]
            assert abs(float(pres[s[0]]) - float(gpres[sg[0]])) < 0.51
    finally:
        ours.close()
        gd.close()


def test_rbr_realtime_semantics_and_gsw_doxy(products) -> None:
    d = products["dir"] / "profiles"
    with netCDF4.Dataset(str(d / f"R{WMO}_{TEL0:03d}.nc")) as r:
        assert r.getncattr("Conventions") == "Argo-3.1 CF-1.6"
        dm = r.variables["DATA_MODE"][:].tobytes().decode()
        assert set(dm) == {"R"}
        assert int(r.variables["CYCLE_NUMBER"][0]) == TEL0
        p = r.variables["PRES"][2]
        assert 1980.0 < float(p[p < 90000].max()) < 1982.0
    with netCDF4.Dataset(str(d / f"BR{WMO}_{TEL0:03d}.nc")) as b:
        dm = b.variables["DATA_MODE"][:].tobytes().decode()
        assert set(dm) == {"R"}
        pdm = b.variables["PARAMETER_DATA_MODE"][:]
        flat = set(pdm.tobytes().decode()) - {"\x00", " "}
        assert flat == {"R"}
        dv = b.variables["DOXY"][2]
        dv = dv[dv < 90000]
        # gsw chain: deep median in the BoB OMZ band, NOT a 1.025 artifact
        assert len(dv) == 140
        assert 20.0 < float(np.median(dv)) < 60.0
        bv = b.variables["BBP700"][3]
        bv = bv[bv < 90000]
        assert len(bv) == 141 and 3e-4 < float(bv.max()) < 1.5e-3


def test_wmo_is_external_and_validated(products, tmp_path) -> None:
    em = build_external_meta_from_gdac(REF / "incois_2902086_meta.nc", WMO)
    with pytest.raises(ValueError):
        process_float(GROUP, "12170", tmp_path, em)      # IMEI not a WMO
    with pytest.raises(ValueError):
        process_float(GROUP, "290209", tmp_path, em)     # 6 digits
