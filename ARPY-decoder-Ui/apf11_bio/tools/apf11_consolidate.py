#!/usr/bin/env python3
"""Consolidate per-file APF11 intermediates into compact per-float tables.

The full per-file decode is ~83 MB, too large to keep in the workspace. This
builds a small, analysis-ready view -- one file per (float, log family, record
type) -- from the same extraction, so the investigation has something to read
without holding every intermediate.

Record-level provenance is preserved: every row keeps its source filename, so
cycle attribution can still be traced back to the original .gz.

Usage:
    python3 apf11_consolidate.py --decoded <decoded dir> --out <out dir>
"""

from __future__ import annotations

import argparse
import csv
import gzip
from collections import Counter, defaultdict
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--decoded", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    report: dict[str, dict] = {}

    for fdir in sorted(p for p in args.decoded.iterdir() if p.is_dir()):
        fl = fdir.name
        stats: dict[str, dict] = {}

        # --- science / vitals: vendor-decoded binary, keyed by record type ---
        for fam in ("science_log", "vitals_log", "science_log_predecoded",
                    "vitals_log_predecoded"):
            famdir = fdir / fam
            if not famdir.is_dir():
                continue
            by_type: dict[str, list[str]] = defaultdict(list)
            nfiles = 0
            for f in sorted(famdir.iterdir()):
                if not f.is_file():
                    continue
                nfiles += 1
                with open(f, errors="replace") as fh:
                    for line in fh:
                        line = line.rstrip("\n")
                        if not line:
                            continue
                        rtype = line.split(",", 1)[0]
                        by_type[rtype].append(f"{f.stem.split('.')[1]},{line}")
            for rtype, rows in sorted(by_type.items()):
                out = args.out / f"{fl}_{fam.replace('_predecoded','')}_{rtype}.csv"
                # ``science_log`` and ``science_log_predecoded`` (one float ships
                # already-decoded .csv siblings alongside its .gz files) map to
                # the SAME output name. Writing mode "w" here silently discarded
                # whichever family was processed first -- 227818 vendor-decoded
                # rows lost to a 1978-row predecoded file on one float. Append
                # instead, and only emit the header on creation.
                exists = out.exists()
                with open(out, "a") as fh:
                    if not exists:
                        fh.write("src_cycle," + ",".join(
                            ["record_type", "timestamp", "payload"]) + "\n")
                    for r in rows:
                        parts = r.split(",", 3)
                        fh.write(",".join(parts[:3]) + "," +
                                 (parts[3] if len(parts) > 3 else "") + "\n")
                key = f"{fam}:{rtype}"
                stats[key] = {"files": nfiles, "rows": len(rows)}

        # --- suna: already one tidy CSV per file; concatenate ---
        sundir = fdir / "suna_log"
        if sundir.is_dir():
            rows = []
            header = None
            nfiles = 0
            for f in sorted(sundir.iterdir()):
                if not f.name.endswith(".csv") or f.name.endswith(".spectrum.csv"):
                    continue
                nfiles += 1
                with open(f, newline="", errors="replace") as fh:
                    rd = csv.reader(fh)
                    h = next(rd, None)
                    if header is None:
                        header = h
                    cyc = f.stem.split(".")[1] if len(f.stem.split(".")) > 1 else ""
                    for r in rd:
                        rows.append([cyc] + r)
            if header:
                out = args.out / f"{fl}_suna_log.csv"
                with open(out, "w", newline="") as fh:
                    w = csv.writer(fh)
                    w.writerow(["src_cycle"] + header)
                    w.writerows(rows)
                stats["suna_log"] = {"files": nfiles, "rows": len(rows)}

        # --- system / production: keyed by message key ---
        for fam in ("system_log", "production_log", "system_log_predecoded"):
            famdir = fdir / fam
            if not famdir.is_dir():
                continue
            by_key: dict[str, list[str]] = defaultdict(list)
            nfiles = 0
            nlines = 0
            for f in sorted(famdir.iterdir()):
                if not f.is_file():
                    continue
                nfiles += 1
                with open(f, errors="replace") as fh:
                    for line in fh:
                        line = line.rstrip("\r\n")
                        if not line:
                            continue
                        nlines += 1
                        parts = line.split("|")
                        key = parts[2] if len(parts) > 2 else "(no-key)"
                        key = key.strip().split()[0] if key.strip() else "(empty)"
                        by_key[key].append(line)
            stats[fam] = {"files": nfiles, "lines": nlines,
                          "distinct_keys": len(by_key)}
            # write the full log keyed, sorted by key for readability
            out = args.out / f"{fl}_{fam.replace('_predecoded','')}_keyed.txt"
            with open(out, "w") as fh:
                for key in sorted(by_key):
                    for line in by_key[key]:
                        fh.write(line + "\n")
            # distinct key inventory
            (args.out / f"{fl}_{fam.replace('_predecoded','')}_keys.txt").write_text(
                "\n".join(f"{len(by_key[k]):8d}  {k}"
                          for k in sorted(by_key, key=lambda x: -len(by_key[x]))),
                encoding="utf-8")

        report[fl] = stats
        total = sum(v.get("rows", v.get("lines", 0)) for v in stats.values())
        print(f"{fl}: {len(stats)} streams, {total} rows/lines")

    import json
    (args.out / "consolidation_report.json").write_text(
        json.dumps(report, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
