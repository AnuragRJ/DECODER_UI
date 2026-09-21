import React, { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Satellite,
  Search,
  X,
} from "lucide-react";
import { useDecoderStore } from "../store/useDecoderStore";
import {
  startFleetStatusPolling,
  stopFleetStatusPolling,
  useFleetStatusStore,
} from "../store/useFleetStatusStore";
import type { FleetDataStatus, FleetPrediction, FleetStatusRow } from "../types";
import FleetOceanMap, { FleetMapFloat, FleetMapPrediction } from "./FleetOceanMap";
import {
  FLEET_STATUS_META,
  APPROX_PROFILES_MISSED_NOTE,
  FleetSortKey,
  SortDir,
  applyFleetFilters,
  approxMissedNote,
  defaultSortRows,
  formatCoord,
  formatDays,
  formatForwardTest,
  formatInterval,
  formatPredictionHorizon,
  formatPredictionRadius,
  formatUTC,
  formatSyncInterval,
  predictionStatusLabel,
  fleetCacheIsStale,
  hasFleetPosition,
  paginateRows,
  sortFleetRows,
} from "../utils/fleetStatus";

/** Float Status monitors published profile/data recency from <WMO>_prof.nc.
 * All monitoring formulas are backend-derived from max valid profile JULD.
 * The existing upstream position selector, map renderer and navigation remain
 * separate from those formulas; no local decoder dates or positions are used.
 */

const PAGE_SIZE = 20;

const STATUS_OPTIONS: Array<"" | FleetDataStatus> = [
  "",
  "ACTIVE / RECENT PROFILE",
  "PROFILE OVERDUE",
  "NO RECENT PROFILE DATA 60+ DAYS",
  "NO DATA",
];

export const FloatStatusPage: React.FC = () => {
  const { setActiveView } = useDecoderStore();
  const {
    payload,
    loading,
    fetchError,
    syncStarting,
    fetchFleetStatus,
    triggerSync,
  } = useFleetStatusStore();

  const [query, setQuery] = useState("");
  const [floatType, setFloatType] = useState("");
  const [statusFilter, setStatusFilter] = useState<"" | FleetDataStatus>("");
  const [sortKey, setSortKey] = useState<FleetSortKey | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [page, setPage] = useState(1);
  const [selectedWmo, setSelectedWmo] = useState<number | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    void fetchFleetStatus();
    startFleetStatusPolling();
    return () => stopFleetStatusPolling();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const rows = useMemo(() => payload?.floats || [], [payload]);
  const sync = payload?.sync || null;
  const summary = payload?.summary || null;
  const source = payload?.source || null;

  const floatTypes = useMemo(
    () => [...new Set(rows.map((r) => r.float_type))].sort(),
    [rows]
  );

  const filtered = useMemo(() => {
    const f = applyFleetFilters(rows, { query, floatType, status: statusFilter });
    return sortKey ? sortFleetRows(f, sortKey, sortDir) : defaultSortRows(f);
  }, [rows, query, floatType, statusFilter, sortKey, sortDir]);

  useEffect(() => {
    setPage(1);
  }, [query, floatType, statusFilter, sortKey, sortDir]);

  const { pageRows, totalPages, safePage } = useMemo(
    () => paginateRows(filtered, page, PAGE_SIZE),
    [filtered, page]
  );

  const mapFloats: FleetMapFloat[] = useMemo(
    () =>
      filtered
        .filter(hasFleetPosition)
        .map((r) => ({
          wmo: r.wmo,
          platform: r.float_type,
          status: r.data_status,
          lat: r.lat as number,
          lon: r.lon as number,
          cyclesCount: r.profile_count ?? 0,
        })),
    [filtered]
  );
  const unplotted = filtered.length - mapFloats.length;

  /** Experimental prediction layer (optional, OFF by default). Only floats
   *  whose prediction is available AND has a validated radius are plotted —
   *  an unavailable prediction never becomes a marker. */
  const mapPredictions: FleetMapPrediction[] = useMemo(
    () =>
      filtered
        .map((r) => ({ row: r, p: (r.prediction || null) as FleetPrediction | null }))
        .filter(
          (item): item is { row: FleetStatusRow; p: FleetPrediction } =>
            !!item.p &&
            item.p.available &&
            item.p.predicted_lat != null &&
            item.p.predicted_lon != null &&
            item.p.r90_km != null
        )
        .map(({ row, p }) => ({
          wmo: row.wmo,
          lat: p.predicted_lat as number,
          lon: p.predicted_lon as number,
          fromLat: row.lat,
          fromLon: row.lon,
          r50Km: p.r50_km,
          r90Km: p.r90_km,
          methodLabel: p.method_label,
          targetTimeIso: p.target_time_iso,
        })),
    [filtered]
  );

  const selected: FleetStatusRow | null = useMemo(
    () => rows.find((r) => r.wmo === selectedWmo) || null,
    [rows, selectedWmo]
  );

  const handleSort = (key: FleetSortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "wmo" ? "asc" : "desc");
    }
  };

  const handleSelect = (wmo: number) => {
    setSelectedWmo(wmo);
    setDrawerOpen(true);
  };

  const handleClear = () => {
    setQuery("");
    setFloatType("");
    setStatusFilter("");
    setSortKey(null);
    setSortDir("desc");
    setPage(1);
  };

  const syncState = sync?.status || "never-synced";
  const syncing = sync?.running || false;
  const stale = Boolean(fetchError) || fleetCacheIsStale(payload);
  const progress = sync?.progress || { done: 0, total: 0 };

  return (
    <div
      className="relative h-screen w-screen flex flex-col bg-[#F4F7F9] text-slate-800 overflow-hidden font-sans select-none"
      data-testid="float-status-page"
    >
      {/* ===================== Header ===================== */}
      <header className="h-16 bg-[#163857] text-white border-b border-[#0f2439] px-4 flex items-center justify-between shrink-0 shadow-md">
        <div className="flex items-center space-x-4 min-w-0">
          <button
            onClick={() => setActiveView("results")}
            className="px-3.5 py-2 bg-white/10 hover:bg-white/20 text-white border border-white/20 rounded font-mono text-[13px] font-bold transition flex items-center space-x-2 cursor-pointer shadow-2xs shrink-0"
            title="Return to Decoder Results"
          >
            <ArrowLeft className="w-4 h-4 text-sky-300" />
            <span>[ Back to Results ]</span>
          </button>
          <div className="h-7 w-px bg-white/15 hidden sm:block shrink-0" />
          <div className="min-w-0">
            <div className="flex items-center space-x-2">
              <Satellite className="w-5 h-5 text-sky-300 shrink-0" />
              <h1 className="font-mono text-base sm:text-lg font-extrabold tracking-wider uppercase text-white truncate">
                Float Status
              </h1>
              <span className="px-2 py-0.5 bg-sky-500/20 text-sky-200 border border-sky-400/30 rounded font-mono text-[11px] font-bold uppercase whitespace-nowrap hidden md:inline">
                Published Profile Monitor
              </span>
            </div>
            <p className="text-[13px] font-mono text-sky-200/90 mt-0.5 truncate">
              {source
                ? `Ifremer GDAC · dac/${source.dac} · ${rows.length} Floats`
                : "Ifremer GDAC · dac/incois"}
            </p>
          </div>
        </div>

        <div className="flex items-center space-x-2.5 font-mono text-xs shrink-0">
          <div
            className="flex items-center space-x-1.5 px-3 py-1.5 bg-white/10 border border-white/20 rounded font-mono text-[12px]"
            title={
              fetchError || sync?.stale_reason || sync?.error ||
              (sync?.last_success_at
                ? `Last successful sync ${formatUTC(sync.last_success_at)}`
                : "No successful sync yet")
            }
            data-testid="fleet-sync-pill"
          >
            {syncing ? (
              <>
                <RefreshCw className="w-3.5 h-3.5 text-amber-300 shrink-0 animate-spin" />
                <span className="text-amber-200 font-bold">
                  Syncing {progress.total > 0 ? `${progress.done}/${progress.total}` : "…"}
                </span>
              </>
            ) : stale ? (
              <>
                <AlertTriangle className="w-3.5 h-3.5 text-amber-300 shrink-0" />
                <span className="text-amber-200 font-bold">Stale cache{syncState === "disabled" ? " · sync disabled" : ""}</span>
              </>
            ) : syncState === "ok" ? (
              <>
                <span className="w-2 h-2 rounded-full bg-emerald-400 shrink-0" />
                <span className="text-emerald-300 font-bold">
                  Synced{sync?.last_success_at ? ` ${formatUTC(sync.last_success_at)}` : ""}
                </span>
              </>
            ) : syncState === "disabled" ? (
              <span className="text-slate-300 font-bold">Sync disabled</span>
            ) : (
              <span className="text-slate-300">
                {loading ? "Loading…" : "No sync yet"}
              </span>
            )}
          </div>
          <button
            onClick={() => void triggerSync()}
            disabled={syncing || syncStarting || syncState === "disabled"}
            className="px-3.5 py-2 bg-white/10 hover:bg-white/20 disabled:opacity-40 text-white border border-white/20 rounded font-bold text-[13px] transition flex items-center space-x-1.5 shadow-2xs cursor-pointer disabled:cursor-not-allowed"
            title="Start one Ifremer GDAC sync cycle now (background)"
          >
            <RefreshCw
              className={`w-3.5 h-3.5 ${syncing || syncStarting ? "animate-spin" : ""}`}
            />
            <span>[ Sync now ]</span>
          </button>
        </div>
      </header>

      {/* Sync/source strip */}
      <div className="px-4 py-1.5 bg-white border-b border-slate-200 font-mono text-[11.5px] text-slate-500 flex flex-wrap items-center gap-x-4 gap-y-0.5 shrink-0 select-text">
        <span className="truncate" title="Exact upstream product and field">
          src: ftp://{source?.host || "ftp.ifremer.fr"}:{source?.port || 21}
          {source?.root || "/ifremer/argo"}/{source?.product || "dac/incois/<wmo>/<wmo>_prof.nc"}
          {" "}· field {source?.field || "JULD (maximum valid N_PROF value)"}
        </span>
        <span className="whitespace-nowrap">
          last full sync: {sync?.last_success_at ? formatUTC(sync.last_success_at) : "—"}
        </span>
        <span className="whitespace-nowrap">
          interval: {formatSyncInterval(sync?.interval_s ?? null)}
        </span>
        {sync?.error && (
          <span className="text-amber-700 truncate" title={sync.error}>
            ⚠ {sync.error}
          </span>
        )}
        {fetchError && (
          <span className="text-rose-700 truncate" title={fetchError}>
            ⚠ backend request failed: {fetchError}
          </span>
        )}
      </div>

      {(stale || syncing) && payload && (
        <div data-testid="fleet-freshness-notice" className="px-4 py-1.5 bg-amber-50 border-b border-amber-200 text-amber-900 font-mono text-[11.5px] shrink-0">
          {stale ? "Cached observations — current upstream state is not fully verified. " : "Checking upstream; showing the last verified snapshot. "}
          {fetchError || sync?.stale_reason || ""}
          {" "}Status evaluated at {formatUTC(payload.generated_at)}. These values describe published profile recency, not telecom activity.
        </div>
      )}

      {/* ===================== Summary metrics ===================== */}
      <section
        className="bg-[#f5f8fb] border-b border-slate-200 px-4 sm:px-8 lg:px-10 py-4 shrink-0"
        data-testid="fleet-status-metrics"
      >
        <div className="flex items-stretch w-full font-mono overflow-x-auto">
          <ProfileMetric label="TOTAL FLOATS" value={String(summary?.total ?? "—")} valueClass="text-[#163857]" barClass="bg-[#163857]/60" />
          <ProfileDivider />
          <ProfileMetric label="RECENT PROFILE" value={String(summary?.recent_profile ?? "—")} valueClass="text-emerald-600" barClass="bg-emerald-500/60" />
          <ProfileDivider />
          <ProfileMetric label="PROFILE OVERDUE" value={String(summary?.profile_overdue ?? "—")} valueClass="text-amber-600" barClass="bg-amber-500/60" />
          <ProfileDivider />
          <ProfileMetric label="NO RECENT 60+ DAYS" value={String(summary?.no_recent_profile_60 ?? "—")} valueClass="text-rose-600" barClass="bg-rose-500/60" />
          <ProfileDivider />
          <ProfileMetric label="NO DATA" value={String(summary?.no_data ?? "—")} valueClass="text-slate-500" barClass="bg-slate-400/60" />
          <ProfileDivider />
          <ProfileMetric label="APPROX. PROFILES MISSED" value={String(summary?.approx_profiles_missed_total ?? "—")} valueClass="text-[#276095]" barClass="bg-[#276095]/60" title={`${APPROX_PROFILES_MISSED_NOTE} Sum of known estimates (${summary?.profile_dates_known ?? 0}/${summary?.total ?? 0} floats); not an exact file inventory.`} />
          <ProfileDivider />
          <ProfileMetric label="PROFILE CYCLES" value={String(summary?.total_profiles ?? "—")} valueClass="text-[#1d547d]" barClass="bg-[#1d547d]/60" title={`Available unique positive cycles, not the sum of Prof# or BGC sensor grids. Listings available for ${summary?.profile_records_known ?? 0}/${summary?.total ?? 0} floats.`} />
        </div>
      </section>

      {/* ===================== Toolbar ===================== */}
      <div className="px-3 py-2 bg-slate-50 border-b border-slate-200 flex flex-wrap items-center gap-2 shrink-0 font-mono text-[13px]">
        <div className="relative w-60">
          <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-2.5" />
          <input
            type="text"
            placeholder="Search WMO / internal ID…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="w-full pl-8 pr-2.5 py-1.5 bg-white border border-slate-300 rounded text-[13px] font-mono text-slate-900 focus:outline-none focus:ring-1 focus:ring-[#276095]"
          />
        </div>
        <select
          value={floatType}
          onChange={(e) => setFloatType(e.target.value)}
          className="px-2.5 py-1.5 bg-white border border-slate-300 rounded text-[12.5px] font-mono text-slate-700 focus:outline-none focus:ring-1 focus:ring-[#276095] cursor-pointer"
          title="Filter by float type"
        >
          <option value="">All float types</option>
          {floatTypes.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as "" | FleetDataStatus)}
          className="px-2.5 py-1.5 bg-white border border-slate-300 rounded text-[12.5px] font-mono text-slate-700 focus:outline-none focus:ring-1 focus:ring-[#276095] cursor-pointer"
          title="Filter by data status"
        >
          {STATUS_OPTIONS.map((s) => (
            <option key={s || "all"} value={s}>
              {s === "" ? "All data statuses" : s}
            </option>
          ))}
        </select>
        {(query || floatType || statusFilter || sortKey) && (
          <button
            onClick={handleClear}
            className="px-2.5 py-1.5 bg-white hover:bg-slate-100 text-slate-600 border border-slate-300 rounded text-[12px] font-bold transition flex items-center space-x-1 cursor-pointer"
            title="Clear search, filters and sorting"
          >
            <X className="w-3.5 h-3.5" />
            <span>Clear</span>
          </button>
        )}
        <span className="ml-auto text-[12px] text-slate-500">
          {filtered.length} of {rows.length} floats
          {sortKey ? ` · sorted by ${sortKey} ${sortDir}` : ""}
        </span>
      </div>

      {/* ===================== Map + table ===================== */}
      <div className="flex-1 flex flex-col lg:flex-row overflow-hidden min-h-0">
        <div className="flex flex-col lg:w-[42%] lg:border-r border-b lg:border-b-0 border-slate-200 bg-white overflow-hidden shrink-0 min-h-[220px]">
          <div className="flex-1 min-h-0 flex flex-col relative">
            <FleetOceanMap
              positions={mapFloats}
              predictions={mapPredictions}
              trajectory={[]}
              selectedWmo={selectedWmo}
              onSelect={handleSelect}
              dataKey={sync?.last_success_at || "fleet-status"}
              title="Fleet positions — latest upstream GDAC fixes"
              subtitleNoun="with upstream positions"
              footerNote="newest verified QC 1/2 upstream position · source/time in detail"
            />
          </div>
          <div className="px-3 py-1 bg-slate-50 border-t border-slate-200 font-mono text-[11px] text-slate-500 shrink-0">
            Plotting {mapFloats.length} of {filtered.length} floats
            {unplotted > 0 ? ` · ${unplotted} without upstream position` : ""}
          </div>
        </div>

        <div className="flex-1 flex flex-col bg-white overflow-hidden min-w-0 min-h-0">
          <div className="flex-1 overflow-auto p-2.5 select-text font-mono text-[13px]">
            {pageRows.length === 0 ? (
              <div className="p-8 text-center text-slate-400 space-y-2">
                <Satellite className="w-7 h-7 mx-auto text-slate-300" />
                <p>
                  {rows.length === 0
                    ? syncing || loading
                      ? "First Ifremer sync in progress — rows appear as floats refresh…"
                      : "No fleet data yet"
                    : "No float records match current filters"}
                </p>
              </div>
            ) : (
              <table className="w-full text-left border border-slate-200 rounded min-w-[880px]">
                <thead className="bg-slate-100 text-slate-600 font-bold text-[12px] uppercase tracking-wider border-b border-slate-200 sticky top-0">
                  <tr>
                    <SortTh label="WMO ID" k="wmo" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} className="py-2.5 px-2.5" />
                    <th className="py-2.5 px-2 font-bold">Internal ID</th>
                    <SortTh label="Prof#" help="Highest upstream published cycle, not available profile count" k="prof" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} className="py-2.5 px-2 text-center" center />
                    <th className="py-2.5 px-2 text-right font-bold">Lon (E)</th>
                    <th className="py-2.5 px-2 text-right font-bold">Lat (N)</th>
                    <SortTh label="Last Profile Date" k="last_profile" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} className="py-2.5 px-2" />
                    <SortTh label="Days Since Last Profile" help="Completed UTC days since the newest valid JULD in the published profile history" k="days" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} className="py-2.5 px-2 text-right" center={false} right />
                    <SortTh label="Approx. Profiles Missed" help={APPROX_PROFILES_MISSED_NOTE} k="missed" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} className="py-2.5 px-2 text-center" center />
                    <th className="py-2.5 px-2 font-bold">Float Type</th>
                    <th className="py-2.5 px-2 font-bold">Data Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {pageRows.map((r) => {
                    const isSelected = r.wmo === selectedWmo;
                    const meta = FLEET_STATUS_META[r.data_status];
                    return (
                      <tr
                        key={r.wmo}
                        onClick={() => handleSelect(r.wmo)}
                        data-testid={`fleet-row-${r.wmo}`}
                        className={`cursor-pointer transition-colors ${
                          isSelected
                            ? "bg-amber-50/90 border-l-4 border-l-amber-500"
                            : "hover:bg-slate-50"
                        }`}
                      >
                        <td className="py-2.5 px-2.5 font-bold text-[#276095] tabular-nums" data-field="wmo">
                          {r.wmo}
                          {r.stale && <span data-testid={`fleet-stale-${r.wmo}`} title={r.stale_reason || "Cached observation needs re-verification"} className="block text-[9px] text-amber-700">STALE CACHE</span>}
                        </td>
                        <td className="py-2.5 px-2 text-slate-600 text-[12.5px] tabular-nums" data-field="internal_id">
                          {r.internal_id || <span className="text-slate-300">—</span>}
                        </td>
                        <td className="py-2.5 px-2 text-center text-slate-700 font-semibold tabular-nums" data-field="prof_num" title="Highest published cycle; see detail for available count">
                          {r.prof_num ?? <span className="text-slate-300">—</span>}
                        </td>
                        <td className="py-2.5 px-2 text-right text-slate-700 tabular-nums whitespace-nowrap" data-field="lon" title={`${r.position_file || "No verified position"} · ${formatUTC(r.position_iso || null)}`}>
                          {r.lon !== null ? formatCoord(r.lon, "lon") : <span className="text-slate-300">—</span>}
                        </td>
                        <td className="py-2.5 px-2 text-right text-slate-700 tabular-nums whitespace-nowrap" data-field="lat" title={`${r.position_file || "No verified position"} · ${formatUTC(r.position_iso || null)}`}>
                          {r.lat !== null ? formatCoord(r.lat, "lat") : <span className="text-slate-300">—</span>}
                        </td>
                        <td
                          className="py-2.5 px-2 text-slate-700 text-[12.5px] whitespace-nowrap tabular-nums"
                          data-field="last_profile_iso"
                          title={
                            r.last_profile_iso
                              ? `${r.last_profile_file} · ${r.last_profile_field} · Expected Next Profile ${formatUTC(r.expected_next_profile_iso)}`
                              : r.profile_date_error || r.error || "No valid published profile JULD"
                          }
                        >
                          {r.last_profile_iso ? (
                            <>
                              {formatUTC(r.last_profile_iso)}
                            </>
                          ) : (
                            <span className="text-slate-300">—</span>
                          )}
                        </td>
                        <td className="py-2.5 px-2 text-right font-bold tabular-nums whitespace-nowrap" data-field="days_since_last_profile" title={`Elapsed days; evaluated at ${formatUTC(payload?.generated_at || null)}`}>
                          {r.days_since_last_profile !== null ? (
                            <span className={r.data_status === "ACTIVE / RECENT PROFILE" ? "text-emerald-700" : r.data_status === "PROFILE OVERDUE" ? "text-amber-700" : "text-rose-700"}>
                              {formatDays(r.days_since_last_profile)}
                            </span>
                          ) : (
                            <span className="text-slate-300 font-medium">—</span>
                          )}
                        </td>
                        <td
                          className="py-2.5 px-2 text-center font-bold tabular-nums"
                          title={approxMissedNote(r)}
                          data-field="approx_profiles_missed"
                        >
                          {r.approx_profiles_missed !== null ? (
                            <span className={r.approx_profiles_missed > 0 ? "text-amber-700" : "text-slate-500"}>
                              {r.approx_profiles_missed}
                            </span>
                          ) : (
                            <span className="text-slate-300 font-medium">—</span>
                          )}
                        </td>
                        <td className="py-2.5 px-2 text-slate-600 text-[12.5px]" data-field="float_type">{r.float_type}</td>
                        <td className="py-2 px-2" data-field="data_status">
                          <span
                            className={`px-2 py-1 border rounded text-[11px] font-bold whitespace-nowrap ${meta.pill}`}
                            title={r.profile_date_error || r.error || undefined}
                          >
                            {r.data_status}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
          <div className="p-2 bg-slate-50 border-t border-slate-200 flex items-center justify-between font-mono text-[12px] text-slate-500 shrink-0">
            <span>
              Showing {pageRows.length === 0 ? 0 : (safePage - 1) * PAGE_SIZE + 1}–
              {(safePage - 1) * PAGE_SIZE + pageRows.length} of {filtered.length}
            </span>
            <span className="flex items-center space-x-1.5">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={safePage <= 1}
                className="p-1.5 bg-white border border-slate-300 rounded disabled:opacity-40 hover:bg-slate-100 cursor-pointer disabled:cursor-not-allowed"
                title="Previous page"
              >
                <ChevronLeft className="w-3.5 h-3.5" />
              </button>
              <span className="tabular-nums">
                Page {safePage} of {totalPages}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={safePage >= totalPages}
                className="p-1.5 bg-white border border-slate-300 rounded disabled:opacity-40 hover:bg-slate-100 cursor-pointer disabled:cursor-not-allowed"
                title="Next page"
              >
                <ChevronRight className="w-3.5 h-3.5" />
              </button>
            </span>
          </div>
        </div>
      </div>

      {/* ===================== Detail drawer ===================== */}
      {drawerOpen && selected && (
        <>
          <div
            className="fixed inset-0 z-40 bg-slate-950/40"
            onClick={() => setDrawerOpen(false)}
          />
          <aside data-testid="fleet-detail" className="fixed top-0 right-0 h-full w-full max-w-md bg-white shadow-2xl border-l border-slate-200 z-50 flex flex-col font-mono animate-in slide-in-from-right duration-150">
            <div className="h-16 bg-[#163857] text-white px-4 flex items-center justify-between shrink-0">
              <div className="min-w-0">
                <div className="flex items-center space-x-2">
                  <span className="text-lg font-black">WMO {selected.wmo}</span>
                  <span
                    className={`px-2 py-0.5 border rounded text-[11px] font-bold whitespace-nowrap ${FLEET_STATUS_META[selected.data_status].pill}`}
                  >
                    {selected.data_status}
                  </span>
                </div>
                <p className="text-[12px] text-sky-200/90 mt-0.5">
                  {selected.float_type} · {selected.transmission_type}
                </p>
              </div>
              <button
                onClick={() => setDrawerOpen(false)}
                className="p-2 bg-white/10 hover:bg-white/20 rounded border border-white/20 cursor-pointer"
                title="Close detail"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-4 space-y-3 text-[12.5px] select-text">
              <DetailSection title="Identity" testId="detail-section-identity">
                <DetailRow label="WMO" value={String(selected.wmo)} />
                <DetailRow label="Float Type" value={selected.float_type} />
                <DetailRow label="Internal ID" value={selected.internal_id || "— (unavailable / sanitized)"} />
                {selected.ptt && <DetailRow label="PTT" value={selected.ptt} />}
                {selected.imei && <DetailRow label="IMEI" value={selected.imei} />}
                <DetailRow
                  label="INCOIS upstream record"
                  value={
                    selected.in_incois_dac === true
                      ? "yes — dac/incois"
                      : selected.in_incois_dac === false
                      ? "no — absent from dac/incois"
                      : "—"
                  }
                />
              </DetailSection>
              <DetailSection title="Profile / data recency" testId="detail-section-recency">
                <DetailRow label="Product" value={`dac/${source?.dac || "incois"}/${selected.wmo}/${selected.last_profile_file}`} />
                <DetailRow label="Last Profile Date" value={formatUTC(selected.last_profile_iso)} strong />
                <DetailRow label="Timestamp field" value="JULD — newest valid published profile" />
                <DetailRow label="Expected Next Profile" value={formatUTC(selected.expected_next_profile_iso)} />
                <DetailRow label="Observed cycle interval" value={formatInterval(selected)} />
                <DetailRow label="Days Since Last Profile" value={selected.days_since_last_profile !== null ? `${selected.days_since_last_profile.toFixed(3)} days` : "—"} />
                <DetailRow label="Approx. Profiles Missed" value={selected.approx_profiles_missed !== null ? String(selected.approx_profiles_missed) : "—"} />
                <p className="text-slate-500 text-[11px]" title={approxMissedNote(selected)}>{approxMissedNote(selected)} Not an exact missing-file inventory.</p>
                <DetailRow label="Data Status" value={selected.data_status} strong />
                {selected.profile_date_error && <p className="text-amber-800 text-[11.5px]">{selected.profile_date_error}</p>}
                {selected.profile_history_lagging_latest_file && selected.latest_profile && (
                  <p data-testid="profile-history-lag" className="px-2.5 py-2 bg-amber-50 border border-amber-300 rounded text-amber-900 text-[11.5px]">
                    A newer individual profile exists (measurement date: {formatUTC(selected.latest_profile.juld_iso)}).
                    It is not yet represented in {selected.last_profile_file}. Data Status uses only that history product.
                  </p>
                )}
                {selected.last_profile_index != null && <DetailRow label="Profile array index" value={`${selected.last_profile_index} (0-based N_PROF)`} />}
              </DetailSection>
              <DetailSection title="Position (upstream)" testId="detail-section-position">
                <DetailRow label="Latitude" value={formatCoord(selected.lat, "lat")} />
                <DetailRow label="Longitude" value={formatCoord(selected.lon, "lon")} />
                {selected.pos_source && (
                  <DetailRow
                    label="Position source"
                    value={
                      selected.pos_source === "profile"
                        ? "upstream profile (newer valid position)"
                        : "trajectory latest valid fix"
                    }
                  />
                )}
                {selected.pos_qc && <DetailRow label="Position QC" value={selected.pos_qc} />}
                <DetailRow label="Position observed" value={formatUTC(selected.position_iso || null)} />
                <DetailRow label="Position time field" value={selected.position_time_field || "—"} />
                <DetailRow label="Position file" value={selected.position_file || "—"} />
                {selected.position_error && <p className="text-amber-800 text-[11.5px]">{selected.position_error}</p>}
              </DetailSection>
              <DetailSection title="Published profile inventory" testId="detail-section-inventory">
                <DetailRow label="Prof#" value={selected.prof_num !== null ? String(selected.prof_num) : "—"} />
                <p className="text-slate-500 text-[11px]">Prof# is the highest published cycle, not the number of available profiles or the approximate missed-profile estimate.</p>
                <DetailRow label="Available profile cycles" value={selected.profile_count !== null ? String(selected.profile_count) : "—"} />
                {selected.latest_profile && <DetailRow label="Highest-cycle profile file" value={selected.latest_profile.file || "—"} />}
              </DetailSection>
              {selected.traj_last_fix && (
                <DetailSection title="Trajectory last fix">
                  <DetailRow label="Fix time" value={formatUTC(selected.traj_last_fix.juld_iso)} />
                  <DetailRow
                    label="Lon / Lat"
                    value={`${formatCoord(selected.traj_last_fix.lon, "lon")} / ${formatCoord(selected.traj_last_fix.lat, "lat")}`}
                  />
                  {selected.traj_last_fix.cycle !== null && (
                    <DetailRow label="Cycle" value={String(selected.traj_last_fix.cycle)} />
                  )}
                </DetailSection>
              )}
              <DetailSection title="NEXT PROFILE LOCATION (PREDICTED)" testId="detail-section-prediction">
                <PredictionDetail row={selected} />
              </DetailSection>
              <DetailSection title="Sync" testId="detail-section-sync">
                <DetailRow label="Profile history checked" value={formatUTC(selected.profile_checked_at)} />
                <DetailRow label="Upstream checked" value={formatUTC(selected.checked_at || null)} />
                <DetailRow label="Row assembled" value={formatUTC(selected.updated_at)} />
                <DetailRow label="Cache freshness" value={selected.stale ? selected.stale_reason || "Stale" : "Verified within sync interval"} />
                {selected.rtraj_mdtm && <DetailRow label="Upstream Rtraj MDTM" value={selected.rtraj_mdtm} />}
                {selected.error && (
                  <div className="px-2.5 py-2 bg-rose-50 border border-rose-200 rounded text-rose-900 text-[12px] break-words">
                    ⚠ {selected.error} (any previously validated observations are retained)
                  </div>
                )}
              </DetailSection>
            </div>
          </aside>
        </>
      )}
    </div>
  );
};

/* ---------------------------------------------------------------------- */
/* Small presentational helpers (same visual language as Results)          */
/* ---------------------------------------------------------------------- */

function ProfileDivider() {
  return (
    <div
      className="w-px self-stretch my-1 bg-slate-200/90 hidden sm:block shrink-0"
      aria-hidden="true"
    />
  );
}

function ProfileMetric({
  label,
  value,
  valueClass,
  barClass,
  title,
}: {
  label: string;
  value: string;
  valueClass: string;
  barClass: string;
  title?: string;
}) {
  return (
    <div className="flex-1 basis-0 min-w-[92px] text-center px-1.5 sm:px-3" title={title}>
      <p
        className={`text-[26px] sm:text-[32px] md:text-[36px] leading-none font-black tabular-nums tracking-tight ${valueClass}`}
      >
        {value}
      </p>
      <p className="mt-2 text-[10px] sm:text-[11px] font-bold uppercase tracking-[0.12em] text-slate-500 leading-tight whitespace-nowrap">
        {label}
      </p>
      <span
        className={`mt-2 block mx-auto h-[3px] w-7 sm:w-9 rounded-full ${barClass}`}
        aria-hidden="true"
      />
    </div>
  );
}

function SortTh({
  label,
  help,
  k,
  sortKey,
  sortDir,
  onSort,
  className,
  center,
  right,
}: {
  label: string;
  help?: string;
  k: FleetSortKey;
  sortKey: FleetSortKey | null;
  sortDir: SortDir;
  onSort: (k: FleetSortKey) => void;
  className?: string;
  center?: boolean;
  right?: boolean;
}) {
  const active = sortKey === k;
  return (
    <th className={className || ""}>
      <button
        onClick={() => onSort(k)}
        title={`Sort by ${label}${help ? ` — ${help}` : ""}`}
        className={`font-bold uppercase tracking-wider hover:text-[#276095] cursor-pointer ${
          center ? "mx-auto" : right ? "ml-auto" : ""
        } flex items-center gap-1`}
      >
        <span>{label}</span>
        <span className={active ? "text-[#276095]" : "text-slate-300"}>
          {active ? (sortDir === "asc" ? "▲" : "▼") : "△"}
        </span>
      </button>
    </th>
  );
}

/** Experimental next-profile-location prediction.
 *
 *  Every number comes from the backend payload (derived from the cached
 *  Ifremer `_prof.nc` / `_Rtraj.nc` data). When data is insufficient the
 *  section says so — it never invents a position, and it never claims to be a
 *  communication signal. The profile-recency status above is independent of
 *  this section and is not modified by it.
 */
export function PredictionDetail({ row }: { row: FleetStatusRow }) {
  const p = row.prediction || null;
  if (!p) {
    return (
      <p className="text-slate-500 text-[11.5px]" data-testid="prediction-absent">
        Prediction unavailable — insufficient data (no prediction in this payload; refresh the
        upstream sync).
      </p>
    );
  }
  return (
    <div className="space-y-1.5" data-testid="prediction-section">
      <p
        data-testid="prediction-label"
        className="px-2.5 py-1.5 bg-sky-50 border border-sky-300 rounded text-sky-900 text-[11.5px] font-bold uppercase tracking-wider"
      >
        Experimental prediction — not a communication signal
      </p>
      {p.predictor_stage === "stage1" && (
        <p
          data-testid="prediction-stage-note"
          className="px-2.5 py-2 bg-amber-50 border border-amber-300 rounded text-amber-900 text-[11px]"
        >
          Stage-1 cycle-scale step in use for this prediction. It is under evaluation: Stage-0
          (last-hop step) remains the shipped baseline and its R50/R90 are not reused here.
        </p>
      )}
      {p.available ? (
        <>
          <DetailRow label="Predicted Latitude" value={formatCoord(p.predicted_lat, "lat")} strong />
          <DetailRow label="Predicted Longitude" value={formatCoord(p.predicted_lon, "lon")} strong />
          <DetailRow label="Expected Next Profile" value={formatUTC(p.target_time_iso)} />
          <DetailRow label="Prediction Horizon" value={formatPredictionHorizon(p.prediction_horizon_days)} />
          <DetailRow
            label="Prediction Method"
            value={p.method_label || "—"}
            strong
          />
          <DetailRow
            label="Predictor stage"
            value={
              p.predictor_stage_label ||
              "Stage-0 baseline (last-hop step) — no stage reported by this payload"
            }
            strong
          />
          {p.predictor_stage === "stage1" && (
            <DetailRow
              label="Cycle-scale step basis"
              value={
                `${p.step_basis || "—"}` +
                (p.step_cycles != null && p.step_cycles > 1
                  ? ` · gap normalised over ${p.step_cycles} cycles`
                  : "")
              }
            />
          )}
          <DetailRow
            label="Fallback rung"
            value={
              p.fallback_rung != null
                ? `${p.fallback_rung}${p.fallback_rung === 4 ? " — validated history/prior baseline" : ""}`
                : "—"
            }
          />
          <DetailRow
            label="Trajectory history available"
            value={
              (p.trajectory_transitions ?? 0) > 0
                ? `yes — ${p.trajectory_transitions} cycle hop(s) in the cached trajectory`
                : "no — no usable cycle hops in the cached trajectory"
            }
          />
          <DetailRow
            label="Trajectory transitions"
            value={p.trajectory_transitions != null ? String(p.trajectory_transitions) : "—"}
          />
          <DetailRow label="Validation Sample Count" value={String(p.validation_samples)} />
          <DetailRow
            label="R50 (empirical)"
            value={
              p.r50_km != null
                ? `R50: ${p.r50_km.toFixed(1)} km — 50% of historical validation prediction errors were within this distance.`
                : "—"
            }
          />
          <DetailRow
            label="R90 (empirical)"
            value={
              p.r90_km != null
                ? `R90: ${p.r90_km.toFixed(1)} km — 90% of historical validation prediction errors were within this distance.`
                : "—"
            }
          />
          <DetailRow
            label="Prediction Status"
            value={p.status === "ok" ? "AVAILABLE" : predictionStatusLabel(p.status)}
            strong
          />
          {p.ensemble_members != null && (
            <DetailRow
              label="Ensemble"
              value={`${p.ensemble_members} members · 90 % spread ${p.ensemble_spread_km ?? "—"} km`}
            />
          )}
        </>
      ) : (
        <p className="text-amber-800 text-[11.5px]" data-testid="prediction-unavailable">
          {p.status_message || "Prediction unavailable — insufficient data"}
        </p>
      )}
      <div className="pt-1 mt-1 border-t border-slate-200 space-y-1">
        <DetailRow
          label="Issued from"
          value={`${formatUTC(p.issued_from_iso)}${p.trajectory_transitions ? ` · ${p.trajectory_transitions} recent cycle hop(s)` : ""}`}
        />
        <DetailRow
          label="Cycle interval used"
          value={`${p.expected_interval_days?.toFixed(2) ?? "—"} d (${p.interval_source || "—"})`}
        />
        <DetailRow
          label="Region / cycle class"
          value={`${p.region || "—"} · ${p.cycle_class || "—"}`}
        />
        <DetailRow
          label="Regional/seasonal prior"
          value={
            p.prior_basis
              ? `${p.prior_basis}${p.prior_neighbours ? ` · n=${p.prior_neighbours}` : ""}`
              : "not available for this position"
          }
        />
        <DetailRow label="Ocean currents" value={p.currents || "—"} />
        {p.available && p.r50_km != null && p.r90_km != null && (
          <p
            className="px-2.5 py-2 bg-slate-50 border border-slate-200 rounded text-slate-600 text-[11px]"
            data-testid="prediction-radius-note"
          >
            These are empirical uncertainty radii calculated from historical validation
            errors, not a probability guarantee for this individual prediction.
            {p.validation_source ? ` Calibrated on: ${p.validation_source}.` : ""}
            {p.validation_samples ? ` Sample: ${p.validation_samples} historical validation cases.` : ""}
          </p>
        )}
        {p.validation_source && <DetailRow label="Calibration basis" value={p.validation_source} />}
        {p.forward_test && p.forward_test.n > 0 && (
          <DetailRow
            label="Forward test (scored)"
            value={`${formatForwardTest(p.forward_test)} — deployment-local audit of earlier predictions, not the historical corpus`}
          />
        )}
        {p.issues.length > 0 && (
          <ul className="text-slate-500 text-[11px] list-disc pl-4 space-y-0.5" data-testid="prediction-issues">
            {p.issues.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function DetailSection({
  title,
  children,
  testId,
}: {
  title: string;
  children: React.ReactNode;
  testId?: string;
}) {
  return (
    <div className="border border-slate-200 rounded overflow-hidden" data-testid={testId}>
      <div className="bg-slate-100 px-2.5 py-1.5 text-[11px] font-bold text-slate-600 uppercase tracking-wider border-b border-slate-200">
        {title}
      </div>
      <div className="p-2.5 space-y-1.5">{children}</div>
    </div>
  );
}

function DetailRow({
  label,
  value,
  strong,
}: {
  label: string;
  value: string;
  strong?: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-3" data-detail-label={label}>
      <span className="text-slate-500 shrink-0">{label}</span>
      <span
        className={`text-right break-words ${strong ? "font-bold text-slate-900" : "text-slate-700"}`}
      >
        {value}
      </span>
    </div>
  );
}

export default FloatStatusPage;
