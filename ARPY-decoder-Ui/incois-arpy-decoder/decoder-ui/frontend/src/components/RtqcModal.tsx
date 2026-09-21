import React, { useState } from "react";
import { X, Zap, ShieldCheck, FileCode, Check } from "lucide-react";
import { useDecoderStore } from "../store/useDecoderStore";
import { RtqcPass } from "../types";

const RTQC_REFERENCE_TESTS: Record<
  RtqcPass,
  Array<{
    id: string;
    num: number;
    name: string;
    rule: string;
    pyfile: string;
    pyfunc: string;
    desc: string;
  }>
> = {
  PASS_A: [
    {
      id: "TEST019",
      num: 19,
      name: "Deepest Pressure Check",
      rule: "limit = CONFIG_ProfilePressure + max(10%, 100 dbar)",
      pyfile: "argo_decoder/rtqc/non_density.py",
      pyfunc: "test_deepest_pressure",
      desc: "Flag 3 if profile pressure exceeds target profile pressure + 10% tolerance (APEX floats).",
    },
    {
      id: "TEST006_PRES",
      num: 6,
      name: "Global Range Check (PRES)",
      rule: "PRES in (-5.0, 12000.0) dbar",
      pyfile: "argo_decoder/rtqc/non_density.py",
      pyfunc: "test_global_range",
      desc: "Flags NaN, fills, or unphysical ocean pressures as Flag 4.",
    },
    {
      id: "TEST006_BAND",
      num: 6,
      name: "Pressure Band Check",
      rule: "p < -5 -> 4; -5 <= p <= -2.4 -> 3",
      pyfile: "argo_decoder/rtqc/non_density.py",
      pyfunc: "test_pressure_band",
      desc: "Near-surface atmospheric pressure sensor noise and offset checks.",
    },
    {
      id: "TEST008",
      num: 8,
      name: "Pressure Increasing Check",
      rule: "p[k] >= p[k-1] - 2.0 dbar",
      pyfile: "argo_decoder/rtqc/non_density.py",
      pyfunc: "test_pressure_increasing",
      desc: "Ensures ascending profile levels increase monotonically. Non-monotonic samples flagged 4.",
    },
    {
      id: "TEST006_TEMP_PSAL",
      num: 6,
      name: "Global Range (TEMP / PSAL / CNDC)",
      rule: "TEMP: (-2.5, 42.0)°C, PSAL: (2.0, 41.0) psu, CNDC: (0.0, 8.5) S/m",
      pyfile: "argo_decoder/rtqc/non_density.py",
      pyfunc: "test_global_range",
      desc: "Physical plausibility bounds for in-situ ocean temperature, practical salinity, and conductivity.",
    },
    {
      id: "TEST009",
      num: 9,
      name: "Spike Check",
      rule: "|v - median(v[k-2..k+2])| > 6.0°C (TEMP) / 0.5 (PSAL)",
      pyfile: "argo_decoder/rtqc/non_density.py",
      pyfunc: "test_spike",
      desc: "Calculates 5-point median residual window; deviations beyond threshold flagged 3.",
    },
    {
      id: "TEST011",
      num: 11,
      name: "Gradient Check",
      rule: "|Δv| / Δp > 9.0°C/dbar (TEMP) / 1.0 psu/dbar (PSAL)",
      pyfile: "argo_decoder/rtqc/non_density.py",
      pyfunc: "test_gradient",
      desc: "Flags extreme vertical gradients between consecutive measurement levels.",
    },
    {
      id: "TEST012",
      num: 12,
      name: "Digit Rollover Check",
      rule: "|Δv| > 10.0°C (TEMP) / 5.0 psu (PSAL)",
      pyfile: "argo_decoder/rtqc/non_density.py",
      pyfunc: "test_digit_rollover",
      desc: "Identifies telemetry byte counter jumps and bit-flips in raw bitstream.",
    },
    {
      id: "TEST013",
      num: 13,
      name: "Stuck Value Check",
      rule: "All valid levels identical (4 decimal places)",
      pyfile: "argo_decoder/rtqc/non_density.py",
      pyfunc: "test_stuck_value",
      desc: "Flags entire profile as 4 if sensor repeats constant value throughout water column.",
    },
  ],
  PASS_B: [
    {
      id: "TEST014",
      num: 14,
      name: "Density Inversion Check (TEOS-10)",
      rule: "σ_shallow - σ_deep >= 0.03 kg/m³",
      pyfile: "argo_decoder/rtqc/density_inversion.py",
      pyfunc: "run_density_inversion_test",
      desc: "Evaluates potential density anomaly via GSW (Gibbs SeaWater). Inversions where lighter water sits below denser water flagged 4.",
    },
  ],
  PASS_C: [
    {
      id: "TEST001",
      num: 1,
      name: "Platform Identification Check",
      rule: "WMO registered in database and metadata registry",
      pyfile: "argo_decoder/rtqc/profile_scalar.py",
      pyfunc: "test_platform_identification",
      desc: "Verifies platform WMO matches institutional registry and header metadata.",
    },
    {
      id: "TEST002",
      num: 2,
      name: "Impossible Date Check",
      rule: "JULD in [1997-01-01, current_utc_time]",
      pyfile: "argo_decoder/rtqc/profile_scalar.py",
      pyfunc: "test_impossible_date",
      desc: "JULD_QC = 4 if date is before Argo inception or in future.",
    },
    {
      id: "TEST003",
      num: 3,
      name: "Impossible Location Check",
      rule: "-90 <= LAT <= 90 and -180 <= LON <= 180",
      pyfile: "argo_decoder/rtqc/profile_scalar.py",
      pyfunc: "test_impossible_location",
      desc: "POSITION_QC = 4 if coordinate is out of earthly range.",
    },
    {
      id: "TEST004",
      num: 4,
      name: "Position on Land Check (GEBCO Bathymetry)",
      rule: "GEBCO ocean depth < 0.0 m",
      pyfile: "argo_decoder/rtqc/profile_scalar.py",
      pyfunc: "test_position_on_land",
      desc: "Queries GEBCO global bathymetric elevation grid. Positions located on dry land flagged 4.",
    },
  ],
  PASS_D: [
    {
      id: "TEST005",
      num: 5,
      name: "Impossible Speed Check",
      rule: "Haversine Distance / Δt > 3.0 m/s (vs previous cycle)",
      pyfile: "argo_decoder/rtqc/cross_cycle.py",
      pyfunc: "test_impossible_speed",
      desc: "Calculates float drift velocity across consecutive surfacings. Speed > 3 m/s flags both position fixes.",
    },
    {
      id: "TEST018",
      num: 18,
      name: "Frozen Profile Check",
      rule: "50-dbar slabs across cycles: max<0.3, min<0.001, mean<0.02 (T)",
      pyfile: "argo_decoder/rtqc/cross_cycle.py",
      pyfunc: "test_frozen_profile",
      desc: "Detects dead or stuck CTD sensors repeating previous cycle profiles.",
    },
    {
      id: "TEST016",
      num: 16,
      name: "Gross Salinity/Temperature Sensor Drift",
      rule: "Deepest 100-dbar band offset > 1.0°C (TEMP) / 0.5 (PSAL)",
      pyfile: "argo_decoder/rtqc/cross_cycle.py",
      pyfunc: "test_gross_sensor_drift",
      desc: "Compares deep ocean calibration against previous GOOD cycle to detect sensor drift.",
    },
  ],
  PASS_BGC: [
    {
      id: "TEST057",
      num: 57,
      name: "DOXY Pre-deployment Drift",
      rule: "raw DOXY → QC 3 all defined levels; PRES_QC=4 or TEMP_QC=4 → 4",
      pyfile: "argo_decoder/rtqc/cts4.py",
      pyfunc: "_run_doxy_like",
      desc: "DOXY manual v2.2 §2.2.2: real-time unadjusted DOXY takes QC 3 everywhere by construction — Aanderaa optodes suffer pre-deployment storage drift (median 7.6% sensitivity loss array-wide). Common tests 6/9/11/12/13 run first via the shared suite; PSAL_QC=4 leaves DOXY at 3.",
    },
    {
      id: "TEST062",
      num: 62,
      name: "BBP700 Five Sub-tests",
      rule: "62.1 bin coverage; 62.2 deep median > 0.0005 m-1; 62.3 negatives; 62.4 outliers ≥10%; 62.5 parking hook",
      pyfile: "argo_decoder/rtqc/cts4.py",
      pyfunc: "_run_bbp",
      desc: "BBP manual §2.2.2: 62.1 missing-data coverage of the upper 1000 dbar in 10 bins (≥1 pt each); 62.2 high deep value (median-filtered w=11 median below 700 dbar > 0.0005 m-1, needs ≥5 pts); 62.3 negative BBP (shallow <5 dbar → 4; deep ≥10% negative → whole-profile 4, any → 3); 62.4 noisy profile (median residual > 0.0005 m-1 on ≥10% of shallow <100 dbar levels, needs ≥10 pts); 62.5 parking hook (ascending profiles only). All pass → BBP700_QC = 1: the only derived BGC parameter that can earn 1 in real time.",
    },
    {
      id: "TEST063",
      num: 63,
      name: "CHLA Raw-data Caveat",
      rule: "raw CHLA → QC 3 all defined levels (quenching/drift caveat)",
      pyfile: "argo_decoder/rtqc/cts4.py",
      pyfunc: "_run_chla",
      desc: "CHLA manual v3.0 §2.2.2: raw CHLA is not advisable for use, so CHLA_QC = 3 everywhere by construction. CHLA_FLUORESCENCE instead keeps QC 1. Bad raw-fluorescence flags propagate into CHLA (§2.6).",
    },
  ],
};

export const RtqcModal: React.FC = () => {
  const { isRtqcModalOpen, setRtqcModalOpen, selectedRtqcTest, setSelectedRtqcTest } =
    useDecoderStore();
  const [activeTab, setActiveTab] = useState<RtqcPass>("PASS_A");

  if (!isRtqcModalOpen) return null;

  return (
    <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-2xs z-50 flex items-center justify-center p-4 select-none font-mono text-slate-800">
      <div className="bg-white border border-slate-300 w-full max-w-4xl max-h-[88vh] rounded shadow-xl flex flex-col overflow-hidden">
        {/* Header */}
        <div className="h-10 px-4 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <Zap className="w-4 h-4 text-amber-600" />
            <span className="font-bold text-xs uppercase tracking-wider text-slate-900">
              REAL-TIME QUALITY CONTROL (RTQC) MATRIX :: ARGO TABLE 11 + BGC QC
            </span>
          </div>
          <button
            onClick={() => {
              setRtqcModalOpen(false);
              setSelectedRtqcTest(null);
            }}
            className="p-1 hover:bg-slate-200 text-slate-500 hover:text-slate-900 transition rounded"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Pass Navigation Tabs */}
        <div className="flex border-b border-slate-200 bg-slate-50/50 px-3 pt-1 space-x-1">
          {(
            [
              { id: "PASS_A", label: "PASS A: Vertical Non-Density (Tests 6,8,9,11,12,13,19)" },
              { id: "PASS_B", label: "PASS B: Density Inversion (Test 14 / TEOS-10)" },
              { id: "PASS_C", label: "PASS C: Profile Scalars (Tests 1,2,3,4)" },
              { id: "PASS_D", label: "PASS D: Cross-Cycle Fleet (Tests 5,16,18)" },
              { id: "PASS_BGC", label: "PASS BGC: Oxygen & Bio-optical (Tests 57,62,63)" },
            ] as const
          ).map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-3 py-1.5 text-[11px] font-bold uppercase transition border-t border-x rounded-t ${
                activeTab === tab.id
                  ? "bg-white text-sky-800 border-slate-300 border-b-transparent shadow-2xs"
                  : "bg-transparent text-slate-500 hover:text-slate-900 border-transparent"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Test List & Detailed Rules */}
        <div className="flex-1 overflow-y-auto p-3 space-y-2 bg-slate-50/30">
          {RTQC_REFERENCE_TESTS[activeTab].map((t) => {
            const isSelected = selectedRtqcTest?.test_id === t.id;

            return (
              <div
                key={t.id}
                className={`p-2.5 border rounded transition space-y-1.5 ${
                  isSelected
                    ? "bg-sky-50 border-sky-400 shadow-2xs"
                    : "bg-white border-slate-200 hover:border-slate-300"
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-2">
                    <span className="px-1.5 py-0.5 font-bold text-[10px] bg-sky-50 text-sky-800 border border-sky-200 rounded">
                      {t.id}
                    </span>
                    <span className="font-bold text-xs text-slate-900">{t.name}</span>
                  </div>
                  <span className="text-[9px] px-1.5 py-0.5 bg-emerald-50 text-emerald-800 border border-emerald-200 rounded font-bold flex items-center space-x-1">
                    <Check className="w-2.5 h-2.5 inline text-emerald-600" />
                    <span>ACTIVE IN PIPELINE</span>
                  </span>
                </div>

                <p className="text-[11px] text-slate-600 leading-normal font-sans">{t.desc}</p>

                <div className="grid grid-cols-2 gap-2 text-[10px] pt-1.5 border-t border-slate-100">
                  <div className="bg-slate-50 p-1.5 border border-slate-200 rounded">
                    <span className="text-slate-500 text-[9px] block uppercase font-bold">
                      FORMULA / THRESHOLD
                    </span>
                    <span className="text-amber-900 font-mono font-medium">{t.rule}</span>
                  </div>
                  <div className="bg-slate-50 p-1.5 border border-slate-200 rounded">
                    <span className="text-slate-500 text-[9px] block uppercase font-bold">
                      PYTHON SOURCE CODE
                    </span>
                    <span className="text-sky-800 font-mono font-medium">
                      {t.pyfile}::{t.pyfunc}
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {/* Footer */}
        <div className="h-9 px-4 bg-slate-50 border-t border-slate-200 flex items-center justify-between text-[11px] text-slate-600">
          <div className="flex items-center space-x-1.5">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" />
            <span>QC FLAGS: 1=Good, 2=Probably Good, 3=Doubtful, 4=Bad, 9=Missing</span>
          </div>
          <button
            onClick={() => setRtqcModalOpen(false)}
            className="px-3 py-1 bg-white hover:bg-slate-100 text-slate-700 border border-slate-300 rounded text-[10px] font-bold uppercase transition shadow-2xs"
          >
            Close Matrix
          </button>
        </div>
      </div>
    </div>
  );
};
