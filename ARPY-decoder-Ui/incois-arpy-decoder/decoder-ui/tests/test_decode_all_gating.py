"""Unit tests for the Decode-All idempotency gate (api.start_batch_decode).

Contract under test:

* When EVERY currently eligible float already has a genuinely successful
  run from today, POST /batch/decode-all must NOT create another batch —
  the response advertises ``status="already_complete"`` + the existing
  completed batch to open in Results, and batch history stays untouched.
* When some floats are failed/stopped/incomplete, the existing rules hold
  (new batch; cached floats carried over; the rest decoded).
* force=True (Re-run All) always starts a fresh batch.
* An ACTIVE batch always wins with HTTP 409 — even when runs are cached.

Run with:
    cd decoder-ui && PYTHONPATH=service python -m pytest tests/test_decode_all_gating.py -q
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import types

import pytest
from fastapi import HTTPException

# Isolate every test case's EventBus from the deployment's persisted
# run/batch data (the constructor recovers state from ARGO_UI_DATA_DIR).
os.environ.setdefault(
    "ARGO_UI_DATA_DIR", tempfile.mkdtemp(prefix="decoder-ui-gating-test-")
)

import api
from event_bus import EventBus
from models import (
    BatchDecodeRequest,
    BatchFloatItem,
    BatchSummary,
    NodeStatus,
    OutputFileInfo,
    RunSummary,
)

WMOS = [2901304, 2901339, 2902201, 2902203]
PRESETS = [
    {"wmo": w, "platform_type": "APEX", "transmission_type": "IRIDIUM", "decoder_id": 1}
    for w in WMOS
]


class _Pool:
    """Executor stub — records submissions, never runs the worker."""

    def __init__(self):
        self.submitted: list[tuple] = []

    def submit(self, fn, *args):
        self.submitted.append((fn, args))


def _today_success_run(wmo: int) -> RunSummary:
    return RunSummary(
        run_id=f"run-success-{wmo}",
        wmo=wmo,
        status=NodeStatus.COMPLETED,
        total_cycles=10,
        completed_cycles=10,
        profile_count=10,
        output_files=[OutputFileInfo(filename=f"{wmo}.nc", category="other", filepath=f"/tmp/{wmo}.nc")],
    )


def _completed_batch(batch_id: str, wmos: list[int] = WMOS) -> BatchSummary:
    items = []
    for w in wmos:
        item = BatchFloatItem(wmo=w, status=NodeStatus.COMPLETED, run_id=f"run-success-{w}")
        items.append(item)
    return BatchSummary(
        batch_id=batch_id,
        name="Today's Fleet Telemetry Ingestion",
        status=NodeStatus.COMPLETED,
        total_floats=len(items),
        completed_floats=len(items),
        items=items,
    )


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Isolated EventBus + preset + executor wiring for each test."""

    class IsolatedBus(EventBus):
        def _recover_orphaned_state(self) -> None:  # never inherit run history
            self._orphaned_runs = set()
            self._orphaned_batches = set()

    bus = IsolatedBus()
    # Redirect every run/batch file write the worker paths would emit
    # (nothing real is decoded in these tests, but keep disk fully clean).
    (tmp_path / "runs").mkdir()
    (tmp_path / "batches").mkdir()
    monkeypatch.setattr("event_bus.RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr("event_bus.BATCHES_DIR", tmp_path / "batches")
    pool = _Pool()
    monkeypatch.setattr(api, "bus", bus)
    monkeypatch.setattr(api.path_resolver, "build_dynamic_float_presets", lambda: PRESETS)
    monkeypatch.setattr(api, "thread_pool", pool)
    # email/base-url resolution is read-only; keep it deterministic
    monkeypatch.setattr(
        "email_notifier.resolve_app_base_url", lambda hint=None: "http://localhost:8000", raising=False
    )
    req = types.SimpleNamespace(headers={})
    return types.SimpleNamespace(bus=bus, pool=pool, request=req)


def _post(env, body: BatchDecodeRequest):
    return asyncio.run(api.start_batch_decode(body, env.request))


def _store_success(env, wmo: int):
    env.bus.store_run(_today_success_run(wmo))


def _store_completed_batch(env, batch_id: str = "batch-complete-1", wmos: list[int] = WMOS):
    env.bus.store_batch(_completed_batch(batch_id, wmos))


# ---------------------------------------------------------------------------
# 1. Everything already processed -> NO new batch, already_complete payload
# ---------------------------------------------------------------------------

def test_already_complete_returns_existing_batch_and_creates_nothing(env):
    _store_completed_batch(env)
    for w in WMOS:
        _store_success(env, w)

    before = [b.batch_id for b in env.bus.get_all_batches()]
    result = _post(env, BatchDecodeRequest())

    assert result["status"] == "already_complete"
    assert result["message"] == api.ALREADY_COMPLETE_MESSAGE
    assert result["message"] == (
        "Today's fleet decoding is already complete. "
        "All currently detected floats have already been processed."
    )
    assert result["batch_id"] == "batch-complete-1"
    assert result["total_floats"] == len(WMOS)
    assert result["cached_floats"] == len(WMOS)
    assert result["to_decode"] == 0
    # no new batch, no worker, history untouched (append-only stayed at 1)
    assert [b.batch_id for b in env.bus.get_all_batches()] == before
    assert env.pool.submitted == []


def test_already_complete_no_completed_batch_yields_none_batch_id(env):
    for w in WMOS:
        _store_success(env, w)
    result = _post(env, BatchDecodeRequest())
    assert result["status"] == "already_complete"
    assert result["batch_id"] is None
    assert env.bus.get_all_batches() == []


def test_already_complete_decision_comes_from_real_current_state(env):
    """Only floats with TODAY's genuinely-successful runs count: a float with
    a successful run yesterday (or a completed-but-empty run today) is NOT
    'already processed'."""
    for w in WMOS[:-1]:
        _store_success(env, w)
    # yesterday's success for float 4 must not satisfy the gate
    stale = _today_success_run(WMOS[-1])
    stale.start_time = "2001-01-02T03:04:05+00:00"
    env.bus.store_run(stale)
    # completed-but-empty run today must not satisfy the gate either
    empty = _today_success_run(WMOS[-1])
    empty.completed_cycles = 0
    empty.profile_count = 0
    empty.output_files = []
    empty.run_id = "run-empty"
    env.bus.store_run(empty)

    result = _post(env, BatchDecodeRequest())
    assert result["status"] == "started", f"expected a real batch, got {result}"
    assert result["to_decode"] == 1
    batch = env.bus.get_batch(result["batch_id"])
    assert batch is not None
    statuses = {i.wmo: i.status for i in batch.items}
    assert statuses[WMOS[-1]] == NodeStatus.PENDING
    assert all(statuses[w] == NodeStatus.COMPLETED for w in WMOS[:-1])
    assert len(env.pool.submitted) == 1


def test_already_complete_covers_subset_requests(env):
    """wmos=[A,B] with today's successes for A,B only -> complete for the subset."""
    _store_completed_batch(env, wmos=WMOS[:2])
    _store_success(env, WMOS[0])
    _store_success(env, WMOS[1])
    result = _post(env, BatchDecodeRequest(wmos=WMOS[:2]))
    assert result["status"] == "already_complete"
    assert result["floats"] == WMOS[:2]


# ---------------------------------------------------------------------------
# 2. force=True (Re-run All) always creates a fresh batch
# ---------------------------------------------------------------------------

def test_force_always_reruns_everything(env):
    _store_completed_batch(env)
    for w in WMOS:
        _store_success(env, w)
    result = _post(env, BatchDecodeRequest(force=True))
    assert result["status"] == "started"
    assert result["cached_floats"] == 0
    assert result["to_decode"] == len(WMOS)
    batch = env.bus.get_batch(result["batch_id"])
    assert all(i.status == NodeStatus.PENDING and not i.cached for i in batch.items)
    assert len(env.pool.submitted) == 1


# ---------------------------------------------------------------------------
# 3. An ACTIVE batch always wins (409), even when everything is cached
# ---------------------------------------------------------------------------

def test_active_batch_blocks_with_409_even_when_all_cached(env):
    active = BatchSummary(
        batch_id="batch-active-1",
        status=NodeStatus.ACTIVE,
        total_floats=len(WMOS),
        pending_floats=len(WMOS),
        items=[BatchFloatItem(wmo=w) for w in WMOS],
    )
    env.bus.store_batch(active)
    for w in WMOS:
        _store_success(env, w)
    with pytest.raises(HTTPException) as ei:
        _post(env, BatchDecodeRequest())
    assert ei.value.status_code == 409
    assert ei.value.detail["active_batch_id"] == "batch-active-1"
    # still exactly one batch, nothing extra recorded or submitted
    assert len(env.bus.get_all_batches()) == 1
    assert env.pool.submitted == []


# ---------------------------------------------------------------------------
# 4. Batch-covering helper picks the right completed batch to open
# ---------------------------------------------------------------------------

def test_results_batch_prefers_newest_covering_completed(env):
    env.bus.store_batch(_completed_batch("batch-old", wmos=WMOS[:1]))
    env.bus.store_batch(_completed_batch("batch-covering", wmos=WMOS))
    assert env.bus.find_results_batch_for_floats(WMOS) == "batch-covering"
    assert env.bus.find_results_batch_for_floats([WMOS[0]]) == "batch-covering"
    assert env.bus.find_results_batch_for_floats([1234567]) == "batch-covering"  # fallback: newest completed
