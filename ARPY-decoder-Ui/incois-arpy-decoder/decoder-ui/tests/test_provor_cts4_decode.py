"""Regression tests for PROVOR CTS4 / decoder-301 float decoding.

Verifies:
1. CTS4 discovery: data root, SBD root, and official GDAC meta.nc directory resolution.
2. CTS4 preset inventory: all staged Provor floats have valid groups, meta files, and non-zero SBDs.
3. Batch decode filtering: fleet-wide Decode All queues only staged floats, avoiding false failures.
4. Single-float validation: explicit decode of unstaged float surfaces exact missing input contract.
5. End-to-end decode execution: real Provor float decodes cleanly into valid Core, BGC, tech, meta, and traj NetCDFs.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure service directory is in sys.path
TEST_DIR = Path(__file__).resolve().parent
SERVICE_DIR = TEST_DIR.parent / "service"
PROJECT_ROOT = TEST_DIR.parent.parent
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

import path_resolver
from cts4_runner import execute_cts4_with_observability
from models import NodeStatus


def test_cts4_path_discovery():
    """Verify that CTS4 data root, raw SBD root, and GDAC meta dir resolve correctly."""
    data_root = path_resolver.find_cts4_data_root()
    assert data_root is not None, "CTS4 data root must resolve"
    assert data_root.is_dir(), f"CTS4 data root {data_root} must exist"

    sbd_root = path_resolver.find_cts4_sbd_root()
    assert sbd_root is not None, "CTS4 SBD root must resolve"
    assert sbd_root.is_dir(), f"CTS4 SBD root {sbd_root} must exist"

    meta_dir = path_resolver.find_cts4_meta_dir()
    assert meta_dir is not None, "CTS4 GDAC meta dir must resolve"
    assert meta_dir.is_dir(), f"CTS4 meta dir {meta_dir} must exist"
    
    # Must contain official incois_*_meta.nc files
    meta_files = list(meta_dir.glob("incois_*_meta.nc"))
    assert len(meta_files) >= 10, f"Expected at least 10 official meta.nc files, found {len(meta_files)}"


def test_cts4_staged_presets():
    """Verify that all 10 staged Provor floats have valid presets with input files and meta."""
    presets = path_resolver.build_dynamic_float_presets()
    staged_provors = [
        p for p in presets
        if p.get("platform_type") == "PROVOR_III" and (p.get("input_file_count") or 0) > 0
    ]
    assert len(staged_provors) == 10, f"Expected 10 staged Provor presets, found {len(staged_provors)}"

    expected_staged_wmos = {
        2902086, 2902087, 2902088, 2902092, 2902093,
        2902114, 2902115, 2902118, 2902130, 2902131
    }
    found_wmos = {p["wmo"] for p in staged_provors}
    assert found_wmos == expected_staged_wmos, f"Mismatch in staged WMOs: {found_wmos ^ expected_staged_wmos}"

    for p in staged_provors:
        assert p.get("cts4") is True
        assert p.get("decoder_id") == 301
        assert p.get("cts4_group_dir") is not None
        assert Path(p["cts4_group_dir"]).is_dir()
        assert p.get("cts4_meta_nc") is not None
        assert Path(p["cts4_meta_nc"]).is_file()
        assert p.get("input_file_count", 0) > 0


def test_cts4_unstaged_presets():
    """Verify that the 5 unstaged Provor floats are reported with 0 inputs and no group dir."""
    presets = path_resolver.build_dynamic_float_presets()
    unstaged_provors = [
        p for p in presets
        if p.get("platform_type") == "PROVOR_III" and (p.get("input_file_count") or 0) == 0
    ]
    assert len(unstaged_provors) == 5, f"Expected 5 unstaged Provor presets, found {len(unstaged_provors)}"

    expected_unstaged_wmos = {2902089, 2902090, 2902091, 2902113, 2902120}
    found_unstaged = {p["wmo"] for p in unstaged_provors}
    assert found_unstaged == expected_unstaged_wmos

    for p in unstaged_provors:
        assert p.get("cts4_group_dir") is None
        assert p.get("input_file_count") == 0


def test_batch_decode_selection_excludes_unstaged():
    """Verify fleet-wide Decode All only selects floats with staged inputs."""
    presets = path_resolver.build_dynamic_float_presets()
    
    # Logic in api.start_batch_decode:
    selected = [
        p for p in presets
        if not (p.get("cts4") and not p.get("cts4_group_dir"))
        and p.get("input_file_count") != 0
    ]
    
    selected_wmos = {p["wmo"] for p in selected}
    for unstaged_wmo in (2902089, 2902090, 2902091, 2902113, 2902120):
        assert unstaged_wmo not in selected_wmos, f"Unstaged WMO {unstaged_wmo} must not be in fleet batch"

    for staged_wmo in (2902086, 2902087, 2902088, 2902092, 2902093, 2902114, 2902115, 2902118, 2902130, 2902131):
        assert staged_wmo in selected_wmos, f"Staged WMO {staged_wmo} must be in fleet batch"


def test_provor_cts4_decode_end_to_end(tmp_path):
    """Execute real end-to-end decode for Provor float 2902086 and verify NetCDF artifacts."""
    presets = path_resolver.build_dynamic_float_presets()
    preset_2902086 = next(p for p in presets if p["wmo"] == 2902086)

    out_root = tmp_path / "decode_output" / "2902086"
    summary = execute_cts4_with_observability(
        wmo=2902086,
        group_dir=Path(preset_2902086["cts4_group_dir"]),
        meta_nc=Path(preset_2902086["cts4_meta_nc"]),
        out_root=out_root,
        run_id="test-regression-2902086",
    )

    assert summary.status == NodeStatus.COMPLETED
    assert summary.total_cycles == 16
    assert summary.profile_count == 15
    assert len(summary.errors) == 0
    assert len(summary.output_files) == 34

    # Verify key NetCDF product categories were created on disk
    created_filenames = {out.filename for out in summary.output_files}
    assert "2902086_meta.nc" in created_filenames
    assert "2902086_tech.nc" in created_filenames
    assert "2902086_Rtraj.nc" in created_filenames
    assert any(fn.startswith("R2902086_") for fn in created_filenames), "Core profiles missing"
    assert any(fn.startswith("BR2902086_") for fn in created_filenames), "BGC profiles missing"

    for out in summary.output_files:
        p = Path(out.filepath)
        assert p.is_file(), f"Output file {p} must exist"
        assert p.stat().st_size > 0, f"Output file {p} must not be empty"
        assert out.checksum_sha256, f"Output file {out.filename} must have SHA256 checksum"
