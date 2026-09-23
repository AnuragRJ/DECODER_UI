"""APEX APF11 accumulating real-time trajectory file (``<WMO>_Rtraj.nc``).

Layout transcribed from the published INCOIS APF11 ``2902296_Rtraj.nc``:
dims, variable order, dtypes, per-variable attributes and fill conventions.
Content comes from :mod:`argo_decoder.platforms.apex_apf11_ir.traj_block`;
everything this writer emits that the platform layer resolved is already
telemetry-backed; the deep/transmission/grounding anchor families stay at
their documented fills.

Real-time production uses ``DATA_MODE='R'``. No clock-drift or scientific
adjustment is computed by this path; JULD_ADJUSTED and its flags remain fill,
not mirrors of JULD. CLOCK_OFFSET is also fill: an unevaluated offset must
not masquerade as a measured zero. Argo User Manual 3.44 section 2.3.5 allows
sparse/empty JULD_ADJUSTED in R-mode. DATA_STATE_INDICATOR describes the QC
processing stage independently of adjustment mode and is not changed here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import netCDF4
import numpy as np

from argo_decoder.writer.apf11_policy import APF11_NC_FORMAT, APF11_DATA_MODE

from argo_decoder.platforms.apex_apf11_ir.traj_block import (
    FloatTrajectory,
    JULD_FILL,
)

DATE_TIME = 14
STRING2, STRING4, STRING8, STRING16 = 2, 4, 8, 16
STRING32, STRING64 = 32, 64
INT_FILL = np.int32(99999)
FLOAT_FILL = np.float32(99999.0)
DOUBLE_FILL = np.float64(99999.0)
JULD_F = np.float64(999999.0)

_TITLE_TIME = "Relative julian days with decimal part (as parts of day)"
_UNITS_TIME = "days since 1950-01-01 00:00:00 UTC"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y%m%d%H%M%S")


class _Ds:
    """Small helper binding a dataset and its fixed string dims."""

    def __init__(self, ds: netCDF4.Dataset):
        self.ds = ds

    def char_scalar(
        self,
        name: str,
        width: int,
        value: str,
        long_name: str | None = None,
        conventions: str | None = None,
    ) -> None:
        dim = "DATE_TIME" if width == DATE_TIME else f"STRING{width}"
        var = self.ds.createVariable(name, "S1", (dim,), fill_value=" ")
        data = np.zeros((width,), dtype="S1")
        data[:] = b" "
        raw = value.encode("ascii", "replace")[:width]
        data[: len(raw)] = np.frombuffer(raw, dtype="S1")
        var[:] = data
        if long_name is not None:
            var.setncattr("long_name", long_name)
        if conventions is not None:
            var.setncattr("conventions", conventions)

    def date(self, name: str, value: str, long_name: str) -> None:
        self.char_scalar(name, DATE_TIME, value, long_name, "YYYYMMDDHHMISS")


def build_traj_dataset(
    traj: FloatTrajectory,
    *,
    wmo: int,
    data_centre: str = "",
    wmo_inst_type: str = "",
    project_name: str = "",
    pi_name: str = "",
    platform_type: str = "",
    float_serial_no: str = "",
    firmware_version: str = "",
    launch_lat: float | None = None,
    launch_lon: float | None = None,
    date_creation: str | None = None,
) -> netCDF4.Dataset:
    """Return an open in-memory dataset with the full trajectory."""

    now = _now()
    created = date_creation or now

    rows = traj.rows
    cyc = traj.cycles
    n_meas, n_cycle = len(rows), len(cyc)

    ds = netCDF4.Dataset("inmemory", mode="w", format=APF11_NC_FORMAT, diskless=True)
    ds.createDimension("N_MEASUREMENT", n_meas)
    ds.createDimension("N_CYCLE", n_cycle)
    ds.createDimension("N_PARAM", 3)
    ds.createDimension("N_HISTORY", 1)
    for w in (2, 4, 8, 16, 32, 64):
        ds.createDimension(f"STRING{w}", w)
    ds.createDimension("DATE_TIME", DATE_TIME)

    h = _Ds(ds)
    h.date("DATE_CREATION", created, "Date of file creation")
    h.date("DATE_UPDATE", now, "Date of update of this file")
    h.char_scalar("PLATFORM_NUMBER", STRING8, str(wmo), "Float unique identifier", "WMO float identifier : A9IIIII")
    h.char_scalar("DATA_CENTRE", STRING2, data_centre, "Data centre in charge of float data processing", "Argo reference table 4")
    h.char_scalar("WMO_INST_TYPE", STRING4, wmo_inst_type, "Coded instrument type", "Argo reference table 8")
    h.char_scalar("PROJECT_NAME", STRING64, project_name, "Name of the project")
    h.char_scalar("PI_NAME", STRING64, pi_name, "Name of the principal investigator")
    h.char_scalar("DATA_TYPE", STRING16, "Argo trajectory", "Data type", "Argo reference table 1")
    h.char_scalar("FORMAT_VERSION", STRING4, "3.1", "File format version")
    h.char_scalar("HANDBOOK_VERSION", STRING4, " 3.1", "Data handbook version")
    h.date("REFERENCE_DATE_TIME", "19500101000000", "Date of reference for Julian days")
    pos_sys = ds.createVariable("POSITIONING_SYSTEM", "S1", ("STRING8",), fill_value=np.bytes_(b" "))
    arr = np.zeros((STRING8,), dtype="S1"); arr[:] = b" "
    arr[:3] = np.frombuffer(b"GPS", dtype="S1")
    pos_sys[:] = arr
    pos_sys.setncattr("long_name", "Positioning system")
    tp = ds.createVariable("TRAJECTORY_PARAMETERS", "S1", ("N_PARAM", "STRING16"), fill_value=np.bytes_(b" "))
    arr = np.zeros((3, STRING16), dtype="S1"); arr[:] = b" "
    for i, p in enumerate(("PRES", "TEMP", "PSAL")):
        raw = p.encode()[:STRING16]
        arr[i, : len(raw)] = np.frombuffer(raw, dtype="S1")
    tp[:] = arr
    tp.setncattr("long_name", "List of available parameters for the station")
    tp.setncattr("conventions", "Argo reference table 3")
    h.char_scalar("DATA_STATE_INDICATOR", STRING4, "2B", "Degree of processing the data have passed through", "Argo reference table 6")
    h.char_scalar("PLATFORM_TYPE", STRING32, platform_type, "Type of float", "Argo reference table 23")
    h.char_scalar("FLOAT_SERIAL_NO", STRING32, float_serial_no, "Serial number of the float")
    h.char_scalar("FIRMWARE_VERSION", STRING32, firmware_version, "Instrument firmware version")

    # ---- N_MEASUREMENT rows -------------------------------------------------
    n = n_meas
    juld = np.full(n, JULD_FILL, dtype=np.float64)
    status = np.full((n, 1), b" ", dtype="S1")
    qcs = np.full((n, 1), b" ", dtype="S1")
    cyc_num = np.full(n, INT_FILL, dtype=np.int32)
    mc = np.full(n, INT_FILL, dtype=np.int32)
    juld_adj = np.full(n, JULD_FILL, dtype=np.float64)
    status_adj = np.full((n, 1), b" ", dtype="S1")
    qc_adj = np.full((n, 1), b" ", dtype="S1")
    lat = np.full(n, DOUBLE_FILL, dtype=np.float64)
    lon = np.full(n, DOUBLE_FILL, dtype=np.float64)
    pos_flag = np.full(n, b" ", dtype="S1")

    for i, r in enumerate(rows):
        if r.juld != JULD_FILL:
            juld[i] = np.float64(r.juld)
        st = r.juld_status if getattr(r, "juld_status", "") else r.status
        status[i, 0] = st.encode("ascii", "replace")[:1]
        qc_val = getattr(r, "juld_qc", "")
        if not qc_val:
            qc_val = "1" if (r.mc == 0 or r.juld != JULD_FILL) else "9"
        qcs[i, 0] = qc_val.encode("ascii", "replace")[:1]
        cyc_num[i] = np.int32(r.cycle)
        mc[i] = np.int32(r.mc)

        r_lat = getattr(r, "latitude", DOUBLE_FILL)
        if r_lat != DOUBLE_FILL:
            lat[i] = np.float64(r_lat)
        elif r.cycle == -1 and r.mc == 0 and launch_lat is not None:
            lat[i] = np.float64(launch_lat)

        r_lon = getattr(r, "longitude", DOUBLE_FILL)
        if r_lon != DOUBLE_FILL:
            lon[i] = np.float64(r_lon)
        elif r.cycle == -1 and r.mc == 0 and launch_lon is not None:
            lon[i] = np.float64(launch_lon)

        r_pqc = getattr(r, "position_qc", " ")
        if r_pqc != " ":
            pos_flag[i] = r_pqc.encode("ascii", "replace")[:1]
        elif r.cycle == -1 and r.mc == 0 and launch_lat is not None and launch_lon is not None:
            pos_flag[i] = b"1"

    def mvar(name, values, fill, attrs):
        v = ds.createVariable(name, values.dtype, ("N_MEASUREMENT",), fill_value=fill)
        v[:] = values
        for k, val in attrs.items():
            v.setncattr(k, val)
        return v

    time_attrs = {
        "standard_name": "time",
        "units": _UNITS_TIME,
        "conventions": _TITLE_TIME,
        "resolution": np.float64(0.01),
        "axis": "T",
    }
    mvar("JULD", juld, JULD_F, {"long_name": "Julian day (UTC) of each measurement relative to REFERENCE_DATE_TIME", **time_attrs})
    st_var = ds.createVariable("JULD_STATUS", "S1", ("N_MEASUREMENT",), fill_value=np.bytes_(b" "))
    st_var[:] = status[:, 0]
    st_var.setncattr("long_name", "Status of the date and time")
    st_var.setncattr("conventions", "Argo reference table 19")
    qc_var = ds.createVariable("JULD_QC", "S1", ("N_MEASUREMENT",), fill_value=np.bytes_(b" "))
    qc_var[:] = qcs[:, 0]
    qc_var.setncattr("long_name", "Quality on date and time")
    qc_var.setncattr("conventions", "Argo reference table 2")
    mvar("JULD_ADJUSTED", juld_adj, JULD_F, {"long_name": "Adjusted julian day (UTC) of each measurement relative to REFERENCE_DATE_TIME", **time_attrs})
    adjst = ds.createVariable("JULD_ADJUSTED_STATUS", "S1", ("N_MEASUREMENT",), fill_value=np.bytes_(b" "))
    adjst[:] = status_adj[:, 0]
    adjst.setncattr("long_name", "Status of the JULD_ADJUSTED date")
    adjst.setncattr("conventions", "Argo reference table 19")
    adjqc = ds.createVariable("JULD_ADJUSTED_QC", "S1", ("N_MEASUREMENT",), fill_value=np.bytes_(b" "))
    adjqc[:] = qc_adj[:, 0]
    adjqc.setncattr("long_name", "Quality on adjusted date and time")
    adjqc.setncattr("conventions", "Argo reference table 2")

    mvar("LATITUDE", lat, DOUBLE_FILL, {"long_name": "Latitude of each location", "standard_name": "latitude", "units": "degree_north", "valid_min": -90.0, "valid_max": 90.0, "axis": "Y"})
    mvar("LONGITUDE", lon, DOUBLE_FILL, {"long_name": "Longitude of each location", "standard_name": "longitude", "units": "degree_east", "valid_min": -180.0, "valid_max": 180.0, "axis": "X"})
    for name, ln, conv in (
        ("POSITION_ACCURACY", "Estimated accuracy in latitude and longitude", "Argo reference table 5"),
        ("POSITION_QC", "Quality on position", "Argo reference table 2"),
    ):
        v = ds.createVariable(name, "S1", ("N_MEASUREMENT",), fill_value=np.bytes_(b" "))
        v[:] = pos_flag if name == "POSITION_QC" else np.full(n, b" ", dtype="S1")
        v.setncattr("long_name", ln)
        v.setncattr("conventions", conv)
    mvar("CYCLE_NUMBER", cyc_num, INT_FILL, {"long_name": "Float cycle number of the measurement", "conventions": "0...N, 0 : launch cycle, 1 : first complete cycle"})
    mvar("CYCLE_NUMBER_ADJUSTED", np.full(n, INT_FILL, dtype=np.int32), INT_FILL, {"long_name": "Adjusted float cycle number of the measurement", "conventions": "0...N, 0 : launch cycle, 1 : first complete cycle"})
    mvar("MEASUREMENT_CODE", mc, INT_FILL, {"long_name": "Flag referring to a measurement event in the cycle", "conventions": "Argo reference table 15"})

    _PTS = {
        "PRES": {
            "long_name": "Sea water pressure, equals 0 at sea-level",
            "standard_name": "sea_water_pressure",
            "units": "decibar",
            "valid_min": 0.0, "valid_max": 12000.0,
            "C_format": "%7.1f", "FORTRAN_format": "F7.1", "resolution": 0.0,
        },
        "TEMP": {
            "long_name": "Sea temperature in-situ ITS-90 scale",
            "standard_name": "sea_water_temperature",
            "units": "degree_Celsius",
            "valid_min": -2.5, "valid_max": 40.0,
            "C_format": "%9.3f", "FORTRAN_format": "F9.3", "resolution": 1.0,
        },
        "PSAL": {
            "long_name": "Practical salinity",
            "standard_name": "sea_water_salinity",
            "units": "psu",
            "valid_min": 2.0, "valid_max": 41.0,
            "C_format": "%9.3f", "FORTRAN_format": "F9.3", "resolution": 0.001,
        },
    }

    def _pts_attrs(base, suffix):
        a = _PTS[base]
        attrs = {
            "long_name": a["long_name"],
            "standard_name": a["standard_name"],
            "units": a["units"],
            "_FillValue": None,  # placeholder, set via mvar
            "valid_min": np.float64(a["valid_min"]),
            "valid_max": np.float64(a["valid_max"]),
            "C_format": a["C_format"],
            "FORTRAN_format": a["FORTRAN_format"],
            "resolution": np.float64(a["resolution"]),
        }
        if suffix == "PRES_ADJUSTED" or base == "PRES" and suffix == "adj":
            attrs["comment"] = "In situ measurement, sea surface = 0"
        return attrs

    for base in ("PRES", "TEMP", "PSAL"):
        a = _PTS[base]
        fillcol = np.full(n, FLOAT_FILL, dtype=np.float32)
        mvar(base, fillcol, FLOAT_FILL, {
            "long_name": a["long_name"],
            "standard_name": a["standard_name"],
            "units": a["units"],
            "valid_min": np.float64(a["valid_min"]),
            "valid_max": np.float64(a["valid_max"]),
            "C_format": a["C_format"],
            "FORTRAN_format": a["FORTRAN_format"],
            "resolution": np.float64(a["resolution"]),
            **({"axis": "Z"} if base == "PRES" else {}),
            **({"comment": "In situ measurement, sea surface = 0"} if base == "PRES" else {}),
        })
        qv = ds.createVariable(f"{base}_QC", "S1", ("N_MEASUREMENT",), fill_value=np.bytes_(b" "))
        qv[:] = np.full(n, b" ", dtype="S1")
        qv.setncattr("long_name", "quality flag")
        qv.setncattr("conventions", "Argo reference table 2")
        mvar(f"{base}_ADJUSTED", fillcol.copy(), FLOAT_FILL, {
            "long_name": a["long_name"],
            "standard_name": a["standard_name"],
            "units": a["units"],
            "valid_min": np.float64(a["valid_min"]),
            "valid_max": np.float64(a["valid_max"]),
            "C_format": a["C_format"],
            "FORTRAN_format": a["FORTRAN_format"],
            "resolution": np.float64(a["resolution"]),
            **({"axis": "Z"} if base == "PRES" else {}),
            **({"comment": "In situ measurement, sea surface = 0"} if base == "PRES" else {}),
        })
        av = ds.createVariable(f"{base}_ADJUSTED_QC", "S1", ("N_MEASUREMENT",), fill_value=np.bytes_(b" "))
        av[:] = np.full(n, b" ", dtype="S1")
        av.setncattr("long_name", "quality flag")
        av.setncattr("conventions", "Argo reference table 2")
        mvar(f"{base}_ADJUSTED_ERROR", fillcol.copy(), FLOAT_FILL, {
            "long_name": "Contains the error on the adjusted values as determined by the delayed mode QC process",
            "units": a["units"],
            "C_format": a["C_format"],
            "FORTRAN_format": a["FORTRAN_format"],
        })
    _AXES = {
        "AXES_ERROR_ELLIPSE_MAJOR": ("Major axis of error ellipse from positioning system", "meters"),
        "AXES_ERROR_ELLIPSE_MINOR": ("Minor axis of error ellipse from positioning system", "meters"),
        "AXES_ERROR_ELLIPSE_ANGLE": ("Angle of error ellipse from positioning system", "Degrees (from North when heading East)"),
    }
    for name, (ln, units) in _AXES.items():
        mvar(name, np.full(n, FLOAT_FILL, dtype=np.float32), FLOAT_FILL, {"long_name": ln, "units": units})
    sn = ds.createVariable("SATELLITE_NAME", "S1", ("N_MEASUREMENT",), fill_value=np.bytes_(b" "))
    sn[:] = np.full(n, b" ", dtype="S1")
    sn.setncattr("long_name", "Satellite name from positioning system")

    # ---- N_CYCLE anchors -----------------------------------------------------
    def anchor(name, values, long_name):
        v = ds.createVariable(name, "f8", ("N_CYCLE",), fill_value=JULD_F)
        v[:] = values
        v.setncattr("long_name", long_name)
        v.setncattr("standard_name", "time")
        v.setncattr("units", _UNITS_TIME)
        v.setncattr("conventions", _TITLE_TIME)
        v.setncattr("resolution", np.float64(0.01))

    def anchor_status(name, values, statuses):
        anchor(name, values, _ANCHOR_LONG[name])
        st = ds.createVariable(f"{name}_STATUS", "S1", ("N_CYCLE",), fill_value=np.bytes_(b" "))
        st[:] = np.array([s.encode() for s in statuses], dtype="S1")
        st.setncattr("long_name", f"Status of {_ANCHOR_LONG[name][0].lower() + _ANCHOR_LONG[name][1:]}")
        st.setncattr("conventions", "Argo reference table 19")

    n = n_cycle
    def _st(v):
        return "1" if v != JULD_FILL else "9"

    anchor_status("JULD_ASCENT_START", np.array([b.ascent_start for b in cyc], dtype=np.float64), [_st(b.ascent_start) for b in cyc])
    anchor_status("JULD_ASCENT_END", np.array([b.ascent_end for b in cyc], dtype=np.float64), [_st(b.ascent_end) for b in cyc])
    anchor_status("JULD_DESCENT_START", np.array([b.descent_start for b in cyc], dtype=np.float64), [_st(b.descent_start) for b in cyc])
    anchor_status("JULD_DESCENT_END", np.array([b.descent_end for b in cyc], dtype=np.float64), [_st(b.descent_end) for b in cyc])
    anchor_status("JULD_TRANSMISSION_START", np.array([b.transmission_start for b in cyc], dtype=np.float64), [_st(b.transmission_start) for b in cyc])
    anchor_status("JULD_FIRST_STABILIZATION", np.full(n, JULD_F, dtype=np.float64), ["9"] * n)
    anchor_status("JULD_PARK_START", np.array([b.park_start for b in cyc], dtype=np.float64), [_st(b.park_start) for b in cyc])
    anchor_status("JULD_PARK_END", np.array([b.park_end for b in cyc], dtype=np.float64), [_st(b.park_end) for b in cyc])
    anchor_status("JULD_DEEP_PARK_START", np.full(n, JULD_F, dtype=np.float64), ["9"] * n)
    anchor_status("JULD_DEEP_DESCENT_END", np.array([b.deep_descent_end for b in cyc], dtype=np.float64), [_st(b.deep_descent_end) for b in cyc])
    anchor_status("JULD_DEEP_ASCENT_START", np.full(n, JULD_F, dtype=np.float64), ["9"] * n)
    anchor_status("JULD_TRANSMISSION_END", np.array([b.transmission_end for b in cyc], dtype=np.float64), [_st(b.transmission_end) for b in cyc])
    anchor_status("JULD_FIRST_MESSAGE", np.array([b.first_message for b in cyc], dtype=np.float64), [_st(b.first_message) for b in cyc])
    anchor_status("JULD_FIRST_LOCATION", np.full(n, JULD_F, dtype=np.float64), ["9"] * n)
    anchor_status("JULD_LAST_MESSAGE", np.array([b.last_message for b in cyc], dtype=np.float64), [_st(b.last_message) for b in cyc])
    anchor_status("JULD_LAST_LOCATION", np.full(n, JULD_F, dtype=np.float64), ["9"] * n)

    co = ds.createVariable("CLOCK_OFFSET", "f8", ("N_CYCLE",), fill_value=JULD_F)
    co[:] = np.full(n, JULD_F, dtype=np.float64)
    co.setncattr("long_name", "Time of float clock drift")
    co.setncattr("units", "days")
    co.setncattr("conventions", "Days with decimal part (as parts of day)")
    gr = ds.createVariable("GROUNDED", "S1", ("N_CYCLE",), fill_value=np.bytes_(b" "))
    gr[:] = np.array([b.grounded.encode() for b in cyc], dtype="S1")
    gr.setncattr("long_name", "Did the profiler touch the ground for that cycle?")
    gr.setncattr("conventions", "Argo reference table 20")
    rp = ds.createVariable("REPRESENTATIVE_PARK_PRESSURE", "f4", ("N_CYCLE",), fill_value=FLOAT_FILL)
    rp[:] = np.full(n, FLOAT_FILL, dtype=np.float32)
    rp.setncattr("long_name", "Best pressure value during park phase")
    rp.setncattr("units", "decibar")
    rpl = ds.createVariable("REPRESENTATIVE_PARK_PRESSURE_STATUS", "S1", ("N_CYCLE",), fill_value=np.bytes_(b" "))
    rpl[:] = np.full(n, b" ", dtype="S1")
    rpl.setncattr("long_name", "Status of best pressure value during park phase")
    rpl.setncattr("conventions", "Argo reference table 21")
    cm = ds.createVariable("CONFIG_MISSION_NUMBER", "i4", ("N_CYCLE",), fill_value=INT_FILL)
    cm[:] = np.array(
        [b.config_mission_number if b.config_mission_number is not None else INT_FILL for b in cyc],
        dtype=np.int32,
    )
    cm.setncattr("long_name", "Unique number denoting the missions performed by the float")
    cm.setncattr("conventions", "1...N, 1 : first complete mission")
    ci = ds.createVariable("CYCLE_NUMBER_INDEX", "i4", ("N_CYCLE",), fill_value=INT_FILL)
    ci[:] = np.array([b.cycle for b in cyc], dtype=np.int32)
    ci.setncattr("long_name", "Cycle number that corresponds to the current index")
    ci.setncattr("conventions", "0...N, 0 : launch cycle, 1 : first complete cycle")
    cia = ds.createVariable("CYCLE_NUMBER_INDEX_ADJUSTED", "i4", ("N_CYCLE",), fill_value=INT_FILL)
    cia[:] = np.full(n, INT_FILL, dtype=np.int32)
    cia.setncattr("long_name", "Adjusted cycle number that corresponds to the current index")
    cia.setncattr("conventions", "0...N, 0 : launch cycle, 1 : first complete cycle")
    dm = ds.createVariable("DATA_MODE", "S1", ("N_CYCLE",), fill_value=np.bytes_(b" "))
    dm[:] = np.full(n, APF11_DATA_MODE.encode(), dtype="S1") if n else np.zeros((0,), dtype="S1")
    dm.setncattr("long_name", "Delayed mode or real time data")
    dm.setncattr("conventions", "R : real time; D : delayed mode; A : real time with adjustment")

    # ---- N_HISTORY (single empty row, as published) --------------------------
    _H_ATTRS = {
        "HISTORY_INSTITUTION": ("STRING4", "Institution which performed action", "Argo reference table 4"),
        "HISTORY_STEP": ("STRING4", "Step in data processing", "Argo reference table 12"),
        "HISTORY_SOFTWARE": ("STRING4", "Name of software which performed action", "Institution dependent"),
        "HISTORY_SOFTWARE_RELEASE": ("STRING4", "Version/release of software which performed action", "Institution dependent"),
        "HISTORY_REFERENCE": ("STRING64", "Reference of database", "Institution dependent"),
        "HISTORY_DATE": ("DATE_TIME", "Date the history record was created", "YYYYMMDDHHMISS"),
        "HISTORY_ACTION": ("STRING4", "Action performed on data", "Argo reference table 7"),
        "HISTORY_PARAMETER": ("STRING16", "Station parameter action is performed on", "Argo reference table 3"),
        "HISTORY_QCTEST": ("STRING16", "Documentation of tests performed, tests failed (in hex form)", "Write tests performed when ACTION=QCP$; tests failed when ACTION=QCF$"),
    }
    for name, (dim, ln, conv) in _H_ATTRS.items():
        v = ds.createVariable(name, "S1", ("N_HISTORY", dim), fill_value=np.bytes_(b" "))
        w = int(dim[6:]) if dim.startswith("STRING") else DATE_TIME
        v[:] = np.full((1, w), b" ", dtype="S1")
        v.setncattr("long_name", ln)
        v.setncattr("conventions", conv)
    v = ds.createVariable("HISTORY_INDEX_DIMENSION", "S1", ("N_HISTORY",), fill_value=np.bytes_(b" "))
    v[:] = np.array([b" "], dtype="S1")
    v.setncattr("long_name", "Name of dimension to which HISTORY_START_INDEX and HISTORY_STOP_INDEX correspond")
    v.setncattr("conventions", "C: N_CYCLE, M: N_MEASUREMENT")
    hpv = ds.createVariable("HISTORY_PREVIOUS_VALUE", "f4", ("N_HISTORY",), fill_value=FLOAT_FILL)
    hpv[:] = np.full(1, FLOAT_FILL, dtype=np.float32)
    hpv.setncattr("long_name", "Parameter/Flag previous value before action")
    hsi = ds.createVariable("HISTORY_START_INDEX", "i4", ("N_HISTORY",), fill_value=INT_FILL)
    hsi[:] = np.full(1, INT_FILL, dtype=np.int32)
    hsi.setncattr("long_name", "Start index action applied on")
    hti = ds.createVariable("HISTORY_STOP_INDEX", "i4", ("N_HISTORY",), fill_value=INT_FILL)
    hti[:] = np.full(1, INT_FILL, dtype=np.int32)
    hti.setncattr("long_name", "Stop index action applied on")
    # ---- globals --------------------------------------------------------------
    iso = lambda s: f"{s[:4]}-{s[4:6]}-{s[6:8]}T{s[8:10]}:{s[10:12]}:{s[12:14]}Z"
    ds.setncattr("title", "Argo float trajectory file")
    ds.setncattr("institution", data_centre)
    ds.setncattr("source", "Argo float")
    ds.setncattr("history", f"{iso(created)} creation")
    ds.setncattr("references", "http://www.argodatamgt.org/Documentation")
    ds.setncattr("user_manual_version", "3.1")
    ds.setncattr("Conventions", "Argo-3.1 CF-1.6")
    ds.setncattr("featureType", "trajectory")
    ds.setncattr("comment_on_resolution", "PRES variable resolution depends on measurement codes")
    return ds


_ANCHOR_LONG = {
    "JULD_ASCENT_START": "Start date of the ascent to the surface",
    "JULD_ASCENT_END": "End date of ascent to the surface",
    "JULD_DESCENT_START": "Descent start date of the cycle",
    "JULD_DESCENT_END": "Descent end date of the cycle",
    "JULD_TRANSMISSION_START": "Start date of transmission",
    "JULD_PARK_START": "Drift start date of the cycle",
    "JULD_PARK_END": "Drift end date of the cycle",
    "JULD_DEEP_PARK_START": "Deep park start date of the cycle",
    "JULD_DEEP_DESCENT_END": "Deep descent end date of the cycle",
    "JULD_DEEP_ASCENT_START": "Deep ascent start date of the cycle",
    "JULD_TRANSMISSION_END": "Transmission end date",
    "JULD_FIRST_MESSAGE": "Date of earliest float message received",
    "JULD_FIRST_LOCATION": "Date of earliest location",
    "JULD_LAST_MESSAGE": "Date of latest float message received",
    "JULD_LAST_LOCATION": "Date of latest location",
    "JULD_FIRST_STABILIZATION": "Time when a float first becomes water-neutral",
}


def write_traj_file(path: Path, traj: FloatTrajectory, **meta) -> Path:
    """Write ``<WMO>_Rtraj.nc`` (whole-file deterministic rewrite)."""

    ds = build_traj_dataset(traj, **meta)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        out = netCDF4.Dataset(str(path), mode="w", format=APF11_NC_FORMAT)
        for dim, d in ds.dimensions.items():
            out.createDimension(dim, None if d.isunlimited() else d.size)
        for name, var in ds.variables.items():
            kwargs = {}
            if "_FillValue" in var.ncattrs():
                kwargs["fill_value"] = var.getncattr("_FillValue")
            nv = out.createVariable(name, var.datatype, var.dimensions, **kwargs)
            for a in var.ncattrs():
                if a == "_FillValue":
                    continue
                nv.setncattr(a, var.getncattr(a))
            nv[:] = var[:]
        for a in ds.ncattrs():
            out.setncattr(a, ds.getncattr(a))
        out.close()
    finally:
        ds.close()
    return path


__all__ = ["build_traj_dataset", "write_traj_file"]
