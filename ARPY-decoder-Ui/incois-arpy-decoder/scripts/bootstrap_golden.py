#!/usr/bin/env python3
"""Bootstrap a ``tests/golden/expected/`` tree from the *Python* null decoder.

During Phase 0/1 we do not yet have a populated MATLAB golden set for the
file-oracle path. This script runs the Python NullDecoder (driven by the
CSV registry) against the demo WMOs and writes the resulting NetCDF/XML
into ``tests/golden/expected/``. As soon as we capture MATLAB reference
outputs for these floats (Phase 1's structural-parity gate), this
directory is replaced / augmented with those MATLAB outputs and the
comparator tests will then compare Python vs MATLAB rather than Python vs
Python. Until then, the generated golden is used to lock in structural
regressions (dimension/variable/attribute shape) of the null pipeline.

Usage::

    python scripts/bootstrap_golden.py
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from argo_decoder.config import DecoderConfig  # noqa: E402
from argo_decoder.pipeline.runner import run_pipeline  # noqa: E402

DEMO = (
    REPO_ROOT.parent / "Coriolis-data-processing-chain-for-Argo-floats-container" / "decArgo_demo"
)


def bootstrap(out_dir: Path, wmos: list[int]) -> None:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    nc_root = out_dir / "nc"
    xml_root = out_dir / "xml"
    nc_root.mkdir(parents=True, exist_ok=True)
    xml_root.mkdir(parents=True, exist_ok=True)

    cfg = DecoderConfig()
    cfg.metadata.backend = "csv"  # type: ignore[assignment]
    cfg.metadata.registry_path = REPO_ROOT / "config" / "registry.csv"
    cfg.paths.rsync_data_dir = DEMO / "input" / "archive" / "cycle"
    cfg.paths.rsync_log_dir = DEMO / "input" / "rsync_list"
    cfg.paths.xml_dir = xml_root
    cfg.paths.nc_dir = nc_root
    for d in (
        cfg.paths.nc_dir,
        cfg.paths.xml_dir,
        cfg.paths.log_dir,
        cfg.paths.csv_dir,
        cfg.paths.iridium_decoded_dir,
        cfg.paths.temporary_dir,
    ):
        d.mkdir(parents=True, exist_ok=True)

    for wmo in wmos:
        result = run_pipeline(
            config=cfg,
            wmo=wmo,
            xml_filename=f"co041404_golden_{wmo}.xml",
            use_null_decoder=True,
        )
        print(
            f"WMO {wmo}: status={result.status} n_cycles={result.n_cycles} n_files={result.n_files}"
        )
        assert result.status == "ok"
        assert result.xml_report is not None and result.xml_report.exists()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "tests" / "golden" / "expected",
    )
    ap.add_argument(
        "--wmo",
        type=int,
        action="append",
        default=[6902892],
        help="WMO(s) to materialize (repeatable; defaults to 6902892 only).",
    )
    args = ap.parse_args()
    bootstrap(args.out, args.wmo)
    print(f"wrote golden tree to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
