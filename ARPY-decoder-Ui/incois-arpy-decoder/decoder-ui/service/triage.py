"""Agentic failure triage for batch decoding.

A deterministic analysis engine that inspects the REAL error evidence of each
failed float (terminal error event, run summary, batch item error message)
and emits a structured triage result:

    {wmo, run_id, status, category, root_cause, recommended_action, evidence}

Design rules (strict):
  * ``root_cause`` is always a quote/slice of actual backend error data —
    nothing is ever invented or paraphrased as a cause.
  * ``recommended_action`` is operator guidance derived from the matched
    category, never a claim about what happened.
  * When no known signal matches, the result is ``UNCLASSIFIED`` and the raw
    error is preserved verbatim — the triage must never hide real errors.

Pure/read-only: no decoder execution, no file mutation, no network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from models import BatchSummary, NodeStatus, RunSummary, LiveEvent

# ---------------------------------------------------------------------------
# Categories (mapped from real signals observed in this deployment)
# ---------------------------------------------------------------------------

CATEGORY_MISSING_FLOAT_INFO = "MISSING_FLOAT_INFO"
CATEGORY_STAGED_INPUT_MISSING = "STAGED_INPUT_MISSING"
CATEGORY_MISSING_INPUT_FILES = "MISSING_INPUT_FILES"
CATEGORY_WRITER_OUTPUT = "WRITER_OUTPUT"
CATEGORY_UNSUPPORTED_PLATFORM = "UNSUPPORTED_PLATFORM"
CATEGORY_CORRUPTED_INPUT = "CORRUPTED_INPUT"
CATEGORY_CONFIG_PATH_ERROR = "CONFIG_PATH_ERROR"
CATEGORY_DECODER_ERROR = "DECODER_ERROR"
CATEGORY_USER_STOPPED = "USER_STOPPED"
CATEGORY_UNCLASSIFIED = "UNCLASSIFIED"

CATEGORY_LABELS: dict[str, str] = {
    CATEGORY_MISSING_FLOAT_INFO: "Missing float info config",
    CATEGORY_STAGED_INPUT_MISSING: "Staged input / metadata missing",
    CATEGORY_MISSING_INPUT_FILES: "Missing raw telemetry",
    CATEGORY_WRITER_OUTPUT: "NetCDF output writer failure",
    CATEGORY_UNSUPPORTED_PLATFORM: "Unsupported platform / firmware",
    CATEGORY_CORRUPTED_INPUT: "Corrupted input data",
    CATEGORY_CONFIG_PATH_ERROR: "Misconfigured path",
    CATEGORY_DECODER_ERROR: "Decoder exception",
    CATEGORY_USER_STOPPED: "Stopped by user",
    CATEGORY_UNCLASSIFIED: "Needs manual review",
}

# (category, regex) — evaluated in order against the collected evidence text.
# Order matters: UNSUPPORTED_PLATFORM is checked BEFORE CORRUPTED_INPUT
# because "unsupported firmware checksum N" contains "checksum" but is a
# mapping problem, not damaged data.
_SIGNALS: list[tuple[str, re.Pattern[str]]] = [
    (CATEGORY_MISSING_FLOAT_INFO,
     re.compile(r"no info json found for wmo", re.I)),
    (CATEGORY_STAGED_INPUT_MISSING,
     re.compile(r"cts4|none staged|stage_(input_files|metadata)", re.I)),
    (CATEGORY_MISSING_INPUT_FILES,
     re.compile(r"no (input|telemetry) files? found", re.I)),
    (CATEGORY_WRITER_OUTPUT,
     re.compile(r"netcdf output failed|_(build|write)_failed|writer failed|build failed|write failed", re.I)),
    (CATEGORY_UNSUPPORTED_PLATFORM,
     re.compile(r"unsupported (firmware|decoder|platform|format)|unknown or unsupported|maps to decoder ids|firmware checksum", re.I)),
    (CATEGORY_CORRUPTED_INPUT,
     re.compile(r"corrupt|checksum (mismatch|failed|invalid|error)|bad checksum|invalid checksum", re.I)),
    (CATEGORY_CONFIG_PATH_ERROR,
     re.compile(r"Is a directory|NotADirectoryError|No such file or directory", re.I)),
]

_ACTION_BY_CATEGORY: dict[str, str] = {
    CATEGORY_MISSING_FLOAT_INFO:
        "Register this WMO in the float-info config directory "
        "(config_floats/json_float_info) or correct the WMO, then re-run the float.",
    CATEGORY_STAGED_INPUT_MISSING:
        "Stage the missing CTS4 inputs (raw SBD group directory and/or "
        "GDAC meta.nc) for this WMO, then re-run the float. The run record "
        "names the exact missing dependency.",
    CATEGORY_MISSING_INPUT_FILES:
        "Ingest this float's raw telemetry into the raw input directory "
        "(or verify the WMO is expected in today's batch), then re-run the float.",
    CATEGORY_WRITER_OUTPUT:
        "The decoder finished but writing NetCDF output failed — inspect the "
        "OUTPUT-stage error event (VIEW RUN) for the writer message, check "
        "disk space/permissions if indicated, then re-run the float.",
    CATEGORY_UNSUPPORTED_PLATFORM:
        "This float's platform/firmware combination is not supported by the "
        "decoder mapping — confirm the float type and firmware in the "
        "metadata, then re-run or escalate with the error text.",
    CATEGORY_CORRUPTED_INPUT:
        "Re-ingest the raw telemetry for this WMO from the source "
        "(the existing file appears damaged) and re-run the float.",
    CATEGORY_CONFIG_PATH_ERROR:
        "Check the affected path in the decoder config — a directory was "
        "supplied where a file is expected (or the path does not exist).",
    CATEGORY_DECODER_ERROR:
        "Inspect the full traceback in the run's event log (VIEW RUN) — "
        "this exception originated inside the decoder itself.",
    CATEGORY_USER_STOPPED:
        "This float was stopped by the user; re-run it if decoding should continue.",
    CATEGORY_UNCLASSIFIED:
        "Open the run's event log (VIEW RUN) and review the raw error below — "
        "no known signature matched automatically.",
}

# Action variants for failures that never created a run record (pre-pipeline
# failures on historical batches): they must not point at an event log that
# does not exist. ``{root_cause}`` is the quoted real error, never invented.
_ACTION_NO_RUN_TEMPLATES: dict[str, str] = {
    CATEGORY_DECODER_ERROR:
        "No decoder run was created for this failure, so there is no event "
        "log to open. Known error: “{root_cause}”. The traceback below "
        "originated inside the decoder itself — report it with the failing WMO.",
    CATEGORY_UNCLASSIFIED:
        "No decoder run was created for this failure, so there is no event "
        "log to open. Known error: “{root_cause}”. Fix the underlying issue "
        "and re-run the float; no known signature matched automatically.",
}


@dataclass
class TriageEvidence:
    source: str
    detail: str


@dataclass
class TriageResult:
    wmo: int
    run_id: str | None
    status: str
    category: str
    category_label: str
    root_cause: str
    recommended_action: str
    evidence: list[TriageEvidence] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "wmo": self.wmo,
            "run_id": self.run_id,
            "status": self.status,
            "category": self.category,
            "category_label": self.category_label,
            "root_cause": self.root_cause,
            "recommended_action": self.recommended_action,
            "evidence": [e.__dict__ for e in self.evidence],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_final_exception(text: str) -> str | None:
    """Pull the final exception line out of a traceback (evidence, not cause)."""
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    for ln in reversed(lines):
        if re.match(r"^[A-Za-z_][\w.]*(Error|Exception|Interrupt|Exit)\b", ln):
            return ln[:400]
    return None


def _terminal_error_events(run: RunSummary | None, events: list[LiveEvent]) -> list[LiveEvent]:
    if not events:
        return []
    errs = [e for e in events if e.level == "error" or e.status == NodeStatus.ERROR]
    return errs[-2:]  # keep at most the two most recent error events as evidence


def _classify(evidence_text: str, item_status: str) -> str:
    if item_status in ("stopped", "cancelled"):
        return CATEGORY_USER_STOPPED
    for category, pattern in _SIGNALS:
        if pattern.search(evidence_text):
            return category
    # A traceback that survived all known signals is still a real decoder error.
    if _extract_final_exception(evidence_text):
        return CATEGORY_DECODER_ERROR
    return CATEGORY_UNCLASSIFIED


def _truncate(text: str, limit: int = 280) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def triage_failed_float(
    wmo: int,
    status: str,
    run: RunSummary | None,
    events: list[LiveEvent],
    error_message: str | None,
    run_id: str | None = None,
    error_type: str | None = None,
) -> TriageResult:
    """Produce the structured triage for a single (non-successful) batch item.

    ``error_type`` is the batch item's failure type when known ("MissingInput"
    is set only by the CTS4 staging gate, so it maps directly even if the
    message wording ever changes).
    """
    evidence: list[TriageEvidence] = []
    evidence_texts: list[str] = []

    for ev in _terminal_error_events(run, events):
        detail = _truncate(ev.message or ev.operation or "")
        if ev.error_details and ev.error_details not in (ev.message or ""):
            detail = f"{detail} | {_truncate(ev.error_details, 120)}"
        src = f"event:{ev.operation or 'error'}@{(ev.stage.value if ev.stage else '?')}"
        evidence.append(TriageEvidence(source=src, detail=detail))
        evidence_texts.append(ev.message or "")
        evidence_texts.append(ev.operation or "")
        if ev.error_details:
            evidence_texts.append(ev.error_details)

    if error_message:
        evidence.append(TriageEvidence(source="item.error_message", detail=_truncate(error_message)))
        evidence_texts.append(error_message)

    if run is not None and run.active_stage:
        evidence.append(TriageEvidence(source="run.active_stage", detail=run.active_stage.value))
        evidence_texts.append(run.active_stage.value)

    if run is not None and run.errors:
        evidence.append(TriageEvidence(source="run.errors", detail=_truncate(run.errors[-1])))
        evidence_texts.append(run.errors[-1])

    if error_type == "MissingInput":
        # Set only by the CTS4 staging gate: a missing staged dependency,
        # regardless of message wording.
        category = CATEGORY_STAGED_INPUT_MISSING
    else:
        category = _classify("\n".join(evidence_texts), status)

    # Root cause = the strongest actual error text available (never invented).
    root_cause = ""
    if error_message:
        final_exc = _extract_final_exception(error_message)
        root_cause = final_exc or error_message
    else:
        errs = _terminal_error_events(run, events)
        if errs:
            root_cause = errs[-1].message or (errs[-1].error_details or "")
        elif run is not None and run.errors:
            root_cause = run.errors[-1]
    root_cause = _truncate(root_cause) or "No error text captured by the backend."

    # Failures without a run record have no event log: never point at one.
    if run is None and category in _ACTION_NO_RUN_TEMPLATES:
        recommended_action = _ACTION_NO_RUN_TEMPLATES[category].format(root_cause=root_cause)
    else:
        recommended_action = _ACTION_BY_CATEGORY[category]

    return TriageResult(
        wmo=wmo,
        run_id=run_id,
        status=status,
        category=category,
        category_label=CATEGORY_LABELS[category],
        root_cause=root_cause,
        recommended_action=recommended_action,
        evidence=evidence,
    )


def triage_batch(
    batch: BatchSummary,
    run_lookup,
    event_lookup,
) -> list[TriageResult]:
    """Triage every non-completed item of a batch.

    ``run_lookup(run_id) -> RunSummary | None`` and
    ``event_lookup(run_id) -> list[LiveEvent]`` are keyed by run_id (a WMO
    has many runs across batches) and injected so this module stays decoupled
    from the event bus (and trivially testable).
    """
    results: list[TriageResult] = []
    for item in batch.items or []:
        if item.status == NodeStatus.COMPLETED:
            continue
        run = run_lookup(item.run_id) if item.run_id else None
        events = event_lookup(item.run_id) if item.run_id else []
        results.append(
            triage_failed_float(
                wmo=item.wmo,
                status=item.status.value,
                run=run,
                events=events,
                error_message=item.error_message,
                run_id=item.run_id,
                error_type=item.error_type,
            )
        )
    return results


def build_run_investigation(run: RunSummary, events: list[LiveEvent]) -> dict[str, Any]:
    """Single-run investigation payload for the interactive Error Detail view.

    Single source of truth for category/root-cause/action: reuses the same
    triage engine as batch triage, so the investigation view can never
    disagree with triage. Works uniformly for pipeline runs and persisted
    pre-run records (both are runs with error events). Pure/read-only.
    """
    err_text = run.errors[-1] if run.errors else None
    # Pre-run records carry the failure type on their events (same hook the
    # batch path uses) so the category survives message-wording changes.
    error_type = next(
        (
            e.data_sample.get("error_type")
            for e in events
            if isinstance(e.data_sample, dict) and e.data_sample.get("error_type")
        ),
        None,
    )
    result = triage_failed_float(
        wmo=run.wmo,
        status=run.status.value,
        run=run,
        events=list(events),
        error_message=err_text,
        run_id=run.run_id,
        error_type=error_type,
    )
    meaningful = [e.strip() for e in (run.errors or []) if (e or "").strip()]
    error_events = [e for e in events if e.level == "error"]
    focus = error_events[0] if error_events else (list(events)[-1] if events else None)

    stages_payload = {
        getattr(sid, "value", sid): {
            "status": getattr(st.status, "value", st.status),
            "detail": st.detail or "",
            "active_operation": st.active_operation or "",
        }
        for sid, st in (run.stages or {}).items()
    }
    focus_payload: dict[str, Any] | None = None
    if focus is not None:
        focus_payload = {
            "id": focus.id,
            "stage": getattr(focus.stage, "value", focus.stage),
            "operation": focus.operation,
            "cycle": focus.cycle,
            "timestamp": focus.timestamp,
            "message": focus.message or "",
            "level": focus.level,
            "input_summary": focus.input_summary or "",
            "python_file": focus.python_file or "",
            "python_function": focus.python_function or "",
            "has_error_details": bool(focus.error_details),
        }

    return {
        "run_id": run.run_id,
        "wmo": run.wmo,
        "status": run.status.value,
        "category": result.category,
        "category_label": result.category_label,
        "root_cause": result.root_cause,
        "recommended_action": result.recommended_action,
        "evidence": [{"source": e.source, "detail": e.detail} for e in result.evidence],
        "primary_error": meaningful[-1] if meaningful else "",
        "error_count": len(meaningful),
        "all_errors": meaningful,
        "root_cause_available": bool(meaningful or error_events),
        "failure_stage": getattr(run.active_stage, "value", run.active_stage),
        "stages": stages_payload,
        "focus_event": focus_payload,
        "started_at": run.start_time,
        "ended_at": run.end_time,
        "duration_seconds": run.duration_seconds,
        "total_files": run.total_files,
        "total_cycles": run.total_cycles,
        "outputs_count": len(run.output_files or []),
        "is_prerun": any(
            isinstance(e.data_sample, dict) and e.data_sample.get("pre_run") is True
            for e in events
        ),
    }
