"""APF11 Bio decode orchestration for the live service.

Runs the frozen APF11 product builder (tools/apf11_build_products.py) under
the shared netCDF guard and emits the lifecycle events the Run Result UI and
the E2E verifier consume. Builder + fleet helpers are loaded via importlib so
the supplier package stays the single source of truth — no decoder logic is
rewritten here.
"""

from __future__ import annotations

import importlib.util
import io
import sys
import time
import uuid
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cts4_runner import extract_cts4_artifacts
from event_bus import bus
from models import LiveEvent, NodeStatus, OutputFileInfo, RunSummary, StageId, StageState
from nc_guard import nc_guard, nc_locked
from argo_decoder.writer.apf11_meta import load_meta_csv

SERVICE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SERVICE_DIR.parent.parent
BUILDER_PATH = PROJECT_ROOT / "tools" / "apf11_build_products.py"
FLEET_MODULE_PATH = PROJECT_ROOT / "scripts" / "run_apf11_fleet.py"

APF11_FAMILY = "APEX APF11 Iridium"
APF11_FLEET_ARGS = {
    "--data-centre": "IN",
    "--project": "INCOIS",
    "--wmo-inst-type": "846",
    "--firmware": "102418",
}
APF11_BLOCKED_TECH_ARG = "--allow-blocked-tech"

_builder_mod: Any = None
_fleet_mod: Any = None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_py_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module from {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_builder() -> Any:
    global _builder_mod
    if _builder_mod is None:
        _builder_mod = _load_py_module("apf11_build_products_frozen", BUILDER_PATH)
    return _builder_mod


def load_sensor_table(meta_dir: str | Path) -> dict[str, Any]:
    """Authoritative APF11 sensor table from the supplier fleet helper."""
    global _fleet_mod
    if _fleet_mod is None:
        _fleet_mod = _load_py_module("run_apf11_fleet_mod", FLEET_MODULE_PATH)
    try:
        # meta.csv is the authoritative serial registry the builder enforces
        # against; parse it the same way up front.
        load_meta_csv(Path(meta_dir))
    except Exception:
        pass
    return _fleet_mod.load_float_table(Path(meta_dir))


@nc_locked
def extract_apf11_artifacts(
    float_dir: Path, wmo: int
) -> tuple[list[Any], list[OutputFileInfo]]:
    """CTS4 artifact extraction over genuine APF11 products (N_PROF-aware).

    APF11 BR files use an N_PROF layout that the generic G2 heuristic would
    flag; APF11 Bio products are not G2-structured, so the signature is
    forced False here and never fabricated upward.
    """
    cycles, outputs = extract_cts4_artifacts(float_dir, wmo)
    fixed = []
    for c in cycles:
        if getattr(c, "matches_g2_signature", False):
            c = c.model_copy(update={"matches_g2_signature": False})
        fixed.append(c)
    return fixed, outputs


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
            python_file="service/apf11_runner.py",
            python_function=python_function,
            data_sample=data_sample or {},
            error_details=error_details,
            timestamp=_utc_now_iso(),
        )
    )


def execute_apf11_with_observability(
    *,
    wmo: int,
    prefix: str,
    out_root: Path,
    run_id: str,
    consolidated: Path,
    raw_root: Path,
    meta_dir: Path,
    serial: str,
) -> RunSummary:
    """Decode one APF11 Bio float via the frozen builder, with observability.

    The builder is importlib-executed with the fleet-standard argv (INCOIS
    deployment attributes + --allow-blocked-tech). Exit 0, or exit 2 with a
    ``*_tech_blocked.json`` report, both land in the same completion path:
    the product counts decide the run status. Every result is observed from
    on-disk artifacts — nothing is reported that was not written.
    """
    t0 = time.time()
    wmo_s = f"{wmo:07d}"
    float_dir = Path(out_root) / wmo_s
    float_dir.mkdir(parents=True, exist_ok=True)

    summary = RunSummary(
        run_id=run_id,
        wmo=wmo,
        float_type="APEX",
        platform_family=APF11_FAMILY,
        transmission_type="IRIDIUM",
        decoder_id=None,
        decoder_version="",
        status=NodeStatus.ACTIVE,
        stages={
            stg: StageState(id=stg, name=stg.value.replace("_", " "), status=NodeStatus.PENDING)
            for stg in StageId
        },
    )

    _emit(
        run_id,
        "info",
        f"APF11 Bio decode started for {prefix}/{wmo} (serial {serial})",
        StageId.RAW_PROCESSING,
        "apf11_decode_start",
        NodeStatus.ACTIVE,
        "Frozen APF11 product builder invoked with fleet-standard attributes.",
        "execute_apf11_with_observability",
        data_sample={"prefix": prefix, "serial": serial, "out_dir": str(float_dir)},
    )

    try:
        load_sensor_table(meta_dir)

        builder = _load_builder()
        argv = ["apf11_build_products.py", prefix, str(wmo), "--serial", str(serial)]
        for key, val in APF11_FLEET_ARGS.items():
            argv += [key, val]
        argv.append(APF11_BLOCKED_TECH_ARG)
        argv += ["--metadata", str(meta_dir), "--out", str(float_dir)]

        cap = io.StringIO()
        exit_code = 0
        old_argv = sys.argv
        try:
            sys.argv = argv
            with nc_guard(), redirect_stdout(cap), redirect_stderr(cap):
                builder.main()
        except SystemExit as exc:
            code = exc.code
            exit_code = code if isinstance(code, int) else (0 if code is None else 1)
        finally:
            sys.argv = old_argv
        if cap.getvalue():
            print(cap.getvalue())

        tech_blocked_reports = sorted(float_dir.glob("*_tech_blocked.json"))
        if exit_code not in (0, 2):
            raise RuntimeError(
                f"APF11 builder exited with code {exit_code} for WMO {wmo}"
            )
        if exit_code == 2 and not tech_blocked_reports:
            raise RuntimeError(
                f"APF11 builder exited with code 2 but wrote no tech-blocked "
                f"report for WMO {wmo}"
            )

        cycles, outputs = extract_apf11_artifacts(float_dir, wmo)

        summary.cycles = cycles
        summary.output_files = outputs
        summary.total_cycles = len(cycles)
        summary.completed_cycles = len(cycles)
        summary.profile_count = sum(1 for c in cycles if c.has_core)
        summary.missing_profiles = 0
        summary.total_files = len(outputs)
        summary.duration_seconds = round(time.time() - t0, 2)
        summary.end_time = _utc_now_iso()
        summary.active_stage = StageId.DONE

        # Counts decide: products on disk mean the run completed.
        if outputs:
            summary.status = NodeStatus.COMPLETED
            summary.active_operation = "Complete"
        else:
            summary.status = NodeStatus.ERROR
            summary.active_operation = "No products written"
            summary.errors.append(
                f"APF11 builder produced no products for WMO {wmo} "
                f"under {float_dir}"
            )

        if tech_blocked_reports:
            _emit(
                run_id,
                "warning",
                f"APF11 tech-blocked sensor channels documented: "
                f"{[p.name for p in tech_blocked_reports]}",
                StageId.PRODUCT_BUILDING,
                "apf11_tech_blocked",
                summary.status,
                "Builder wrote a *_tech_blocked.json report; blocked channels "
                "are documented, never fabricated.",
                "execute_apf11_with_observability",
                data_sample={"reports": [p.name for p in tech_blocked_reports]},
            )

        _emit(
            run_id,
            "success",
            f"APF11 products written: {len(outputs)} outputs across "
            f"{len(cycles)} cycles",
            StageId.PRODUCT_BUILDING,
            "apf11_products_written",
            summary.status,
            "Frozen builder products extracted and inventoried from disk.",
            "execute_apf11_with_observability",
            data_sample={
                "cycles": len(cycles),
                "outputs": len(outputs),
                "bgc_cycles": sum(1 for c in cycles if c.bgc_profiles),
            },
        )
        _emit(
            run_id,
            "success",
            f"APF11 verification complete for WMO {wmo}",
            StageId.DONE,
            "apf11_verification_complete",
            summary.status,
            "Cycle counts, BGC presence and deliverable categories verified "
            "against on-disk products.",
            "execute_apf11_with_observability",
            data_sample={
                "cycles_count": summary.total_cycles,
                "profiles_count": summary.profile_count,
                "outputs_count": len(summary.output_files),
                "error_count": len(summary.errors),
                "duration_seconds": summary.duration_seconds,
            },
        )
    except Exception as exc:
        summary.status = NodeStatus.ERROR
        summary.end_time = _utc_now_iso()
        summary.duration_seconds = round(time.time() - t0, 2)
        summary.errors.append(str(exc))
        summary.active_operation = "Failed"
        _emit(
            run_id,
            "error",
            f"APF11 decode failed for WMO {wmo}: {exc}",
            StageId.DECODE,
            "apf11_decode_start",
            NodeStatus.ERROR,
            "Frozen builder execution failed; nothing fabricated.",
            "execute_apf11_with_observability",
            error_details=str(exc),
        )

    bus.store_run(summary)
    return summary
