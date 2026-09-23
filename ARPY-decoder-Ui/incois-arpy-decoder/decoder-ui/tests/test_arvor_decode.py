"""Regression tests for ARVOR / decoder-232/222 float decoding.

Verifies:
1. ARVOR path discovery: candidate raw directories and _ARVOR_EML_RE filtering.
2. Preset inventory: all 4 ARVOR floats have valid presets, decodable file counts, and metadata.
3. Fallback resolution: in the absence of unified All-float-inputs, path resolver correctly identifies
   authoritative harness_bundle and ARVOR-I-raw-files folders.
4. End-to-end decode execution: real ARVOR float (WMO 6990711) decodes end-to-end into valid
   meta, tech, Rtraj, and mono-profile NetCDFs with 0 errors.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import netCDF4 as nc
import pytest

TEST_DIR = Path(__file__).resolve().parent
SERVICE_DIR = TEST_DIR.parent / "service"
PROJECT_ROOT = TEST_DIR.parent.parent
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from argo_decoder.cli.main import _apply_path_overrides
from argo_decoder.config import load_config
from argo_decoder.config.models import TransmissionType
from argo_decoder.io.rsync import discover
from models import NodeStatus
import path_resolver
from runner_instrumentation import execute_decoder_with_observability


EXPECTED_ARVOR_WMOS = {1902844, 2904082, 6990711, 7902408}
EXPECTED_PTTS = {
    1902844: "123230",
    2904082: "124250",
    6990711: "664170",
    7902408: "339490",
}
EXPECTED_COUNTS = {
    1902844: 87,
    2904082: 93,
    6990711: 35,
    7902408: 64,
}


def test_arvor_path_discovery_and_filtering():
    """Verify that decodable ARVOR telemetry is discovered and unparseable formats are rejected."""
    raw_dirs = path_resolver.find_raw_input_directories()
    assert len(raw_dirs) > 0, "At least one raw input directory must be discovered"

    # All 4 ARVOR floats must have positive file counts in candidate directories
    for wmo in EXPECTED_ARVOR_WMOS:
        ptt = EXPECTED_PTTS[wmo]
        found_any = False
        for rdir in raw_dirs:
            cnt = path_resolver.count_raw_files_for_float(rdir, ptt, "", wmo)
            if cnt == EXPECTED_COUNTS[wmo]:
                found_any = True
                break
        assert found_any, f"Expected {EXPECTED_COUNTS[wmo]} decodable files for WMO {wmo} in raw dirs"

    # Verify that a directory with non-matching .eml files returns 0
    with tempfile.TemporaryDirectory() as tmp_dir:
        fake_float_dir = Path(tmp_dir) / "1902844"
        fake_float_dir.mkdir()
        # Create unredacted operator file (not matching redacted_imei_<prefix>_<momsn>.eml)
        (fake_float_dir / "300534067123230_000046.eml").write_text("From: operator@iridium.com\n")
        cnt = path_resolver.count_raw_files_for_float(Path(tmp_dir), "123230", "", 1902844)
        assert cnt == 0, "Unredacted operator .eml files must NOT be counted as decodable ARVOR files"


def test_arvor_presets_inventory():
    """Verify that all 4 ARVOR floats in fleet metadata have valid presets."""
    presets = path_resolver.build_dynamic_float_presets()
    arvor_presets = [p for p in presets if p.get("platform_type") == "ARVOR"]
    assert len(arvor_presets) == 4, f"Expected 4 ARVOR presets, found {len(arvor_presets)}"

    found_wmos = {p["wmo"] for p in arvor_presets}
    assert found_wmos == EXPECTED_ARVOR_WMOS, f"Mismatch in ARVOR WMOs: {found_wmos ^ EXPECTED_ARVOR_WMOS}"

    for p in arvor_presets:
        wmo = p["wmo"]
        assert p.get("transmission_type") == "IRIDIUM_SBD"
        assert p.get("decoder_id") in (222, 223, 225, 232)
        assert p.get("input_file_count", 0) == EXPECTED_COUNTS[wmo]
        input_path = Path(p["input_path"])
        assert input_path.is_dir(), f"Input path {input_path} for WMO {wmo} must exist"

        # Verify discovery with frozen decoder core
        cfg = load_config(None)
        cfg.transmission_type = TransmissionType.IRIDIUM_SBD
        cfg.paths.rsync_data_dir = input_path
        idx = discover(cfg)
        assert len(idx.files_for(str(wmo))) == EXPECTED_COUNTS[wmo] or len(idx.files_for(EXPECTED_PTTS[wmo])) == EXPECTED_COUNTS[wmo]


def test_arvor_fallback_resolution():
    """Verify fallback when All-float-inputs is not available."""
    d1 = PROJECT_ROOT / "arvor_raw" / "harness_bundle" / "more-raw-files-and-manuals"
    d2 = PROJECT_ROOT / "arvor_raw" / "ARVOR-I-raw-files" / "20260819"

    assert d1.is_dir(), f"Harness bundle directory {d1} must exist"
    assert d2.is_dir(), f"ARVOR-I raw files directory {d2} must exist"

    # WMOs 1902844 and 2904082 exist under d1
    assert path_resolver.count_raw_files_for_float(d1, "123230", "", 1902844) == 87
    assert path_resolver.count_raw_files_for_float(d1, "124250", "", 2904082) == 93

    # WMOs 6990711 and 7902408 exist under d2
    assert path_resolver.count_raw_files_for_float(d2, "664170", "", 6990711) == 35
    assert path_resolver.count_raw_files_for_float(d2, "339490", "", 7902408) == 64


def test_arvor_decode_end_to_end(tmp_path):
    """Execute real end-to-end decode for ARVOR float 6990711 and verify NetCDF artifacts."""
    wmo = 6990711
    presets = path_resolver.build_dynamic_float_presets()
    preset = next(p for p in presets if p["wmo"] == wmo)

    out_root = tmp_path / "decode_output" / str(wmo)
    out_root.mkdir(parents=True, exist_ok=True)

    cfg = load_config(None)
    cfg.rtqc.apply_rtqc = True
    cfg.transmission_type = TransmissionType.IRIDIUM_SBD
    meta_backend = preset.get("metadata_backend", "csv4")
    cfg.metadata.backend = meta_backend
    reg_path = preset.get("registry_path")
    if reg_path:
        cfg.metadata.registry_path = Path(reg_path).resolve()

    cfg = _apply_path_overrides(
        cfg,
        input_root=Path(preset["input_path"]),
        output_root=out_root,
        config_dir=None,
        meta_info_dir=Path(preset["info_dir"]) if preset.get("info_dir") else None,
        meta_dir=Path(preset["meta_dir"]) if preset.get("meta_dir") else None,
        ref_dir=None,
        runtime_dir=None,
        temporary_dir=None,
    )
    if not cfg.paths.rsync_data_dir.exists():
        cfg.paths.rsync_data_dir = Path(preset["input_path"])
        cfg.paths.rsync_log_dir = Path(preset["input_path"])

    for d in (
        cfg.paths.xml_dir,
        cfg.paths.nc_dir,
        cfg.paths.log_dir,
        cfg.paths.csv_dir,
        cfg.paths.iridium_decoded_dir,
        cfg.paths.temporary_dir,
    ):
        d.mkdir(parents=True, exist_ok=True)

    run_id = f"test-regression-arvor-{wmo}"
    summary = execute_decoder_with_observability(wmo=wmo, cfg=cfg, run_id=run_id)

    assert summary.status == NodeStatus.COMPLETED, f"Run failed with errors: {summary.errors}"
    assert summary.total_cycles == 7
    assert summary.profile_count == 7
    assert len(summary.errors) == 0
    assert len(summary.output_files) == 11

    # Verify key NetCDF product categories were created on disk
    created_filenames = {out.filename for out in summary.output_files}
    assert f"{wmo}_meta.nc" in created_filenames
    assert f"{wmo}_tech.nc" in created_filenames
    assert f"{wmo}_Rtraj.nc" in created_filenames
    assert all(f"R{wmo}_{i:03d}.nc" in created_filenames for i in range(1, 8))

    for out in summary.output_files:
        p = Path(out.filepath)
        assert p.is_file(), f"Output file {p} must exist"
        assert p.stat().st_size > 0, f"Output file {p} must not be empty"
        assert out.checksum_sha256, f"Output file {out.filename} must have SHA256 checksum"

        # Validate that NetCDF files are well-formed
        if p.suffix == ".nc":
            with nc.Dataset(str(p), "r") as ds:
                assert ds.file_format is not None
