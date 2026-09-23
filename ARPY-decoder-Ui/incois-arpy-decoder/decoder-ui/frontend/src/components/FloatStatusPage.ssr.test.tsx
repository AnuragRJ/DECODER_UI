import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { FleetStatusPayload, FleetStatusRow } from "../types";
import { APPROX_PROFILES_MISSED_NOTE } from "../utils/fleetStatus";

// Presentation-only fixture. No network or operational cache is modified.
const state = vi.hoisted(() => ({ payload: null as FleetStatusPayload | null }));
vi.mock("../store/useDecoderStore", () => ({ useDecoderStore: () => ({ setActiveView: vi.fn() }) }));
vi.mock("../store/useFleetStatusStore", () => ({
  useFleetStatusStore: () => ({ payload: state.payload, loading: false, fetchError: null,
    syncStarting: false, fetchFleetStatus: vi.fn(), triggerSync: vi.fn() }),
  startFleetStatusPolling: vi.fn(), stopFleetStatusPolling: vi.fn(),
}));
vi.mock("./FleetOceanMap", () => ({ default: ({ positions }: { positions: unknown }) =>
  <div data-testid="map-input" data-positions={JSON.stringify(positions)} />,
}));
import FloatStatusPage from "./FloatStatusPage";

const sample: FleetStatusRow = {
  wmo: 2909999, internal_id: null, ptt: null, imei: null,
  float_type: "APEX", transmission_type: "ARGOS", in_incois_dac: true,
  prof_num: 25, profile_count: 24, lat: -45.719, lon: 8.043,
  pos_source: "traj", pos_qc: "1", position_file: "2909999_Rtraj.nc",
  last_profile_iso: "2026-09-08T12:00:00Z", last_profile_juld: 28009.5,
  last_profile_index: 23, last_profile_cycle: 25, last_profile_file: "2909999_prof.nc",
  last_profile_field: "JULD", profile_date_error: null, profile_checked_at: "2026-09-21T12:00:00Z",
  expected_next_profile_iso: "2026-09-18T12:00:00Z", days_since_last_profile: 13,
  approx_profiles_missed: 1, data_status: "PROFILE OVERDUE", traj_max_cycle: null,
  latest_profile: null, traj_last_fix: null, rtraj_mdtm: null, error: null, updated_at: null,
};

function payload(row = sample): FleetStatusPayload {
  return {
    generated_at: "2026-09-21T12:00:00Z", floats: [row],
    summary: { total: 1, recent_profile: 0, profile_overdue: 1, no_recent_profile_80: 0, no_recent_profile_60: 0,
      no_data: 0, approx_profiles_missed_total: 1, profile_dates_known: 1, total_profiles: 24 },
    source: { host: "ftp.ifremer.fr", port: 21, root: "/ifremer/argo", dac: "incois",
      monitoring: "profile-recency", product: "dac/incois/<wmo>/<wmo>_prof.nc",
      field: "JULD", expected_profile_interval_days: 10, approximation_note: APPROX_PROFILES_MISSED_NOTE,
      interval_s: 21600 },
    sync: { status: "ok", running: false, progress: { done: 1, total: 1 },
      last_attempt_at: "2026-09-21T12:00:00Z", last_success_at: "2026-09-21T12:00:00Z",
      interval_s: 21600, error: null, counts: {} },
  };
}

describe("Float Status profile-recency presentation", () => {
  beforeEach(() => { state.payload = payload(); });

  it("uses the requested profile terminology, not the previous telecom labels", () => {
    const html = renderToStaticMarkup(<FloatStatusPage />);
    expect(html).toContain("Last Profile Date");
    expect(html).toContain("Days Since Last Profile");
    expect(html).toContain("Approx. Profiles Missed");
    expect(html).toContain("Data Status");
    expect(html).toContain("PROFILE OVERDUE");
    expect(html).toContain("Expected Next Profile 2026-09-18 12:00 UTC");
    expect(html).not.toMatch(/Last Communication|Last Transmission|No Transmission|No Communication|\bDead\b/i);
    expect(html).not.toContain("# Profs Missing");
  });

  it("exposes the exact approximation note and the prof.nc source", () => {
    const html = renderToStaticMarkup(<FloatStatusPage />);
    expect(html).toContain(APPROX_PROFILES_MISSED_NOTE);
    expect(html).toContain("2909999_prof.nc · JULD");
    expect(html).toContain('data-field="approx_profiles_missed"');
    expect(html).toContain('data-field="prof_num"');
  });

  it("does not turn missing dates or estimates into zero", () => {
    state.payload = payload({ ...sample, data_status: "NO DATA", last_profile_iso: null,
      last_profile_juld: null, expected_next_profile_iso: null, days_since_last_profile: null,
      approx_profiles_missed: null });
    const html = renderToStaticMarkup(<FloatStatusPage />);
    for (const field of ["last_profile_iso", "days_since_last_profile", "approx_profiles_missed"]) {
      const cell = html.match(new RegExp(`data-field="${field}"[^>]*>([\\s\\S]*?)</td>`))?.[1];
      expect(cell).toContain("—");
      expect(cell).not.toContain(">0<");
    }
  });

  it("keeps the same verified map coordinates and passes data status", () => {
    const html = renderToStaticMarkup(<FloatStatusPage />);
    expect(html).toContain('&quot;lat&quot;:-45.719');
    expect(html).toContain('&quot;lon&quot;:8.043');
    expect(html).toContain('&quot;status&quot;:&quot;PROFILE OVERDUE&quot;');
    expect(html).toContain("45.719°S");
    expect(html).toContain("8.043°E");
  });
});
