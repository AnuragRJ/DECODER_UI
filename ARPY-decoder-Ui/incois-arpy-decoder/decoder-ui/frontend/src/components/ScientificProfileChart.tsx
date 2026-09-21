import React, { useMemo } from "react";
import { Thermometer, Droplets } from "lucide-react";

/**
 * ScientificProfileChart
 * ----------------------
 * A restrained, data-first oceanographic profile plot (SVG):
 *   X axis — physical parameter (Sea temperature / Practical salinity)
 *   Y axis — Sea pressure, increasing DOWNWARD (0 dbar at top)
 *
 * All data comes from the real decoded cycle (ctd_samples of a RunSummary
 * cycle record). No values, QC codes, or positions are ever invented here.
 */

export interface ProfileSample {
  level: number;
  pres: number | null;
  value: number | null;
  qc: string | null;
}

export interface CtdRecord {
  level: number;
  PRES: number | null;
  TEMP: number | null;
  PSAL: number | null;
  CNDC?: number | null;
  PRES_QC: string | number | null;
  TEMP_QC: string | number | null;
  PSAL_QC: string | number | null;
}

/** Standard Argo QC flag vocabulary (used only to label codes present in data). */
const QC_LABELS: Record<string, string> = {
  "0": "Not assessed",
  "1": "Good",
  "2": "Probably good",
  "3": "Probably bad",
  "4": "Bad",
  "9": "Missing",
};

export function qcLabel(qc: string | number | null | undefined): string {
  if (qc === null || qc === undefined || qc === "") return "Not assessed";
  const s = String(qc);
  return QC_LABELS[s] || `Flag ${s}`;
}

export function qcIsGood(qc: string | number | null | undefined): boolean {
  const s = qc === null || qc === undefined ? null : String(qc);
  return s === "1" || s === "0";
}

function niceStep(span: number, targetTicks: number): number {
  const raw = span / Math.max(1, targetTicks);
  const magnitudes = [0.01, 0.02, 0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000];
  for (const m of magnitudes) {
    if (m >= raw) return m;
  }
  return magnitudes[magnitudes.length - 1];
}

function niceCeil(v: number, step: number): number {
  return Math.ceil(v / step) * step;
}

function niceFloor(v: number, step: number): number {
  return Math.floor(v / step) * step;
}

function fmtTick(v: number, decimals: number): string {
  return v.toFixed(decimals);
}

/** Span-adaptive decimal places for BGC values/ticks (BBP700 needs 5+,
 *  DOXY needs 2). Shared by the chart and the BGC measurement table so both
 *  format the same data identically. */
export function decimalsForSpan(s: number): number {
  if (!(s > 0)) return 2;
  return Math.min(7, Math.max(2, Math.ceil(-Math.log10(s)) + 1));
}

/** Restrained per-parameter palette. TEMP/PSAL keep their exact legacy
 *  colors; BGC keys get muted oceanographic tones; anything else falls back
 *  to slate-teal. Colors are presentation only — all data stays file-driven. */
const PARAM_COLORS: Record<string, { main: string; soft: string }> = {
  TEMP: { main: "#c0392b", soft: "#e8a09a" },
  PSAL: { main: "#0e7490", soft: "#8fc4d4" },
  DOXY: { main: "#1b7f5a", soft: "#9ad3b8" },
  TEMP_DOXY: { main: "#a05a2c", soft: "#d9b48f" },
  C1PHASE_DOXY: { main: "#2c7a7b", soft: "#9cc9ca" },
  C2PHASE_DOXY: { main: "#2c7a7b", soft: "#9cc9ca" },
  CHLA: { main: "#8a6d00", soft: "#d9c67a" },
  CHLA_FLUORESCENCE: { main: "#6d7c00", soft: "#c9d18a" },
  FLUORESCENCE_CHLA: { main: "#6d7c00", soft: "#c9d18a" },
  BBP700: { main: "#5b5bd6", soft: "#b9b9ec" },
  BETA_BACKSCATTERING700: { main: "#7c6de0", soft: "#c4bdf0" },
};
const FALLBACK_COLOR = { main: "#33646e", soft: "#9db9c0" };

interface Props {
  paramKey: string;
  title: string;
  axisLabel: string;
  /** e.g. "°C" / "psu" / the file's own BGC units string */
  unitShort: string;
  /** e.g. "degree_Celsius" / "psu", used in the range/legend caption */
  unitLong: string;
  /** samples of the selected cycle (full CTD records) */
  samples: CtdRecord[];
  /** pre-projected samples (value = plotted param, qc = matching QC field) */
  data: ProfileSample[];
  hoveredLevel: number | null;
  onHover: (level: number | null) => void;
  showPoints: boolean;
  showGrid: boolean;
  /** Generic (BGC) mode: plotted-parameter identity from the file's own
   *  attributes. Absent for the classic TEMP/PSAL CTD cards (unchanged). */
  genericParam?: {
    key: string;
    label: string;
  };
}

const W = 540;
const H = 470;
const PAD_L = 62;
const PAD_R = 18;
const PAD_T = 20;
const PAD_B = 52;
const PLOT_W = W - PAD_L - PAD_R;
const PLOT_H = H - PAD_T - PAD_B;

export const ScientificProfileChart: React.FC<Props> = ({
  paramKey,
  title,
  axisLabel,
  unitShort,
  unitLong,
  samples,
  data,
  hoveredLevel,
  onHover,
  showPoints,
  showGrid,
  genericParam,
}) => {
  const palette = PARAM_COLORS[paramKey] || FALLBACK_COLOR;
  const color = palette.main;
  const colorSoft = palette.soft;
  const Icon = paramKey === "TEMP" ? Thermometer : Droplets;

  // Real ranges from the supplied cycle data (never invented).
  const presVals = data.map((d) => d.pres).filter((p): p is number => p !== null && p !== undefined);
  const valVals = data.map((d) => d.value).filter((v): v is number => v !== null && v !== undefined);

  const maxPresRaw = presVals.length > 0 ? Math.max(...presVals) : 0;
  const maxPres = maxPresRaw > 0 ? Math.max(maxPresRaw, 50) : 1000;
  const minPres = 0;

  const valMinRaw = valVals.length > 0 ? Math.min(...valVals) : 0;
  const valMaxRaw = valVals.length > 0 ? Math.max(...valVals) : 1;
  // BGC spans 1e-7..1e2 across parameters, so a fixed minimum span would
  // either crush or explode a card; scale it to the data instead. CTD keeps
  // the exact legacy guards.
  const minSpan = genericParam
    ? Math.max(Math.abs(valMaxRaw) * 0.1, Math.abs(valMinRaw) * 0.1, 1e-12)
    : paramKey === "TEMP"
    ? 1
    : 0.5;
  const span = Math.max(valMaxRaw - valMinRaw, minSpan);
  const padFrac = span * 0.08;
  const valMin = valMinRaw - padFrac;
  const valMax = valMaxRaw + padFrac;

  const xStep = niceStep(valMax - valMin, 5);
  const yStep = niceStep(maxPres - minPres, 6);

  const x0 = niceFloor(valMin, xStep);
  const x1 = niceCeil(valMax, xStep);
  const y0 = minPres;
  const y1 = niceCeil(maxPres, yStep);

  const px = (v: number) => PAD_L + ((v - x0) / (x1 - x0 || 1)) * PLOT_W;
  const py = (p: number) => PAD_T + ((p - y0) / (y1 - y0 || 1)) * PLOT_H;

  const xTicks: number[] = [];
  for (let t = x0; t <= x1 + 1e-9; t += xStep) xTicks.push(t);
  const yTicks: number[] = [];
  for (let t = y0; t <= y1 + 1e-9; t += yStep) yTicks.push(t);

  // Split into visual classes: good (solid), probably-good (solid soft),
  // bad (dashed soft), missing data (marker only).
  interface Seg {
    d: string;
    cls: "good" | "soft" | "bad";
  }
  const segments = useMemo(() => {
    const segs: Seg[] = [];
    let cur: string[] = [];
    let curCls: "good" | "soft" | "bad" | null = null;
    let prevP: number | null = null;
    for (const s of data) {
      if (s.pres === null || s.value === null || s.qc === "9" || s.qc === "4") {
        // Break line at missing/bad values; bad points keep their own marker.
        if (cur.length >= 2) segs.push({ d: cur.join(" "), cls: curCls || "good" });
        cur = [];
        curCls = null;
        prevP = null;
        continue;
      }
      const cls: "good" | "soft" | "bad" = qcIsGood(s.qc) ? "good" : s.qc === "2" ? "soft" : "bad";
      if (curCls !== null && cls !== curCls) {
        if (cur.length >= 2) segs.push({ d: cur.join(" "), cls: curCls });
        cur = [];
        prevP = null;
      }
      curCls = cls;
      // Draw depth-ordered path (pressure increasing downward).
      if (prevP === null || (s.pres as number) >= prevP) {
        cur.push(`${px(s.value)},${py(s.pres)}`);
      } else {
        // Real data may be out of order; connect by value order anyway.
        cur.push(`${px(s.value)},${py(s.pres)}`);
      }
      prevP = s.pres;
    }
    if (cur.length >= 2 && curCls) segs.push({ d: cur.join(" "), cls: curCls });
    return segs;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, x0, x1, y0, y1]);

  // QC codes actually present in this cycle (real, per parameter).
  const presentQc = useMemo(() => {
    const set = new Set<string>();
    for (const s of data) {
      if (s.qc && s.qc !== "9") set.add(s.qc);
    }
    return Array.from(set).sort();
  }, [data]);

  const hoveredSample = useMemo(
    () => (hoveredLevel !== null ? samples.find((s) => s.level === hoveredLevel) || null : null),
    [hoveredLevel, samples]
  );

  // Generic-mode hover: BGC callers pass samples={[]} (no CTD record) and
  // composite level ids, so the readout is driven by the projected datum.
  const hoveredDatum = useMemo(
    () => (hoveredLevel !== null ? data.find((s) => s.level === hoveredLevel) || null : null),
    [hoveredLevel, data]
  );

  // Nearest-level lookup for plot-area mouse movement (by pressure).
  const nearestLevel = (clientY: number, svgRect: DOMRect): number | null => {
    const relY = ((clientY - svgRect.top) / svgRect.height) * H;
    if (relY < PAD_T || relY > PAD_T + PLOT_H) return null;
    const pres = y0 + ((relY - PAD_T) / PLOT_H) * (y1 - y0);
    let best: number | null = null;
    let bestD = Infinity;
    for (const s of data) {
      if (s.pres === null) continue;
      const d = Math.abs(s.pres - pres);
      if (d < bestD) {
        bestD = d;
        best = s.level;
      }
    }
    return best;
  };

  // BGC tick/readout precision adapts to the plotted span; CTD keeps the
  // exact legacy precisions.
  const valueDecimals = genericParam ? decimalsForSpan(span) : 2;
  const xDecimals = genericParam ? valueDecimals : paramKey === "TEMP" ? 1 : 2;

  const hoverPres =
    hoveredSample && hoveredSample.PRES !== null
      ? hoveredSample.PRES
      : genericParam && hoveredDatum && hoveredDatum.pres !== null
      ? hoveredDatum.pres
      : null;
  const hoverPresY = hoverPres !== null ? py(hoverPres) : null;

  return (
    <div className="bg-white border border-slate-200 rounded flex flex-col overflow-hidden">
      {/* Scientific card header */}
      <div className="px-3 py-2 border-b border-slate-200 bg-slate-50/60 flex items-center justify-between gap-2">
        <div className="flex items-center space-x-2 min-w-0">
          <span
            className="w-1.5 h-6 rounded shrink-0"
            style={{ backgroundColor: color }}
          />
          <div className="min-w-0">
            <div className="font-mono text-[12px] font-bold text-slate-900 tracking-wide truncate">
              {title}
            </div>
            <div className="text-[10px] text-slate-500 font-mono truncate">{axisLabel}</div>
          </div>
        </div>
        <span className="font-mono text-[10px] text-slate-400 shrink-0 hidden sm:block">
          {y1.toFixed(0)} dbar max
        </span>
      </div>

      {/* Plot area */}
      <div className="relative flex-1 p-2">
        <svg
          className="w-full h-auto block"
          viewBox={`0 0 ${W} ${H}`}
          onMouseMove={(e) => {
            const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
            onHover(nearestLevel(e.clientY, rect));
          }}
          onMouseLeave={() => onHover(null)}
        >
          {/* White plotting area with subtle frame */}
          <rect x={PAD_L} y={PAD_T} width={PLOT_W} height={PLOT_H} fill="#ffffff" stroke="#cbd8e4" strokeWidth="1" />

          {/* Subtle blue/gray gridlines */}
          {showGrid &&
            yTicks.map((t) => (
              <line
                key={`gy${t}`}
                x1={PAD_L}
                y1={py(t)}
                x2={PAD_L + PLOT_W}
                y2={py(t)}
                stroke="#e3ebf3"
                strokeWidth="1"
              />
            ))}
          {showGrid &&
            xTicks.map((t) => (
              <line
                key={`gx${t}`}
                x1={px(t)}
                y1={PAD_T}
                x2={px(t)}
                y2={PAD_T + PLOT_H}
                stroke="#e3ebf3"
                strokeWidth="1"
              />
            ))}

          {/* Axis frame */}
          <line x1={PAD_L} y1={PAD_T} x2={PAD_L} y2={PAD_T + PLOT_H} stroke="#94a9bd" strokeWidth="1" />
          <line x1={PAD_L} y1={PAD_T + PLOT_H} x2={PAD_L + PLOT_W} y2={PAD_T + PLOT_H} stroke="#94a9bd" strokeWidth="1" />

          {/* Y ticks — Sea pressure, increasing downward */}
          {yTicks.map((t) => (
            <g key={`yt${t}`}>
              <line x1={PAD_L - 4} y1={py(t)} x2={PAD_L} y2={py(t)} stroke="#94a9bd" strokeWidth="1" />
              <text
                x={PAD_L - 7}
                y={py(t) + 3}
                textAnchor="end"
                fontSize="11.5"
                fill="#64748b"
                fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
              >
                {t.toFixed(0)}
              </text>
            </g>
          ))}

          {/* X ticks */}
          {xTicks.map((t) => (
            <g key={`xt${t}`}>
              <line x1={px(t)} y1={PAD_T + PLOT_H} x2={px(t)} y2={PAD_T + PLOT_H + 4} stroke="#94a9bd" strokeWidth="1" />
              <text
                x={px(t)}
                y={PAD_T + PLOT_H + 15}
                textAnchor="middle"
                fontSize="11.5"
                fill="#64748b"
                fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
              >
                {fmtTick(t, xDecimals)}
              </text>
            </g>
          ))}

          {/* Axis titles */}
          <text
            x={PAD_L + PLOT_W / 2}
            y={H - 12}
            textAnchor="middle"
            fontSize="12"
            fill="#475569"
            fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
            fontStyle="italic"
          >
            {axisLabel}
          </text>
          <text
            x={14}
            y={PAD_T + PLOT_H / 2}
            textAnchor="middle"
            fontSize="12"
            fill="#475569"
            fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
            fontStyle="italic"
            transform={`rotate(-90 14 ${PAD_T + PLOT_H / 2})`}
          >
            Sea pressure — decibar
          </text>

          {/* Profile segments — subtle difference for questionable/bad QC */}
          {segments.map((seg, i) => (
            <polyline
              key={`seg${i}`}
              fill="none"
              stroke={seg.cls === "good" ? color : colorSoft}
              strokeWidth={seg.cls === "good" ? 2 : 1.6}
              strokeDasharray={seg.cls === "good" ? undefined : seg.cls === "bad" ? "5,3" : undefined}
              opacity={seg.cls === "good" ? 1 : 0.9}
              points={seg.d}
              strokeLinejoin="round"
            />
          ))}

          {/* Crosshair on hover */}
          {hoverPresY !== null && (
            <g>
              <line x1={PAD_L} y1={hoverPresY} x2={PAD_L + PLOT_W} y2={hoverPresY} stroke="#64748b" strokeWidth="0.8" strokeDasharray="3,3" opacity="0.7" />
            </g>
          )}

          {/* Measurement points */}
          {showPoints &&
            data.map((s) => {
              if (s.pres === null || s.value === null) return null;
              const cx = px(s.value);
              const cy = py(s.pres);
              const isHover = s.level === hoveredLevel;
              const good = qcIsGood(s.qc);
              const bad = s.qc === "3" || s.qc === "4";
              if (s.qc === "9") {
                return (
                  <text key={`m${s.level}`} x={cx} y={cy + 3} textAnchor="middle" fontSize="10.5" fill="#b0bec9" fontFamily="monospace">
                    ×
                  </text>
                );
              }
              return (
                <g key={`m${s.level}`}>
                  {isHover && <circle cx={cx} cy={cy} r={7.5} fill="none" stroke={color} strokeWidth="1.2" opacity="0.8" />}
                  <circle
                    cx={cx}
                    cy={cy}
                    r={bad ? 3.4 : 2.6}
                    fill={bad ? "#ffffff" : good ? color : colorSoft}
                    stroke={color}
                    strokeWidth={bad ? 1.2 : 1}
                    opacity={good || bad ? 1 : 0.85}
                  />
                </g>
              );
            })}
        </svg>

        {/* Hover readout panel (real values of the hovered level) */}
        {hoveredSample && (
          <div className="absolute top-2 right-2 bg-white/95 border border-slate-300 rounded px-2.5 py-1.5 font-mono text-[10.5px] leading-4 shadow-sm pointer-events-none select-none space-y-0.5">
            <div className="text-slate-500">
              Pressure:{" "}
              <span className="font-bold text-slate-900">
                {hoveredSample.PRES !== null && hoveredSample.PRES !== undefined
                  ? `${hoveredSample.PRES.toFixed(0)} dbar`
                  : "—"}
              </span>
            </div>
            <div>
              <span className="text-slate-500">Temperature: </span>
              <span className="font-bold" style={{ color }}>
                {hoveredSample.TEMP !== null && hoveredSample.TEMP !== undefined
                  ? `${hoveredSample.TEMP.toFixed(2)} °C`
                  : "—"}
              </span>
            </div>
            <div>
              <span className="text-slate-500">Salinity: </span>
              <span className="font-bold" style={{ color: paramKey === "PSAL" ? color : "#0e7490" }}>
                {hoveredSample.PSAL !== null && hoveredSample.PSAL !== undefined
                  ? `${hoveredSample.PSAL.toFixed(2)} psu`
                  : "—"}
              </span>
            </div>
            <div className="text-slate-500 pt-0.5 border-t border-slate-200">
              QC:{" "}
              <span className="font-bold text-slate-700">
                {qcLabel(hoveredSample.TEMP_QC)}
                {hoveredSample.PSAL_QC !== null &&
                hoveredSample.PSAL_QC !== undefined &&
                String(hoveredSample.PSAL_QC) !== String(hoveredSample.TEMP_QC)
                  ? ` · PSAL ${qcLabel(hoveredSample.PSAL_QC)}`
                  : ""}
              </span>
            </div>
          </div>
        )}

        {/* Generic-mode hover readout (real plotted value + its level QC) */}
        {genericParam && hoveredDatum && (
          <div className="absolute top-2 right-2 bg-white/95 border border-slate-300 rounded px-2.5 py-1.5 font-mono text-[10.5px] leading-4 shadow-sm pointer-events-none select-none space-y-0.5">
            <div className="text-slate-500">
              Pressure:{" "}
              <span className="font-bold text-slate-900">
                {hoveredDatum.pres !== null && hoveredDatum.pres !== undefined
                  ? `${hoveredDatum.pres.toFixed(0)} dbar`
                  : "—"}
              </span>
            </div>
            <div>
              <span className="text-slate-500">{genericParam.label}: </span>
              <span className="font-bold" style={{ color }}>
                {hoveredDatum.value !== null && hoveredDatum.value !== undefined
                  ? `${hoveredDatum.value.toFixed(valueDecimals)} ${unitShort}`
                  : "—"}
              </span>
            </div>
            <div className="text-slate-500 pt-0.5 border-t border-slate-200">
              QC:{" "}
              <span className="font-bold text-slate-700">
                {qcLabel(hoveredDatum.qc)}
              </span>
            </div>
          </div>
        )}
      </div>

      {/* QC legend — only codes present in the selected cycle (real) */}
      <div className="px-3 pb-1.5 flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2.5 font-mono text-[9.5px] text-slate-500 flex-wrap">
          {presentQc.length === 0 ? (
            <span>QC: no flagged levels in this cycle</span>
          ) : (
            <>
              {presentQc.map((q) => (
                <span key={q} className="flex items-center gap-1">
                  <span
                    className="inline-block w-2 h-2 rounded-full border"
                    style={{
                      backgroundColor: qcIsGood(q) ? color : q === "2" ? colorSoft : "#ffffff",
                      borderColor: color,
                      borderStyle: q === "3" || q === "4" ? "dashed" : "solid",
                      borderWidth: 1,
                    }}
                  />
                  {qcLabel(q)}
                </span>
              ))}
            </>
          )}
        </div>
        <span className="font-mono text-[9.5px] text-slate-400">
          {valVals.length} levels · {unitLong}
        </span>
      </div>

      {/* Range information below the chart (computed from real data) */}
      <div className="px-3 py-1.5 border-t border-slate-200 bg-slate-50/60 flex items-center justify-between font-mono text-[9.5px] text-slate-500">
        <span>
          Range:{" "}
          <span className="font-bold text-slate-700">
            {valVals.length > 0
              ? `${valMinRaw.toFixed(valueDecimals)} – ${valMaxRaw.toFixed(valueDecimals)} ${unitShort}`
              : "no data"}
          </span>
        </span>
        <span>
          Pressure:{" "}
          <span className="font-bold text-slate-700">
            {presVals.length > 0 ? `${Math.min(...presVals).toFixed(0)} – ${maxPresRaw.toFixed(0)} dbar` : "no data"}
          </span>
        </span>
      </div>
    </div>
  );
};

export default ScientificProfileChart;
