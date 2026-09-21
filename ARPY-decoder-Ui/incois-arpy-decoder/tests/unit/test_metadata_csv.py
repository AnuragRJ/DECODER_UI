"""Tests for the CSV metadata loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from argo_decoder.config import get_decoder_table
from argo_decoder.metadata import builder
from argo_decoder.metadata.csv_loader import CsvLoader, load_registry_csv
from argo_decoder.metadata.validators import validate_registry

DEMO_CSV = Path(__file__).resolve().parents[2] / "config" / "registry.csv"


def test_demo_csv_present():
    assert DEMO_CSV.exists(), "config/registry.csv must be bootstrapped"


def test_load_demo_registry():
    rows = load_registry_csv(DEMO_CSV)
    wmos = {r.wmo for r in rows}
    # Iridium demo floats (Phase 2) + 4 APEX ARGOS floats (Phase 4).
    # ARVOR-I floats are intentionally ABSENT since 2026-09-04: the four
    # CSVs are their only metadata/routing source (registry is not an
    # authority for them).
    assert wmos == {6902892, 6903014, 2901339, 2902222, 2902223, 2902201}


def test_registry_validates_clean():
    rows = load_registry_csv(DEMO_CSV)
    report = validate_registry(rows)
    assert report.ok, [i.message for i in report.issues if i.level == "error"]


def test_registry_validates_against_decoder_table():
    rows = load_registry_csv(DEMO_CSV)
    report = validate_registry(rows, decoder_table=get_decoder_table())
    assert report.ok, [i.message for i in report.issues if i.level == "error"]
    assert report.n_warnings == 0, [i.message for i in report.issues]


def test_lookup_by_wmo():
    loader = CsvLoader(DEMO_CSV)
    r = loader.get_float(6902892)
    assert r is not None
    assert r.wmo == 6902892
    assert r.platform_type == "ARVOR_D"
    assert r.decoder_id == 221
    assert r.decoder_version == "5.67"
    assert r.cycle_length_hours == 120
    assert r.drift_sampling_period_hours == 3.0
    # Sensors parsed.
    sensor_names = [s.sensor for s in r.sensors]
    assert "CTD_PRES" in sensor_names
    assert "OPTODE_DOXY" in sensor_names


def test_build_meta_includes_float_transmission_type():
    loader = CsvLoader(DEMO_CSV)
    row = loader.get_float(2902222)
    assert row is not None
    meta = builder.build_meta(row)
    assert (meta.model_extra or {}).get("FLOAT_TRANSMISSION_TYPE") == "1"


def test_phase4_argos_rows_have_real_decoder_metadata():
    loader = CsvLoader(DEMO_CSV)
    row_1005 = loader.get_float(2901339)
    assert row_1005 is not None
    assert row_1005.platform_maker == "WRC"
    assert row_1005.platform_type == "APEX"
    assert row_1005.transmission_type == 1
    assert row_1005.decoder_id == 1005
    assert row_1005.decoder_version == "61810"
    assert row_1005.firmware_version == "61810"
    assert row_1005.frame_length == 31

    for wmo, version in ((2902201, "091515"), (2902222, "091615"), (2902223, "091615")):
        row = loader.get_float(wmo)
        assert row is not None
        assert row.decoder_id == 1010
        assert row.decoder_version == version
        assert row.firmware_version == version
        assert row.frame_length == 31


def test_load_info_from_csv_round_trips_through_json(tmp_path: Path):
    """Info generated from CSV must serialize back to a legacy-compatible
    JSON file that JsonLoader can read.
    """
    from argo_decoder.metadata.json_loader import JsonLoader

    csv_loader = CsvLoader(DEMO_CSV)
    info_dir = tmp_path / "info"
    meta_dir = tmp_path / "meta"
    info_dir.mkdir()
    meta_dir.mkdir()
    for wmo in (6902892, 6903014):
        row = csv_loader.get_float(wmo)
        assert row is not None
        builder.materialize(row, info_dir, meta_dir=meta_dir)
    reloaded = JsonLoader(info_dir, meta_dir)
    for wmo in (6902892, 6903014):
        info = reloaded.load_info(wmo)
        meta = reloaded.load_meta(wmo)
        assert info.wmo == wmo
        assert info.decoder_id > 0
        assert info.frame_length == 31
        assert meta.platform_number == str(wmo)
        assert meta.platform_maker == "NKE"


def test_materialize_writes_both_files(tmp_path: Path):
    loader = CsvLoader(DEMO_CSV)
    row = loader.get_float(6902892)
    assert row is not None
    info_path, meta_path = builder.materialize(row, tmp_path / "info", meta_dir=tmp_path / "meta")
    assert info_path.exists()
    assert meta_path.exists()
    # Reload through JsonLoader to confirm round-trip.
    from argo_decoder.metadata.json_loader import JsonLoader

    jl = JsonLoader(tmp_path / "info", tmp_path / "meta")
    info = jl.load_info(6902892)
    meta = jl.load_meta(6902892)
    assert info.wmo == 6902892
    assert meta.platform_number == "6902892"
    assert meta.platform_type == "ARVOR_D"


def test_duplicate_wmo_rejected_in_strict_mode(tmp_path: Path):
    csv_path = tmp_path / "dup.csv"
    csv_path.write_text(
        "wmo,ptt,platform_type,decoder_id,decoder_version,frame_length,"
        "cycle_length_hours,drift_sampling_period_hours,launch_date_utc,"
        "launch_lon,launch_lat,reference_day,platform_maker,platform_family,"
        "transmission_type,sensors\n"
        "6900001,123456789012345,PROVOR,100,1.0,31,10,1.0,"
        '2020-01-01T00:00:00Z,0.0,0.0,2020-01-01,NKE,FLOAT,3,"[]"\n'
        "6900001,123456789012345,PROVOR,100,1.0,31,10,1.0,"
        '2020-01-01T00:00:00Z,0.0,0.0,2020-01-01,NKE,FLOAT,3,"[]"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Duplicate WMO"):
        list(CsvLoader(csv_path, strict=True).iter_floats())  # triggers load


def test_missing_required_field_is_error(tmp_path: Path):
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text(
        "wmo,ptt,platform_type,decoder_version,frame_length,"
        "cycle_length_hours,drift_sampling_period_hours,launch_date_utc,"
        "launch_lon,launch_lat,reference_day\n"
        "6900002,12345,PROVOR,1.0,31,10,1.0,"
        "2020-01-01T00:00:00Z,0.0,0.0,2020-01-01\n",
        encoding="utf-8",
    )
    rows = load_registry_csv(csv_path, strict=False)
    report = validate_registry(rows)
    assert not report.ok
    codes = {i.code for i in report.issues if i.level == "error"}
    assert "DECODER_ID" in codes
