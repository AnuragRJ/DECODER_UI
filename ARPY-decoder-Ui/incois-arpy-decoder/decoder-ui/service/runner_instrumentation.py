"""Observability bridge for the real Python Argo Decoder pipeline.

This module attaches a Structlog processor to the genuine `argo_decoder` backend,
invoking `argo_decoder.pipeline.runner.run_pipeline()` directly without duplicating
or reimplementing any internal decoder, RTQC, bitstream parsing, or NetCDF serialization logic.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import netCDF4 as nc
import structlog

from argo_decoder.config import DecoderConfig
from argo_decoder.pipeline.runner import PipelineResult, run_pipeline
from argo_decoder.util.logging import _SHARED_PROCESSORS
from event_bus import bus
from models import (
    CycleRecord,
    LiveEvent,
    NodeStatus,
    OutputFileInfo,
    RtqcPass,
    RtqcTestInfo,
    RunSummary,
    StageId,
    StageState,
    utc_now_iso,
)


class ExecutionCancelledException(Exception):
    """Raised when a decoding run is cancelled/stopped by the user."""


# Per-thread registry of the decoder run currently executing (audit C-2).
#
# All batch/single decodes run on one shared ThreadPoolExecutor, so OS threads
# are recycled between tasks and structlog ContextVars — which are thread-local
# — would survive from a finished (or STOPPED) run into the next task that
# happens to land on the same thread. execute_decoder_with_observability now
# clears those ContextVars in a finally block, and this registry provides a
# second, independent guard: the UI bridge only treats a contextvars-merged
# ``run_id`` as authoritative while THIS thread is registered as executing that
# very run; any other event is stale residue, never emit it for that run and,
# critically, never let it cancel unrelated work.
_CURRENT_RUN_BY_THREAD: dict[int, str] = {}
_CURRENT_RUN_LOCK = threading.Lock()


def _set_current_thread_run(run_id: str) -> None:
    with _CURRENT_RUN_LOCK:
        _CURRENT_RUN_BY_THREAD[threading.get_ident()] = run_id


def _clear_current_thread_run() -> None:
    with _CURRENT_RUN_LOCK:
        _CURRENT_RUN_BY_THREAD.pop(threading.get_ident(), None)


def _get_current_thread_run() -> str | None:
    with _CURRENT_RUN_LOCK:
        return _CURRENT_RUN_BY_THREAD.get(threading.get_ident())


# Map Table 11 test numbers to standard names and passes
TABLE_11_TEST_DEFINITIONS: dict[int, dict[str, Any]] = {
    1: {"name": "Platform Identification", "pass": RtqcPass.PASS_C, "rule": "WMO / Platform ID validated in registry"},
    2: {"name": "Impossible Date Check", "pass": RtqcPass.PASS_C, "rule": "1997-01-01 <= JULD <= now_utc"},
    3: {"name": "Impossible Location Check", "pass": RtqcPass.PASS_C, "rule": "-90 <= LAT <= 90 and -180 <= LON <= 180"},
    4: {"name": "Position on Land Check", "pass": RtqcPass.PASS_C, "rule": "Elevation < 0m in GEBCO bathymetry grid"},
    5: {"name": "Impossible Speed Check", "pass": RtqcPass.PASS_D, "rule": "Haversine Distance / Δt <= 3.0 m/s vs previous cycle"},
    6: {"name": "Global Range Check", "pass": RtqcPass.PASS_A, "rule": "PRES, TEMP, PSAL within physical ocean limits"},
    8: {"name": "Pressure Increasing Check", "pass": RtqcPass.PASS_A, "rule": "P(i+1) > P(i) with monotonicity inversion tolerance"},
    9: {"name": "Spike Check", "pass": RtqcPass.PASS_A, "rule": "Triplicate spike test (500 dbar split threshold)"},
    11: {"name": "Gradient Check", "pass": RtqcPass.PASS_A, "rule": "|v(i) - (v(i-1)+v(i+1))/2| <= threshold"},
    12: {"name": "Digit Rollover Check", "pass": RtqcPass.PASS_A, "rule": "Detects sensor transmission rollover artifacts"},
    13: {"name": "Stuck Value Check", "pass": RtqcPass.PASS_A, "rule": "Consecutive identical readings <= stuck run length"},
    14: {"name": "Density Inversion Check", "pass": RtqcPass.PASS_A, "rule": "TEOS-10 potential density stability (rho_shallow - rho_deep < 0.03)"},
    16: {"name": "Gross Sensor Drift Check", "pass": RtqcPass.PASS_D, "rule": "Deep ocean calibration vs previous good profile"},
    18: {"name": "Frozen Profile Check", "pass": RtqcPass.PASS_D, "rule": "Detects dead or stuck repeated sensor profiles"},
    19: {"name": "Deepest Pressure Check", "pass": RtqcPass.PASS_A, "rule": "PRES_max <= CONFIG_ProfilePressure_dbar * 1.1"},
}


def _safe_serializable_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Ensures all values in data_sample are JSON serializable."""
    safe: dict[str, Any] = {}
    for k, v in d.items():
        if k in ("run_id", "logger", "timestamp", "_record", "_logger", "extra"):
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            safe[k] = v
        elif isinstance(v, (list, tuple)):
            safe[k] = [
                x if isinstance(x, (str, int, float, bool)) or x is None else str(x)
                for x in v
            ]
        elif isinstance(v, dict):
            safe[k] = {
                str(subk): subv if isinstance(subv, (str, int, float, bool)) or subv is None else str(subv)
                for subk, subv in v.items()
            }
        else:
            safe[k] = str(v)
    return safe


def _structlog_ui_bridge_processor(logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Intercepts structlog events from argo_decoder and forwards them to EventBus."""
    if not isinstance(event_dict, dict):
        return event_dict

    event_name = event_dict.get("event")
    if not isinstance(event_name, str) or event_name.startswith("2026-"):
        return event_dict

    run_id = event_dict.get("run_id")
    if not run_id:
        return event_dict

    # Stale-context guard (audit C-2): a run_id merged from ContextVars is only
    # authoritative while this thread is registered as executing that run. In
    # every other situation it is residue from a prior task on this reused pool
    # thread — strip it and return the event unchanged, so a previously STOPPED
    # run can never abort an unrelated decode nor receive foreign log lines.
    if _get_current_thread_run() != run_id:
        stripped = dict(event_dict)
        stripped.pop("run_id", None)
        stripped.pop("wmo", None)
        return stripped

    # Cooperative cancellation check on every backend log event
    if bus.is_run_cancelled(run_id):
        raise ExecutionCancelledException(f"Run {run_id} stopped by user request")

    wmo = event_dict.get("wmo")
    level = method_name.lower()
    lvl_literal: Any = "info"
    if level in ("warning", "warn"):
        lvl_literal = "warning"
    elif level in ("error", "critical", "exception"):
        lvl_literal = "error"
    elif level == "debug":
        lvl_literal = "info"

    stage: StageId = StageId.PLATFORM_PROCESSING
    status: NodeStatus = NodeStatus.ACTIVE
    operation: str = event_name
    message: str = f"Executed {event_name.replace('_', ' ')}"
    what_happened: str = f"Backend step {event_name} was completed."
    py_file: str = "argo_decoder"
    py_func: str = "pipeline"
    cycle_num: int | None = None

    if event_name == "pipeline_start":
        stage = StageId.CONFIGURATION
        operation = "pipeline_start"
        message = f"Starting decoder pipeline for float WMO {wmo}"
        what_happened = f"Initialized decoder configuration and run environment to process float telemetry."
        py_file = "argo_decoder/pipeline/runner.py"
        py_func = "run_pipeline"

    elif event_name == "metadata_backend":
        stage = StageId.METADATA
        backend = event_dict.get("backend", "csv")
        operation = "metadata_backend"
        message = f"Configured metadata loader ({backend})"
        what_happened = f"Selected {backend} metadata source to retrieve float calibration and configuration parameters."
        py_file = "argo_decoder/pipeline/metadata_stage.py"
        py_func = "build_metadata_loader"

    elif event_name in ("csv_loaded", "multi_csv_loaded"):
        stage = StageId.METADATA
        status = NodeStatus.COMPLETED
        lvl_literal = "success"
        comp = event_dict.get("component", "CsvLoader")
        n_entries = event_dict.get("n_floats") or event_dict.get("n_rows") or 0
        path = event_dict.get("path", "")
        operation = "metadata_loaded"
        message = f"Loaded metadata registry ({n_entries} floats indexed from {Path(path).name})"
        what_happened = f"Successfully loaded float registry and sensor calibration parameters from {Path(path).name}."
        py_file = "argo_decoder/metadata/csv_loader.py"
        py_func = "load_info / load_meta"

    elif event_name in ("metadata_warning", "meta_missing"):
        stage = StageId.METADATA
        lvl_literal = "warning"
        code = event_dict.get("code", "METADATA")
        msg = event_dict.get("message", "Metadata field missing or defaulted")
        operation = f"metadata_warning_{code}"
        message = f"Metadata notice [{code}]: {msg}"
        what_happened = f"The decoder encountered a non-critical metadata discrepancy: {msg}. Standard defaults applied."
        py_file = "argo_decoder/metadata/validators.py"
        py_func = "validate_float_info"

    elif event_name in ("metadata_error", "meta_error"):
        stage = StageId.METADATA
        lvl_literal = "error"
        code = event_dict.get("code", "METADATA_ERROR")
        msg = event_dict.get("message", "Metadata validation failed")
        operation = f"metadata_error_{code}"
        message = f"Metadata validation error [{code}]: {msg}"
        what_happened = f"Required metadata was missing or invalid: {msg}."
        py_file = "argo_decoder/metadata/validators.py"
        py_func = "validate_float_info"

    elif event_name == "input_files":
        stage = StageId.DISCOVERY
        status = NodeStatus.COMPLETED
        lvl_literal = "success"
        n_files = event_dict.get("n", 0)
        operation = "input_files_discovered"
        message = f"Found {n_files} telemetry files for this float"
        what_happened = "The decoder indexed the raw telemetry archive and found the input files needed to begin processing."
        py_file = "argo_decoder/io/rsync.py"
        py_func = "discover"

    elif event_name == "no_input_files":
        stage = StageId.DISCOVERY
        lvl_literal = "error"
        status = NodeStatus.ERROR
        operation = "no_input_files"
        message = f"No telemetry files found for WMO {wmo}"
        what_happened = f"No raw telemetry files matching float identifier {wmo} were found in the input directory."
        py_file = "argo_decoder/pipeline/runner.py"
        py_func = "run_pipeline"

    elif event_name == "decoder_selected":
        stage = StageId.DECODER_SELECTION
        status = NodeStatus.COMPLETED
        dec = event_dict.get("decoder", "PlatformDecoder")
        operation = "decoder_selected"
        message = f"Selected {dec} platform decoder"
        what_happened = f"Matched float firmware profile to the {dec} decoding plugin in decoder_table.yaml."
        py_file = "argo_decoder/platforms/base.py"
        py_func = "get_decoder"

    elif event_name == "engine_resolved":
        stage = StageId.PLATFORM_PROCESSING
        comp = event_dict.get("component", "Decoder")
        cs = event_dict.get("firmware_checksum", 0)
        ids = event_dict.get("ids", [])
        operation = "engine_resolved"
        message = f"Firmware profile resolved ({comp})"
        what_happened = f"Identified compatible firmware engine (checksum {cs}, compatible IDs {ids}) for {comp}."
        py_file = "argo_decoder/platforms/provor_ir_sbd/arvor_i_decoder.py"
        py_func = "decode_float"

    elif event_name in ("apex_argos_test004_skipped", "arvor_i_rtqc_test004_skipped"):
        stage = StageId.RTQC
        lvl_literal = "info"
        reason = event_dict.get("reason", "no_gebco_grid")
        operation = "rtqc_test004_note"
        message = f"RTQC TEST004 (Position on Land) omitted ({reason})"
        what_happened = f"TEST004 was omitted because no GEBCO bathymetry grid was configured for this run."
        py_file = "argo_decoder/rtqc/profile_scalar.py"
        py_func = "run_profile_scalar_tests"

    elif event_name == "apex_argos_file_split_into_transmissions":
        stage = StageId.RAW_PROCESSING
        n_tx = event_dict.get("n_transmissions", 1)
        operation = "split_transmissions"
        message = f"Split telemetry dump into {n_tx} transmissions"
        what_happened = "Separated multi-pass ARGOS ground-station dump into individual float surfacings."
        py_file = "argo_decoder/platforms/apex_argos/decoder.py"
        py_func = "decode_float"

    elif event_name == "apex_argos_foreign_transmission_withheld":
        stage = StageId.RAW_PROCESSING
        lvl_literal = "warning"
        f_id = event_dict.get("float_id")
        exp_id = event_dict.get("expected_float_id")
        raw_c = event_dict.get("raw_cycle")
        operation = "foreign_transmission_filtered"
        message = f"Filtered foreign transmission (ID {f_id}, expected {exp_id})"
        what_happened = f"Withheld stray transmission belonging to a different float sharing this transmitter channel (raw cycle {raw_c})."
        py_file = "argo_decoder/platforms/apex_argos/decoder.py"
        py_func = "decode_float"

    elif event_name == "apex_argos_cycle_decoded":
        stage = StageId.DECODE
        status = NodeStatus.COMPLETED
        out_c = event_dict.get("output_cycle", 0)
        raw_c = event_dict.get("raw_cycle", 0)
        msgs = event_dict.get("messages", 0)
        sel = event_dict.get("selected", 0)
        lvls = event_dict.get("levels", 0)
        kept = event_dict.get("kept", True)
        cycle_num = out_c
        operation = "apex_argos_cycle_decoded"
        message = f"Decoded Cycle {out_c} — {lvls} measurement levels"
        what_happened = f"Unpacked binary sensor telemetry for Cycle {out_c} ({msgs} messages received, {sel} selected for profile assembly)."
        py_file = "argo_decoder/platforms/apex_argos/decoder.py"
        py_func = "decode_float"

    elif event_name == "apex_argos_multiburst_trajectory_unioned":
        stage = StageId.PROFILE
        c = event_dict.get("cycle", 0)
        n_fixes = event_dict.get("n_fixes", 0)
        n_times = event_dict.get("n_message_times", 0)
        operation = "trajectory_unioned"
        message = f"Compiled surface trajectory for Cycle {c}"
        what_happened = f"Merged multi-burst satellite reception fixes ({n_fixes} fixes, {n_times} message timestamps) for Cycle {c}."
        py_file = "argo_decoder/platforms/apex_argos/decoder.py"
        py_func = "decode_float"

    elif event_name == "apex_argos_technical_built":
        stage = StageId.PROFILE
        n_params = event_dict.get("n_tech_param", 0)
        n_c = event_dict.get("n_cycles", 0)
        operation = "technical_dataset_built"
        message = f"Compiled engineering telemetry ({n_params} variables across {n_c} cycles)"
        what_happened = "Assembled technical engineering dataset (voltage, battery, vacuum, motor state) for NetCDF export."
        py_file = "argo_decoder/platforms/apex_argos/decoder.py"
        py_func = "decode_float"

    elif event_name == "apex_argos_trajectory_built":
        stage = StageId.PROFILE
        n_meas = event_dict.get("n_measurement", 0)
        n_c = event_dict.get("n_cycle", 0)
        operation = "trajectory_dataset_built"
        message = f"Compiled surface trajectory ({n_meas} fixes across {n_c} cycles)"
        what_happened = "Assembled Rtraj trajectory dataset containing satellite surface fixes and transmission times for NetCDF export."
        py_file = "argo_decoder/platforms/apex_argos/decoder.py"
        py_func = "decode_float"

    elif event_name == "arvor_i_rtqc_applied":
        stage = StageId.RTQC
        status = NodeStatus.COMPLETED
        lvl_literal = "success"
        n_prof = event_dict.get("profiles", 0)
        n_fail = event_dict.get("profiles_with_failures", 0)
        operation = "arvor_i_rtqc_applied"
        message = f"Real-Time QC evaluated across {n_prof} profiles"
        what_happened = f"Evaluated Argo Table 11 automated quality control suite across {n_prof} profiles ({n_fail} profiles had quality flag updates)."
        py_file = "argo_decoder/platforms/provor_ir_sbd/arvor_i_decoder.py"
        py_func = "decode_float"

    elif event_name == "mono_profiles_written":
        stage = StageId.OUTPUT
        n_p = event_dict.get("n", 0)
        operation = "mono_profiles_written"
        message = f"Generated {n_p} profile NetCDF deliverables"
        what_happened = f"Successfully wrote {n_p} individual vertical CTD profile NetCDF files to the output directory."
        py_file = "argo_decoder/platforms/provor_ir_sbd/arvor_i_decoder.py"
        py_func = "decode_float"

    elif event_name == "apex_argos_cross_cycle_rtqc":
        stage = StageId.CROSS_CYCLE_RTQC
        status = NodeStatus.COMPLETED
        lvl_literal = "success"
        n_eval = event_dict.get("cycles_evaluated", 0)
        operation = "cross_cycle_rtqc_applied"
        message = f"Cross-cycle fleet checks evaluated {n_eval} cycles"
        what_happened = "Evaluated impossible speed, sensor drift, and frozen profile checks across successive float cycles."
        py_file = "argo_decoder/platforms/apex_argos/decoder.py"
        py_func = "decode_float"

    elif event_name == "nc_write":
        stage = StageId.OUTPUT
        path_str = event_dict.get("path", "")
        n_bytes = event_dict.get("bytes", 0)
        operation = "nc_write"
        message = f"Saved {Path(path_str).name} ({n_bytes:,} bytes)"
        what_happened = f"Serialized standard Argo NetCDF product to disk at {path_str}."
        py_file = "argo_decoder/nc/writer.py"
        py_func = "write_outputs"

    elif event_name == "pipeline_end":
        stage = StageId.DONE
        status = NodeStatus.COMPLETED
        lvl_literal = "success"
        dur = event_dict.get("duration_s", 0.0)
        n_c = event_dict.get("n_cycles", 0)
        n_nc = event_dict.get("nc_files", 0)
        operation = "pipeline_end"
        message = f"Decoding completed in {dur:.2f}s ({n_c} cycles, {n_nc} deliverables)"
        what_happened = f"All telemetry decoding, quality control, and NetCDF output generation finished successfully for WMO {wmo}."
        py_file = "argo_decoder/pipeline/runner.py"
        py_func = "run_pipeline"

    live_event = LiveEvent(
        id=f"evt-{uuid.uuid4().hex[:8]}",
        run_id=run_id,
        level=lvl_literal,
        message=message,
        stage=stage,
        operation=operation,
        cycle=cycle_num,
        status=status,
        what_happened=what_happened,
        python_file=py_file,
        python_function=py_func,
        data_sample=_safe_serializable_dict(event_dict),
        timestamp=utc_now_iso(),
    )
    bus.emit_sync(live_event)
    return event_dict


# Configure global structlog pipeline once with UI bridge processor
def setup_ui_logging_bridge(level: str = "DEBUG") -> None:
    """Configures structlog to stream argo_decoder logs directly to UI EventBus."""
    log_level = logging.getLevelName(level.upper()) if isinstance(level, str) else level
    renderer = structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=[
            structlog.contextvars.merge_contextvars,
            _structlog_ui_bridge_processor,
            *_SHARED_PROCESSORS,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.contextvars.merge_contextvars,
            _structlog_ui_bridge_processor,
            *_SHARED_PROCESSORS,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )


# Initialize logging bridge on module import
setup_ui_logging_bridge("DEBUG")


def _parse_history_qctest_masks(ds: nc.Dataset) -> tuple[str, str]:
    """Parses QCP$ (tests executed) and QCF$ (tests failed) hex masks from NetCDF HISTORY records."""
    qcp_hex = "0"
    qcf_hex = "0"
    if "HISTORY_ACTION" in ds.variables and "HISTORY_QCTEST" in ds.variables:
        actions = ds.variables["HISTORY_ACTION"][:]
        qctests = ds.variables["HISTORY_QCTEST"][:]
        n_hist = actions.shape[0]
        for i in range(n_hist):
            try:
                act_str = (
                    b"".join([c for c in actions[i, 0] if c != b"--" and isinstance(c, bytes)])
                    .decode("ascii", errors="ignore")
                    .strip()
                )
                test_str = (
                    b"".join([c for c in qctests[i, 0] if c != b"--" and isinstance(c, bytes)])
                    .decode("ascii", errors="ignore")
                    .strip()
                )
                if act_str == "QCP$":
                    qcp_hex = test_str
                elif act_str == "QCF$":
                    qcf_hex = test_str
            except Exception:
                pass
    if qcp_hex == "0" and hasattr(ds, "rtqc_tests_done_hex"):
        qcp_hex = str(getattr(ds, "rtqc_tests_done_hex", "0"))
    if qcf_hex == "0" and hasattr(ds, "rtqc_tests_failed_hex"):
        qcf_hex = str(getattr(ds, "rtqc_tests_failed_hex", "0"))
    return qcp_hex, qcf_hex


def _decode_mask_to_test_numbers(hex_str: str) -> list[int]:
    """Decodes hex bitmask to list of 1-based test numbers."""
    if not hex_str or hex_str == "0":
        return []
    try:
        val = int(hex_str, 16)
    except ValueError:
        return []
    return [n for n in range(64) if val & (1 << n)]


def extract_run_artifacts(
    nc_dir: Path, xml_dir: Path, wmo: int
) -> tuple[list[CycleRecord], list[OutputFileInfo]]:
    """Inspects genuine on-disk NetCDF files and XML report generated by run_pipeline()."""
    float_nc_dir = nc_dir / str(wmo)
    cycles: list[CycleRecord] = []
    output_files: list[OutputFileInfo] = []

    # 1. Parse mono-profile NetCDFs
    profiles_dir = float_nc_dir / "profiles"
    if profiles_dir.exists():
        for pfile in sorted(profiles_dir.glob("*.nc")):
            try:
                ds = nc.Dataset(pfile, "r")
                cycle_num = (
                    int(ds.variables["CYCLE_NUMBER"][0]) if "CYCLE_NUMBER" in ds.variables else 0
                )
                lat_raw = (
                    float(ds.variables["LATITUDE"][0]) if "LATITUDE" in ds.variables else None
                )
                lon_raw = (
                    float(ds.variables["LONGITUDE"][0]) if "LONGITUDE" in ds.variables else None
                )
                pos_qc = (
                    ds.variables["POSITION_QC"][0].tobytes().decode("ascii")
                    if "POSITION_QC" in ds.variables
                    else "1"
                )
                juld_raw = (
                    float(ds.variables["JULD"][0]) if "JULD" in ds.variables else None
                )

                lat = round(lat_raw, 4) if lat_raw is not None and abs(lat_raw) < 99990 else None
                lon = round(lon_raw, 4) if lon_raw is not None and abs(lon_raw) < 99990 else None
                juld = round(juld_raw, 4) if juld_raw is not None and abs(juld_raw) < 999990 else None

                pres_var = ds.variables.get("PRES")
                temp_var = ds.variables.get("TEMP")
                psal_var = ds.variables.get("PSAL")
                cndc_var = ds.variables.get("CNDC")

                pres_qc_var = ds.variables.get("PRES_QC")
                temp_qc_var = ds.variables.get("TEMP_QC")
                psal_qc_var = ds.variables.get("PSAL_QC")
                cndc_qc_var = ds.variables.get("CNDC_QC")

                n_levels = (
                    pres_var.shape[1]
                    if pres_var is not None and len(pres_var.shape) > 1
                    else (len(pres_var) if pres_var is not None else 0)
                )

                ctd_samples: list[dict[str, Any]] = []
                flagged_count = 0

                for idx in range(n_levels):
                    p_val = (
                        float(pres_var[0, idx])
                        if pres_var is not None and len(pres_var.shape) > 1
                        else (float(pres_var[idx]) if pres_var is not None else 0.0)
                    )
                    t_val = (
                        float(temp_var[0, idx])
                        if temp_var is not None and len(temp_var.shape) > 1
                        else (float(temp_var[idx]) if temp_var is not None else 0.0)
                    )
                    s_val = (
                        float(psal_var[0, idx])
                        if psal_var is not None and len(psal_var.shape) > 1
                        else (float(psal_var[idx]) if psal_var is not None else 0.0)
                    )
                    c_val = (
                        float(cndc_var[0, idx])
                        if cndc_var is not None and len(cndc_var.shape) > 1
                        else (float(cndc_var[idx]) if cndc_var is not None else None)
                    )

                    p_qc = (
                        pres_qc_var[0, idx].tobytes().decode("ascii")
                        if pres_qc_var is not None and len(pres_qc_var.shape) > 1
                        else "1"
                    )
                    t_qc = (
                        temp_qc_var[0, idx].tobytes().decode("ascii")
                        if temp_qc_var is not None and len(temp_qc_var.shape) > 1
                        else "1"
                    )
                    s_qc = (
                        psal_qc_var[0, idx].tobytes().decode("ascii")
                        if psal_qc_var is not None and len(psal_qc_var.shape) > 1
                        else "1"
                    )
                    c_qc = (
                        cndc_qc_var[0, idx].tobytes().decode("ascii")
                        if cndc_qc_var is not None and len(cndc_qc_var.shape) > 1
                        else None
                    )

                    if any(q in ("3", "4") for q in (p_qc, t_qc, s_qc)):
                        flagged_count += 1

                    ctd_samples.append(
                        {
                            "level": idx + 1,
                            "PRES": round(p_val, 2) if abs(p_val) < 99990 else None,
                            "TEMP": round(t_val, 3) if abs(t_val) < 99990 else None,
                            "PSAL": round(s_val, 3) if abs(s_val) < 99990 else None,
                            "CNDC": round(c_val, 4) if c_val is not None and abs(c_val) < 99990 else None,
                            "PRES_QC": p_qc,
                            "TEMP_QC": t_qc,
                            "PSAL_QC": s_qc,
                            "CNDC_QC": c_qc,
                        }
                    )

                qcp_hex, qcf_hex = _parse_history_qctest_masks(ds)
                tests_done = _decode_mask_to_test_numbers(qcp_hex)
                tests_failed = _decode_mask_to_test_numbers(qcf_hex)

                cycles.append(
                    CycleRecord(
                        cycle_number=cycle_num,
                        status=NodeStatus.COMPLETED,
                        latitude=lat,
                        longitude=lon,
                        position_qc=pos_qc,
                        juld=juld,
                        levels_count=n_levels,
                        ctd_samples=ctd_samples,
                        rtqc_summary={
                            "qcp_hex": qcp_hex,
                            "qcf_hex": qcf_hex,
                            "tests_done": tests_done,
                            "tests_failed": tests_failed,
                            "flagged_levels": flagged_count,
                        },
                    )
                )
                ds.close()
            except Exception as e:
                print(f"Error inspecting mono profile NetCDF {pfile.name}: {e}")

    # 2. Inspect all output NetCDF files
    if float_nc_dir.exists():
        for f in float_nc_dir.rglob("*.nc"):
            try:
                data = f.read_bytes()
                sha = hashlib.sha256(data).hexdigest()
                cat: Any = "other"
                if "profiles" in str(f):
                    cat = "mono_profile"
                elif "Rtraj" in f.name:
                    cat = "traj"
                elif "meta" in f.name:
                    cat = "meta"
                elif "tech" in f.name:
                    cat = "tech"
                elif "prof" in f.name:
                    cat = "multi_profile"

                ds = nc.Dataset(f, "r")
                dims = {dname: int(len(dval)) for dname, dval in ds.dimensions.items()}
                vars_list = list(ds.variables.keys())
                attrs = {k: str(getattr(ds, k)) for k in ds.ncattrs() if not k.startswith("_")}
                qcp, qcf = _parse_history_qctest_masks(ds)
                ds.close()

                output_files.append(
                    OutputFileInfo(
                        filename=f.name,
                        category=cat,
                        filepath=str(f),
                        filesize_bytes=len(data),
                        checksum_sha256=sha,
                        dimensions=dims,
                        variables=vars_list,
                        global_attrs=attrs,
                        qcp_hex=qcp,
                        qcf_hex=qcf,
                    )
                )
            except Exception as err:
                print(f"Error indexing output NetCDF file {f.name}: {err}")

    # 3. Inspect XML report
    if xml_dir.exists():
        for xf in xml_dir.glob(f"*{wmo}*.xml"):
            try:
                data = xf.read_bytes()
                sha = hashlib.sha256(data).hexdigest()
                output_files.append(
                    OutputFileInfo(
                        filename=xf.name,
                        category="xml",
                        filepath=str(xf),
                        filesize_bytes=len(data),
                        checksum_sha256=sha,
                        xml_content=data.decode("utf-8", errors="ignore")[:4000],
                    )
                )
            except Exception as err:
                print(f"Error indexing XML report {xf.name}: {err}")

    return cycles, output_files


def writer_errors_from_checksums(nc_checksums: dict[str, Any] | None) -> dict[str, str]:
    """Extract NetCDF writer failures from a decoder result's checksum map.

    The decoder records per-product sha256 checksums under product keys and
    records writer failures as ``<product>_error`` keys — while still
    reporting status "ok". The writer itself is untouched (out of scope);
    the service layer consumes these keys into run error state so silent
    output loss becomes a visible, investigable ERROR instead of COMPLETED.
    """
    if not nc_checksums:
        return {}
    return {
        key: str(value)
        for key, value in nc_checksums.items()
        if key.endswith("_error") and value not in (None, "")
    }


def decoder_error_events_needed(errors: list[str] | None, events: list[Any]) -> bool:
    """True when the decoder reported errors but no error-level event exists.

    In that case the service bridges each reported error into a labeled
    error event so Investigate always has a focusable event to open.
    """
    if not errors:
        return False
    return not any(getattr(ev, "level", "") == "error" for ev in events)


def execute_decoder_with_observability(
    wmo: int,
    cfg: DecoderConfig,
    run_id: str,
) -> RunSummary:
    """Invokes genuine Python run_pipeline() with real-time logging observability."""
    t0 = time.time()
    _set_current_thread_run(run_id)
    structlog.contextvars.bind_contextvars(run_id=run_id, wmo=wmo)

    # Initialize stage definitions
    stages_dict = {
        stg: StageState(id=stg, name=stg.value.replace("_", " "), status=NodeStatus.PENDING)
        for stg in StageId
    }
    stages_dict[StageId.CONFIGURATION].status = NodeStatus.ACTIVE
    stages_dict[StageId.CONFIGURATION].active_operation = "Initializing pipeline runner"

    summary = RunSummary(
        run_id=run_id,
        wmo=wmo,
        status=NodeStatus.ACTIVE,
        active_stage=StageId.CONFIGURATION,
        active_operation="Initializing Python decoder pipeline",
        stages=stages_dict,
    )
    bus.store_run(summary)

    try:
        # Check cancellation before launch
        if bus.is_run_cancelled(run_id):
            raise ExecutionCancelledException(f"Run {run_id} stopped before pipeline execution")

        # Execute genuine core pipeline
        res: PipelineResult = run_pipeline(
            config=cfg,
            wmo=wmo,
            write_nc=True,
            write_xml=True,
        )

        # Inspect on-disk artifacts generated by run_pipeline()
        cycles, output_files = extract_run_artifacts(cfg.paths.nc_dir, cfg.paths.xml_dir, wmo)
        duration = round(time.time() - t0, 3)

        summary.total_files = res.n_files
        summary.total_cycles = len(cycles) if cycles else res.n_cycles
        summary.completed_cycles = len(cycles) if cycles else res.n_cycles
        summary.profile_count = len([f for f in output_files if f.category == "mono_profile"])
        summary.missing_profiles = max(0, summary.total_cycles - summary.profile_count)
        summary.duration_seconds = duration
        summary.cycles = cycles
        summary.output_files = output_files
        summary.errors = list(res.errors)
        # Writer failures hide inside an "ok" result (see
        # writer_errors_from_checksums): surface them as run error state.
        writer_errors = writer_errors_from_checksums(res.nc_checksums)

        # Determine platform metadata
        if output_files:
            meta_file = next((f for f in output_files if f.category == "meta"), None)
            if meta_file and meta_file.global_attrs:
                summary.float_type = meta_file.global_attrs.get("platform_type", summary.float_type)

        if res.status == "ok" and not res.errors and not writer_errors:
            # Mark all applicable stages as completed
            for stg in StageId:
                if summary.stages[stg].status != NodeStatus.ERROR:
                    summary.stages[stg].status = NodeStatus.COMPLETED
                    summary.stages[stg].active_operation = ""

            # Emit post-run verified RTQC and physical dataset summary
            total_flagged_levels = sum(c.rtqc_summary.get("flagged_levels", 0) for c in cycles)
            verified_tests_count = (
                len(set().union(*[c.rtqc_summary.get("tests_done", []) for c in cycles]))
                if cycles
                else 0
            )

            post_rtqc_event = LiveEvent(
                id=f"evt-{uuid.uuid4().hex[:8]}",
                run_id=run_id,
                level="success",
                message=f"RTQC verified: {len(cycles)} profiles inspected ({verified_tests_count} tests run, {total_flagged_levels} levels flagged)",
                stage=StageId.RTQC,
                operation="rtqc_verification_complete",
                status=NodeStatus.COMPLETED,
                what_happened="Verified Table 11 automated quality control masks and physical profile datasets from generated NetCDF files.",
                python_file="argo_decoder/rtqc/profile_pipeline.py",
                python_function="apply_rtqc_to_profiles",
                data_sample={
                    "wmo": wmo,
                    "cycles_inspected": len(cycles),
                    "tests_executed_count": verified_tests_count,
                    "total_flagged_levels": total_flagged_levels,
                    "output_deliverables_count": len(output_files),
                },
                timestamp=utc_now_iso(),
            )
            bus.emit_sync(post_rtqc_event)

            summary.status = NodeStatus.COMPLETED
            summary.active_stage = StageId.DONE
            summary.active_operation = "Decode finished successfully"
        else:
            summary.status = NodeStatus.ERROR
            if writer_errors and not res.errors:
                # Decoder exited "ok" but NetCDF writing failed: the writer
                # itself is untouched, the service owns the error state.
                summary.errors = [
                    f"NetCDF output failed ({key}): {value}"
                    for key, value in writer_errors.items()
                ]
                summary.active_stage = StageId.OUTPUT
            # Primary error = latest reported error (unified with the UI's
            # row/banner/investigation primary-error rule).
            err_text = summary.errors[-1] if summary.errors else "Pipeline failed"
            summary.active_operation = f"Error: {err_text}"
            if writer_errors and not res.errors:
                summary.stages[StageId.OUTPUT].status = NodeStatus.ERROR
                summary.stages[StageId.OUTPUT].detail = err_text
            elif any("no input files" in e.lower() for e in res.errors):
                summary.stages[StageId.CONFIGURATION].status = NodeStatus.COMPLETED
                summary.stages[StageId.METADATA].status = NodeStatus.COMPLETED
                summary.stages[StageId.DISCOVERY].status = NodeStatus.ERROR
                summary.stages[StageId.DISCOVERY].detail = err_text
                summary.active_stage = StageId.DISCOVERY
            else:
                if summary.active_stage in summary.stages:
                    summary.stages[summary.active_stage].status = NodeStatus.ERROR
                    summary.stages[summary.active_stage].detail = err_text
            if decoder_error_events_needed(summary.errors, bus.get_events(run_id)):
                # The decoder reported errors but no stage emitted an
                # error-level event: bridge each reported error into a
                # LABELED error event so Investigate always has a focusable
                # event to open (instead of landing on an unrelated event).
                for err in summary.errors:
                    bus.emit_sync(
                        LiveEvent(
                            id=f"evt-bridge-{uuid.uuid4().hex[:8]}",
                            run_id=run_id,
                            level="error",
                            message=err,
                            stage=summary.active_stage,
                            operation="decoder_error",
                            status=NodeStatus.ERROR,
                            what_happened=(
                                "The decoder reported this failure but no stage event "
                                "captured it; bridged from the decoder result so the "
                                "failure stays investigable."
                            ),
                            python_file="argo_decoder/pipeline/runner.py",
                            python_function="run_pipeline",
                            data_sample={"bridged": True, "source": "decoder_result"},
                            timestamp=utc_now_iso(),
                        )
                    )

        bus.store_run(summary)
        return summary

    except ExecutionCancelledException:
        duration = round(time.time() - t0, 3)
        summary.status = NodeStatus.STOPPED
        summary.duration_seconds = duration
        summary.active_operation = "Stopped by user request"

        # Check partial outputs
        cycles, output_files = extract_run_artifacts(cfg.paths.nc_dir, cfg.paths.xml_dir, wmo)
        summary.cycles = cycles
        summary.output_files = output_files
        summary.completed_cycles = len(cycles)

        if summary.active_stage in summary.stages:
            summary.stages[summary.active_stage].status = NodeStatus.STOPPED
            summary.stages[summary.active_stage].detail = "Stopped by user request"

        stop_evt = LiveEvent(
            id=f"evt-{uuid.uuid4().hex[:8]}",
            run_id=run_id,
            level="warning",
            message=f"🛑 DECODE STOPPED BY USER: WMO {wmo} execution stopped at user request ({duration:.2f}s).",
            stage=summary.active_stage,
            operation="decode_stopped",
            status=NodeStatus.STOPPED,
            what_happened="Execution was stopped by user request. Partial deliverables preserved.",
            python_file="service/runner_instrumentation.py",
            python_function="execute_decoder_with_observability",
            timestamp=utc_now_iso(),
        )
        bus.emit_sync(stop_evt)
        bus.store_run(summary)
        return summary

    except Exception as exc:
        duration = round(time.time() - t0, 3)
        summary.status = NodeStatus.ERROR
        summary.duration_seconds = duration
        err_msg = str(exc)
        summary.errors.append(err_msg)
        summary.active_operation = f"Error: {err_msg}"

        if summary.active_stage in summary.stages:
            summary.stages[summary.active_stage].status = NodeStatus.ERROR
            summary.stages[summary.active_stage].detail = err_msg

        err_evt = LiveEvent(
            id=f"evt-{uuid.uuid4().hex[:8]}",
            run_id=run_id,
            level="error",
            message=f"Pipeline error for WMO {wmo}: {err_msg}",
            stage=summary.active_stage,
            operation="pipeline_error",
            status=NodeStatus.ERROR,
            what_happened=f"An unhandled exception occurred during decoding: {err_msg}",
            error_details=traceback.format_exc(),
            python_file="argo_decoder/pipeline/runner.py",
            python_function="run_pipeline",
            timestamp=utc_now_iso(),
        )
        bus.emit_sync(err_evt)
        bus.store_run(summary)
        return summary

    finally:
        # Audit C-2 remediation: never leak this run's structlog context onto
        # a reused pool thread. Without this clear, a STOPPED run's run_id/wmo
        # survived in ContextVars and poisoned whatever task executed next on
        # the same thread (e.g. batch preset resolution → multi_csv_loaded
        # → bridge raised for the stale run → all csv4 presets silently lost
        # → IsADirectoryError fallback). Clearing in a finally also covers
        # every path above: success, error and stopped.
        structlog.contextvars.clear_contextvars()
        _clear_current_thread_run()
