#!/usr/bin/env python3
"""Audit generated <wmo>_tech.nc against GDAC technical references.

Phase 6A.4 validation tool. Compares structure (dimensions, variables,
ordering, dtypes, attributes, globals) and, for every cycle both sides
share, every technical parameter value.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import netCDF4
import numpy as np

from argo_decoder.nc.technical import UNSUPPORTED_TECH_PARAMETERS


def _table(ds: netCDF4.Dataset) -> dict[int, dict[str, str]]:
    names = [
        str(x).strip()
        for x in np.asarray(
            netCDF4.chartostring(ds.variables["TECHNICAL_PARAMETER_NAME"][:])
        ).reshape(-1)
    ]
    values = [
        str(x).strip()
        for x in np.asarray(
            netCDF4.chartostring(ds.variables["TECHNICAL_PARAMETER_VALUE"][:])
        ).reshape(-1)
    ]
    cycles = np.ma.filled(ds.variables["CYCLE_NUMBER"][:], -99999)
    out: dict[int, dict[str, str]] = defaultdict(dict)
    for i, name in enumerate(names):
        cycle = int(cycles[i])
        if cycle == -99999 or not name:
            continue
        out[cycle][name] = values[i]
    return dict(out)


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
            if str(a.getncattr(k)) != str(b.getncattr(k)):
                attr_diffs.append(f"{name}.~{k}={a.getncattr(k)!r}vs{b.getncattr(k)!r}")
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


def _numeric_equal(a: str, b: str) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-6
    except ValueError:
        return a == b


def audit(python_root: Path, reference_root: Path, report_dir: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for py_path in sorted(python_root.glob("*/*_tech.nc")):
        wmo = py_path.parent.name
        ref_path = reference_root / wmo / "meta" / f"{wmo}_tech.nc"
        if not ref_path.exists():
            records.append({"wmo": wmo, "status": "missing_reference"})
            continue
        with netCDF4.Dataset(py_path) as py, netCDF4.Dataset(ref_path) as ref:
            structure = _structure(py, ref)
            ours, theirs = _table(py), _table(ref)
            shared = sorted(set(ours) & set(theirs))
            match = mismatch = 0
            not_emitted: dict[str, int] = defaultdict(int)
            examples: list[dict[str, str]] = []
            for cycle in shared:
                for name, ref_value in theirs[cycle].items():
                    if name not in ours[cycle]:
                        not_emitted[name] += 1
                        continue
                    if _numeric_equal(ours[cycle][name], ref_value):
                        match += 1
                    else:
                        mismatch += 1
                        if len(examples) < 10:
                            examples.append(
                                {
                                    "cycle": str(cycle),
                                    "parameter": name,
                                    "py": ours[cycle][name],
                                    "ref": ref_value,
                                }
                            )
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
                    "shared_cycles": len(shared),
                    "value_match": match,
                    "value_mismatch": mismatch,
                    "not_emitted": dict(not_emitted),
                    "mismatch_examples": examples,
                }
            )
    for ref_path in sorted(reference_root.glob("*/meta/*_tech.nc")):
        wmo = ref_path.parent.parent.name
        if not (python_root / wmo / f"{wmo}_tech.nc").exists():
            records.append({"wmo": wmo, "status": "not_generated_no_raw_data"})

    summary: dict[str, int] = {}
    for rec in records:
        summary[rec["status"]] = summary.get(rec["status"], 0) + 1
    payload = {
        "summary": summary,
        "records": records,
        "unsupported_parameters": UNSUPPORTED_TECH_PARAMETERS,
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "phase6a4_technical_audit.json").write_text(
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
    print(f"audited technical files: {payload['summary']}")
    total_match = total_mismatch = 0
    for rec in payload["records"]:
        if rec["status"] not in ("structural_parity", "structural_gap"):
            print(f"  {rec['wmo']}: {rec['status']}")
            continue
        total_match += rec["value_match"]
        total_mismatch += rec["value_mismatch"]
        print(
            f"  {rec['wmo']}: {rec['status']} | shared cycles={rec['shared_cycles']} "
            f"values match={rec['value_match']} mismatch={rec['value_mismatch']} "
            f"not emitted={sum(rec['not_emitted'].values())}"
        )
        for ex in rec["mismatch_examples"][:3]:
            print(f"      MISMATCH cyc{ex['cycle']} {ex['parameter']}: {ex['py']} vs {ex['ref']}")
    if total_match + total_mismatch:
        pct = 100.0 * total_match / (total_match + total_mismatch)
        print(
            f"\nemitted-value agreement: {total_match}/{total_match + total_mismatch} ({pct:.1f}%)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
