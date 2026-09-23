from __future__ import annotations

import sys
import tempfile
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parent.parent / "service"
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

import pytest

from format_checker import (
    CHECKER_VERSION,
    FILE_ACCEPTED,
    FILE_REJECTED,
    STATUS_ACCEPTED,
    STATUS_REJECTED,
    _jar_path,
    _spec_dir,
    _parse_filecheck_xml,
    checker_available,
    classify_file,
    extract_cycle,
    run_check_local,
    not_checked_result,
    CheckResult,
)
from format_checker_cache import FormatCheckerCache


def test_checker_jar_available():
    """Verify that the official ArgoFormatChecker JAR is present locally."""
    assert checker_available() is True
    jar = _jar_path()
    assert jar.is_file()
    assert jar.stat().st_size > 10_000_000  # Official fat JAR is ~27MB


def test_spec_dir_available():
    """Verify that the official file_checker_spec directory is resolved."""
    spec = _spec_dir()
    if spec:
        assert spec.is_dir()
        assert (spec / "VersionInfo.properties").is_file() or (spec / "argo-metadata-spec-v3.1.cdl").is_file()


def test_classify_and_extract_cycle():
    """Verify official Argo filename patterns."""
    assert classify_file("1902844_meta.nc") == "meta"
    assert classify_file("1902844_tech.nc") == "tech"
    assert classify_file("1902844_Rtraj.nc") == "traj"
    assert classify_file("1902844_prof.nc") == "profile"
    assert classify_file("R1902844_001.nc") == "mono_profile"
    assert extract_cycle("R1902844_001.nc") == 1
    assert extract_cycle("R1902844_024.nc") == 24
    assert classify_file("random_file.txt") is None


def test_parse_filecheck_xml_sample():
    """Test XML parsing of official Argo format checker .filecheck format."""
    xml_content = """<FileCheckResults filechecker_version="3.0.6" spec_version="-r1259">
  <file>C:\\Temp\\argo_test\\1902844\\1902844_meta.nc</file>
  <status>FILE-ACCEPTED</status>
  <phase>FILE-NAME-CHECK</phase>
  <metadata>
    <dac>incois</dac>
    <DATA_TYPE>Argo meta-data</DATA_TYPE>
    <FORMAT_VERSION>3.1 </FORMAT_VERSION>
    <PLATFORM_NUMBER>1902844 </PLATFORM_NUMBER>
  </metadata>
  <errors number="0"/>
  <warnings number="1">
    <warning>PI_NAME : 'M Ravichandran' Status: Invalid (not in NVS R40 table)</warning>
  </warnings>
</FileCheckResults>"""

    with tempfile.NamedTemporaryFile(suffix=".filecheck", mode="w", delete=False, encoding="utf-8") as tmp:
        tmp.write(xml_content)
        tmp_path = Path(tmp.name)

    try:
        results = _parse_filecheck_xml(tmp_path, 1902844)
        assert len(results) == 1
        r = results[0]
        assert r.filename == "1902844_meta.nc"
        assert r.category == "meta"
        assert r.result == FILE_ACCEPTED
        assert r.phase == "FILE-NAME-CHECK"
        assert r.errors_number == 0
        assert r.warnings_number == 1
        assert "PI_NAME" in r.warnings_messages[0]
    finally:
        tmp_path.unlink(missing_ok=True)


def test_parse_filecheck_xml_rejected():
    """Test parsing of a rejected file with errors."""
    xml_content = """<FileCheckResults filechecker_version="3.0.6" spec_version="-r1259">
  <file>C:\\Temp\\2902201\\2902201_prof.nc</file>
  <status>FILE-REJECTED</status>
  <phase>FILE-NAME-CHECK</phase>
  <errors number="2">
    <error>D-mode: HISTORY_* not set</error>
    <error>Inconsistent file name</error>
  </errors>
  <warnings number="1">
    <warning>VERTICAL_SAMPLING_SCHEME warning</warning>
  </warnings>
</FileCheckResults>"""

    with tempfile.NamedTemporaryFile(suffix=".filecheck", mode="w", delete=False, encoding="utf-8") as tmp:
        tmp.write(xml_content)
        tmp_path = Path(tmp.name)

    try:
        results = _parse_filecheck_xml(tmp_path, 2902201)
        assert len(results) == 1
        r = results[0]
        assert r.filename == "2902201_prof.nc"
        assert r.category == "profile"
        assert r.result == FILE_REJECTED
        assert r.errors_number == 2
        assert len(r.errors_messages) == 2
        assert r.errors_messages[0] == "D-mode: HISTORY_* not set"
    finally:
        tmp_path.unlink(missing_ok=True)


def test_run_check_local_real_float():
    """Test executing the official checker on float 2901304 decoded output."""
    import path_resolver
    out_root = path_resolver.get_default_output_root(2901304)
    assert out_root.exists()

    run_dirs = sorted([d for d in out_root.iterdir() if d.is_dir() and d.name.startswith("run_")], reverse=True)
    assert len(run_dirs) > 0
    nc_files = [str(f) for f in run_dirs[0].rglob("*.nc")]
    assert len(nc_files) >= 3

    res = run_check_local(2901304, nc_files)
    assert res.wmo == 2901304
    assert res.status in (STATUS_ACCEPTED, STATUS_REJECTED)
    assert res.total_files == len(nc_files)
    assert res.accepted_files > 0
    assert len(res.files) == len(nc_files)
    # Most files (mono-profiles, tech, traj, meta) should be accepted
    accepted = [f for f in res.files if f["result"] == FILE_ACCEPTED]
    assert len(accepted) >= 20
