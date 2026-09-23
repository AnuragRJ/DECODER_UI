import React, { useEffect } from "react";
import { Header } from "./components/Header";
import { BatchProgressBanner } from "./components/BatchProgressBanner";
import { LeftPanel } from "./components/LeftPanel";
import { CenterPanel } from "./components/CenterPanel";
import { RightPanel } from "./components/RightPanel";
import { EventDetailDrawer } from "./components/EventDetailDrawer";
import { ResultsWorkspace } from "./components/ResultsWorkspace";
import { FloatStatusPage } from "./components/FloatStatusPage";
import { RtqcModal } from "./components/RtqcModal";
import { CycleDetailModal } from "./components/CycleDetailModal";
import { OutputFilesModal } from "./components/OutputFilesModal";
import { FlowchartModal } from "./components/FlowchartModal";
import { BatchResultsModal } from "./components/BatchResultsModal";
import { RunHistoryModal } from "./components/RunHistoryModal";
import { DecodeAllCompleteModal } from "./components/DecodeAllCompleteModal";
import { useDecoderStore } from "./store/useDecoderStore";

/** Slim, dismissible feedback strip for email deep links whose target run or
 *  event could not be resolved (otherwise the UI silently stayed on the
 *  default run, which read as "the link doesn't open the error"). */
const DeepLinkNotice: React.FC = () => {
  const notice = useDecoderStore((s) => s.deepLinkNotice);
  const setNotice = useDecoderStore((s) => s.setDeepLinkNotice);
  if (!notice) return null;
  return (
    <div className="shrink-0 flex items-center gap-3 bg-amber-50 border-b border-amber-300 px-4 py-2 text-xs text-amber-900">
      <span className="flex-1 leading-snug">{notice}</span>
      <button
        onClick={() => setNotice(null)}
        className="shrink-0 font-semibold tracking-wide hover:text-amber-950"
      >
        Dismiss
      </button>
    </div>
  );
};

export const App: React.FC = () => {
  const { fetchPresets, initWebSocket, activeView, viewRun } = useDecoderStore();

  useEffect(() => {
    if (typeof window !== "undefined") {
      (window as unknown as { useDecoderStore: typeof useDecoderStore }).useDecoderStore = useDecoderStore;
    }
  }, []);

  useEffect(() => {
    fetchPresets().then(() => {
      if (typeof window !== "undefined") {
        const params = new URLSearchParams(window.location.search);
        const runId = params.get("run_id");
        const eventId = params.get("event_id");
        const focus = params.get("focus");
        if (runId) {
          viewRun(runId, focus === "error", eventId, { viaEmail: true });
        }
      }
    });
    initWebSocket();
    // Incoming-data ingestion (read-only): keep arrival state fresh so NEW
    // DATA badges appear within seconds of a source scan. Ingestion is
    // observational — it never starts decoding.
    const ing = useDecoderStore.getState().fetchIngestion;
    ing();
    const ingTimer = window.setInterval(ing, 15000);
    return () => window.clearInterval(ingTimer);
  }, [fetchPresets, initWebSocket, viewRun]);

  if (activeView === "fleet-status") {
    return (
      <div className="h-screen w-screen flex flex-col bg-[#F4F7F9] text-slate-900 overflow-hidden font-sans">
        <DeepLinkNotice />
        <FloatStatusPage />
      </div>
    );
  }

  if (activeView === "results") {
    return (
      <div className="h-screen w-screen flex flex-col bg-[#F4F7F9] text-slate-900 overflow-hidden font-sans">
        <DeepLinkNotice />
        <ResultsWorkspace />
        {/* Modals available in workspace */}
        <RtqcModal />
        <CycleDetailModal />
        <OutputFilesModal />
        <RunHistoryModal />
      </div>
    );
  }

  return (
    <div className="h-screen w-screen flex flex-col bg-slate-50 text-slate-900 overflow-hidden font-sans">
      {/* 1. Top Navigation & Operational Action Bar */}
      <Header />

      {/* 2. Batch Progress Banner (when batch run is active or completed) */}
      <BatchProgressBanner />

      {/* 2b. Deep-link feedback (only visible when a linked run/event failed to resolve) */}
      <DeepLinkNotice />

      {/* 3. Main Three-Column Dashboard */}
      <div className="flex-1 flex overflow-hidden relative">
        {/* Left Column: Float / Input Context */}
        <LeftPanel />

        {/* Center Column: Live Processing Log */}
        <CenterPanel />

        {/* Right Column: Complete Decoder Pipeline Visualization */}
        <RightPanel />

        {/* Technical Event Details Drawer (Slide-out from Right) */}
        <EventDetailDrawer />
      </div>

      {/* 4. Deep-Dive Modals */}
      <RtqcModal />
      <CycleDetailModal />
      <OutputFilesModal />
      <FlowchartModal />
      <BatchResultsModal />
      <RunHistoryModal />
      <DecodeAllCompleteModal />
    </div>
  );
};

export default App;
