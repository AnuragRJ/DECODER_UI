import { describe, expect, it } from "vitest";
import type { FleetStatusPayload, FleetStatusRow } from "../types";
import {
  APPROX_PROFILES_MISSED_NOTE,
  applyFleetFilters,
  approxMissedNote,
  defaultSortRows,
  formatInterval,
  formatForwardTest,
  formatPredictionHorizon,
  formatPredictionRadius,
  predictionStatusLabel,
  formatCoord,
  formatDays,
  formatUTC,
  formatSyncInterval,
  fleetCacheIsStale,
  hasFleetPosition,
  paginateRows,
  sortFleetRows,
} from "./fleetStatus";

function row(over: Partial<FleetStatusRow> & { wmo: number }): FleetStatusRow {
  return {
    internal_id: null,
    ptt: null,
    imei: null,
    float_type: "APEX",
    transmission_type: "ARGOS",
    in_incois_dac: true,
    prof_num: null,
    profile_count: null,
    last_profile_juld: null,
    last_profile_index: null,
    last_profile_cycle: null,
    last_profile_file: "test_prof.nc",
    last_profile_field: "JULD",
    profile_date_error: null,
    profile_checked_at: null,
    approx_profiles_missed: null,
    lon: null,
    lat: null,
    pos_source: null,
    pos_qc: null,
    last_profile_iso: null,
    days_since_last_profile: null,
    expected_next_profile_iso: null,
    data_status: "NO DATA",
    traj_max_cycle: null,
    latest_profile: null,
    traj_last_fix: null,
    rtraj_mdtm: null,
    error: null,
    updated_at: null,
    ...over,
  };
}

describe("fleetStatus helpers", () => {
  it("default-sorts least recent profile state first", () => {
    const rows = [
      row({ wmo: 1, data_status: "ACTIVE / RECENT PROFILE", days_since_last_profile: 2 }),
      row({ wmo: 2, data_status: "NO RECENT PROFILE DATA 80+ DAYS", days_since_last_profile: 200 }),
      row({ wmo: 3, data_status: "PROFILE OVERDUE", days_since_last_profile: 30 }),
      row({ wmo: 4, data_status: "NO DATA" }),
    ];
    expect(defaultSortRows(rows).map((r) => r.wmo)).toEqual([2, 3, 4, 1]);
  });

  it("filters by query across WMO and identities", () => {
    const rows = [
      row({ wmo: 2901304, internal_id: "102525", ptt: "102525" }),
      row({ wmo: 6902892, internal_id: "589584", ptt: "589584", imei: "300234065895840" }),
    ];
    expect(applyFleetFilters(rows, { query: "2901", floatType: "", status: "" }).map((r) => r.wmo)).toEqual([2901304]);
    expect(applyFleetFilters(rows, { query: "589584", floatType: "", status: "" }).map((r) => r.wmo)).toEqual([6902892]);
    expect(applyFleetFilters(rows, { query: "30023406", floatType: "", status: "" }).map((r) => r.wmo)).toEqual([6902892]);
    expect(applyFleetFilters(rows, { query: "zzz", floatType: "", status: "" })).toEqual([]);
  });

  it("filters by float type and status", () => {
    const rows = [
      row({ wmo: 1, float_type: "APEX", data_status: "ACTIVE / RECENT PROFILE" }),
      row({ wmo: 2, float_type: "ARVOR", data_status: "PROFILE OVERDUE" }),
    ];
    expect(applyFleetFilters(rows, { query: "", floatType: "ARVOR", status: "" }).map((r) => r.wmo)).toEqual([2]);
    expect(applyFleetFilters(rows, { query: "", floatType: "", status: "ACTIVE / RECENT PROFILE" }).map((r) => r.wmo)).toEqual([1]);
  });

  it("sorts with nulls last in both directions", () => {
    const rows = [
      row({ wmo: 1, days_since_last_profile: 5 }),
      row({ wmo: 2, days_since_last_profile: null }),
      row({ wmo: 3, days_since_last_profile: 50 }),
    ];
    expect(sortFleetRows(rows, "days", "asc").map((r) => r.wmo)).toEqual([1, 3, 2]);
    expect(sortFleetRows(rows, "days", "desc").map((r) => r.wmo)).toEqual([3, 1, 2]);
  });

  it("sorts profile numbers and approximate missed-profile estimates", () => {
    const rows = [
      row({ wmo: 1, prof_num: 25, approx_profiles_missed: 1 }),
      row({ wmo: 2, prof_num: 244, approx_profiles_missed: 0 }),
      row({ wmo: 3, prof_num: null, approx_profiles_missed: null }),
    ];
    expect(sortFleetRows(rows, "prof", "desc").map((r) => r.wmo)).toEqual([2, 1, 3]);
    expect(sortFleetRows(rows, "missed", "desc").map((r) => r.wmo)).toEqual([1, 2, 3]);
  });

  it("paginates and clamps pages", () => {
    const rows = [1, 2, 3, 4, 5];
    expect(paginateRows(rows, 2, 2)).toEqual({ pageRows: [3, 4], totalPages: 3, safePage: 2 });
    expect(paginateRows(rows, 99, 2).safePage).toBe(3);
    expect(paginateRows([], 1, 20)).toEqual({ pageRows: [], totalPages: 1, safePage: 1 });
  });

  it("formats days, UTC timestamps and coordinates", () => {
    expect(formatDays(3.7)).toBe("3 d");
    expect(formatDays(null)).toBe("—");
    expect(formatUTC("2026-09-08T14:04:11+00:00")).toBe("2026-09-08 14:04 UTC");
    expect(formatUTC(null)).toBe("—");
    expect(formatUTC("bogus")).toBe("—");
    expect(formatCoord(66.0, "lon")).toBe("66.000°E");
    expect(formatCoord(-7.5, "lat")).toBe("7.500°S");
    expect(formatCoord(null, "lon")).toBe("—");
  });
});


describe("Float Status correctness guards", () => {
  const asOf = Date.parse("2026-09-21T00:00:00Z");
  const payload = (over: Partial<FleetStatusPayload["sync"]> = {}): FleetStatusPayload => ({
    generated_at: "2026-09-21T00:00:00Z",
    floats: [],
    source: { host: "ftp.ifremer.fr", port: 21, root: "/ifremer/argo", dac: "incois", product: "dac/incois/<wmo>/<wmo>_prof.nc", field: "JULD", monitoring: "profile-recency", expected_profile_interval_days: 10, approximation_note: "Approximate estimate based on the expected 10-day profile cycle.", interval_s: 21600 },
    summary: { total: 0, recent_profile: 0, profile_overdue: 0, no_recent_profile_80: 0, no_recent_profile_60: 0, no_data: 0, approx_profiles_missed_total: null, profile_dates_known: 0, total_profiles: 0 },
    sync: { status: "ok", running: false, progress: { done: 0, total: 0 }, last_attempt_at: null,
      last_success_at: "2026-09-20T23:00:00Z", interval_s: 21600, error: null, counts: {}, ...over },
  });

  it("expires old success even when status still says ok or disabled", () => {
    for (const status of ["ok", "disabled"] as const) {
      expect(fleetCacheIsStale(payload({ status, last_success_at: "2026-09-20T00:00:00Z" }), asOf)).toBe(true);
    }
    expect(fleetCacheIsStale(payload(), asOf)).toBe(false);
  });

  it("marks a frozen API payload stale without changing its status badges", () => {
    const p = payload();
    p.floats = [row({ wmo: 2902223, data_status: "ACTIVE / RECENT PROFILE" })];
    expect(fleetCacheIsStale(p, asOf + 121000)).toBe(true);
    expect(p.floats[0].data_status).toBe("ACTIVE / RECENT PROFILE");
  });

  it("honours server row-validation freshness and incomplete-sync states", () => {
    expect(fleetCacheIsStale(payload({ stale: true }), asOf)).toBe(true);
    expect(fleetCacheIsStale(payload({ status: "degraded" }), asOf)).toBe(true);
    expect(fleetCacheIsStale(payload({ last_success_at: null }), asOf)).toBe(true);
    expect(fleetCacheIsStale(null, asOf)).toBe(false);
  });

  it("never formats NaN, infinity or invalid coordinates as observations", () => {
    for (const n of [NaN, Infinity, -Infinity]) {
      expect(formatDays(n)).toBe("—");
      expect(formatCoord(n, "lon")).toBe("—");
    }
    expect(formatDays(-0.5)).toBe("—");
    expect(formatCoord(91, "lat")).toBe("—");
    expect(formatCoord(-181, "lon")).toBe("—");
    expect(formatCoord(0, "lat")).toBe("0.000°N");
  });

  it("keeps unrounded elapsed days below a whole-day boundary", () => {
    expect(formatDays(59.999999)).toBe("59 d");
    expect(formatDays(10.000001)).toBe("10 d");
  });

  it("UTC formatting is independent of client timezone and explicit offsets", () => {
    expect(formatUTC("2026-09-21T05:30:00+05:30")).toBe("2026-09-21 00:00 UTC");
    expect(formatUTC("2026-09-20T17:00:00-07:00")).toBe("2026-09-21 00:00 UTC");
  });

  it("uses one valid paired coordinate predicate for table/map data", () => {
    expect(hasFleetPosition({ lat: 0, lon: 0 })).toBe(true);
    expect(hasFleetPosition({ lat: -45.719, lon: 8.043 })).toBe(true);
    expect(hasFleetPosition({ lat: null, lon: 8.043 })).toBe(false);
    expect(hasFleetPosition({ lat: 92, lon: 8.043 })).toBe(false);
    expect(hasFleetPosition({ lat: 12, lon: Infinity })).toBe(false);
  });

  it("sorts malformed/missing dates last in both directions", () => {
    const r = [row({ wmo: 1, last_profile_iso: "bad" }), row({ wmo: 2, last_profile_iso: "2026-09-20T00:00:00Z" })];
    expect(sortFleetRows(r, "last_profile", "asc").map(x => x.wmo)).toEqual([2, 1]);
    expect(sortFleetRows(r, "last_profile", "desc").map(x => x.wmo)).toEqual([2, 1]);
  });
});

it("labels the effective synchronization cadence in correct units", () => {
  expect(formatSyncInterval(21600)).toBe("6 h");
  expect(formatSyncInterval(300)).toBe("5 min");
  expect(formatSyncInterval(900)).toBe("15 min");
  expect(formatSyncInterval(null)).toBe("—");
});

describe("observed cycle interval presentation", () => {
  it("derives the missed-profile note from the float's own observed cycle", () => {
    expect(
      approxMissedNote({
        expected_interval_days: 9.98,
        expected_interval_source: "profile history",
        expected_interval_samples: 96,
      })
    ).toBe(
      "Approximate estimate based on the observed 10.0-day profile cycle (median of 96 published profile dates)."
    );
    expect(
      approxMissedNote({
        expected_interval_days: 5.0,
        expected_interval_source: "trajectory history",
        expected_interval_samples: 7,
      })
    ).toContain("observed 5.0-day profile cycle (median of 7 trajectory cycles)");
  });

  it("falls back to the documented 10-day wording when no history exists", () => {
    expect(approxMissedNote({})).toBe(APPROX_PROFILES_MISSED_NOTE);
    expect(
      approxMissedNote({
        expected_interval_days: 10,
        expected_interval_source: "default 10-day cycle",
        expected_interval_samples: 0,
      })
    ).toBe(APPROX_PROFILES_MISSED_NOTE);
  });

  it("formats the drawer interval with its provenance", () => {
    expect(
      formatInterval({
        expected_interval_days: 9.98,
        expected_interval_source: "profile history",
        expected_interval_samples: 96,
      })
    ).toBe("9.98 d (profile history, 96 intervals)");
    expect(formatInterval({ expected_interval_days: 10, expected_interval_source: "default 10-day cycle" }))
      .toBe("10.00 d (default 10-day cycle)");
    expect(formatInterval({})).toBe("—");
  });
});

describe("prediction presentation", () => {
  it("maps server statuses to honest badges", () => {
    expect(predictionStatusLabel("ok")).toBe("AVAILABLE");
    expect(predictionStatusLabel("insufficient_data")).toBe("INSUFFICIENT DATA");
    expect(predictionStatusLabel("insufficient_validation")).toBe("NOT VALIDATED");
    expect(predictionStatusLabel("source_unavailable")).toBe("SOURCE UNAVAILABLE");
    expect(predictionStatusLabel(null)).toBe("UNAVAILABLE");
  });

  it("never renders a radius that the backend did not provide", () => {
    expect(formatPredictionRadius(24.1, 88.4)).toBe("24.1 km (50%) / 88.4 km (90%)");
    expect(formatPredictionRadius(null, 88.4)).toBe("—");
    expect(formatPredictionRadius(24.1, null)).toBe("—");
    expect(formatPredictionRadius(undefined, undefined)).toBe("—");
  });

  it("formats the prediction horizon", () => {
    expect(formatPredictionHorizon(10)).toBe("+10.00 d");
    expect(formatPredictionHorizon(5.02)).toBe("+5.02 d");
    expect(formatPredictionHorizon(null)).toBe("—");
    expect(formatPredictionHorizon(0)).toBe("—");
  });
});

describe("forward-test presentation", () => {
  it("reports only what the audit measured", () => {
    expect(
      formatForwardTest({
        n: 5,
        median_km: 31.24,
        p90_km: 88.1,
        within_r50_pct: 60,
        within_r90_pct: 100,
        median_time_error_days: 0.02,
      })
    ).toBe("5 scored · median 31.24 km · p90 88.1 km · 60% within r50 / 100% within r90 · time error 0.02 d");
    expect(formatForwardTest({ n: 2, median_km: 44.0 })).toBe("2 scored · median 44 km");
  });

  it("never implies an audit that has not happened", () => {
    expect(formatForwardTest(null)).toBe("—");
    expect(formatForwardTest(undefined)).toBe("—");
    expect(formatForwardTest({ n: 0 })).toBe("—");
  });
});
