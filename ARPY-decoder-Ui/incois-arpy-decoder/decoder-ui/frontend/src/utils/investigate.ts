// Primary-error helpers shared by the Results row, the error banners and the
// Decoder Log investigation view.
//
// Rule: for a run with multiple errors the PRIMARY error is the latest
// meaningful (non-blank) entry, with the remainder exposed as a count so the
// operator knows more failures exist ("(+N more)").

export interface PrimaryError {
  /** Latest non-blank error text ("" when there is none). */
  text: string;
  /** How many further errors exist beyond the primary one. */
  extra: number;
}

export function primaryError(
  errors: readonly string[] | undefined | null,
): PrimaryError {
  const meaningful = (errors ?? [])
    .map((e) => (e ?? "").trim())
    .filter((e) => e.length > 0);
  if (meaningful.length === 0) return { text: "", extra: 0 };
  return { text: meaningful[meaningful.length - 1], extra: meaningful.length - 1 };
}

/** Renders "" for 0, otherwise " (+N more)". */
export function primaryErrorSuffix(extra: number): string {
  return extra > 0 ? ` (+${extra} more)` : "";
}

// ---------------------------------------------------------------------------
// Processing timeline: the fixed 7-step journey of a decoder run.
//
// Each card rolls up the raw pipeline stages that belong to it. Rollup rule:
// any error -> failed; any active/flagged -> active; all completed ->
// completed; otherwise not-reached. Unknown or absent stage keys are ignored
// (never invented).
// ---------------------------------------------------------------------------

export type TimelineStepStatus = "completed" | "failed" | "active" | "not-reached";

export interface TimelineStep {
  key: string;
  label: string;
  status: TimelineStepStatus;
  detail: string;
}

const TIMELINE_GROUPS: Array<{ key: string; label: string; stages: string[] }> = [
  { key: "input", label: "Input", stages: ["CONFIGURATION", "INPUT_DISCOVERY", "INPUT_FILES"] },
  { key: "discovery", label: "Discovery", stages: ["INPUT_PREPARATION", "DISCOVERY"] },
  { key: "metadata", label: "Metadata / Staging", stages: ["METADATA", "CALIBRATION", "WMO_MAPPING", "CYCLE_GROUPING"] },
  { key: "decoder", label: "Decoder", stages: ["DECODING", "DECODER", "DECODE", "DECODER_SELECTION", "PLATFORM_PROCESSING", "RAW_PROCESSING"] },
  { key: "netcdf", label: "NetCDF", stages: ["PRODUCT_BUILDING", "PROFILE", "POST_PROCESSING"] },
  { key: "rtqc", label: "RTQC", stages: ["RTQC", "CROSS_CYCLE_RTQC"] },
  { key: "output", label: "Output", stages: ["OUTPUT_HANDLING", "OUTPUT", "DONE"] },
];

export function buildProcessingTimeline(
  stages: Record<string, { status?: string; detail?: string }> | undefined | null,
): TimelineStep[] {
  const byKey: Record<string, { status?: string; detail?: string }> = {};
  for (const [rawKey, value] of Object.entries(stages ?? {})) {
    if (value && typeof value === "object") byKey[rawKey.toUpperCase()] = value;
  }
  return TIMELINE_GROUPS.map((group) => {
    const members = group.stages
      .map((id) => byKey[id])
      .filter((s): s is { status?: string; detail?: string } => Boolean(s));
    let status: TimelineStepStatus = "not-reached";
    if (members.some((m) => m.status === "error")) status = "failed";
    else if (members.some((m) => m.status === "active" || m.status === "flagged")) status = "active";
    else if (members.length > 0 && members.every((m) => m.status === "completed")) status = "completed";
    const detail =
      members.find((m) => m.status === "error" && m.detail)?.detail ??
      members.find((m) => m.detail)?.detail ??
      "";
    return { key: group.key, label: group.label, status, detail };
  });
}

/** Which timeline card a raw stage id belongs to (null when unknown). */
export function timelineStepForStage(stageId: string | null | undefined): string | null {
  const needle = (stageId ?? "").toUpperCase();
  if (!needle) return null;
  const group = TIMELINE_GROUPS.find((g) => g.stages.includes(needle));
  return group ? group.key : null;
}
