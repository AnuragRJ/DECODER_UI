from pathlib import Path
root=Path('/home/user/ARPY-decoder-Ui/incois-arpy-decoder/decoder-ui/frontend/src')
p=root/'types/index.ts';s=p.read_text()
s=s.replace('''  cycle_mismatch: boolean;
}

export interface FleetTrajFix''','''  cycle_mismatch: boolean;
  position_iso?: string | null;
  position_error?: string | null;
}

export interface FleetTrajFix''')
s=s.replace('''  prof_num: number | null;
  profiles_missing:''','''  /** Highest published cycle number, not the count of available cycles. */
  prof_num: number | null;
  profile_count?: number | null;
  profiles_missing:''')
s=s.replace('''  pos_source: "profile" | "traj" | null;
  pos_qc: string | null;''','''  pos_source: "profile" | "traj" | null;
  pos_qc: string | null;
  position_iso?: string | null;
  position_time_field?: string | null;
  position_file?: string | null;
  position_error?: string | null;''')
s=s.replace('''  last_tx_status_rt19: string | null;
  days_since_last_tx:''','''  last_tx_status_rt19: string | null;
  last_tx_index?: number | null;
  last_tx_cycle?: number | null;
  communication_error?: string | null;
  days_since_last_tx:''')
s=s.replace('''  updated_at: string | null;
}

export interface FleetSyncState''','''  updated_at: string | null;
  checked_at?: string | null;
  stale?: boolean;
  stale_reason?: string | null;
  cache_age_seconds?: number | null;
}

export interface FleetSyncState''')
s=s.replace('''  last_success_at: string | null;
  interval_s: number;''','''  last_success_at: string | null;
  last_completed_at?: string | null;
  persistence_error?: string | null;
  stale?: boolean;
  stale_reason?: string | null;
  age_seconds?: number | null;
  interval_s: number;''')
s=s.replace('''  total_profiles: number;
}

export interface FleetStatusSource''','''  total_profiles: number;
  profile_records_known?: number;
  stale_rows?: number;
}

export interface FleetStatusSource''')
p.write_text(s)
p=root/'utils/fleetStatus.ts';s=p.read_text().replace('FleetCommStatus, FleetStatusRow','FleetCommStatus, FleetStatusPayload, FleetStatusRow')
s=s.replace('''  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;''','''  const missingA = a == null || !Number.isFinite(a);
  const missingB = b == null || !Number.isFinite(b);
  if (missingA && missingB) return 0;
  if (missingA) return 1;
  if (missingB) return -1;''')
s=s.replace('''  if (days === null || days === undefined || Number.isNaN(days)) return "—";
  return `${Math.max(0, Math.floor(days))} d`;''','''  if (days == null || !Number.isFinite(days) || days < 0) return "—";
  return `${Math.floor(days)} d`;''')
s=s.replace('''  if (v === null || v === undefined || Number.isNaN(v)) return "—";''','''  if (v == null || !Number.isFinite(v) || Math.abs(v) > (kind === "lon" ? 180 : 90)) return "—";''')
s += '''
/** Do not leave an old successful snapshot green when the API is offline or
 * the sync is disabled. Server freshness is authoritative; wall-clock expiry
 * is an additional guard between payload refreshes. Never changes comm status.
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
'''
p.write_text(s)
p=root/'store/useFleetStatusStore.ts';s=p.read_text()
s=s.replace('''    set({ loading: true });
    try {
      const res = await fetch("/api/fleet-status");''','''    set({ loading: true });
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const res = await fetch("/api/fleet-status", { signal: controller.signal });''')
s=s.replace('''    } finally {
      set({ loading: false });''','''    } finally {
      clearTimeout(timeout);
      set({ loading: false });''')
p.write_text(s)
p=root/'components/FloatStatusPage.tsx';s=p.read_text()
s=s.replace('''  formatUTC,
  paginateRows,''','''  formatUTC,
  fleetCacheIsStale,
  hasFleetPosition,
  paginateRows,''')
s=s.replace('.filter((r) => r.lat !== null && r.lon !== null)','.filter(hasFleetPosition)')
s=s.replace('cyclesCount: r.prof_num || 0','cyclesCount: r.profile_count ?? 0')
s=s.replace('''  const stale = syncState === "degraded" || syncState === "error";''','''  const stale = Boolean(fetchError) || fleetCacheIsStale(payload);''')
s=s.replace('''              sync?.error ||
              (sync?.last_success_at''','''              fetchError || sync?.stale_reason || sync?.error ||
              (sync?.last_success_at''')
s=s.replace('''<span className="text-amber-200 font-bold">Stale upstream</span>''','''<span className="text-amber-200 font-bold">Stale cache{syncState === "disabled" ? " · sync disabled" : ""}</span>''')
s=s.replace('''last success: {sync?.last_success_at''','''last full sync: {sync?.last_success_at''')
needle='''      {/* ===================== Summary metrics ===================== */}'''
s=s.replace(needle,'''      {(stale || syncing) && payload && (
        <div data-testid="fleet-freshness-notice" className="px-4 py-1.5 bg-amber-50 border-b border-amber-200 text-amber-900 font-mono text-[11.5px] shrink-0">
          {stale ? "Cached observations — current upstream state is not fully verified. " : "Checking upstream; showing the last verified snapshot. "}
          {fetchError || sync?.stale_reason || ""}
          {" "}Status evaluated at {formatUTC(payload.generated_at)}. A new API response is not a new float transmission.
        </div>
      )}

'''+needle)
s=s.replace('''<CommMetric label="PROFILES MISSING" value={String(summary?.profiles_missing_total ?? "—")} valueClass="text-[#276095]" barClass="bg-[#276095]/60" />''','''<CommMetric label="PROFILES MISSING" value={String(summary?.profiles_missing_total ?? "—")} valueClass="text-[#276095]" barClass="bg-[#276095]/60" title={`File-cycle gaps in 1..Prof#, not communication gaps. Listings available for ${summary?.profile_records_known ?? 0}/${summary?.total ?? 0} floats.`} />''')
s=s.replace('''<CommMetric label="TOTAL PROFILES" value={String(summary?.total_profiles ?? "—")} valueClass="text-[#1d547d]" barClass="bg-[#1d547d]/60" />''','''<CommMetric label="PROFILE CYCLES" value={String(summary?.total_profiles ?? "—")} valueClass="text-[#1d547d]" barClass="bg-[#1d547d]/60" title={`Available unique positive cycles, not the sum of Prof# or BGC sensor grids. Listings available for ${summary?.profile_records_known ?? 0}/${summary?.total ?? 0} floats.`} />''')
s=s.replace('''footerNote="positions from Ifremer GDAC upstream (latest profile, else traj fix)"''','''footerNote="newest verified QC 1/2 upstream position · source/time in detail"''')
s=s.replace('''<th className="py-2.5 px-2 text-right font-bold">Lon (E)</th>''','''<th className="py-2.5 px-2 text-right font-bold">Longitude</th>''')
s=s.replace('''<th className="py-2.5 px-2 text-right font-bold">Lat (N)</th>''','''<th className="py-2.5 px-2 text-right font-bold">Latitude</th>''')
s=s.replace('''<SortTh label="Prof#" k="prof"''','''<SortTh label="Prof#" help="Highest upstream published cycle, not available profile count" k="prof"''')
s=s.replace('''<SortTh label="No Transmission" k="days"''','''<SortTh label="No Communication" help="Completed days since the verified upstream transmission" k="days"''')
s=s.replace('''<SortTh label="# Profs Missing" k="missing"''','''<SortTh label="# Profs Missing" help="Missing file cycles in 1..Prof# across upstream R/D/B/S families, not missed transmissions" k="missing"''')
s=s.replace('''<td className="py-2.5 px-2.5 font-bold text-[#276095] tabular-nums">{r.wmo}</td>''','''<td className="py-2.5 px-2.5 font-bold text-[#276095] tabular-nums" data-field="wmo">
                          {r.wmo}
                          {r.stale && <span data-testid={`fleet-stale-${r.wmo}`} title={r.stale_reason || "Cached observation needs re-verification"} className="block text-[9px] text-amber-700">STALE CACHE</span>}
                        </td>''')
s=s.replace('''className="py-2.5 px-2 text-slate-600 text-[12.5px] tabular-nums">''','''className="py-2.5 px-2 text-slate-600 text-[12.5px] tabular-nums" data-field="internal_id">''')
s=s.replace('''className="py-2.5 px-2 text-center text-slate-700 font-semibold tabular-nums">''','''className="py-2.5 px-2 text-center text-slate-700 font-semibold tabular-nums" data-field="prof_num" title="Highest published cycle; see detail for available count">''')
s=s.replace('''<td className="py-2.5 px-2 text-right text-slate-700 tabular-nums whitespace-nowrap">
                          {r.lon''','''<td className="py-2.5 px-2 text-right text-slate-700 tabular-nums whitespace-nowrap" data-field="lon" title={`${r.position_file || "No verified position"} · ${formatUTC(r.position_iso || null)}`}>
                          {r.lon''')
s=s.replace('''<td className="py-2.5 px-2 text-right text-slate-700 tabular-nums whitespace-nowrap">
                          {r.lat''','''<td className="py-2.5 px-2 text-right text-slate-700 tabular-nums whitespace-nowrap" data-field="lat" title={`${r.position_file || "No verified position"} · ${formatUTC(r.position_iso || null)}`}>
                          {r.lat''')
s=s.replace('''className="py-2.5 px-2 text-slate-700 text-[12.5px] whitespace-nowrap tabular-nums"
                          title={''','''className="py-2.5 px-2 text-slate-700 text-[12.5px] whitespace-nowrap tabular-nums"
                          data-field="last_tx_iso"
                          title={''')
s=s.replace(''': r.error || "No upstream timestamp"''',''': r.communication_error || r.error || "No upstream timestamp"''')
s=s.replace('''Trajectory last message is older than the latest upstream profile — DAC trajectory lag (see detail)''','''A newer profile measurement exists; it is not a substitute for a communication timestamp (see detail)''')
s=s.replace('''<td className="py-2.5 px-2 text-right font-bold tabular-nums whitespace-nowrap">''','''<td className="py-2.5 px-2 text-right font-bold tabular-nums whitespace-nowrap" data-field="days_since_last_tx" title={`Elapsed days; evaluated at ${formatUTC(payload?.generated_at || null)}`}>''')
s=s.replace('''className="py-2.5 px-2 text-center font-bold tabular-nums"
                          title={''','''className="py-2.5 px-2 text-center font-bold tabular-nums"
                          data-field="profiles_missing"
                          title={''')
s=s.replace('''<td className="py-2.5 px-2 text-slate-600 text-[12.5px]">{r.float_type}</td>''','''<td className="py-2.5 px-2 text-slate-600 text-[12.5px]" data-field="float_type">{r.float_type}</td>''')
s=s.replace('''<td className="py-2 px-2">
                          <span''','''<td className="py-2 px-2" data-field="status">
                          <span''')
s=s.replace('''title={r.error || undefined}''','''title={r.communication_error || r.error || undefined}''')
s=s.replace('''<aside className="fixed top-0''','''<aside data-testid="fleet-detail" className="fixed top-0''')
s=s.replace('''<DetailRow label="Internal ID" value={selected.internal_id || "— (none on record)"} />''','''<DetailRow label="Internal ID (local)" value={selected.internal_id || "— (unavailable / sanitized)"} />''')
s=s.replace('''<DetailSection title="Communication (Ifremer GDAC)">
                <DetailRow''','''<DetailSection title="Communication (Ifremer GDAC)">
                <DetailRow label="Product" value={`dac/${source?.dac || "incois"}/${selected.wmo}/${selected.wmo}_Rtraj.nc`} />
                <DetailRow''')
s=s.replace('''<DetailRow label="Expected next" value={formatUTC(selected.expected_next_iso)} />''','''<DetailRow label="Expected next (+10 days)" value={formatUTC(selected.expected_next_iso)} />
                {selected.communication_error && <p className="text-amber-800 text-[11.5px]">{selected.communication_error}</p>}
                {selected.last_tx_index != null && <DetailRow label="Source cycle / array index" value={`${selected.last_tx_cycle ?? "—"} / ${selected.last_tx_index} (0-based)`} />}''')
s=s.replace('''label="No transmission"''','''label="No communication"''')
s=s.replace('''`${selected.days_since_last_tx.toFixed(1)} days`''','''`${selected.days_since_last_tx.toFixed(3)} days`''')
s=s.replace('''? "latest upstream profile"
                        : "trajectory last fix"''','''? "upstream profile (newer valid position)"
                        : "trajectory latest valid fix"''')
s=s.replace('''{selected.pos_qc && <DetailRow label="Position QC" value={selected.pos_qc} />}
              </DetailSection>''','''{selected.pos_qc && <DetailRow label="Position QC" value={selected.pos_qc} />}
                <DetailRow label="Position observed" value={formatUTC(selected.position_iso || null)} />
                <DetailRow label="Position time field" value={selected.position_time_field || "—"} />
                <DetailRow label="Position file" value={selected.position_file || "—"} />
                {selected.position_error && <p className="text-amber-800 text-[11.5px]">{selected.position_error}</p>}
              </DetailSection>''')
s=s.replace('''<DetailSection title="Profiles (upstream)">
                <DetailRow''','''<DetailSection title="Profiles (upstream)">
                <DetailRow label="Available profile cycles" value={selected.profile_count != null ? String(selected.profile_count) : "—"} />
                <DetailRow''')
s=s.replace('''label="Missing profiles"''','''label="Missing file cycles"''')
s=s.replace('''⚠ Trajectory is behind the profiles: the latest upstream profile was measured
                    after the trajectory's last recorded message (DAC trajectory lag).''','''⚠ A profile measurement is newer than the recorded communication. Upstream products
                    disagree in recency; profile time is not substituted for Last Transmission.''')
s=s.replace('''<DetailRow label="Row refreshed" value={formatUTC(selected.updated_at)} />''','''<DetailRow label="Upstream checked" value={formatUTC(selected.checked_at || null)} />
                <DetailRow label="Contents read" value={formatUTC(selected.updated_at)} />
                <DetailRow label="Cache freshness" value={selected.stale ? selected.stale_reason || "Stale" : "Verified within sync interval"} />''')
s=s.replace('''⚠ {selected.error} (last valid row retained)''','''⚠ {selected.error} (any previously validated observations are retained)''')
s=s.replace('''  barClass,
}: {
  label: string;''','''  barClass,
  title,
}: {
  label: string;''')
s=s.replace('''  barClass: string;
}) {''','''  barClass: string;
  title?: string;
}) {''')
s=s.replace('''<div className="flex-1 basis-0 min-w-[92px] text-center px-1.5 sm:px-3">''','''<div className="flex-1 basis-0 min-w-[92px] text-center px-1.5 sm:px-3" title={title}>''')
s=s.replace('''function SortTh({
  label,
  k,''','''function SortTh({
  label,
  help,
  k,''')
s=s.replace('''  label: string;
  k: FleetSortKey;''','''  label: string;
  help?: string;
  k: FleetSortKey;''')
s=s.replace('''title={`Sort by ${label}`}''','''title={`Sort by ${label}${help ? ` — ${help}` : ""}`}''')
s=s.replace('''<div className="flex items-start justify-between gap-3">''','''<div className="flex items-start justify-between gap-3" data-detail-label={label}>''')
p.write_text(s)
