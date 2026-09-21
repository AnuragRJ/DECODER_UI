"""Unit tests for the agentic failure triage engine (triage.py).

All classification cases use REAL error texts observed in this deployment's
persisted runs and batch records — the classifier must map them correctly
and, per the no-fabrication rule, quote actual text as the root cause.
"""

from __future__ import annotations

import pytest

from models import LiveEvent, NodeStatus, RunSummary, StageId
from triage import (
    CATEGORY_CONFIG_PATH_ERROR,
    CATEGORY_CORRUPTED_INPUT,
    CATEGORY_DECODER_ERROR,
    CATEGORY_MISSING_FLOAT_INFO,
    CATEGORY_MISSING_INPUT_FILES,
    CATEGORY_UNCLASSIFIED,
    CATEGORY_USER_STOPPED,
    _extract_final_exception,
    triage_failed_float,
)


def _run(wmo: int, error: str | None = None) -> RunSummary:
    return RunSummary(
        run_id=f"run-{wmo}-test",
        wmo=wmo,
        status=NodeStatus.ERROR,
        active_stage=StageId.CONFIGURATION,
        errors=[error] if error else [],
    )


def _err_event(wmo: int, message: str, operation: str = "pipeline_error",
               details: str | None = None) -> LiveEvent:
    return LiveEvent(
        id=f"evt-{wmo}-test",
        run_id=f"run-{wmo}-test",
        stage=StageId.CONFIGURATION,
        operation=operation,
        level="error",
        status=NodeStatus.ERROR,
        message=message,
        error_details=details,
    )


# ---------------------------------------------------------------------------
# Final-exception extraction (tracebacks)
# ---------------------------------------------------------------------------

TRACEBACK_NO_INFO = (
    'Traceback (most recent call last):\n'
    '  File "/home/user/decoder-ui/service/runner_instrumentation.py", line 700, '
    'in execute_decoder_with_observability\n'
    '    res: PipelineResult = run_pipeline(cfg)\n'
    '  File "/home/user/src/argo_decoder/pipeline/runner.py", line 100, in run_pipeline\n'
    '    info = loader.load_info(wmo_int)\n'
    'FileNotFoundError: No info JSON found for WMO 6902892 in /home/user/sample_data/config_floats/json_float_info'
)


def test_extract_final_exception():
    assert _extract_final_exception(TRACEBACK_NO_INFO) == (
        "FileNotFoundError: No info JSON found for WMO 6902892 in "
        "/home/user/sample_data/config_floats/json_float_info"
    )
    assert _extract_final_exception("no traceback here") is None


# ---------------------------------------------------------------------------
# Category classification against real observed messages
# ---------------------------------------------------------------------------

def test_missing_float_info_from_event():
    wmo = 6902892
    r = triage_failed_float(
        wmo, "error", _run(wmo),
        [_err_event(wmo, "Pipeline error for WMO 6902892: No info JSON found for "
                          "WMO 6902892 in /home/user/sample_data/config_floats/json_float_info",
                     details=TRACEBACK_NO_INFO)],
        None,
    )
    assert r.category == CATEGORY_MISSING_FLOAT_INFO
    # root cause must quote actual backend text (no fabrication)
    assert "No info JSON found for WMO 6902892" in r.root_cause
    assert r.evidence, "evidence must be non-empty"


def test_missing_input_files():
    wmo = 2901305
    r = triage_failed_float(
        wmo, "error", _run(wmo),
        [_err_event(wmo, "No telemetry files found for WMO 2901305",
                    operation="no_input_files")],
        "no input files found for WMO 2901305 under /home/user/phase4_reference/raw/raw-files: nothing was decoded",
    )
    assert r.category == CATEGORY_MISSING_INPUT_FILES
    assert "2901305" in r.root_cause


def test_corrupted_input():
    wmo = 2901304
    r = triage_failed_float(
        wmo, "error", _run(wmo), [],
        "Corrupted cycle frame checksum in raw telemetry chunk 4",
    )
    assert r.category == CATEGORY_CORRUPTED_INPUT
    assert "checksum" in r.root_cause.lower()


def test_config_path_error():
    wmo = 2901304
    r = triage_failed_float(
        wmo, "error", _run(wmo), [],
        "[Errno 21] Is a directory: '/home/user/updated-/config/metadata'",
    )
    assert r.category == CATEGORY_CONFIG_PATH_ERROR


def test_decoder_error_traceback_fallback():
    wmo = 6903014
    tb = (
        'Traceback (most recent call last):\n'
        '  File "x.py", line 1, in <module>\n'
        'ValueError: some decoder-internal condition'
    )
    r = triage_failed_float(wmo, "error", _run(wmo), [], tb)
    assert r.category == CATEGORY_DECODER_ERROR
    assert r.root_cause == "ValueError: some decoder-internal condition"


def test_user_stopped():
    wmo = 2902201
    r = triage_failed_float(wmo, "stopped", _run(wmo), [], "Batch stopped by user")
    assert r.category == CATEGORY_USER_STOPPED


def test_unclassified_preserves_raw_error():
    wmo = 1902844
    weird = "something the classifier has never seen before"
    r = triage_failed_float(wmo, "error", _run(wmo), [], weird)
    assert r.category == CATEGORY_UNCLASSIFIED
    assert r.root_cause == weird  # raw error preserved, never hidden


def test_no_evidence_at_all():
    wmo = 1234567
    r = triage_failed_float(wmo, "error", None, [], None, run_id=None)
    assert r.category == CATEGORY_UNCLASSIFIED
    assert r.root_cause  # still returns a (honest) root cause string
