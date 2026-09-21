#!/usr/bin/env python3
"""Audit ``<wmo>_prof.nc`` against the GDAC multi-profile references.

Sibling of ``audit_mono_profile_admt.py``. Compares structure (dimensions,
variable inventory, dtypes) and the per-profile semantics that the
multi-profile writer previously got wrong: ``PROFILE_<PARAM>_QC``,
``CONFIG_MISSION_NUMBER``, ``DC_REFERENCE`` and
``VERTICAL_SAMPLING_SCHEME``.

``N_PROF`` is deliberately *not* compared: the references span a float's
whole mission while a local run covers only the cycles whose raw files
are present.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import netCDF4  # type: ignore[import-untyped]
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "phase4_outputs" / "apex_argos_nc" / "nc"
DEFAULT_REPORT = REPO_ROOT / "docs" / "phase_reports" / "multi_profile_admt_audit.json"

#: Dimensions whose size is a property of the run, not of the format.
_RUN_SIZED = {"N_PROF", "N_LEVELS", "N_HISTORY"}


def _text(values: Any) -> str:
    array = np.ma.filled(np.asarray(values), b" ").astype("S1")
    joined = array.tobytes() if array.ndim else bytes(array.item())
    return joined.decode("ascii", "replace").strip("\x00 ")


def _audit_one(ours: Path, reference: Path) -> dict[str, Any]:
    with netCDF4.Dataset(ours) as local, netCDF4.Dataset(reference) as ref:
        ref_vars, local_vars = set(ref.variables), set(local.variables)
        missing = sorted(ref_vars - local_vars)
        extra = sorted(local_vars - ref_vars)

        dim_issues = []
        for name, dim in ref.dimensions.items():
            if name in _RUN_SIZED:
                if name not in local.dimensions:
                    dim_issues.append(f"{name}: absent")
                continue
            if name not in local.dimensions:
                dim_issues.append(f"{name}: absent")
            elif local.dimensions[name].size != dim.size:
                dim_issues.append(f"{name}: {local.dimensions[name].size} != {dim.size}")

        dtype_issues = [
            f"{name}: {local[name].dtype} != {ref[name].dtype}"
            for name in sorted(ref_vars & local_vars)
            if str(local[name].dtype) != str(ref[name].dtype)
        ]

        # Per-profile semantics, checked on the cycles we actually hold.
        ref_cycles = {
            int(c): i for i, c in enumerate(np.ma.filled(ref["CYCLE_NUMBER"][:], -1)) if c != -1
        }
        semantic: dict[str, Any] = {"compared": 0, "mismatch": []}
        local_cycles = np.ma.filled(local["CYCLE_NUMBER"][:], -1)
        for i, cycle in enumerate(local_cycles):
            j = ref_cycles.get(int(cycle))
            if j is None:
                continue
            semantic["compared"] += 1
            checks = {
                "CONFIG_MISSION_NUMBER": (
                    int(local["CONFIG_MISSION_NUMBER"][i]),
                    int(ref["CONFIG_MISSION_NUMBER"][j]),
                ),
                "DC_REFERENCE": (
                    _text(local["DC_REFERENCE"][i]),
                    _text(ref["DC_REFERENCE"][j]),
                ),
                "VERTICAL_SAMPLING_SCHEME": (
                    _text(local["VERTICAL_SAMPLING_SCHEME"][i]),
                    _text(ref["VERTICAL_SAMPLING_SCHEME"][j]),
                ),
            }
            for param in ("PRES", "TEMP", "PSAL"):
                name = f"PROFILE_{param}_QC"
                if name in local_vars and name in ref_vars:
                    checks[name] = (
                        _text(local[name][i]),
                        _text(ref[name][j]),
                    )
            for field, (got, want) in checks.items():
                if got != want:
                    semantic["mismatch"].append(
                        {"cycle": int(cycle), "field": field, "ours": got, "gdac": want}
                    )

        status = (
            "structural_parity" if not (missing or extra or dim_issues or dtype_issues) else "gap"
        )
        return {
            "status": status,
            "missing_variables": missing,
            "extra_variables": extra,
            "dimension_issues": dim_issues,
            "dtype_issues": dtype_issues,
            "semantics": semantic,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--reference", type=Path, action="append", default=None)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    references = args.reference or []
    results: dict[str, Any] = {}
    for reference in references:
        wmo = reference.name.split("_")[0].replace("gdac-", "")
        ours = args.output_root / wmo / f"{wmo}_prof.nc"
        if not ours.exists():
            results[wmo] = {"status": "not_generated_no_raw_data"}
            continue
        results[wmo] = _audit_one(ours, reference)

    for wmo, entry in sorted(results.items()):
        if entry["status"] == "not_generated_no_raw_data":
            print(f"  {wmo}: not_generated_no_raw_data")
            continue
        semantics = entry["semantics"]
        print(
            f"  {wmo}: {entry['status']} | missing={len(entry['missing_variables'])} "
            f"extra={len(entry['extra_variables'])} dims={len(entry['dimension_issues'])} "
            f"dtypes={len(entry['dtype_issues'])} | semantics compared="
            f"{semantics['compared']} mismatch={len(semantics['mismatch'])}"
        )
        for item in semantics["mismatch"][:6]:
            print(
                f"      cycle {item['cycle']} {item['field']}: {item['ours']!r} != {item['gdac']!r}"
            )
        for name in entry["missing_variables"][:8]:
            print(f"      missing: {name}")

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(results, indent=2, sort_keys=True))
    print(f"wrote {args.report}")


if __name__ == "__main__":
    main()
