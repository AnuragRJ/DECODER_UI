"""Regression tests for the 'View Decoder Error' email deep-link pipeline.

Covers the exact values the email emits and the guarantees the UI depends on:

  * link shape  : {base}/?run_id={run_id}&focus=error[&event_id={event_id}]
  * base URL    : APP_BASE_URL env > valid request Origin > localhost default
  * persistence : EventBus.ensure_run_persisted so every emailed run_id
                  resolves against on-disk run/event data

Run with:
    cd decoder-ui && PYTHONPATH=service python -m pytest tests/test_email_deeplink.py -q
"""

from __future__ import annotations

import os
import re
import types

import pytest

import event_bus
from event_bus import EventBus, RUNS_DIR
from email_notifier import build_batch_email_content, resolve_app_base_url
from models import BatchFloatItem, BatchSummary, NodeStatus, RunSummary


# ---------------------------------------------------------------------------
# resolve_app_base_url
# ---------------------------------------------------------------------------

@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.delenv("APP_BASE_URL", raising=False)
    monkeypatch.delenv("DECODER_UI_URL", raising=False)
    yield


def test_origin_used_when_no_env(clean_env):
    assert resolve_app_base_url("https://3000-abc.e2b.app") == "https://3000-abc.e2b.app"
    # trailing slash normalised
    assert resolve_app_base_url("http://localhost:3000/") == "http://localhost:3000"


def test_default_when_no_env_no_origin(clean_env):
    assert resolve_app_base_url(None) == "http://localhost:3000"


def test_invalid_scheme_falls_back(clean_env):
    assert resolve_app_base_url("javascript:alert(1)") == "http://localhost:3000"
    assert resolve_app_base_url("ftp://files.example.com") == "http://localhost:3000"


def test_env_wins_over_origin(monkeypatch):
    monkeypatch.setenv("APP_BASE_URL", "https://fixed.example.com")
    assert resolve_app_base_url("https://3000-abc.e2b.app") == "https://fixed.example.com"


# ---------------------------------------------------------------------------
# build_batch_email_content — link construction
# ---------------------------------------------------------------------------

def _failed_batch() -> BatchSummary:
    item = BatchFloatItem(
        wmo=6902892,
        status=NodeStatus.ERROR,
        run_id="run-6902892-abc123",
        error_message="No info JSON found for WMO 6902892",
    )
    return BatchSummary(
        batch_id="batch-test-deeplink",
        name="test",
        status=NodeStatus.COMPLETED,
        total_floats=1,
        pending_floats=0,
        completed_floats=0,
        failed_floats=1,
        items=[item],
    )


def _report_with_failure(event_id: str | None):
    failure = types.SimpleNamespace(
        paragraph="A deterministic test failure paragraph.",
        event_id=event_id,
    )
    float_rep = types.SimpleNamespace(wmo=6902892, failure=failure)
    return types.SimpleNamespace(floats=[float_rep])


def _links(text: str) -> list[str]:
    return re.findall(r"View Decoder Error:\s*(\S+)", text)


def test_link_shape_with_event_id(clean_env):
    batch = _failed_batch()
    text, html = build_batch_email_content(
        batch,
        report_data=_report_with_failure("evt-111111"),
        pdf_available=False,
        app_base_url="https://ui.example.com",
    )
    assert _links(text) == [
        "https://ui.example.com/?run_id=run-6902892-abc123&focus=error&event_id=evt-111111"
    ]
    # HTML href must carry the identical URL
    assert 'href="https://ui.example.com/?run_id=run-6902892-abc123&focus=error&event_id=evt-111111"' in html


def test_link_omits_event_id_when_absent(clean_env):
    batch = _failed_batch()
    text, _ = build_batch_email_content(
        batch,
        report_data=_report_with_failure(None),
        pdf_available=False,
        app_base_url="https://ui.example.com",
    )
    assert _links(text) == [
        "https://ui.example.com/?run_id=run-6902892-abc123&focus=error"
    ]


def test_default_base_url(clean_env):
    batch = _failed_batch()
    text, _ = build_batch_email_content(batch, report_data=_report_with_failure(None))
    assert _links(text) == [
        "http://localhost:3000/?run_id=run-6902892-abc123&focus=error"
    ]


def test_no_failure_section_for_success_batch(clean_env):
    item = BatchFloatItem(wmo=2902201, status=NodeStatus.COMPLETED, run_id="run-2902201-zz")
    batch = BatchSummary(
        batch_id="batch-test-ok",
        name="test",
        status=NodeStatus.COMPLETED,
        total_floats=1,
        pending_floats=0,
        completed_floats=1,
        failed_floats=0,
        items=[item],
    )
    text, _ = build_batch_email_content(batch, report_data=types.SimpleNamespace(floats=[]))
    assert "View Decoder Error" not in text


# ---------------------------------------------------------------------------
# EventBus.ensure_run_persisted
# ---------------------------------------------------------------------------

def test_ensure_run_persisted_writes_missing_file(tmp_path, monkeypatch):
    bus = event_bus.bus
    monkeypatch.setattr(event_bus, "RUNS_DIR", tmp_path)
    run_id = "run-7777777-selftest"

    run = RunSummary(
        run_id=run_id, wmo=7777777, status=NodeStatus.ERROR,
        active_operation="test", errors=["test error"],
    )
    bus._runs[run_id] = run
    try:
        assert not (tmp_path / f"{run_id}.json").exists()
        assert bus.ensure_run_persisted(run_id) is True
        assert (tmp_path / f"{run_id}.json").exists()

        # already present -> still True (no-op)
        assert bus.ensure_run_persisted(run_id) is True

        # unknown run -> False
        assert bus.ensure_run_persisted("run-0000000-ghost") is False
    finally:
        bus._runs.pop(run_id, None)
        bus._events.pop(run_id, None)


def test_real_runs_dir_intact():
    # sanity: the module-level RUNS_DIR still points at the real store
    assert RUNS_DIR.name == "runs"
