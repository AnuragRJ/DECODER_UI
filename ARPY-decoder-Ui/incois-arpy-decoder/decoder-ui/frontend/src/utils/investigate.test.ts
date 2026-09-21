import { describe, expect, it } from "vitest";
import {
  buildProcessingTimeline,
  primaryError,
  primaryErrorSuffix,
  timelineStepForStage,
} from "./investigate";

describe("primaryError", () => {
  it("returns the latest error and counts the rest", () => {
    expect(primaryError(["first failed", "second failed"])).toEqual({
      text: "second failed",
      extra: 1,
    });
  });

  it("returns a single error with no remainder", () => {
    expect(primaryError(["only failure"])).toEqual({ text: "only failure", extra: 0 });
  });

  it("skips blank entries when picking the latest meaningful error", () => {
    expect(primaryError(["first failed", "   ", ""])).toEqual({
      text: "first failed",
      extra: 0,
    });
  });

  it("returns empty for missing or all-blank errors", () => {
    expect(primaryError(undefined)).toEqual({ text: "", extra: 0 });
    expect(primaryError(null)).toEqual({ text: "", extra: 0 });
    expect(primaryError([])).toEqual({ text: "", extra: 0 });
    expect(primaryError(["  ", ""])).toEqual({ text: "", extra: 0 });
  });
});

describe("primaryErrorSuffix", () => {
  it("renders nothing for zero and (+N more) otherwise", () => {
    expect(primaryErrorSuffix(0)).toBe("");
    expect(primaryErrorSuffix(1)).toBe(" (+1 more)");
    expect(primaryErrorSuffix(3)).toBe(" (+3 more)");
  });
});

describe("buildProcessingTimeline", () => {
  const completed = { status: "completed", detail: "" };
  const pending = { status: "pending", detail: "" };

  it("always returns the seven fixed steps in order", () => {
    const steps = buildProcessingTimeline({});
    expect(steps.map((s) => s.label)).toEqual([
      "Input",
      "Discovery",
      "Metadata / Staging",
      "Decoder",
      "NetCDF",
      "RTQC",
      "Output",
    ]);
    expect(steps.every((s) => s.status === "not-reached")).toBe(true);
  });

  it("marks reached steps completed, the failed stage failed, the rest not-reached", () => {
    const steps = buildProcessingTimeline({
      CONFIGURATION: completed,
      INPUT_DISCOVERY: completed,
      INPUT_PREPARATION: completed,
      METADATA: { status: "error", detail: "staged CTS4 files missing" },
      DECODER: pending,
      PRODUCT_BUILDING: pending,
      RTQC: pending,
      OUTPUT_HANDLING: pending,
      DONE: pending,
    });
    const byKey = Object.fromEntries(steps.map((s) => [s.key, s]));
    expect(byKey.input.status).toBe("completed");
    expect(byKey.discovery.status).toBe("completed");
    expect(byKey.metadata.status).toBe("failed");
    expect(byKey.metadata.detail).toBe("staged CTS4 files missing");
    expect(byKey.decoder.status).toBe("not-reached");
    expect(byKey.netcdf.status).toBe("not-reached");
    expect(byKey.rtqc.status).toBe("not-reached");
    expect(byKey.output.status).toBe("not-reached");
  });

  it("treats DONE completed as an Output completed and stays case-insensitive", () => {
    const steps = buildProcessingTimeline({
      output_handling: completed,
      done: completed,
    });
    expect(steps.find((s) => s.key === "output")?.status).toBe("completed");
  });

  it("ignores unknown stage keys instead of inventing failures", () => {
    const steps = buildProcessingTimeline({ SOMEDAY_STAGE: { status: "error", detail: "x" } });
    expect(steps.every((s) => s.status === "not-reached")).toBe(true);
  });
});

describe("timelineStepForStage", () => {
  it("maps raw stage ids to timeline cards and returns null for unknowns", () => {
    expect(timelineStepForStage("DECODER")).toBe("decoder");
    expect(timelineStepForStage("metadata")).toBe("metadata");
    expect(timelineStepForStage("DONE")).toBe("output");
    expect(timelineStepForStage("NOPE")).toBeNull();
    expect(timelineStepForStage(null)).toBeNull();
  });
});
