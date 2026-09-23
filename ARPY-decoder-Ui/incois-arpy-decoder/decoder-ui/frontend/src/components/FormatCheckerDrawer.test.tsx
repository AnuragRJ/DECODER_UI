import { describe, expect, it, vi } from "vitest";
import React from "react";
import { renderToString } from "react-dom/server";
import FormatCheckerDrawer from "./FormatCheckerDrawer";
import { shouldUpdateFormatCheckerSummary } from "./ResultsWorkspace";
import type { FormatCheckerDetail, FormatCheckerSummary } from "../types";

describe("FormatCheckerDrawer & ResultsWorkspace - View Stability Regressions", () => {
  const sampleSummary: FormatCheckerSummary = {
    status: "accepted",
    accepted_files: 14,
    rejected_files: 0,
    total_files: 14,
    total_errors: 0,
    total_warnings: 0,
    checked_at: "2026-09-22T12:00:00Z",
  };

  describe("shouldUpdateFormatCheckerSummary (loop breaker)", () => {
    it("returns true when no current result exists", () => {
      expect(shouldUpdateFormatCheckerSummary(undefined, sampleSummary)).toBe(true);
    });

    it("returns false when current and next summary are identical (prevents re-render cascades)", () => {
      const clone = { ...sampleSummary };
      expect(shouldUpdateFormatCheckerSummary(sampleSummary, clone)).toBe(false);
    });

    it("returns true when status changes", () => {
      const updated: FormatCheckerSummary = { ...sampleSummary, status: "rejected", rejected_files: 2 };
      expect(shouldUpdateFormatCheckerSummary(sampleSummary, updated)).toBe(true);
    });

    it("returns true when file count changes", () => {
      const updated: FormatCheckerSummary = { ...sampleSummary, total_files: 15, accepted_files: 15 };
      expect(shouldUpdateFormatCheckerSummary(sampleSummary, updated)).toBe(true);
    });

    it("returns true when error count changes", () => {
      const updated: FormatCheckerSummary = { ...sampleSummary, total_errors: 1 };
      expect(shouldUpdateFormatCheckerSummary(sampleSummary, updated)).toBe(true);
    });

    it("returns true when checked_at timestamp advances", () => {
      const updated: FormatCheckerSummary = { ...sampleSummary, checked_at: "2026-09-22T13:00:00Z" };
      expect(shouldUpdateFormatCheckerSummary(sampleSummary, updated)).toBe(true);
    });
  });

  function textOf(html: string): string {
    return html.replace(/<!-- -->/g, "");
  }

  describe("FormatCheckerDrawer presentation contract", () => {
    it("renders nothing when closed (open = false)", () => {
      const html = renderToString(
        <FormatCheckerDrawer
          wmo={2901304}
          open={false}
          onClose={() => undefined}
          onResultChange={() => undefined}
        />
      );
      expect(html).toBe("");
    });

    it("renders drawer shell and WMO header steadily when open", () => {
      const html = renderToString(
        <FormatCheckerDrawer
          wmo={2901304}
          open={true}
          onClose={() => undefined}
          onResultChange={() => undefined}
        />
      );
      const text = textOf(html);
      expect(text).toContain("Argo Format Checker");
      expect(text).toContain("WMO 2901304");
      expect(text).toContain("DAC INCOIS");
      expect(text).toContain("Run Check");
    });

    it("does not crash or throw when re-rendered with new callback references", () => {
      const onClose1 = vi.fn();
      const onClose2 = vi.fn();
      const onChange1 = vi.fn();
      const onChange2 = vi.fn();

      const html1 = renderToString(
        <FormatCheckerDrawer
          wmo={2901304}
          open={true}
          onClose={onClose1}
          onResultChange={onChange1}
        />
      );

      // Simulating a parent re-render with fresh callback instances
      const html2 = renderToString(
        <FormatCheckerDrawer
          wmo={2901304}
          open={true}
          onClose={onClose2}
          onResultChange={onChange2}
        />
      );

      expect(html1).toBe(html2);
      expect(textOf(html2)).toContain("WMO 2901304");
    });
  });
});
