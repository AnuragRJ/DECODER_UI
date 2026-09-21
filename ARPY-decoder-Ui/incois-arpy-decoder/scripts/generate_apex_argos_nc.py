#!/usr/bin/env python3
"""Generate NetCDF outputs for supplied Phase 4 WRC/APEX ARGOS raw files.

This is a convenience wrapper around the normal pipeline. It does not bypass
or special-case science decoding; it only builds a CSV-backed ARGOS
``DecoderConfig`` and runs each requested WMO through ``run_pipeline``.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from argo_decoder.config import DecoderConfig  # noqa: E402
from argo_decoder.config.models import TransmissionType  # noqa: E402
from argo_decoder.pipeline.runner import PipelineResult, run_pipeline  # noqa: E402

DEFAULT_WMOS = (2901339, 2902201, 2902222, 2902223)


@dataclass(frozen=True)
class GenerationRecord:
    wmo: int
    status: str
    n_raw_files: int
    n_input_cycles: int
    n_nc_files: int
    nc_checksums: dict[str, str]
    xml_report: str | None
    errors: list[str]


def _config(
    raw_root: Path,
    output_root: Path,
    registry: Path,
    ref_dir: Path | None = None,
) -> DecoderConfig:
    cfg = DecoderConfig()
    cfg.transmission_type = TransmissionType.ARGOS
    # RTQC reference data (GEBCO for TEST004). Resolved exactly as the
    # ``argo-decoder --ref`` flag does, so both entry points run the same
    # tests from the same grid. Left untouched when no directory is given,
    # so a decode without bathymetry behaves as before and TEST004 is
    # simply reported as not run.
    if ref_dir is not None:
        ref_dir = ref_dir.resolve()
        cfg.rtqc.reference_files.gebco_file = ref_dir / "gebco.nc"
        cfg.rtqc.reference_files.woa_file = ref_dir / "woa13_all_n00_01.nc"
        cfg.rtqc.reference_files.chla_correction_file = ref_dir / "SLOPE_RT_2024.txt"
    # A directory selects the four-CSV backend (meta / sensor-info /
    # calib / config_params); a file keeps the single-registry backend.
    cfg.metadata.backend = "csv4" if registry.is_dir() else "csv"  # type: ignore[assignment]
    cfg.metadata.registry_path = registry
    cfg.paths.rsync_data_dir = raw_root
    cfg.paths.rsync_log_dir = raw_root
    cfg.paths.xml_dir = output_root / "xml"
    cfg.paths.nc_dir = output_root / "nc"
    cfg.paths.log_dir = output_root / "log"
    cfg.paths.csv_dir = output_root / "csv"
    cfg.paths.iridium_decoded_dir = output_root / "iridium"
    cfg.paths.temporary_dir = output_root / "tmp"
    for path in (
        cfg.paths.xml_dir,
        cfg.paths.nc_dir,
        cfg.paths.log_dir,
        cfg.paths.csv_dir,
        cfg.paths.iridium_decoded_dir,
        cfg.paths.temporary_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)
    return cfg


def _record(result: PipelineResult) -> GenerationRecord:
    return GenerationRecord(
        wmo=result.wmo,
        status=result.status,
        n_raw_files=result.n_files,
        n_input_cycles=result.n_cycles,
        n_nc_files=len(result.nc_checksums),
        nc_checksums=dict(result.nc_checksums),
        xml_report=str(result.xml_report) if result.xml_report is not None else None,
        errors=list(result.errors),
    )


def generate(
    *,
    raw_root: Path,
    output_root: Path,
    registry: Path,
    wmos: list[int],
    ref_dir: Path | None = None,
) -> list[GenerationRecord]:
    cfg = _config(raw_root, output_root, registry, ref_dir)
    records: list[GenerationRecord] = []
    for wmo in wmos:
        result = run_pipeline(
            config=cfg,
            wmo=wmo,
            xml_filename=f"phase4_argos_{wmo}.xml",
            write_nc=True,
            write_xml=True,
        )
        records.append(_record(result))
    report_path = output_root / "phase4_argos_generation_summary.json"
    report_path.write_text(
        json.dumps([asdict(record) for record in records], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=REPO_ROOT / "phase4_reference" / "raw" / "raw-files",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=REPO_ROOT / "phase4_outputs" / "apex_argos_nc",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=REPO_ROOT / "config" / "registry.csv",
        help="registry.csv file, or a directory holding the four metadata CSVs.",
    )
    parser.add_argument(
        "--ref",
        type=Path,
        default=None,
        dest="ref_dir",
        help=(
            "RTQC reference-data directory holding gebco.nc (enables TEST004, "
            "position on land). Omit to run without bathymetry. The grid is an "
            "external dependency and is never stored in the repository; see "
            "docs/BATHYMETRY_SETUP.md."
        ),
    )
    parser.add_argument("--wmo", type=int, action="append", default=[])
    args = parser.parse_args()
    wmos = args.wmo or list(DEFAULT_WMOS)
    records = generate(
        raw_root=args.raw_root,
        output_root=args.output_root,
        registry=args.registry,
        wmos=wmos,
        ref_dir=args.ref_dir,
    )
    for record in records:
        print(
            f"WMO {record.wmo}: status={record.status} raw_files={record.n_raw_files} "
            f"input_cycles={record.n_input_cycles} nc_files={record.n_nc_files}"
        )
    print(f"wrote outputs under {args.output_root}")
    return 0 if all(record.status == "ok" for record in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
