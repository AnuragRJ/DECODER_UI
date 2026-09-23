#!/usr/bin/env python3
"""Append the four APF11-Bio floats to the three existing metadata tables.

Append-only by construction: existing rows and the header are read, never
rewritten, and the new rows are written at the end. The three existing CSV
schemas are not altered.

The APF11 source tables are TAB-delimited with placeholder headers
(``column_1`` …) and are two concatenated batches -- the header row repeats
mid-file. Positional alignment against the workspace schema was verified
column-by-column before this script was written:

    meta.csv          APF11 [0..29] -> WS [0..29]; APF11 omits the trailing
                      empty "end mission date" so WS [30] is filled blank and
                      WS [31] takes the APF11 ``endrow`` sentinel.
    calib.csv         APF11 [0..32] -> WS [0..32] exactly (33/33).
    config-params.csv APF11 [0..33] -> WS [0..33] exactly; APF11 [34],[35] are
                      extra trailing empties and are dropped.

No value is invented. Every field comes from the supplied APF11 metadata.

Usage:
    python3 apf11_append_metadata.py --apf11-meta <dir> --ws-meta <dir> [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
from pathlib import Path

#: (apf11 file, workspace file, delimiter of the APF11 source)
TABLES = [
    ("meta.csv", "meta.csv"),
    ("calib.csv", "calib.csv"),
    ("config-params.csv", "config_params.csv"),
]

#: APF11 source rows are identified by their leading sentinel.
SENTINEL = {"meta.csv": "Column1", "calib.csv": "11111",
            "config-params.csv": "column1"}

#: WMOs to append, in the order the user specified.
TARGET_WMO = ["2902275", "2902274", "2902296", "2902298"]

#: APF11 column index holding the WMO in each source table.
WMO_COL = {"meta.csv": 6, "calib.csv": 1, "config-params.csv": 2}

#: How many APF11 columns map onto the workspace schema, per table.
MAP_LEN = {"meta.csv": 30, "calib.csv": 33, "config-params.csv": 34}


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def load_source(path: Path, sentinel: str) -> list[list[str]]:
    """Read the APF11 table, skipping the repeated header rows mid-file."""
    with open(path, newline="", errors="replace") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    return [r for r in rows if r and r[0].strip() == sentinel]


def map_row(src: list[str], table: str, ws_width: int) -> list[str]:
    """Positionally map an APF11 row onto the workspace schema width."""
    n = MAP_LEN[table]
    out = list(src[:n])
    out += [""] * (n - len(out))
    if table == "meta.csv":
        # APF11 omits WS[30] "end mission date"; its sentinel is WS[31].
        tail = src[n] if len(src) > n else "endrow"
        out.append("")            # WS[30] end mission date
        out.append(tail or "endrow")  # WS[31] End Mark
    else:
        out += [""] * (ws_width - len(out))
    return out[:ws_width]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apf11-meta", required=True, type=Path)
    ap.add_argument("--ws-meta", required=True, type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    for src_name, dst_name in TABLES:
        src = args.apf11_meta / src_name
        dst = args.ws_meta / dst_name
        if not src.is_file() or not dst.is_file():
            raise SystemExit(f"missing {src} or {dst}")

        before = md5(dst)
        with open(dst, newline="", errors="replace") as f:
            text = f.read()
        nl = "\r\n" if "\r\n" in text.split("\n")[0] else "\n"
        rows = list(csv.reader(text.splitlines(), delimiter=","))
        width = len(rows[0])
        existing = [r for r in rows[1:] if r]
        have = {r[WMO_COL[src_name]] for r in existing
                if len(r) > WMO_COL[src_name]}

        candidates = load_source(src, SENTINEL[src_name])
        picked = []
        for wmo in TARGET_WMO:
            hit = [r for r in candidates
                   if len(r) > WMO_COL[src_name]
                   and r[WMO_COL[src_name]].strip() == wmo]
            if not hit:
                print(f"  !! {src_name}: no APF11 row for WMO {wmo}")
                continue
            picked.append(map_row(hit[0], src_name, width))

        print(f"{dst_name}: {len(existing)} rows, width {width}; "
              f"appending {len(picked)}")
        for wmo, r in zip([w for w in TARGET_WMO
                           if any(c[WMO_COL[src_name]] == w for c in candidates)],
                          picked):
            print(f"   + WMO {wmo}  ({len(r)} fields)")

        if args.dry_run:
            continue

        shutil.copyfile(dst, dst.with_suffix(dst.suffix + ".bak"))
        with open(dst, "a", newline="") as f:
            w = csv.writer(f, lineterminator=nl)
            for r in picked:
                w.writerow(r)

        after = md5(dst)
        # Re-read and prove the original rows survived untouched.
        with open(dst, newline="", errors="replace") as f:
            check = [r for r in csv.reader(f, delimiter=",") if r]
        assert check[0] == rows[0], "header changed!"
        assert check[1:1 + len(existing)] == [r for r in rows[1:] if r], \
            "existing rows changed!"
        print(f"   verified: header + {len(existing)} original rows intact; "
              f"now {len(check) - 1} rows")
        print(f"   md5 {before[:8]} -> {after[:8]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
