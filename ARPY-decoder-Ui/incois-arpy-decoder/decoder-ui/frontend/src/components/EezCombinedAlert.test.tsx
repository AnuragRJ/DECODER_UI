import { describe, expect, it } from "vitest";
import React from "react";
import { renderToString } from "react-dom/server";
import { useDecoderStore } from "../store/useDecoderStore";
import { EezCombinedAlert } from "./EezCombinedAlert";

/**
 * Component contract for the ONE combined CURRENT-STATE EEZ alert:
 *  - normal compact view (expanded=false) renders NOTHING — even with floats inside;
 *  - Indian EEZ toggle OFF (layerOn=false) renders NOTHING — even when expanded;
 *  - expanded view + layer ON renders EXACTLY ONE panel listing
 *    currently-inside WMOs, anchored bottom-left of the map;
 *  - NO cycle numbers, NO C100 → C101 pairs, NO historical Entry/Exit content;
 *  - duplicate WMOs collapse to one row; long lists cap with an overflow line;
 *  - zero inside → no alert; dismiss snapshots the inside set but keeps
 *    classification/history; a newly-inside WMO re-surfaces the panel;
 *  - uses neutral scientific wording only.
 *
 * NOTE: derived state is injected via props (the component's documented test
 * seam) because React 19 SSR snapshots zustand's initial state. The live app
 * omits the overrides and subscribes to the store; the dismissal tests below
 * still drive the REAL store action and then render the resulting state.
 */
const THREE = [2901304, 2901305, 2901307];

function render(
  expanded: boolean,
  over: { insideWmos?: number[]; dismissed?: Record<string, true>; layerOn?: boolean } = {}
): string {
  return renderToString(
    React.createElement(EezCombinedAlert, {
      expanded,
      insideWmos: over.insideWmos ?? THREE,
      dismissed: over.dismissed ?? {},
      layerOn: over.layerOn ?? true,
    })
  );
}

function countPanels(html: string): number {
  return (html.match(/data-testid="eez-combined-alert"/g) || []).length;
}

/** React SSR inserts `<!-- -->` between JSX text/expression boundaries; the
 *  browser textContent reads through them, so strip them for text assertions. */
function textOf(html: string): string {
  return html.replace(/<!-- -->/g, "");
}

describe("EezCombinedAlert visibility", () => {
  it("normal compact view renders NOTHING even when floats are inside", () => {
    expect(render(false)).toBe("");
  });

  it("expanded view with ZERO inside renders nothing", () => {
    expect(render(true, { insideWmos: [] })).toBe("");
  });

  it("toggle OFF renders NOTHING even when expanded with floats inside", () => {
    expect(render(true, { layerOn: false })).toBe("");
    expect(render(false, { layerOn: false })).toBe("");
  });

  it("panel is anchored bottom-left of the map", () => {
    const html = render(true);
    expect(html).toContain('data-testid="eez-combined-alert-wrap"');
    expect(html).toContain("bottom-3 left-3");
    expect(html).not.toContain("right-3");
  });

  it("panel fades smoothly (entrance keyframes + opacity transition, settled visible in SSR)", () => {
    const html = render(true);
    expect(html).toContain("eez-fade-in");
    expect(html).toContain("transition:opacity 300ms ease-in-out");
    expect(html).toContain("opacity:1");
  });

  it("expanded view renders EXACTLY ONE panel for several inside floats", () => {
    const html = render(true);
    expect(countPanels(html)).toBe(1);
    expect(html).toContain("Indian EEZ Alert");
    expect(html).toContain('role="alert"');
    expect(textOf(html)).toContain("3 floats currently inside EEZ");
    // every WMO appears exactly once as a compact row
    for (const wmo of THREE) {
      expect(html.split(`data-wmo="${wmo}"`).length - 1).toBe(1);
    }
    expect(textOf(html)).toContain("WMO 2901304");
    // restrained red operational family + reference disclaimer
    expect(html).toContain("border-red-400/40");
    expect(html).toContain("bg-[#230d12]/95");
    expect(html).toContain("text-red-300");
    expect(html).toContain("not official INCOIS");
  });

  it("singular phrasing for exactly one inside float", () => {
    const html = render(true, { insideWmos: [2901304] });
    expect(countPanels(html)).toBe(1);
    expect(textOf(html)).toContain("1 float currently inside EEZ");
  });

  it("contains NO cycle or historical-event content whatsoever", () => {
    const html = render(true);
    expect(textOf(html)).not.toMatch(/C\d+\s*→\s*C\d+/);
    expect(textOf(html)).not.toMatch(/cycle/i);
    expect(textOf(html)).not.toMatch(/entry|exit/i);
    expect(textOf(html)).not.toMatch(/juld/i);
    expect(html).not.toContain("data-eez-id");
  });

  it("collapses duplicate WMOs to one row each", () => {
    const html = render(true, { insideWmos: [2901304, 2901304, 2901305, 2901304, 2901305] });
    expect(countPanels(html)).toBe(1);
    expect((html.match(/data-testid="eez-alert-row"/g) || []).length).toBe(2);
    expect(textOf(html)).toContain("2 floats currently inside EEZ");
  });

  it("caps long lists instead of flooding the screen", () => {
    const many = Array.from({ length: 9 }, (_, i) => 2901300 + i);
    const html = render(true, { insideWmos: many });
    expect(countPanels(html)).toBe(1);
    expect((html.match(/data-testid="eez-alert-row"/g) || []).length).toBe(6);
    expect(textOf(html)).toContain("+3 more");
  });

  it("uses neutral scientific wording only", () => {
    const html = render(true);
    expect(html).not.toMatch(/illegal|violation|unauthorized|intrusion|breach/i);
  });
});

describe("EezCombinedAlert dismissal (real store action)", () => {
  function seedStore(inside: number[], outside: number[] = []) {
    const eezByWmo: Record<number, Array<{ cycle: number; lat: number; lon: number; eezStatus: "INDIAN_EEZ" | "OUTSIDE_INDIAN_EEZ" }>> = {};
    for (const w of inside) {
      eezByWmo[w] = [{ cycle: 71, lat: 18.236, lon: 69.731, eezStatus: "INDIAN_EEZ" }];
    }
    for (const w of outside) {
      eezByWmo[w] = [{ cycle: 12, lat: -59.9, lon: 69.366, eezStatus: "OUTSIDE_INDIAN_EEZ" }];
    }
    useDecoderStore.setState({ eezByWmo, eezDismissed: {}, eezTransitions: [] });
  }

  it("dismiss-all snapshots the inside set; classification stays intact; re-render cannot resurrect", () => {
    seedStore([2901304, 2901305], [2901306]);
    const before = useDecoderStore.getState();
    expect(before.eezByWmo[2901304][0].eezStatus).toBe("INDIAN_EEZ");
    useDecoderStore.getState().dismissAllEezNotices();
    const after = useDecoderStore.getState();
    // inside WMOs dismissed, outside WMO untouched, classification intact
    expect(after.eezDismissed["inside|2901304"]).toBe(true);
    expect(after.eezDismissed["inside|2901305"]).toBe(true);
    expect(after.eezDismissed["inside|2901306"]).toBeUndefined();
    expect(after.eezByWmo[2901304][0].eezStatus).toBe("INDIAN_EEZ");
    expect(render(true, { insideWmos: [2901304, 2901305], dismissed: after.eezDismissed })).toBe("");
    expect(render(false, { insideWmos: [2901304, 2901305], dismissed: after.eezDismissed })).toBe("");
  });

  it("a newly-inside WMO re-surfaces the single alert", () => {
    seedStore([2901304]);
    useDecoderStore.getState().dismissAllEezNotices();
    const s = useDecoderStore.getState();
    expect(render(true, { insideWmos: [2901304], dismissed: s.eezDismissed })).toBe("");
    const html = render(true, { insideWmos: [2901304, 2901311], dismissed: s.eezDismissed });
    expect(countPanels(html)).toBe(1);
    expect(textOf(html)).toContain("1 float currently inside EEZ");
    expect(html).toContain('data-wmo="2901311"');
    expect(html).not.toContain('data-wmo="2901304"');
  });
});
