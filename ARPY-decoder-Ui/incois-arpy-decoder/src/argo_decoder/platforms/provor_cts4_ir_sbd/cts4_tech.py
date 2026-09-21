"""CTS4 technical (``<wmo>_tech.nc``) product model — accumulating.

Builds per-cycle TECH rows from CTS4 telemetry (253/252/250) using
Corolis 301 label tables (labels_301). No fabrication: only fields with
authoritative labels are emitted; missing telemetry → no row (fill handled
by writer via _FillValue, not invented value).

Mirrors ARVOR's approach but for CTS4 family: one tech file per float,
accumulating across cycles (N_TECH_PARAM unlimited).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from argo_decoder.platforms.provor_cts4_ir_sbd.labels_301 import (
    TECH250_CTD_FREE_LABEL,
    TECH250_LABEL,
    TECH253_LABEL,
)
from argo_decoder.platforms.provor_cts4_ir_sbd.tech import (
    PressurePacket,
    SensorTechPacket,
    VectorTech,
)


@dataclass(frozen=True)
class Cts4TechRow:
    cycle_number: int
    name: str
    value: str

@dataclass
class Cts4TechDataset:
    wmo: str | None
    rows: list[Cts4TechRow] = field(default_factory=list)

    @property
    def tech_rows(self):
        return self.rows

def _fmt(value) -> str:
    if isinstance(value, float):
        # limit to reasonable precision, match GDAC string formatting
        if value == int(value):
            return str(int(value))
        return f"{value:g}"
    return str(value)

def collect_tech_for_cycle(cycle_number: int, vt: VectorTech | None, pp: PressurePacket | None = None, st: SensorTechPacket | None = None) -> list[Cts4TechRow]:
    rows: list[Cts4TechRow] = []
    if vt is not None:
        for field_name, label in TECH253_LABEL.items():
            if label is None:
                continue
            val = getattr(vt, field_name, None)
            if val is None:
                continue
            # handle FloatTime special: format YYYYMMDDHHMMSS
            if field_name == "time":
                # vt.time is FloatTime
                ft = val
                try:
                    s = f"{2000+ft.yy:04d}{ft.mm:02d}{ft.dd:02d}{ft.hh:02d}{ft.mi:02d}{ft.ss:02d}"
                except:
                    s = _fmt(val)
                rows.append(Cts4TechRow(cycle_number, label, s))
            elif field_name == "vacuum_raw":
                rows.append(Cts4TechRow(cycle_number, label, _fmt(val*5)))  # mbar x5
            elif field_name == "battery_raw":
                volt = 15.0 - val/10.0
                rows.append(Cts4TechRow(cycle_number, label, _fmt(volt)))
            elif field_name.endswith("_day") or field_name.endswith("_hour") or "cycle" in field_name or "serial" in field_name:
                rows.append(Cts4TechRow(cycle_number, label, _fmt(val)))
            else:
                rows.append(Cts4TechRow(cycle_number, label, _fmt(val)))
    # 252 pressure samples -> not directly TECH labels except via derived counts; we skip for now (DATA-COVERAGE)
    # 250 sensor halves -> emit counts per sensor
    if st is not None:
        for half in st.halves:
            if not half.present:
                continue
            sensor_name = {0: "CTD", 1: "Optode", 4: "Flbb"}.get(half.sensor, f"UNKNOWN{half.sensor}")
            for fname, tmpl in TECH250_LABEL.items():
                if tmpl is None:
                    continue
                val = getattr(half, fname, None)
                if val is None:
                    continue
                label = tmpl.replace("<Sensor>", sensor_name)
                # acq_descent/acq_ascent are tuples per zone
                if fname in ("acq_descent", "acq_ascent"):
                    for zi, cnt in enumerate(val, start=1):
                        zlabel = label.replace("<Z>", str(zi))
                        rows.append(Cts4TechRow(cycle_number, zlabel, _fmt(cnt)))
                else:
                    rows.append(Cts4TechRow(cycle_number, label, _fmt(val)))
            # free zones
            if half.free is not None:
                if half.free.__class__.__name__ == "CtdFree":
                    for fname, tmpl in TECH250_CTD_FREE_LABEL.items():
                        if tmpl is None:
                            continue
                        val = getattr(half.free, fname, None)
                        if val is None:
                            continue
                        rows.append(Cts4TechRow(cycle_number, tmpl, _fmt(val)))
                elif half.free.__class__.__name__ == "FlbbFree":
                    # FLBB free zone values are factory coeffs, not TECH per 301 (all None), so skip
                    pass
    return rows

def build_cts4_tech_dataset(cycles_data: list[tuple[int, VectorTech | None, PressurePacket | None, SensorTechPacket | None]], wmo: str | None = None) -> Cts4TechDataset:
    ds = Cts4TechDataset(wmo=wmo)
    for cyc, vt, pp, st in sorted(cycles_data, key=lambda x: x[0]):
        rows = collect_tech_for_cycle(cyc, vt, pp, st)
        ds.rows.extend(rows)
    # sort by cycle then name for writer stability (like ARVOR finalize)
    ds.rows.sort(key=lambda r: (r.cycle_number, r.name))
    return ds
