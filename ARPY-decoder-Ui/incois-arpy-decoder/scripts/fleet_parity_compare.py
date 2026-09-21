#!/usr/bin/env python3
"""Value-level GDAC parity comparator for ARVOR-I fleet products.

Compares one pair of NetCDF files (ours vs GDAC) at three levels:

* **file** — format, dimensions (sizes, unlimited flags, order), global
  attributes, variable inventory/order/dtypes/attributes (incl.
  ``_FillValue``, units, long_name, ...).
* **variable** — element-wise comparison of every comparable variable:
  exact / near / mismatch cells, fill-vs-value asymmetries, max abs and
  rel differences, capped mismatch samples with locations.
* **row alignment** — for products whose rows have event semantics
  (Rtraj: CYCLE_NUMBER + MEASUREMENT_CODE + occurrence; Tech:
  CYCLE_NUMBER + parameter name + occurrence) rows are matched by key
  and every row variable is compared on matched rows, with ours-only /
  GDAC-only keys reported explicitly.

Output is a machine-readable JSON artifact (this is the record of the
comparison; reports summarise it, they do not replace it).

Usage::

    python scripts/fleet_parity_compare.py \
        --product rtraj --ours <ours.nc> --gdac <gdac.nc> --out report.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import netCDF4
import numpy as np

MAX_SAMPLES = 50
NEAR_RTOL = 1e-6  # "near": within float32-scale rounding


def _jdict(o: object) -> object:
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def _attr(ds: netCDF4.Dataset, name: str):
    try:
        v = ds.getncattr(name)
    except AttributeError:
        return None
    if isinstance(v, np.ndarray):
        return [_jdict(x) for x in v.ravel()]
    return _jdict(v)


def _dims(ds: netCDF4.Dataset) -> list[dict]:
    out = []
    for name, dim in ds.dimensions.items():
        out.append({"name": name, "size": dim.size, "unlimited": dim.isunlimited()})
    return out


def _var_attr_diff(vours, vgdac) -> dict:
    diff: dict = {}
    keys = sorted(set(vours.ncattrs()) | set(vgdac.ncattrs()))
    for k in keys:
        a, b = _attr_attr(vours, k), _attr_attr(vgdac, k)
        if a != b:
            diff[k] = [a, b]
    return diff


def _attr_attr(var, name):
    try:
        v = var.getncattr(name)
    except AttributeError:
        return "<absent>"
    if isinstance(v, np.ndarray):
        return [_jdict(x) for x in v.ravel()]
    return _jdict(v)


def _rows(var) -> np.ndarray:
    """2-D view of a char variable: (rows, strlen)."""
    data = var[:]
    if data.ndim == 1:
        data = data.reshape(1, -1)
    return np.ma.filled(data, b" ").astype("S1")


def _scalar(var) -> np.ndarray:
    if np.ma.is_masked(var[:]):
        return np.ma.masked_all(1)
    return np.asarray(var[:]).ravel()[:1].astype("f8")


def _decode_rows(var) -> list[str]:
    m = _rows(var)
    return [b"".join(r).decode("ascii", "replace").rstrip("\x00 ").strip() for r in m]


def _elem_stats(ours: np.ndarray, gdac: np.ndarray, juld: bool = False) -> dict:
    # Cast to float first so integer variables with masked entries can be
    # NaN-filled (int + NaN fill raises).
    o_ma = np.ma.asarray(ours).astype("f8")
    g_ma = np.ma.asarray(gdac).astype("f8")
    # Argo fill convention: masked entries plus the legacy sentinels
    # (99999 / 999999 and friends) all count as "no value".
    of = o_ma.filled(999999.0)
    gf = g_ma.filled(999999.0)
    sentinel = np.abs(of) >= 99999.0
    gsentinel = np.abs(gf) >= 99999.0
    if juld:
        # Coriolis legacy "undated" placeholder: 1999-11-30 (=18230 d).
        sentinel = sentinel | (of == 18230.0)
        gsentinel = gsentinel | (gf == 18230.0)
    omask = np.ma.getmaskarray(o_ma) | ~np.isfinite(of) | sentinel
    gmask = np.ma.getmaskarray(g_ma) | ~np.isfinite(gf) | gsentinel
    o = np.where(omask, np.nan, of)
    g = np.where(gmask, np.nan, gf)
    both_fill = omask & gmask
    ofill_gval = omask & ~gmask
    oval_gfill = ~omask & gmask
    comparable = ~omask & ~gmask
    diff = np.abs(o - g)
    exact = comparable & (diff == 0)
    near_tol = 1.0 / 86400.0 if juld else NEAR_RTOL * np.maximum(np.abs(g), 1e-30)
    near = comparable & ~exact & (diff <= near_tol)
    mismatch = comparable & ~exact & ~near
    with np.errstate(invalid="ignore", divide="ignore"):
        rel = diff / np.maximum(np.abs(g), 1e-30)
    stats = {
        "total_cells": int(ours.size),
        "exact": int(exact.sum()),
        "near": int(near.sum()),
        "mismatch": int(mismatch.sum()),
        "ours_fill_gdac_value": int(ofill_gval.sum()),
        "ours_value_gdac_fill": int(oval_gfill.sum()),
        "both_fill": int(both_fill.sum()),
    }
    if comparable.any():
        stats["max_abs_diff"] = float(np.nanmax(diff[comparable])) if comparable.sum() else 0.0
        if mismatch.any():
            stats["max_rel_diff"] = float(np.nanmax(rel[mismatch]))
        if juld:
            stats["max_diff_seconds"] = float(np.nanmax(diff[comparable]) * 86400.0)
    samples = []
    if mismatch.any():
        idx = np.argwhere(mismatch)[:MAX_SAMPLES]
        for i in idx:
            i = tuple(int(x) for x in i)
            entry = {
                "index": i,
                "ours": float(o[i]),
                "gdac": float(g[i]),
                "abs_diff": float(diff[i]),
            }
            if juld:
                entry["diff_seconds"] = float(diff[i] * 86400.0)
            samples.append(entry)
        stats["mismatch_total"] = int(mismatch.sum())
    if ofill_gval.any():
        idx = np.argwhere(ofill_gval)[:MAX_SAMPLES]
        stats["ours_fill_samples"] = [
            {"index": tuple(int(x) for x in i), "gdac": float(g[tuple(int(x) for x in i)])}
            for i in idx
        ]
    if oval_gfill.any():
        idx = np.argwhere(oval_gfill)[:MAX_SAMPLES]
        stats["gdac_fill_samples"] = [
            {"index": tuple(int(x) for x in i), "ours": float(o[tuple(int(x) for x in i)])}
            for i in idx
        ]
    if samples:
        stats["samples"] = samples
    return stats


def _char_stats(ours: netCDF4.Variable, gdac: netCDF4.Variable) -> dict:
    o_rows, g_rows = _decode_rows(ours), _decode_rows(gdac)
    n = min(len(o_rows), len(g_rows))
    exact = sum(a == b for a, b in zip(o_rows[:n], g_rows[:n], strict=True))
    stats = {
        "total_rows": {"ours": len(o_rows), "gdac": len(g_rows)},
        "compared_rows": n,
        "exact": int(exact),
        "mismatch": int(n - exact),
    }
    if n - exact:
        samples = [
            {"index": i, "ours": o_rows[i], "gdac": g_rows[i]}
            for i in range(n)
            if o_rows[i] != g_rows[i]
        ][:MAX_SAMPLES]
        stats["samples"] = samples
    return stats


def _row_keys(ds: netCDF4.Dataset, product: str, cycle_shift: int = 0) -> list[tuple]:
    """Per-row semantic keys for row-aligned products."""

    def _col(name: str) -> np.ndarray:
        # raw read (mask off): fills stay numeric sentinels, never NaN->int
        ds.set_auto_mask(False)
        return np.asarray(ds[name][:]).ravel()

    if product == "rtraj":
        cyc = _col("CYCLE_NUMBER")
        code = _col("MEASUREMENT_CODE").astype(np.int64)
    elif product == "tech":
        cyc = _col("CYCLE_NUMBER")
        code = _decode_rows(ds["TECHNICAL_PARAMETER_NAME"])
        code = [hash(c) for c in code]  # name string; combined below
        names = _decode_rows(ds["TECHNICAL_PARAMETER_NAME"])
        keys, seen = [], {}
        for c, n in zip(cyc, names, strict=True):
            k = (int(c), n)
            seen[k] = seen.get(k, 0) + 1
            keys.append((k[0], k[1], seen[k]))
        return keys
    else:
        raise ValueError(product)
    keys, seen = [], {}
    for c, m in zip(cyc, code, strict=True):
        k = (int(c) + cycle_shift, int(m))
        seen[k] = seen.get(k, 0) + 1
        keys.append((k[0], k[1], seen[k]))
    return keys


def compare_pair(ours_path: Path, gdac_path: Path, product: str, cycle_shift: int = 0) -> dict:
    report: dict = {"ours": str(ours_path), "gdac": str(gdac_path), "product": product}
    with netCDF4.Dataset(ours_path) as a, netCDF4.Dataset(gdac_path) as b:
        report["file"] = {
            "format_ours": a.data_model,
            "format_gdac": b.data_model,
            "dims_ours": _dims(a),
            "dims_gdac": _dims(b),
            "dims_equal": _dims(a) == _dims(b),
            "var_order_ours": list(a.variables),
            "var_order_gdac": list(b.variables),
            "var_order_equal": list(a.variables) == list(b.variables),
            "global_attr_diff": {
                k: [_attr(a, k), _attr(b, k)]
                for k in sorted(set(a.ncattrs()) | set(b.ncattrs()))
                if _attr(a, k) != _attr(b, k)
            },
        }
        variables: dict = {}
        for name in dict.fromkeys(list(a.variables) + list(b.variables)):
            entry: dict = {}
            if name not in a.variables:
                entry["presence"] = "gdac_only"
                variables[name] = entry
                continue
            if name not in b.variables:
                entry["presence"] = "ours_only"
                va = a[name]
                entry["dtype"] = str(va.dtype)
                entry["shape"] = list(va.shape)
                variables[name] = entry
                continue
            va, vb = a[name], b[name]
            entry["presence"] = "both"
            entry["dtype_ours"], entry["dtype_gdac"] = str(va.dtype), str(vb.dtype)
            entry["shape_ours"], entry["shape_gdac"] = list(va.shape), list(vb.shape)
            entry["attrs_diff"] = _var_attr_diff(va, vb)
            if va.dtype.kind == "S" and va.shape and va.shape[0] > 0:
                entry["char_values"] = _char_stats(va, vb)
            elif va.shape == () or va.shape == (1,):
                oa = _scalar(va)
                ob = _scalar(vb)
                entry["scalar"] = _elem_stats(oa, ob, juld="JULD" in name.upper())
            elif va.shape == vb.shape and va.dtype.kind in "fiu":
                entry["values"] = _elem_stats(va[:], vb[:], juld="JULD" in name.upper())
            elif va.shape != vb.shape:
                entry["shape_mismatch"] = True
            variables[name] = entry
        report["variables"] = variables

        # Row alignment for event-semantics products
        if product in ("rtraj", "tech"):
            try:
                ka, kb = _row_keys(a, product), _row_keys(b, product, cycle_shift)
            except KeyError as exc:
                report["row_alignment"] = {"error": f"missing key variable {exc}"}
                ka = kb = []
            if ka and kb:
                sa, sb = set(ka), set(kb)
                matched = sorted(sa & sb)
                pos_a = {k: i for i, k in enumerate(ka)}
                pos_b = {k: i for i, k in enumerate(kb)}
                align = {
                    "mode": "cycle+code+occurrence",
                    "rows_ours": len(ka),
                    "rows_gdac": len(kb),
                    "matched": len(matched),
                    "ours_only": len(sa - sb),
                    "gdac_only": len(sb - sa),
                    "ours_only_keys": [list(k) for k in sorted(sa - sb)][:200],
                    "gdac_only_keys": [list(k) for k in sorted(sb - sa)][:200],
                }
                row_stats: dict = {}
                ia = np.array([pos_a[k] for k in matched])
                ib = np.array([pos_b[k] for k in matched])
                row_dim = a["CYCLE_NUMBER"].dimensions[0]  # N_MEASUREMENT
                for name, va in a.variables.items():
                    if name not in b.variables:
                        continue
                    vb = b[name]
                    if not va.shape or va.shape[0] != len(ka) or vb.shape[0] != len(kb):
                        continue
                    if va.dimensions[:1] != (row_dim,) or vb.dimensions[:1] != (row_dim,):
                        continue
                    if va.dtype.kind in "fiu":
                        row_stats[name] = _elem_stats(
                            va[:][ia], vb[:][ib], juld="JULD" in name.upper()
                        )
                    elif va.dtype.kind == "S":
                        row_stats[name] = _sum_char(va[:][ia], vb[:][ib])
                align["row_variables"] = row_stats
                report["row_alignment"] = align
    return report


def _sum_char(ours: np.ndarray, gdac: np.ndarray) -> dict:
    o = np.ma.filled(ours, b" ").astype("S1")
    g = np.ma.filled(gdac, b" ").astype("S1")
    if o.shape != g.shape:
        return {"shape_mismatch": [list(o.shape), list(g.shape)]}
    eq = o == g
    per_row = eq.all(axis=tuple(range(1, eq.ndim)))
    stats = {
        "total_rows": len(per_row),
        "exact": int(per_row.sum()),
        "mismatch": int((~per_row).sum()),
    }
    if (~per_row).any():
        idx = np.argwhere(~per_row)[:MAX_SAMPLES]
        stats["samples"] = []
        for i in idx:
            i = int(i[0])
            stats["samples"].append(
                {
                    "row": i,
                    "ours": b"".join(o[i].ravel()).decode("ascii", "replace"),
                    "gdac": b"".join(g[i].ravel()).decode("ascii", "replace"),
                }
            )
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--product", required=True, choices=("rtraj", "tech", "meta", "mono"))
    ap.add_argument("--ours", type=Path, required=True)
    ap.add_argument("--gdac", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument(
        "--cycle-shift",
        type=int,
        default=0,
        help="gdac_cycle = our_cycle + shift (ARVOR-I Rtraj/Tech: 1)",
    )
    args = ap.parse_args()
    report = compare_pair(args.ours, args.gdac, args.product, args.cycle_shift)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, default=str))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
