#!/usr/bin/env python3
"""Value-level comparison of generated R*.nc against GDAC references.

The Phase 5B parity gate, kept as a permanent script so the
mono-profile result can be re-verified after any shared refactor
(it was previously an ad-hoc scratch file).
"""

from __future__ import annotations

import argparse
import collections
from pathlib import Path

import netCDF4
import numpy as np


def _pairs(python_root: Path, reference_root: Path) -> list[tuple[str, Path, Path, str]]:
    out = []
    for py in sorted(python_root.glob("*/profiles/R*.nc")):
        wmo = py.parent.parent.name
        cycle = py.stem.rsplit("_", 1)[1]
        for prefix in ("R", "D"):
            ref = reference_root / wmo / "profiles" / f"{prefix}{wmo}_{cycle}.nc"
            if ref.exists():
                out.append((wmo, py, ref, prefix))
                break
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--python-nc-root", type=Path, default=Path("phase4_outputs/apex_argos_nc/nc"))
    ap.add_argument(
        "--reference-root", type=Path, default=Path("phase5_reference/gdac_reference_dataset")
    )
    args = ap.parse_args()

    pairs = _pairs(args.python_nc_root, args.reference_root)
    r_pairs = [p for p in pairs if p[3] == "R"]
    print(f"pairs: {len(pairs)} (R-references: {len(r_pairs)})")

    gattr: collections.defaultdict[str, set[str]] = collections.defaultdict(set)
    dtypes: collections.defaultdict[str, set[str]] = collections.defaultdict(set)
    attrs: collections.defaultdict[str, set[str]] = collections.defaultdict(set)
    for _wmo, py, ref, _p in r_pairs:
        with netCDF4.Dataset(py) as a, netCDF4.Dataset(ref) as b:
            for k in sorted(set(b.ncattrs()) - set(a.ncattrs())):
                gattr["missing_in_py"].add(k)
            for k in sorted(set(a.ncattrs()) - set(b.ncattrs())):
                gattr["extra_in_py"].add(k)
            for k in sorted(set(a.ncattrs()) & set(b.ncattrs())):
                if str(a.getncattr(k)) != str(b.getncattr(k)):
                    gattr[f"differs:{k}"].add("*")
            for name in sorted(set(a.variables) & set(b.variables)):
                x, y = a.variables[name], b.variables[name]
                if x.dtype != y.dtype:
                    dtypes[name].add(f"{x.dtype} vs {y.dtype}")
                ka, kb = set(x.ncattrs()), set(y.ncattrs())
                for k in sorted(kb - ka):
                    attrs[name].add(f"-{k}")
                for k in sorted(ka - kb):
                    attrs[name].add(f"+{k}")
                for k in sorted(ka & kb):
                    u, v = x.getncattr(k), y.getncattr(k)
                    if isinstance(u, (float, np.floating)) and isinstance(v, (float, np.floating)):
                        if not np.isclose(float(u), float(v)):
                            attrs[name].add(f"~{k}")
                    elif str(u) != str(v):
                        attrs[name].add(f"~{k}")

    print("\nglobal attribute differences:")
    for k in sorted(gattr):
        print(f"  {k}: {sorted(gattr[k])[:6]}")
    print(f"\nvariable dtype differences: {len(dtypes)}")
    for name in sorted(dtypes):
        print(f"  {name}: {sorted(dtypes[name])}")
    print(f"variable attribute differences: {len(attrs)}")
    for name in sorted(attrs):
        print(f"  {name}: {sorted(attrs[name])}")

    total = equal = 0
    for _wmo, py, ref, _p in pairs:
        with netCDF4.Dataset(py) as a, netCDF4.Dataset(ref) as b:
            for param in ("PRES", "TEMP", "PSAL"):
                xa = np.ma.filled(a.variables[param][:], np.nan).ravel()
                xb = np.ma.filled(b.variables[param][:], np.nan).ravel()
                n = min(len(xa), len(xb))
                idx = [i for i in range(n) if np.isfinite(xb[i])]
                total += len(idx)
                equal += sum(1 for i in idx if abs(xa[i] - xb[i]) < 1e-6)
    print(f"\nshared science levels bit-identical: {equal}/{total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
