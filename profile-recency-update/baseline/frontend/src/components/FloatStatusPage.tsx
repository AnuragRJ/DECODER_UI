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
import type { FleetCommStatus, FleetStatusRow } from "../types";
import FleetOceanMap, { FleetMapFloat } from "./FleetOceanMap";
import {
  FLEET_STATUS_META,
  FleetSortKey,
  SortDir,
  applyFleetFilters,
  defaultSortRows,
  formatCoord,
  formatDays,
  formatUTC,
  formatSyncInterval,
  fleetCacheIsStale,
  hasFleetPosition,
  paginateRows,
  sortFleetRows,
} from "../utils/fleetStatus";

/**
 * FloatStatusPage — fleet-level upstream communication monitoring.
 *
 * Observation timestamps come from verified Ifremer/Argo GDAC fields; communication
 * status and expected-next time are derived from those observations. Data is
 * served from the backend sync cache (/api/fleet-status); the page never
 * touches FTP and never substitutes local decoder timestamps. Styling
 * mirrors the Results workspace (header, summary metrics, fleet table);
 * the map is a separate instance of the shared FleetOceanMap (no map
 * changes — markers are status-agnostic, the tooltip uppercases status).
 */

const PAGE_SIZE = 20;

const STATUS_OPTIONS: Array<"" | FleetCommStatus> = [
  "",
  "ACTIVE",
  "OVERDUE",
  "NO COMMUNICATION 60+ DAYS",
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
  const [statusFilter, setStatusFilter] = useState<"" | FleetCommStatus>("");
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
          status: r.status,
          lat: r.lat as number,
          lon: r.lon as number,
          cyclesCount: r.profile_count ?? 0,
        })),
    [filtered]
  );
  const unplotted = filtered.length - mapFloats.length;

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
                Upstream Communication Monitor
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
          {source?.root || "/ifremer/argo"}/{source?.product || "dac/incois/<wmo>/<wmo>_Rtraj.nc"}
          {" "}· field {source?.field || "JULD_LAST_MESSAGE"}
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
          {" "}Status evaluated at {formatUTC(payload.generated_at)}. A new API response is not a new float transmission.
        </div>
      )}

      {/* ===================== Summary metrics ===================== */}
      <section
        className="bg-[#f5f8fb] border-b border-slate-200 px-4 sm:px-8 lg:px-10 py-4 shrink-0"
        data-testid="fleet-status-metrics"
      >
        <div className="flex items-stretch w-full font-mono overflow-x-auto">
          <CommMetric label="TOTAL FLOATS" value={String(summary?.total ?? "—")} valueClass="text-[#163857]" barClass="bg-[#163857]/60" />
          <CommDivider />
          <CommMetric label="ACTIVE" value={String(summary?.active ?? "—")} valueClass="text-emerald-600" barClass="bg-emerald-500/60" />
          <CommDivider />
          <CommMetric label="OVERDUE" value={String(summary?.overdue ?? "—")} valueClass="text-amber-600" barClass="bg-amber-500/60" />
          <CommDivider />
          <CommMetric label="NO COMM 60+ DAYS" value={String(summary?.no_comm_60 ?? "—")} valueClass="text-rose-600" barClass="bg-rose-500/60" />
          <CommDivider />
          <CommMetric label="NO DATA" value={String(summary?.no_data ?? "—")} valueClass="text-slate-500" barClass="bg-slate-400/60" />
          <CommDivider />
          <CommMetric label="PROFILES MISSING" value={String(summary?.profiles_missing_total ?? "—")} valueClass="text-[#276095]" barClass="bg-[#276095]/60" title={`File-cycle gaps in 1..Prof#, not communication gaps. Listings available for ${summary?.profile_records_known ?? 0}/${summary?.total ?? 0} floats.`} />
          <CommDivider />
          <CommMetric label="PROFILE CYCLES" value={String(summary?.total_profiles ?? "—")} valueClass="text-[#1d547d]" barClass="bg-[#1d547d]/60" title={`Available unique positive cycles, not the sum of Prof# or BGC sensor grids. Listings available for ${summary?.profile_records_known ?? 0}/${summary?.total ?? 0} floats.`} />
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
          onChange={(e) => setStatusFilter(e.target.value as "" | FleetCommStatus)}
          className="px-2.5 py-1.5 bg-white border border-slate-300 rounded text-[12.5px] font-mono text-slate-700 focus:outline-none focus:ring-1 focus:ring-[#276095] cursor-pointer"
          title="Filter by communication status"
        >
          {STATUS_OPTIONS.map((s) => (
            <option key={s || "all"} value={s}>
              {s === "" ? "All statuses" : s}
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
                    <th className="py-2.5 px-2 text-right font-bold">Longitude</th>
                    <th className="py-2.5 px-2 text-right font-bold">Latitude</th>
                    <SortTh label="Last Transmission" k="last_tx" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} className="py-2.5 px-2" />
                    <SortTh label="No Communication" help="Completed days since the verified upstream transmission" k="days" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} className="py-2.5 px-2 text-right" center={false} right />
                    <SortTh label="# Profs Missing" help="Missing file cycles in 1..Prof# across upstream R/D/B/S families, not missed transmissions" k="missing" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} className="py-2.5 px-2 text-center" center />
                    <th className="py-2.5 px-2 font-bold">Float Type</th>
                    <th className="py-2.5 px-2 font-bold">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {pageRows.map((r) => {
                    const isSelected = r.wmo === selectedWmo;
                    const meta = FLEET_STATUS_META[r.status];
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
                          data-field="last_tx_iso"
                          title={
                            r.last_tx_iso
                              ? `Field ${r.last_tx_field} · expected next ${formatUTC(r.expected_next_iso)}`
                              : r.communication_error || r.error || "No upstream timestamp"
                          }
                        >
                          {r.last_tx_iso ? (
                            <>
                              {formatUTC(r.last_tx_iso)}
                              {r.traj_lagging_profiles && (
                                <span
                                  className="ml-1.5 px-1.5 py-0.5 rounded bg-amber-100 border border-amber-300 text-amber-800 text-[10px] font-bold"
                                  title="A newer profile measurement exists; it is not a substitute for a communication timestamp (see detail)"
                                >
                                  TRAJ LAG
                                </span>
                              )}
                            </>
                          ) : (
                            <span className="text-slate-300">—</span>
                          )}
                        </td>
                        <td className="py-2.5 px-2 text-right font-bold tabular-nums whitespace-nowrap" data-field="days_since_last_tx" title={`Elapsed days; evaluated at ${formatUTC(payload?.generated_at || null)}`}>
                          {r.days_since_last_tx !== null ? (
                            <span className={r.status === "ACTIVE" ? "text-emerald-700" : r.status === "OVERDUE" ? "text-amber-700" : "text-rose-700"}>
                              {formatDays(r.days_since_last_tx)}
                            </span>
                          ) : (
                            <span className="text-slate-300 font-medium">—</span>
                          )}
                        </td>
                        <td
                          className="py-2.5 px-2 text-center font-bold tabular-nums"
                          data-field="profiles_missing"
                          title={
                            r.profiles_missing_list.length > 0
                              ? `Missing cycles: ${r.profiles_missing_list.join(", ")}`
                              : undefined
                          }
                        >
                          {r.profiles_missing !== null ? (
                            <span className={r.profiles_missing > 0 ? "text-amber-700" : "text-slate-500"}>
                              {r.profiles_missing}
                            </span>
                          ) : (
                            <span className="text-slate-300 font-medium">—</span>
                          )}
                        </td>
                        <td className="py-2.5 px-2 text-slate-600 text-[12.5px]" data-field="float_type">{r.float_type}</td>
                        <td className="py-2 px-2" data-field="status">
                          <span
                            className={`px-2 py-1 border rounded text-[11px] font-bold whitespace-nowrap ${meta.pill}`}
                            title={r.communication_error || r.error || undefined}
                          >
                            {r.status}
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
                    className={`px-2 py-0.5 border rounded text-[11px] font-bold whitespace-nowrap ${FLEET_STATUS_META[selected.status].pill}`}
                  >
                    {selected.status}
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
              <DetailSection title="Identity">
                <DetailRow label="Internal ID (local)" value={selected.internal_id || "— (unavailable / sanitized)"} />
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
              <DetailSection title="Communication (Ifremer GDAC)">
                <DetailRow label="Product" value={`dac/${source?.dac || "incois"}/${selected.wmo}/${selected.wmo}_Rtraj.nc`} />
                <DetailRow label="Last transmission" value={formatUTC(selected.last_tx_iso)} strong />
                <DetailRow label="Timestamp field" value={selected.last_tx_field || "—"} />
                {selected.last_tx_status_rt19 && (
                  <DetailRow label="Field status (RT19)" value={selected.last_tx_status_rt19} />
                )}
                <DetailRow label="Expected next (+10 days)" value={formatUTC(selected.expected_next_iso)} />
                {selected.communication_error && <p className="text-amber-800 text-[11.5px]">{selected.communication_error}</p>}
                {selected.last_tx_index != null && <DetailRow label="Source cycle / array index" value={`${selected.last_tx_cycle ?? "—"} / ${selected.last_tx_index} (0-based)`} />}
                <DetailRow
                  label="No communication"
                  value={
                    selected.days_since_last_tx !== null
                      ? `${selected.days_since_last_tx.toFixed(3)} days`
                      : "—"
                  }
                />
              </DetailSection>
              <DetailSection title="Position (upstream)">
                <DetailRow
                  label="Lon / Lat"
                  value={
                    selected.lon !== null && selected.lat !== null
                      ? `${formatCoord(selected.lon, "lon")} / ${formatCoord(selected.lat, "lat")}`
                      : "— (no usable upstream position)"
                  }
                />
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
              <DetailSection title="Profiles (upstream)">
                <DetailRow label="Available profile cycles" value={selected.profile_count != null ? String(selected.profile_count) : "—"} />
                <DetailRow label="Latest profile cycle (Prof#)" value={selected.prof_num !== null ? String(selected.prof_num) : "—"} />
                <DetailRow
                  label="Missing file cycles"
                  value={
                    selected.profiles_missing !== null
                      ? selected.profiles_missing_list.length > 0
                        ? `${selected.profiles_missing} — cycles ${selected.profiles_missing_list.join(", ")}`
                        : "0"
                      : "—"
                  }
                />
                {selected.latest_profile && (
                  <>
                    <DetailRow label="Latest profile file" value={selected.latest_profile.file || "—"} />
                    <DetailRow
                      label="Profile measurement time"
                      value={`${formatUTC(selected.latest_profile.juld_iso)} (measurement, not a transmission)`}
                    />
                  </>
                )}
                {selected.traj_max_cycle !== null && (
                  <DetailRow label="Trajectory max cycle" value={String(selected.traj_max_cycle)} />
                )}
                {selected.traj_lagging_profiles && (
                  <div className="px-2.5 py-2 bg-amber-50 border border-amber-300 rounded text-amber-900 text-[12px]">
                    ⚠ A profile measurement is newer than the recorded communication. Upstream products
                    disagree in recency; profile time is not substituted for Last Transmission.
                  </div>
                )}
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
              <DetailSection title="Sync">
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

function CommDivider() {
  return (
    <div
      className="w-px self-stretch my-1 bg-slate-200/90 hidden sm:block shrink-0"
      aria-hidden="true"
    />
  );
}

function CommMetric({
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

function DetailSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="border border-slate-200 rounded overflow-hidden">
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
