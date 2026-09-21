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
export type FleetCommStatus =
  | "ACTIVE"
  | "OVERDUE"
  | "NO COMMUNICATION 60+ DAYS"
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

export interface FleetStatusRow {
  wmo: number;
  internal_id: string | null;
  ptt: string | null;
  imei: string | null;
  float_type: string;
  transmission_type: string;
  in_incois_dac: boolean | null;
  /** Highest published cycle number, not the count of available cycles. */
  prof_num: number | null;
  profile_count?: number | null;
  profiles_missing: number | null;
  profiles_missing_list: number[];
  lon: number | null;
  lat: number | null;
  pos_source: "profile" | "traj" | null;
  pos_qc: string | null;
  position_iso?: string | null;
  position_time_field?: string | null;
  position_file?: string | null;
  position_error?: string | null;
  last_tx_iso: string | null;
  last_tx_field: string | null;
  last_tx_status_rt19: string | null;
  last_tx_index?: number | null;
  last_tx_cycle?: number | null;
  communication_error?: string | null;
  days_since_last_tx: number | null;
  expected_next_iso: string | null;
  status: FleetCommStatus;
  traj_max_cycle: number | null;
  latest_profile: FleetLatestProfile | null;
  traj_last_fix: FleetTrajFix | null;
  traj_lagging_profiles: boolean | null;
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
  active: number;
  overdue: number;
  no_comm_60: number;
  no_data: number;
  profiles_missing_total: number;
  total_profiles: number;
  profile_records_known?: number;
  stale_rows?: number;
}

export interface FleetStatusSource {
  host: string;
  port: number;
  root: string;
  dac: string;
  product: string;
  field: string;
  interval_s: number;
}

export interface FleetStatusPayload {
  generated_at: string;
  sync: FleetSyncState;
  summary: FleetStatusSummary;
  floats: FleetStatusRow[];
  source: FleetStatusSource;
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
