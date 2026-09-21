"""Observability models for the Argo Float Decoder Live UI."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class NodeStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    FLAGGED = "flagged"
    NOT_RUN = "not_run"
    ERROR = "error"
    STOPPED = "stopped"
    CANCELLED = "cancelled"


class StageId(str, Enum):
    INPUT_FILES = "INPUT_FILES"
    CONFIGURATION = "CONFIGURATION"
    METADATA = "METADATA"
    DISCOVERY = "DISCOVERY"
    WMO_MAPPING = "WMO_MAPPING"
    CYCLE_GROUPING = "CYCLE_GROUPING"
    DECODER_SELECTION = "DECODER_SELECTION"
    PLATFORM_PROCESSING = "PLATFORM_PROCESSING"
    RAW_PROCESSING = "RAW_PROCESSING"
    DECODE = "DECODE"
    PROFILE = "PROFILE"
    RTQC = "RTQC"
    POST_PROCESSING = "POST_PROCESSING"
    CROSS_CYCLE_RTQC = "CROSS_CYCLE_RTQC"
    PRODUCT_BUILDING = "PRODUCT_BUILDING"
    OUTPUT = "OUTPUT"
    DONE = "DONE"


class RtqcPass(str, Enum):
    PASS_A = "PASS_A"  # Non-density vertical profile tests
    PASS_B = "PASS_B"  # Density inversion test
    PASS_C = "PASS_C"  # Profile scalar tests (date, loc, land)
    PASS_D = "PASS_D"  # Cross-cycle tests (speed, frozen, drift)


class RtqcTestInfo(BaseModel):
    test_id: str  # e.g. "TEST009"
    test_number: int  # e.g. 9 (Table 11 ID)
    test_index: int | None = None  # e.g. 4 (1-based sequence progress count)
    total_tests: int | None = None  # e.g. 15 (total applicable tests)
    name: str  # e.g. "Spike Check"
    rtqc_pass: RtqcPass
    status: NodeStatus = NodeStatus.PENDING
    cycle: int | None = None
    input_params: list[str] = Field(default_factory=list)  # ["TEMP", "PSAL", "CNDC"]
    levels_checked: int = 0
    levels_flagged: int = 0
    rule_applied: str = ""  # e.g. "|v - median| > 6.0 °C"
    flags_before: list[int] = Field(default_factory=list)
    flags_after: list[int] = Field(default_factory=list)
    flag_changes: list[dict[str, Any]] = Field(default_factory=list)
    python_file: str = "rtqc/non_density.py"
    python_function: str = "run_non_density_tests"
    reason_not_run: str | None = None
    timestamp: str = Field(default_factory=utc_now_iso)


class LiveEvent(BaseModel):
    id: str
    run_id: str
    timestamp: str = Field(default_factory=utc_now_iso)
    level: Literal["info", "success", "warning", "error", "rtqc"] = "info"
    message: str  # Fast human-readable string
    stage: StageId | None = None
    operation: str | None = None
    cycle: int | None = None
    status: NodeStatus = NodeStatus.ACTIVE
    
    # Expandable details
    what_happened: str = ""
    input_summary: str = ""
    processing_details: str = ""
    output_summary: str = ""
    python_file: str = ""
    python_function: str = ""
    line_number: int | None = None
    data_sample: dict[str, Any] | None = None
    rtqc_test: RtqcTestInfo | None = None
    error_details: str | None = None


class StageState(BaseModel):
    id: StageId
    name: str
    status: NodeStatus = NodeStatus.PENDING
    active_operation: str = ""
    current_cycle: int | None = None
    total_cycles: int | None = None
    detail: str = ""
    updated_at: str = Field(default_factory=utc_now_iso)


class CycleRecord(BaseModel):
    cycle_number: int
    raw_cycle_key: int | None = None
    status: NodeStatus = NodeStatus.PENDING
    received_at: str | None = None
    juld: float | None = None
    juld_formatted: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    position_qc: str | int | None = None
    messages_received: int = 0
    messages_selected: int = 0
    levels_count: int = 0
    engineering_data: dict[str, Any] = Field(default_factory=dict)
    rtqc_summary: dict[str, Any] = Field(default_factory=dict)
    ctd_samples: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    # --- BGC (301 floats only; empty/absent otherwise — legacy untouched) ---
    # Per-profile BGC series parsed N_PROF-aware from the cycle's BR file.
    bgc_profiles: list["BgcProfile"] = Field(default_factory=list)
    bgc_source_file: str | None = None
    bgc_n_prof: int | None = None
    # True when the BR file matches the documented G2 signature
    # (non-standard N_PROF layout + labeled sensor channels entirely fill).
    matches_g2_signature: bool = False
    # False for BR-only cycles (no core R profile this cycle).
    has_core: bool = True


class BgcProfile(BaseModel):
    """One N_PROF profile of a BR file: own grid, params, series and QC."""

    profile_index: int
    station_parameters: list[str] = Field(default_factory=list)
    levels_count: int = 0
    # False when the profile labels sensor channels but all are fill.
    sensor_data_present: bool = True
    # File's own units/long names per parameter (never invented).
    param_units: dict[str, str] = Field(default_factory=dict)
    param_labels: dict[str, str] = Field(default_factory=dict)
    # {"level", "PRES", <PARAM>, <PARAM>_QC, ...}; fill reads as None.
    samples: list[dict[str, Any]] = Field(default_factory=list)


class OutputFileInfo(BaseModel):
    filename: str
    category: Literal["mono_profile", "multi_profile", "tech", "traj", "meta", "xml", "other"]
    filepath: str
    filesize_bytes: int = 0
    checksum_sha256: str = ""
    cycle: int | None = None
    dimensions: dict[str, int] = Field(default_factory=dict)
    variables: list[str] = Field(default_factory=list)
    global_attrs: dict[str, Any] = Field(default_factory=dict)
    qc_stats: dict[str, Any] = Field(default_factory=dict)
    qcp_hex: str = ""
    qcf_hex: str = ""
    xml_content: str | None = None


class RunSummary(BaseModel):
    run_id: str
    wmo: int
    float_type: str = ""
    platform_family: str = ""
    transmission_type: str = ""
    decoder_id: int | None = None
    decoder_version: str = ""
    status: NodeStatus = NodeStatus.PENDING
    orphaned: bool = False  # persisted as 'active' but owning process died; recovered at startup
    start_time: str = Field(default_factory=utc_now_iso)
    end_time: str | None = None
    duration_seconds: float = 0.0
    total_files: int = 0
    total_cycles: int = 0
    completed_cycles: int = 0
    profile_count: int = 0
    missing_profiles: int = 0
    active_stage: StageId = StageId.INPUT_FILES
    active_operation: str = "Ready to start"
    stages: dict[StageId, StageState] = Field(default_factory=dict)
    cycles: list[CycleRecord] = Field(default_factory=list)
    output_files: list[OutputFileInfo] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class BatchFloatItem(BaseModel):
    wmo: int
    run_id: str | None = None
    platform_type: str = ""
    transmission_type: str = ""
    decoder_id: int | None = None
    status: NodeStatus = NodeStatus.PENDING
    cached: bool = False  # True when this item reuses today's earlier successful run instead of re-decoding
    cycles_count: int = 0
    profiles_count: int = 0
    missing_profiles: int = 0
    outputs_count: int = 0
    duration_seconds: float = 0.0
    error_message: str | None = None
    error_type: str | None = None
    # Number of distinct errors recorded for this item (len of the run's
    # errors list, or number of pre-run problems). Drives the "(+N more)"
    # suffix so row/banner/investigation stay consistent.
    error_count: int = 0


class BatchSummary(BaseModel):
    batch_id: str
    name: str = "Today's Fleet Decoding"
    status: NodeStatus = NodeStatus.PENDING
    orphaned: bool = False  # persisted as 'active' but owning process died; recovered at startup
    created_at: str = Field(default_factory=utc_now_iso)
    ended_at: str | None = None
    duration_seconds: float = 0.0
    total_floats: int = 0
    completed_floats: int = 0
    cached_floats: int = 0  # subset of completed_floats whose results were reused from today (not re-decoded)
    failed_floats: int = 0
    stopped_floats: int = 0
    pending_floats: int = 0
    running_wmo: int | None = None
    running_run_id: str | None = None
    total_profiles_generated: int = 0
    total_profiles_missing: int = 0
    total_output_files: int = 0
    items: list[BatchFloatItem] = Field(default_factory=list)
    email_status: Literal["not_sent", "sent", "failed"] = "not_sent"
    email_sent_at: str | None = None
    email_recipient: str | None = None
    email_error: str | None = None

    # PDF daily fleet report (generated at batch terminal state; a failure
    # here is recorded but never changes the decoder/batch result)
    pdf_status: Literal["none", "generated", "failed"] = "none"
    pdf_generated_at: str | None = None
    pdf_error: str | None = None
    pdf_size_bytes: int | None = None
    pdf_pages: int | None = None


class DecodeRequest(BaseModel):
    wmo: int
    run_id: str | None = None
    input_path: str | None = None
    metadata_backend: Literal["json", "csv", "csv4"] | str | None = None
    registry_path: str | None = None
    info_dir: str | None = None
    meta_dir: str | None = None
    out_dir: str | None = None
    ref_dir: str | None = None


class BatchDecodeRequest(BaseModel):
    batch_id: str | None = None
    wmos: list[int] | None = None
    out_dir: str | None = None
    # Deliberate reprocessing: when True, floats already successfully decoded
    # today are re-decoded instead of being carried over as COMPLETED/CACHED.
    # This is what the UI's explicit "RE-RUN ALL" action sends; the normal
    # "Decode All Today's Floats" path always uses force=False.
    force: bool = False
