"""Integration tests: ARVOR-I ``<WMO>_meta.nc`` over both raw datasets.

Phase-6 validation, pinned to ``docs/phase_reports/ARVOR_I_META_NC_MAPPING_2026-08-27.md``:

* 65-variable layout/order/dtypes identical to the GDAC references;
* telemetry- and family-derived values equal GDAC (platform identity,
  transmission/positioning systems, LAUNCH_DATE — the established launch
  constants are GDAC-equal — and the blanks that GDAC also carries blank);
* registry-sourced fields stay proper fills/blanks (DATA-COVERAGE; the
  Coriolis registry ``<wmo>_meta.json`` does not exist in this workspace
  and values are never copied from GDAC);
* clamped one-row CONFIG/SENSOR/PARAMETER blocks carry fills only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import netCDF4
import numpy as np
import pytest

from argo_decoder.platforms.provor_ir_sbd.arvor_i import read_arvor_i_eml
from argo_decoder.platforms.provor_ir_sbd.arvor_i_meta import (
    build_arvor_meta_nc,
    write_arvor_meta_nc,
)
from argo_decoder.platforms.provor_ir_sbd.arvor_i_science import reconstruct_science

ARGO_PY_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ARGO_PY_ROOT.parent
RAW_ROOT = WORKSPACE / "arvor_raw" / "ARVOR-I-raw-files" / "20260819"
REF_ROOT = WORKSPACE / "gdac_arvor_i_ref"

LAUNCHES = {
    6990711: datetime(2025, 3, 2, 5, 16, tzinfo=UTC),
    7902408: datetime(2026, 3, 25, 17, 44, tzinfo=UTC),
}

pytestmark = pytest.mark.skipif(not RAW_ROOT.exists(), reason="ARVOR-I raw datasets not present")


@pytest.fixture(scope="module")
def meta_files(tmp_path_factory: pytest.TempPathFactory) -> dict[int, Path]:
    out: dict[int, Path] = {}
    for wmo, launch in LAUNCHES.items():
        msgs = [read_arvor_i_eml(p) for p in sorted((RAW_ROOT / str(wmo)).glob("*.eml"))]
        result = reconstruct_science(msgs, launch)
        ds = build_arvor_meta_nc(wmo=wmo, launch_date=launch, result=result)
        path = tmp_path_factory.mktemp(f"meta_{wmo}") / f"{wmo}_meta.nc"
        write_arvor_meta_nc(ds, path)
        out[wmo] = path
    return out


def _text(d: netCDF4.Dataset, name: str) -> str:
    d.set_auto_mask(False)
    return bytes(np.asarray(d[name][:]).reshape(-1)).decode().rstrip()


def test_layout_matches_gdac_references(meta_files: dict[int, Path]) -> None:
    if not REF_ROOT.exists():
        pytest.skip("GDAC meta references not present")
    for wmo, path in meta_files.items():
        ours = netCDF4.Dataset(path)
        ref = netCDF4.Dataset(REF_ROOT / f"{wmo}_meta.nc")
        try:
            assert ours.data_model == "NETCDF3_CLASSIC"
            assert list(ours.variables) == list(ref.variables)
            assert len(ours.variables) == 65
            assert all(ours[v].dtype == ref[v].dtype for v in ours.variables)
            assert ours.dimensions["N_MISSIONS"].isunlimited()
            assert len(ours.dimensions["N_MISSIONS"]) == 1
            assert sorted(ours.ncattrs()) == sorted(ref.ncattrs())
            # Clamped one-row blocks vs the registry-populated references.
            for dim in ("N_CONFIG_PARAM", "N_LAUNCH_CONFIG_PARAM", "N_SENSOR", "N_PARAM"):
                assert len(ours.dimensions[dim]) == 1
                assert len(ours.dimensions[dim]) < len(ref.dimensions[dim])
        finally:
            ours.close()
            ref.close()


@pytest.mark.parametrize("wmo", [6990711, 7902408])
def test_derived_values_equal_gdac(meta_files: dict[int, Path], wmo: int) -> None:
    if not (REF_ROOT / f"{wmo}_meta.nc").exists():
        pytest.skip("GDAC meta reference not present")
    ours = netCDF4.Dataset(meta_files[wmo])
    ref = netCDF4.Dataset(REF_ROOT / f"{wmo}_meta.nc")
    try:
        for var in (
            "PLATFORM_NUMBER",
            "TRANS_SYSTEM",
            "POSITIONING_SYSTEM",
            "PLATFORM_FAMILY",
            "PLATFORM_TYPE",
            "PLATFORM_MAKER",
            "LAUNCH_DATE",
            "LAUNCH_QC",
            "DATA_TYPE",
            "FORMAT_VERSION",
            "HANDBOOK_VERSION",
            "END_MISSION_DATE",
            "END_MISSION_STATUS",
            "STARTUP_DATE",
            "STARTUP_DATE_QC",
            "ANOMALY",
            "CONFIG_MISSION_NUMBER",
        ):
            assert _text(ours, var) == _text(ref, var), var
    finally:
        ours.close()
        ref.close()


@pytest.mark.parametrize("wmo", [6990711, 7902408])
def test_registry_gaps_remain_fills(meta_files: dict[int, Path], wmo: int) -> None:
    ours = netCDF4.Dataset(meta_files[wmo])
    ours.set_auto_mask(False)
    try:
        assert float(ours["LAUNCH_LATITUDE"][...]) == 99999.0
        assert float(ours["LAUNCH_LONGITUDE"][...]) == 99999.0
        # START_DATE is telemetry-derived (UM 3.44.0 §2.4.5 "first
        # descent" == cookbook DST/MC 100), so it is published even
        # without a registry json; its QC tracks it per ref table 2.
        assert _text(ours, "START_DATE") != ""
        assert _text(ours, "START_DATE_QC") == "1"
        assert _text(ours, "PTT") == ""  # absent from Iridium mail headers
        assert _text(ours, "FLOAT_SERIAL_NO") == ""
        assert _text(ours, "FIRMWARE_VERSION") == ""
        assert _text(ours, "WMO_INST_TYPE") == ""
        assert _text(ours, "DATA_CENTRE") == ""
        assert _text(ours, "DEPLOYMENT_PLATFORM") == ""
        assert np.all(np.asarray(ours["CONFIG_PARAMETER_VALUE"][:]) == 99999.0)
        assert np.all(np.asarray(ours["LAUNCH_CONFIG_PARAMETER_VALUE"][:]) == 99999.0)
        assert ours.institution == "CORIOLIS"  # 4A/4B/5 product-family default
    finally:
        ours.close()


def test_decid_derived_platform_type(meta_files: dict[int, Path]) -> None:
    # 7902408 resolves decId 232 from its Tech#1 firmware checksum.
    ours = netCDF4.Dataset(meta_files[7902408])
    try:
        assert _text(ours, "PLATFORM_TYPE") == "ARVOR"
    finally:
        ours.close()
