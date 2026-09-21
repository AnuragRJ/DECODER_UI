from pathlib import Path
root=Path('/home/user/ARPY-decoder-Ui/incois-arpy-decoder/decoder-ui/frontend/src')
p=root/'types/index.ts';s=p.read_text();a=s.index('export type FleetCommStatus');b=s.index('export interface FleetSyncState',a)
s=s[:a]+'''export type FleetDataStatus =
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
  profile_checked_at: string | null;
  expected_next_profile_iso: string | null;
  days_since_last_profile: number | null;
  /** Approximation from elapsed time, never the published-file gap count. */
  approx_profiles_missed: number | null;
  data_status: FleetDataStatus;
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

'''+s[b:]
a=s.index('export interface FleetStatusSummary');b=s.index('export interface FleetStatusPayload',a)
s=s[:a]+'''export interface FleetStatusSummary {
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
  interval_s: number;
}

'''+s[b:];p.write_text(s)

p=root/'utils/fleetStatus.ts';s=p.read_text()
s=s.replace('FleetCommStatus','FleetDataStatus').replace('all communication truth comes from the backend payload','all profile/data-recency values come from the backend payload')
s=s.replace('"last_tx"','"last_profile"').replace('"missing"','"missed"')
s=s.replace('worst communication state','least recent profile state')
s=s.replace('"NO COMMUNICATION 60+ DAYS"','"NO RECENT PROFILE DATA 60+ DAYS"')
s=s.replace('  OVERDUE:', '  "PROFILE OVERDUE":').replace('  ACTIVE:', '  "ACTIVE / RECENT PROFILE":')
s=s.replace('a.status','a.data_status').replace('b.status','b.data_status').replace('r.status','r.data_status')
s=s.replace('days_since_last_tx','days_since_last_profile').replace('last_tx_iso','last_profile_iso').replace('r.profiles_missing','r.approx_profiles_missed')
s=s.replace('Never changes comm status','Never changes data status')
s += '''
/** Monitoring estimate, deliberately not a published-file inventory label. */
export const APPROX_PROFILES_MISSED_NOTE =
  "Approximate estimate based on the expected 10-day profile cycle.";
'''
p.write_text(s)

p=root/'components/FloatStatusPage.tsx';s=p.read_text()
s=s.replace('FleetCommStatus','FleetDataStatus')
s=s.replace('''  FLEET_STATUS_META,
''','''  FLEET_STATUS_META,
  APPROX_PROFILES_MISSED_NOTE,
''')
a=s.index('/**\n * FloatStatusPage');b=s.index('const PAGE_SIZE',a)
s=s[:a]+'''/** Float Status monitors published profile/data recency from <WMO>_prof.nc.
 * All monitoring formulas are backend-derived from max valid profile JULD.
 * The existing upstream position selector, map renderer and navigation remain
 * separate from those formulas; no local decoder dates or positions are used.
 */

'''+s[b:]
s=s.replace('"NO COMMUNICATION 60+ DAYS"','"NO RECENT PROFILE DATA 60+ DAYS"').replace('"ACTIVE"','"ACTIVE / RECENT PROFILE"').replace('"OVERDUE"','"PROFILE OVERDUE"')
s=s.replace('status: r.status','status: r.data_status').replace('r.status','r.data_status').replace('selected.status','selected.data_status')
s=s.replace('Upstream Communication Monitor','Published Profile Monitor')
s=s.replace('dac/incois/<wmo>/<wmo>_Rtraj.nc','dac/incois/<wmo>/<wmo>_prof.nc')
s=s.replace('source?.field || "JULD_LAST_MESSAGE"','source?.field || "JULD (maximum valid N_PROF value)"')
s=s.replace('A new API response is not a new float transmission.','These values describe published profile recency, not telecom activity.')
s=s.replace('''label="ACTIVE / RECENT PROFILE" value={String(summary?.active''','''label="RECENT PROFILE" value={String(summary?.recent_profile''')
s=s.replace('summary?.overdue','summary?.profile_overdue').replace('summary?.no_comm_60','summary?.no_recent_profile_60')
s=s.replace('label="NO COMM 60+ DAYS"','label="NO RECENT 60+ DAYS"')
s=s.replace('''<CommMetric label="PROFILES MISSING" value={String(summary?.profiles_missing_total ?? "—")} valueClass="text-[#276095]" barClass="bg-[#276095]/60" title={`File-cycle gaps in 1..Prof#, not communication gaps. Listings available for ${summary?.profile_records_known ?? 0}/${summary?.total ?? 0} floats.`} />''','''<CommMetric label="APPROX. PROFILES MISSED" value={String(summary?.approx_profiles_missed_total ?? "—")} valueClass="text-[#276095]" barClass="bg-[#276095]/60" title={`${APPROX_PROFILES_MISSED_NOTE} Sum of known estimates (${summary?.profile_dates_known ?? 0}/${summary?.total ?? 0} floats); not an exact file inventory.`} />''')
s=s.replace('CommMetric','ProfileMetric').replace('CommDivider','ProfileDivider')
s=s.replace('Filter by communication status','Filter by data status').replace('All statuses','All data statuses')
s=s.replace('''<th className="py-2.5 px-2 text-right font-bold">Longitude</th>''','''<th className="py-2.5 px-2 text-right font-bold">Lon (E)</th>''')
s=s.replace('''<th className="py-2.5 px-2 text-right font-bold">Latitude</th>''','''<th className="py-2.5 px-2 text-right font-bold">Lat (N)</th>''')
s=s.replace('''<SortTh label="Last Transmission" k="last_tx"''','''<SortTh label="Last Profile Date" k="last_profile"''')
s=s.replace('''<SortTh label="No Communication" help="Completed days since the verified upstream transmission"''','''<SortTh label="Days Since Last Profile" help="Completed UTC days since the newest valid JULD in the published profile history"''')
s=s.replace('''<SortTh label="# Profs Missing" help="Missing file cycles in 1..Prof# across upstream R/D/B/S families, not missed transmissions" k="missing"''','''<SortTh label="Approx. Profiles Missed" help={APPROX_PROFILES_MISSED_NOTE} k="missed"''')
s=s.replace('''<th className="py-2.5 px-2 font-bold">Status</th>''','''<th className="py-2.5 px-2 font-bold">Data Status</th>''')
s=s.replace('last_tx_iso','last_profile_iso').replace('last_tx_field','last_profile_field')
s=s.replace('expected_next_iso','expected_next_profile_iso').replace('days_since_last_tx','days_since_last_profile')
s=s.replace('communication_error','profile_date_error').replace('No upstream timestamp','No valid published profile JULD')
s=s.replace('''`Field ${r.last_profile_field} · expected next ${formatUTC(r.expected_next_profile_iso)}`''','''`${r.last_profile_file} · ${r.last_profile_field} · Expected Next Profile ${formatUTC(r.expected_next_profile_iso)}`''')
a=s.index('''                              {r.traj_lagging_profiles && (''');b=s.index('''                            </>''',a)
s=s[:a]+s[b:]
s=s.replace('''data-field="profiles_missing"''','''data-field="approx_profiles_missed"''')
a=s.index('''                          title={
                            r.profiles_missing_list.length''');b=s.index('''                        >''',a)
s=s[:a]+'''                          title={APPROX_PROFILES_MISSED_NOTE}
'''+s[b:]
s=s.replace('r.profiles_missing','r.approx_profiles_missed')
s=s.replace('data-field="status"','data-field="data_status"')
s=s.replace('''              <DetailSection title="Identity">
                <DetailRow label="Internal ID (local)"''','''              <DetailSection title="Identity">
                <DetailRow label="WMO" value={String(selected.wmo)} />
                <DetailRow label="Float Type" value={selected.float_type} />
                <DetailRow label="Internal ID"''')
a=s.index('''              <DetailSection title="Communication (Ifremer GDAC)">''');b=s.index('''              <DetailSection title="Position (upstream)">''',a)
s=s[:a]+'''              <DetailSection title="Profile / data recency">
                <DetailRow label="Product" value={`dac/${source?.dac || "incois"}/${selected.wmo}/${selected.last_profile_file}`} />
                <DetailRow label="Last Profile Date" value={formatUTC(selected.last_profile_iso)} strong />
                <DetailRow label="Timestamp field" value="JULD — newest valid published profile" />
                <DetailRow label="Expected Next Profile" value={formatUTC(selected.expected_next_profile_iso)} />
                <DetailRow label="Days Since Last Profile" value={selected.days_since_last_profile !== null ? `${selected.days_since_last_profile.toFixed(3)} days` : "—"} />
                <DetailRow label="Approx. Profiles Missed" value={selected.approx_profiles_missed !== null ? String(selected.approx_profiles_missed) : "—"} />
                <p className="text-slate-500 text-[11px]" title={APPROX_PROFILES_MISSED_NOTE}>{APPROX_PROFILES_MISSED_NOTE} Not an exact missing-file inventory.</p>
                <DetailRow label="Data Status" value={selected.data_status} strong />
                {selected.profile_date_error && <p className="text-amber-800 text-[11.5px]">{selected.profile_date_error}</p>}
                {selected.last_profile_index != null && <DetailRow label="Profile array index" value={`${selected.last_profile_index} (0-based N_PROF)`} />}
              </DetailSection>
'''+s[b:]
s=s.replace('''                <DetailRow
                  label="Lon / Lat"
                  value={
                    selected.lon !== null && selected.lat !== null
                      ? `${formatCoord(selected.lon, "lon")} / ${formatCoord(selected.lat, "lat")}`
                      : "— (no usable upstream position)"
                  }
                />''','''                <DetailRow label="Latitude" value={formatCoord(selected.lat, "lat")} />
                <DetailRow label="Longitude" value={formatCoord(selected.lon, "lon")} />''')
a=s.index('''              <DetailSection title="Profiles (upstream)">''');b=s.index('''              {selected.traj_last_fix && (''',a)
s=s[:a]+'''              <DetailSection title="Published profile inventory">
                <DetailRow label="Prof#" value={selected.prof_num !== null ? String(selected.prof_num) : "—"} />
                <p className="text-slate-500 text-[11px]">Prof# is the highest published cycle, not the number of available profiles or the approximate missed-profile estimate.</p>
                <DetailRow label="Available profile cycles" value={selected.profile_count !== null ? String(selected.profile_count) : "—"} />
                {selected.latest_profile && <DetailRow label="Highest-cycle profile file" value={selected.latest_profile.file || "—"} />}
              </DetailSection>
'''+s[b:]
s=s.replace('''              <DetailSection title="Sync">
''','''              <DetailSection title="Sync">
                <DetailRow label="Profile history checked" value={formatUTC(selected.profile_checked_at)} />
''')
p.write_text(s)
