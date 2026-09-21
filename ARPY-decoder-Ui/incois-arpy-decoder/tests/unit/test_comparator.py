"""Unit tests for the NetCDF/XML comparator."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import xarray as xr

from argo_decoder.pipeline.comparator import (
    _canonical_nc_key,
    _find_xml_for_wmo,
    compare_outputs,
)


def _write_nc(path: Path, pres: np.ndarray, temp: np.ndarray, qc: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ds = xr.Dataset(
        {
            "PRES": (("N_LEVELS",), pres, {"_FillValue": 99999.0}),
            "TEMP": (("N_LEVELS",), temp, {"_FillValue": 99999.0}),
            "TEMP_QC": (("N_LEVELS",), qc.astype("S1")),
        },
        coords={"N_LEVELS": np.arange(len(pres))},
        attrs={"decoder": "test"},
    )
    ds.to_netcdf(path, engine="netcdf4")


def test_comparator_matches_identical_files(tmp_path: Path) -> None:
    e = tmp_path / "expected"
    a = tmp_path / "actual"
    _write_nc(
        e / "nc" / "69" / "69_001.nc",
        np.arange(5, dtype=float) * 1.0,
        np.arange(5, dtype=float) * 0.1,
        np.array([b"1"] * 5),
    )
    _write_nc(
        a / "nc" / "69" / "69_001.nc",
        np.arange(5, dtype=float) * 1.0,
        np.arange(5, dtype=float) * 0.1,
        np.array([b"1"] * 5),
    )
    report = compare_outputs(e, a, wmo=69)
    assert report.ok, [m.message for m in report.mismatches]


def test_comparator_flags_numeric_mismatch(tmp_path: Path) -> None:
    e = tmp_path / "expected"
    a = tmp_path / "actual"
    _write_nc(
        e / "nc" / "69" / "69_001.nc",
        np.arange(5, dtype=float),
        np.arange(5, dtype=float) * 0.1,
        np.array([b"1"] * 5),
    )
    _write_nc(
        a / "nc" / "69" / "69_001.nc",
        np.arange(5, dtype=float),
        np.arange(5, dtype=float) * 0.5,
        np.array([b"1"] * 5),
    )
    report = compare_outputs(e, a, wmo=69)
    assert not report.ok
    msgs = [m.variable for m in report.mismatches if m.severity == "error"]
    assert "TEMP" in msgs


def test_comparator_flags_qc_mismatch(tmp_path: Path) -> None:
    e = tmp_path / "expected"
    a = tmp_path / "actual"
    _write_nc(
        e / "nc" / "69" / "69_001.nc",
        np.arange(5, dtype=float),
        np.arange(5, dtype=float) * 0.1,
        np.array([b"1"] * 5),
    )
    qc = np.array([b"1"] * 5)
    qc[2] = b"4"
    _write_nc(
        a / "nc" / "69" / "69_001.nc",
        np.arange(5, dtype=float),
        np.arange(5, dtype=float) * 0.1,
        qc,
    )
    report = compare_outputs(e, a, wmo=69)
    assert not report.ok
    assert any(m.variable == "TEMP_QC" for m in report.mismatches if m.severity == "error")


def test_canonical_nc_key_strips_admt_prefixes(tmp_path: Path) -> None:
    """MATLAB prefixes R/BR/D must be stripped for cross-side matching."""
    assert _canonical_nc_key(tmp_path / "R6902892_086.nc") == "6902892_086.nc"
    assert _canonical_nc_key(tmp_path / "BR6902892_086.nc") == "6902892_086.nc"
    assert _canonical_nc_key(tmp_path / "D6902892_086.nc") == "6902892_086.nc"
    assert _canonical_nc_key(tmp_path / "6902892_086.nc") == "6902892_086.nc"


def test_comparator_matches_profiles_subdir_with_r_prefix(tmp_path: Path) -> None:
    """MATLAB writes mono-profiles into profiles/ with R-prefix; we match them."""
    e = tmp_path / "expected"
    a = tmp_path / "actual"
    _write_nc(
        e / "nc" / "69" / "profiles" / "R69_001.nc",
        np.arange(5, dtype=float),
        np.arange(5, dtype=float) * 0.1,
        np.array([b"1"] * 5),
    )
    _write_nc(
        a / "nc" / "69" / "69_001.nc",
        np.arange(5, dtype=float),
        np.arange(5, dtype=float) * 0.1,
        np.array([b"1"] * 5),
    )
    report = compare_outputs(e, a, wmo=69)
    assert report.ok, [m.message for m in report.mismatches]
    assert report.files_compared == 1


def test_find_xml_falls_back_to_timestamped_name(tmp_path: Path) -> None:
    """When oracle appends its own timestamp, the matcher must still find the XML."""
    xml_dir = tmp_path / "xml"
    xml_dir.mkdir()
    ts_xml = xml_dir / "co041404_oracle_69_20250101T120000Z.xml"
    ts_xml.write_text("<root><a>1</a></root>")
    found = _find_xml_for_wmo(xml_dir, 69)
    assert found is not None
    assert found.name == ts_xml.name


def test_find_xml_prefers_expected_name_first(tmp_path: Path) -> None:
    xml_dir = tmp_path / "xml"
    xml_dir.mkdir()
    (xml_dir / "co041404_oracle_69_other.xml").write_text("<x/>")
    exact = xml_dir / "co041404_oracle_69.xml"
    exact.write_text("<root/>")
    found = _find_xml_for_wmo(xml_dir, 69, expected_name="co041404_oracle_69.xml")
    assert found is not None
    assert found.name == exact.name


def test_comparator_xml_timestamped_match_end_to_end(tmp_path: Path) -> None:
    """End-to-end: timestamped oracle XML vs fixed Python XML name compare cleanly."""
    e = tmp_path / "expected"
    a = tmp_path / "actual"
    _write_nc(
        e / "nc" / "69" / "profiles" / "R69_001.nc",
        np.arange(5, dtype=float),
        np.arange(5, dtype=float) * 0.1,
        np.array([b"1"] * 5),
    )
    _write_nc(
        a / "nc" / "69" / "69_001.nc",
        np.arange(5, dtype=float),
        np.arange(5, dtype=float) * 0.1,
        np.array([b"1"] * 5),
    )
    e_xml = e / "xml"
    a_xml = a / "xml"
    e_xml.mkdir(parents=True)
    a_xml.mkdir(parents=True)
    (e_xml / "co041404_oracle_69_20250101T120000Z.xml").write_text(
        "<root><status>ok</status></root>"
    )
    (a_xml / "co041404_oracle_69.xml").write_text("<root><status>ok</status></root>")
    report = compare_outputs(e, a, wmo=69)
    assert report.ok, [m.message for m in report.mismatches]


def test_unimplemented_products_are_warnings_not_errors(tmp_path: Path) -> None:
    """Oracle-only meta/tech/traj/prof/D-pal files must NOT be flagged as errors."""
    e = tmp_path / "expected"
    a = tmp_path / "actual"
    # Oracle emits these extra files that Python does not produce yet.
    for name in [
        "6902892_Rtraj.nc",
        "6902892_meta.nc",
        "6902892_tech.nc",
        "profiles/BR6902892_001D.nc",
    ]:
        p = e / "nc" / "6902892" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        _write_nc(
            p, np.arange(3, dtype=float), np.arange(3, dtype=float) * 0.1, np.array([b"1"] * 3)
        )
    # Python side has only the mono-profile ascent file.
    _write_nc(
        a / "nc" / "6902892" / "6902892_001.nc",
        np.arange(3, dtype=float),
        np.arange(3, dtype=float) * 0.1,
        np.array([b"1"] * 3),
    )
    report = compare_outputs(e, a, wmo=6902892)
    errors = [m for m in report.mismatches if m.severity == "error"]
    assert not errors, [m.message for m in errors]
    warnings = [m for m in report.mismatches if m.severity == "warning"]
    # All four "missing" files should surface as warnings, not errors.
    assert len(warnings) >= 4


def test_canonical_key_strips_admt_prefix_not_d_suffix() -> None:
    """BR-prefix is stripped; key itself is used only for matching after
    prefix removal. The D suffix is detected via _python_omits_expected_file,
    not via the key (so 001 and 001D don't collide)."""
    assert _canonical_nc_key(Path("BR6902892_086.nc")) == "6902892_086.nc"
    assert _canonical_nc_key(Path("R6902892_086.nc")) == "6902892_086.nc"
    # D-suffix preserved in key so the canonicalisation doesn't collapse
    # deep and ascent cycles onto the same key.
    assert _canonical_nc_key(Path("BR6902892_001D.nc")) == "6902892_001D.nc"
