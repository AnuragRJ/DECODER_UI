"""Metadata management CLI subcommands.

Exposed as ``argo-decoder metadata ...``:

* ``argo-decoder metadata validate <registry.csv>`` — run
  :func:`validate_registry` and print a structured report.
* ``argo-decoder metadata materialize <registry> --out <dir>`` —
  materialise a full ``json_float_info/`` + ``json_float_meta_*/`` tree
  from the registry (useful for debugging and for feeding MATLAB during
  transition). ``<registry>`` is either the legacy ``registry.csv`` or
  the four-CSV metadata directory.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from argo_decoder.metadata import builder
from argo_decoder.metadata.csv_loader import CsvLoader, load_registry_csv
from argo_decoder.metadata.multi_csv_loader import MultiCsvLoader
from argo_decoder.metadata.validators import validate_registry
from argo_decoder.util.logging import configure_logging, get_logger

app = typer.Typer(
    add_completion=False,
    help="Central metadata registry (CSV) validation and materialisation.",
)


@app.callback()
def _cb(
    ctx: typer.Context,
    log_level: str = typer.Option("INFO", "--log-level", "-l"),
    json_logs: bool = typer.Option(False, "--json-logs"),
) -> None:
    configure_logging(log_level, json_output=json_logs)


@app.command("validate")
def validate_cmd(
    registry: Path = typer.Argument(..., exists=True, dir_okay=False, help="Path to registry.csv"),
    report_out: Path | None = typer.Option(
        None, "--report", help="Write a JSON report to this path"
    ),
    decoder_table_path: Path | None = typer.Option(
        None,
        "--decoder-table",
        exists=True,
        dir_okay=False,
        help="Path to decoder_table.yaml (defaults to the bundled table).",
    ),
    no_decoder_table: bool = typer.Option(
        False,
        "--no-decoder-table",
        help="Skip decoder-table referential-integrity checks.",
    ),
    strict: bool = typer.Option(
        False,
        "--strict/--no-strict",
        help="Exit non-zero on warnings as well as errors (default: errors only).",
    ),
) -> None:
    """Validate a registry CSV and print a human-readable report."""
    log = get_logger()
    rows = load_registry_csv(registry, strict=False)
    # Lazy import avoids a circular dep at module-import time (metadata <-> config).
    if no_decoder_table:
        dtable = None
    else:
        from argo_decoder.config import get_decoder_table as _get_table
        from argo_decoder.config import load_decoder_table as _load_table

        dtable = _load_table(decoder_table_path) if decoder_table_path else _get_table()
    report = validate_registry(rows, decoder_table=dtable)
    for issue in report.issues:
        lvl = log.error if issue.level == "error" else log.warning
        lvl(
            "validation_issue",
            code=issue.code,
            wmo=issue.wmo,
            message=issue.message,
        )
    log.info("validation_summary", summary=report.summary(), n_rows=len(rows))
    if report_out:
        report_out.parent.mkdir(parents=True, exist_ok=True)
        report_out.write_text(
            json.dumps(
                {
                    "ok": report.ok and (not strict or report.n_warnings == 0),
                    "n_rows": len(rows),
                    "n_errors": report.n_errors,
                    "n_warnings": report.n_warnings,
                    "issues": [
                        {
                            "level": i.level,
                            "code": i.code,
                            "message": i.message,
                            "wmo": i.wmo,
                        }
                        for i in report.issues
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    if not report.ok or (strict and report.n_warnings > 0):
        raise typer.Exit(code=1)


@app.command("materialize")
def materialize_cmd(
    registry: Path = typer.Argument(
        ...,
        exists=True,
        help="Path to registry.csv, or to the four-CSV metadata directory.",
    ),
    out: Path = typer.Option(
        ..., "--out", "-o", file_okay=False, help="Root directory to write JSON into"
    ),
    wmo: list[int] = typer.Option(None, "--wmo", help="Only materialise this WMO (repeatable)"),
    meta_subdir: str = typer.Option(
        "json_float_meta_ir_sbd",
        "--meta-subdir",
        help="Subdirectory name for *_meta.json files (Iridium SBD by default).",
    ),
    flat: bool = typer.Option(
        False,
        "--flat",
        help="Write both JSON families straight into --out, with no subdirectories.",
    ),
) -> None:
    """Materialise a ``decArgo_config_floats/`` tree from the metadata.

    Creates ``<out>/json_float_info/<wmo>_<ptt>_info.json`` and
    ``<out>/<meta_subdir>/<wmo>_meta.json`` for each row in the registry
    (or only for the WMOs passed via repeated ``--wmo``).

    ``registry`` accepts either backend, chosen the same way the decode
    entry points choose it: a **file** is the legacy single
    ``registry.csv``, a **directory** is the four-CSV set
    (``meta.csv`` / ``sensor-info.csv`` / ``calib.csv`` /
    ``config_params.csv``). Only the four-CSV backend carries the
    pre-deployment calibration, so materialising from the legacy CSV
    writes ``"n/a"`` into ``PREDEPLOYMENT_CALIB_*`` and the resulting
    ``_meta.nc`` is rejected by the Argo file checker with six "Empty"
    errors.

    ``--flat`` writes both families directly into ``--out``, which is the
    layout ``decode-float --info-dir/--meta-dir`` expects when both point
    at the same directory.
    """
    log = get_logger()
    out_info = out if flat else out / "json_float_info"
    out_meta = out if flat else out / meta_subdir
    out_info.mkdir(parents=True, exist_ok=True)
    out_meta.mkdir(parents=True, exist_ok=True)

    loader: CsvLoader | MultiCsvLoader = (
        MultiCsvLoader(registry) if registry.is_dir() else CsvLoader(registry, strict=False)
    )
    target = set(wmo) if wmo else None
    n_info = 0
    n_meta = 0
    for row in loader.iter_floats(target):
        i_path, m_path = builder.materialize(row, out_info)
        # Builder writes meta to out_info's parent; move meta to out_meta.
        # Simpler: re-target meta by writing explicitly.
        meta_obj = builder.build_meta(row)
        m_path = builder.write_meta_json(meta_obj, out_meta)
        n_info += 1
        n_meta += 1
        log.debug("materialised", wmo=row.wmo, info=str(i_path), meta=str(m_path))
    log.info(
        "materialize_done",
        n_info=n_info,
        n_meta=n_meta,
        out_info=str(out_info),
        out_meta=str(out_meta),
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(app())
