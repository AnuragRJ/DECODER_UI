"""Unit tests for the Investigate-Error reliability fixes.

Covers (all without touching the deployment's real run/batch data):
  * pre-run failure records (``build_prerun_failure_record`` + the bus
    ``record_prerun_failure`` thin wrapper),
  * writer-failure detection from decoder checksum maps
    (``writer_errors_from_checksums``),
  * the bridged-error-event trigger (``decoder_error_events_needed``),
  * the new triage categories, the firmware/corruption split, the
    ``error_type`` hook and the run-aware no-run actions.

Classification cases use REAL error texts observed in this deployment's
persisted runs and batch records.
"""

from __future__ import annotations

import json

import pytest

import event_bus as event_bus_module
from event_bus import EventBus, build_prerun_failure_record
from models import LiveEvent, NodeStatus, RunSummary, StageId
import runner_instrumentation as runner_module
from runner_instrumentation import (
    decoder_error_events_needed,
    execute_decoder_with_observability,
    writer_errors_from_checksums,
)
from triage import (
    CATEGORY_CORRUPTED_INPUT,
    CATEGORY_DECODER_ERROR,
    CATEGORY_MISSING_FLOAT_INFO,
    CATEGORY_STAGED_INPUT_MISSING,
    CATEGORY_UNCLASSIFIED,
    CATEGORY_UNSUPPORTED_PLATFORM,
    CATEGORY_WRITER_OUTPUT,
    build_run_investigation,
    triage_failed_float,
)


# ---------------------------------------------------------------------------
# Pre-run failure records
# ---------------------------------------------------------------------------

CTS4_SBD_PROBLEM = "CTS4 raw SBD group directory missing: (none staged)"
CTS4_META_PROBLEM = "CTS4 GDAC meta.nc missing: (none staged)"


def test_prerun_record_single_problem():
    summary, events = build_prerun_failure_record(
        run_id="run-2902086-abc123",
        wmo=2902086,
        problems=[(StageId.METADATA.value, CTS4_META_PROBLEM)],
        error_type="MissingInput",
        platform_type="PROVOR_III",
        transmission_type="IRIDIUM_SBD",
        decoder_id=301,
    )
    assert summary.status == NodeStatus.ERROR
    assert summary.errors == [CTS4_META_PROBLEM]
    assert summary.active_stage == StageId.METADATA
    assert summary.stages[StageId.METADATA].status == NodeStatus.ERROR
    assert summary.stages[StageId.INPUT_FILES].status == NodeStatus.PENDING
    assert summary.float_type == "PROVOR_III"
    assert summary.decoder_id == 301

    assert len(events) == 1
    evt = events[0]
    assert evt.level == "error"
    assert evt.status == NodeStatus.ERROR
    assert evt.stage == StageId.METADATA
    assert evt.message == CTS4_META_PROBLEM
    assert evt.operation == "stage_metadata"
    assert evt.data_sample == {"pre_run": True, "error_type": "MissingInput"}


def test_prerun_record_multi_problem_cts4():
    """Both CTS4 staging dependencies fail -> one error event per problem."""
    summary, events = build_prerun_failure_record(
        run_id="run-2902089-abc123",
        wmo=2902089,
        problems=[
            (StageId.INPUT_FILES.value, CTS4_SBD_PROBLEM),
            (StageId.METADATA.value, CTS4_META_PROBLEM),
        ],
        error_type="MissingInput",
    )
    assert summary.status == NodeStatus.ERROR
    assert summary.errors == [CTS4_SBD_PROBLEM, CTS4_META_PROBLEM]
    assert summary.stages[StageId.INPUT_FILES].status == NodeStatus.ERROR
    assert summary.stages[StageId.METADATA].status == NodeStatus.ERROR
    assert [e.operation for e in events] == ["stage_input_files", "stage_metadata"]
    assert all(e.level == "error" for e in events)


def test_prerun_record_unknown_stage_falls_back_to_configuration():
    summary, events = build_prerun_failure_record(
        run_id="run-1-x",
        wmo=1,
        problems=[("NOPE", "boom")],
        error_type="RuntimeError",
    )
    assert summary.active_stage == StageId.CONFIGURATION
    assert summary.stages[StageId.CONFIGURATION].status == NodeStatus.ERROR
    assert events[0].operation == "pre_run_configuration"


def test_record_prerun_failure_persists_via_bus(tmp_path, monkeypatch):
    """The bus wrapper registers events BEFORE the terminal store/persist."""
    monkeypatch.setattr(event_bus_module, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(event_bus_module, "BATCHES_DIR", tmp_path / "batches")
    test_bus = EventBus()

    summary = test_bus.record_prerun_failure(
        run_id="run-2902086-abc123",
        wmo=2902086,
        problems=[(StageId.METADATA.value, CTS4_META_PROBLEM)],
        error_type="MissingInput",
    )
    assert test_bus.get_run("run-2902086-abc123") is summary
    assert len(test_bus.get_events("run-2902086-abc123")) == 1

    # Synchronous persist of exactly what store_run would write async.
    test_bus._persist_run_to_disk("run-2902086-abc123")
    payload = json.loads((tmp_path / "runs" / "run-2902086-abc123.json").read_text())
    assert payload["summary"]["status"] == "error"
    assert payload["summary"]["errors"] == [CTS4_META_PROBLEM]
    assert len(payload["events"]) == 1
    assert payload["events"][0]["level"] == "error"


# ---------------------------------------------------------------------------
# Writer-failure detection + bridged-event trigger
# ---------------------------------------------------------------------------

def test_writer_errors_from_checksums():
    assert writer_errors_from_checksums(None) == {}
    assert writer_errors_from_checksums({}) == {}
    assert writer_errors_from_checksums({"mono_profile": "abc123", "meta": "def456"}) == {}
    assert writer_errors_from_checksums({
        "mono_profile": "abc123",
        "multi_profile_error": "disk quota exceeded",
        "traj_error": "",
        "other_error": None,
    }) == {"multi_profile_error": "disk quota exceeded"}


def _evt(level: str) -> LiveEvent:
    return LiveEvent(id="e", run_id="r", level=level, message="m")  # type: ignore[arg-type]


def test_decoder_error_events_needed():
    assert decoder_error_events_needed(["boom"], []) is True
    assert decoder_error_events_needed(["boom"], [_evt("info"), _evt("warning")]) is True
    assert decoder_error_events_needed(["boom"], [_evt("info"), _evt("error")]) is False
    assert decoder_error_events_needed([], []) is False
    assert decoder_error_events_needed(None, []) is False


# ---------------------------------------------------------------------------
# Triage: new categories (real observed texts)
# ---------------------------------------------------------------------------

def _run(wmo: int, error: str | None = None) -> RunSummary:
    return RunSummary(
        run_id=f"run-{wmo}-test",
        wmo=wmo,
        status=NodeStatus.ERROR,
        active_stage=StageId.CONFIGURATION,
        errors=[error] if error else [],
    )


def _err_event(wmo: int, message: str, operation: str = "pipeline_error",
               stage: StageId = StageId.CONFIGURATION,
               details: str | None = None) -> LiveEvent:
    return LiveEvent(
        id=f"evt-{wmo}-test",
        run_id=f"run-{wmo}-test",
        stage=stage,
        operation=operation,
        level="error",
        status=NodeStatus.ERROR,
        message=message,
        error_details=details,
    )


def test_staged_input_missing_via_error_type():
    """Current-batch CTS4 staging failure: MissingInput maps directly."""
    r = triage_failed_float(
        2902086, "error", _run(2902086, CTS4_META_PROBLEM),
        [_err_event(2902086, CTS4_META_PROBLEM, operation="stage_metadata",
                    stage=StageId.METADATA)],
        CTS4_META_PROBLEM,
        run_id="run-2902086-test",
        error_type="MissingInput",
    )
    assert r.category == CATEGORY_STAGED_INPUT_MISSING
    assert "meta.nc" in r.root_cause
    assert "re-run the float" in r.recommended_action


def test_staged_input_missing_via_regex_without_run():
    """Historical CTS4 item (message only, no run): regex still matches and
    the action must not point at a nonexistent event log."""
    msg = f"{CTS4_SBD_PROBLEM}; {CTS4_META_PROBLEM}"
    r = triage_failed_float(2902089, "error", None, [], msg,
                            run_id="run-2902089-test")
    assert r.category == CATEGORY_STAGED_INPUT_MISSING
    assert "2902089" in r.root_cause or "CTS4" in r.root_cause


def test_writer_output_from_service_error_string():
    msg = "NetCDF output failed (multi_profile_error): disk quota exceeded"
    r = triage_failed_float(
        2901304, "error", _run(2901304, msg),
        [_err_event(2901304, msg, operation="decoder_error", stage=StageId.OUTPUT)],
        msg,
        run_id="run-2901304-test",
    )
    assert r.category == CATEGORY_WRITER_OUTPUT
    assert "OUTPUT" in r.recommended_action


def test_writer_output_from_bridged_decoder_message():
    """Generic decoder writer message (no '_error' key in the text): the
    operation name carried into the evidence still routes to WRITER_OUTPUT."""
    msg = "Executed multi profile build failed"
    r = triage_failed_float(
        2901304, "error", _run(2901304, msg),
        [_err_event(2901304, msg, operation="multi_profile_build_failed",
                    stage=StageId.OUTPUT)],
        msg,
        run_id="run-2901304-test",
    )
    assert r.category == CATEGORY_WRITER_OUTPUT


def test_unsupported_firmware_is_not_corruption():
    """Real decoder message: firmware mapping problem, not damaged data."""
    msg = "Unknown or unsupported firmware checksum 232 for decoder ids [210]"
    r = triage_failed_float(
        1902844, "error", _run(1902844, msg),
        [_err_event(1902844, msg, operation="decoder_error")],
        msg,
        run_id="run-1902844-test",
    )
    assert r.category == CATEGORY_UNSUPPORTED_PLATFORM
    assert "232" in r.root_cause


def test_corrupted_input_still_matches_real_damage():
    msg = "Corrupt SBD packet: checksum mismatch in attachment #3"
    r = triage_failed_float(
        2901304, "error", _run(2901304, msg),
        [_err_event(2901304, msg, operation="decode_cycle")],
        msg,
        run_id="run-2901304-test",
    )
    assert r.category == CATEGORY_CORRUPTED_INPUT


# ---------------------------------------------------------------------------
# Triage: run-aware actions for failures without a run record
# ---------------------------------------------------------------------------

def test_unclassified_without_run_has_no_log_reference():
    r = triage_failed_float(
        9999999, "error", None, [],
        "mysterious failure with no known signature",
        run_id="run-9999999-test",
    )
    assert r.category == CATEGORY_UNCLASSIFIED
    assert "No decoder run was created" in r.recommended_action
    assert "mysterious failure" in r.recommended_action  # quotes the real error
    assert "VIEW RUN" not in r.recommended_action


def test_unclassified_with_run_points_at_log():
    r = triage_failed_float(
        9999999, "error", _run(9999999, "mysterious failure"), [],
        "mysterious failure with no known signature",
        run_id="run-9999999-test",
    )
    assert r.category == CATEGORY_UNCLASSIFIED
    assert "VIEW RUN" in r.recommended_action


def test_decoder_error_without_run_has_no_log_reference():
    tb = ("Traceback (most recent call last):\n"
          '  File "x.py", line 1, in <module>\n'
          "ValueError: bad value")
    r = triage_failed_float(9999999, "error", None, [], tb,
                            run_id="run-9999999-test")
    assert r.category == CATEGORY_DECODER_ERROR
    assert "No decoder run was created" in r.recommended_action
    assert "ValueError: bad value" in r.recommended_action


# ---------------------------------------------------------------------------
# execute_* integration (service-level monkeypatching only — src/ untouched):
# writer failures and bridged decoder-error events end to end
# ---------------------------------------------------------------------------

def _isolated_bus(tmp_path, monkeypatch) -> EventBus:
    """Fresh bus writing only to tmp dirs; async persist disabled."""
    monkeypatch.setattr(event_bus_module, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(event_bus_module, "BATCHES_DIR", tmp_path / "batches")
    test_bus = EventBus()
    monkeypatch.setattr(test_bus, "_persist_run_to_disk_async", lambda run_id: None)
    monkeypatch.setattr(runner_module, "bus", test_bus)
    return test_bus


def test_execute_writer_failure_marks_output_error(tmp_path, monkeypatch):
    """Decoder exits "ok" but the writer failed -> ERROR + OUTPUT stage +
    bridged error event (the writer itself is never touched)."""
    from argo_decoder.config import load_config
    from argo_decoder.pipeline.runner import PipelineResult

    test_bus = _isolated_bus(tmp_path, monkeypatch)
    monkeypatch.setattr(
        runner_module,
        "run_pipeline",
        lambda **kwargs: PipelineResult(
            wmo=9999999,
            status="ok",
            n_cycles=0,
            n_files=0,
            nc_checksums={"mono_profile": "abc123", "multi_profile_error": "disk quota exceeded"},
        ),
    )
    summary = execute_decoder_with_observability(
        wmo=9999999, cfg=load_config(None), run_id="run-9999999-writer"
    )
    assert summary.status == NodeStatus.ERROR
    assert summary.active_stage == StageId.OUTPUT
    assert summary.errors == ["NetCDF output failed (multi_profile_error): disk quota exceeded"]
    assert summary.stages[StageId.OUTPUT].status == NodeStatus.ERROR

    err_events = [e for e in test_bus.get_events("run-9999999-writer") if e.level == "error"]
    assert len(err_events) == 1
    assert err_events[0].operation == "decoder_error"
    assert err_events[0].data_sample == {"bridged": True, "source": "decoder_result"}


def test_execute_decoder_errors_without_events_are_bridged(tmp_path, monkeypatch):
    """res.errors with no error-level event -> one labeled bridged event per
    error, so Investigate always has a focusable event."""
    from argo_decoder.config import load_config
    from argo_decoder.pipeline.runner import PipelineResult

    test_bus = _isolated_bus(tmp_path, monkeypatch)
    monkeypatch.setattr(
        runner_module,
        "run_pipeline",
        lambda **kwargs: PipelineResult(
            wmo=9999999, status="error", n_cycles=0, n_files=0,
            errors=["first failure", "second failure"],
        ),
    )
    summary = execute_decoder_with_observability(
        wmo=9999999, cfg=load_config(None), run_id="run-9999999-bridge"
    )
    assert summary.status == NodeStatus.ERROR
    assert summary.errors == ["first failure", "second failure"]

    err_events = [e for e in test_bus.get_events("run-9999999-bridge") if e.level == "error"]
    assert [e.message for e in err_events] == ["first failure", "second failure"]
    assert all(e.operation == "decoder_error" for e in err_events)
    assert all((e.data_sample or {}).get("bridged") is True for e in err_events)


# ---------------------------------------------------------------------------
# build_run_investigation: single source of truth for the Error Detail view
# ---------------------------------------------------------------------------

def test_investigation_payload_multi_error_run():
    """6902892-shaped run: primary = latest, count, focus event, category."""
    wmo = 6902892
    short = "No info JSON found for WMO 6902892 in /home/user/json_float_info"
    tb = "Traceback (most recent call last):\nFileNotFoundError: " + short
    run = RunSummary(
        run_id="run-6902892-test",
        wmo=wmo,
        status=NodeStatus.ERROR,
        active_stage=StageId.CONFIGURATION,
        errors=[short, tb],
    )
    evt = _err_event(wmo, f"Pipeline error for WMO {wmo}: {short}",
                     operation="pipeline_error", details=tb)
    inv = build_run_investigation(run, [evt])
    assert inv["run_id"] == "run-6902892-test"
    assert inv["category"] == CATEGORY_MISSING_FLOAT_INFO
    assert inv["primary_error"] == tb
    assert inv["error_count"] == 2
    assert inv["all_errors"] == [short, tb]
    assert inv["root_cause_available"] is True
    assert inv["failure_stage"] == "CONFIGURATION"
    assert inv["focus_event"]["id"] == evt.id
    assert inv["focus_event"]["operation"] == "pipeline_error"
    assert inv["focus_event"]["has_error_details"] is True
    assert inv["is_prerun"] is False
    assert inv["evidence"], "evidence must be non-empty"


def test_investigation_payload_prerun_record():
    """A persisted pre-run record investigates uniformly (no special case)."""
    summary, events = build_prerun_failure_record(
        run_id="run-2902086-x",
        wmo=2902086,
        problems=[(StageId.METADATA.value, CTS4_META_PROBLEM)],
        error_type="MissingInput",
    )
    inv = build_run_investigation(summary, events)
    assert inv["is_prerun"] is True
    assert inv["category"] == CATEGORY_STAGED_INPUT_MISSING
    assert inv["failure_stage"] == "METADATA"
    assert inv["primary_error"] == CTS4_META_PROBLEM
    assert inv["root_cause_available"] is True
    assert inv["focus_event"]["operation"] == "stage_metadata"


def test_investigation_payload_errors_without_error_events():
    """Case 4 shape: decoder errors but no error-level event — still
    investigable; focus falls back to the latest event (labeled by the UI)."""
    wmo = 2901304
    run = _run(wmo, "Executed multi profile build failed")
    info_evt = LiveEvent(
        id="evt-info", run_id=f"run-{wmo}-test", stage=StageId.PRODUCT_BUILDING,
        operation="build_products", level="info", status=NodeStatus.ACTIVE,
        message="Building profile products",
    )
    inv = build_run_investigation(run, [info_evt])
    assert inv["root_cause_available"] is True
    assert inv["primary_error"] == "Executed multi profile build failed"
    assert inv["focus_event"]["id"] == "evt-info"
    assert inv["focus_event"]["level"] == "info"


def test_investigation_payload_empty_means_unavailable():
    run = RunSummary(run_id="run-1-x", wmo=1, status=NodeStatus.ERROR,
                     active_stage=StageId.CONFIGURATION)
    inv = build_run_investigation(run, [])
    assert inv["root_cause_available"] is False
    assert inv["primary_error"] == ""
    assert inv["error_count"] == 0
    assert inv["focus_event"] is None


def test_investigation_payload_completed_run_is_graceful():
    run = RunSummary(run_id="run-1-x", wmo=1, status=NodeStatus.COMPLETED,
                     active_stage=StageId.DONE)
    inv = build_run_investigation(run, [])
    assert inv["status"] == "completed"
    assert inv["root_cause_available"] is False
