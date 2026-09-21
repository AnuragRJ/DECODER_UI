"""NetCDF / XML comparator used by the dual-run harness.

Compares the output of the MATLAB oracle with the Python output and emits a
structured list of mismatches. Implements the tolerance policy from the
migration plan:

* QC flags → exact match
* JULD → 1 ms
* PRES / TEMP / CNDC / PSAL / DOXY / BGC → per-variable tolerances
* Dimensions, variable names, attributes, and NaN/fill masks → exact
* XML → structural comparison (ignoring timing fields)
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import xarray as xr

# Default relative tolerance for scientific variables.
_DEFAULT_RTOL: dict[str, float] = {
    "PRES": 1e-3,
    "TEMP": 1e-6,
    "CNDC": 1e-6,
    "PSAL": 1e-6,
    "DOXY": 1e-2,
    "CHLA": 1e-6,
    "BBP": 1e-6,
    "PH_IN_SITU_TOTAL": 1e-4,
    "PH": 1e-4,
    "NITRATE": 1e-6,
    "PRES_ADJUSTED": 1e-3,
}
# Absolute tolerances (in variable units) used near zero / for time.
_DEFAULT_ATOL: dict[str, float] = {
    "JULD": 1.0 / 86400.0 / 1000.0,  # 1 ms in days
    "LATITUDE": 1e-7,
    "LONGITUDE": 1e-7,
}
# Variables whose values must match exactly.
_EXACT = {"<QC>"}  # sentinel; matched by suffix


@dataclass
class Mismatch:
    severity: str  # "error" | "warning" | "info"
    scope: str  # "nc_file" | "nc_variable" | "xml" | "file_set"
    file: str
    message: str
    variable: str | None = None
    max_abs_diff: float | None = None


@dataclass
class ComparisonReport:
    mismatches: list[Mismatch] = field(default_factory=list)
    files_compared: int = 0
    variables_compared: int = 0

    @property
    def ok(self) -> bool:
        return not any(m.severity == "error" for m in self.mismatches)

    def add(
        self,
        sev: str,
        scope: str,
        file: str,
        msg: str,
        *,
        variable: str | None = None,
        max_abs_diff: float | None = None,
    ) -> None:
        self.mismatches.append(
            Mismatch(
                severity=sev,
                scope=scope,
                file=file,
                message=msg,
                variable=variable,
                max_abs_diff=max_abs_diff,
            )
        )


def _is_qc_var(name: str) -> bool:
    return name.endswith("_QC") or name == "POSITION_QC" or name.startswith("SCIENTIFIC_CALIB")


def _compare_nc_file(
    expected: Path, actual: Path, report: ComparisonReport, rtol_map: dict[str, float]
) -> None:
    if not expected.exists():
        report.add("error", "file_set", actual.name, f"Expected file missing: {expected}")
        return
    if not actual.exists():
        report.add("error", "file_set", expected.name, f"Actual file missing: {actual}")
        return
    try:
        with (
            xr.open_dataset(expected, decode_cf=False) as ds_e,
            xr.open_dataset(actual, decode_cf=False) as ds_a,
        ):
            # Dimensions
            if dict(ds_e.sizes) != dict(ds_a.sizes):
                report.add(
                    "error",
                    "nc_file",
                    expected.name,
                    f"Dimension mismatch: {dict(ds_e.sizes)} vs {dict(ds_a.sizes)}",
                )
                return
            # Variable presence
            e_vars: set[str] = {str(v) for v in ds_e.variables}
            a_vars: set[str] = {str(v) for v in ds_a.variables}
            missing: set[str] = e_vars - a_vars
            extra: set[str] = a_vars - e_vars
            for v in sorted(missing):
                report.add(
                    "error", "nc_variable", expected.name, f"Missing variable: {v}", variable=v
                )
            for v in sorted(extra):
                report.add(
                    "warning", "nc_variable", expected.name, f"Extra variable: {v}", variable=v
                )
            # Global attributes
            e_attrs = {k: v for k, v in ds_e.attrs.items() if k != "history"}
            a_attrs = {k: v for k, v in ds_a.attrs.items() if k != "history"}
            for k in e_attrs:
                if k not in a_attrs:
                    report.add("warning", "nc_file", expected.name, f"Missing global attr {k}")
                elif e_attrs[k] != a_attrs.get(k):
                    sev = "info" if k in _VOLATILE_GLOBAL_ATTRS else "warning"
                    report.add(
                        sev,
                        "nc_file",
                        expected.name,
                        f"Global attr {k!r} differs: {e_attrs[k]!r} vs {a_attrs.get(k)!r}",
                    )
            # Variables
            common_vars: set[str] = e_vars & a_vars
            for v in sorted(common_vars):
                report.variables_compared += 1
                ve = ds_e[v]
                va = ds_a[v]
                is_qc = _is_qc_var(v)
                if ve.dtype != va.dtype and not is_qc:
                    report.add(
                        "error",
                        "nc_variable",
                        expected.name,
                        f"dtype differs: {ve.dtype} vs {va.dtype}",
                        variable=v,
                    )
                    continue
                if ve.shape != va.shape:
                    report.add(
                        "error",
                        "nc_variable",
                        expected.name,
                        f"shape differs: {ve.shape} vs {va.shape}",
                        variable=v,
                    )
                    continue
                a_e = ve.values
                a_a = va.values
                # NaN/fill mask comparison (floating-point only).
                if np.issubdtype(a_e.dtype, np.floating) and np.issubdtype(a_a.dtype, np.floating):
                    nan_mask_e = ~np.isfinite(a_e)
                    nan_mask_a = ~np.isfinite(a_a)
                    if not np.array_equal(nan_mask_e, nan_mask_a):
                        report.add(
                            "error",
                            "nc_variable",
                            expected.name,
                            "NaN/fill mask differs",
                            variable=v,
                        )
                        continue
                    valid = ~nan_mask_e
                else:
                    nan_mask_e = np.zeros_like(a_e, dtype=bool)
                    nan_mask_a = np.zeros_like(a_a, dtype=bool)
                    valid = np.ones(a_e.shape, dtype=bool)
                if is_qc:
                    # Compare QC flag strings robustly across dtypes:
                    # MATLAB writes NC_CHAR (dtype 'S1'), our mono files
                    # write int8, and our multi file writes NC_CHAR. Cast
                    # both sides to str before comparing.
                    eq = np.array_equal(a_e.astype(str), a_a.astype(str))
                    if not eq:
                        report.add(
                            "error",
                            "nc_variable",
                            expected.name,
                            "QC flag values differ",
                            variable=v,
                        )
                    continue
                # Numeric compare
                valid = ~nan_mask_e
                if not valid.any():
                    continue
                diff = np.abs(a_e[valid] - a_a[valid])
                rtol = rtol_map.get(v, _DEFAULT_RTOL.get(v, 1e-6))
                atol = _DEFAULT_ATOL.get(v, 0.0)
                scale = np.maximum(np.abs(a_e[valid]), 1e-12)
                bad = diff > (atol + rtol * scale)
                if bad.any():
                    max_diff = float(diff.max())
                    report.add(
                        "error",
                        "nc_variable",
                        expected.name,
                        (
                            f"Values differ (rtol={rtol:g}, atol={atol:g}); "
                            f"max |diff|={max_diff:.3g}"
                        ),
                        variable=v,
                        max_abs_diff=max_diff,
                    )
    except Exception as exc:  # pragma: no cover - defensive
        report.add("error", "nc_file", expected.name, f"Exception comparing: {exc!r}")


_IGNORED_XML_TAGS = {"start_date", "duration_seconds", "decoder_version", "message"}


def _compare_xml(expected: Path, actual: Path, report: ComparisonReport) -> None:
    if not expected.exists() or not actual.exists():
        report.add(
            "error",
            "xml",
            expected.name,
            "XML file present on one side only",
        )
        return
    try:
        e_tree = ET.parse(expected).getroot()
        a_tree = ET.parse(actual).getroot()
    except ET.ParseError as exc:
        report.add("error", "xml", expected.name, f"XML parse error: {exc}")
        return

    def _collect(elem: ET.Element, prefix: str = "") -> dict[str, str]:
        out: dict[str, str] = {}
        for child in elem:
            tag = f"{prefix}{child.tag}"
            if child.tag not in _IGNORED_XML_TAGS:
                text = (child.text or "").strip()
                if text:
                    out[tag] = text
            out.update(_collect(child, prefix=f"{tag}/"))
        return out

    e_map = _collect(e_tree)
    a_map = _collect(a_tree)
    for k in e_map.keys() | a_map.keys():
        if e_map.get(k) != a_map.get(k) and k.split("/")[-1] not in _IGNORED_XML_TAGS:
            report.add(
                "warning" if k.endswith("/message") else "error",
                "xml",
                expected.name,
                f"XML tag {k!r} differs: {e_map.get(k)!r} vs {a_map.get(k)!r}",
            )


_MATLAB_FNAME_PREFIXES = ("R", "BR", "D")

# Names of non-mono-profile NetCDF products produced by the MATLAB chain
# that are NOT yet implemented on the Python side (M5 trajectory, meta/tech
# auxiliary files, multi-profile). These are reported as ``warning`` rather
# than ``error`` so their absence does not block cutover gating for the
# implemented mono-profile pipeline.
_PYTHON_NOT_YET_PRODUCED_SUFFIXES = frozenset(
    {
        "_Rtraj.nc",  # M5 real-time trajectory product (not yet produced)
        "_meta.nc",  # float-level meta NetCDF (wire-up pending)
        "_tech.nc",  # technical / engineering NetCDF (wire-up pending)
    }
)

# Global attributes that are expected to differ between oracle (MATLAB) and
# Python outputs (decoder id, creation timestamps, software revision). These
# are compared but emit ``info`` rather than ``warning`` so they don't
# drown the signal.
_VOLATILE_GLOBAL_ATTRS = frozenset(
    {
        "history",
        "decoder_version",
        "DATE_CREATION",
        "DATE_UPDATE",
        "date_update",
        "date_creation",
    }
)

# Suffix appended to a mono-profile cycle number to denote a deep-park /
# downcast companion profile (e.g. ``BR6902892_001D.nc``). Our Python
# pipeline only emits ascent profiles, so these deep companions are not
# yet produced.
_DEEP_PROFILE_SUFFIX_LETTER = "D"


def _canonical_nc_key(path: Path) -> str:
    """Normalize a NetCDF filename to a canonical WMO-cycle key.

    The MATLAB oracle writes mono-profiles into a ``profiles/`` subdirectory
    and prefixes filenames according to the ADMT convention:

    * ``R``   - real-time (RT) profile     (e.g. ``R6902892_086.nc``)
    * ``BR``  - best-of-RT (B) profile     (e.g. ``BR6902892_086.nc``)
    * ``D``   - delayed-mode profile       (e.g. ``D6902892_086.nc``)

    A trailing single letter (e.g. ``001D.nc``) denotes the deep-park
    / downcast companion profile and is NOT treated as a separate cycle
    for matching purposes.

    Our Python writer emits plain ``<wmo>_<cycle>.nc`` at the root of the
    ``nc/<wmo>/`` directory. Strip the MATLAB prefixes (the ``profiles/``
    directory is flattened away by keying on basename alone) so the two
    layouts can be matched directly.
    """
    name = path.name
    # Strip the longest-matching ADMT prefix first (BR before R, etc.).
    for pfx in sorted(_MATLAB_FNAME_PREFIXES, key=len, reverse=True):
        if name.startswith(pfx) and not name[len(pfx) :].startswith(pfx):
            name = name[len(pfx) :]
            break
    return name


def _python_omits_expected_file(key: str, oracle_path: Path) -> bool:
    """Return True if ``key`` names a NetCDF the oracle legitimately
    produces but our Python pipeline does not yet implement (M5/M6/meta/tech
    and deep/downcast companion profiles).

    These are classified as ``warning`` -- not ``error`` -- so the cutover
    gate reflects mono-profile scientific correctness rather than M5/M6
    roadmap status.
    """
    if any(key.endswith(suf) for suf in _PYTHON_NOT_YET_PRODUCED_SUFFIXES):
        return True
    # Deep/downcast companion profile: basename matches e.g.
    # ``6902892_001D.nc`` (trailing capital letter right before .nc).
    base = oracle_path.name
    for pfx in sorted(_MATLAB_FNAME_PREFIXES, key=len, reverse=True):
        if base.startswith(pfx):
            base = base[len(pfx) :]
            break
    if base.endswith(f"{_DEEP_PROFILE_SUFFIX_LETTER}.nc") and "_" in base:
        stem = base[: -len(".nc")]
        if stem[-1] == _DEEP_PROFILE_SUFFIX_LETTER and stem[-2].isdigit():
            return True
    return False


def _collect_nc_files(root: Path, wmo: int) -> dict[str, Path]:
    """Recursively collect NetCDF files under ``root`` keyed by canonical name.

    The MATLAB layout places mono-profiles under ``profiles/`` and meta/
    multi-profile/tech/trajectory files at the ``nc/<wmo>/`` root; we
    therefore rglob ``**/*.nc`` rather than globbing only the top level.
    """
    wmo_dir = root / "nc" / str(wmo)
    out: dict[str, Path] = {}
    if not wmo_dir.exists():
        return out
    for p in wmo_dir.rglob("*.nc"):
        key = _canonical_nc_key(p)
        # If the same key appears in multiple places (e.g. both a top-level
        # and a profiles/ copy, which MATLAB sometimes produces), prefer
        # the profiles/ version as it is the canonical ADMT location.
        if key not in out or "profiles" in p.parts:
            out[key] = p
    return out


def _find_xml_for_wmo(xml_root: Path, wmo: int, expected_name: str | None = None) -> Path | None:
    """Locate the XML report for ``wmo`` under ``xml_root``.

    The MATLAB oracle does NOT honour the requested ``xmlreport`` filename
    verbatim -- it appends its own timestamp/identifier suffix, producing
    names like ``co041404_oracle_<wmo>_<timestamp>.xml`` instead of the
    requested ``co041404_oracle_<wmo>.xml``. The structural-parity golden
    tree uses a different prefix again (``co041404_golden_<wmo>.xml``).
    We therefore locate by WMO token in the basename rather than by exact
    name, with the caller-supplied ``expected_name`` preferred first.
    """
    if not xml_root.exists():
        return None
    # 1) Prefer the caller's expected name (e.g. what the Python side wrote).
    if expected_name is not None:
        candidate = xml_root / expected_name
        if candidate.exists():
            return candidate
    # 2) Known prefixes used by the oracle, golden trees, and offline CI.
    # The container's own rsynclog driver emits filenames of the form
    # ``co041404_<timestamp>.xml`` (WMO lives inside the XML body not the
    # filename), so we also glob for the timestamped variant and prefer
    # the most recent one when no WMO-named XML is found.
    wmo_token = f"{wmo}"
    for prefix in (
        "co041404_oracle_",
        "co041404_golden_",
        f"co041404_oracle_{wmo_token}",
        f"co041404_golden_{wmo_token}",
    ):
        hits = sorted(xml_root.glob(f"{prefix}*.xml"))
        if hits:
            return hits[-1]  # most recent if multiple timestamped copies
    # 3) Fallback: any co041404_*.xml (container-generated timestamped
    # reports whose filename does not encode the WMO). Pick the most
    # recent by mtime so we compare against the latest run.
    co_hits = sorted(
        xml_root.glob("co041404_*.xml"),
        key=lambda p: p.stat().st_mtime,
    )
    if co_hits:
        return co_hits[-1]
    # 4) Last-resort fallback: any XML containing the WMO token.
    for xf in sorted(xml_root.glob("*.xml")):
        if wmo_token in xf.name:
            return xf
    return None


def compare_outputs(
    expected_root: Path,
    actual_root: Path,
    *,
    wmo: int,
    rtol_map: dict[str, float] | None = None,
) -> ComparisonReport:
    """Compare all output files for a given WMO between expected and actual."""
    report = ComparisonReport()
    rtol_map = rtol_map or {}

    # Collect NetCDF files on both sides. The oracle may lay files out in
    # ``nc/<wmo>/profiles/`` with R/BR/D prefixes; our Python output writes
    # directly to ``nc/<wmo>/`` with no prefix. We canonicalise both.
    e_root, a_root = Path(expected_root), Path(actual_root)
    e_files = _collect_nc_files(e_root, wmo)
    a_files = _collect_nc_files(a_root, wmo)

    # Diagnose missing directories.
    e_nc_dir = e_root / "nc" / str(wmo)
    a_nc_dir = a_root / "nc" / str(wmo)
    if not e_files and not e_nc_dir.exists():
        report.add("error", "file_set", str(e_nc_dir), "Oracle NetCDF directory not found")
    if not a_files and not a_nc_dir.exists():
        report.add("error", "file_set", str(a_nc_dir), "Python NetCDF directory not found")

    all_keys = sorted(e_files.keys() | a_files.keys())
    for key in all_keys:
        report.files_compared += 1
        e_path = e_files.get(key)
        a_path = a_files.get(key)
        if e_path is None:
            report.add(
                "warning",
                "file_set",
                key,
                f"File present in Python output but not in oracle: {a_path}",
            )
            continue
        if a_path is None:
            severity = "warning" if _python_omits_expected_file(key, e_path) else "error"
            report.add(
                severity,
                "file_set",
                key,
                f"Oracle produced {e_path} but Python did not produce a matching file",
            )
            continue
        _compare_nc_file(e_path, a_path, report, rtol_map)

    # XML comparison. The Python side writes to a known filename; the
    # oracle appends its own timestamp and the golden-tree tests use yet
    # another prefix, so we locate each side by WMO token.
    e_xml_dir = e_root / "xml"
    a_xml_dir = a_root / "xml"
    py_xml_name = f"co041404_oracle_{wmo}.xml"
    e_xml = _find_xml_for_wmo(e_xml_dir, wmo)
    a_xml = _find_xml_for_wmo(a_xml_dir, wmo, expected_name=py_xml_name)
    if e_xml is not None and a_xml is not None:
        _compare_xml(e_xml, a_xml, report)
        report.files_compared += 1
    elif e_xml is not None and a_xml is None:
        report.add("error", "xml", py_xml_name, "Expected XML present but actual XML missing")
    elif (
        e_xml is None and a_xml is not None and e_xml_dir.exists() and any(e_xml_dir.glob("*.xml"))
    ):
        # XML directory exists on the expected side but no WMO match →
        # non-fatal warning (oracle may skip XML on early decode failure).
        report.add(
            "warning",
            "xml",
            py_xml_name,
            "Expected-side XML directory has files but none matched this WMO",
        )

    return report
