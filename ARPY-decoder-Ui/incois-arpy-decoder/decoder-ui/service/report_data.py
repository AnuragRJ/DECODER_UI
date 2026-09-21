"""Report data model for the INCOIS ARPY Daily Fleet Decoding Report.

This module is the SINGLE authoritative "Report Data Model" layer. It converts
the persisted run/batch records (the exact data the Results page and the email
system already consume from the EventBus) into a structured report model that
the PDF renderer and the batch email both use.

Architecture rule honoured here:

    Authoritative Run/Batch Data  (bus: BatchSummary, RunSummary, LiveEvents)
        -> Report Data Model      (this module)
        -> Results UI             (renders the same authoritative records)
        -> PDF                    (pdf_report.py renders the model)
        -> Email                  (email_notifier.py uses the model)

No independent re-derivation of fleet statistics is performed: fleet totals
are read directly from the BatchSummary fields; per-float figures come from
the BatchFloatItem records; RTQC and deliverable detail come from the
RunSummary cycles/output_files that the Results page renders. Values that do
not exist in the authoritative records are explicitly marked as unavailable
("—") instead of being invented.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from event_bus import bus
from models import (
    BatchFloatItem,
    BatchSummary,
    LiveEvent,
    NodeStatus,
    RunSummary,
    StageId,
    utc_now_iso,
)

# Reuse the canonical Table 11 definitions already maintained by the
# observability layer (single source of truth for test names / passes).
# Imported lazily: runner_instrumentation drags in the argo_decoder package
# (which requires path_resolver to set up sys.path) — the server always has
# that available, but keeping the import lazy keeps this module lightweight
# and safe to import in any context.
_TABLE_11_DEFS: dict[int, dict] | None = None


def table11_definitions() -> dict[int, dict]:
    global _TABLE_11_DEFS
    if _TABLE_11_DEFS is None:
        try:
            import path_resolver  # ensures argo_decoder is importable
        except Exception:
            pass
        from runner_instrumentation import TABLE_11_TEST_DEFINITIONS

        _TABLE_11_DEFS = TABLE_11_TEST_DEFINITIONS
    return _TABLE_11_DEFS

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
REPORTS_DIR = DATA_DIR / "reports"

TERMINAL_STATUSES = (NodeStatus.COMPLETED, NodeStatus.STOPPED, NodeStatus.ERROR, NodeStatus.CANCELLED)


def _fmt_dt(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except ValueError:
        return iso


def _one_line_error(msg: str | None) -> str:
    """Condenses a possibly multi-line backend error (e.g. a full traceback)
    to its final exception line, for use in flowing prose. The verbatim
    full text is kept separately for evidence cells."""
    if not msg:
        return ""
    lines = [ln.strip() for ln in str(msg).splitlines() if ln.strip()]
    return lines[-1] if lines else str(msg).strip()


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class FailureAnalysis:
    """Evidence-based failure breakdown for one float.

    ``paragraph`` is the exact natural-language explanation shared by the PDF
    and the batch email (single source of truth). Every field is derived from
    real backend events / run state — no cause is invented; the backend error
    is quoted verbatim.
    """

    paragraph: str
    event_id: str | None
    what_failed: str
    where_failed: str
    why_failed: str
    succeeded: list[str] = field(default_factory=list)
    incomplete: str = ""


@dataclass
class FloatFileReport:
    filename: str
    category: str
    size_bytes: int
    dimensions: dict[str, int]
    checksum_sha256: str
    validation: str  # "verified" | "missing on disk"
    cycle: int | None
    n_variables: int


@dataclass
class FloatRtqcReport:
    applicable: int = 0      # run-wide suite (union of QCP masks over cycles)
    executed: int = 0        # tests verified as executed in the profile masks
    failed: int = 0          # union of QCF masks over cycles
    flagged_levels: int = 0  # measurement levels with degraded QC (3/4), run-wide
    qcp_hex: str = "0"
    qcf_hex: str = "0"
    per_test: list[dict[str, Any]] = field(default_factory=list)
    not_executed_count: int = 0
    notes: list[str] = field(default_factory=list)
    has_records: bool = False


@dataclass
class FloatBgcReport:
    """BGC evidence for one float, read from the run's own cycle records.

    Every field comes from the authoritative RunSummary the Results page
    renders (``bgc_profiles`` series + ``multi_profile`` deliverables) —
    nothing is re-derived from NetCDF here. ``has_bgc`` is False for all
    legacy/APEX/ARVOR floats, which leave every consumer unchanged.
    """

    has_bgc: bool = False
    br_files: int = 0               # indexed BR deliverables (multi_profile)
    cycles_with_bgc: int = 0        # cycles carrying at least one BR profile
    bgc_only_cycles: list[int] = field(default_factory=list)  # no core R
    g2_cycles: list[int] = field(default_factory=list)        # sensor-absent, flagged
    n_prof_values: list[int] = field(default_factory=list)    # sorted unique N_PROF
    params: list[str] = field(default_factory=list)           # sorted union of sensor params
    series_points: int = 0          # non-fill sensor measurements across profiles

    def summary_line(self) -> str:
        """One compact factual line shared by the PDF per-float block and the email."""
        if not self.has_bgc:
            return ""
        parts = [
            f"{self.br_files} BR file(s)",
            f"{self.cycles_with_bgc} cycle(s) with BGC series",
            f"{self.series_points} measurement(s)",
        ]
        if self.n_prof_values:
            parts.append(
                "N_PROF " + (str(self.n_prof_values[0]) if len(self.n_prof_values) == 1
                             else "/".join(str(v) for v in self.n_prof_values))
            )
        if self.params:
            parts.append("params: " + ", ".join(self.params))
        if self.bgc_only_cycles:
            parts.append("BGC-only cycle(s): " + ", ".join(f"C{c}" for c in sorted(self.bgc_only_cycles)))
        if self.g2_cycles:
            parts.append("sensor-absent, flagged (not plotted): " + ", ".join(f"C{c}" for c in sorted(self.g2_cycles)))
        return "; ".join(parts) + "."


@dataclass
class FloatReport:
    wmo: int
    platform: str
    transmission: str
    decoder_id: int | None
    run_id: str | None
    status: str
    cached: bool  # True when results were reused from today's earlier successful run
    cycles: int
    profiles: int
    missing_profiles: int
    outputs: int
    duration: float
    error_message: str | None
    error_type: str | None

    # Evidence extracted from the real backend events of this run
    n_input_files: int | None = None
    metadata_backend: str | None = None
    registry_file: str | None = None
    registry_floats: int | None = None
    decoder_name: str | None = None
    n_transmissions: int | None = None
    foreign_filtered: int = 0
    metadata_warnings: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    n_events: int = 0

    rtqc: FloatRtqcReport = field(default_factory=FloatRtqcReport)
    bgc: FloatBgcReport = field(default_factory=FloatBgcReport)
    files: list[FloatFileReport] = field(default_factory=list)
    outputs_by_category: dict[str, int] = field(default_factory=dict)
    nc_outputs: int = 0
    xml_outputs: int = 0

    narrative: str = ""
    failure: FailureAnalysis | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in ("completed", "error", "stopped", "cancelled")


@dataclass
class StageReport:
    key: str
    label: str
    basis: str  # "OBSERVED" | "VERIFIED PRODUCT" | "INFERRED" | "NOT REACHED"
    n_floats_evidence: int
    n_floats_total: int
    status_summary: str
    operations: list[str]
    sample: str | None
    explanation: str


@dataclass
class FleetReport:
    total_floats: int
    completed: int
    failed: int
    stopped: int
    pending: int
    total_cycles: int
    total_profiles: int
    total_missing: int
    total_outputs: int
    nc_outputs: int
    xml_outputs: int


@dataclass
class BatchReport:
    batch: BatchSummary
    generated_at: str
    fleet: FleetReport
    floats: list[FloatReport]
    pipeline: list[StageReport]
    assessment: str
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Failure analysis (shared by PDF and email — identical text by construction)
# ---------------------------------------------------------------------------

def analyze_failed_float(
    item: BatchFloatItem,
    run: RunSummary | None,
    events: list[LiveEvent],
) -> FailureAnalysis:
    """Builds the evidence-based failure breakdown for one failed/stopped float.

    Strictly uses: the item error recorded by the batch worker, the last error
    event, and the run stage state. The cause is the backend error message
    itself, quoted verbatim — nothing is invented.
    """
    error_event = next(
        (e for e in reversed(events) if e.level == "error" or e.status == NodeStatus.ERROR),
        None,
    )
    event_id = error_event.id if error_event else None

    raw_error = item.error_message or (error_event.message if error_event else None)
    if run and run.errors and not raw_error:
        raw_error = run.errors[0]
    if not raw_error:
        raw_error = "Stopped by user" if item.status in (
            NodeStatus.STOPPED.value, NodeStatus.CANCELLED.value) else "Unexpected processing error during execution"

    failed_stage = (
        error_event.stage.value.replace("_", " ")
        if error_event and error_event.stage
        else (run.active_stage.value.replace("_", " ") if run else "processing")
    )
    py_func = (
        error_event.python_function
        if error_event and error_event.python_function
        else (error_event.operation if error_event else "decoder execution")
    )

    # What had already succeeded
    succeeded: list[str] = []
    if run:
        if run.completed_cycles > 0:
            succeeded.append(f"successfully decoded {run.completed_cycles} cycle(s)")
        if len(run.output_files) > 0:
            succeeded.append(f"generated {len(run.output_files)} deliverable file(s)")
        if not succeeded:
            # Use real stage states to describe what actually completed
            done_stages = [
                k.value.replace("_", " ")
                for k, s in run.stages.items()
                if s.status == NodeStatus.COMPLETED
            ]
            if done_stages:
                succeeded.append("completed: " + ", ".join(sorted(set(done_stages))[:4]))
            else:
                succeeded.append("initialized float configuration and metadata loading")
    else:
        if item.cycles_count > 0:
            succeeded.append(f"processed {item.cycles_count} cycle(s)")
        if item.outputs_count > 0:
            succeeded.append(f"produced {item.outputs_count} output(s)")
        if not succeeded:
            succeeded.append("initiated the decoding pipeline")

    succeeded_text = " and ".join(succeeded)

    # What remains incomplete (evidence-based wording)
    if "no input files" in raw_error.lower():
        incomplete = "no telemetry could be decoded because input files were absent from the archive"
    elif "metadata" in raw_error.lower():
        incomplete = "full profile quality control and NetCDF assembly could not proceed"
    elif "nc" in raw_error.lower() or "prof" in raw_error.lower() or "output" in failed_stage.lower():
        incomplete = f"the required NetCDF deliverables ({item.missing_profiles} missing profiles) could not be written to disk"
    else:
        incomplete = "downstream product building and output archiving remain incomplete"

    one_line = _one_line_error(raw_error)
    paragraph = (
        f"Float WMO {item.wmo} ({item.platform_type or 'APEX'}) could not complete decoding "
        f"because an error occurred during the {failed_stage} stage ({py_func}): {one_line}. "
        f"The decoder {succeeded_text}, but {incomplete}, leaving the final delivery incomplete."
    )

    where = f"{failed_stage} stage ({py_func})"
    why = f"The backend reported: “{raw_error}”"

    return FailureAnalysis(
        paragraph=paragraph,
        event_id=event_id,
        what_failed=one_line,
        where_failed=where,
        why_failed=why,
        succeeded=succeeded,
        incomplete=incomplete,
    )


# ---------------------------------------------------------------------------
# Per-float evidence extraction (all from real run records / events)
# ---------------------------------------------------------------------------

def _extract_float_report(
    item: BatchFloatItem,
    run: RunSummary | None,
    events: list[LiveEvent],
) -> FloatReport:
    fr = FloatReport(
        wmo=item.wmo,
        platform=item.platform_type or (run.float_type if run and run.float_type else "APEX"),
        transmission=item.transmission_type or (run.transmission_type if run else "ARGOS"),
        decoder_id=item.decoder_id if item.decoder_id is not None else (run.decoder_id if run else None),
        run_id=item.run_id,
        status=item.status.value if isinstance(item.status, NodeStatus) else str(item.status),
        cached=bool(getattr(item, "cached", False)),
        cycles=item.cycles_count,
        profiles=item.profiles_count,
        missing_profiles=item.missing_profiles,
        outputs=item.outputs_count,
        duration=item.duration_seconds or 0.0,
        error_message=item.error_message,
        error_type=item.error_type,
        n_events=len(events),
    )

    # --- event-level evidence ------------------------------------------------
    for e in events:
        if e.level == "warning":
            fr.warnings.append(e.message)
            if e.stage == StageId.METADATA:
                fr.metadata_warnings.append(e.message)
        op = e.operation or ""
        ds = e.data_sample or {}
        if op == "input_files_discovered":
            fr.n_input_files = int(ds.get("n") or 0)
        elif op == "metadata_backend":
            fr.metadata_backend = str(ds.get("backend") or fr.metadata_backend)
        elif op == "metadata_loaded":
            fr.registry_floats = int(ds.get("n_entries") or 0) or None
            path = str(ds.get("path") or "")
            if path:
                fr.registry_file = Path(path).name
        elif op == "decoder_selected":
            fr.decoder_name = str(ds.get("decoder") or fr.decoder_name)
        elif op == "split_transmissions":
            fr.n_transmissions = int(ds.get("n_transmissions") or 1)
        elif op == "foreign_transmission_filtered":
            fr.foreign_filtered += 1

    if fr.n_input_files is None and run is not None and run.total_files:
        fr.n_input_files = run.total_files

    # --- RTQC (from the verified per-cycle rtqc_summary of the run) ----------
    if run is not None and run.cycles:
        done: set[int] = set()
        failed: set[int] = set()
        flagged_total = 0
        qcp = "0"
        qcf = "0"
        for c in run.cycles:
            s = c.rtqc_summary or {}
            done.update(int(t) for t in (s.get("tests_done") or []))
            failed.update(int(t) for t in (s.get("tests_failed") or []))
            flagged_total += int(s.get("flagged_levels") or 0)
            if s.get("qcp_hex"):
                qcp = str(s["qcp_hex"])
            if s.get("qcf_hex"):
                qcf = str(s["qcf_hex"])
        fr.rtqc.applicable = len(done)
        fr.rtqc.executed = len(done)
        fr.rtqc.failed = len(failed)
        fr.rtqc.flagged_levels = flagged_total
        fr.rtqc.qcp_hex = qcp
        fr.rtqc.qcf_hex = qcf
        fr.rtqc.has_records = done or failed or flagged_total > 0
        defs = table11_definitions()
        for n in sorted(defs):
            if n in done:
                fr.rtqc.per_test.append({
                    "test_id": f"TEST{n:03d}",
                    "name": defs[n]["name"],
                    "pass": defs[n]["pass"].value,
                    "status": "FAILED" if n in failed else "EXECUTED",
                    "failed": n in failed,
                    "flagged": None,  # per-test flag counts are not recorded by the backend
                })
        fr.rtqc.not_executed_count = len(defs) - len(done)
        for e in events:
            if e.operation == "rtqc_test004_note":
                reason = (e.data_sample or {}).get("reason", "no GEBCO grid")
                fr.rtqc.notes.append(
                    f"TEST004 (Position on Land) was omitted for this run ({reason})."
                )
            elif e.operation == "arvor_i_rtqc_applied":
                ds = e.data_sample or {}
                n_prof = int(ds.get("profiles") or 0)
                n_fail = int(ds.get("profiles_with_failures") or 0)
                fr.rtqc.notes.append(
                    f"RTQC evaluated {n_prof} profile(s); {n_fail} profile(s) received quality-flag updates."
                )
            elif e.operation == "cross_cycle_rtqc_applied":
                ds = e.data_sample or {}
                fr.rtqc.notes.append(
                    f"Cross-cycle checks (impossible speed, sensor drift, frozen profile) evaluated {int(ds.get('cycles_evaluated') or 0)} cycle(s)."
                )
            elif e.operation == "rtqc_verification_complete":
                ds = e.data_sample or {}
                fr.rtqc.notes.append(
                    f"Post-run verification from generated NetCDF: {int(ds.get('tests_executed_count') or 0)} test(s) verified, "
                    f"{int(ds.get('total_flagged_levels') or 0)} level(s) flagged."
                )

    # --- deliverables (from the indexed on-disk artifacts of the run) --------
    if run is not None:
        for f in run.output_files:
            present = Path(f.filepath).exists()
            fr.files.append(FloatFileReport(
                filename=f.filename,
                category=f.category,
                size_bytes=f.filesize_bytes,
                dimensions=dict(f.dimensions or {}),
                checksum_sha256=f.checksum_sha256,
                validation="verified" if present else "missing on disk",
                cycle=f.cycle,
                n_variables=len(f.variables or []),
            ))
            fr.outputs_by_category[f.category] = fr.outputs_by_category.get(f.category, 0) + 1
            if f.category == "xml":
                fr.xml_outputs += 1
            else:
                fr.nc_outputs += 1

    # --- BGC (from the run's own per-cycle BGC records + BR deliverables) ----
    if run is not None and run.cycles:
        params: set[str] = set()
        nprofs: set[int] = set()
        points = 0
        for c in run.cycles:
            bps = c.bgc_profiles or []
            if not bps:
                continue
            fr.bgc.cycles_with_bgc += 1
            if c.bgc_n_prof:
                nprofs.add(c.bgc_n_prof)
            if c.has_core is False:
                fr.bgc.bgc_only_cycles.append(c.cycle_number)
            if c.matches_g2_signature:
                fr.bgc.g2_cycles.append(c.cycle_number)
            for p in bps:
                for s in p.station_parameters or []:
                    if s and s not in ("PRES", "TEMP", "PSAL"):
                        params.add(s)
                for row in p.samples or []:
                    for k, v in row.items():
                        if k in ("level", "PRES") or k.endswith("_QC"):
                            continue
                        if v is not None:
                            points += 1
        fr.bgc.params = sorted(params)
        fr.bgc.n_prof_values = sorted(nprofs)
        fr.bgc.series_points = points
        fr.bgc.br_files = fr.outputs_by_category.get("multi_profile", 0)
        fr.bgc.has_bgc = fr.bgc.cycles_with_bgc > 0

    # --- failure analysis -----------------------------------------------------
    if fr.status == "error":
        fr.failure = analyze_failed_float(item, run, events)

    # --- narrative -------------------------------------------------------------
    fr.narrative = _compose_narrative(fr)
    return fr


def _compose_narrative(fr: FloatReport) -> str:
    """Composes the per-float natural-language report strictly from evidence."""
    p: list[str] = []
    plat = fr.platform
    trans = fr.transmission
    head_extra = f", decoder table entry #{fr.decoder_id}" if fr.decoder_id is not None else ""

    if fr.status == "completed":
        if fr.cached:
            p.append(
                f"Float WMO {fr.wmo} ({plat} / {trans}{head_extra}) was already successfully decoded today; "
                f"this batch deliberately reused that result (COMPLETED / CACHED, run {fr.run_id}) instead of decoding again."
            )
        else:
            p.append(f"Float WMO {fr.wmo} ({plat} / {trans}{head_extra}) entered the batch decoding queue in a ready state.")
        if fr.n_input_files is not None:
            p.append(f"Input discovery found {fr.n_input_files} raw telemetry file(s) in the archive for this float.")
        if fr.metadata_backend:
            reg = f" — {fr.registry_floats} floats indexed from {fr.registry_file}" if fr.registry_file else ""
            p.append(f"The pipeline was configured and metadata was loaded through the {fr.metadata_backend} metadata backend{reg}.")
            if fr.metadata_warnings:
                p.append(f"{len(fr.metadata_warnings)} non-critical metadata notice(s) were raised during loading.")
        if fr.decoder_name:
            p.append(f"Platform selection resolved the {fr.decoder_name} decoder for this float's firmware profile.")
        if fr.n_transmissions is not None:
            p.append(f"The ARGOS telemetry dump was split into {fr.n_transmissions} transmission(s).")
            if fr.foreign_filtered:
                p.append(f"{fr.foreign_filtered} foreign transmission(s) from other floats sharing the channel were identified and withheld.")
        p.append(
            f"Decoding processed {fr.cycles} cycle(s); {fr.profiles} vertical profile(s) were generated"
            + (f" with {fr.missing_profiles} missing" if fr.missing_profiles else "")
            + "."
        )
        if fr.rtqc.has_records:
            p.append(
                f"Real-Time Quality Control (Argo Table 11) executed {fr.rtqc.executed} test(s): "
                f"{fr.rtqc.failed} failed and {fr.rtqc.flagged_levels} measurement level(s) received a degraded quality flag (QC 3/4)."
            )
            for note in fr.rtqc.notes:
                p.append(note)
        if fr.bgc.has_bgc:
            b = fr.bgc
            nprof_txt = (
                f"N_PROF {b.n_prof_values[0]}" if len(b.n_prof_values) == 1
                else f"N_PROF values {'/'.join(str(v) for v in b.n_prof_values)}"
            )
            p.append(
                f"BGC: {b.br_files} BR file(s) indexed; {b.cycles_with_bgc} of {fr.cycles} cycle(s) carry BGC series "
                f"({b.series_points} measurement(s) across {len(b.params)} sensor parameter(s), {nprof_txt})."
            )
            if b.bgc_only_cycles:
                only = ", ".join(f"C{c}" for c in sorted(b.bgc_only_cycles))
                p.append(f"Cycle(s) {only} are BGC-only (no core R profile was published for them).")
            if b.g2_cycles:
                g2 = ", ".join(f"C{c}" for c in sorted(b.g2_cycles))
                p.append(
                    f"Cycle(s) {g2} label BGC sensor channels that are entirely fill; flagged as a suspected "
                    f"301 writer artifact and not plotted."
                )
        cat_bits = []
        for cat, label in (
            ("mono_profile", "profile NetCDF"),
            ("meta", "meta NetCDF"),
            ("tech", "technical NetCDF"),
            ("traj", "trajectory NetCDF"),
            ("multi_profile", "multi-profile NetCDF"),
        ):
            n = fr.outputs_by_category.get(cat, 0)
            if n:
                cat_bits.append(f"{n} {label}")
        if cat_bits:
            p.append(f"{fr.outputs} deliverable file(s) were written, including {' and '.join(cat_bits)}.")
        if fr.xml_outputs:
            p.append(f"{fr.xml_outputs} Coriolis XML report(s) completed the deliverable set.")
        else:
            p.append("No XML report was produced for this float in this run.")
        if fr.cached:
            p.append(
                f"All figures above belong to run {fr.run_id} (decoded earlier today); "
                "no decoding time was spent on this float in this batch."
            )
        else:
            p.append(f"Execution ended with status COMPLETED after {fr.duration:.2f} s.")
        if fr.warnings:
            p.append(f"{len(fr.warnings)} warning(s) were logged during execution (see event log for details).")

    elif fr.status in ("stopped", "cancelled"):
        p.append(f"Float WMO {fr.wmo} ({plat} / {trans}) was stopped by user request during batch execution.")
        if fr.n_input_files is not None:
            p.append(f"Before the stop, input discovery had found {fr.n_input_files} raw telemetry file(s).")
        p.append(
            f"At the moment of the stop, {fr.cycles} cycle(s) had been processed and {fr.profiles} profile(s) generated; "
            f"{fr.outputs} deliverable file(s) had already been written and are preserved."
        )
        p.append(
            "Remaining incomplete: decoding of the remaining cycles and final deliverable assembly for this float."
        )
        p.append(f"Execution ended with status STOPPED after {fr.duration:.2f} s.")

    elif fr.status == "error":
        fa = fr.failure
        p.append(f"Float WMO {fr.wmo} ({plat} / {trans}{head_extra}) was queued for batch decoding and initialization began.")
        if fr.n_input_files is not None:
            p.append(f"Input discovery reported {fr.n_input_files} telemetry file(s) available for this float.")
        if fr.metadata_backend:
            p.append(f"Metadata loading through the {fr.metadata_backend} backend had started before the failure.")
        if fa:
            p.append(f"Processing halted at the {fa.where_failed} because: {fa.what_failed}.")
            if fa.succeeded:
                p.append("Before the failure the decoder had " + " and ".join(fa.succeeded) + ".")
            p.append(f"Consequently, {fa.incomplete}.")
        if fr.outputs:
            p.append(
                f"Execution ended with status ERROR after {fr.duration:.2f} s. "
                f"At the point of failure, {fr.outputs} deliverable file(s) had already been written and are preserved (see Section 7)."
            )
        else:
            p.append(f"Execution ended with status ERROR after {fr.duration:.2f} s; no deliverables were produced for this float.")

    else:
        p.append(f"Float WMO {fr.wmo} ({plat} / {trans}) was queued but not executed in this batch (status {fr.status.upper()}).")

    return " ".join(x for x in p if x)


# ---------------------------------------------------------------------------
# Pipeline stage aggregation (observed events vs inferred lifecycle)
# ---------------------------------------------------------------------------

#: Report pipeline stages (in execution order) with the backend evidence that
#: directly supports each one. Stages with no direct backend event are
#: lifecycle definitions of the decoder pipeline and are reported as INFERRED
#: (or VERIFIED PRODUCT when the on-disk deliverables confirm them).
REPORT_STAGES: list[tuple[str, str, StageId, list[tuple[StageId, str | None]]]] = [
    ("INPUT", "INPUT", StageId.DISCOVERY, [
        (StageId.DISCOVERY, "input_files_discovered"),
        (StageId.DISCOVERY, "no_input_files"),
        (StageId.INPUT_FILES, None),
    ]),
    ("CONFIGURATION", "CONFIGURATION", StageId.CONFIGURATION, [
        (StageId.CONFIGURATION, None),
    ]),
    ("METADATA", "METADATA", StageId.METADATA, [
        (StageId.METADATA, None),
    ]),
    ("DISCOVERY", "DISCOVERY", StageId.DISCOVERY, [
        (StageId.DISCOVERY, "input_files_discovered"),
        (StageId.DISCOVERY, "no_input_files"),
        (StageId.RAW_PROCESSING, "split_transmissions"),
    ]),
    ("WMO_MAPPING", "WMO MAPPING", StageId.WMO_MAPPING, []),
    ("CYCLE_GROUPING", "CYCLE GROUPING", StageId.CYCLE_GROUPING, []),
    ("DECODER", "DECODER", StageId.DECODER_SELECTION, [
        (StageId.DECODER_SELECTION, None),
        (StageId.PLATFORM_PROCESSING, "engine_resolved"),
    ]),
    ("DECODE", "DECODE", StageId.DECODE, [
        (StageId.DECODE, None),
        (StageId.RAW_PROCESSING, None),
    ]),
    ("PROFILE", "PROFILE", StageId.PROFILE, [
        (StageId.PROFILE, None),
    ]),
    ("RTQC", "RTQC", StageId.RTQC, [
        (StageId.RTQC, None),
        (StageId.CROSS_CYCLE_RTQC, None),
    ]),
    ("OUTPUT", "OUTPUT", StageId.OUTPUT, [
        (StageId.OUTPUT, None),
    ]),
    ("DONE", "DONE", StageId.DONE, [
        (StageId.DONE, None),
    ]),
]

_STAGE_ROLE: dict[str, str] = {
    "INPUT": "raw telemetry archive scan for each float's transmitted files",
    "CONFIGURATION": "initialization of decoder configuration and the run environment",
    "METADATA": "loading of float calibration and configuration parameters from the registry",
    "DISCOVERY": "selection of this float's files and splitting of raw transmissions",
    "WMO_MAPPING": "mapping of the raw WMO number to its float record and decoder table entry",
    "CYCLE_GROUPING": "grouping of messages into individual decoded cycles",
    "DECODER": "selection of the platform decoder and firmware engine for this float",
    "DECODE": "binary decoding of each cycle's sensor telemetry",
    "PROFILE": "assembly of vertical CTD profiles and auxiliary datasets",
    "RTQC": "Argo Table 11 real-time quality control over the profiles",
    "OUTPUT": "NetCDF and XML product serialization to the output archive",
    "DONE": "pipeline completion and run finalization",
}


def _build_pipeline(report_floats: list[FloatReport], batch: BatchSummary) -> list[StageReport]:
    n_total = len(report_floats)
    out: list[StageReport] = []

    for idx, (key, label, primary_stage, evidence) in enumerate(REPORT_STAGES):
        n_event = 0
        n_product = 0
        ops: set[str] = set()
        sample: str | None = None
        states: dict[str, int] = defaultdict(int)

        for fr in report_floats:
            run = bus.get_run(fr.run_id) if fr.run_id else None
            events = bus.get_events(fr.run_id) if fr.run_id else []

            has_event = False
            for e in events:
                if not e.stage:
                    continue
                for ev_stage, ev_op in evidence:
                    if e.stage == ev_stage and (ev_op is None or e.operation == ev_op):
                        has_event = True
                        if e.operation:
                            ops.add(e.operation)
                        if sample is None and e.message:
                            sample = e.message
                        break
            if has_event:
                n_event += 1

            has_product = False
            if key == "PROFILE":
                has_product = fr.outputs_by_category.get("mono_profile", 0) > 0
            elif key == "OUTPUT":
                has_product = len(fr.files) > 0
            elif key == "INPUT":
                has_product = (fr.n_input_files or 0) > 0
            elif key == "DONE":
                has_product = fr.status == "completed"
            if has_product:
                n_product += 1

            st = "not_reached"
            if run is not None:
                s = run.stages.get(primary_stage)
                st = s.status.value if s else "unknown"
            states[st] += 1

        basis = "OBSERVED" if n_event else ("VERIFIED PRODUCT" if n_product else "INFERRED")
        if n_event == 0 and n_product == 0 and all(
            fr.status in ("pending",) for fr in report_floats):
            basis = "NOT REACHED"

        # Status summary from real run stage states
        parts = []
        if states.get("completed"):
            parts.append(f"completed for {states['completed']} float(s)")
        if states.get("error"):
            parts.append(f"failed for {states['error']}")
        if states.get("stopped") or states.get("cancelled"):
            parts.append(f"stopped for {states.get('stopped', 0) + states.get('cancelled', 0)}")
        if states.get("active"):
            parts.append(f"active for {states['active']}")
        if states.get("pending"):
            parts.append(f"not started for {states['pending']}")
        if states.get("not_reached") or states.get("unknown"):
            parts.append(f"not reached by {states.get('not_reached', 0) + states.get('unknown', 0)}")
        status_summary = " · ".join(parts) if parts else "no run records"

        explanation = _stage_explanation(key, label, n_total, n_event, n_product, states, report_floats)

        out.append(StageReport(
            key=key,
            label=label,
            basis=basis,
            n_floats_evidence=max(n_event, n_product),
            n_floats_total=n_total,
            status_summary=status_summary,
            operations=sorted(ops),
            sample=sample,
            explanation=explanation,
        ))

    return out


def _stage_explanation(
    key: str,
    label: str,
    n_total: int,
    n_event: int,
    n_product: int,
    states: dict[str, int],
    floats: list[FloatReport],
) -> str:
    role = _STAGE_ROLE[key]
    reached = n_total - states.get("not_reached", 0) - states.get("unknown", 0)

    if key == "INPUT":
        total_files = sum(fr.n_input_files or 0 for fr in floats)
        with_files = sum(1 for fr in floats if (fr.n_input_files or 0) > 0)
        none_files = [fr.wmo for fr in floats if fr.n_input_files == 0]
        txt = (f"{role.capitalize()}: {total_files} input file(s) discovered across "
               f"{with_files} of {n_total} float(s).")
        if none_files:
            txt += f" No telemetry was found for WMO {', '.join(str(w) for w in none_files[:6])}"
            if len(none_files) > 6:
                txt += f" and {len(none_files) - 6} more"
            txt += "."
        return txt

    if key == "METADATA":
        backends = sorted({fr.metadata_backend for fr in floats if fr.metadata_backend})
        regs = sorted({fr.registry_file for fr in floats if fr.registry_file})
        n_warn = sum(1 for fr in floats if fr.metadata_warnings)
        txt = f"{role.capitalize()} via the {' and '.join(backends) if backends else 'configured'} metadata backend"
        if regs:
            txt += f" (registry: {regs[0]})"
        txt += "."
        n_err = sum(1 for fr in floats if fr.status == "error" and "metadata" in (fr.error_message or "").lower())
        if n_err:
            txt += f" Metadata errors aborted {n_err} float(s)."
        elif n_warn:
            txt += f" Non-critical metadata notices occurred for {n_warn} float(s)."
        return txt

    if key == "DECODER":
        names = sorted({fr.decoder_name for fr in floats if fr.decoder_name})
        txt = f"{role.capitalize()}."
        if names:
            txt += f" Decoders used in this batch: {', '.join(names)}."
        return txt

    if key == "DECODE":
        n_tx = sum(fr.n_transmissions or 0 for fr in floats if fr.n_transmissions is not None)
        n_foreign = sum(fr.foreign_filtered for fr in floats)
        txt = f"{role.capitalize()} for {sum(fr.cycles for fr in floats)} cycle(s) across the batch."
        if n_tx:
            txt += f" {n_tx} raw transmission(s) were split for decoding"
            if n_foreign:
                txt += f" and {n_foreign} foreign transmission(s) withheld"
            txt += "."
        return txt

    if key == "PROFILE":
        n_prof = sum(fr.profiles for fr in floats)
        n_miss = sum(fr.missing_profiles for fr in floats)
        txt = f"{role.capitalize()}: {n_prof} profile(s) assembled"
        if n_miss:
            txt += f", {n_miss} missing"
        txt += "."
        return txt

    if key == "RTQC":
        done = max((fr.rtqc.executed for fr in floats), default=0)
        flagged = sum(fr.rtqc.flagged_levels for fr in floats)
        failed_tests = sorted({t["test_id"] for fr in floats for t in fr.rtqc.per_test if t["failed"]})
        txt = f"{role.capitalize()} over the generated profiles; fleet-wide {flagged} measurement level(s) were flagged."
        if failed_tests:
            txt += f" Tests with failed profiles: {', '.join(failed_tests)}."
        return txt

    if key == "OUTPUT":
        nc = sum(fr.nc_outputs for fr in floats)
        xml = sum(fr.xml_outputs for fr in floats)
        missing_files = sum(1 for fr in floats for f in fr.files if f.validation != "verified")
        txt = f"{role.capitalize()}: {nc} NetCDF file(s) and {xml} XML report(s) written."
        if missing_files:
            txt += f" {missing_files} file(s) listed in the run record were not found on disk at report time."
        return txt

    if key == "DONE":
        n_ok = sum(1 for fr in floats if fr.status == "completed")
        n_err = sum(1 for fr in floats if fr.status == "error")
        n_stop = sum(1 for fr in floats if fr.status in ("stopped", "cancelled"))
        txt = f"{role.capitalize()} for {n_ok} float(s)"
        if n_err:
            txt += f"; {n_err} ended in error"
        if n_stop:
            txt += f"; {n_stop} stopped by user"
        txt += "."
        return txt

    if key == "WMO_MAPPING":
        return (f"No direct backend event is emitted for this stage. It is a pipeline lifecycle step — "
                f"{role} — inferred from the successful downstream decoder selection "
                f"(completed for {states.get('completed', 0)} of {reached} float(s) that reached the stage).")

    if key == "CYCLE_GROUPING":
        n_cyc = sum(fr.cycles for fr in floats)
        return (f"No direct backend event is emitted for this stage. It is a pipeline lifecycle step — "
                f"{role} — inferred from the {n_cyc} per-cycle decode records and generated profiles "
                f"(completed for {states.get('completed', 0)} of {reached} float(s) that reached the stage).")

    if n_event:
        return f"{role.capitalize()} (observed directly in {n_event} float(s) event log(s))."
    if n_product:
        return f"{role.capitalize()} — confirmed by verified on-disk products for {n_product} float(s); no dedicated backend event is emitted."
    return f"{role.capitalize()} — no direct evidence in this batch; stage status inferred from the pipeline definition."


# ---------------------------------------------------------------------------
# Fleet + assessment + top-level build
# ---------------------------------------------------------------------------

def _build_fleet(batch: BatchSummary, floats: list[FloatReport]) -> FleetReport:
    nc = sum(fr.nc_outputs for fr in floats)
    xml = sum(fr.xml_outputs for fr in floats)
    # Floats without a run record: their outputs_count is authoritative but
    # the NC/XML split is not classifiable — count them as NetCDF-side only if
    # no XML is recorded (conservative, matches batch total).
    for item in batch.items:
        fr = next((f for f in floats if f.wmo == item.wmo), None)
        if fr is not None and fr.run_id is None and item.outputs_count:
            nc += item.outputs_count
    return FleetReport(
        total_floats=batch.total_floats or len(batch.items),
        completed=batch.completed_floats,
        failed=batch.failed_floats,
        stopped=batch.stopped_floats,
        pending=batch.pending_floats,
        total_cycles=sum(fr.cycles for fr in floats),
        total_profiles=batch.total_profiles_generated,
        total_missing=batch.total_profiles_missing,
        total_outputs=batch.total_output_files,
        nc_outputs=nc,
        xml_outputs=xml,
    )


def _build_assessment(batch: BatchSummary, fleet: FleetReport, floats: list[FloatReport]) -> str:
    p: list[str] = []
    status = batch.status.value if isinstance(batch.status, NodeStatus) else str(batch.status)
    duration = f"{batch.duration_seconds:.2f}"

    ok = [f for f in floats if f.status == "completed"]
    bad = [f for f in floats if f.status == "error"]
    sto = [f for f in floats if f.status in ("stopped", "cancelled")]
    cached = [f for f in ok if f.cached]
    fresh_ok = [f for f in ok if not f.cached]

    opening = (
        f"The batch {batch.batch_id} finished with overall status {status.upper()} after {duration} s of wall-clock processing, "
        f"covering {fleet.total_floats} float(s) of today's fleet."
    )
    if bad and ok:
        opening += (
            f" The operation was substantially successful: {len(ok)} of {fleet.total_floats} floats decoded to completion, "
            f"generating {fleet.total_profiles} verified profiles and {fleet.total_outputs} deliverable files"
            f" ({fleet.nc_outputs} NetCDF, {fleet.xml_outputs} XML), while {len(bad)} float(s) failed and require attention."
        )
    elif ok and not bad and cached and not fresh_ok:
        opening += (
            f" All {len(ok)} float(s) were already successfully decoded earlier today; this batch carried their "
            f"results over without re-decoding (cached), covering {fleet.total_profiles} verified profiles and "
            f"{fleet.total_outputs} deliverable files ({fleet.nc_outputs} NetCDF, {fleet.xml_outputs} XML)."
        )
    elif ok and not bad:
        opening += f" All {len(ok)} float(s) decoded to completion, generating {fleet.total_profiles} verified profiles and {fleet.total_outputs} deliverable files ({fleet.nc_outputs} NetCDF, {fleet.xml_outputs} XML)."
    elif bad and not ok:
        opening += f" No float reached successful completion in this batch: {len(bad)} of {fleet.total_floats} failed. The batch should be re-run or investigated before operational use of its (nonexistent) products."
    else:
        opening += f" The batch ended without successful float completions (status {status.upper()})."
    p.append(opening)

    if ok:
        ok_desc = ", ".join(f"WMO {f.wmo} ({f.cycles} cycles)" for f in ok)
        p.append(f"Successful floats — {len(ok)}: {ok_desc}.")
    if bad:
        bits = []
        for f in bad:
            cause = _one_line_error(f.failure.what_failed if f.failure else f.error_message) or "unspecified error"
            bits.append(f"WMO {f.wmo}: {cause}")
        p.append(f"Failed floats — {len(bad)}: " + "; ".join(bits) + ".")
    if sto:
        p.append(f"Stopped floats — {len(sto)}: " + ", ".join(f"WMO {f.wmo}" for f in sto) + " (stopped by user; partial products preserved).")

    # Major problems
    errors_by_msg: dict[str, list[int]] = defaultdict(list)
    for f in bad:
        key = _one_line_error(f.failure.what_failed if f.failure else f.error_message) or "unspecified"
        errors_by_msg[key].append(f.wmo)
    if len(errors_by_msg) > 1:
        p.append(
            "The failures are not caused by a single shared fault: "
            + "; ".join(f"“{msg[:110]}” affected {len(ws)} float(s) ({', '.join(str(w) for w in ws)})" for msg, ws in errors_by_msg.items())
            + "."
        )

    # Missing / incomplete products
    miss = [f for f in floats if f.missing_profiles > 0]
    no_out = [f for f in floats if f.status != "completed" and f.outputs == 0]
    if miss:
        p.append("Incomplete products: " + ", ".join(f"WMO {f.wmo} ({f.missing_profiles} missing profile(s))" for f in miss) + ".")
    if no_out:
        p.append("Floats with no deliverables produced: " + ", ".join(f"WMO {f.wmo}" for f in no_out) + ".")

    # RTQC findings
    flagged_total = sum(f.rtqc.flagged_levels for f in floats)
    failed_tests: dict[str, list[int]] = defaultdict(list)
    for f in floats:
        for t in f.rtqc.per_test:
            if t["failed"]:
                failed_tests[t["test_id"]].append(f.wmo)
    if any(f.rtqc.has_records for f in floats):
        rtqc_bits = [f"{flagged_total} measurement level(s) received a degraded quality flag (QC 3/4) fleet-wide"]
        if failed_tests:
            rtqc_bits.append(
                "failed-test hotspots: " + ", ".join(f"{tid} on WMO {', '.join(str(w) for w in ws)}" for tid, ws in sorted(failed_tests.items()))
            )
        else:
            rtqc_bits.append("no Table 11 test recorded a profile failure in this batch")
        p.append("RTQC findings — " + "; ".join(rtqc_bits) + ".")
    test004 = [f for f in floats if any("TEST004" in n for n in f.rtqc.notes)]
    if test004:
        p.append("Note: TEST004 (Position on Land) was omitted for " + ", ".join(f"WMO {f.wmo}" for f in test004) + " because no GEBCO bathymetry grid was configured.")

    bgc_floats = [f for f in floats if f.bgc.has_bgc]
    if bgc_floats:
        bgc_bits = [
            f"{sum(f.bgc.br_files for f in bgc_floats)} BR file(s) indexed fleet-wide",
            f"{sum(f.bgc.series_points for f in bgc_floats)} BGC measurement(s) across "
            + ", ".join(f"WMO {f.wmo}" for f in bgc_floats),
        ]
        g2_hot = [(f.wmo, sorted(f.bgc.g2_cycles)) for f in bgc_floats if f.bgc.g2_cycles]
        if g2_hot:
            bgc_bits.append(
                "sensor-absent cycles flagged (not plotted): "
                + "; ".join(f"WMO {w} ({', '.join(f'C{c}' for c in cs)})" for w, cs in g2_hot)
            )
        only_hot = [(f.wmo, sorted(f.bgc.bgc_only_cycles)) for f in bgc_floats if f.bgc.bgc_only_cycles]
        if only_hot:
            bgc_bits.append(
                "BGC-only cycles (no core R profile): "
                + "; ".join(f"WMO {w} ({', '.join(f'C{c}' for c in cs)})" for w, cs in only_hot)
            )
        p.append("BGC findings — " + "; ".join(bgc_bits) + ".")

    p.append(
        f"Overall, this batch produced {fleet.total_profiles} profile(s) and {fleet.total_outputs} deliverable file(s) "
        f"({fleet.nc_outputs} NetCDF, {fleet.xml_outputs} XML) for the INCOIS ARPY archive. "
        + ("The full per-float inventory, checksums and RTQC detail is documented in Sections 4, 6 and 7 of this report." if ok else "No products were generated; refer to the per-float sections for the failure analysis.")
    )
    return " ".join(p)


def build_batch_report_data(batch_id: str) -> BatchReport:
    """Builds the complete report data model for a batch from authoritative data."""
    batch = bus.get_batch(batch_id)
    if not batch:
        raise KeyError(f"Batch {batch_id} not found")

    floats: list[FloatReport] = []
    for item in batch.items:
        run = bus.get_run(item.run_id) if item.run_id else None
        events = bus.get_events(item.run_id) if item.run_id else []
        floats.append(_extract_float_report(item, run, events))

    fleet = _build_fleet(batch, floats)
    pipeline = _build_pipeline(floats, batch)
    assessment = _build_assessment(batch, fleet, floats)

    return BatchReport(
        batch=batch,
        generated_at=utc_now_iso(),
        fleet=fleet,
        floats=floats,
        pipeline=pipeline,
        assessment=assessment,
    )
