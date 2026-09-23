/**
 * FormatCheckerDrawer — side drawer showing the complete format-check result
 * for a single WMO, including per-file details and exact error messages
 * from the official OneArgo ArgoFormatChecker.
 */
import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import {
  X,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Clock,
  FileText,
  ChevronDown,
  ChevronRight,
  Loader2,
  ShieldCheck,
  ShieldAlert,
  ShieldX,
  ShieldQuestion,
} from "lucide-react";
import type {
  FormatCheckerDetail,
  FormatCheckerFileResult,
  FormatCheckerStatus,
} from "../types";

// ---------------------------------------------------------------------------
// Category display config
// ---------------------------------------------------------------------------
const CATEGORY_ORDER = [
  "meta",
  "tech",
  "traj",
  "profile",
  "mono_profile",
  "bgc_profile",
  "bgc_traj",
] as const;

const CATEGORY_LABELS: Record<string, string> = {
  meta: "METADATA",
  tech: "TECHNICAL",
  traj: "TRAJECTORY",
  profile: "CORE PROFILE / MULTI-PROFILE",
  mono_profile: "MONO PROFILES",
  bgc_profile: "BGC PROFILE",
  bgc_traj: "BGC TRAJECTORY",
};

// ---------------------------------------------------------------------------
// Status badge component
// ---------------------------------------------------------------------------
function StatusBadge({ status }: { status: FormatCheckerStatus | string }) {
  const config: Record<string, { bg: string; text: string; icon: React.ReactNode; label: string }> = {
    accepted: {
      bg: "bg-emerald-100",
      text: "text-emerald-800",
      icon: <ShieldCheck className="w-4 h-4" />,
      label: "ACCEPTED",
    },
    rejected: {
      bg: "bg-red-100",
      text: "text-red-800",
      icon: <ShieldX className="w-4 h-4" />,
      label: "REJECTED",
    },
    checker_error: {
      bg: "bg-red-100",
      text: "text-red-700",
      icon: <ShieldAlert className="w-4 h-4" />,
      label: "CHECKER ERROR",
    },
    incomplete: {
      bg: "bg-amber-100",
      text: "text-amber-800",
      icon: <AlertTriangle className="w-4 h-4" />,
      label: "INCOMPLETE",
    },
    checking: {
      bg: "bg-blue-100",
      text: "text-blue-700",
      icon: <Loader2 className="w-4 h-4 animate-spin" />,
      label: "CHECKING…",
    },
    not_checked: {
      bg: "bg-slate-100",
      text: "text-slate-500",
      icon: <ShieldQuestion className="w-4 h-4" />,
      label: "NOT CHECKED",
    },
  };
  const c = config[status] ?? config.not_checked;
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-bold uppercase tracking-wider ${c.bg} ${c.text}`}
    >
      {c.icon}
      {c.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// File result badge (small, inline)
// ---------------------------------------------------------------------------
function FileResultBadge({ result }: { result: string }) {
  if (result === "FILE-ACCEPTED") {
    return (
      <span className="inline-flex items-center gap-1 text-emerald-700 font-semibold text-xs">
        <CheckCircle className="w-3.5 h-3.5" />
        ACCEPTED
      </span>
    );
  }
  if (result === "FILE-REJECTED") {
    return (
      <span className="inline-flex items-center gap-1 text-red-700 font-semibold text-xs">
        <XCircle className="w-3.5 h-3.5" />
        REJECTED
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-amber-700 font-semibold text-xs">
      <AlertTriangle className="w-3.5 h-3.5" />
      ERROR
    </span>
  );
}

// ---------------------------------------------------------------------------
// Expandable file row
// ---------------------------------------------------------------------------
function FileRow({ file }: { file: FormatCheckerFileResult }) {
  const [expanded, setExpanded] = useState(false);
  const hasMessages =
    file.errors_messages.length > 0 || file.warnings_messages.length > 0;
  const isExpandable = hasMessages || file.result !== "FILE-ACCEPTED";

  return (
    <div className="border-b border-slate-100 last:border-b-0">
      <button
        type="button"
        className={`w-full flex items-center gap-2 px-3 py-2 text-left text-[12px] font-mono hover:bg-slate-50 transition-colors ${
          isExpandable ? "cursor-pointer" : "cursor-default"
        }`}
        onClick={() => isExpandable && setExpanded(!expanded)}
        disabled={!isExpandable}
      >
        {isExpandable ? (
          expanded ? (
            <ChevronDown className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
          ) : (
            <ChevronRight className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
          )
        ) : (
          <span className="w-3.5 flex-shrink-0" />
        )}

        {/* Cycle */}
        <span className="w-16 text-slate-500 flex-shrink-0">
          {file.cycle !== null ? `Cycle ${String(file.cycle).padStart(3, "0")}` : "—"}
        </span>

        {/* Filename */}
        <span className="flex-1 text-slate-800 truncate" title={file.filename}>
          {file.filename}
        </span>

        {/* Result badge */}
        <span className="flex-shrink-0">
          <FileResultBadge result={file.result} />
        </span>

        {/* Error/warning counts */}
        <span className="w-24 text-right text-slate-500 flex-shrink-0">
          {file.errors_number > 0 && (
            <span className="text-red-600 font-semibold">
              {file.errors_number} err{file.errors_number !== 1 ? "s" : ""}
            </span>
          )}
          {file.errors_number > 0 && file.warnings_number > 0 && " · "}
          {file.warnings_number > 0 && (
            <span className="text-amber-600">
              {file.warnings_number} warn{file.warnings_number !== 1 ? "s" : ""}
            </span>
          )}
          {file.errors_number === 0 && file.warnings_number === 0 && (
            <span className="text-slate-400">clean</span>
          )}
        </span>
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className="px-4 pb-3 pt-1 ml-6 border-l-2 border-slate-200 bg-slate-50/50 text-[11px] space-y-2">
          <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-slate-600">
            <span className="font-semibold">Filename</span>
            <span className="font-mono">{file.filename}</span>
            <span className="font-semibold">Category</span>
            <span>{file.category}</span>
            {file.cycle !== null && (
              <>
                <span className="font-semibold">Cycle</span>
                <span>{file.cycle}</span>
              </>
            )}
            <span className="font-semibold">Result</span>
            <FileResultBadge result={file.result} />
            {file.phase && (
              <>
                <span className="font-semibold">Phase</span>
                <span className="font-mono">{file.phase}</span>
              </>
            )}
          </div>

          {file.errors_messages.length > 0 && (
            <div>
              <div className="font-bold text-red-700 uppercase tracking-wider mb-1">
                Errors ({file.errors_messages.length})
              </div>
              <ol className="list-decimal list-inside space-y-0.5">
                {file.errors_messages.map((msg, i) => (
                  <li key={i} className="text-red-800 font-mono break-all">
                    {msg}
                  </li>
                ))}
              </ol>
            </div>
          )}

          {file.warnings_messages.length > 0 && (
            <div>
              <div className="font-bold text-amber-700 uppercase tracking-wider mb-1">
                Warnings ({file.warnings_messages.length})
              </div>
              <ol className="list-decimal list-inside space-y-0.5">
                {file.warnings_messages.map((msg, i) => (
                  <li key={i} className="text-amber-800 font-mono break-all">
                    {msg}
                  </li>
                ))}
              </ol>
            </div>
          )}

          {file.errors_messages.length === 0 && file.warnings_messages.length === 0 && (
            <p className="text-slate-400 italic">No error or warning messages.</p>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Category section
// ---------------------------------------------------------------------------
function CategorySection({
  category,
  files,
}: {
  category: string;
  files: FormatCheckerFileResult[];
}) {
  const [collapsed, setCollapsed] = useState(false);
  const label = CATEGORY_LABELS[category] ?? category.toUpperCase();
  const accepted = files.filter((f) => f.result === "FILE-ACCEPTED").length;
  const rejected = files.filter((f) => f.result === "FILE-REJECTED").length;

  // Sort mono-profile files by cycle
  const sorted = useMemo(() => {
    if (category === "mono_profile" || category === "bgc_profile") {
      return [...files].sort((a, b) => (a.cycle ?? 0) - (b.cycle ?? 0));
    }
    return files;
  }, [files, category]);

  return (
    <div className="border border-slate-200 rounded-lg overflow-hidden mb-3">
      <button
        type="button"
        className="w-full flex items-center gap-2 px-3 py-2 bg-slate-50 hover:bg-slate-100 transition-colors text-left"
        onClick={() => setCollapsed(!collapsed)}
      >
        {collapsed ? (
          <ChevronRight className="w-4 h-4 text-slate-400" />
        ) : (
          <ChevronDown className="w-4 h-4 text-slate-400" />
        )}
        <span className="text-xs font-bold uppercase tracking-wider text-slate-700">
          {label}
        </span>
        <span className="text-xs text-slate-500 ml-auto">
          {files.length} file{files.length !== 1 ? "s" : ""}
          {accepted > 0 && (
            <span className="text-emerald-600 ml-2">
              {accepted} accepted
            </span>
          )}
          {rejected > 0 && (
            <span className="text-red-600 ml-2">
              {rejected} rejected
            </span>
          )}
        </span>
      </button>
      {!collapsed && (
        <div>
          {sorted.map((file) => (
            <FileRow key={file.filename} file={file} />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main drawer component
// ---------------------------------------------------------------------------
interface FormatCheckerDrawerProps {
  wmo: number;
  runId?: string | null;
  open: boolean;
  onClose: () => void;
  onResultChange?: (result: FormatCheckerDetail) => void;
}

export default function FormatCheckerDrawer({
  wmo,
  runId,
  open,
  onClose,
  onResultChange,
}: FormatCheckerDrawerProps) {
  const [detail, setDetail] = useState<FormatCheckerDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Keep a stable ref for onResultChange to avoid triggering re-fetch cascades
  const onResultChangeRef = useRef(onResultChange);
  useEffect(() => {
    onResultChangeRef.current = onResultChange;
  });

  // Track the current WMO for which detail was loaded
  const currentWmoRef = useRef<number | null>(null);

  // Stable fetcher that only sets loading=true on initial load
  const fetchDetail = useCallback(async (showLoading = false) => {
    if (!wmo) return;
    if (showLoading) setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/floats/${wmo}/format-check`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: FormatCheckerDetail = await res.json();
      setDetail(data);
      onResultChangeRef.current?.(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load");
    } finally {
      if (showLoading) setLoading(false);
    }
  }, [wmo]);

  // Initial fetch when drawer opens or WMO changes — runs once per float selection
  useEffect(() => {
    if (!open || !wmo) return;
    let active = true;
    const isNewWmo = currentWmoRef.current !== wmo;
    currentWmoRef.current = wmo;

    if (isNewWmo) {
      setDetail(null);
      setError(null);
    }

    const run = async () => {
      if (isNewWmo) setLoading(true);
      setError(null);
      try {
        const res = await fetch(`/api/floats/${wmo}/format-check`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data: FormatCheckerDetail = await res.json();
        if (active) {
          setDetail(data);
          onResultChangeRef.current?.(data);
        }
      } catch (err: unknown) {
        if (active) {
          setError(err instanceof Error ? err.message : "Failed to load");
        }
      } finally {
        if (active && isNewWmo) {
          setLoading(false);
        }
      }
    };

    run();

    return () => {
      active = false;
    };
  }, [open, wmo]);

  // Background poll ONLY when status is actively checking (no loading spinner, no flicker)
  useEffect(() => {
    if (!open || !wmo || detail?.status !== "checking") return;
    let active = true;

    const timer = setTimeout(async () => {
      try {
        const res = await fetch(`/api/floats/${wmo}/format-check`);
        if (!res.ok) return;
        const data: FormatCheckerDetail = await res.json();
        if (active) {
          setDetail(data);
          onResultChangeRef.current?.(data);
        }
      } catch {
        /* retry on next interval */
      }
    }, 2000);

    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [open, wmo, detail?.status]);

  const handleRunCheck = async () => {
    if (!wmo || running) return;
    setRunning(true);
    setError(null);
    try {
      const url = runId
        ? `/api/floats/${wmo}/format-check/run?run_id=${encodeURIComponent(runId)}`
        : `/api/floats/${wmo}/format-check/run`;
      const res = await fetch(url, { method: "POST" });
      const data = await res.json();
      if (data.status === "no_files") {
        setError(data.error || "No decoded NetCDF files found on disk for this float. Decode the float first.");
      } else {
        setDetail((prev) => (prev ? { ...prev, status: "checking" } : null));
        fetchDetail(false);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to run format check");
    } finally {
      setRunning(false);
    }
  };

  // Group files by category
  const filesByCategory = useMemo(() => {
    if (!detail?.files) return {};
    const groups: Record<string, FormatCheckerFileResult[]> = {};
    for (const f of detail.files) {
      const cat = f.category || "unknown";
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(f);
    }
    return groups;
  }, [detail]);

  // Ordered categories that actually have files
  const orderedCategories = useMemo(() => {
    const cats: string[] = [];
    for (const cat of CATEGORY_ORDER) {
      if (filesByCategory[cat]?.length) cats.push(cat);
    }
    // Add any unlisted categories
    for (const cat of Object.keys(filesByCategory)) {
      if (!cats.includes(cat)) cats.push(cat);
    }
    return cats;
  }, [filesByCategory]);

  if (!open) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/30 z-40 transition-opacity"
        onClick={onClose}
      />

      {/* Drawer */}
      <div className="fixed inset-y-0 right-0 w-[680px] max-w-full bg-white shadow-2xl z-50 flex flex-col overflow-hidden border-l border-slate-200">
        {/* Header */}
        <div className="bg-slate-900 text-white px-5 py-4 flex items-start justify-between">
          <div>
            <div className="text-[10px] uppercase tracking-[0.2em] text-slate-400 mb-1">
              Argo Format Checker
            </div>
            <div className="text-lg font-bold font-mono">
              WMO {wmo}{" "}
              <span className="text-slate-400 font-normal text-sm">
                · DAC INCOIS
              </span>
            </div>
            {detail && (
              <div className="mt-2">
                <StatusBadge status={detail.status} />
                {detail.stale && (
                  <span className="ml-2 text-xs text-amber-400 font-semibold">
                    (stale — re-check in progress)
                  </span>
                )}
              </div>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleRunCheck}
              disabled={running || detail?.status === "checking"}
              className="px-3 py-1.5 bg-[#276095] hover:bg-[#1f4e7a] text-white rounded text-xs font-bold transition flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
              title="Execute the official OneArgo ArgoFormatChecker on this float's decoded files"
            >
              {running || detail?.status === "checking" ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  Checking…
                </>
              ) : (
                <>
                  <ShieldCheck className="w-3.5 h-3.5" />
                  {detail?.status && detail.status !== "not_checked" ? "Re-run Check" : "Run Check"}
                </>
              )}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="text-slate-400 hover:text-white transition-colors p-1 cursor-pointer"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto">
          {loading && !detail && (
            <div className="flex items-center justify-center h-40 text-slate-400">
              <Loader2 className="w-6 h-6 animate-spin mr-2" />
              Loading format check result…
            </div>
          )}

          {error && !detail && (
            <div className="p-5 text-red-600 text-sm">
              <AlertTriangle className="w-5 h-5 inline mr-2" />
              {error}
            </div>
          )}

          {detail && (
            <div className="p-5 space-y-5">
              {error && (
                <div className="p-3 bg-red-50 border border-red-200 rounded text-red-700 text-xs flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4 shrink-0" />
                  <span>{error}</span>
                </div>
              )}
              {/* Summary cards */}
              <div className="grid grid-cols-5 gap-2">
                {[
                  {
                    label: "Files Checked",
                    value: detail.total_files,
                    color: "text-slate-700",
                  },
                  {
                    label: "Accepted",
                    value: detail.accepted_files,
                    color: "text-emerald-700",
                  },
                  {
                    label: "Rejected",
                    value: detail.rejected_files,
                    color:
                      detail.rejected_files > 0
                        ? "text-red-700"
                        : "text-slate-400",
                  },
                  {
                    label: "Errors",
                    value: detail.total_errors,
                    color:
                      detail.total_errors > 0
                        ? "text-red-600"
                        : "text-slate-400",
                  },
                  {
                    label: "Warnings",
                    value: detail.total_warnings,
                    color:
                      detail.total_warnings > 0
                        ? "text-amber-600"
                        : "text-slate-400",
                  },
                ].map((card) => (
                  <div
                    key={card.label}
                    className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-center"
                  >
                    <div className={`text-2xl font-bold ${card.color}`}>
                      {card.value}
                    </div>
                    <div className="text-[10px] uppercase tracking-wider text-slate-500 mt-0.5">
                      {card.label}
                    </div>
                  </div>
                ))}
              </div>

              {/* Provenance */}
              <div className="text-[11px] text-slate-500 flex items-center gap-3 flex-wrap">
                {detail.checked_at && (
                  <span>
                    <Clock className="w-3 h-3 inline mr-1" />
                    Checked:{" "}
                    {new Date(detail.checked_at).toLocaleString("en-GB", {
                      dateStyle: "medium",
                      timeStyle: "short",
                      timeZone: "UTC",
                    })}{" "}
                    UTC
                  </span>
                )}
                {detail.checker_version && (
                  <span>
                    Checker v{detail.checker_version}
                  </span>
                )}
              </div>

              {/* Discovery info */}
              {detail.discovery?.discovery_errors?.length > 0 && (
                <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs">
                  <div className="font-bold text-amber-800 mb-1">
                    <AlertTriangle className="w-3.5 h-3.5 inline mr-1" />
                    Discovery Issues
                  </div>
                  <ul className="list-disc list-inside text-amber-700 space-y-0.5 font-mono">
                    {detail.discovery.discovery_errors.map((e, i) => (
                      <li key={i}>{e}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* File sections by category */}
              {orderedCategories.length > 0 ? (
                orderedCategories.map((cat) => (
                  <CategorySection
                    key={cat}
                    category={cat}
                    files={filesByCategory[cat]}
                  />
                ))
              ) : detail.status === "not_checked" ? (
                <div className="text-center text-slate-400 py-8 space-y-3">
                  <ShieldQuestion className="w-8 h-8 mx-auto text-slate-300" />
                  <p className="font-semibold text-slate-600">No format check has been run for this float yet.</p>
                  <p className="text-xs text-slate-500 max-w-sm mx-auto">
                    Execute the official OneArgo ArgoFormatChecker to validate all NetCDF files against the Argo specification.
                  </p>
                  <button
                    type="button"
                    onClick={handleRunCheck}
                    disabled={running}
                    className="inline-flex items-center gap-1.5 px-4 py-2 bg-[#276095] hover:bg-[#1f4e7a] text-white rounded font-bold text-xs shadow-xs cursor-pointer disabled:opacity-50"
                  >
                    {running ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ShieldCheck className="w-3.5 h-3.5" />}
                    Run Format Check Now
                  </button>
                </div>
              ) : (
                <div className="text-center text-slate-400 py-8">
                  <FileText className="w-8 h-8 mx-auto text-slate-300 mb-2" />
                  <p>No file results available.</p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
