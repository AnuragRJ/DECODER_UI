#!/usr/bin/env python3
"""APF11-Bio raw-file extraction harness.

Establishes the APF11 raw -> CSV/TXT conversion path. Four log families occur in
the supplied corpus, and they are NOT all binary:

    science_log.bin.gz    BINARY  length-prefixed records -> apf11dec_py3.py
    vitals_log.bin.gz     BINARY  length-prefixed records -> apf11dec_py3.py
    system_log.txt.gz     TEXT    `YYYYMMDDTHHMMSS|level|key|value`
    production_log.txt.gz TEXT    `YYYYMMDDTHHMMSS|level|text`
    suna_log.txt.gz       TEXT    Satlantic SUNA CSV (`0xNNNN,A,mm/dd/yyyy ...`)

The two binary families are handed to the vendor decoder unmodified in logic;
this script only decompresses, stages and routes. Nothing here re-implements
record parsing.

Source .gz files are never modified. Intermediates go to a separate output root.

Usage:
    python3 apf11_extract.py --src <raw-files dir> --out <output dir>
                             [--floats f8499,f8671] [--limit N]
"""

from __future__ import annotations

import argparse
import csv
import gzip
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECODER = HERE / "apf11dec_py3.py"

#: log family -> (is_binary, output extension)
FAMILIES = {
    "science_log": (True, "csv"),
    "vitals_log": (True, "csv"),
    "system_log": (False, "txt"),
    "production_log": (False, "txt"),
    "suna_log": (False, "txt"),
    #: Already-decoded files shipped alongside the .gz corpus (f8673). Text;
    #: copied through untouched rather than re-parsed.
    "science_log_predecoded": (False, "csv"),
    "vitals_log_predecoded": (False, "csv"),
    "system_log_predecoded": (False, "txt"),
}

#: SUNA "SATNDL" extended CSV field order. Derived from the Satlantic SUNA-V2
#: extended-data output as observed in this corpus, then *verified* against the
#: float's own binary records: field 20 (nitrate) matches science_log record ID
#: 100 (LOG_SCIENCE_SUNA / 'NO3') exactly on every compared sample, and field 10
#: (thermistor temperature) tracks the CTD_PT temperature series. Field 24 is
#: the 256-channel hex spectrum (512 hex chars); it is kept in a sidecar file
#: rather than inline, because 512-char cells make the CSV unusable.
SUNA_FIELDS = [
    "frame_header", "frame_type", "date_utc", "date_time_fraction",
    "nitrogen_in_nitrate_umol_per_l", "first_wavelength_nm",
    "average_pixel_value_counts", "integration_time_ms",
    "sample_record_counter", "spectrum_average_counts",
    "thermistor_temperature_degC", "lamp_temperature_degC",
    "cumulative_lamp_on_time_min", "v_internal_V", "v_main_V",
    "v_lamp_V", "relative_humidity_percent", "main_current_mA",
    "lamp_current_mA", "fit_error", "nitrate_umol_per_l",
    "second_fit_nitrite_umol_per_l", "spectrometer_voltage_V",
    "ground_offset_counts", "spectrum_hex", "checksum",
]
#: Field 24 is the UV absorbance spectrum as packed hex. In this corpus it is
#: 164 hex chars = **82 channels** on all 7037 records (verified), not the 256
#: of a full-frame SATNDL. The channel count is emitted per row rather than
#: assumed, so a different instrument frame width needs no code change.


def detect_family(name: str) -> str | None:
    """Identify the log family from the filename.

    Binary families are only binary while they still carry ``.bin``: the corpus
    mixes a handful of already-decoded ``*.science_log.csv`` /
    ``*.vitals_log.csv`` / ``*.system_log.txt`` files (present for f8673), and
    those are plain text that must not be fed to the record parser.
    """
    for fam, (is_bin, _) in FAMILIES.items():
        if f".{fam}." not in name:
            continue
        if is_bin and ".bin" not in name:
            return fam + "_predecoded"
        return fam
    return None


def stage_gz(src: Path, workdir: Path) -> Path:
    """Decompress one .gz into workdir without touching the source."""
    out = workdir / src.name[:-3] if src.name.endswith(".gz") else workdir / src.name
    with gzip.open(src, "rb") as fin, open(out, "wb") as fout:
        shutil.copyfileobj(fin, fout)
    return out


def run_vendor_decoder(bin_path: Path) -> Path:
    """Invoke the ported vendor decoder; it writes <stem>.csv beside the input."""
    expected = bin_path.with_suffix(".csv")
    if expected.exists():
        expected.unlink()
    proc = subprocess.run(
        [sys.executable, str(DECODER), str(bin_path)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"decoder failed on {bin_path.name}: {proc.stderr[:300]}")
    # The vendor decoder reports unparseable records on stdout, not stderr.
    if not expected.exists():
        raise RuntimeError(f"decoder produced no output for {bin_path.name}")
    if proc.stdout.strip():
        expected.with_suffix(".stderr.txt").write_text(proc.stdout)
    return expected


def split_suna(txt_path: Path, out_csv: Path, out_spec: Path) -> tuple[int, int]:
    """Convert a SUNA text log to a tidy CSV plus a spectrum sidecar."""
    rows, specs = 0, 0
    with open(txt_path, "rt", errors="replace") as fin, \
            open(out_csv, "w", newline="") as fcsv, \
            open(out_spec, "w", newline="") as fspec:
        w = csv.writer(fcsv)
        w.writerow(SUNA_FIELDS[:-2] + ["n_spectrum_channels"])
        ws = csv.writer(fspec)
        ws.writerow(["frame_header", "date_utc", "n_channels", "spectrum_hex"])
        for line in fin:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            padded = parts + [""] * (len(SUNA_FIELDS) - len(parts))
            padded = padded[:len(SUNA_FIELDS)]
            spec = padded[24]
            nch = len(spec) // 2 if spec else 0
            w.writerow(padded[:24] + [nch])
            rows += 1
            if spec:
                ws.writerow([padded[0], padded[2], nch, spec])
                specs += 1
    return rows, specs


def pipe_text(txt_path: Path, out_path: Path) -> int:
    """system_log / production_log are already delimited text; copy as UTF-8."""
    n = 0
    with open(txt_path, "rt", errors="replace") as fin, \
            open(out_path, "w") as fout:
        for line in fin:
            fout.write(line if line.endswith("\n") else line + "\n")
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--floats", default="", help="comma list, e.g. f8499,f8671")
    ap.add_argument("--limit", type=int, default=0, help="cap files per family")
    args = ap.parse_args()

    floats = [f.strip() for f in args.floats.split(",") if f.strip()]
    if not floats:
        floats = sorted(p.name for p in args.src.iterdir() if p.is_dir())

    summary: dict[str, dict[str, int]] = {}
    problems: list[str] = []

    for fl in floats:
        fdir = args.src / fl
        if not fdir.is_dir():
            problems.append(f"{fl}: no such directory")
            continue
        per: dict[str, int] = Counter()
        seen: dict[str, int] = Counter()

        for src in sorted(fdir.iterdir()):
            fam = detect_family(src.name)
            if fam is None:
                continue
            if args.limit and seen[fam] >= args.limit:
                continue
            seen[fam] += 1
            is_bin, _ = FAMILIES[fam]
            outdir = args.out / fl / fam
            outdir.mkdir(parents=True, exist_ok=True)

            try:
                with tempfile.TemporaryDirectory() as td:
                    work = Path(td)
                    if src.name.endswith(".gz"):
                        staged = stage_gz(src, work)
                    else:
                        # Already-uncompressed input. Copy it into the scratch
                        # dir rather than aliasing the source file: the decoder
                        # writes <stem>.csv beside its input and we unlink that
                        # path first, which would otherwise delete a source file
                        # that happens to already be a .csv.
                        staged = work / src.name
                        shutil.copyfile(src, staged)

                    if is_bin:
                        csvp = run_vendor_decoder(staged)
                        dest = outdir / (src.name.replace(".gz", "") + ".csv")
                        shutil.copyfile(csvp, dest)
                        with open(dest) as f:
                            per[fam] += sum(1 for _ in f)
                    elif fam == "suna_log":
                        rows, specs = split_suna(
                            staged,
                            outdir / (src.name.replace(".gz", "") + ".csv"),
                            outdir / (src.name.replace(".gz", "") + ".spectrum.csv"),
                        )
                        per[fam] += rows
                        per["suna_spectra"] += specs
                    else:
                        per[fam] += pipe_text(
                            staged,
                            outdir / src.name.replace(".gz", ""),
                        )
                per[fam + "_files"] += 1
            except Exception as exc:
                problems.append(f"{fl}/{src.name}: {type(exc).__name__}: {exc}")

        summary[fl] = dict(per)

    (args.out / "extraction_summary.json").write_text(
        __import__("json").dumps(
            {"floats": summary, "problems": problems}, indent=1),
        encoding="utf-8",
    )
    for fl, per in summary.items():
        files = sum(v for k, v in per.items() if k.endswith("_files"))
        rows = sum(v for k, v in per.items() if not k.endswith("_files")
                   and k != "suna_spectra")
        print(f"{fl}: {files} files -> {rows} rows")
    if problems:
        print(f"\n{len(problems)} problem(s):")
        for p in problems[:15]:
            print("  ", p)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
