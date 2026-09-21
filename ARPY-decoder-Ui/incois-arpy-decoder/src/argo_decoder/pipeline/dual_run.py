"""Dual-run harness: drives oracle and Python against the same inputs and diffs.

Usage in Phase 0:

    python -m argo_decoder.cli.main dual-run --wmo 6902892 \
        --config ./demo/config/decoder_conf.json \
        --input ./demo/input \
        --oracle file:./golden/expected \
        --out ./out
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from argo_decoder.config import load_config
from argo_decoder.pipeline.comparator import ComparisonReport, compare_outputs
from argo_decoder.pipeline.oracle import (
    DockerOracle,
    FileOracle,
    OracleBackend,
    OracleRunResult,
)
from argo_decoder.pipeline.runner import PipelineResult, run_pipeline
from argo_decoder.util.logging import get_logger


@dataclass
class DualRunReport:
    wmo: int
    oracle: OracleRunResult
    python: PipelineResult
    comparison: ComparisonReport
    ok: bool


def _resolve_oracle(spec: str) -> OracleBackend:
    if spec.startswith("file:"):
        return FileOracle(Path(spec[5:]))
    if spec.startswith("docker:"):
        return DockerOracle(image=spec[7:])
    # Default: docker image reference
    return DockerOracle(image=spec)


def _materialize_config(config_path: Path, overrides: dict[str, Path]) -> Path:
    """Return the config path (kept for API symmetry; overrides are applied on
    the Python Pydantic object directly so no JSON rewrite is needed)."""
    return Path(config_path)


def _resolve_rsync_mounts(input_root: Path) -> tuple[Path, Path, str, str]:
    """Return (host_rsync_dir, host_rsync_log_dir, container_rsync_path,
    container_rsync_log_path).

    Tolerates both the canonical MATLAB demo layout (``input_root/archive/cycle``
    + ``input_root/rsync_list``) and a flattened layout (``input_root/cycle``
    + ``input_root/rsync_list``). The mount source directories must exist on
    the host because Docker requires real paths for bind mounts; the log
    directory is auto-created when missing.
    """
    rsync = input_root / "archive" / "cycle"
    rsync_list = input_root / "rsync_list"
    if not rsync.exists() and (input_root / "cycle").exists():
        rsync = input_root / "cycle"
        rsync_list = input_root.parent / "rsync_list"
    rsync_list.mkdir(parents=True, exist_ok=True)
    return rsync, rsync_list, "/mnt/data/rsync/archive/cycle/", "/mnt/data/rsync/rsync_list/"


def _materialize_default_config(
    scratch: Path,
    input_root: Path,
    ref_root: Path | None,
    *,
    wmo: int | None = None,
    info_dir_host: Path | None,
    meta_dir_host: Path | None,
) -> tuple[Path, Path, Path]:
    """Write a minimal MATLAB-compatible decoder_conf.json for the oracle.

    Returns ``(config_path, mounted_config_dir, info_dir_to_mount)`` so the
    Docker call can bind-mount exactly what the container expects. When
    ``info_dir_host``/``meta_dir_host`` are supplied we use them directly
    (the Python side already validated they exist); otherwise we fall back
    to a sibling ``decArgo_config_floats`` under the config parent which is
    where the demo layout ships its JSON metadata.

    When the caller passes ``--config`` (a real decoder_conf.json pointing
    at its own metadata tree), we don't use this function at all — see
    :func:`dual_run`.
    """
    import json

    def _transmission_type_from_meta_dir(meta_dir: Path | None, wmo_value: int | None) -> str:
        if meta_dir is None or not meta_dir.exists():
            return "3"
        candidates: list[Path] = []
        if wmo_value is not None:
            candidates.append(meta_dir / f"{wmo_value}_meta.json")
        candidates.extend(sorted(meta_dir.glob("*_meta.json")))
        for path in candidates:
            if not path.exists() or not path.is_file():
                continue
            try:
                raw_meta = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            value = raw_meta.get("FLOAT_TRANSMISSION_TYPE")
            if value not in (None, ""):
                return str(value)
        return "3"

    scratch.mkdir(parents=True, exist_ok=True)

    # Mirror the json_float_info / json_float_meta_ir_sbd tree under scratch
    # so a single bind-mount of scratch -> /mnt/data/config matches the paths
    # we put into the JSON config. Symlink individual *_info.json and
    # *_meta.json files so the container sees the real files without copying.
    cfg_target = scratch / "decArgo_config_floats"
    info_target = cfg_target / "json_float_info"
    meta_target = cfg_target / "json_float_meta_ir_sbd"
    info_target.mkdir(parents=True, exist_ok=True)
    meta_target.mkdir(parents=True, exist_ok=True)

    def _link_json_files(src_dir: Path | None, dst_dir: Path, suffix: str) -> None:
        if src_dir is None or not src_dir.exists():
            return
        for p in src_dir.glob(f"*{suffix}"):
            if not p.is_file():
                continue
            link = dst_dir / p.name
            if link.exists() or link.is_symlink():
                continue
            try:
                link.symlink_to(p.resolve())
            except OSError:
                # Cross-device / permission denied: fall back to a copy.
                import shutil as _shutil

                _shutil.copy2(p, link)

    _link_json_files(info_dir_host, info_target, "_info.json")
    _link_json_files(meta_dir_host, meta_target, "_meta.json")

    _info = "/mnt/data/config/decArgo_config_floats/json_float_info/"
    _meta = "/mnt/data/config/decArgo_config_floats/json_float_meta_ir_sbd/"
    float_transmission_type = _transmission_type_from_meta_dir(meta_dir_host, wmo)
    cfg: dict[str, object] = {
        "FLOAT_TRANSMISSION_TYPE": float_transmission_type,
        "DIR_INPUT_RSYNC_DATA": "/mnt/data/rsync/archive/cycle/",
        "DIR_INPUT_RSYNC_LOG": "/mnt/data/rsync/rsync_list/",
        "DIR_INPUT_JSON_FLOAT_DECODING_PARAMETERS_FILE": _info,
        "DIR_INPUT_JSON_FLOAT_META_DATA_FILE": _meta,
        "IRIDIUM_DATA_DIRECTORY": "/mnt/data/output/iridium/",
        "DIR_OUTPUT_LOG_FILE": "/mnt/data/output/log/",
        "DIR_OUTPUT_CSV_FILE": "/mnt/data/output/csv/",
        "DIR_OUTPUT_XML_FILE": "/mnt/data/output/xml/",
        "DIR_OUTPUT_NETCDF_FILE": "/mnt/data/output/nc/",
        "DIR_OUTPUT_NETCDF_TRAJ_3_1_FILE": "/mnt/data/output/nc/",
        "DIR_OUTPUT_NETCDF_TRAJ_3_2_FILE": "/mnt/data/output/nc/",
        "DIR_OUTPUT_TEMPORARY": "/tmp",
        "PROCESS_REMAINING_BUFFERS": "1",
        "GENERATE_NC_MONO_PROF": "2",
        "GENERATE_NC_TECH": "2",
        "GENERATE_NC_META": "2",
        "GENERATE_NC_TRAJ_3_1": "0",
        "GENERATE_NC_TRAJ_3_2": "2",
        "GENERATE_NC_MULTI_PROF": "0",
        "APPLY_RTQC": "0",
    }
    if ref_root is not None:
        cfg["TEST004_GEBCO_FILE"] = "/mnt/ref/gebco.nc"
        cfg["WOA_FILE"] = "/mnt/ref/woa13_all_n00_01.nc"
        cfg["CHLA_COR_FACT_FILE"] = "/mnt/ref/SLOPE_RT_2024.txt"
    p = scratch / "decoder_conf.json"
    p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return p, scratch, cfg_target


def dual_run(
    *,
    wmo: int,
    config_path: Path | None,
    input_root: Path,
    output_root: Path,
    oracle_spec: str = (
        "docker:ghcr.io/euroargodev/coriolis-data-processing-chain-for-argo-floats-container:082m"
    ),
    runtime_root: Path | None = None,
    ref_root: Path | None = None,
    use_null_decoder: bool = False,
    info_dir: Path | None = None,
    meta_dir: Path | None = None,
) -> DualRunReport:
    log = get_logger().bind(wmo=wmo)
    output_root = Path(output_root)
    input_root = Path(input_root)
    py_out = output_root / "python"
    ora_out = output_root / "oracle"
    # Pre-create the output layout expected by MATLAB / writer.  The Docker
    # container is fussy about some output directories already existing with
    # the right permissions (Linux container UID mapping); mkdir here is safe
    # on Windows too because Path.mkdir is cross-platform via pathlib.
    for d in (
        py_out,
        ora_out,
        py_out / "xml",
        py_out / "log",
        py_out / "csv",
        py_out / "nc",
        py_out / "iridium",
        ora_out / "xml",
        ora_out / "log",
        ora_out / "csv",
        ora_out / "nc",
        ora_out / "iridium",
    ):
        d.mkdir(parents=True, exist_ok=True)

    log.info("dual_run_start", oracle=oracle_spec)

    # Resolve info/meta directories for both oracle + Python.
    # Priority: explicit CLI flags > next to config_path > sibling of input_root.
    resolved_info_dir: Path | None = None
    resolved_meta_dir: Path | None = None
    if info_dir is not None:
        resolved_info_dir = Path(info_dir)
    elif config_path is not None:
        cand = Path(config_path).parent / "decArgo_config_floats" / "json_float_info"
        if cand.exists():
            resolved_info_dir = cand
    if meta_dir is not None:
        resolved_meta_dir = Path(meta_dir)
    elif config_path is not None:
        cand = Path(config_path).parent / "decArgo_config_floats" / "json_float_meta_ir_sbd"
        if cand.exists():
            resolved_meta_dir = cand

    # Resolve which config file to give the oracle. The oracle always needs a
    # real file (it bind-mounts its parent), so if the caller didn't supply one
    # we materialize a minimal config in the output tree with symlinked metadata.
    if config_path is None:
        ora_cfg_path, _cfg_mount, _ = _materialize_default_config(
            ora_out,
            input_root,
            ref_root,
            wmo=wmo,
            info_dir_host=resolved_info_dir,
            meta_dir_host=resolved_meta_dir,
        )
    else:
        ora_cfg_path = Path(config_path)
    rsync_dir, rsync_list_dir, _, _ = _resolve_rsync_mounts(input_root)

    # 1. Run oracle (MATLAB or file-based). DockerOracle mounts input/config/
    # output directly; FileOracle copies reference files into ora_out.
    oracle = _resolve_oracle(oracle_spec)
    ora_res = oracle.run(
        wmo=wmo,
        config_path=ora_cfg_path,
        input_root=input_root,
        output_root=ora_out,
        runtime_root=runtime_root,
        ref_root=ref_root,
    )
    log.info(
        "oracle_done",
        ok=ora_res.ok,
        rc=ora_res.exit_code,
        dur=ora_res.duration_seconds,
        errors=ora_res.errors,
    )

    # 2. Run Python
    cfg = load_config(config_path if config_path is not None else None)
    cfg.paths.rsync_data_dir = rsync_dir
    cfg.paths.rsync_log_dir = rsync_list_dir
    if resolved_info_dir is not None:
        cfg.paths.float_info_dir = resolved_info_dir
    if resolved_meta_dir is not None:
        cfg.paths.float_meta_dir = resolved_meta_dir
    cfg.paths.xml_dir = py_out / "xml"
    cfg.paths.log_dir = py_out / "log"
    cfg.paths.csv_dir = py_out / "csv"
    cfg.paths.nc_dir = py_out / "nc"
    cfg.paths.nc_traj_3_1_dir = py_out / "nc"
    cfg.paths.nc_traj_3_2_dir = py_out / "nc"
    cfg.paths.iridium_decoded_dir = py_out / "iridium"
    for d in (cfg.paths.xml_dir, cfg.paths.log_dir, cfg.paths.csv_dir, cfg.paths.nc_dir):
        d.mkdir(parents=True, exist_ok=True)
    py_res = run_pipeline(
        config=cfg,
        wmo=wmo,
        xml_filename=f"co041404_python_{wmo}.xml",
        use_null_decoder=use_null_decoder,
    )
    log.info(
        "python_done",
        status=py_res.status,
        cycles=py_res.n_cycles,
        dur=py_res.duration_seconds,
    )

    # 3. Compare - even if the oracle failed we still produce a report so the
    # developer can see what Python produced; mismatches will fire for every
    # missing oracle file and the CLI surfaces them as errors.
    cmp_report = compare_outputs(ora_out, py_out, wmo=wmo)
    n_err = sum(1 for m in cmp_report.mismatches if m.severity == "error")
    log.info(
        "compare_done",
        files=cmp_report.files_compared,
        vars=cmp_report.variables_compared,
        ok=cmp_report.ok,
        n_mismatch=n_err,
    )
    ok = ora_res.ok and cmp_report.ok and py_res.status == "ok"
    return DualRunReport(
        wmo=wmo,
        oracle=ora_res,
        python=py_res,
        comparison=cmp_report,
        ok=ok,
    )


def report_to_json(r: DualRunReport) -> dict[str, object]:
    return {
        "wmo": r.wmo,
        "ok": r.ok,
        "oracle": {
            "backend": r.oracle.backend,
            "ok": r.oracle.ok,
            "exit_code": r.oracle.exit_code,
            "duration_seconds": r.oracle.duration_seconds,
            "errors": r.oracle.errors,
        },
        "python": {
            "status": r.python.status,
            "n_cycles": r.python.n_cycles,
            "n_files": r.python.n_files,
            "duration_seconds": r.python.duration_seconds,
            "nc_files": list(r.python.nc_checksums),
        },
        "comparison": {
            "files_compared": r.comparison.files_compared,
            "variables_compared": r.comparison.variables_compared,
            "ok": r.comparison.ok,
            "mismatches": [asdict(m) for m in r.comparison.mismatches],
        },
    }
