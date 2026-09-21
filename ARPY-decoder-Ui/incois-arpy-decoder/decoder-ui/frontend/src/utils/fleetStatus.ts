import type { FleetDataStatus, FleetStatusPayload, FleetStatusRow } from "../types";

/** Filter/sort/paginate/format helpers for the Float Status page. Pure and
 *  unit-tested; all profile/data-recency values come from the backend payload. */

export type FleetSortKey = "wmo" | "last_profile" | "days" | "prof" | "missed";
export type SortDir = "asc" | "desc";

export interface FleetFilters {
  query: string;
  floatType: string; // "" = all
  status: "" | FleetDataStatus;
}

/** Default (operational) ordering: least recent profile state first. */
const STATUS_RANK: Record<FleetDataStatus, number> = {
  "NO RECENT PROFILE DATA 60+ DAYS": 0,
  "PROFILE OVERDUE": 1,
  "NO DATA": 2,
  "ACTIVE / RECENT PROFILE": 3,
};

export function defaultSortRows(rows: FleetStatusRow[]): FleetStatusRow[] {
  return [...rows].sort(
    (a, b) =>
      STATUS_RANK[a.data_status] - STATUS_RANK[b.data_status] ||
      (b.days_since_last_profile ?? -1) - (a.days_since_last_profile ?? -1) ||
      a.wmo - b.wmo
  );
}

export function applyFleetFilters(
  rows: FleetStatusRow[],
  filters: FleetFilters
): FleetStatusRow[] {
  const q = filters.query.trim().toLowerCase();
  return rows.filter((r) => {
    if (filters.floatType && r.float_type !== filters.floatType) return false;
    if (filters.status && r.data_status !== filters.status) return false;
    if (q) {
      const hay = [String(r.wmo), r.internal_id, r.ptt, r.imei]
        .filter((v): v is string => !!v)
        .join(" ")
        .toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

function cmpNullsLast(
  a: number | null,
  b: number | null,
  dir: SortDir
): number {
  const missingA = a == null || !Number.isFinite(a);
  const missingB = b == null || !Number.isFinite(b);
  if (missingA && missingB) return 0;
  if (missingA) return 1;
  if (missingB) return -1;
  return dir === "asc" ? a - b : b - a;
}

export function sortFleetRows(
  rows: FleetStatusRow[],
  key: FleetSortKey,
  dir: SortDir
): FleetStatusRow[] {
  const val = (r: FleetStatusRow): number | null => {
    switch (key) {
      case "wmo":
        return r.wmo;
      case "last_profile":
        return r.last_profile_iso ? Date.parse(r.last_profile_iso) : null;
      case "days":
        return r.days_since_last_profile;
      case "prof":
        return r.prof_num;
      case "missed":
        return r.approx_profiles_missed;
    }
  };
  return [...rows].sort(
    (a, b) => cmpNullsLast(val(a), val(b), dir) || a.wmo - b.wmo
  );
}

export function paginateRows<T>(
  rows: T[],
  page: number,
  perPage: number
): { pageRows: T[]; totalPages: number; safePage: number } {
  const totalPages = Math.max(1, Math.ceil(rows.length / perPage));
  const safePage = Math.min(Math.max(1, page), totalPages);
  const start = (safePage - 1) * perPage;
  return {
    pageRows: rows.slice(start, start + perPage),
    totalPages,
    safePage,
  };
}

export function formatDays(days: number | null): string {
  if (days == null || !Number.isFinite(days) || days < 0) return "—";
  return `${Math.floor(days)} d`;
}

/** "2026-09-08T14:04:11+00:00" -> "2026-09-08 14:04 UTC" (minute precision). */
export function formatUTC(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const p = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ` +
    `${p(d.getUTCHours())}:${p(d.getUTCMinutes())} UTC`
  );
}

export function formatCoord(
  v: number | null,
  kind: "lon" | "lat"
): string {
  if (v == null || !Number.isFinite(v) || Math.abs(v) > (kind === "lon" ? 180 : 90)) return "—";
  const hemi = kind === "lon" ? (v < 0 ? "W" : "E") : v < 0 ? "S" : "N";
  return `${Math.abs(v).toFixed(3)}°${hemi}`;
}

/** Badge styling mirroring the Results status pills. */
export const FLEET_STATUS_META: Record<
  FleetDataStatus,
  { pill: string; dot: string }
> = {
  "ACTIVE / RECENT PROFILE": {
    pill: "bg-emerald-50 text-emerald-800 border-emerald-300",
    dot: "bg-emerald-500",
  },
  "PROFILE OVERDUE": {
    pill: "bg-amber-50 text-amber-900 border-amber-300",
    dot: "bg-amber-500",
  },
  "NO RECENT PROFILE DATA 60+ DAYS": {
    pill: "bg-rose-50 text-rose-800 border-rose-300",
    dot: "bg-rose-500",
  },
  "NO DATA": {
    pill: "bg-slate-100 text-slate-500 border-slate-300",
    dot: "bg-slate-400",
  },
};

/** Do not leave an old successful snapshot green when the API is offline or
 * the sync is disabled. Server freshness is authoritative; wall-clock expiry
 * is an additional guard between payload refreshes. Never changes data status.
 */
export function fleetCacheIsStale(payload: FleetStatusPayload | null, nowMs = Date.now()): boolean {
  if (!payload) return false;
  const sync = payload.sync;
  if (sync.stale || sync.status === "error" || sync.status === "degraded") return true;
  const checked = sync.last_success_at ? Date.parse(sync.last_success_at) : NaN;
  const generated = Date.parse(payload.generated_at);
  return !Number.isFinite(checked) || !Number.isFinite(generated) ||
    checked > nowMs || nowMs - checked > sync.interval_s * 1000 ||
    nowMs - generated > 120000;
}

/** This same paired-coordinate predicate feeds the table/map contract. */
export function hasFleetPosition(row: Pick<FleetStatusRow, "lat" | "lon">): boolean {
  return row.lat != null && row.lon != null && Number.isFinite(row.lat) &&
    Number.isFinite(row.lon) && Math.abs(row.lat) <= 90 && Math.abs(row.lon) <= 180;
}

/** Exact cadence labels: sub-hour schedules must not read as "0 h". */
export function formatSyncInterval(seconds: number | null): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return "—";
  if (seconds % 3600 === 0) return `${seconds / 3600} h`;
  if (seconds % 60 === 0) return `${seconds / 60} min`;
  return `${seconds} s`;
}

/** Monitoring estimate, deliberately not a published-file inventory label.
 *  Legacy/fallback wording — the per-float note below is preferred, because the
 *  expected interval is measured from each float's own published profile
 *  dates whenever the history is sufficient. */
export const APPROX_PROFILES_MISSED_NOTE =
  "Approximate estimate based on the expected 10-day profile cycle.";

/** Per-float note: observed interval + its source, or the documented fallback. */
export function approxMissedNote(row: {
  expected_interval_days?: number | null;
  expected_interval_source?: string | null;
  expected_interval_samples?: number | null;
  interval_note?: string | null;
}): string {
  if (row.interval_note) return row.interval_note;
  const days = row.expected_interval_days;
  const source = row.expected_interval_source;
  const samples = row.expected_interval_samples ?? 0;
  if (days == null || !Number.isFinite(days)) return APPROX_PROFILES_MISSED_NOTE;
  if (!source || source === "default 10-day cycle") return APPROX_PROFILES_MISSED_NOTE;
  const where =
    source === "profile history" ? "published profile dates" : "trajectory cycles";
  return `Approximate estimate based on the observed ${days.toFixed(1)}-day profile cycle (median of ${samples} ${where}).`;
}

/** "9.99 d (profile history · 96 intervals)" for the detail drawer. */
export function formatInterval(row: {
  expected_interval_days?: number | null;
  expected_interval_source?: string | null;
  expected_interval_samples?: number | null;
}): string {
  const days = row.expected_interval_days;
  if (days == null || !Number.isFinite(days)) return "—";
  const source = row.expected_interval_source || "unknown source";
  const samples = row.expected_interval_samples ?? 0;
  return samples > 0
    ? `${days.toFixed(2)} d (${source}, ${samples} intervals)`
    : `${days.toFixed(2)} d (${source})`;
}

/** Forward-test line for the drawer: only what the audit actually measured. */
export function formatForwardTest(stats: {
  n?: number;
  median_km?: number;
  mean_km?: number;
  p90_km?: number;
  max_km?: number;
  within_r50_pct?: number;
  within_r90_pct?: number;
  median_time_error_days?: number;
} | null | undefined): string {
  if (!stats || !stats.n) return "—";
  const parts = [`${stats.n} scored`];
  if (stats.median_km != null) parts.push(`median ${stats.median_km} km`);
  if (stats.p90_km != null) parts.push(`p90 ${stats.p90_km} km`);
  if (stats.within_r50_pct != null && stats.within_r90_pct != null) {
    parts.push(`${stats.within_r50_pct}% within r50 / ${stats.within_r90_pct}% within r90`);
  }
  if (stats.median_time_error_days != null) {
    parts.push(`time error ${stats.median_time_error_days} d`);
  }
  return parts.join(" · ");
}

/** Prediction status → short badge wording (never a fabricated value). */
export function predictionStatusLabel(status: string | null | undefined): string {
  switch (status) {
    case "ok":
      return "AVAILABLE";
    case "insufficient_data":
      return "INSUFFICIENT DATA";
    case "insufficient_validation":
      return "NOT VALIDATED";
    case "source_unavailable":
      return "SOURCE UNAVAILABLE";
    default:
      return "UNAVAILABLE";
  }
}

/** Uncertainty wording; the radius is always the validated one from the payload. */
export function formatPredictionRadius(
  r50: number | null | undefined,
  r90: number | null | undefined
): string {
  if (r50 == null || r90 == null || !Number.isFinite(r50) || !Number.isFinite(r90)) return "—";
  return `${r50.toFixed(1)} km (50%) / ${r90.toFixed(1)} km (90%)`;
}

export function formatPredictionHorizon(days: number | null | undefined): string {
  if (days == null || !Number.isFinite(days) || days <= 0) return "—";
  return `+${days.toFixed(2)} d`;
}
