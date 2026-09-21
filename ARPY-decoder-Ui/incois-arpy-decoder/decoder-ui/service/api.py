"""REST and WebSocket API endpoints for the Live Argo Float Decoder."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse

# Ensure sys.path includes src before importing argo_decoder
import path_resolver
from argo_decoder.config import DecoderConfig, load_config
from argo_decoder.cli.main import _apply_path_overrides
from event_bus import bus
from models import (
    BatchDecodeRequest,
    BatchFloatItem,
    BatchSummary,
    DecodeRequest,
    LiveEvent,
    NodeStatus,
    OutputFileInfo,
    RunSummary,
    StageId,
)
from runner_instrumentation import execute_decoder_with_observability
from cts4_runner import execute_cts4_with_observability

router = APIRouter(prefix="/api")
thread_pool = ThreadPoolExecutor(max_workers=8)


@router.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "backend": "argo-decoder-python",
        "project_root": str(path_resolver.PROJECT_ROOT),
    }


# ---------------------------------------------------------------------------
# GEOGRAPHIC REFERENCE LAYERS — Indian EEZ (external reference geometry).
#
# Serves the VERIFIED dataset at decoder-ui/data/geography/india_eez.geojson
# (Marine Regions World EEZ v12, 2023-10-25, MRGID 8480 + 8333 — see
# data/geography/README.md for full provenance). The endpoint validates the
# artifact on every load: it never serves a malformed or substituted file.
# The layer is read-only reference data; nothing here alters decode logic.
# ---------------------------------------------------------------------------
INDIA_EEZ_GEOJSON = Path(__file__).parent.parent / "data" / "geography" / "india_eez.geojson"


def _load_india_eez() -> dict[str, Any]:
    payload = json.loads(INDIA_EEZ_GEOJSON.read_text(encoding="utf-8"))
    if payload.get("type") != "FeatureCollection":
        raise ValueError("not a FeatureCollection")
    features = payload.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError("no features")
    mrgids = {
        (f.get("properties") or {}).get("MRGID") for f in features
    }
    if mrgids != {8480, 8333}:
        raise ValueError(f"unexpected feature set {sorted(m for m in mrgids if m is not None)}")
    for f in features:
        gtype = (f.get("geometry") or {}).get("type")
        if gtype not in ("Polygon", "MultiPolygon"):
            raise ValueError(f"unexpected geometry type {gtype}")
        if (f["properties"].get("SOVEREIGN1")) != "India":
            raise ValueError("non-India geometry")
    return payload


@router.get("/geography/india-eez")
async def india_eez_geometry() -> JSONResponse:
    """Verified Indian EEZ boundary geometry (external reference dataset).

    Source: Marine Regions World EEZ v12 (2023-10-25), Indian features
    MRGID 8480 + MRGID 8333, EPSG:4326, CC-BY-4.0. This is an EXTERNAL
    scientific reference, not an official INCOIS product.
    """
    try:
        payload = _load_india_eez()
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="Indian EEZ reference geometry not provisioned")
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Indian EEZ reference geometry failed validation: {exc}")
    return JSONResponse(
        content=payload,
        headers={
            "Cache-Control": "public, max-age=86400",
            "X-Dataset-Source": "Marine Regions World EEZ v12 (2023-10-25) via https://doi.org/10.5281/zenodo.16314546",
            "X-Dataset-Status": "external-reference-not-official-incois",
            "X-Dataset-License": "CC-BY-4.0",
        },
    )


@router.get("/presets")
async def list_presets() -> list[dict[str, Any]]:
    """Dynamically return presets based on floats present in registry and raw directories."""
    return path_resolver.build_dynamic_float_presets()


@router.get("/runs")
async def list_runs() -> list[RunSummary]:
    return bus.get_all_runs()


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> RunSummary:
    run = bus.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/runs/{run_id}/events")
async def get_run_events(
    run_id: str,
    limit: int = Query(5000, ge=1, le=10000),
    offset: int = Query(0, ge=0),
) -> list[LiveEvent]:
    return bus.get_events(run_id, limit=limit, offset=offset)


@router.get("/runs/{run_id}/investigation")
async def get_run_investigation(run_id: str) -> dict[str, Any]:
    """Interactive Error Detail payload for one run (or pre-run record).

    Read-only: the same triage engine as batch triage, plus the run context
    the investigation view needs (primary error, failure stage, stage states,
    focus event, counts). One shared backend so Results, email deep links and
    triage can never disagree about a failure.
    """
    run = bus.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    from triage import build_run_investigation

    return build_run_investigation(run, bus.get_events(run_id))


@router.post("/runs/{run_id}/stop")
async def stop_run(run_id: str) -> dict[str, Any]:
    """Cooperatively stop a running decode process."""
    run = bus.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    bus.cancel_run(run_id)
    return {
        "status": "stopping",
        "run_id": run_id,
        "message": "Stop signal sent to backend worker",
    }


@router.get("/runs/{run_id}/cycles/{cycle_num}")
async def get_run_cycle(run_id: str, cycle_num: int) -> dict[str, Any]:
    run = bus.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    for c in run.cycles:
        if c.cycle_number == cycle_num:
            return c.model_dump()
    raise HTTPException(status_code=404, detail="Cycle not found")


@router.get("/runs/{run_id}/outputs/{filename}")
async def get_output_file_details(run_id: str, filename: str) -> dict[str, Any]:
    run = bus.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    for out in run.output_files:
        if out.filename == filename:
            return out.model_dump()
    raise HTTPException(status_code=404, detail="Output file not found")


def _run_decoder_worker(wmo: int, cfg: DecoderConfig, run_id: str) -> None:
    try:
        execute_decoder_with_observability(wmo=wmo, cfg=cfg, run_id=run_id)
    except Exception as exc:
        print(f"Decoder execution failed for WMO {wmo}: {exc}")


def _is_cts4_preset(preset: dict[str, Any] | None) -> bool:
    """True when a preset routes to the CTS4/301 service path (never legacy)."""
    return bool(preset and preset.get("cts4"))


def _cts4_missing_inputs(group_dir: Any, meta_nc: Any) -> list[str]:
    """Exact missing CTS4 input dependencies (empty when decode-ready)."""
    problems: list[str] = []
    gd = Path(group_dir) if group_dir else None
    if not gd or not gd.is_dir():
        problems.append(f"CTS4 raw SBD group directory missing: {group_dir or '(none staged)'}")
    elif not any(gd.rglob("*.sbd")):
        problems.append(f"CTS4 raw SBD group has no .sbd files: {gd}")
    mn = Path(meta_nc) if meta_nc else None
    if not mn or not mn.is_file():
        problems.append(f"CTS4 GDAC meta.nc missing: {meta_nc or '(none staged)'}")
    return problems


def _cts4_problem_stage(problem: str) -> str:
    """Map a CTS4 staging-gate problem to the stage its dependency belongs to."""
    text = problem.lower()
    if "meta.nc" in text or "gdac" in text:
        return StageId.METADATA.value
    if "sbd group" in text or "group dir" in text or ".sbd" in text:
        return StageId.INPUT_FILES.value
    return StageId.CONFIGURATION.value


def _run_cts4_worker(
    wmo: int, group_dir: Path, meta_nc: Path, out_root: Path, run_id: str
) -> None:
    try:
        execute_cts4_with_observability(
            wmo=wmo, group_dir=group_dir, meta_nc=meta_nc, out_root=out_root, run_id=run_id
        )
    except Exception as exc:
        print(f"CTS4 execution failed for WMO {wmo}: {exc}")


async def _start_cts4_decode(req: DecodeRequest, preset: dict[str, Any]) -> dict[str, Any]:
    """Starts a CTS4/301 decode (preset-driven; refuses missing inputs)."""
    wmo = int(req.wmo)
    group_dir = preset.get("cts4_group_dir")
    meta_nc = preset.get("cts4_meta_nc")
    problems = _cts4_missing_inputs(group_dir, meta_nc)
    if problems:
        raise HTTPException(
            status_code=400,
            detail={
                "message": (
                    f"WMO {wmo} is a CTS4/301 float but its required inputs are "
                    f"not staged; nothing was decoded."
                ),
                "missing": problems,
                "wmo": wmo,
            },
        )

    out_root = (
        Path(req.out_dir)
        if req.out_dir
        else path_resolver.get_default_output_root(wmo) / f"run_{int(time.time())}"
    )
    run_id = req.run_id or f"run-{wmo}-{uuid.uuid4().hex[:6]}"

    summary = RunSummary(
        run_id=run_id,
        wmo=wmo,
        status=NodeStatus.ACTIVE,
        active_operation="Queued for execution",
    )
    bus.store_run(summary)

    thread_pool.submit(
        _run_cts4_worker, wmo, Path(group_dir), Path(meta_nc), out_root, run_id
    )

    return {
        "status": "started",
        "run_id": run_id,
        "wmo": wmo,
        "output_directory": str(out_root),
    }


@router.post("/decode")
async def start_decode(req: DecodeRequest) -> dict[str, Any]:
    presets = path_resolver.build_dynamic_float_presets()
    preset = next((p for p in presets if p["wmo"] == req.wmo), None)

    # CTS4/301 floats run the dedicated 301 service path, never the legacy
    # DecoderConfig pipeline. All floats below this branch are unchanged.
    if _is_cts4_preset(preset):
        return await _start_cts4_decode(req, preset)

    # Dynamic resolution of input path
    raw_dirs = path_resolver.find_raw_input_directories()
    default_input = raw_dirs[0] if raw_dirs else (path_resolver.PROJECT_ROOT / "sample_data" / "argos")
    reg_file = path_resolver.find_registry_csv()
    info_dir_found, meta_dir_found = path_resolver.find_provor_config_directories()

    input_path = req.input_path or (preset["input_path"] if preset else str(default_input))
    input_root = Path(input_path).resolve()
    out_root = Path(req.out_dir) if req.out_dir else path_resolver.get_default_output_root(req.wmo) / f"run_{int(time.time())}"
    
    meta_backend = req.metadata_backend or (preset["metadata_backend"] if preset else "csv")
    reg_path = req.registry_path or (preset.get("registry_path") if preset else (str(reg_file) if reg_file else None))
    info_dir = req.info_dir or (preset.get("info_dir") if preset else (str(info_dir_found) if info_dir_found else None))
    meta_dir = req.meta_dir or (preset.get("meta_dir") if preset else (str(meta_dir_found) if meta_dir_found else None))

    cfg = load_config(None)
    cfg.rtqc.apply_rtqc = True
    cfg.metadata.backend = meta_backend  # type: ignore[assignment]
    if meta_backend in ("csv", "csv4") and reg_path:
        cfg.metadata.registry_path = Path(reg_path).resolve()

    cfg = _apply_path_overrides(
        cfg,
        input_root=input_root,
        output_root=out_root,
        config_dir=None,
        meta_info_dir=Path(info_dir) if info_dir else None,
        meta_dir=Path(meta_dir) if meta_dir else None,
        ref_dir=Path(req.ref_dir) if req.ref_dir else None,
        runtime_dir=None,
        temporary_dir=None,
    )

    # Ensure rsync_data_dir points to valid input directory if _apply_path_overrides fell through
    if not cfg.paths.rsync_data_dir.exists() and input_root.exists():
        cfg.paths.rsync_data_dir = input_root
        cfg.paths.rsync_log_dir = input_root

    for d in (
        cfg.paths.xml_dir,
        cfg.paths.nc_dir,
        cfg.paths.log_dir,
        cfg.paths.csv_dir,
        cfg.paths.iridium_decoded_dir,
        cfg.paths.temporary_dir,
    ):
        d.mkdir(parents=True, exist_ok=True)

    run_id = req.run_id or f"run-{req.wmo}-{uuid.uuid4().hex[:6]}"
    
    summary = RunSummary(
        run_id=run_id,
        wmo=req.wmo,
        status=NodeStatus.ACTIVE,
        active_operation="Queued for execution",
    )
    bus.store_run(summary)

    thread_pool.submit(_run_decoder_worker, req.wmo, cfg, run_id)

    return {
        "status": "started",
        "run_id": run_id,
        "wmo": req.wmo,
        "output_directory": str(out_root),
    }


def _apply_cached_item(item: BatchFloatItem, cached_run: Any) -> None:
    """Convert a batch item into a COMPLETED/CACHED reference to an earlier run.

    The decoder is NOT executed for this float in this batch; the item instead
    points at today's already-successful run so the float stays fully visible —
    with real counts — in the batch totals, the fleet table and Results.
    """
    item.status = NodeStatus.COMPLETED
    item.cached = True
    item.run_id = cached_run.run_id
    item.cycles_count = cached_run.total_cycles
    item.profiles_count = cached_run.profile_count
    item.missing_profiles = cached_run.missing_profiles
    item.outputs_count = len(cached_run.output_files)
    item.duration_seconds = 0.0  # no decoding time was spent in THIS batch
    item.error_message = None
    item.error_type = None
    item.error_count = 0


def _accumulate_cached_totals(batch: BatchSummary, item: BatchFloatItem) -> None:
    """Roll a cached item's existing output metrics into the batch totals."""
    batch.total_profiles_generated += item.profiles_count
    batch.total_profiles_missing += item.missing_profiles
    batch.total_output_files += item.outputs_count


def _run_cts4_batch_item(
    batch: BatchSummary,
    item: BatchFloatItem,
    preset: dict[str, Any],
    wmo: int,
    run_id: str,
    out_dir: str | None,
) -> None:
    """Decodes one CTS4/301 batch item via the 301 service path.

    Item accounting mirrors the legacy per-item flow exactly (status, counts,
    totals); missing staged inputs fail the ITEM with the exact dependency
    instead of raising.
    """
    float_out_root = (
        Path(out_dir) / str(wmo)
        if out_dir
        else path_resolver.get_default_output_root(wmo) / f"run_{int(time.time())}"
    )

    problems = _cts4_missing_inputs(preset.get("cts4_group_dir"), preset.get("cts4_meta_nc"))
    if problems:
        item.status = NodeStatus.ERROR
        item.error_message = "; ".join(problems)
        item.error_type = "MissingInput"
        item.error_count = len(problems)
        # The pipeline never ran, but the failure still gets a persisted
        # ERROR run record with error events so Investigate/triage/email
        # deep links resolve to this exact failure instead of a 404.
        bus.record_prerun_failure(
            run_id=run_id,
            wmo=wmo,
            problems=[(_cts4_problem_stage(p), p) for p in problems],
            error_type="MissingInput",
            platform_type=item.platform_type,
            transmission_type=item.transmission_type,
            decoder_id=item.decoder_id,
        )
        batch.failed_floats += 1
        return

    try:
        run_summary = execute_cts4_with_observability(
            wmo=wmo,
            group_dir=Path(preset["cts4_group_dir"]),
            meta_nc=Path(preset["cts4_meta_nc"]),
            out_root=float_out_root,
            run_id=run_id,
        )
        item.status = run_summary.status
        item.cycles_count = run_summary.total_cycles
        item.profiles_count = run_summary.profile_count
        item.missing_profiles = run_summary.missing_profiles
        item.outputs_count = len(run_summary.output_files)
        item.duration_seconds = run_summary.duration_seconds
        item.error_count = len(run_summary.errors)

        if run_summary.status == NodeStatus.COMPLETED:
            batch.completed_floats += 1
        elif run_summary.status in (NodeStatus.STOPPED, NodeStatus.CANCELLED):
            batch.stopped_floats += 1
            item.error_message = "Stopped by user"
        else:
            batch.failed_floats += 1
            if run_summary.errors:
                item.error_message = run_summary.errors[-1]

        batch.total_profiles_generated += item.profiles_count
        batch.total_profiles_missing += item.missing_profiles
        batch.total_output_files += item.outputs_count

    except Exception as exc:
        item.status = NodeStatus.ERROR
        item.error_message = str(exc)
        item.error_type = type(exc).__name__
        item.error_count = 1
        # If the CTS4 runner raised before persisting any run, leave a
        # minimal ERROR record so the failure stays investigable.
        if bus.get_run(run_id) is None:
            bus.record_prerun_failure(
                run_id=run_id,
                wmo=wmo,
                problems=[(StageId.CONFIGURATION.value, str(exc) or type(exc).__name__)],
                error_type=type(exc).__name__,
                platform_type=item.platform_type,
                transmission_type=item.transmission_type,
                decoder_id=item.decoder_id,
            )
        batch.failed_floats += 1


def _run_batch_worker(
    batch_id: str,
    out_dir: str | None = None,
    app_base_url: str | None = None,
    force: bool = False,
) -> None:
    batch = bus.get_batch(batch_id)
    if not batch:
        return

    presets = path_resolver.build_dynamic_float_presets()
    presets_map = {p["wmo"]: p for p in presets}

    raw_dirs = path_resolver.find_raw_input_directories()
    default_input = raw_dirs[0] if raw_dirs else (path_resolver.PROJECT_ROOT / "sample_data" / "argos")
    reg_file = path_resolver.find_registry_csv()
    info_dir_found, meta_dir_found = path_resolver.find_provor_config_directories()

    start_time = time.time()
    batch.status = NodeStatus.ACTIVE
    bus.broadcast_batch_update_sync(batch)

    fresh_decodes = 0  # floats actually decoded in THIS batch (not cache-carried)

    bus.broadcast_batch_update_sync(batch)

    fresh_decodes = 0  # floats actually decoded in THIS batch (not cache-carried)

    for item in batch.items:
        # Check if entire batch was stopped
        if bus.is_batch_cancelled(batch_id):
            for remaining in batch.items:
                if remaining.status == NodeStatus.PENDING:
                    remaining.status = NodeStatus.STOPPED
                    remaining.error_message = "Batch stopped by user"
                    batch.stopped_floats += 1
            batch.pending_floats = 0
            break

        wmo = item.wmo

        # Items already carried over at batch creation (COMPLETED/CACHED with a
        # reference to today's earlier successful run) are never decoded again.
        if item.cached:
            continue

        # Deferred cache check: even if this float was still pending when the
        # batch was created, a successful run may have appeared in the meantime
        # (e.g. a single-float decode finished while the batch queued). A
        # deliberate re-run (force=True) bypasses the skip logic entirely.
        if not force and item.status == NodeStatus.PENDING:
            cached_run = bus.find_cached_successful_run(wmo)
            if cached_run is not None:
                _apply_cached_item(item, cached_run)
                batch.completed_floats += 1
                batch.cached_floats += 1
                _accumulate_cached_totals(batch, item)
                batch.pending_floats = max(0, batch.pending_floats - 1)
                batch.duration_seconds = round(time.time() - start_time, 2)
                bus.broadcast_batch_update_sync(batch)
                print(
                    f"WMO {wmo}: already successfully decoded today "
                    f"(run {cached_run.run_id}) — carried over as CACHED, not re-decoded"
                )
                continue

        preset = presets_map.get(wmo)
        run_id = f"run-{wmo}-{uuid.uuid4().hex[:6]}"
        item.run_id = run_id
        item.status = NodeStatus.ACTIVE
        fresh_decodes += 1

        batch.running_wmo = wmo
        batch.running_run_id = run_id
        batch.pending_floats = max(0, batch.pending_floats - 1)
        bus.broadcast_batch_update_sync(batch)

        # CTS4/301 floats run the dedicated 301 service path with the same
        # item accounting. Everything below this branch is the unchanged
        # legacy flow.
        if _is_cts4_preset(preset):
            _run_cts4_batch_item(batch, item, preset, wmo, run_id, out_dir)

            batch.duration_seconds = round(time.time() - start_time, 2)
            bus.broadcast_batch_update_sync(batch)

            if bus.is_batch_cancelled(batch_id):
                for remaining in batch.items:
                    if remaining.status == NodeStatus.PENDING:
                        remaining.status = NodeStatus.STOPPED
                        remaining.error_message = "Batch stopped by user"
                        batch.stopped_floats += 1
                batch.pending_floats = 0
                break
            continue

        # Prepare config for this float
        input_path = preset["input_path"] if preset else str(default_input)
        input_root = Path(input_path).resolve()
        float_out_root = (
            Path(out_dir) / str(wmo)
            if out_dir
            else path_resolver.get_default_output_root(wmo) / f"run_{int(time.time())}"
        )

        meta_backend = preset["metadata_backend"] if preset else "csv"
        reg_path = preset.get("registry_path") if preset else (str(reg_file) if reg_file else None)
        if preset is None and reg_path and Path(reg_path).is_dir():
            # Audit C-2 remediation: find_registry_csv() may resolve to a
            # multi-CSV metadata DIRECTORY; the plain "csv" backend expects a
            # single FILE and would crash CsvLoader with IsADirectoryError.
            # Route directory registries through the csv4 backend instead so
            # the degraded fallback still decodes instead of erroring in ~0 s.
            meta_backend = "csv4"
        info_dir = preset.get("info_dir") if preset else (str(info_dir_found) if info_dir_found else None)
        meta_dir = preset.get("meta_dir") if preset else (str(meta_dir_found) if meta_dir_found else None)

        cfg = load_config(None)
        cfg.rtqc.apply_rtqc = True
        cfg.metadata.backend = meta_backend
        if meta_backend in ("csv", "csv4") and reg_path:
            cfg.metadata.registry_path = Path(reg_path).resolve()

        cfg = _apply_path_overrides(
            cfg,
            input_root=input_root,
            output_root=float_out_root,
            config_dir=None,
            meta_info_dir=Path(info_dir) if info_dir else None,
            meta_dir=Path(meta_dir) if meta_dir else None,
            ref_dir=None,
            runtime_dir=None,
            temporary_dir=None,
        )

        # Ensure rsync_data_dir points to valid input directory if _apply_path_overrides fell through
        if not cfg.paths.rsync_data_dir.exists() and input_root.exists():
            cfg.paths.rsync_data_dir = input_root
            cfg.paths.rsync_log_dir = input_root

        for d in (
            cfg.paths.xml_dir,
            cfg.paths.nc_dir,
            cfg.paths.log_dir,
            cfg.paths.csv_dir,
            cfg.paths.iridium_decoded_dir,
            cfg.paths.temporary_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

        try:
            run_summary = execute_decoder_with_observability(wmo=wmo, cfg=cfg, run_id=run_id)
            item.status = run_summary.status
            item.cycles_count = run_summary.total_cycles
            item.profiles_count = run_summary.profile_count
            item.missing_profiles = run_summary.missing_profiles
            item.outputs_count = len(run_summary.output_files)
            item.duration_seconds = run_summary.duration_seconds
            item.error_count = len(run_summary.errors)

            if run_summary.status == NodeStatus.COMPLETED:
                batch.completed_floats += 1
            elif run_summary.status in (NodeStatus.STOPPED, NodeStatus.CANCELLED):
                batch.stopped_floats += 1
                item.error_message = "Stopped by user"
            else:
                batch.failed_floats += 1
                if run_summary.errors:
                    item.error_message = run_summary.errors[-1]

            batch.total_profiles_generated += item.profiles_count
            batch.total_profiles_missing += item.missing_profiles
            batch.total_output_files += item.outputs_count

        except Exception as exc:
            item.status = NodeStatus.ERROR
            item.error_message = str(exc)
            item.error_type = type(exc).__name__
            item.error_count = 1
            # A raise-before-persist here (config/path setup) previously left
            # no run record; persist a minimal ERROR record instead so the
            # failure stays investigable. The instrumented runner stores its
            # own run on in-pipeline failures, so only backfill when missing.
            if bus.get_run(run_id) is None:
                bus.record_prerun_failure(
                    run_id=run_id,
                    wmo=wmo,
                    problems=[(StageId.CONFIGURATION.value, str(exc) or type(exc).__name__)],
                    error_type=type(exc).__name__,
                    platform_type=item.platform_type,
                    transmission_type=item.transmission_type,
                    decoder_id=item.decoder_id,
                )
            batch.failed_floats += 1

        batch.duration_seconds = round(time.time() - start_time, 2)
        bus.broadcast_batch_update_sync(batch)

        if bus.is_batch_cancelled(batch_id):
            for remaining in batch.items:
                if remaining.status == NodeStatus.PENDING:
                    remaining.status = NodeStatus.STOPPED
                    remaining.error_message = "Batch stopped by user"
                    batch.stopped_floats += 1
            batch.pending_floats = 0
            break

    # Batch completed
    batch.running_wmo = None
    batch.running_run_id = None
    batch.ended_at = datetime.now(timezone.utc).isoformat()
    batch.duration_seconds = round(time.time() - start_time, 2)

    if bus.is_batch_cancelled(batch_id) or batch.status == NodeStatus.STOPPED:
        batch.status = NodeStatus.STOPPED
    elif batch.failed_floats > 0 and batch.completed_floats == 0:
        batch.status = NodeStatus.ERROR
    else:
        batch.status = NodeStatus.COMPLETED

    bus.store_batch(batch)
    bus.broadcast_batch_update_sync(batch)

    if fresh_decodes == 0:
        # Every float was carried over from today's successful runs
        # (COMPLETED/CACHED): no decoding happened in this batch, so there is
        # no new report to generate and no new summary email to send. The
        # original decoding batch already produced both.
        batch.pdf_status = "none"
        bus.store_batch(batch)
        bus.broadcast_batch_update_sync(batch)
        print(
            f"Batch {batch_id}: all {len(batch.items)} float(s) reused today's cached "
            "results; no fresh decoding — skipping report PDF and summary email."
        )
        return

    # Generate the INCOIS ARPY Daily Fleet Decoding Report PDF (best-effort).
    # A PDF failure is recorded on the batch record but must NEVER change the
    # decoder/batch result or block the summary email.
    try:
        from pdf_report import generate_batch_report_pdf
        pdf_result = generate_batch_report_pdf(batch.batch_id)
        batch.pdf_status = "generated" if pdf_result["status"] == "generated" else "failed"
        batch.pdf_generated_at = pdf_result.get("generated_at")
        batch.pdf_error = pdf_result.get("error")
        batch.pdf_size_bytes = pdf_result.get("size_bytes")
        batch.pdf_pages = pdf_result.get("pages")
        bus.store_batch(batch)
        bus.broadcast_batch_update_sync(batch)
        if batch.pdf_status == "failed":
            print(f"[PDFReport] Generation failed for {batch_id}: {batch.pdf_error}")
    except Exception as exc:
        batch.pdf_status = "failed"
        batch.pdf_error = f"{type(exc).__name__}: {exc}"
        bus.store_batch(batch)
        bus.broadcast_batch_update_sync(batch)
        print(f"[PDFReport] Unexpected error generating report for {batch_id}: {exc}")

    # Automatically send consolidated batch summary email
    try:
        from email_notifier import send_batch_summary_email
        from report_data import build_batch_report_data

        # Guarantee every failed float's run data is on disk before the email
        # is built, so each "View Decoder Error" deep link in the email
        # resolves against persisted run/event data even after an API restart.
        # Runs live in the bus for the life of this process, so the write is
        # normally a fast no-op when the terminal persist already happened.
        for item in batch.items or []:
            if item.status == NodeStatus.ERROR and item.run_id:
                try:
                    bus.ensure_run_persisted(item.run_id)
                except Exception as exc:
                    print(f"[EmailNotifier] Run persistence check failed for {item.run_id}: {exc}")

        report_data = None
        try:
            report_data = build_batch_report_data(batch.batch_id)
        except Exception as exc:
            print(f"[EmailNotifier] Report data build failed for {batch_id}: {exc}")
        send_batch_summary_email(batch, report_data=report_data, app_base_url=app_base_url)
    except Exception as exc:
        print(f"Error triggering batch summary email for {batch_id}: {exc}")


ALREADY_COMPLETE_MESSAGE = (
    "Today's fleet decoding is already complete. "
    "All currently detected floats have already been processed."
)


@router.post("/batch/decode-all")
async def start_batch_decode(req: BatchDecodeRequest, request: Request) -> dict[str, Any]:
    """Starts decoding all today's discovered floats sequentially with real Python backend.

    Idempotency first: unless ``req.force`` is set (the UI's explicit
    "RE-RUN ALL" action), the CURRENT run/batch state decides what happens:

    * Every eligible float already has a genuinely successful run from
      *today* -> NO new batch is created at all. The response advertises
      ``status="already_complete"`` with the existing completed batch id so
      the frontend can offer View Results / Re-run All. Rapid clicks and
      second browser tabs land here too: already-completed work is never
      processed twice, and batch/run history stays append-only (no
      redundant all-cached batches).

    * Otherwise a NEW batch is created (append-only history): floats that
      already have a genuinely successful run from *today* are carried over
      as COMPLETED/CACHED items referencing that run instead of being
      decoded again. Failed, stopped, incomplete or genuinely new floats
      are always (re-)executed.

    Duplicate protection: if any batch is currently running, this returns
    HTTP 409 with the active batch id — the frontend button state is NOT
    the guard, this endpoint is.
    """
    # Capture the host the operator is browsing the workstation from so the
    # completion email's deep links open on THAT UI (not a hardcoded one).
    from email_notifier import resolve_app_base_url

    app_base_url = resolve_app_base_url(request.headers.get("origin") or request.headers.get("referer"))

    presets = path_resolver.build_dynamic_float_presets()
    if req.wmos:
        selected_presets = [p for p in presets if p["wmo"] in req.wmos]
    else:
        selected_presets = presets

    if not selected_presets:
        raise HTTPException(status_code=400, detail="No floats found for batch decoding")

    # An ACTIVE batch always wins: never report "already complete" while a
    # (re-)decode is in flight — concurrent clients must follow the running
    # batch instead (409 contract, unchanged).
    active = bus.get_active_batch()
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    f"A fleet batch is already running ({active.batch_id}). "
                    "Wait for it to finish or stop it before starting a new one."
                ),
                "active_batch_id": active.batch_id,
            },
        )

    items: list[BatchFloatItem] = []
    n_cached = 0
    for p in selected_presets:
        item = BatchFloatItem(
            wmo=p["wmo"],
            platform_type=p.get("platform_type", ""),
            transmission_type=p.get("transmission_type", ""),
            decoder_id=p.get("decoder_id"),
            status=NodeStatus.PENDING,
        )
        if not req.force:
            cached_run = bus.find_cached_successful_run(p["wmo"])
            if cached_run is not None:
                _apply_cached_item(item, cached_run)
                n_cached += 1
        items.append(item)

    # Everything eligible is already genuinely processed today: do NOT
    # start another duplicate batch — report the existing completed work.
    if not req.force and n_cached == len(items):
        return {
            "status": "already_complete",
            "message": ALREADY_COMPLETE_MESSAGE,
            "batch_id": bus.find_results_batch_for_floats([i.wmo for i in items]),
            "total_floats": len(items),
            "cached_floats": n_cached,
            "to_decode": 0,
            "force": False,
            "floats": [i.wmo for i in items],
        }

    batch_id = req.batch_id or f"batch-{int(time.time())}-{uuid.uuid4().hex[:4]}"

    batch = BatchSummary(
        batch_id=batch_id,
        name="Today's Fleet Telemetry Ingestion",
        status=NodeStatus.ACTIVE,
        total_floats=len(items),
        completed_floats=n_cached,
        cached_floats=n_cached,
        pending_floats=len(items) - n_cached,
        items=items,
    )
    for item in items:
        if item.cached:
            _accumulate_cached_totals(batch, item)

    # Atomic check-and-create: only one batch may be active at a time, even
    # under two browser tabs / rapid repeated clicks / repeated API calls.
    blocker = bus.create_batch_exclusive(batch)
    if blocker is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    f"A fleet batch is already running ({blocker.batch_id}). "
                    "Wait for it to finish or stop it before starting a new one."
                ),
                "active_batch_id": blocker.batch_id,
            },
        )

    thread_pool.submit(_run_batch_worker, batch_id, req.out_dir, app_base_url, req.force)

    return {
        "status": "started",
        "batch_id": batch_id,
        "total_floats": len(items),
        "cached_floats": n_cached,
        "to_decode": len(items) - n_cached,
        "force": bool(req.force),
        "floats": [i.wmo for i in items],
    }


@router.post("/batch/{batch_id}/stop")
async def stop_batch(batch_id: str) -> dict[str, Any]:
    """Stops an active batch run safely, halting current float and preventing pending floats."""
    batch = bus.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    bus.cancel_batch(batch_id)
    return {
        "status": "stopping",
        "batch_id": batch_id,
        "message": "Batch stop signal sent",
    }


@router.get("/batches")
async def list_batches() -> list[BatchSummary]:
    return bus.get_all_batches()


@router.get("/batch/latest")
async def get_latest_batch() -> BatchSummary | None:
    return bus.get_latest_batch()


@router.get("/batch/{batch_id}")
async def get_batch(batch_id: str) -> BatchSummary:
    batch = bus.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    return batch


@router.get("/batch/{batch_id}/triage")
async def get_batch_triage(batch_id: str) -> dict[str, Any]:
    """Agentic triage of every non-successful float in a batch.

    Read-only: inspects the real error evidence (terminal error events, run
    summary, item error message) and returns a structured per-float result —
    category, quoted root cause (actual backend text), recommended operator
    action, and the evidence used. No cause is ever invented.
    """
    batch = bus.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    from triage import triage_batch

    results = triage_batch(
        batch,
        run_lookup=lambda rid: bus.get_run(rid),
        event_lookup=lambda rid: bus.get_events(rid),
    )
    failed = sum(1 for i in batch.items or [] if i.status == NodeStatus.ERROR)
    return {
        "batch_id": batch_id,
        "failed_floats": failed,
        "triaged": len(results),
        "items": [r.to_dict() for r in results],
    }


@router.post("/batch/{batch_id}/send-email")
async def send_batch_email(batch_id: str, request: Request) -> dict[str, Any]:
    """Explicitly send or re-send summary email for a batch.

    Manual resend uses ``force=True``: the already-sent guard is bypassed on
    purpose, while per-batch serialization inside the notifier still prevents
    a concurrent automatic send from delivering a duplicate.
    """
    batch = bus.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    from email_notifier import resolve_app_base_url, send_batch_summary_email

    success = send_batch_summary_email(
        batch,
        force=True,
        app_base_url=resolve_app_base_url(
            request.headers.get("origin") or request.headers.get("referer")
        ),
    )
    return {
        "status": "success" if success else "failed",
        "batch_id": batch_id,
        "email_status": batch.email_status,
        "email_recipient": batch.email_recipient,
        "email_sent_at": batch.email_sent_at,
        "email_error": batch.email_error,
    }


@router.get("/email-config")
async def get_email_config() -> dict[str, Any]:
    """Returns safe (non-secret) email configuration."""
    from email_notifier import EmailConfig

    return {
        "smtp_host": EmailConfig.get_smtp_host(),
        "smtp_port": EmailConfig.get_smtp_port(),
        "smtp_user": EmailConfig.get_smtp_user(),
        "has_password": bool(EmailConfig.get_smtp_password()),
        "use_tls": EmailConfig.get_smtp_use_tls(),
        "use_ssl": EmailConfig.get_smtp_use_ssl(),
        "sender": EmailConfig.get_sender(),
        "recipient": EmailConfig.get_recipient(),
        "app_base_url": EmailConfig.get_app_base_url(),
    }


# ---------------------------------------------------------------------------
# Incoming-data ingestion (phase 1: discovery → NEW DATA in Fleet UI only;
# no automatic decoding is ever started here).
# ---------------------------------------------------------------------------
from ingestion import ingestion


@router.get("/ingestion/status")
async def ingestion_status() -> dict[str, Any]:
    """Active data source status.

    Never contains credentials. ``connected`` is only true after a real,
    successful source interaction (an actual FTP session for ftp mode, a
    successful on-disk scan for local mode) — it is never inferred from
    configuration. ``test_mode`` marks the local/development source so the
    UI can label it (the live INCOIS feed is not provisioned yet).
    """
    return ingestion.status_payload()


@router.get("/ingestion/arrivals")
async def ingestion_arrivals(state: str | None = None) -> list[dict[str, Any]]:
    """Normalized arrival records (newest first).

    Each record carries only facts the source genuinely provides (WMO when
    resolvable from real metadata, source identifier, arrival timestamps);
    ``parser_pending`` objects are opaque source data awaiting the real
    INCOIS format parser.
    """
    return ingestion.arrivals(state=state)


@router.post("/ingestion/ack")
async def ingestion_ack(payload: dict[str, Any]) -> dict[str, Any]:
    """Mark a float's arrivals as seen (clears the NEW DATA badge).

    Acknowledgement is visibility-only: it never starts decoding — the
    explicit Decode workflow stays the user's choice.
    """
    identifier = str(payload.get("identifier") or payload.get("wmo") or "").strip()
    if not identifier:
        raise HTTPException(status_code=400, detail="identifier (or wmo) required")
    return ingestion.ack(identifier)


@router.post("/ingestion/scan")
async def ingestion_scan() -> dict[str, Any]:
    """Trigger an on-demand source scan (operators/tests); returns counts."""
    try:
        return await asyncio.to_thread(ingestion.scan_now)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


# ---------------------------------------------------------------------------
# Float profile/data-recency monitoring — Ifremer/Argo GDAC published profiles.
# Served from the periodic-sync cache immediately (never blocks on FTP);
# profile-derived fields (days-since, data status, expected-next) are computed at serve
# time so they stay fresh between sync cycles. See FLEET_STATUS.md.
# ---------------------------------------------------------------------------
from fleet_status import fleet_sync


@router.get("/fleet-status")
async def get_fleet_status() -> dict[str, Any]:
    """Published profile-recency rows + sync state + summary (cached upstream)."""
    return fleet_sync.payload()


@router.post("/fleet-status/sync")
async def trigger_fleet_sync(background: BackgroundTasks) -> dict[str, Any]:
    """Start one Ifremer GDAC sync cycle in the background (manual refresh).

    Returns at once; poll GET /api/fleet-status for progress/completion.
    """
    if not fleet_sync.enabled:
        raise HTTPException(status_code=503, detail="fleet sync disabled (FLEET_SYNC_ENABLED=0)")
    # Atomic test-and-set shared with the periodic poll loop.
    if not fleet_sync.try_begin():
        state = fleet_sync.payload()["sync"]
        return {"status": "already-running", "sync": state}
    background.add_task(fleet_sync.run_cycle)
    return {"status": "started"}


@router.get("/floats/{wmo}/next-location")
async def get_next_location(wmo: int) -> dict[str, Any]:
    """Experimental predicted next-profile location for ONE float.

    Derived server-side from the cached Ifremer `<WMO>_prof.nc` /
    `<WMO>_Rtraj.nc` data (no download, no browser-side current-data request).
    The same prediction object is embedded in every Float Status row, so the
    detail drawer needs no extra request; this endpoint exists for scripts and
    for the eventual map/detail consumers outside the table.
    """
    payload = fleet_sync.payload()
    row = next((f for f in payload.get("floats", []) if f.get("wmo") == wmo), None)
    if row is None:
        raise HTTPException(status_code=404, detail=f"WMO {wmo} is not in the monitored fleet")
    return {
        "wmo": wmo,
        "generated_at": payload.get("generated_at"),
        "label": "Experimental prediction — not a communication signal",
        "prediction": row.get("prediction"),
        "prediction_summary": payload.get("prediction"),
    }


@router.get("/sse")
async def sse_stream() -> StreamingResponse:
    """Server-Sent Events fallback for real-time live events and batch updates."""
    q = bus.register_sse()

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            while True:
                data = await q.get()
                yield f"data: {json.dumps(data)}\n\n"
        except asyncio.CancelledError:
            bus.unregister_sse(q)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
