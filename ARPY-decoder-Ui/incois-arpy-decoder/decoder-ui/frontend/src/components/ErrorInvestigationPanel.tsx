import React, { useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Circle,
  FileText,
  FolderOpen,
  ListOrdered,
  ScrollText,
  X,
  XCircle,
} from "lucide-react";
import { useDecoderStore } from "../store/useDecoderStore";
import {
  buildProcessingTimeline,
  primaryErrorSuffix,
  type TimelineStepStatus,
} from "../utils/investigate";

const INPUT_STAGES = new Set([
  "INPUT_DISCOVERY",
  "INPUT_PREPARATION",
  "INPUT_FILES",
  "DISCOVERY",
]);

function StepIcon({ status }: { status: TimelineStepStatus }) {
  if (status === "completed") return <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />;
  if (status === "failed") return <XCircle className="w-3.5 h-3.5 text-red-600" />;
  if (status === "active") return <Circle className="w-3.5 h-3.5 text-sky-600 fill-sky-200" />;
  return <Circle className="w-3.5 h-3.5 text-slate-300" />;
}

const STEP_STATUS_WORD: Record<TimelineStepStatus, string> = {
  completed: "done",
  failed: "failed",
  active: "active",
  "not-reached": "not reached",
};

function Fact({ label, value, mono = true }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <div className="text-[9.5px] font-semibold uppercase tracking-wider text-slate-400">{label}</div>
      <div
        className={`text-[11.5px] text-slate-800 truncate ${mono ? "font-mono" : "font-sans"}`}
        title={value}
      >
        {value}
      </div>
    </div>
  );
}

function ActionButton({
  onClick,
  icon,
  label,
  title,
  primary = false,
}: {
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
  title: string;
  primary?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      className={
        primary
          ? "inline-flex items-center space-x-1.5 px-2.5 py-1.5 rounded border border-slate-800 bg-slate-800 text-white text-[11px] font-mono font-semibold hover:bg-slate-700"
          : "inline-flex items-center space-x-1.5 px-2.5 py-1.5 rounded border border-slate-300 bg-white text-slate-700 text-[11px] font-mono font-semibold hover:bg-slate-50"
      }
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

function PanelShell({
  title,
  subtitle,
  onClose,
  children,
}: {
  title: string;
  subtitle: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col h-full overflow-hidden select-none text-slate-800">
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-200 bg-white shrink-0">
        <div className="flex items-center space-x-2 min-w-0">
          <AlertTriangle className="w-4 h-4 text-red-600 shrink-0" />
          <div className="min-w-0">
            <h2 className="text-[12px] font-mono font-bold text-slate-900 leading-tight">{title}</h2>
            <p className="text-[10.5px] font-mono text-slate-500 truncate">{subtitle}</p>
          </div>
        </div>
        <button
          onClick={onClose}
          title="Close the investigation and return to the Decoder Log"
          className="p-1.5 rounded text-slate-400 hover:text-slate-700 hover:bg-slate-100 shrink-0"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-3 space-y-3">{children}</div>
    </div>
  );
}

/** Interactive Error Detail: WHAT failed first, the log one click away. */
export const ErrorInvestigationPanel: React.FC = () => {
  const {
    investigationRunId,
    investigation,
    investigationLoading,
    investigationError,
    investigationMissing,
    openInvestigation,
    closeInvestigation,
    setSelectedEvent,
    setLogFilter,
    setOutputModalOpen,
    setActiveView,
    events,
  } = useDecoderStore();
  const [showAllErrors, setShowAllErrors] = useState(false);

  const backToLog = () => closeInvestigation();
  const viewRun = () => closeInvestigation({ unfocusError: true });

  // ---- loading / fetch-error / run-not-started variants -------------------
  if (investigationLoading || (!investigation && !investigationMissing && !investigationError)) {
    return (
      <PanelShell title="Error Investigation" subtitle={investigationRunId ?? ""} onClose={backToLog}>
        <div className="text-[11.5px] font-mono text-slate-500 py-8 text-center">
          Loading the error investigation…
        </div>
      </PanelShell>
    );
  }

  if (investigationError && !investigation && !investigationMissing) {
    return (
      <PanelShell title="Error Investigation" subtitle={investigationRunId ?? ""} onClose={backToLog}>
        <div className="bg-white border border-slate-200 rounded p-3 space-y-2">
          <p className="text-[11.5px] font-sans text-slate-700">{investigationError}</p>
          <div className="flex flex-wrap gap-2">
            {investigationRunId && (
              <ActionButton
                onClick={() => openInvestigation(investigationRunId)}
                icon={<ScrollText className="w-3.5 h-3.5" />}
                label="Retry"
                title="Retry loading the investigation"
                primary
              />
            )}
            <ActionButton
              onClick={backToLog}
              icon={<FileText className="w-3.5 h-3.5" />}
              label="View Decoder Log"
              title="Return to the Decoder Log for this run"
            />
          </div>
        </div>
      </PanelShell>
    );
  }

  if (investigationMissing && !investigation) {
    const { runId, wmo, knownError } = investigationMissing;
    return (
      <PanelShell title="Error Investigation" subtitle={runId} onClose={backToLog}>
        <div className="bg-white border border-slate-200 rounded p-3 space-y-2">
          <div className="flex items-center space-x-2">
            <span className="inline-flex items-center px-2 py-0.5 rounded text-[10.5px] font-mono font-bold bg-slate-100 text-slate-700 border border-slate-300">
              Decoder run not started
            </span>
          </div>
          <div className="grid grid-cols-2 gap-x-3 gap-y-2">
            <Fact label="WMO" value={wmo ? String(wmo) : "—"} />
            <Fact label="Run" value={runId} />
          </div>
          {knownError ? (
            <div className="pt-1">
              <div className="text-[9.5px] font-semibold uppercase tracking-wider text-slate-400 mb-1">
                Reported error
              </div>
              <pre className="text-[11px] font-mono text-slate-800 bg-slate-50 border border-slate-200 rounded p-2 whitespace-pre-wrap break-words max-h-40 overflow-y-auto">
                {knownError}
              </pre>
            </div>
          ) : (
            <p className="text-[11px] font-sans text-slate-500">
              No run record and no reported error are available for this id — there is nothing to
              investigate yet.
            </p>
          )}
          <div className="flex flex-wrap gap-2 pt-1">
            <ActionButton
              onClick={() => {
                closeInvestigation();
                setActiveView("results");
              }}
              icon={<ArrowLeft className="w-3.5 h-3.5" />}
              label="Back to Results"
              title="Return to the Results table"
              primary
            />
            <ActionButton
              onClick={backToLog}
              icon={<FileText className="w-3.5 h-3.5" />}
              label="View Decoder Log"
              title="Return to the Decoder Log view"
            />
          </div>
        </div>
      </PanelShell>
    );
  }

  if (!investigation) return null;

  // ---- main investigation view ---------------------------------------------
  const inv = investigation;
  const steps = buildProcessingTimeline(inv.stages);
  const extra = Math.max(0, inv.error_count - 1);
  const focus = inv.focus_event;
  const cycleText = focus?.cycle !== null && focus?.cycle !== undefined ? String(focus.cycle) : "—";
  const failureTime = focus?.timestamp || inv.ended_at || "—";
  const inputSource = focus?.input_summary || "—";
  const hasOutput = inv.outputs_count > 0;
  const inputEvent = events.find((e) => INPUT_STAGES.has((e.stage ?? "").toUpperCase())) ?? null;
  const whereLine = focus
    ? [focus.python_file || null, focus.python_function || null].filter(Boolean).join(" · ") ||
      focus.operation ||
      focus.stage ||
      "—"
    : "—";

  return (
    <PanelShell
      title={`Error Investigation — WMO ${inv.wmo}`}
      subtitle={inv.run_id}
      onClose={backToLog}
    >
      {/* Facts: what failed, where it stopped. Nothing is invented. */}
      <div className="bg-white border border-slate-200 rounded p-3 space-y-2.5">
        <div className="flex items-center flex-wrap gap-2">
          <span className="inline-flex items-center px-2 py-0.5 rounded text-[10.5px] font-mono font-bold bg-red-50 text-red-700 border border-red-200">
            {inv.category_label}
          </span>
          <span className="text-[10.5px] font-mono text-slate-500">
            {inv.status}
            {inv.is_prerun ? " · pre-run record" : ""}
          </span>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-3 gap-y-2">
          <Fact label="WMO" value={String(inv.wmo)} />
          <Fact label="Cycle" value={cycleText} />
          <Fact label="Status" value={inv.status} />
          <Fact label="Failure stage" value={inv.failure_stage ?? "—"} />
          <Fact label="Time of failure" value={failureTime} />
          <Fact label="Run" value={inv.run_id} />
        </div>
        <Fact label="Input source" value={inputSource} />
        <div>
          <div className="text-[9.5px] font-semibold uppercase tracking-wider text-slate-400 mb-1">
            Primary error{primaryErrorSuffix(extra)}
          </div>
          <pre className="text-[11px] font-mono text-slate-800 bg-slate-50 border-l-2 border-red-400 rounded-r p-2 whitespace-pre-wrap break-words max-h-44 overflow-y-auto">
            {inv.primary_error || "—"}
          </pre>
          {extra > 0 && (
            <div className="mt-1.5">
              <button
                onClick={() => setShowAllErrors((v) => !v)}
                className="inline-flex items-center space-x-1 text-[11px] font-mono font-semibold text-slate-600 hover:text-slate-900"
              >
                {showAllErrors ? (
                  <ChevronUp className="w-3.5 h-3.5" />
                ) : (
                  <ChevronDown className="w-3.5 h-3.5" />
                )}
                <span>
                  {showAllErrors ? "Hide" : "Show"} all {inv.error_count} errors
                </span>
              </button>
              {showAllErrors && (
                <ol className="mt-1.5 space-y-1.5">
                  {inv.all_errors.map((err, i) => (
                    <li
                      key={i}
                      className="text-[10.5px] font-mono text-slate-700 bg-white border border-slate-200 rounded p-1.5 whitespace-pre-wrap break-words max-h-32 overflow-y-auto"
                    >
                      <span className="text-slate-400">
                        [{i + 1}/{inv.error_count}]{i === inv.error_count - 1 ? " primary" : ""}{" "}
                      </span>
                      {err}
                    </li>
                  ))}
                </ol>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Processing timeline: how far the run got. */}
      <div className="bg-white border border-slate-200 rounded p-3">
        <div className="text-[9.5px] font-semibold uppercase tracking-wider text-slate-400 mb-2">
          Processing timeline
        </div>
        <div className="flex items-stretch gap-0 overflow-x-auto pb-1">
          {steps.map((step, i) => (
            <React.Fragment key={step.key}>
              {i > 0 && <div className="w-3 shrink-0 border-t border-slate-200 mt-[9px]" />}
              <div
                className={`flex-1 min-w-[92px] rounded border px-1.5 py-1.5 text-center ${
                  step.status === "failed"
                    ? "border-red-300 bg-red-50/50"
                    : "border-slate-200 bg-slate-50/60"
                }`}
                title={step.detail || step.label}
              >
                <div className="flex justify-center">
                  <StepIcon status={step.status} />
                </div>
                <div className="text-[9.5px] font-mono font-semibold text-slate-700 leading-tight mt-1">
                  {step.label}
                </div>
                <div
                  className={`text-[9px] font-mono leading-tight ${
                    step.status === "failed" ? "text-red-600 font-bold" : "text-slate-400"
                  }`}
                >
                  {STEP_STATUS_WORD[step.status]}
                </div>
              </div>
            </React.Fragment>
          ))}
        </div>
        {steps.some((s) => s.status === "failed" && s.detail) && (
          <p className="text-[10.5px] font-mono text-slate-600 mt-2 truncate" title={steps.find((s) => s.status === "failed")?.detail}>
            {steps.find((s) => s.status === "failed")?.detail}
          </p>
        )}
      </div>

      {/* Root cause: what / where / why, or the exact unavailable line. */}
      <div className="bg-white border border-slate-200 rounded p-3 space-y-2">
        <div className="text-[9.5px] font-semibold uppercase tracking-wider text-slate-400">
          Root cause
        </div>
        {inv.root_cause_available ? (
          <>
            <p className="text-[11.5px] font-sans text-slate-800 leading-relaxed">{inv.root_cause}</p>
            <div className="grid grid-cols-1 gap-y-1.5">
              <Fact label="Where" value={whereLine} />
              {focus?.operation && <Fact label="Operation" value={focus.operation} />}
              {focus?.stage && <Fact label="Stage" value={focus.stage} />}
            </div>
            {inv.recommended_action && (
              <p className="text-[11px] font-sans text-slate-600 leading-relaxed">
                <span className="font-semibold text-slate-700">Recommended action: </span>
                {inv.recommended_action}
              </p>
            )}
          </>
        ) : (
          <p className="text-[11.5px] font-mono text-slate-600">Root cause unavailable</p>
        )}
        {inv.evidence.length > 0 && (
          <div>
            <div className="text-[9.5px] font-semibold uppercase tracking-wider text-slate-400 mb-1">
              Evidence
            </div>
            <ul className="space-y-1">
              {inv.evidence.map((ev, i) => (
                <li key={i} className="text-[10.5px] font-mono text-slate-600 flex space-x-1.5">
                  <span className="text-slate-400 shrink-0">{ev.source}:</span>
                  <span className="break-words min-w-0">{ev.detail}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* Evidence actions: only shown when the target exists. */}
      <div className="bg-white border border-slate-200 rounded p-3">
        <div className="text-[9.5px] font-semibold uppercase tracking-wider text-slate-400 mb-2">
          Evidence
        </div>
        <div className="flex flex-wrap gap-2">
          <ActionButton
            onClick={backToLog}
            icon={<FileText className="w-3.5 h-3.5" />}
            label="View Decoder Log"
            title="Return to the Decoder Log for this run, focused on the error"
            primary
          />
          <ActionButton
            onClick={viewRun}
            icon={<ListOrdered className="w-3.5 h-3.5" />}
            label="View Run"
            title="Return to the plain run view (clears the error focus)"
          />
          {inputEvent && (
            <ActionButton
              onClick={() => {
                setSelectedEvent(inputEvent);
                setLogFilter("all");
                closeInvestigation();
              }}
              icon={<FolderOpen className="w-3.5 h-3.5" />}
              label="View Input"
              title={`Open the log at the input event “${inputEvent.id}”`}
            />
          )}
          {hasOutput && (
            <ActionButton
              onClick={() => setOutputModalOpen(true)}
              icon={<ScrollText className="w-3.5 h-3.5" />}
              label="View Output"
              title={`Open the ${inv.outputs_count} output file(s) of this run`}
            />
          )}
        </div>
      </div>
    </PanelShell>
  );
};
