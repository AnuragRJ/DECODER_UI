"""Typer-based command line interface for the Argo decoder."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from argo_decoder.cli.metadata_cli import app as metadata_app
from argo_decoder.config import DecoderConfig, load_config
from argo_decoder.config.models import PathSet
from argo_decoder.pipeline.dual_run import dual_run, report_to_json
from argo_decoder.pipeline.runner import run_pipeline
from argo_decoder.util.logging import configure_logging, get_logger

app = typer.Typer(add_completion=False, help="Coriolis Argo float decoder (Python)")
app.add_typer(metadata_app, name="metadata", help="Metadata registry validation & materialisation.")


def _looks_like_argos_archive(root: Path) -> bool:
    """True when ``root`` holds ARGOS PTT directories of ``*.txt`` files.

    An ARGOS archive is ``<root>/<ptt>/<ptt>_<date>.txt`` -- one directory
    per transmitter, no ``archive/cycle`` wrapper. Detected structurally
    rather than by name so it cannot be confused with the Iridium layout,
    whose telemetry lives in ``archive/cycle`` and never directly under a
    numeric child of the root.
    """
    if not root.is_dir():
        return False
    return any(
        child.is_dir() and child.name.isdigit() and any(child.glob("*.txt"))
        for child in root.iterdir()
    )


def _resolve_input_layout(input_root: Path) -> tuple[Path, Path]:
    """Map ``--input`` onto ``(rsync_data_dir, rsync_log_dir)``.

    Three layouts are recognised, in order:

    ``<root>/archive/cycle`` + ``<root>/rsync_list``
        The Iridium SBD production tree.
    ``<root>/cycle``
        The demo tree, where ``archive/`` is the supplied ``--input``.
    ``<root>/<ptt>/*.txt``
        An ARGOS archive. It has no ``rsync_list``, so the log directory
        points at the root; discovery walks the tree with ``rglob`` and
        does not read it.

    Falling through to ``archive/cycle`` for an ARGOS tree used to leave
    ``rsync_data_dir`` on a path that does not exist, so discovery found
    nothing and the run still reported success.
    """
    archive_cycle = input_root / "archive" / "cycle"
    if archive_cycle.exists():
        return archive_cycle, input_root / "rsync_list"
    if (input_root / "cycle").exists():
        return input_root / "cycle", input_root.parent / "rsync_list"
    if _looks_like_argos_archive(input_root):
        return input_root, input_root
    # Unrecognised: keep the documented default so the error names the
    # path the user most likely meant to create.
    return archive_cycle, input_root / "rsync_list"


def _apply_path_overrides(
    cfg: DecoderConfig,
    *,
    input_root: Path | None,
    output_root: Path | None,
    config_dir: Path | None,
    meta_info_dir: Path | None,
    meta_dir: Path | None,
    ref_dir: Path | None,
    runtime_dir: Path | None,
    temporary_dir: Path | None,
) -> DecoderConfig:
    """Apply CLI path overrides to a loaded config.

    All overrides are optional and applied independently. ``input_root`` and
    ``output_root`` are the high-level conveniences used in tutorials and on
    Windows; they rewrite the full rsync/rsync_list or output tree under a
    single root. ``meta_info_dir``/``meta_dir``/``ref_dir``/``runtime_dir``/
    ``temporary_dir`` allow fine-grained overrides.
    """
    paths: PathSet = cfg.paths
    if input_root is not None:
        rsync, rsync_list = _resolve_input_layout(input_root.resolve())
        paths.rsync_data_dir = rsync
        paths.rsync_log_dir = rsync_list
    if output_root is not None:
        output_root = output_root.resolve()
        paths.iridium_decoded_dir = output_root / "iridium"
        paths.log_dir = output_root / "log"
        paths.csv_dir = output_root / "csv"
        paths.xml_dir = output_root / "xml"
        paths.nc_dir = output_root / "nc"
        paths.nc_traj_3_1_dir = output_root / "nc"
        paths.nc_traj_3_2_dir = output_root / "nc"
    if config_dir is not None:
        config_dir = config_dir.resolve()
        paths.config_dir = config_dir
        paths.float_info_dir = config_dir / "decArgo_config_floats" / "json_float_info"
        paths.float_meta_dir = config_dir / "decArgo_config_floats" / "json_float_meta_ir_sbd"
        paths.dm_buffer_list_dir = config_dir / "decArgo_config_floats" / "float_dm_buffer_lists"
        paths.tech_label_dir = config_dir / "_techParamNames"
        paths.config_label_dir = config_dir / "_configParamNames"
    if meta_info_dir is not None:
        paths.float_info_dir = meta_info_dir.resolve()
    if meta_dir is not None:
        paths.float_meta_dir = meta_dir.resolve()
    if ref_dir is not None:
        # Ref dir is consumed indirectly via RTQC reference files; update each
        # to the resolved reference root so callers needn't set each file.
        ref_dir = ref_dir.resolve()
        cfg.rtqc.reference_files.gebco_file = ref_dir / "gebco.nc"
        cfg.rtqc.reference_files.woa_file = ref_dir / "woa13_all_n00_01.nc"
        cfg.rtqc.reference_files.chla_correction_file = ref_dir / "SLOPE_RT_2024.txt"
    if temporary_dir is not None:
        paths.temporary_dir = temporary_dir.resolve()
    # runtime_dir is honored by DockerOracle directly (passed through the
    # dual-run CLI) and does not require mutation of the config object here.
    return cfg


@app.callback()
def _main(
    ctx: typer.Context,
    log_level: str = typer.Option("INFO", "--log-level", "-l", help="Log level"),
    json_logs: bool = typer.Option(False, "--json-logs", help="Emit JSON log lines"),
) -> None:
    configure_logging(log_level, json_output=json_logs)


@app.command("decode-float")
def decode_float(
    wmo: int = typer.Argument(..., help="WMO number of the float to decode"),
    config: Path = typer.Option(
        None,
        "--config",
        "-c",
        exists=False,
        help="Path to decoder_conf.json (optional; defaults apply if omitted).",
    ),
    xml_name: str | None = typer.Option(None, "--xml-name", help="XML report filename"),
    null_decoder: bool = typer.Option(
        False, "--null-decoder", help="Use the null (plumbing-only) decoder"
    ),
    input_root: Annotated[
        Path | None,
        typer.Option(
            "--input",
            "-i",
            exists=True,
            file_okay=False,
            help=(
                "Override input root. Accepts an Iridium tree "
                "(archive/cycle + rsync_list) or an ARGOS archive "
                "(one <ptt>/ directory of *.txt per transmitter)."
            ),
        ),
    ] = None,
    output_root: Annotated[
        Path | None,
        typer.Option(
            "--out",
            "-o",
            file_okay=False,
            help="Override output root (creates nc/, xml/, log/, csv/ below it).",
        ),
    ] = None,
    meta_info_dir: Annotated[
        Path | None,
        typer.Option(
            "--info-dir",
            exists=True,
            file_okay=False,
            help="Override directory of *_info.json files.",
        ),
    ] = None,
    meta_dir: Annotated[
        Path | None,
        typer.Option(
            "--meta-dir",
            exists=True,
            file_okay=False,
            help="Override directory of *_meta.json files.",
        ),
    ] = None,
    ref_dir: Annotated[
        Path | None,
        typer.Option(
            "--ref",
            exists=True,
            file_okay=False,
            help="Override RTQC reference-data directory.",
        ),
    ] = None,
    temporary_dir: Annotated[
        Path | None,
        typer.Option(
            "--tmp",
            file_okay=False,
            help="Override temporary directory (defaults to OS temp).",
        ),
    ] = None,
    metadata_backend: Annotated[
        str,
        typer.Option(
            "--metadata-backend",
            help="Metadata backend: 'json' (default) or 'csv'.",
        ),
    ] = "json",
    registry: Annotated[
        Path | None,
        typer.Option(
            "--registry",
            exists=True,
            help=(
                "Path to registry.csv (backend csv), or to the four-CSV metadata "
                "directory (backend csv4)."
            ),
        ),
    ] = None,
    apply_rtqc: Annotated[
        bool,
        typer.Option(
            "--rtqc/--no-rtqc",
            help=(
                "Run the real-time QC stage on mono profiles. Without it the "
                "published <PARAM>_QC stay '0' (no QC performed) and "
                "PROFILE_<PARAM>_QC stay blank, which the GDAC FileChecker "
                "rejects. Tests that cannot run (e.g. TEST004 without a "
                "bathymetry grid) are recorded as skipped, never as passed."
            ),
        ),
    ] = False,
) -> None:
    """Decode a single float and write NetCDF/XML outputs.

    All path flags are optional and work on both Linux and Windows; when
    omitted the values come from ``--config`` (if supplied) or from
    OS-appropriate defaults.
    """
    log = get_logger()
    cfg = load_config(config)
    cfg.metadata.backend = metadata_backend  # type: ignore[assignment]
    if apply_rtqc:
        cfg.rtqc.apply_rtqc = True
    if registry is not None:
        cfg.metadata.registry_path = registry.resolve()
    cfg = _apply_path_overrides(
        cfg,
        input_root=input_root,
        output_root=output_root,
        config_dir=config.parent if config is not None else None,
        meta_info_dir=meta_info_dir,
        meta_dir=meta_dir,
        ref_dir=ref_dir,
        runtime_dir=None,
        temporary_dir=temporary_dir,
    )
    # Ensure output directories exist before we start writing.
    for d in (
        cfg.paths.xml_dir,
        cfg.paths.nc_dir,
        cfg.paths.log_dir,
        cfg.paths.csv_dir,
        cfg.paths.iridium_decoded_dir,
        cfg.paths.temporary_dir,
    ):
        d.mkdir(parents=True, exist_ok=True)
    result = run_pipeline(config=cfg, wmo=wmo, xml_filename=xml_name, use_null_decoder=null_decoder)
    log.info(
        "decode_done",
        wmo=wmo,
        status=result.status,
        n_cycles=result.n_cycles,
        n_files=result.n_files,
        duration_s=result.duration_seconds,
        xml=str(result.xml_report) if result.xml_report else None,
    )
    if result.errors:
        for e in result.errors:
            log.error("decode_error", message=e)
        raise typer.Exit(code=1)


@app.command("validate-config")
def validate_config(
    config: Path = typer.Argument(..., exists=True, help="Path to decoder_conf.json"),
) -> None:
    """Validate a decoder configuration file."""
    cfg = load_config(config)
    print(json.dumps(cfg.model_dump(mode="json", exclude_none=True), indent=2))


@app.command("dual-run")
def dual_run_cmd(
    wmo: int = typer.Argument(..., help="WMO to decode"),
    config: Path = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to decoder_conf.json (optional; defaults apply if omitted).",
    ),
    input_root: Path = typer.Option(
        ...,
        "--input",
        "-i",
        exists=True,
        file_okay=False,
        help="Root of input tree containing archive/cycle and rsync_list",
    ),
    output_root: Path = typer.Option(
        ...,
        "--out",
        "-o",
        file_okay=False,
        help="Output directory (will contain python/ and oracle/ subdirs)",
    ),
    oracle: str = typer.Option(
        "docker:ghcr.io/euroargodev/coriolis-data-processing-chain-for-argo-floats-container:082m",
        "--oracle",
        help="Oracle spec: file:<path> or docker:<image>",
    ),
    runtime: Path | None = typer.Option(
        None,
        "--runtime",
        exists=True,
        file_okay=False,
        help="MATLAB runtime root (docker oracle)",
    ),
    ref: Path | None = typer.Option(
        None,
        "--ref",
        exists=True,
        file_okay=False,
        help="Reference data directory",
    ),
    meta_info_dir: Path | None = typer.Option(
        None,
        "--info-dir",
        exists=True,
        file_okay=False,
        help="Override *_info.json directory",
    ),
    meta_dir: Path | None = typer.Option(
        None,
        "--meta-dir",
        exists=True,
        file_okay=False,
        help="Override *_meta.json directory",
    ),
    null_decoder: bool = typer.Option(
        False, "--null-decoder", help="Use null (plumbing) decoder instead of the real one"
    ),
    report_out: Path | None = typer.Option(
        None, "--report", help="Write JSON diff report to this file"
    ),
) -> None:
    """Run oracle and Python against the same inputs, then diff outputs.

    Aliased as ``shadow`` for convenience during Phase 3.
    """
    _invoke_dual_run(
        wmo=wmo,
        config=config,
        input_root=input_root,
        output_root=output_root,
        oracle=oracle,
        runtime=runtime,
        ref=ref,
        meta_info_dir=meta_info_dir,
        meta_dir=meta_dir,
        null_decoder=null_decoder,
        report_out=report_out,
    )


@app.command("shadow")
def shadow_cmd(
    wmo: int = typer.Argument(..., help="WMO to decode"),
    input_root: Path = typer.Option(
        ...,
        "--input",
        "-i",
        exists=True,
        file_okay=False,
        help="Root of input tree (archive/cycle + rsync_list below it)",
    ),
    output_root: Path = typer.Option(
        ...,
        "--out",
        "-o",
        file_okay=False,
        help="Output directory (python/ and oracle/ subdirs will be created)",
    ),
    config: Path | None = typer.Option(
        None, "--config", "-c", help="decoder_conf.json (optional; defaults work with demo layout)"
    ),
    image: str = typer.Option(
        "ghcr.io/euroargodev/coriolis-data-processing-chain-for-argo-floats-container:082m",
        "--image",
        help="Docker oracle image tag",
    ),
    runtime: Path | None = typer.Option(
        None,
        "--runtime",
        exists=True,
        file_okay=False,
        help="Path to a host MATLAB Runtime install (optional)",
    ),
    ref: Path | None = typer.Option(
        None,
        "--ref",
        exists=True,
        file_okay=False,
        help="Reference-data directory (gebco.nc, woa13_all_n00_01.nc)",
    ),
    meta_info_dir: Path | None = typer.Option(None, "--info-dir", exists=True, file_okay=False),
    meta_dir: Path | None = typer.Option(None, "--meta-dir", exists=True, file_okay=False),
    report_out: Path | None = typer.Option(None, "--report"),
) -> None:
    """Shorthand for dual-run against the Docker/MCR MATLAB oracle.

    This is the primary Phase-3 validation entry point: it invokes the real
    Python decoder (not the plumbing null decoder) alongside the MATLAB
    container and compares NetCDF outputs on a per-variable tolerance basis.
    """
    _invoke_dual_run(
        wmo=wmo,
        config=config,
        input_root=input_root,
        output_root=output_root,
        oracle=f"docker:{image}",
        runtime=runtime,
        ref=ref,
        meta_info_dir=meta_info_dir,
        meta_dir=meta_dir,
        null_decoder=False,
        report_out=report_out,
    )


def _invoke_dual_run(
    *,
    wmo: int,
    config: Path | None,
    input_root: Path,
    output_root: Path,
    oracle: str,
    runtime: Path | None,
    ref: Path | None,
    meta_info_dir: Path | None,
    meta_dir: Path | None,
    null_decoder: bool,
    report_out: Path | None,
) -> None:
    log = get_logger()
    report = dual_run(
        wmo=wmo,
        config_path=config,
        input_root=input_root,
        output_root=output_root,
        oracle_spec=oracle,
        runtime_root=runtime,
        ref_root=ref,
        use_null_decoder=null_decoder,
        info_dir=meta_info_dir,
        meta_dir=meta_dir,
    )
    data: dict[str, object] = report_to_json(report)
    if report_out:
        report_out.parent.mkdir(parents=True, exist_ok=True)
        report_out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    comparison = data.get("comparison", {})
    files_count = comparison.get("files_compared", 0) if isinstance(comparison, dict) else 0
    n_err = sum(1 for m in report.comparison.mismatches if m.severity == "error")
    n_warn = sum(1 for m in report.comparison.mismatches if m.severity == "warning")
    log.info(
        "dual_run_summary",
        ok=report.ok,
        errors=n_err,
        warnings=n_warn,
        files=files_count,
        oracle_ok=report.oracle.ok,
        python_status=report.python.status,
        python_cycles=report.python.n_cycles,
    )
    if not report.ok:
        for m in report.comparison.mismatches:
            if m.severity == "error":
                log.error(
                    "mismatch",
                    scope=m.scope,
                    file=m.file,
                    var=m.variable,
                    message=m.message,
                    max_abs_diff=m.max_abs_diff,
                )
        raise typer.Exit(code=2)



@app.command("publish-cts4")
def publish_cts4(
    wmo: str = typer.Option(..., "--wmo", help="WMO identifier, exactly seven digits (e.g. 2902091). Externally supplied; writer never derives from IMEI/telemetry."),
    cycle: int = typer.Option(1, "--cycle", help="Cycle number for profile files (001)."),
    out_dir: Path = typer.Option(..., "--out", "-o", file_okay=False, help="Output directory for publication NetCDF (meta/tech/R/BR — real-time only; D/BD are reference evidence only when R/BR unavailable)."),
    decoder_version: str = typer.Option("PY-301-0.3.0", "--decoder-version", help="Decoder version string PY-301-x.y.z."),
    bbp_mode: str = typer.Option("TELEMETRY_ORIGINAL", "--bbp-mode", help="BBP mode: TELEMETRY_ORIGINAL (default) or INCOIS_CORRECTED (requires --bbp-corrected-scale)."),
    bbp_corrected_scale: float | None = typer.Option(None, "--bbp-corrected-scale", help="Corrected BPP scale for INCOIS_CORRECTED mode (Barnard 54520)."),
    bbp_original_scale: float | None = typer.Option(None, "--bbp-original-scale", help="Original BBP scale (from snapshot opcode 250)."),
    external_meta: Path | None = typer.Option(None, "--external-meta", exists=True, file_okay=True, dir_okay=False, help="Path to JSON file containing ExternalMeta (required for meta/tech; see writer/fixtures.py for test builders)."),
    tech_records_json: Path | None = typer.Option(None, "--tech-records", exists=True, file_okay=True, dir_okay=False, help="Path to JSON file containing list of tech_records (required for tech)."),
    allow_synthetic: bool = typer.Option(False, "--allow-synthetic", help="Allow synthetic test fixtures (uses writer/fixtures.py helpers) — TEST ONLY, not for GDAC submission."),
) -> None:
    """Publish CTS4 (decoder-301) NetCDF files per frozen Phase-2C contract.

    WMO is EXTERNALLY supplied and strictly validated (^[0-9]{7}$); no IMEI
    fallback. BBP CORRECTED mode recomputes from raw BETA via
    2*pi*khi*((BETA-DARK)*scale-BETASW) with no ratio shortcut. DOXY without
    external calib preserves C1/C2/TEMP_DOXY but sets DOXY to fill QC 9.
    All float-specific metadata MUST be supplied via --external-meta / --tech-records;
    writer never fabricates 2902091 values.
    """
    from argo_decoder.writer.nc import WriterInputs, PublicationBuilder, ExternalMeta
    from argo_decoder.writer.nc import parse_wmo_arg

    try:
        wmo_valid = parse_wmo_arg(wmo)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=2)
    if bbp_mode not in ("TELEMETRY_ORIGINAL", "INCOIS_CORRECTED"):
        typer.echo(f"bbp_mode must be TELEMETRY_ORIGINAL or INCOIS_CORRECTED, got {bbp_mode!r}", err=True)
        raise typer.Exit(code=2)
    if bbp_mode == "INCOIS_CORRECTED" and bbp_corrected_scale is None:
        typer.echo("INCOIS_CORRECTED requires --bbp-corrected-scale (no silent fallback).", err=True)
        raise typer.Exit(code=2)

    # Load BBP scales from dedicated CSV if not supplied and wmo known
    if bbp_original_scale is None or (bbp_mode == "INCOIS_CORRECTED" and bbp_corrected_scale is None):
        try:
            import csv
            csv_path = Path(__file__).resolve().parents[2].parent / "config" / "metadata" / "provor_cts4_pub_bbp_scales.csv"
            if not csv_path.exists():
                csv_path = Path("config/metadata/provor_cts4_pub_bbp_scales.csv")
            if csv_path.exists():
                with open(csv_path, newline="") as f:
                    for row in csv.DictReader(f):
                        if row.get("wmo") == wmo_valid:
                            if bbp_original_scale is None and row.get("bbp_original_scale"):
                                bbp_original_scale = float(row["bbp_original_scale"])
                            if bbp_corrected_scale is None and row.get("bbp_corrected_scale"):
                                if bbp_mode == "INCOIS_CORRECTED":
                                    bbp_corrected_scale = float(row["bbp_corrected_scale"])
                            break
        except Exception as e:
            typer.echo(f"warning: failed to read BBP scales CSV: {e}", err=True)

    # ExternalMeta handling — NO FABRICATION
    external_meta_obj = None
    tech_records = None
    if external_meta is not None:
        try:
            data = json.loads(external_meta.read_text(encoding="utf-8"))
            external_meta_obj = ExternalMeta(**data)
        except Exception as e:
            typer.echo(f"Failed to load --external-meta {external_meta}: {e}", err=True)
            raise typer.Exit(code=2)
    elif allow_synthetic:
        from argo_decoder.writer.fixtures import make_synthetic_external_meta, make_synthetic_tech_records
        external_meta_obj = make_synthetic_external_meta(wmo_valid)
        tech_records = make_synthetic_tech_records(cycle=cycle)
        typer.echo("Using synthetic test fixtures (--allow-synthetic) — NOT for GDAC submission", err=True)
    else:
        typer.echo("Missing --external-meta (authoritative per-float metadata JSON required for meta/tech — see writer/fixtures.py for test builders; use --allow-synthetic for test-only synthetic)", err=True)
        raise typer.Exit(code=2)
    if tech_records is None and tech_records_json is not None:
        try:
            tech_records = json.loads(tech_records_json.read_text(encoding="utf-8"))
        except Exception as e:
            typer.echo(f"Failed to load --tech-records {tech_records_json}: {e}", err=True)
            raise typer.Exit(code=2)
    if tech_records is None and allow_synthetic:
        from argo_decoder.writer.fixtures import make_synthetic_tech_records
        tech_records = make_synthetic_tech_records(cycle=cycle)
    if tech_records is None:
        # Will cause write_tech to fail with clear message; surface here
        typer.echo("Missing --tech-records (and --allow-synthetic not set) — tech requires authoritative records", err=True)
        # Still proceed to let writer raise, but we exit early for clarity
        raise typer.Exit(code=2)

    try:
        inputs = WriterInputs(
            wmo=wmo_valid,
            decoder_version=decoder_version,
            cycle=cycle,
            bbp_mode=bbp_mode,  # type: ignore
            bbp_corrected_scale=bbp_corrected_scale,
            bbp_original_scale=bbp_original_scale,
            external_meta=external_meta_obj,
            tech_records=tech_records,
        )
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=2)
    try:
        builder = PublicationBuilder(inputs)
        written = builder.write(out_dir)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=2)
    except RuntimeError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=2)
    for k, v in written.items():
        typer.echo(f"{k}: {v}")

@app.command("version")
def version() -> None:
    from argo_decoder import __version__

    print(__version__)


if __name__ == "__main__":  # pragma: no cover
    app()
