"""Event bus for broadcasting real-time decoding execution events and persisting run history."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from fastapi import WebSocket

from models import LiveEvent, RunSummary, BatchSummary, StageId, StageState, NodeStatus

# Runtime persistence root. Overridable (ARGO_UI_DATA_DIR) so tests and
# parallel deployments can use an isolated, fresh data directory without
# touching the workspace's operational history.
DATA_DIR = Path(os.environ.get("ARGO_UI_DATA_DIR") or (Path(__file__).resolve().parent.parent / "data"))
RUNS_DIR = DATA_DIR / "runs"
BATCHES_DIR = DATA_DIR / "batches"


def _parse_iso(ts: str | None) -> datetime | None:
    """Tolerantly parse an ISO-8601 timestamp (accepts trailing 'Z')."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _is_today_local(ts: str | None) -> bool:
    """True when ``ts`` falls on the current calendar day in the server's local timezone.

    'Today' is the operator-visible day boundary the product language uses
    ("Decode All TODAY'S Floats"), so the local date — not a rolling 24 h
    window — is the correct cache boundary.
    """
    dt = _parse_iso(ts)
    if dt is None:
        return False
    return dt.astimezone().date() == datetime.now().astimezone().date()


# Operation names for pre-run gate events, keyed by the stage the missing
# dependency belongs to. Kept stable: triage categories match on these.
_PRE_RUN_OPERATIONS: dict[str, str] = {
    StageId.INPUT_FILES.value: "stage_input_files",
    StageId.METADATA.value: "stage_metadata",
    StageId.CONFIGURATION.value: "pre_run_configuration",
}


def build_prerun_failure_record(
    *,
    run_id: str,
    wmo: int,
    problems: list[tuple[str, str]],
    error_type: str | None = None,
    platform_type: str = "",
    transmission_type: str = "",
    decoder_id: int | None = None,
) -> tuple[RunSummary, list[LiveEvent]]:
    """Build a minimal ERROR run record + one error event per pre-run problem.

    Used when a failure happens BEFORE the decoder pipeline runs (CTS4
    staging gate, batch config setup): previously these left no run record
    at all, so Investigate opened a 404 and the UI fell back to showing an
    unrelated older run. One problem yields at least one error-level event
    so the failure is always investigable.

    Pure function — no disk or socket I/O — so unit tests can verify the
    record shape without touching the workspace. ``problems`` is a list of
    ``(stage_id, message)`` pairs; unknown stage ids map to CONFIGURATION.
    """
    if not problems:
        problems = [(StageId.CONFIGURATION.value, error_type or "pre-run failure")]

    now = datetime.now(timezone.utc).isoformat()
    stages: dict[StageId, StageState] = {
        stg: StageState(id=stg, name=stg.value.replace("_", " "), status=NodeStatus.PENDING)
        for stg in StageId
    }
    failed_stages: list[StageId] = []
    for stage_id, message in problems:
        try:
            stage = StageId(stage_id)
        except ValueError:
            stage = StageId.CONFIGURATION
        stages[stage].status = NodeStatus.ERROR
        stages[stage].detail = message
        stages[stage].updated_at = now
        if stage not in failed_stages:
            failed_stages.append(stage)

    messages = [message for _, message in problems]
    summary = RunSummary(
        run_id=run_id,
        wmo=wmo,
        float_type=platform_type,
        transmission_type=transmission_type,
        decoder_id=decoder_id,
        status=NodeStatus.ERROR,
        start_time=now,
        end_time=now,
        duration_seconds=0.0,
        active_stage=failed_stages[0],
        active_operation=f"Pre-run check failed: {messages[0]}",
        stages=stages,
        errors=messages,
    )

    events: list[LiveEvent] = []
    for stage_id, message in problems:
        try:
            stage = StageId(stage_id)
        except ValueError:
            stage = StageId.CONFIGURATION
        events.append(
            LiveEvent(
                id=f"evt-prerun-{uuid.uuid4().hex[:8]}",
                run_id=run_id,
                level="error",
                message=message,
                stage=stage,
                operation=_PRE_RUN_OPERATIONS.get(
                    stage.value, _PRE_RUN_OPERATIONS[StageId.CONFIGURATION.value]
                ),
                status=NodeStatus.ERROR,
                what_happened=(
                    "A pre-run gate failed before the decoder pipeline started; "
                    "no decode stages ran. Fix the missing dependency and re-run this float."
                ),
                python_file="decoder-ui/service/api.py",
                python_function="_run_cts4_batch_item" if error_type == "MissingInput" else "_run_batch_worker",
                data_sample={"pre_run": True, "error_type": error_type},
                timestamp=now,
            )
        )
    return summary, events


class EventBus:
    """Thread-safe and async-safe EventBus for real-time observability and persistent history."""

    def __init__(self) -> None:
        self._websockets: list[WebSocket] = []
        self._sse_queues: list[asyncio.Queue[dict[str, Any]]] = []
        self._runs: dict[str, RunSummary] = {}
        self._events: dict[str, list[LiveEvent]] = defaultdict(list)
        self._batches: dict[str, BatchSummary] = {}
        self._cancelled_runs: set[str] = set()
        self._cancelled_batches: set[str] = set()
        self._disk_lock = threading.Lock()
        # Serialises the "is a batch already active?" check with batch creation
        # so concurrent Decode-All requests (two tabs, rapid re-clicks, repeated
        # API calls) can never both pass the check and both create a batch.
        self._batch_create_lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        # Tracks the last terminal status pushed to live clients per run, so a
        # terminal RunSummary is broadcast exactly once even though the bus may
        # hold a reference to the already-mutated summary object.
        self._last_broadcast_status: dict[str, Any] = {}

        # Ensure storage directories exist
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        BATCHES_DIR.mkdir(parents=True, exist_ok=True)

        # Load persisted runs and batches from disk, then recover anything the
        # previous process left behind (orphaned 'active' records, stale tmps).
        self._load_from_disk()
        self._recover_orphaned_state()
        self._sweep_stale_tmp_files()

    def _load_from_disk(self) -> None:
        """Load previously saved runs and batches from disk."""
        try:
            if RUNS_DIR.exists():
                for f in RUNS_DIR.glob("*.json"):
                    try:
                        with open(f, "r", encoding="utf-8") as fp:
                            data = json.load(fp)
                        summary_data = data.get("summary")
                        events_data = data.get("events", [])
                        if summary_data:
                            run = RunSummary.model_validate(summary_data)
                            self._runs[run.run_id] = run
                            ev_list = [LiveEvent.model_validate(e) for e in events_data]
                            self._events[run.run_id] = ev_list
                    except Exception as err:
                        print(f"Failed to load run file {f.name}: {err}")

            if BATCHES_DIR.exists():
                for f in BATCHES_DIR.glob("*.json"):
                    try:
                        with open(f, "r", encoding="utf-8") as fp:
                            data = json.load(fp)
                        batch = BatchSummary.model_validate(data)
                        self._batches[batch.batch_id] = batch
                    except Exception as err:
                        print(f"Failed to load batch file {f.name}: {err}")
        except Exception as e:
            print(f"Error loading persisted runs/batches: {e}")

    def _recover_orphaned_state(self) -> None:
        """Reconcile persisted records that claim to be live but cannot be.

        Any run/batch persisted as ``active`` was written by *this* process in
        a previous life; a freshly started process has no worker threads, so a
        persisted-active record means the previous process died mid-execution.
        Mark it STOPPED + ``orphaned`` so it reads as *interrupted* — never as
        currently live — while keeping every event, cycle and artifact that was
        already captured.
        """
        now = datetime.now(timezone.utc).isoformat()
        for run in list(self._runs.values()):
            if run.status == NodeStatus.ACTIVE:
                run.status = NodeStatus.STOPPED
                run.orphaned = True
                run.end_time = run.end_time or now
                run.active_operation = "Interrupted: workstation restarted"
                if "Interrupted by workstation restart" not in run.errors:
                    run.errors = [
                        *run.errors,
                        "Run was active when the workstation process ended; marked interrupted on startup.",
                    ]
                self._persist_run_to_disk(run.run_id)
                print(f"Recovered orphaned active run {run.run_id} (WMO {run.wmo}) -> interrupted")
        for batch in list(self._batches.values()):
            if batch.status == NodeStatus.ACTIVE:
                batch.status = NodeStatus.STOPPED
                batch.orphaned = True
                batch.ended_at = batch.ended_at or now
                batch.running_wmo = None
                batch.running_run_id = None
                for item in batch.items:
                    if item.status in (NodeStatus.PENDING, NodeStatus.ACTIVE):
                        item.status = NodeStatus.STOPPED
                        item.error_message = "Interrupted: workstation restarted"
                batch.stopped_floats = len(
                    [i for i in batch.items if i.status in (NodeStatus.STOPPED, NodeStatus.CANCELLED)]
                )
                batch.pending_floats = 0
                self._persist_batch_to_disk(batch.batch_id)
                print(f"Recovered orphaned active batch {batch.batch_id} -> interrupted")

    def _sweep_stale_tmp_files(self) -> None:
        """Remove orphaned ``*.json.tmp`` files left by a crash during an atomic write.

        Tmp files exist only between write and ``os.replace``; at startup no
        writes are in flight, so every tmp present is guaranteed stale. Final
        JSONs (if any) are untouched.
        """
        for directory in (RUNS_DIR, BATCHES_DIR):
            try:
                for tmp in directory.glob("*.json.tmp"):
                    try:
                        tmp.unlink()
                        print(f"Removed stale atomic-write residue {tmp.name}")
                    except OSError:
                        pass
            except OSError:
                pass

    def find_cached_successful_run(self, wmo: int) -> RunSummary | None:
        """Return this float's newest genuinely-successful run from *today*, if any.

        'Genuinely successful' means the run completed AND produced decoded
        content — a run that ended COMPLETED but decoded nothing (zero cycles,
        zero profiles or no output files) is treated as incomplete and the
        float remains eligible for decoding. Runs whose status is anything but
        COMPLETED (failed, stopped, partial) never qualify.
        """
        candidates: list[RunSummary] = []
        for run in self._runs.values():
            if run.wmo != wmo or run.status != NodeStatus.COMPLETED or run.orphaned:
                continue
            if not _is_today_local(run.start_time):
                continue
            if (run.completed_cycles or 0) <= 0 and (run.profile_count or 0) <= 0:
                continue  # nothing decoded — do not treat as a day's success
            if not run.output_files:
                continue  # missing required outputs — re-run allowed
            candidates.append(run)
        if not candidates:
            return None
        candidates.sort(key=lambda r: _parse_iso(r.start_time) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return candidates[0]

    def get_active_batch(self) -> BatchSummary | None:
        for batch in self._batches.values():
            if batch.status == NodeStatus.ACTIVE and not batch.orphaned:
                return batch
        return None

    def create_batch_exclusive(self, batch: BatchSummary) -> BatchSummary | None:
        """Atomically store ``batch`` iff no other batch is currently active.

        Returns the already-active batch when one exists (caller should refuse
        with HTTP 409); returns None when creation succeeded. The check-and-
        create is serialized so concurrent Decode-All requests cannot both
        create batches even under two tabs or repeated API calls.
        """
        with self._batch_create_lock:
            active = self.get_active_batch()
            if active is not None:
                return active
            self.store_batch(batch)
            return None

    def _persist_run_to_disk_async(self, run_id: str) -> None:
        """Persist run to disk in a separate background thread to avoid blocking execution."""
        threading.Thread(target=self._persist_run_to_disk, args=(run_id,), daemon=True).start()

    def _persist_run_to_disk(self, run_id: str) -> None:
        """Save run summary and full event history to a JSON file atomically."""
        run = self._runs.get(run_id)
        if not run:
            return
        events = list(self._events.get(run_id, []))
        filepath = RUNS_DIR / f"{run_id}.json"
        tmppath = RUNS_DIR / f"{run_id}.json.tmp"
        try:
            with self._disk_lock:
                with open(tmppath, "w", encoding="utf-8") as fp:
                    json.dump(
                        {
                            "summary": run.model_dump(),
                            "events": [e.model_dump() for e in events],
                        },
                        fp,
                        default=str,
                    )
                os.replace(tmppath, filepath)
        except Exception as err:
            print(f"Error persisting run {run_id} to disk: {err}")

    def ensure_run_persisted(self, run_id: str) -> bool:
        """Synchronously guarantee the run's JSON file exists on disk.

        Used before batch summary emails are built so every deep link in the
        email points at run data the API can serve after a restart. The run
        must already be in memory; if it is, the write is a fast no-op when
        the file already exists. Returns True when the run file is available.
        """
        run = self._runs.get(run_id)
        if not run:
            return False
        filepath = RUNS_DIR / f"{run_id}.json"
        if filepath.exists():
            return True
        self._persist_run_to_disk(run_id)
        return filepath.exists()

    def _persist_batch_to_disk(self, batch_id: str) -> None:
        """Save batch summary to a JSON file atomically."""
        batch = self._batches.get(batch_id)
        if not batch:
            return
        filepath = BATCHES_DIR / f"{batch_id}.json"
        tmppath = BATCHES_DIR / f"{batch_id}.json.tmp"
        try:
            with self._disk_lock:
                with open(tmppath, "w", encoding="utf-8") as fp:
                    json.dump(batch.model_dump(), fp, default=str)
                os.replace(tmppath, filepath)
        except Exception as err:
            print(f"Error persisting batch {batch_id} to disk: {err}")

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def cancel_run(self, run_id: str) -> None:
        """Mark a run as cancelled/stopped by user."""
        self._cancelled_runs.add(run_id)
        run = self._runs.get(run_id)
        if run and run.status == NodeStatus.ACTIVE:
            run.active_operation = "Cancellation requested... stopping worker"
            if self._loop and self._loop.is_running():
                asyncio.run_coroutine_threadsafe(self.broadcast_run_update(run), self._loop)

    def is_run_cancelled(self, run_id: str) -> bool:
        return run_id in self._cancelled_runs

    def cancel_batch(self, batch_id: str) -> None:
        """Mark a batch as cancelled/stopped by user and stop current running run."""
        self._cancelled_batches.add(batch_id)
        batch = self._batches.get(batch_id)
        if batch:
            batch.status = NodeStatus.STOPPED
            for item in batch.items:
                if item.status == NodeStatus.PENDING:
                    item.status = NodeStatus.STOPPED
                    item.error_message = "Batch stopped by user"
            batch.stopped_floats = len([i for i in batch.items if i.status in (NodeStatus.STOPPED, NodeStatus.CANCELLED)])
            batch.pending_floats = 0
            if batch.running_run_id:
                self.cancel_run(batch.running_run_id)
            self.broadcast_batch_update_sync(batch)
            self._persist_batch_to_disk(batch.batch_id)

    def is_batch_cancelled(self, batch_id: str) -> bool:
        return batch_id in self._cancelled_batches

    async def register_ws(self, ws: WebSocket) -> None:
        await ws.accept()
        self._websockets.append(ws)

    async def unregister_ws(self, ws: WebSocket) -> None:
        if ws in self._websockets:
            self._websockets.remove(ws)

    def register_sse(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=5000)
        self._sse_queues.append(q)
        return q

    def unregister_sse(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        if q in self._sse_queues:
            self._sse_queues.remove(q)

    def store_run(self, run: RunSummary) -> None:
        existing = self._runs.get(run.run_id)
        if existing and existing.status == NodeStatus.STOPPED and run.status != NodeStatus.STOPPED:
            run.status = NodeStatus.STOPPED
            run.active_operation = "Stopped by user"
        self._runs[run.run_id] = run
        if run.status in (NodeStatus.COMPLETED, NodeStatus.STOPPED, NodeStatus.ERROR):
            self._persist_run_to_disk_async(run.run_id)
            # The final RunSummary is the authoritative terminal state, and it
            # is stored AFTER the pipeline_end event (artifact extraction runs
            # in between, during which /api/runs* still reports "active").
            # Push it to every live client so the UI transitions to the final
            # state as soon as the backend run actually finishes, instead of
            # relying on poll snapshots (which may have been captured while
            # the summary was still active) or on no state update at all.
            #
            # Note: the bus may already hold a reference to the very object
            # the caller mutated (summary.status is set before store_run is
            # called), so detect "transition into terminal" via the status
            # last broadcast for this run_id, not via `existing`.
            if (
                self._last_broadcast_status.get(run.run_id) != run.status
                and self._loop is not None
                and self._loop.is_running()
            ):
                self._last_broadcast_status[run.run_id] = run.status
                asyncio.run_coroutine_threadsafe(self.broadcast_run_update(run), self._loop)

    def record_prerun_failure(
        self,
        *,
        run_id: str,
        wmo: int,
        problems: list[tuple[str, str]],
        error_type: str | None = None,
        platform_type: str = "",
        transmission_type: str = "",
        decoder_id: int | None = None,
    ) -> RunSummary:
        """Persist a minimal ERROR run record + error events for a failure
        that happened before the decoder pipeline ran. The record goes
        through the same store/persist path as normal runs so Investigate,
        triage and email deep links all resolve to the real failure."""
        summary, events = build_prerun_failure_record(
            run_id=run_id,
            wmo=wmo,
            problems=problems,
            error_type=error_type,
            platform_type=platform_type,
            transmission_type=transmission_type,
            decoder_id=decoder_id,
        )
        # Register events BEFORE store_run: the async disk persist reads both.
        self._events[run_id] = events
        self.store_run(summary)
        return summary

    def get_run(self, run_id: str) -> RunSummary | None:
        return self._runs.get(run_id)

    def get_all_runs(self) -> list[RunSummary]:
        return sorted(self._runs.values(), key=lambda r: r.start_time, reverse=True)

    def store_batch(self, batch: BatchSummary) -> None:
        existing = self._batches.get(batch.batch_id)
        if existing and existing.status == NodeStatus.STOPPED and batch.status != NodeStatus.STOPPED:
            batch.status = NodeStatus.STOPPED
        self._batches[batch.batch_id] = batch
        self._persist_batch_to_disk(batch.batch_id)

    def get_batch(self, batch_id: str) -> BatchSummary | None:
        return self._batches.get(batch_id)

    def get_all_batches(self) -> list[BatchSummary]:
        return sorted(self._batches.values(), key=lambda b: b.created_at, reverse=True)

    def get_latest_batch(self) -> BatchSummary | None:
        batches = self.get_all_batches()
        return batches[0] if batches else None

    def find_results_batch_for_floats(self, wmos: list[int]) -> str | None:
        """Best existing batch to open in Results for this set of floats.

        Preference order (newest first, batches are never mutated/reused):
        1. a COMPLETED batch whose items cover every requested WMO,
        2. any COMPLETED batch.
        Returns the batch id, or None when no completed batch exists yet.
        Used to answer "already complete" Decode-All requests without
        creating a redundant batch — history stays append-only.
        """
        batches = self.get_all_batches()  # newest first
        wanted = set(wmos)
        for b in batches:
            if b.orphaned or b.status != NodeStatus.COMPLETED:
                continue
            have = {i.wmo for i in b.items or []}
            if wanted and wanted.issubset(have):
                return b.batch_id
        for b in batches:
            if not b.orphaned and b.status == NodeStatus.COMPLETED:
                return b.batch_id
        return None

    def get_events(self, run_id: str, limit: int = 5000, offset: int = 0) -> list[LiveEvent]:
        events = self._events.get(run_id, [])
        return events[offset : offset + limit]

    def emit_sync(self, event: LiveEvent) -> None:
        """Called from synchronous backend code to publish an event."""
        if self._loop is not None and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self.emit(event), self._loop)
        else:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.run_coroutine_threadsafe(self.emit(event), loop)
                else:
                    loop.run_until_complete(self.emit(event))
            except RuntimeError:
                self._events[event.run_id].append(event)

    async def emit(self, event: LiveEvent) -> None:
        """Asynchronously record, broadcast, and store event."""
        self._events[event.run_id].append(event)
        
        # Update run summary if present
        run = self._runs.get(event.run_id)
        if run:
            if event.stage:
                run.active_stage = event.stage
                if event.stage not in run.stages:
                    run.stages[event.stage] = StageState(
                        id=event.stage,
                        name=event.stage.value.replace("_", " "),
                        status=event.status,
                    )
                stage_state = run.stages[event.stage]
                stage_state.status = event.status
                if event.status in (NodeStatus.COMPLETED, NodeStatus.STOPPED, NodeStatus.ERROR):
                    stage_state.active_operation = ""
                elif event.operation:
                    stage_state.active_operation = event.operation
                    run.active_operation = event.operation
                if event.cycle is not None:
                    stage_state.current_cycle = event.cycle
                stage_state.detail = event.message
            
            if event.level == "error" and event.error_details:
                if event.error_details not in run.errors:
                    run.errors.append(event.error_details)

        payload = {
            "type": "event",
            "data": event.model_dump(),
        }

        # Broadcast to WebSockets
        dead_ws = []
        for ws in self._websockets:
            try:
                await ws.send_text(json.dumps(payload))
            except Exception:
                dead_ws.append(ws)
        for ws in dead_ws:
            await self.unregister_ws(ws)

        # Broadcast to SSE queues
        for q in self._sse_queues:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass

        if event.stage == StageId.DONE or event.status in (NodeStatus.COMPLETED, NodeStatus.STOPPED, NodeStatus.ERROR):
            self._persist_run_to_disk_async(event.run_id)

    async def broadcast_run_update(self, run: RunSummary) -> None:
        """Broadcast updated run status."""
        self._runs[run.run_id] = run
        if run.status in (NodeStatus.COMPLETED, NodeStatus.STOPPED, NodeStatus.ERROR):
            self._persist_run_to_disk_async(run.run_id)

        payload = {
            "type": "run_update",
            "data": run.model_dump(),
        }
        dead_ws = []
        for ws in self._websockets:
            try:
                await ws.send_text(json.dumps(payload))
            except Exception:
                dead_ws.append(ws)
        for ws in dead_ws:
            await self.unregister_ws(ws)

        for q in self._sse_queues:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    def broadcast_batch_update_sync(self, batch: BatchSummary) -> None:
        """Synchronous helper for batch updates from worker threads."""
        self._batches[batch.batch_id] = batch
        self._persist_batch_to_disk(batch.batch_id)
        if self._loop is not None and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self.broadcast_batch_update(batch), self._loop)

    async def broadcast_batch_update(self, batch: BatchSummary) -> None:
        """Broadcast updated batch status to clients."""
        self._batches[batch.batch_id] = batch
        self._persist_batch_to_disk(batch.batch_id)
        payload = {
            "type": "batch_update",
            "data": batch.model_dump(),
        }
        dead_ws = []
        for ws in self._websockets:
            try:
                await ws.send_text(json.dumps(payload))
            except Exception:
                dead_ws.append(ws)
        for ws in dead_ws:
            await self.unregister_ws(ws)

        for q in self._sse_queues:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass


# Global singleton EventBus instance
bus = EventBus()
