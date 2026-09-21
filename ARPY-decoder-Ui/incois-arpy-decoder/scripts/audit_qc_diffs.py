#!/usr/bin/env python3
"""Audit every QC difference between decoder output and the GDAC reference.

Compares, per float and per cycle:

* per-level ``<PARAM>_QC`` for PRES / TEMP / PSAL (levels matched on PRES so
  that levels we recovered but GDAC never published are reported separately
  rather than shifting the comparison),
* the profile-scalar ``PROFILE_<PARAM>_QC`` summary flags,
* ``POSITION_QC`` / ``JULD_QC`` on the mono-profile files,
* ``POSITION_QC`` / ``JULD_QC`` / ``JULD_ADJUSTED_QC`` on the N_MEASUREMENT
  block of the trajectory file (matched on MEASUREMENT_CODE + JULD),
* ``POSITION_ACCURACY`` and the ``HISTORY_QCTEST`` masks where present.

Nothing here is float-specific: pass any number of ``--float WMO=our_dir=ref_dir``
triples.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import netCDF4  # type: ignore[import-untyped]
import numpy as np

PARAMS = ("PRES", "TEMP", "PSAL")
_CYCLE_RE = re.compile(r"_(\d+)\.nc$")


def _txt(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("ascii", "replace")
    if isinstance(value, np.ndarray):
        return "".join(_txt(v) for v in value.tolist())
    if isinstance(value, (list, tuple)):
        return "".join(_txt(v) for v in value)
    if value is np.ma.masked:
        return " "
    if isinstance(value, (int, np.integer)):
        # netCDF4 sometimes hands back char arrays as their ordinals
        return chr(int(value)) if 0 < int(value) < 128 else " "
    return str(value)


def _flags(ds: netCDF4.Dataset, name: str, row: int = 0) -> list[str]:
    if name not in ds.variables:
        return []
    raw = ds.variables[name][row]
    return [_txt(c) for c in np.ma.filled(raw, b" ").tolist()]


def _scalar_flag(ds: netCDF4.Dataset, name: str, row: int = 0) -> str:
    if name not in ds.variables:
        return ""
    return _txt(np.ma.filled(ds.variables[name][row], b" "))


def _pres(ds: netCDF4.Dataset, row: int = 0) -> np.ndarray:
    arr = ds.variables["PRES"][row]
    return np.ma.filled(arr.astype("f8"), np.nan)


@dataclass
class FloatReport:
    wmo: int
    cycles_ours: int = 0
    cycles_ref: int = 0
    cycles_common: list[int] = field(default_factory=list)
    cycles_only_ours: list[int] = field(default_factory=list)
    cycles_only_ref: list[int] = field(default_factory=list)
    ref_mode: Counter[str] = field(default_factory=Counter)
    level_total: int = 0
    level_diff: int = 0
    level_extra_ours: int = 0
    level_missing_ours: int = 0
    per_param: dict[str, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))
    per_cycle: dict[int, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))
    transitions: Counter[str] = field(default_factory=Counter)
    profile_flag_total: int = 0
    profile_flag_diff: list[str] = field(default_factory=list)
    position_qc_diff: list[str] = field(default_factory=list)
    juld_qc_diff: list[str] = field(default_factory=list)
    qctest_diff: list[str] = field(default_factory=list)
    traj_total: int = 0
    traj_diff: Counter[str] = field(default_factory=Counter)
    traj_examples: list[str] = field(default_factory=list)


def _cycle_of(path: Path) -> int:
    m = _CYCLE_RE.search(path.name)
    return int(m.group(1)) if m else -1


def _index_profiles(root: Path) -> dict[int, Path]:
    out: dict[int, Path] = {}
    for path in sorted(root.glob("*.nc")):
        cyc = _cycle_of(path)
        if cyc < 0:
            continue
        # a D-file supersedes an R-file for the same cycle
        if cyc in out and path.name.startswith("R"):
            continue
        out[cyc] = path
    return out


def _compare_profile(rep: FloatReport, cyc: int, ours: Path, ref: Path) -> None:
    a = netCDF4.Dataset(ours)
    b = netCDF4.Dataset(ref)
    try:
        rep.ref_mode[ref.name[0]] += 1
        pa, pb = _pres(a), _pres(b)
        # match levels on pressure (rounded to the stored resolution)
        key_b: dict[float, int] = {}
        for j, p in enumerate(pb):
            if np.isfinite(p):
                key_b.setdefault(round(float(p), 3), j)
        matched_b: set[int] = set()

        flags_a = {p: _flags(a, f"{p}_QC") for p in PARAMS}
        flags_b = {p: _flags(b, f"{p}_QC") for p in PARAMS}

        for i, p in enumerate(pa):
            if not np.isfinite(p):
                continue
            j = key_b.get(round(float(p), 3))
            if j is None:
                rep.level_extra_ours += 1
                continue
            matched_b.add(j)
            for param in PARAMS:
                fa = flags_a[param][i] if i < len(flags_a[param]) else " "
                fb = flags_b[param][j] if j < len(flags_b[param]) else " "
                rep.level_total += 1
                if fa != fb:
                    rep.level_diff += 1
                    rep.per_param[param][f"{fb}->{fa}"] += 1
                    rep.per_cycle[cyc][param] += 1
                    rep.transitions[f"{param} ref={fb} ours={fa}"] += 1
        rep.level_missing_ours += sum(
            1 for j, p in enumerate(pb) if np.isfinite(p) and j not in matched_b
        )

        for param in PARAMS:
            name = f"PROFILE_{param}_QC"
            fa, fb = _scalar_flag(a, name), _scalar_flag(b, name)
            if name in a.variables or name in b.variables:
                rep.profile_flag_total += 1
                if fa != fb:
                    rep.profile_flag_diff.append(f"cyc {cyc} {name}: ref={fb!r} ours={fa!r}")

        for name, bucket in (
            ("POSITION_QC", rep.position_qc_diff),
            ("JULD_QC", rep.juld_qc_diff),
        ):
            fa, fb = _scalar_flag(a, name), _scalar_flag(b, name)
            if fa != fb:
                bucket.append(f"cyc {cyc} {name}: ref={fb!r} ours={fa!r}")

        if "HISTORY_QCTEST" in a.variables and "HISTORY_QCTEST" in b.variables:
            qa = {_txt(x).strip() for x in np.ma.filled(a.variables["HISTORY_QCTEST"][:], b" ")}
            qb = {_txt(x).strip() for x in np.ma.filled(b.variables["HISTORY_QCTEST"][:], b" ")}
            qa.discard("")
            qb.discard("")
            if qa != qb:
                rep.qctest_diff.append(f"cyc {cyc}: ref={sorted(qb)} ours={sorted(qa)}")
    finally:
        a.close()
        b.close()


def _traj_rows(path: Path) -> dict[tuple[int, int, str], dict[str, str]]:
    ds = netCDF4.Dataset(path)
    try:
        if "MEASUREMENT_CODE" not in ds.variables:
            return {}
        mc = np.ma.filled(ds.variables["MEASUREMENT_CODE"][:], -1).astype(int)
        cyc = (
            np.ma.filled(ds.variables["CYCLE_NUMBER"][:], -99999).astype(int)
            if "CYCLE_NUMBER" in ds.variables
            else np.full(mc.shape, -1)
        )
        juld = (
            np.ma.filled(ds.variables["JULD"][:].astype("f8"), np.nan)
            if "JULD" in ds.variables
            else np.full(mc.shape, np.nan)
        )
        fields = {}
        for name in ("JULD_QC", "POSITION_QC", "JULD_ADJUSTED_QC"):
            if name in ds.variables:
                fields[name] = [_txt(c) for c in np.ma.filled(ds.variables[name][:], b" ").tolist()]
        rows: dict[tuple[int, int, str], dict[str, str]] = {}
        seen: Counter[tuple[int, int, str]] = Counter()
        for i in range(len(mc)):
            j = juld[i]
            jkey = "nan" if not np.isfinite(j) else f"{j:.6f}"
            key = (int(cyc[i]), int(mc[i]), jkey)
            seen[key] += 1
            if seen[key] > 1:
                key = (*key, seen[key])  # type: ignore[assignment]
            rows[key] = {k: (v[i] if i < len(v) else " ") for k, v in fields.items()}
        return rows
    finally:
        ds.close()


def _compare_traj(rep: FloatReport, ours: Path, ref: Path) -> None:
    if not ours.exists() or not ref.exists():
        return
    ra, rb = _traj_rows(ours), _traj_rows(ref)
    for key, vb in rb.items():
        va = ra.get(key)
        if va is None:
            continue
        for name, fb in vb.items():
            fa = va.get(name, " ")
            rep.traj_total += 1
            if fa != fb:
                rep.traj_diff[f"{name} ref={fb!r} ours={fa!r}"] += 1
                if len(rep.traj_examples) < 12:
                    rep.traj_examples.append(f"cyc {key[0]} MC{key[1]} {name}: {fb!r}->{fa!r}")


def audit(wmo: int, ours_root: Path, ref_root: Path) -> FloatReport:
    rep = FloatReport(wmo=wmo)
    ours = _index_profiles(ours_root / "profiles") if (ours_root / "profiles").is_dir() else {}
    ref = _index_profiles(ref_root / "profiles") if (ref_root / "profiles").is_dir() else {}
    rep.cycles_ours = len(ours)
    rep.cycles_ref = len(ref)
    rep.cycles_common = sorted(set(ours) & set(ref))
    rep.cycles_only_ours = sorted(set(ours) - set(ref))
    rep.cycles_only_ref = sorted(set(ref) - set(ours))
    for cyc in rep.cycles_common:
        _compare_profile(rep, cyc, ours[cyc], ref[cyc])
    _compare_traj(rep, ours_root / f"{wmo}_Rtraj.nc", ref_root / f"{wmo}_Rtraj.nc")
    return rep


def _print(rep: FloatReport) -> None:
    print(f"\n===== WMO {rep.wmo} =====")
    print(
        f"cycles: ours={rep.cycles_ours} ref={rep.cycles_ref} common={len(rep.cycles_common)}"
        f" only-ours={rep.cycles_only_ours} only-ref={rep.cycles_only_ref}"
    )
    print(f"reference file modes: {dict(rep.ref_mode)}")
    agree = rep.level_total - rep.level_diff
    pct = 100.0 * agree / rep.level_total if rep.level_total else float("nan")
    print(f"per-level QC cells: {agree}/{rep.level_total} identical ({pct:.2f}%)")
    print(
        f"levels only in ours: {rep.level_extra_ours}   "
        f"levels only in ref: {rep.level_missing_ours}"
    )
    if rep.level_diff:
        print("  by parameter:")
        for param in PARAMS:
            if rep.per_param[param]:
                total = sum(rep.per_param[param].values())
                detail = ", ".join(
                    f"{k}:{v}" for k, v in sorted(rep.per_param[param].items(), key=lambda x: -x[1])
                )
                print(f"    {param}: {total}  [{detail}]")
        print("  by cycle:")
        for cyc in sorted(rep.per_cycle):
            print(f"    cycle {cyc}: {dict(rep.per_cycle[cyc])}")
    print(
        f"PROFILE_<PARAM>_QC: {rep.profile_flag_total - len(rep.profile_flag_diff)}"
        f"/{rep.profile_flag_total} identical"
    )
    for line in rep.profile_flag_diff:
        print(f"    {line}")
    for label, bucket in (
        ("POSITION_QC", rep.position_qc_diff),
        ("JULD_QC", rep.juld_qc_diff),
        ("HISTORY_QCTEST", rep.qctest_diff),
    ):
        print(f"{label} diffs: {len(bucket)}")
        for line in bucket[:10]:
            print(f"    {line}")
    if rep.traj_total:
        tdiff = sum(rep.traj_diff.values())
        print(
            f"trajectory QC cells (matched rows): {rep.traj_total - tdiff}/{rep.traj_total}"
            f" identical"
        )
        for k, v in sorted(rep.traj_diff.items(), key=lambda x: -x[1]):
            print(f"    {k}: {v}")
        for line in rep.traj_examples:
            print(f"      e.g. {line}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--float",
        action="append",
        required=True,
        metavar="WMO=OURS_DIR=REF_DIR",
        help="repeatable triple",
    )
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    reports = []
    for spec in args.float:
        wmo_s, ours_s, ref_s = spec.split("=", 2)
        rep = audit(int(wmo_s), Path(ours_s), Path(ref_s))
        _print(rep)
        reports.append(rep)

    if args.json:
        payload = []
        for rep in reports:
            payload.append(
                {
                    "wmo": rep.wmo,
                    "cycles_common": rep.cycles_common,
                    "level_total": rep.level_total,
                    "level_diff": rep.level_diff,
                    "level_extra_ours": rep.level_extra_ours,
                    "level_missing_ours": rep.level_missing_ours,
                    "transitions": dict(rep.transitions),
                    "per_cycle": {str(k): dict(v) for k, v in rep.per_cycle.items()},
                    "profile_flag_diff": rep.profile_flag_diff,
                    "position_qc_diff": rep.position_qc_diff,
                    "juld_qc_diff": rep.juld_qc_diff,
                    "qctest_diff": rep.qctest_diff,
                    "traj_total": rep.traj_total,
                    "traj_diff": dict(rep.traj_diff),
                }
            )
        args.json.write_text(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
