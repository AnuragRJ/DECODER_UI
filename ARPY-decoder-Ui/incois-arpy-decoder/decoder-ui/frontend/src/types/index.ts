export type NodeStatus =
  | "pending"
  | "active"
  | "completed"
  | "flagged"
  | "not_run"
  | "error"
  | "stopped"
  | "cancelled";

export type StageId =
  | "INPUT_FILES"
  | "CONFIGURATION"
  | "METADATA"
  | "DISCOVERY"
  | "WMO_MAPPING"
  | "CYCLE_GROUPING"
  | "DECODER_SELECTION"
  | "PLATFORM_PROCESSING"
  | "RAW_PROCESSING"
  | "DECODE"
  | "PROFILE"
  | "RTQC"
  | "POST_PROCESSING"
  | "CROSS_CYCLE_RTQC"
  | "PRODUCT_BUILDING"
  | "OUTPUT"
  | "DONE";

export type RtqcPass = "PASS_A" | "PASS_B" | "PASS_C" | "PASS_D" | "PASS_BGC";

export interface RtqcTestInfo {
  test_id: string;
  test_number: number;
  test_index?: number;
  total_tests?: number;
  name: string;
  rtqc_pass: RtqcPass;
  status: NodeStatus;
  cycle?: number;
  input_params: string[];
  levels_checked: number;
  levels_flagged: number;
  rule_applied: string;
  flags_before: number[];
  flags_after: number[];
  flag_changes: Array<{
    level: number;
    param: string;
    from: number;
    to: number;
  }>;
  python_file: string;
  python_function: string;
  reason_not_run?: string;
  timestamp: string;
}

export interface LiveEvent {
  id: string;
  run_id: string;
  timestamp: string;
  level: "info" | "success" | "warning" | "error" | "rtqc";
  message: string;
  stage?: StageId;
  operation?: string;
  cycle?: number;
  status: NodeStatus;
  what_happened: string;
  input_summary: string;
  processing_details: string;
  output_summary: string;
  python_file: string;
  python_function: string;
  line_number?: number;
  data_sample?: Record<string, any>;
  rtqc_test?: RtqcTestInfo;
  error_details?: string;
}

export interface StageState {
  id: StageId;
  name: string;
  status: NodeStatus;
  active_operation: string;
  current_cycle?: number;
  total_cycles?: number;
  detail: string;
  updated_at: string;
}

/** One N_PROF profile of a cycle's BR file: own grid, params, series and QC.
 *  Present only on 301-float runs (parsed N_PROF-aware by the service);
 *  legacy runs carry an empty list. Optional so pre-BGC run records still load. */
export interface BgcProfile {
  profile_index: number;
  station_parameters: string[];
  levels_count: number;
  /** False when the profile labels sensor channels but all of them are fill. */
  sensor_data_present: boolean;
  /** The file's own units / long names per parameter (never invented). */
  param_units: Record<string, string>;
  param_labels: Record<string, string>;
  /** { level, PRES, <PARAM>, <PARAM>_QC, ... }; fill reads as null. */
  samples: Array<Record<string, number | string | null>>;
}

export interface CycleRecord {
  cycle_number: number;
  raw_cycle_key?: number;
  status: NodeStatus;
  received_at?: string;
  juld?: number;
  juld_formatted?: string;
  latitude?: number;
  longitude?: number;
  position_qc?: string | number;
  messages_received: number;
  messages_selected: number;
  levels_count: number;
  engineering_data: Record<string, any>;
  rtqc_summary: Record<string, any>;
  ctd_samples: Array<{
    level: number;
    PRES: number;
    TEMP: number;
    PSAL: number;
    CNDC?: number;
    PRES_QC: number;
    TEMP_QC: number;
    PSAL_QC: number;
  }>;
  errors: string[];
  /** BGC series of this cycle (301 floats only; [] on legacy / pre-BGC runs). */
  bgc_profiles?: BgcProfile[];
  bgc_source_file?: string | null;
  bgc_n_prof?: number | null;
  /** True when the BR file matches the documented G2 signature
   *  (non-standard N_PROF layout + labeled sensor channels entirely fill). */
  matches_g2_signature?: boolean;
  /** False for BR-only cycles (no core R profile this cycle). */
  has_core?: boolean;
}

export interface OutputFileInfo {
  filename: string;
  category: "mono_profile" | "multi_profile" | "tech" | "traj" | "meta" | "xml" | "other";
  filepath: string;
  filesize_bytes: number;
  checksum_sha256: string;
  cycle?: number;
  dimensions: Record<string, number>;
  variables: string[];
  global_attrs: Record<string, any>;
  qc_stats: Record<string, any>;
  qcp_hex: string;
  qcf_hex: string;
  xml_content?: string;
}

export interface RunSummary {
  run_id: string;
  wmo: number;
  float_type: string;
  platform_family: string;
  transmission_type: string;
  decoder_id?: number;
  decoder_version: string;
  status: NodeStatus;
  /** True when this run was persisted as 'active' but its process died (recovered at startup). */
  orphaned?: boolean;
  start_time: string;
  end_time?: string;
  duration_seconds: number;
  total_files: number;
  total_cycles: number;
  completed_cycles: number;
  profile_count?: number;
  missing_profiles?: number;
  active_stage: StageId;
  active_operation: string;
  stages: Record<StageId, StageState>;
  cycles: CycleRecord[];
  output_files: OutputFileInfo[];
  errors: string[];
  error_paragraph?: string | null;
  rtqc_summary?: Record<string, any> | null;
  total_levels?: number;
}

export interface FloatPreset {
  wmo: number;
  name: string;
  platform_type: string;
  transmission_type: string;
  decoder_id: number;
  decoder_version: string;
  input_path: string;
  metadata_backend: "json" | "csv" | "csv4" | string;
  registry_path?: string;
  info_dir?: string;
  meta_dir?: string;
  description: string;
  input_file_count: number;
  is_default?: boolean;
}

export interface BatchFloatItem {
  wmo: number;
  run_id?: string | null;
  platform_type: string;
  transmission_type: string;
  decoder_id?: number | null;
  status: NodeStatus;
  /** True when this float reused today's earlier successful run instead of being re-decoded. */
  cached?: boolean;
  cycles_count: number;
  profiles_count: number;
  missing_profiles: number;
  outputs_count: number;
  duration_seconds: number;
  error_message?: string | null;
  error_type?: string | null;
  /** Number of distinct errors recorded for this item (drives the "(+N more)" suffix). */
  error_count?: number;
}

export interface TriageEvidence {
  source: string;
  detail: string;
}

export interface TriageItem {
  wmo: number;
  run_id?: string | null;
  status: string;
  category: string;
  category_label: string;
  root_cause: string;
  recommended_action: string;
  evidence: TriageEvidence[];
}

export interface BatchSummary {
  batch_id: string;
  name: string;
  status: NodeStatus;
  /** True when this batch was persisted as 'active' but its process died (recovered at startup). */
  orphaned?: boolean;
  created_at: string;
  ended_at?: string | null;
  duration_seconds: number;
  total_floats: number;
  completed_floats: number;
  /** Subset of completed_floats carried over from today's successful runs (not re-decoded). */
  cached_floats?: number;
  failed_floats: number;
  stopped_floats: number;
  pending_floats: number;
  running_wmo?: number | null;
  running_run_id?: string | null;
  total_profiles_generated: number;
  total_profiles_missing: number;
  total_output_files: number;
  items: BatchFloatItem[];
  email_status?: "not_sent" | "sent" | "failed";
  email_sent_at?: string | null;
  email_recipient?: string | null;
  email_error?: string | null;
  pdf_status?: "none" | "generated" | "failed";
  pdf_generated_at?: string | null;
  pdf_error?: string | null;
  pdf_size_bytes?: number | null;
  pdf_pages?: number | null;
}

// ---------------------------------------------------------------------------
// Incoming-data ingestion (normalized arrival contract — source independent)
// ---------------------------------------------------------------------------

/** One normalized float association discovered by the active DataSource.
 *  Fields are null unless the source genuinely provides them. */
export interface IngestionArrival {
  fingerprint: string;
  identifier: string;
  wmo: number | null;
  platform: string | null;
  cycle_number: number | null;
  juld: string | null;
  latitude: number | null;
  longitude: number | null;
  source_id: string;
  source_kind: string;
  arrived_at: string;
  files: number;
  parser_pending: boolean;
  ingested_at: string;
  state: "new" | "seen";
  is_new_wmo: boolean;
}

/** Float Status — one fleet row served from the Ifremer GDAC sync cache.
 *  Every communication timestamp is authoritative upstream data; derived
 *  fields (days-since, status, expected-next) are computed backend-side at
 *  serve time. See decoder-ui/FLEET_STATUS.md. */
export type FleetDataStatus =
  | "ACTIVE / RECENT PROFILE"
  | "PROFILE OVERDUE"
  | "NO RECENT PROFILE DATA 60+ DAYS"
  | "NO DATA";

export interface FleetLatestProfile {
  file: string | null;
  prefix: string | null;
  cycle: number | null;
  juld_iso: string | null;
  lat: number | null;
  lon: number | null;
  pos_qc: string | null;
  cycle_mismatch: boolean;
  position_iso?: string | null;
  position_error?: string | null;
}

export interface FleetTrajFix {
  juld_iso: string;
  lat: number;
  lon: number;
  cycle: number | null;
  mc: number | null;
  pos_qc: string | null;
}

export type PredictionStatus =
  | "ok"
  | "insufficient_data"
  | "insufficient_validation"
  | "source_unavailable";

export type PredictionMethod =
  | "history_prior"
  | "trajectory_extrapolation"
  | "regional_prior"
  | "persistence"
  | "current_assisted"
  | "physics_lagrangian"
  | "ml_residual"
  /* Stage-1 cycle-scale step (opt-in; Stage-0 remains the default) */
  | "cycle_window"
  | "cycle_window_prior"
  | "cycle_median"
  | "cycle_median_prior";

/** Experimental next-profile-location prediction (server-derived). */
export interface FleetPrediction {
  wmo: number;
  available: boolean;
  status: PredictionStatus;
  status_message: string | null;
  predicted_lat: number | null;
  predicted_lon: number | null;
  prediction_horizon_days: number | null;
  target_time_iso: string | null;
  r50_km: number | null;
  r90_km: number | null;
  method: PredictionMethod | null;
  method_label: string | null;
  /** Which predictor stage produced this prediction ("stage0" | "stage1"). */
  predictor_stage?: "stage0" | "stage1" | null;
  predictor_stage_label?: string | null;
  /** Stage-1 provenance: the cycle-scale window actually used for the step. */
  step_basis?: string | null;
  step_span_days?: number | null;
  step_ratio?: number | null;
  step_cycles?: number | null;
  step_windows_used?: number | null;
  stage1_fallback_reason?: string | null;
  fallback_rung: number | null;
  validation_samples: number;
  validation_source: string | null;
  ensemble_members: number | null;
  ensemble_spread_km: number | null;
  issued_from_iso: string | null;
  issued_from_position: [number, number] | null;
  expected_interval_days: number | null;
  interval_source: string | null;
  interval_samples: number | null;
  region: string | null;
  cycle_class: string | null;
  trajectory_transitions: number;
  prior_neighbours: number | null;
  prior_basis: string | null;
  currents: string | null;
  issues: string[];
  /** This float's own scored predictions (deployment-local audit). */
  forward_test?: FleetForwardTestStats | null;
  generated_at: string | null;
  label: string;
}

/** Deployment-local forward test: how this float's earlier predictions scored
 *  when the next verified fix actually arrived. Absent until something has been
 *  scored — the UI must not imply an audit that has not happened. */
export interface FleetForwardTestStats {
  n: number;
  median_km?: number;
  mean_km?: number;
  p90_km?: number;
  max_km?: number;
  within_r50_pct?: number;
  within_r90_pct?: number;
  median_time_error_days?: number;
}

export interface FleetForwardTestSummary {
  enabled: boolean;
  path: string;
  issued: number;
  scored: number;
  pending: number;
  note?: string;
  error?: string | null;
  overall?: FleetForwardTestStats | null;
  methods?: Record<string, FleetForwardTestStats>;
  floats?: Record<string, FleetForwardTestStats>;
}

export interface FleetPredictionSummary {
  available: number;
  unavailable: number;
  methods: Record<string, number>;
  calibration: {
    available: boolean;
    version: number;
    generated_at: string | null;
    path: string | null;
    load_error: string | null;
    blend_weight_on_prior: number;
    corpus: Record<string, unknown>;
    prior_grid_cells: number;
    methods: Record<
      string,
      { label: string; r50_km: number | null; r90_km: number | null; samples: number | null }
    >;
  } | null;
  forward_test?: FleetForwardTestSummary | null;
  error?: string | null;
  currents: string | null;
  label: string;
}

export interface FleetStatusRow {
  wmo: number;
  internal_id: string | null;
  ptt: string | null;
  imei: string | null;
  float_type: string;
  transmission_type: string;
  in_incois_dac: boolean | null;
  /** Highest published cycle, not an available-profile count. */
  prof_num: number | null;
  profile_count: number | null;
  lon: number | null;
  lat: number | null;
  pos_source: "profile" | "traj" | null;
  pos_qc: string | null;
  position_iso?: string | null;
  position_time_field?: string | null;
  position_file?: string | null;
  position_error?: string | null;
  /** Monitoring authority: max valid JULD in <WMO>_prof.nc only. */
  last_profile_iso: string | null;
  last_profile_juld: number | null;
  last_profile_index: number | null;
  last_profile_cycle: number | null;
  last_profile_file: string;
  last_profile_field: "JULD";
  profile_date_error: string | null;
  profile_history_lagging_latest_file?: boolean | null;
  profile_checked_at: string | null;
  expected_next_profile_iso: string | null;
  /** Observed cycle interval (median of valid profile JULDs) or the 10-day fallback. */
  expected_interval_days?: number | null;
  expected_interval_source?: string | null;
  expected_interval_samples?: number | null;
  interval_note?: string | null;
  days_since_last_profile: number | null;
  /** Approximation from elapsed time, never the published-file gap count. */
  approx_profiles_missed: number | null;
  data_status: FleetDataStatus;
  /** Next-profile-location prediction (null only on legacy payloads). */
  prediction?: FleetPrediction | null;
  traj_max_cycle: number | null;
  latest_profile: FleetLatestProfile | null;
  traj_last_fix: FleetTrajFix | null;
  rtraj_mdtm: string | null;
  error: string | null;
  updated_at: string | null;
  checked_at?: string | null;
  stale?: boolean;
  stale_reason?: string | null;
  cache_age_seconds?: number | null;
}

export interface FleetSyncState {
  status: "ok" | "degraded" | "error" | "never-synced" | "disabled" | "running";
  running: boolean;
  progress: { done: number; total: number };
  last_attempt_at: string | null;
  last_success_at: string | null;
  last_completed_at?: string | null;
  persistence_error?: string | null;
  stale?: boolean;
  stale_reason?: string | null;
  age_seconds?: number | null;
  interval_s: number;
  error: string | null;
  counts: { total: number; updated: number; unchanged: number; failed: number } | Record<string, never>;
}

export interface FleetStatusSummary {
  total: number;
  recent_profile: number;
  profile_overdue: number;
  no_recent_profile_60: number;
  no_data: number;
  approx_profiles_missed_total: number | null;
  profile_dates_known: number;
  total_profiles: number;
  profile_records_known?: number;
  stale_rows?: number;
}

export interface FleetStatusSource {
  host: string;
  port: number;
  root: string;
  dac: string;
  monitoring: "profile-recency";
  product: string;
  field: string;
  expected_profile_interval_days: number;
  approximation_note: string;
  interval_policy?: string;
  interval_s: number;
}

export interface FleetStatusPayload {
  generated_at: string;
  sync: FleetSyncState;
  summary: FleetStatusSummary;
  floats: FleetStatusRow[];
  source: FleetStatusSource;
  prediction?: FleetPredictionSummary | null;
}

/** Sanitized status of the active ingestion source (never credentials). */
export interface IngestionStatus {
  kind: string;
  configured: boolean;
  connected: boolean;
  detail: string;
  mode: string;
  test_mode: boolean;
  poll_interval_s: number;
  scans: number;
  last_scan_at: string | null;
  last_scan_records: number;
  last_new_arrivals: number;
  arrivals_total: number;
  new_arrivals: number;
  last_error: string | null;
}

export interface InvestigationFocusEvent {
  id: string;
  stage: string | null;
  operation: string | null;
  cycle: number | null;
  timestamp: string;
  message: string;
  level: string;
  input_summary: string;
  python_file: string;
  python_function: string;
  has_error_details: boolean;
}

export interface InvestigationStageState {
  status: string;
  detail: string;
  active_operation: string;
}

/** Payload of GET /api/runs/{run_id}/investigation — single source of truth
 * for the interactive Error Detail view (same triage engine as batch triage). */
export interface RunInvestigation {
  run_id: string;
  wmo: number;
  status: string;
  category: string;
  category_label: string;
  root_cause: string;
  recommended_action: string;
  evidence: TriageEvidence[];
  primary_error: string;
  error_count: number;
  all_errors: string[];
  root_cause_available: boolean;
  failure_stage: string | null;
  stages: Record<string, InvestigationStageState>;
  focus_event: InvestigationFocusEvent | null;
  started_at: string;
  ended_at: string | null;
  duration_seconds: number;
  total_files: number;
  total_cycles: number;
  outputs_count: number;
  is_prerun: boolean;
}
