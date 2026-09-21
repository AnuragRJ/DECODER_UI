#!/usr/bin/env python3
"""Audit generated <wmo>_meta.nc against GDAC metadata references.

Phase 6A.2 validation tool. Compares structure (dimensions, variables,
ordering, dtypes, attributes, globals) and every field value, and
reports which values match, which are blank on our side, and which
genuinely differ.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import netCDF4
import numpy as np


def _values(ds: netCDF4.Dataset, name: str) -> list[str]:
    var = ds.variables[name]
    arr = var[:]
    if var.dtype.kind != "S":
        flat = np.atleast_1d(np.ma.filled(arr, np.nan)).astype(np.float64).ravel()
        return ["" if not np.isfinite(x) or x >= 99999.0 else f"{x:g}" for x in flat]
    if arr.ndim == 0:
        item = arr.item()
        text = item.decode() if isinstance(item, bytes) else str(item)
        return [text.strip()]
    decoded = netCDF4.chartostring(arr)
    return [str(x).strip() for x in np.asarray(decoded).reshape(-1)]


def _structure(py: netCDF4.Dataset, ref: netCDF4.Dataset) -> dict[str, Any]:
    pv, rv = list(py.variables), list(ref.variables)
    dtype_diffs: list[str] = []
    attr_diffs: list[str] = []
    for name in sorted(set(pv) & set(rv)):
        a, b = py.variables[name], ref.variables[name]
        if a.dtype != b.dtype:
            dtype_diffs.append(f"{name}: {a.dtype} vs {b.dtype}")
        if tuple(a.dimensions) != tuple(b.dimensions):
            dtype_diffs.append(f"{name}: dims {a.dimensions} vs {b.dimensions}")
        ka, kb = set(a.ncattrs()), set(b.ncattrs())
        for k in sorted(kb - ka):
            attr_diffs.append(f"{name}.-{k}")
        for k in sorted(ka - kb):
            attr_diffs.append(f"{name}.+{k}")
        for k in sorted(ka & kb):
            x, y = a.getncattr(k), b.getncattr(k)
            if isinstance(x, (float, np.floating)) and isinstance(y, (float, np.floating)):
                if not np.isclose(float(x), float(y)):
                    attr_diffs.append(f"{name}.~{k}={x!r}vs{y!r}")
            elif str(x) != str(y):
                attr_diffs.append(f"{name}.~{k}={x!r}vs{y!r}")
    gdiff = []
    for k in sorted(set(ref.ncattrs()) - set(py.ncattrs())):
        gdiff.append(f"-{k}")
    for k in sorted(set(py.ncattrs()) - set(ref.ncattrs())):
        gdiff.append(f"+{k}")
    for k in sorted(set(py.ncattrs()) & set(ref.ncattrs())):
        if str(py.getncattr(k)) != str(ref.getncattr(k)):
            gdiff.append(f"~{k}")
    return {
        "missing_variables": sorted(set(rv) - set(pv)),
        "extra_variables": sorted(set(pv) - set(rv)),
        "variable_order_identical": pv == rv,
        "missing_dimensions": sorted(set(ref.dimensions) - set(py.dimensions)),
        "extra_dimensions": sorted(set(py.dimensions) - set(ref.dimensions)),
        "dtype_diffs": dtype_diffs,
        "attribute_diffs": attr_diffs,
        "global_attribute_diffs": gdiff,
    }


# Fields whose value is expected to differ for a documented reason.
_VOLATILE = {"DATE_CREATION", "DATE_UPDATE"}


def _compare_values(py: netCDF4.Dataset, ref: netCDF4.Dataset) -> dict[str, Any]:
    match: list[str] = []
    blank_in_py: list[str] = []
    differs: list[dict[str, str]] = []
    both_blank: list[str] = []
    for name in list(ref.variables):
        if name not in py.variables or name in _VOLATILE:
            continue
        pvals, rvals = _values(py, name), _values(ref, name)
        # compare as sets of non-empty entries where the vector may be
        # ordered differently; order is reported separately.
        p_join, r_join = "|".join(pvals), "|".join(rvals)
        if p_join == r_join:
            (both_blank if not any(pvals) else match).append(name)
        elif not any(pvals):
            blank_in_py.append(name)
        else:
            differs.append({"variable": name, "py": p_join[:160], "ref": r_join[:160]})
    return {
        "value_match": match,
        "both_blank": both_blank,
        "blank_in_py": blank_in_py,
        "differs": differs,
    }


def audit(python_root: Path, reference_root: Path, report_dir: Path) -> dict:
    records = []
    for py_path in sorted(python_root.glob("*/*_meta.nc")):
        wmo = py_path.parent.name
        ref_path = reference_root / wmo / "meta" / f"{wmo}_meta.nc"
        if not ref_path.exists():
            records.append({"wmo": wmo, "status": "missing_reference"})
            continue
        with netCDF4.Dataset(py_path) as py, netCDF4.Dataset(ref_path) as ref:
            structure = _structure(py, ref)
            values = _compare_values(py, ref)
            clean = (
                not structure["missing_variables"]
                and not structure["extra_variables"]
                and structure["variable_order_identical"]
                and not structure["missing_dimensions"]
                and not structure["extra_dimensions"]
                and not structure["dtype_diffs"]
                and not structure["attribute_diffs"]
            )
            records.append(
                {
                    "wmo": wmo,
                    "status": "structural_parity" if clean else "structural_gap",
                    "structure": structure,
                    "values": values,
                }
            )
    for ref_path in sorted(reference_root.glob("*/meta/*_meta.nc")):
        wmo = ref_path.parent.parent.name
        if not (python_root / wmo / f"{wmo}_meta.nc").exists():
            records.append({"wmo": wmo, "status": "not_generated_no_raw_data"})

    summary: dict[str, int] = {}
    for rec in records:
        summary[rec["status"]] = summary.get(rec["status"], 0) + 1
    payload = {"summary": summary, "records": records}
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "phase6a2_metadata_audit.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--python-nc-root", type=Path, default=Path("phase4_outputs/apex_argos_nc/nc"))
    ap.add_argument(
        "--reference-root", type=Path, default=Path("phase5_reference/gdac_reference_dataset")
    )
    ap.add_argument("--report-dir", type=Path, default=Path("docs/phase_reports"))
    args = ap.parse_args()
    payload = audit(args.python_nc_root, args.reference_root, args.report_dir)
    print(f"audited metadata files: {payload['summary']}")
    for rec in payload["records"]:
        if rec["status"] not in ("structural_parity", "structural_gap"):
            print(f"  {rec['wmo']}: {rec['status']}")
            continue
        v = rec["values"]
        print(
            f"  {rec['wmo']}: {rec['status']} | match={len(v['value_match'])} "
            f"both_blank={len(v['both_blank'])} blank_in_py={len(v['blank_in_py'])} "
            f"differs={len(v['differs'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
