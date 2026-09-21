#!/usr/bin/env python3
"""Audit generated <wmo>_Rtraj.nc against GDAC trajectory references.

Phase 6A validation tool, mirroring ``audit_mono_profile_admt.py``.
Compares structure (dimensions, variables, ordering, dtypes, attributes,
global attributes) and values (per-cycle measurement rows, surface fixes,
cycle timings), and classifies every value difference by cause.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import netCDF4
import numpy as np

MC_SURFACE_FIX = 703
MC_FIRST_MESSAGE = 702
MC_LAST_MESSAGE = 704
JULD_TOL = 1e-5
POS_TOL = 1e-6


def _chars(ds: netCDF4.Dataset, name: str) -> list[str]:
    raw = netCDF4.chartostring(ds.variables[name][:])
    return [str(v) for v in np.asarray(raw).reshape(-1)]


def _f(ds: netCDF4.Dataset, name: str) -> np.ndarray:
    return np.ma.filled(ds.variables[name][:], np.nan).astype(np.float64).reshape(-1)


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
    global_diffs = []
    for k in sorted(set(ref.ncattrs()) - set(py.ncattrs())):
        global_diffs.append(f"-{k}")
    for k in sorted(set(py.ncattrs()) - set(ref.ncattrs())):
        global_diffs.append(f"+{k}")
    for k in sorted(set(py.ncattrs()) & set(ref.ncattrs())):
        if str(py.getncattr(k)) != str(ref.getncattr(k)):
            global_diffs.append(f"~{k}")
    return {
        "missing_variables": sorted(set(rv) - set(pv)),
        "extra_variables": sorted(set(pv) - set(rv)),
        "variable_order_identical": pv == rv,
        "missing_dimensions": sorted(set(ref.dimensions) - set(py.dimensions)),
        "extra_dimensions": sorted(set(py.dimensions) - set(ref.dimensions)),
        "dtype_diffs": dtype_diffs,
        "attribute_diffs": attr_diffs,
        "global_attribute_diffs": global_diffs,
    }


def _fix_key(juld: float, lat: float, lon: float) -> tuple[float, float, float]:
    return (round(juld, 5), round(lat, 4), round(lon, 4))


def _values(py: netCDF4.Dataset, ref: netCDF4.Dataset) -> dict[str, Any]:
    pmc, rmc = py.variables["MEASUREMENT_CODE"][:], ref.variables["MEASUREMENT_CODE"][:]
    pcn, rcn = py.variables["CYCLE_NUMBER"][:], ref.variables["CYCLE_NUMBER"][:]
    pj, rj = _f(py, "JULD"), _f(ref, "JULD")
    pla, rla = _f(py, "LATITUDE"), _f(ref, "LATITUDE")
    plo, rlo = _f(py, "LONGITUDE"), _f(ref, "LONGITUDE")
    pacc = np.ma.filled(py.variables["POSITION_ACCURACY"][:], b" ")
    racc = np.ma.filled(ref.variables["POSITION_ACCURACY"][:], b" ")

    shared = sorted({int(c) for c in pcn.tolist() if c >= 0} & {int(c) for c in rcn.tolist()})
    fix_total = fix_match = fix_acc_match = 0
    ref_only: list[float] = []
    py_only: list[float] = []
    endpoint_rows: list[dict[str, Any]] = []

    for cyc in shared:
        pi = [k for k in np.where(pcn == cyc)[0] if pmc[k] == MC_SURFACE_FIX]
        ri = [k for k in np.where(rcn == cyc)[0] if rmc[k] == MC_SURFACE_FIX]
        pset = {_fix_key(pj[k], pla[k], plo[k]): k for k in pi}
        rset = {_fix_key(rj[k], rla[k], rlo[k]): k for k in ri}
        fix_total += len(rset)
        for key, rk in rset.items():
            if key in pset:
                fix_match += 1
                if bytes(pacc[pset[key]]) == bytes(racc[rk]):
                    fix_acc_match += 1
            else:
                ref_only.append(key[0])
        for key in pset:
            if key not in rset:
                py_only.append(key[0])

        row: dict[str, Any] = {"cycle": cyc, "n_fix_py": len(pi), "n_fix_ref": len(ri)}
        for label, code in (("first_message", MC_FIRST_MESSAGE), ("last_message", MC_LAST_MESSAGE)):
            pv = next((pj[k] for k in np.where(pcn == cyc)[0] if pmc[k] == code), np.nan)
            rv = next((rj[k] for k in np.where(rcn == cyc)[0] if rmc[k] == code), np.nan)
            row[label] = (
                "exact"
                if np.isfinite(pv) and np.isfinite(rv) and abs(pv - rv) < JULD_TOL
                else f"{pv - rv:+.5f}"
                if np.isfinite(pv) and np.isfinite(rv)
                else "fill"
            )
        endpoint_rows.append(row)

    return {
        "shared_cycles": shared,
        "ref_fixes_total": fix_total,
        "ref_fixes_reproduced": fix_match,
        "ref_fixes_accuracy_match": fix_acc_match,
        "ref_only_fix_julds": sorted(ref_only),
        "py_only_fix_julds": sorted(py_only),
        "endpoints": endpoint_rows,
    }


def _classify(
    py_path: Path, ref: netCDF4.Dataset, values: dict[str, Any], raw_root: Path, ptt: str | None
) -> dict[str, Any]:
    """Classify unmatched fixes by checking the whole raw archive."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from argo_decoder.platforms.apex_argos.frames import parse_argos_fixes
    from argo_decoder.platforms.apex_argos.profile import datetime_to_juld

    archive: set[float] = set()
    if ptt:
        for raw in sorted((raw_root / ptt).glob("*.txt")):
            for fix in parse_argos_fixes(raw.read_bytes()):
                archive.add(round(datetime_to_juld(fix.at), 5))

    ref_only = values["ref_only_fix_julds"]
    absent = [j for j in ref_only if j not in archive]
    elsewhere = [j for j in ref_only if j in archive]

    rmc = ref.variables["MEASUREMENT_CODE"][:]
    rj = _f(ref, "JULD")
    ref_all = {round(float(rj[k]), 5) for k in np.where(rmc == MC_SURFACE_FIX)[0]}
    py_only = values["py_only_fix_julds"]
    py_absent_from_ref = [j for j in py_only if j not in ref_all]

    return {
        "ref_only_absent_from_raw_archive": len(absent),
        "ref_only_present_in_archive_other_cycle": len(elsewhere),
        "py_only_absent_from_reference_entirely": len(py_absent_from_ref),
        "py_only_total": len(py_only),
    }


PTT_BY_WMO = {"2901339": "102510", "2902201": "152399", "2902222": "152389", "2902223": "152382"}


def audit(python_root: Path, reference_root: Path, raw_root: Path, report_dir: Path) -> dict:
    records = []
    for py_path in sorted(python_root.glob("*/*_Rtraj.nc")):
        wmo = py_path.parent.name
        ref_path = reference_root / wmo / "meta" / f"{wmo}_Rtraj.nc"
        if not ref_path.exists():
            records.append({"wmo": wmo, "status": "missing_reference"})
            continue
        with netCDF4.Dataset(py_path) as py, netCDF4.Dataset(ref_path) as ref:
            structure = _structure(py, ref)
            values = _values(py, ref)
            classification = _classify(py_path, ref, values, raw_root, PTT_BY_WMO.get(wmo))
            structural_clean = (
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
                    "status": "structural_parity" if structural_clean else "structural_gap",
                    "n_measurement_py": len(py.dimensions["N_MEASUREMENT"]),
                    "n_measurement_ref": len(ref.dimensions["N_MEASUREMENT"]),
                    "n_cycle_py": len(py.dimensions["N_CYCLE"]),
                    "n_cycle_ref": len(ref.dimensions["N_CYCLE"]),
                    "structure": structure,
                    "values": values,
                    "classification": classification,
                }
            )
    # references with no generated counterpart
    for ref_path in sorted(reference_root.glob("*/meta/*_Rtraj.nc")):
        wmo = ref_path.parent.parent.name
        if not (python_root / wmo / f"{wmo}_Rtraj.nc").exists():
            records.append({"wmo": wmo, "status": "not_generated_no_raw_data"})

    summary: dict[str, int] = {}
    for rec in records:
        summary[rec["status"]] = summary.get(rec["status"], 0) + 1
    payload = {"summary": summary, "records": records}
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "phase6a_trajectory_audit.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--python-nc-root", type=Path, default=Path("phase4_outputs/apex_argos_nc/nc"))
    ap.add_argument(
        "--reference-root", type=Path, default=Path("phase5_reference/gdac_reference_dataset")
    )
    ap.add_argument("--raw-root", type=Path, default=Path("phase4_reference/raw/raw-files"))
    ap.add_argument("--report-dir", type=Path, default=Path("docs/phase_reports"))
    args = ap.parse_args()
    payload = audit(args.python_nc_root, args.reference_root, args.raw_root, args.report_dir)
    print(f"audited trajectories: {payload['summary']}")
    for rec in payload["records"]:
        if rec["status"] not in ("structural_parity", "structural_gap"):
            print(f"  {rec['wmo']}: {rec['status']}")
            continue
        v, c = rec["values"], rec["classification"]
        print(
            f"  {rec['wmo']}: {rec['status']} | fixes {v['ref_fixes_reproduced']}/"
            f"{v['ref_fixes_total']} reproduced | ref-only absent from raw archive: "
            f"{c['ref_only_absent_from_raw_archive']} | py-only absent from reference: "
            f"{c['py_only_absent_from_reference_entirely']}/{c['py_only_total']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
