#!/usr/bin/env python3
"""Audit generated mono-profile NetCDFs against GDAC ADMT profile references.

This Phase 5 baseline script identifies structural gaps before we change the
writer. It compares the NetCDF dimensions/variables of Python-generated
``R*.nc`` profile files against available GDAC ``R*.nc`` or ``D*.nc`` files,
and also reports core science differences for PRES/TEMP/PSAL when shapes
match.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import netCDF4
import numpy as np

PARAMS = ("PRES", "TEMP", "PSAL")
TOLERANCES = {"PRES": 1e-3, "TEMP": 1e-6, "PSAL": 2e-6}


@dataclass(frozen=True)
class MonoProfileAuditRecord:
    wmo: int
    cycle: int
    python_file: str
    reference_file: str | None
    status: str
    python_dims: dict[str, int]
    reference_dims: dict[str, int]
    missing_dimensions: list[str]
    extra_dimensions: list[str]
    missing_variables: list[str]
    extra_variables: list[str]
    science_max_abs_diff: dict[str, float]
    notes: str


def _dims(path: Path) -> dict[str, int]:
    with netCDF4.Dataset(path) as ds:
        return {name: len(dim) for name, dim in ds.dimensions.items()}


def _variables(path: Path) -> set[str]:
    with netCDF4.Dataset(path) as ds:
        return set(ds.variables)


def _read_param(path: Path, name: str) -> np.ndarray:
    with netCDF4.Dataset(path) as ds:
        arr = np.ma.filled(ds.variables[name][:], np.nan).astype(np.float64)
    return np.asarray(arr).reshape(-1)


def _science_diffs(py_path: Path, ref_path: Path) -> tuple[dict[str, float], str]:
    diffs: dict[str, float] = {}
    notes: list[str] = []
    for param in PARAMS:
        try:
            actual = _read_param(py_path, param)
            expected = _read_param(ref_path, param)
        except KeyError:
            notes.append(f"{param}:missing")
            continue
        if actual.shape != expected.shape:
            notes.append(f"{param}:shape {actual.shape}!={expected.shape}")
            continue
        diff = float(np.nanmax(np.abs(actual - expected)))
        diffs[param] = diff
        if diff > TOLERANCES[param]:
            notes.append(f"{param}:diff {diff:g}>{TOLERANCES[param]:g}")
    return diffs, "; ".join(notes)


def _parse_python_profile(path: Path) -> tuple[int, int] | None:
    # .../nc/<wmo>/profiles/R<wmo>_<CCC>.nc
    try:
        wmo = int(path.parent.parent.name)
        cycle = int(path.stem.rsplit("_", 1)[1])
    except (IndexError, ValueError):
        return None
    return wmo, cycle


def _reference_for(reference_root: Path, wmo: int, cycle: int) -> Path | None:
    profile_dir = reference_root / str(wmo) / "profiles"
    for prefix in ("R", "D"):
        candidate = profile_dir / f"{prefix}{wmo}_{cycle:03d}.nc"
        if candidate.exists():
            return candidate
    return None


def audit(
    *,
    python_nc_root: Path,
    reference_root: Path,
    report_dir: Path,
) -> list[MonoProfileAuditRecord]:
    records: list[MonoProfileAuditRecord] = []
    for py_path in sorted(python_nc_root.glob("*/profiles/R*.nc")):
        parsed = _parse_python_profile(py_path)
        if parsed is None:
            continue
        wmo, cycle = parsed
        ref_path = _reference_for(reference_root, wmo, cycle)
        py_dims = _dims(py_path)
        py_vars = _variables(py_path)
        if ref_path is None:
            records.append(
                MonoProfileAuditRecord(
                    wmo=wmo,
                    cycle=cycle,
                    python_file=str(py_path),
                    reference_file=None,
                    status="missing_reference",
                    python_dims=py_dims,
                    reference_dims={},
                    missing_dimensions=[],
                    extra_dimensions=[],
                    missing_variables=[],
                    extra_variables=[],
                    science_max_abs_diff={},
                    notes="No GDAC R/D profile reference available for this cycle",
                )
            )
            continue
        ref_dims = _dims(ref_path)
        ref_vars = _variables(ref_path)
        missing_dims = sorted(set(ref_dims) - set(py_dims))
        extra_dims = sorted(set(py_dims) - set(ref_dims))
        missing_vars = sorted(ref_vars - py_vars)
        extra_vars = sorted(py_vars - ref_vars)
        diffs, science_notes = _science_diffs(py_path, ref_path)
        status = "pass" if not missing_dims and not missing_vars and not science_notes else "gap"
        notes = science_notes
        if missing_dims or missing_vars:
            notes = (notes + "; " if notes else "") + "structural gaps"
        records.append(
            MonoProfileAuditRecord(
                wmo=wmo,
                cycle=cycle,
                python_file=str(py_path),
                reference_file=str(ref_path),
                status=status,
                python_dims=py_dims,
                reference_dims=ref_dims,
                missing_dimensions=missing_dims,
                extra_dimensions=extra_dims,
                missing_variables=missing_vars,
                extra_variables=extra_vars,
                science_max_abs_diff=diffs,
                notes=notes,
            )
        )
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": {
            status: sum(1 for rec in records if rec.status == status)
            for status in sorted({rec.status for rec in records})
        },
        "records": [asdict(rec) for rec in records],
        "missing_variable_frequency": _frequency(
            var for rec in records for var in rec.missing_variables
        ),
        "missing_dimension_frequency": _frequency(
            dim for rec in records for dim in rec.missing_dimensions
        ),
    }
    (report_dir / "phase5_mono_profile_admt_baseline.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (report_dir / "phase5_mono_profile_admt_baseline.md").write_text(
        _markdown(records, payload),
        encoding="utf-8",
    )
    return records


def _frequency(values: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:  # type: ignore[union-attr]
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _markdown(records: list[MonoProfileAuditRecord], payload: dict[str, object]) -> str:
    lines = [
        "# Phase 5 mono-profile ADMT baseline audit",
        "",
        (
            "This report compares Python-generated mono-profile files with "
            "available GDAC R/D references."
        ),
        "",
        "## Summary",
        "",
    ]
    summary = payload.get("summary", {})
    if isinstance(summary, dict):
        for key in sorted(summary):
            lines.append(f"- {key}: {summary[key]}")
    lines.extend(
        [
            "",
            "## Most frequent missing dimensions",
            "",
        ]
    )
    missing_dims = payload.get("missing_dimension_frequency", {})
    if isinstance(missing_dims, dict):
        for key, count in list(missing_dims.items())[:20]:
            lines.append(f"- `{key}`: {count}")
    lines.extend(["", "## Most frequent missing variables", ""])
    missing_vars = payload.get("missing_variable_frequency", {})
    if isinstance(missing_vars, dict):
        for key, count in list(missing_vars.items())[:40]:
            lines.append(f"- `{key}`: {count}")
    lines.extend(
        [
            "",
            "## Records",
            "",
            (
                "| WMO | Cycle | Status | Reference | Missing dims | Missing vars | "
                "Science diffs | Notes |"
            ),
            "| ---: | ---: | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for rec in records:
        diffs = ", ".join(f"{key}={value:.3g}" for key, value in rec.science_max_abs_diff.items())
        lines.append(
            "| "
            f"{rec.wmo} | {rec.cycle} | {rec.status} | {rec.reference_file or ''} | "
            f"{', '.join(rec.missing_dimensions)} | {len(rec.missing_variables)} vars | "
            f"{diffs} | {rec.notes} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--python-nc-root",
        type=Path,
        default=Path("phase4_outputs") / "apex_argos_nc" / "nc",
    )
    parser.add_argument(
        "--reference-root",
        type=Path,
        default=Path("phase5_reference") / "gdac_reference_dataset",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path("docs") / "phase_reports",
    )
    args = parser.parse_args()
    records = audit(
        python_nc_root=args.python_nc_root,
        reference_root=args.reference_root,
        report_dir=args.report_dir,
    )
    summary: dict[str, int] = {}
    for rec in records:
        summary[rec.status] = summary.get(rec.status, 0) + 1
    print(f"audited {len(records)} mono profiles: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
