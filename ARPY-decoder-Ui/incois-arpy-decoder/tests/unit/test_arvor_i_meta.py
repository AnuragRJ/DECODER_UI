"""Unit tests: ARVOR-I meta adapter (``arvor_i_meta``).

Covers the telemetry-derived FloatMeta mapping, the no-fabrication blanks
when no Coriolis registry json is supplied, registry-json precedence when
one is, and the hand-off to the generic metadata builder.  End-to-end
file parity against the GDAC references is pinned in
``tests/integration/test_arvor_i_meta_nc.py``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from argo_decoder.nc.admt import institution_for_data_centre
from argo_decoder.platforms.provor_ir_sbd.arvor_i_meta import (
    build_arvor_float_meta,
    build_arvor_meta_nc,
)

LAUNCH = datetime(2026, 3, 25, 17, 44, tzinfo=UTC)


def test_telemetry_meta_fields_without_registry() -> None:
    meta = build_arvor_float_meta(wmo=7902408, launch_date=LAUNCH)
    assert meta.platform_number == "7902408"
    assert meta.trans_system == [{"TRANS_SYSTEM_1": "IRIDIUM"}]
    assert meta.positioning_system == [{"POSITIONING_SYSTEM_1": "GPS"}]
    assert meta.platform_family == "FLOAT"
    assert meta.platform_maker == "NKE"
    assert meta.platform_type == ""  # no decodable stream -> not inferred
    assert meta.launch_date == "2026-03-25T17:44:00"
    assert meta.launch_qc == "1"


def test_no_registry_blanks_are_proper_fills() -> None:
    meta = build_arvor_float_meta(wmo=6990711, launch_date=LAUNCH)
    # Never fabricate registry values (library defaults explicitly blanked).
    assert meta.launch_latitude == 99999.0
    assert meta.launch_longitude == 99999.0
    # START_DATE is no longer registry-sourced: UM 3.44.0 §2.4.5 defines
    # it as the first descent, which this family transmits, so it is
    # derived from telemetry when available. With no decode result there
    # is nothing to derive, hence fill + '9' (ref table 2 "Missing value")
    # -- never blank, which is not a table-2 member.
    assert meta.start_date == "" and meta.start_date_qc == "9"
    assert meta.data_centre == ""  # model default 'IF' suppressed
    assert meta.float_owner == ""  # model default 'IFREMER' suppressed
    assert meta.ptt == ""


def test_dataset_without_registry(tmp_path: Path) -> None:
    ds = build_arvor_meta_nc(wmo=7902408, launch_date=LAUNCH)
    assert len(ds.data_vars) == 65
    names = list(ds.data_vars)
    assert names[0] == "DATA_TYPE" and names[-1] == "PREDEPLOYMENT_CALIB_COMMENT"
    assert float(ds["LAUNCH_LATITUDE"]) == 99999.0
    assert bytes(ds["PLATFORM_NUMBER"].values.reshape(-1)).decode().rstrip() == "7902408"
    assert bytes(ds["TRANS_SYSTEM"].values.reshape(-1)).decode().rstrip() == "IRIDIUM"
    assert bytes(ds["POSITIONING_SYSTEM"].values.reshape(-1)).decode().rstrip() == "GPS"
    assert bytes(ds["LAUNCH_DATE"].values.reshape(-1)).decode().rstrip() == "20260325174400"
    assert bytes(ds["DATA_CENTRE"].values.reshape(-1)).decode().rstrip() == ""
    # Clamped one-row blocks carry fills, not invented values.
    assert np.all(np.asarray(ds["CONFIG_PARAMETER_VALUE"].values) == 99999.0)
    assert np.all(np.asarray(ds["LAUNCH_CONFIG_PARAMETER_VALUE"].values) == 99999.0)
    assert ds.sizes["N_CONFIG_PARAM"] == 1
    assert ds.sizes["N_SENSOR"] == 1 and ds.sizes["N_PARAM"] == 1
    # Generic builder default for the mission counter (1-based convention).
    assert np.asarray(ds["CONFIG_MISSION_NUMBER"].values).tolist() == [1]
    # 4A/4B/5 product-family default when no registry DATA_CENTRE exists.
    assert ds.attrs["institution"] == "CORIOLIS"


def test_registry_json_supplies_registry_fields(tmp_path: Path) -> None:
    registry = {
        "PLATFORM_NUMBER": "0000000",
        "PTT": "123456",
        "FLOAT_SERIAL_NO": "SYNTH-1",
        "DATA_CENTRE": "IF",
        "FIRMWARE_VERSION": "SYNTHFW",
        "LAUNCH_DATE": "25/03/2026 17:44:00",
        "LAUNCH_LATITUDE": 12.5,
        "LAUNCH_LONGITUDE": -45.25,
        "START_DATE": "25/03/2026 12:08:16",
        "CONFIG_MISSION_NUMBER": [{"CONFIG_MISSION_NUMBER_1": "0"}],
    }
    path = tmp_path / "7902408_meta.json"
    path.write_text(json.dumps(registry), encoding="utf-8")

    meta = build_arvor_float_meta(wmo=7902408, launch_date=LAUNCH, meta_json_path=path)
    assert meta.ptt == "123456"
    assert meta.float_serial_no == "SYNTH-1"
    assert meta.data_centre == "IF"
    assert meta.launch_latitude == 12.5 and meta.launch_longitude == -45.25
    # Telemetry-derived identity still applies; registry wins where it speaks.
    assert meta.platform_number == "7902408"
    assert meta.launch_date == "25/03/2026 17:44:00"

    ds = build_arvor_meta_nc(
        wmo=7902408, launch_date=LAUNCH, meta_json_path=path, date_creation="20260401093709"
    )
    assert bytes(ds["PTT"].values.reshape(-1)).decode().rstrip() == "123456"
    assert float(ds["LAUNCH_LATITUDE"]) == 12.5
    assert bytes(ds["START_DATE"].values.reshape(-1)).decode().rstrip() == "20260325120816"
    assert bytes(ds["DATA_CENTRE"].values.reshape(-1)).decode().rstrip() == "IF"
    assert ds.attrs["institution"] == institution_for_data_centre("IF")
    assert bytes(ds["DATE_CREATION"].values.reshape(-1)).decode().rstrip() == "20260401093709"
    # Registry 0-based mission counter normalised to the 1-based convention.
    assert np.asarray(ds["CONFIG_MISSION_NUMBER"].values).tolist() == [1]


def test_registry_gap_keeps_telemetry_defaults(tmp_path: Path) -> None:
    """A sparse registry json must not unset the telemetry-derived fields."""
    path = tmp_path / "6990711_meta.json"
    path.write_text(json.dumps({"PTT": "654321"}), encoding="utf-8")
    meta = build_arvor_float_meta(wmo=6990711, launch_date=LAUNCH, meta_json_path=path)
    assert meta.ptt == "654321"
    assert meta.platform_number == "6990711"
    assert meta.trans_system == [{"TRANS_SYSTEM_1": "IRIDIUM"}]
    # Registry present but silent on launch position -> not filled, not 0.0.
    assert meta.launch_latitude == 0.0  # model default retained (registry owns it)
    ds = build_arvor_meta_nc(wmo=6990711, launch_date=LAUNCH, meta_json_path=path)
    assert ds.attrs["institution"] == institution_for_data_centre("IF")


def test_launch_date_formats_from_naive_and_aware() -> None:
    naive = datetime(2025, 3, 2, 5, 16)
    meta = build_arvor_float_meta(wmo=6990711, launch_date=naive)
    ds = build_arvor_meta_nc(wmo=6990711, launch_date=naive)
    stamp = bytes(ds["LAUNCH_DATE"].values.reshape(-1)).decode().rstrip()
    assert stamp == "20250302051600"
    assert meta.launch_date == "2025-03-02T05:16:00"


@pytest.mark.parametrize("wmo", [6990711, 7902408])
def test_platform_identity_is_never_wmo_specific(wmo: int) -> None:
    """Family constants come from the decId family, not the WMO."""
    meta = build_arvor_float_meta(wmo=wmo, launch_date=LAUNCH)
    assert meta.platform_maker == "NKE"
    assert meta.platform_family == "FLOAT"
