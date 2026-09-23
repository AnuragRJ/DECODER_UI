import { describe, expect, it } from "vitest";
import {
  MIN_EXPANDED_MAP_HEIGHT,
  MIN_EXPANDED_PANEL_HEIGHT,
  calculateClampedPanelHeight,
} from "./ResultsWorkspace";

describe("ResultsWorkspace - Floating Fleet Panel Drag Behavior", () => {
  const containerH = 900; // Typical viewport height minus header

  it("increases panel height when dragged upward (deltaY < 0)", () => {
    const initialH = 340;
    const deltaY = -120; // mouse moved up by 120px
    const result = calculateClampedPanelHeight(initialH, deltaY, containerH);
    expect(result).toBe(460);
    expect(result).toBeGreaterThan(initialH);
  });

  it("decreases panel height when dragged downward (deltaY > 0)", () => {
    const initialH = 460;
    const deltaY = 160; // mouse moved down by 160px
    const result = calculateClampedPanelHeight(initialH, deltaY, containerH);
    expect(result).toBe(300);
    expect(result).toBeLessThan(initialH);
  });

  it("clamps to MIN_EXPANDED_PANEL_HEIGHT when dragged too far down", () => {
    const initialH = 340;
    const deltaY = 300; // attempted to shrink to 40px
    const result = calculateClampedPanelHeight(initialH, deltaY, containerH);
    expect(result).toBe(MIN_EXPANDED_PANEL_HEIGHT);
    expect(result).toBe(180);
  });

  it("clamps to (containerHeight - MIN_EXPANDED_MAP_HEIGHT) when dragged too far up", () => {
    const initialH = 340;
    const deltaY = -800; // attempted to expand to 1140px
    const result = calculateClampedPanelHeight(initialH, deltaY, containerH);
    const maxExpected = containerH - MIN_EXPANDED_MAP_HEIGHT; // 900 - 160 = 740
    expect(result).toBe(maxExpected);
    expect(result).toBe(740);
  });

  it("preserves stable position when delta is 0 (interaction without dragging)", () => {
    const userSetHeight = 520;
    const result = calculateClampedPanelHeight(userSetHeight, 0, containerH);
    expect(result).toBe(userSetHeight);
  });

  it("guarantees minimum map clearance even on small viewports", () => {
    const smallContainerH = 300;
    const result = calculateClampedPanelHeight(200, -200, smallContainerH);
    // Even if clamped, it never shrinks below MIN_EXPANDED_PANEL_HEIGHT
    expect(result).toBe(MIN_EXPANDED_PANEL_HEIGHT);
  });
});
