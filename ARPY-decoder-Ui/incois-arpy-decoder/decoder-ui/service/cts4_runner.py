"""CTS4 / decoder-301 execution bridge for the Live Argo Float Decoder UI.

This module drives the FROZEN backend chain for one 301 float —

    raw SBD group -> decode_group -> resolve_group
    -> build_external_meta_from_gdac -> process_float
    -> R/BR + meta + tech + Rtraj

— with the same run lifecycle the workstation already uses for APEX/ARVOR
(run record, live events, stage tracking, artifact extraction, terminal
persistence). No decoder, RTQC, bitstream-parsing, or NetCDF logic is
duplicated or reimplemented here; the backend calls below are the supplier's
own canonical chain (see their fleet-genericity procedure).

Because the frozen 301 backend emits no log events of its own, the lifecycle
events in this module are emitted by the SERVICE (python_file honestly set to
this file) and carry only real data observed at each step.
"""

from __future__ import annotations

import hashlib
import time
import traceback
import uuid
import warnings
from pathlib import Path
from typing import Any

import netCDF4 as nc
import structlog

from bgc_reader import _qc_char, read_br_file
from event_bus import bus
from models import (
    BgcProfile,
    CycleRecord,
    LiveEvent,
    NodeStatus,
    OutputFileInfo,
    RunSummary,
    StageId,
    StageState,
    utc_now_iso,
)

# Shared service-internal helpers (same package; the legacy runner owns them).
# Imported — never copied — so quirk fixes stay single-point.
from runner_instrumentation import (
    ExecutionCancelledException,
    _clear_current_thread_run,
    _decode_mask_to_test_numbers,
    _parse_history_qctest_masks,
    _set_current_thread_run,
)


def _emit(
    run_id: str,
    level: Any,
    message: str,
    stage: StageId,
    operation: str,
    status: NodeStatus,
    what_happened: str,
    python_function: str,
    data_sample: dict[str, Any] | None = None,
    cycle: int | None = None,
    error_details: str | None = None,
) -> None:
    bus.emit_sync(
        LiveEvent(
            id=f"evt-{uuid.uuid4().hex[:8]}",
            run_id=run_id,
            level=level,
            message=message,
            stage=stage,
            operation=operation,
            cycle=cycle,
            status=status,
            what_happened=what_happened,
            python_file="service/cts4_runner.py",
            python_function=python_function,
            data_sample=data_sample or {},
            error_details=error_details,
            timestamp=utc_now_iso(),
        )
    )


def _first_scalar(var: Any) -> Any:
    """First element of an (N_PROF,) variable (or the scalar itself)."""
    try:
        if getattr(var, "ndim", 0) and var.shape and var.shape[0] > 0:
            return var[0]
        return var[...]
    except Exception:
        return None


def extract_cts4_artifacts(
    float_dir: Path, wmo: int
) -> tuple[list[CycleRecord], list[OutputFileInfo]]:
    """Inspects genuine on-disk 301 products written by process_float().

    Cycle records are built from the per-cycle R (core) files — the same
    CTD-level fields the workstation already models (position, JULD, PRES /
    TEMP / PSAL samples, HISTORY QC masks) — plus N_PROF-aware per-profile
    BGC series parsed from the matching BR file (service/bgc_reader.py).
    BR files are also indexed as output deliverables (category
    ``multi_profile``); cycles with a BR but no R become BGC-only records
    (``has_core=False``), never 404s. The 301 backend writes no XML
    report, so none is expected.
    """
    wmo_s = f"{wmo:07d}"
    profiles_dir = float_dir / "profiles"
    cycles: list[CycleRecord] = []
    output_files: list[OutputFileInfo] = []

    # 1. Parse R (core) profile files into cycle records
    if profiles_dir.is_dir():
        for pfile in sorted(profiles_dir.glob(f"R{wmo_s}_*.nc")):
            try:
                with warnings.catch_warnings():
                    # Trailing fill levels convert fill->None below; silence
                    # the per-level masked-element conversion warnings only.
                    warnings.simplefilter("ignore")
                    ds = nc.Dataset(pfile, "r")
                    try:
                        cycle_num = (
                            int(_first_scalar(ds.variables["CYCLE_NUMBER"]))
                            if "CYCLE_NUMBER" in ds.variables
                            else 0
                        )
                        lat_raw = (
                            float(_first_scalar(ds.variables["LATITUDE"]))
                            if "LATITUDE" in ds.variables
                            else None
                        )
                        lon_raw = (
                            float(_first_scalar(ds.variables["LONGITUDE"]))
                            if "LONGITUDE" in ds.variables
                            else None
                        )
                        if "POSITION_QC" in ds.variables:
                            pos_qc: str | None = _qc_char(
                                _first_scalar(ds.variables["POSITION_QC"])
                            )
                        else:
                            pos_qc = "1"
                        juld_raw = (
                            float(_first_scalar(ds.variables["JULD"]))
                            if "JULD" in ds.variables
                            else None
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
                                _qc_char(pres_qc_var[0, idx])
                                if pres_qc_var is not None and len(pres_qc_var.shape) > 1
                                else "1"
                            )
                            t_qc = (
                                _qc_char(temp_qc_var[0, idx])
                                if temp_qc_var is not None and len(temp_qc_var.shape) > 1
                                else "1"
                            )
                            s_qc = (
                                _qc_char(psal_qc_var[0, idx])
                                if psal_qc_var is not None and len(psal_qc_var.shape) > 1
                                else "1"
                            )
                            c_qc = (
                                _qc_char(cndc_qc_var[0, idx])
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
                    finally:
                        ds.close()
            except Exception as e:
                print(f"Error inspecting CTS4 R profile NetCDF {pfile.name}: {e}")

    # 1b. Attach per-cycle BGC series from BR files (N_PROF-aware); cycles
    # with a BR but no R become honest BGC-only records instead of 404s.
    if profiles_dir.is_dir():
        br_files = sorted(profiles_dir.glob(f"BR{wmo_s}_*.nc"))
        by_cycle = {c.cycle_number: c for c in cycles}
        for bfile in br_files:
            try:
                br = read_br_file(bfile)
            except Exception as e:
                print(f"Error inspecting CTS4 BR profile NetCDF {bfile.name}: {e}")
                continue
            cnum = br["cycle_number"]
            if cnum is None:
                continue
            bgc_profiles = [BgcProfile(**p) for p in br["profiles"]]
            rec = by_cycle.get(cnum)
            if rec is not None:
                rec.bgc_profiles = bgc_profiles
                rec.bgc_source_file = bfile.name
                rec.bgc_n_prof = br["n_prof"]
                rec.matches_g2_signature = br["matches_g2_signature"]
            else:
                cycles.append(
                    CycleRecord(
                        cycle_number=cnum,
                        status=NodeStatus.COMPLETED,
                        latitude=br["latitude"],
                        longitude=br["longitude"],
                        position_qc=br["position_qc"],
                        juld=br["juld"],
                        levels_count=0,
                        bgc_profiles=bgc_profiles,
                        bgc_source_file=bfile.name,
                        bgc_n_prof=br["n_prof"],
                        matches_g2_signature=br["matches_g2_signature"],
                        has_core=False,
                    )
                )
    cycles.sort(key=lambda c: c.cycle_number)

    # 2. Index every 301 NetCDF deliverable (R, BR, meta, tech, Rtraj)
    indexed: list[tuple[Path, Any]] = []
    if profiles_dir.is_dir():
        indexed += [(f, "mono_profile") for f in sorted(profiles_dir.glob(f"R{wmo_s}_*.nc"))]
        indexed += [(f, "multi_profile") for f in sorted(profiles_dir.glob(f"BR{wmo_s}_*.nc"))]
    for fname, cat in (
        (f"{wmo_s}_meta.nc", "meta"),
        (f"{wmo_s}_tech.nc", "tech"),
        (f"{wmo_s}_Rtraj.nc", "traj"),
    ):
        f = float_dir / fname
        if f.is_file():
            indexed.append((f, cat))

    for f, cat in indexed:
        try:
            data = f.read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            ds = nc.Dataset(f, "r")
            try:
                dims = {dname: int(len(dval)) for dname, dval in ds.dimensions.items()}
                vars_list = list(ds.variables.keys())
                attrs = {k: str(getattr(ds, k)) for k in ds.ncattrs() if not k.startswith("_")}
                qcp, qcf = _parse_history_qctest_masks(ds)
            finally:
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
            print(f"Error indexing CTS4 output NetCDF file {f.name}: {err}")

    return cycles, output_files


def execute_cts4_with_observability(
    wmo: int,
    group_dir: Path,
    meta_nc: Path,
    out_root: Path,
    run_id: str,
) -> RunSummary:
    """Decodes one real 301 float via the frozen backend with run observability."""
    from argo_decoder.platforms.provor_cts4_ir_sbd import cts4_realtime
    from argo_decoder.platforms.provor_cts4_ir_sbd import external_meta_io
    from argo_decoder.platforms.provor_cts4_ir_sbd import resolve as cts4_resolve

    t0 = time.time()
    wmo_s = f"{wmo:07d}"
    _set_current_thread_run(run_id)
    structlog.contextvars.bind_contextvars(run_id=run_id, wmo=wmo)

    stages_dict = {
        stg: StageState(id=stg, name=stg.value.replace("_", " "), status=NodeStatus.PENDING)
        for stg in StageId
    }
    stages_dict[StageId.CONFIGURATION].status = NodeStatus.ACTIVE
    stages_dict[StageId.CONFIGURATION].active_operation = "Initializing CTS4 runner"

    summary = RunSummary(
        run_id=run_id,
        wmo=wmo,
        status=NodeStatus.ACTIVE,
        active_stage=StageId.CONFIGURATION,
        active_operation="Initializing CTS4 decoder path",
        stages=stages_dict,
    )
    bus.store_run(summary)

    try:
        if bus.is_run_cancelled(run_id):
            raise ExecutionCancelledException(f"Run {run_id} stopped before CTS4 execution")

        group_dir = Path(group_dir)
        meta_nc = Path(meta_nc)
        if not group_dir.is_dir():
            raise FileNotFoundError(f"CTS4 raw SBD group directory missing: {group_dir}")
        sbd_files = sorted(group_dir.rglob("*.sbd"))
        if not sbd_files:
            raise FileNotFoundError(f"CTS4 raw SBD group has no .sbd files: {group_dir}")
        if not meta_nc.is_file():
            raise FileNotFoundError(f"CTS4 GDAC meta.nc missing: {meta_nc}")

        summary.total_files = len(sbd_files)
        summary.active_stage = StageId.DISCOVERY
        summary.active_operation = f"Decoding CTS4 group {group_dir.name}"
        bus.store_run(summary)

        _emit(
            run_id, "info",
            f"Starting CTS4 decode for float WMO {wmo} (group {group_dir.name}, {len(sbd_files)} SBD files)",
            StageId.CONFIGURATION, "cts4_decode_start", NodeStatus.ACTIVE,
            "Initialized the CTS4/301 backend path with the staged raw group and GDAC metadata.",
            "execute_cts4_with_observability",
            {"wmo": wmo, "group": group_dir.name, "sbd_files": len(sbd_files),
             "meta_nc": meta_nc.name, "output_root": str(out_root)},
        )

        # --- frozen backend chain (supplier's canonical order) ---
        cycles = cts4_realtime.decode_group(group_dir)
        _emit(
            run_id, "success",
            f"Decoded CTS4 group {group_dir.name}: {len(cycles)} internal cycles from {len(sbd_files)} SBD files",
            StageId.DISCOVERY, "cts4_group_decoded", NodeStatus.COMPLETED,
            "Attributed and decoded every .sbd file in the group directory.",
            "execute_cts4_with_observability",
            {"wmo": wmo, "group": group_dir.name, "internal_cycles": len(cycles)},
        )

        cals = cts4_resolve.resolve_group(group_dir)
        serial = int(cals["flbb"].serial)  # type: ignore[union-attr]
        wmo_hyp = cals.get("wmo_hypothesis")
        doxy_kind = type(cals.get("doxy")).__name__
        if wmo_hyp is None:
            raise ValueError(
                f"FLBB serial {serial} (group {group_dir.name}) has no WMO row in the "
                f"301 reference: DATA-COVERAGE — nothing may be published"
            )
        if str(wmo_hyp) != wmo_s:
            raise ValueError(
                f"Group {group_dir.name} resolves to WMO {wmo_hyp}, not requested WMO {wmo_s}"
            )
        summary.active_stage = StageId.DECODE
        summary.active_operation = f"Publishing 301 products for WMO {wmo}"
        bus.store_run(summary)
        _emit(
            run_id, "success",
            f"Resolved group {group_dir.name} to WMO {wmo} (FLBB serial {serial}, DOXY cal: {doxy_kind})",
            StageId.WMO_MAPPING, "cts4_group_resolved", NodeStatus.COMPLETED,
            "Derived the float identity from telemetry via the dedicated 301 reference.",
            "execute_cts4_with_observability",
            {"wmo": wmo, "group": group_dir.name, "flbb_serial": serial,
             "doxy_calibration": doxy_kind},
        )

        external_meta = external_meta_io.build_external_meta_from_gdac(meta_nc, wmo_s)
        _emit(
            run_id, "success",
            f"Built authoritative external metadata from {meta_nc.name} "
            f"({len(external_meta.config_parameter_names)} config params, "
            f"{len(external_meta.config_mission_values or ())} missions)",
            StageId.METADATA, "cts4_external_meta_built", NodeStatus.COMPLETED,
            "Read the float's own GDAC metadata as the authoritative external source.",
            "execute_cts4_with_observability",
            {"wmo": wmo, "meta_nc": meta_nc.name,
             "float_serial_no": external_meta.float_serial_no,
             "n_config_params": len(external_meta.config_parameter_names)},
        )

        if bus.is_run_cancelled(run_id):
            raise ExecutionCancelledException(f"Run {run_id} stopped before product publication")

        res = cts4_realtime.process_float(group_dir, wmo_s, out_root, external_meta)
        _emit(
            run_id, "success",
            f"Published 301 products for WMO {wmo}: {len(res.r_files)} R + {len(res.br_files)} BR "
            f"profiles, meta/tech/Rtraj ({res.tech_rows} tech rows, {res.rtraj_rows} traj rows)",
            StageId.OUTPUT, "cts4_products_written", NodeStatus.COMPLETED,
            "Ran the frozen real-time 301 pipeline and wrote R/BR + meta + tech + Rtraj.",
            "execute_cts4_with_observability",
            {"wmo": wmo, "r_cycles": sorted(res.r_files),
             "br_cycles": sorted(res.br_files),
             "skipped": {str(k): v for k, v in res.skipped.items()},
             "tech_rows": res.tech_rows, "rtraj_rows": res.rtraj_rows},
        )
        for cyc in sorted(res.skipped):
            _emit(
                run_id, "warning",
                f"Cycle {cyc}: {res.skipped[cyc]}",
                StageId.OUTPUT, "cts4_cycle_skipped", NodeStatus.COMPLETED,
                "The backend declined to fabricate this cycle's profiles; recorded verbatim.",
                "execute_cts4_with_observability",
                {"wmo": wmo, "cycle": cyc, "reason": res.skipped[cyc]},
                cycle=cyc,
            )

        if bus.is_run_cancelled(run_id):
            raise ExecutionCancelledException(f"Run {run_id} stopped after publication")

        # Inspect on-disk artifacts generated by process_float()
        cycles_out, output_files = extract_cts4_artifacts(out_root / wmo_s, wmo)
        duration = round(time.time() - t0, 3)

        summary.total_cycles = len(cycles_out)
        summary.completed_cycles = len(cycles_out)
        summary.profile_count = len([f for f in output_files if f.category == "mono_profile"])
        summary.missing_profiles = max(0, summary.total_cycles - summary.profile_count)
        summary.duration_seconds = duration
        summary.cycles = cycles_out
        summary.output_files = output_files

        if output_files:
            meta_file = next((f for f in output_files if f.category == "meta"), None)
            if meta_file and meta_file.global_attrs:
                summary.float_type = meta_file.global_attrs.get("platform_type", summary.float_type)

        for stg in StageId:
            if summary.stages[stg].status != NodeStatus.ERROR:
                summary.stages[stg].status = NodeStatus.COMPLETED
                summary.stages[stg].active_operation = ""

        n_br = len([f for f in output_files if f.category == "multi_profile"])
        n_r = sum(1 for c in cycles_out if c.has_core)
        n_br_only = len(cycles_out) - n_r
        total_flagged_levels = sum(c.rtqc_summary.get("flagged_levels", 0) for c in cycles_out)
        post_event = LiveEvent(
            id=f"evt-{uuid.uuid4().hex[:8]}",
            run_id=run_id,
            level="success",
            message=(
                f"CTS4 products verified: {n_r} R profiles inspected "
                f"({total_flagged_levels} levels flagged), {n_br} BR BGC profiles indexed"
                + (f", {n_br_only} BGC-only cycle(s)" if n_br_only else "")
            ),
            stage=StageId.RTQC,
            operation="cts4_verification_complete",
            status=NodeStatus.COMPLETED,
            what_happened=(
                "Verified the published 301 NetCDF deliverables on disk. Per-test QC masks "
                "are not published in HISTORY (actions CF/CV only); level QC is carried in "
                "the *_QC variables."
            ),
            python_file="service/cts4_runner.py",
            python_function="execute_cts4_with_observability",
            data_sample={
                "wmo": wmo,
                "cycles_inspected": len(cycles_out),
                "r_cycles_inspected": n_r,
                "bgc_only_cycles": n_br_only,
                "br_files_indexed": n_br,
                "total_flagged_levels": total_flagged_levels,
                "output_deliverables_count": len(output_files),
            },
            timestamp=utc_now_iso(),
        )
        bus.emit_sync(post_event)

        summary.status = NodeStatus.COMPLETED
        summary.active_stage = StageId.DONE
        summary.active_operation = "CTS4 decode finished successfully"
        bus.store_run(summary)
        return summary

    except ExecutionCancelledException:
        duration = round(time.time() - t0, 3)
        summary.status = NodeStatus.STOPPED
        summary.duration_seconds = duration
        summary.active_operation = "Stopped by user request"

        try:
            cycles_out, output_files = extract_cts4_artifacts(out_root / wmo_s, wmo)
        except Exception:
            cycles_out, output_files = [], []
        summary.cycles = cycles_out
        summary.output_files = output_files
        summary.completed_cycles = len(cycles_out)

        if summary.active_stage in summary.stages:
            summary.stages[summary.active_stage].status = NodeStatus.STOPPED
            summary.stages[summary.active_stage].detail = "Stopped by user request"

        _emit(
            run_id, "warning",
            f"🛑 CTS4 DECODE STOPPED BY USER: WMO {wmo} execution stopped at user request ({duration:.2f}s).",
            summary.active_stage, "decode_stopped", NodeStatus.STOPPED,
            "Execution was stopped by user request. Partial deliverables preserved.",
            "execute_cts4_with_observability",
        )
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

        _emit(
            run_id, "error",
            f"CTS4 pipeline error for WMO {wmo}: {err_msg}",
            summary.active_stage, "cts4_pipeline_error", NodeStatus.ERROR,
            f"An unhandled exception occurred during CTS4 decoding: {err_msg}",
            "execute_cts4_with_observability",
            error_details=traceback.format_exc(),
        )
        bus.store_run(summary)
        return summary

    finally:
        # Same audit C-2 guarantee as the legacy runner: never leak this run's
        # structlog context onto a reused pool thread.
        structlog.contextvars.clear_contextvars()
        _clear_current_thread_run()
