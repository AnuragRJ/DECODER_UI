"""CTS4 ``<WMO>_Rtraj.nc`` writer — Phase-4 (supersedes the provisional (be)
builder; variable set mirrors GDAC ``2902086_Rtraj.nc``, Argo-3.1/CF-1.6,
real-time DATA_MODE 'R').

Structure (evidence: GDAC dump + Argo trajectory spec §2.3 + validated ARVOR-I
``rtraj_arvor.py`` conventions): N_MEASUREMENT unlimited rows with
JULD/STATUS/QC (+ADJUSTED twins), LATITUDE/LONGITUDE (+QC/accuracy),
CYCLE_NUMBER(+ADJUSTED), MEASUREMENT_CODE, TRAJECTORY_PARAMETER_DATA_MODE,
PRES(+QC, ADJUSTED), the 12 BGC trajectory parameters (+QC, ADJUSTED for the
delayed-adjustable ones), per-cycle N_CYCLE summary columns, SCIENTIFIC_CALIB
(from ExternalMeta), JULD_CALIB (blank), one HISTORY row.

No fabrication: unknown cells carry explicit fills (JULD 999999, positions
99999, status/QC ' ' or '9' per the adjudicated rules).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import netCDF4
import numpy as np

JULD_FILL = 999999.0
F_FILL = np.float32(99999.0)
D_FILL = np.float64(99999.0)
I_FILL = np.int32(99999)

TRAJ_PARAMS: tuple[str, ...] = (
    "PRES", "FLUORESCENCE_CHLA", "BETA_BACKSCATTERING700", "CHLA",
    "CHLA_FLUORESCENCE", "BBP700", "C1PHASE_DOXY", "C2PHASE_DOXY",
    "TEMP_DOXY", "DOXY", "TEMP", "PSAL",
)
#: Parameters carrying ADJUSTED twins in the GDAC file.
ADJUSTED_PARAMS: tuple[str, ...] = (
    "CHLA", "CHLA_FLUORESCENCE", "BBP700", "DOXY", "TEMP", "PSAL",
)
PARAM_UNITS: dict[str, tuple[str, str]] = {
    "FLUORESCENCE_CHLA": ("count", "%9.1f"),
    "BETA_BACKSCATTERING700": ("count", "%9.1f"),
    "CHLA": ("mg/m3", "%9.3f"),
    "CHLA_FLUORESCENCE": ("ru", "%9.3f"),
    "BBP700": ("m-1", "%9.6f"),
    "C1PHASE_DOXY": ("degree", "%9.3f"),
    "C2PHASE_DOXY": ("degree", "%9.3f"),
    "TEMP_DOXY": ("degree_Celsius", "%9.3f"),
    "DOXY": ("micromole/kg", "%9.3f"),
    "TEMP": ("degree_Celsius", "%9.3f"),
    "PSAL": ("psu", "%9.3f"),
}

#: Raw sensor channels no quality-control step is ever run on (Argo reference
#: table 2 code '0' = "no QC was performed"). Mirrors the R/BR profile writer.
_NO_QC_PERFORMED_PARAMS = frozenset({
    "C1PHASE_DOXY", "C2PHASE_DOXY", "FLUORESCENCE_CHLA", "BETA_BACKSCATTERING700",
})


_TRAJ_SPEC_ATTRS = {'DATA_TYPE': {'long_name': 'Data type', 'conventions': 'Argo reference table 1'}, 'FORMAT_VERSION': {'long_name': 'File format version'}, 'HANDBOOK_VERSION': {'long_name': 'Data handbook version'}, 'REFERENCE_DATE_TIME': {'long_name': 'Date of reference for Julian days', 'conventions': 'YYYYMMDDHHMISS'}, 'DATE_CREATION': {'long_name': 'Date of file creation', 'conventions': 'YYYYMMDDHHMISS'}, 'DATE_UPDATE': {'long_name': 'Date of update of this file', 'conventions': 'YYYYMMDDHHMISS'}, 'PLATFORM_NUMBER': {'long_name': 'Float unique identifier', 'conventions': 'WMO float identifier : A9IIIII'}, 'PROJECT_NAME': {'long_name': 'Name of the project'}, 'PI_NAME': {'long_name': 'Name of the principal investigator'}, 'TRAJECTORY_PARAMETERS': {'long_name': 'List of available parameters', 'conventions': 'Argo reference table 3'}, 'DATA_CENTRE': {'long_name': 'Data centre in charge of float data processing', 'conventions': 'Argo reference table 4'}, 'DATA_STATE_INDICATOR': {'long_name': 'Degree of processing the data have passed through', 'conventions': 'Argo reference table 6'}, 'PLATFORM_TYPE': {'long_name': 'Type of float', 'conventions': 'Argo reference table 23'}, 'FLOAT_SERIAL_NO': {'long_name': 'Serial number of the float'}, 'FIRMWARE_VERSION': {'long_name': 'Instrument firmware version'}, 'WMO_INST_TYPE': {'long_name': 'Coded instrument type', 'conventions': 'Argo reference table 8'}, 'POSITIONING_SYSTEM': {'long_name': 'Positioning system'}, 'JULD': {'long_name': 'Julian day (UTC) of each measurement relative to REFERENCE_DATE_TIME', 'standard_name': 'time', 'units': 'days since 1950-01-01 00:00:00 UTC', 'conventions': 'Relative julian days with decimal part (as parts of day)', 'axis': 'T'}, 'JULD_STATUS': {'long_name': 'Status of the date and time', 'conventions': 'Argo reference table 19'}, 'JULD_QC': {'long_name': 'Quality on date and time', 'conventions': 'Argo reference table 2'}, 'JULD_ADJUSTED': {'long_name': 'Adjusted julian day (UTC) of each measurement relative to REFERENCE_DATE_TIME', 'standard_name': 'time', 'units': 'days since 1950-01-01 00:00:00 UTC', 'conventions': 'Relative julian days with decimal part (as parts of day)', 'axis': 'T'}, 'JULD_ADJUSTED_STATUS': {'long_name': 'Status of the JULD_ADJUSTED date', 'conventions': 'Argo reference table 19'}, 'JULD_ADJUSTED_QC': {'long_name': 'Quality on adjusted date and time', 'conventions': 'Argo reference table 2'}, 'LATITUDE': {'long_name': 'Latitude of each location', 'standard_name': 'latitude', 'units': 'degree_north', 'valid_min': '-90.', 'valid_max': '90.', 'axis': 'Y'}, 'LONGITUDE': {'long_name': 'Longitude of each location', 'standard_name': 'longitude', 'units': 'degree_east', 'valid_min': '-180.', 'valid_max': '180.', 'axis': 'X'}, 'POSITION_ACCURACY': {'long_name': 'Estimated accuracy in latitude and longitude', 'conventions': 'Argo reference table 5'}, 'POSITION_QC': {'long_name': 'Quality on position', 'conventions': 'Argo reference table 2'}, 'CYCLE_NUMBER': {'long_name': 'Float cycle number of the measurement', 'conventions': '0...N, 0 : launch cycle, 1 : first complete cycle'}, 'CYCLE_NUMBER_ADJUSTED': {'long_name': 'Adjusted float cycle number of the measurement', 'conventions': '0...N, 0 : launch cycle, 1 : first complete cycle'}, 'MEASUREMENT_CODE': {'long_name': 'Flag referring to a measurement event in the cycle', 'conventions': 'Argo reference table 15'}, 'AXES_ERROR_ELLIPSE_MAJOR': {'long_name': 'Semi-major axis of error ellipse from positioning system', 'units': 'meters'}, 'AXES_ERROR_ELLIPSE_MINOR': {'long_name': 'Semi-minor axis of error ellipse from positioning system', 'units': 'meters'}, 'AXES_ERROR_ELLIPSE_ANGLE': {'long_name': 'Angle of error ellipse from positioning system', 'units': 'Degrees (from North when heading East)'}, 'SATELLITE_NAME': {'long_name': 'Satellite name from positioning system'}, 'TRAJECTORY_PARAMETER_DATA_MODE': {'long_name': 'Delayed mode or real time data', 'conventions': 'R : real time; D : delayed mode; A : real time with adjustment'}, 'JULD_DATA_MODE': {'long_name': 'Delayed mode or real time data', 'conventions': 'R : real time; D : delayed mode; A : real time with adjustment'}, 'JULD_DESCENT_START': {'long_name': 'Descent start date of the cycle', 'standard_name': 'time', 'units': 'days since 1950-01-01 00:00:00 UTC', 'conventions': 'Relative julian days with decimal part (as parts of day)'}, 'JULD_DESCENT_START_STATUS': {'long_name': 'Status of descent start date of the cycle', 'conventions': 'Argo reference table 19'}, 'JULD_FIRST_STABILIZATION': {'long_name': 'Time when a float first becomes water-neutral', 'standard_name': 'time', 'units': 'days since 1950-01-01 00:00:00 UTC', 'conventions': 'Relative julian days with decimal part (as parts of day)'}, 'JULD_FIRST_STABILIZATION_STATUS': {'long_name': 'Status of time when a float first becomes water-neutral', 'conventions': 'Argo reference table 19'}, 'JULD_DESCENT_END': {'long_name': 'Descent end date of the cycle', 'standard_name': 'time', 'units': 'days since 1950-01-01 00:00:00 UTC', 'conventions': 'Relative julian days with decimal part (as parts of day)'}, 'JULD_DESCENT_END_STATUS': {'long_name': 'Status of descent end date of the cycle', 'conventions': 'Argo reference table 19'}, 'JULD_PARK_START': {'long_name': 'Drift start date of the cycle', 'standard_name': 'time', 'units': 'days since 1950-01-01 00:00:00 UTC', 'conventions': 'Relative julian days with decimal part (as parts of day)'}, 'JULD_PARK_START_STATUS': {'long_name': 'Status of drift start date of the cycle', 'conventions': 'Argo reference table 19'}, 'JULD_PARK_END': {'long_name': 'Drift end date of the cycle', 'standard_name': 'time', 'units': 'days since 1950-01-01 00:00:00 UTC', 'conventions': 'Relative julian days with decimal part (as parts of day)'}, 'JULD_PARK_END_STATUS': {'long_name': 'Status of drift end date of the cycle', 'conventions': 'Argo reference table 19'}, 'JULD_DEEP_DESCENT_END': {'long_name': 'Deep descent end date of the cycle', 'standard_name': 'time', 'units': 'days since 1950-01-01 00:00:00 UTC', 'conventions': 'Relative julian days with decimal part (as parts of day)'}, 'JULD_DEEP_DESCENT_END_STATUS': {'long_name': 'Status of deep descent end date of the cycle', 'conventions': 'Argo reference table 19'}, 'JULD_DEEP_PARK_START': {'long_name': 'Deep park start date of the cycle', 'standard_name': 'time', 'units': 'days since 1950-01-01 00:00:00 UTC', 'conventions': 'Relative julian days with decimal part (as parts of day)'}, 'JULD_DEEP_PARK_START_STATUS': {'long_name': 'Status of deep park start date of the cycle', 'conventions': 'Argo reference table 19'}, 'JULD_ASCENT_START': {'long_name': 'Start date of the ascent to the surface', 'standard_name': 'time', 'units': 'days since 1950-01-01 00:00:00 UTC', 'conventions': 'Relative julian days with decimal part (as parts of day)'}, 'JULD_ASCENT_START_STATUS': {'long_name': 'Status of start date of the ascent to the surface', 'conventions': 'Argo reference table 19'}, 'JULD_DEEP_ASCENT_START': {'long_name': 'Deep ascent start date of the cycle', 'standard_name': 'time', 'units': 'days since 1950-01-01 00:00:00 UTC', 'conventions': 'Relative julian days with decimal part (as parts of day)'}, 'JULD_DEEP_ASCENT_START_STATUS': {'long_name': 'Status of deep ascent start date of the cycle', 'conventions': 'Argo reference table 19'}, 'JULD_ASCENT_END': {'long_name': 'End date of ascent to the surface', 'standard_name': 'time', 'units': 'days since 1950-01-01 00:00:00 UTC', 'conventions': 'Relative julian days with decimal part (as parts of day)'}, 'JULD_ASCENT_END_STATUS': {'long_name': 'Status of end date of ascent to the surface', 'conventions': 'Argo reference table 19'}, 'JULD_TRANSMISSION_START': {'long_name': 'Start date of transmission', 'standard_name': 'time', 'units': 'days since 1950-01-01 00:00:00 UTC', 'conventions': 'Relative julian days with decimal part (as parts of day)'}, 'JULD_TRANSMISSION_START_STATUS': {'long_name': 'Status of start date of transmission', 'conventions': 'Argo reference table 19'}, 'JULD_FIRST_MESSAGE': {'long_name': 'Date of earliest float message received', 'standard_name': 'time', 'units': 'days since 1950-01-01 00:00:00 UTC', 'conventions': 'Relative julian days with decimal part (as parts of day)'}, 'JULD_FIRST_MESSAGE_STATUS': {'long_name': 'Status of date of earliest float message received', 'conventions': 'Argo reference table 19'}, 'JULD_FIRST_LOCATION': {'long_name': 'Date of earliest location', 'standard_name': 'time', 'units': 'days since 1950-01-01 00:00:00 UTC', 'conventions': 'Relative julian days with decimal part (as parts of day)'}, 'JULD_FIRST_LOCATION_STATUS': {'long_name': 'Status of date of earliest location', 'conventions': 'Argo reference table 19'}, 'JULD_LAST_LOCATION': {'long_name': 'Date of latest location', 'standard_name': 'time', 'units': 'days since 1950-01-01 00:00:00 UTC', 'conventions': 'Relative julian days with decimal part (as parts of day)'}, 'JULD_LAST_LOCATION_STATUS': {'long_name': 'Status of date of latest location', 'conventions': 'Argo reference table 19'}, 'JULD_LAST_MESSAGE': {'long_name': 'Date of latest float message received', 'standard_name': 'time', 'units': 'days since 1950-01-01 00:00:00 UTC', 'conventions': 'Relative julian days with decimal part (as parts of day)'}, 'JULD_LAST_MESSAGE_STATUS': {'long_name': 'Status of date of latest float message received', 'conventions': 'Argo reference table 19'}, 'JULD_TRANSMISSION_END': {'long_name': 'Transmission end date', 'standard_name': 'time', 'units': 'days since 1950-01-01 00:00:00 UTC', 'conventions': 'Relative julian days with decimal part (as parts of day)'}, 'JULD_TRANSMISSION_END_STATUS': {'long_name': 'Status of transmission end date', 'conventions': 'Argo reference table 19'}, 'CLOCK_OFFSET': {'long_name': 'Time of float clock drift', 'units': 'days', 'conventions': 'Days with decimal part (as parts of day)'}, 'GROUNDED': {'long_name': 'Did the profiler touch the ground for that cycle?', 'conventions': 'Argo reference table 20'}, 'REPRESENTATIVE_PARK_PRESSURE': {'long_name': 'Best pressure value during park phase', 'units': 'decibar'}, 'REPRESENTATIVE_PARK_PRESSURE_STATUS': {'long_name': 'Status of best pressure value during park phase', 'conventions': 'Argo reference table 21'}, 'CONFIG_MISSION_NUMBER': {'long_name': 'Unique number denoting the missions performed by the float', 'conventions': '1...N, 1 : first complete mission'}, 'CYCLE_NUMBER_INDEX': {'long_name': 'Cycle number that corresponds to the current index', 'conventions': '0...N, 0 : launch cycle, 1 : first complete cycle'}, 'CYCLE_NUMBER_INDEX_ADJUSTED': {'long_name': 'Adjusted cycle number that corresponds to the current index', 'conventions': '0...N, 0 : launch cycle, 1 : first complete cycle'}, 'DATA_MODE': {'long_name': 'Delayed mode or real time data', 'conventions': 'R : real time; D : delayed mode; A : real time with adjustment'}, 'SCIENTIFIC_CALIB_PARAMETER': {'long_name': 'List of parameters with calibration information', 'conventions': 'Argo reference table 3'}, 'SCIENTIFIC_CALIB_EQUATION': {'long_name': 'Calibration equation for this parameter'}, 'SCIENTIFIC_CALIB_COEFFICIENT': {'long_name': 'Calibration coefficients for this equation'}, 'SCIENTIFIC_CALIB_COMMENT': {'long_name': 'Comment applying to this parameter calibration'}, 'SCIENTIFIC_CALIB_DATE': {'long_name': 'Date of calibration', 'conventions': 'YYYYMMDDHHMISS'}, 'JULD_CALIB_EQUATION': {'long_name': 'Calibration equation for JULD'}, 'JULD_CALIB_COEFFICIENT': {'long_name': 'Calibration coefficients for JULD equation'}, 'JULD_CALIB_COMMENT': {'long_name': 'Comment applying to JULD calibration'}, 'JULD_CALIB_DATE': {'long_name': 'Date of JULD calibration', 'conventions': 'YYYYMMDDHHMISS'}, 'HISTORY_INSTITUTION': {'long_name': 'Institution which performed action', 'conventions': 'Argo reference table 4'}, 'HISTORY_STEP': {'long_name': 'Step in data processing', 'conventions': 'Argo reference table 12'}, 'HISTORY_SOFTWARE': {'long_name': 'Name of software which performed action', 'conventions': 'Institution dependent'}, 'HISTORY_SOFTWARE_RELEASE': {'long_name': 'Version/release of software which performed action', 'conventions': 'Institution dependent'}, 'HISTORY_REFERENCE': {'long_name': 'Reference of database', 'conventions': 'Institution dependent'}, 'HISTORY_DATE': {'long_name': 'Date the history record was created', 'conventions': 'YYYYMMDDHHMISS'}, 'HISTORY_ACTION': {'long_name': 'Action performed on data', 'conventions': 'Argo reference table 7'}, 'HISTORY_PARAMETER': {'long_name': 'Parameter action is performed on', 'conventions': 'Argo reference table 3'}, 'HISTORY_INDEX_DIMENSION': {'long_name': 'Name of dimension to which HISTORY_START_INDEX and HISTORY_STOP_INDEX correspond', 'conventions': 'C: N_CYCLE, M: N_MEASUREMENT'}, 'HISTORY_START_INDEX': {'long_name': 'Start index action applied on'}, 'HISTORY_STOP_INDEX': {'long_name': 'Stop index action applied on'}, 'HISTORY_QCTEST': {'long_name': 'Documentation of tests performed, tests failed (in hex form)', 'conventions': 'Write tests performed when ACTION=QCP$; tests failed when ACTION=QCF$'}}

_NCYCLE_JULDS: tuple[str, ...] = (
    "JULD_DESCENT_START", "JULD_FIRST_STABILIZATION", "JULD_DESCENT_END",
    "JULD_PARK_START", "JULD_PARK_END", "JULD_DEEP_DESCENT_END",
    "JULD_DEEP_PARK_START", "JULD_ASCENT_START", "JULD_DEEP_ASCENT_START",
    "JULD_ASCENT_END", "JULD_TRANSMISSION_START", "JULD_FIRST_MESSAGE",
    "JULD_FIRST_LOCATION", "JULD_LAST_LOCATION", "JULD_LAST_MESSAGE",
    "JULD_TRANSMISSION_END",
)

_STRING_DIMS = {"STRING2": 2, "STRING4": 4, "STRING8": 8, "STRING16": 16,
                "STRING32": 32, "STRING64": 64, "STRING256": 256}


def _char(ds, name, value, dim, attrs=None, dims=None):
    length = 14 if dim == "DATE_TIME" else _STRING_DIMS[dim]
    var = ds.createVariable(name, "S1", (dims or (dim,)), fill_value=b" ")
    padded = str(value).ljust(length)[:length]
    var[:] = np.frombuffer(padded.encode("ascii"), dtype="S1")
    for k, v in (attrs or {}).items():
        var.setncattr(k, v)
    return var


def _now() -> str:
    return datetime.now(UTC).strftime("%Y%m%d%H%M%S")


def write_cts4_rtraj(
    path: Path | str,
    rows,                       # list[rtraj_build.RtrajRow]
    cycle_summaries,            # list[Cts4RtrajCycleSummary]
    external_meta,              # writer.nc.ExternalMeta
    wmo: str,                   # externally supplied; never derived from IMEI
    institution: str = "IN",
    decoder_version: str = "PY-301-0.4.0",
    calib_by_param: dict[str, dict[str, str]] | None = None,
) -> Path:
    """Write the float-level accumulating Rtraj file (rebuilt per run)."""
    import re

    from argo_decoder.writer.nc import ExternalMeta

    if not isinstance(external_meta, ExternalMeta):
        raise ValueError("write_cts4_rtraj requires ExternalMeta")
    if not re.fullmatch(r"[0-9]{7}", str(wmo)):
        raise ValueError(f"WMO must be exactly seven digits, got {wmo!r}")
    if not rows:
        raise ValueError("write_cts4_rtraj requires non-empty rows")

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = len(rows)
    ncyc = len(cycle_summaries)
    ds = netCDF4.Dataset(str(path), "w", format="NETCDF4_CLASSIC")
    for d, sz in _STRING_DIMS.items():
        ds.createDimension(d, sz)
    ds.createDimension("DATE_TIME", 14)
    ds.createDimension("N_MEASUREMENT", None)
    ds.createDimension("N_CYCLE", ncyc)
    ds.createDimension("N_PARAM", len(TRAJ_PARAMS))
    ds.createDimension("N_CALIB_PARAM", 1)
    ds.createDimension("N_CALIB_JULD", 1)
    ds.createDimension("N_HISTORY", 1)

    # ---- globals -----------------------------------------------------------
    ds.title = "Argo float trajectory file"
    ds.institution = institution
    ds.source = "Argo float"
    ds.history = f"{datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')} creation"
    ds.references = "http://www.argodatamgt.org/Documentation"
    # The trajectory format is 3.2, so the manual version must be the
    # matching 3.4 (FileChecker regex 3\.[4-9]...); declaring 3.1 alongside
    # Conventions 'Argo-3.2' was self-inconsistent and drew a warning on every
    # Rtraj. GDAC 2902093 Rtraj publishes 3.4 / Argo-3.2.
    ds.user_manual_version = "3.4"
    ds.Conventions = "Argo-3.2 CF-1.6"
    ds.featureType = "trajectory"
    ds.decoder_version = decoder_version

    _char(ds, "DATA_TYPE", "Argo trajectory", "STRING16",
          {"long_name": "Data type", "conventions": "Argo reference table 1"})
    _char(ds, "FORMAT_VERSION", "3.2", "STRING4",
          {"long_name": "File format version"})
    _char(ds, "HANDBOOK_VERSION", "1.2", "STRING4",
          {"long_name": "Data handbook version"})
    _char(ds, "REFERENCE_DATE_TIME", "19500101000000", "DATE_TIME",
          {"long_name": "Date of reference for Julian days",
           "conventions": "YYYYMMDDHHMISS"}, dims=("DATE_TIME",))
    _char(ds, "DATE_CREATION", _now(), "DATE_TIME",
          {"long_name": "Date of file creation",
           "conventions": "YYYYMMDDHHMISS"}, dims=("DATE_TIME",))
    _char(ds, "DATE_UPDATE", _now(), "DATE_TIME",
          {"long_name": "Date of update of this file",
           "conventions": "YYYYMMDDHHMISS"}, dims=("DATE_TIME",))
    _char(ds, "PLATFORM_NUMBER", wmo, "STRING8",
          {"long_name": "Float unique identifier",
           "conventions": "WMO float identifier : A9IIIII"})
    _char(ds, "PROJECT_NAME", external_meta.project_name, "STRING64",
          {"long_name": "Name of the project"})
    _char(ds, "PI_NAME", external_meta.pi_name, "STRING64",
          {"long_name": "Name of the principal investigator"})
    tp = ds.createVariable("TRAJECTORY_PARAMETERS", "S1",
                           ("N_PARAM", "STRING64"), fill_value=b" ")
    arr = np.full((len(TRAJ_PARAMS), 64), b" ", dtype="S1")
    for i, p in enumerate(TRAJ_PARAMS):
        arr[i] = np.frombuffer(p.ljust(64).encode("ascii"), dtype="S1")
    tp[:] = arr
    tp.setncattr("long_name", "List of available parameters")
    tp.setncattr("conventions", "Argo reference table 3")
    _char(ds, "DATA_CENTRE", institution, "STRING2",
          {"long_name": "Data centre in charge of float data processing",
           "conventions": "Argo reference table 4"})
    _char(ds, "DATA_STATE_INDICATOR", "2B", "STRING4",
          {"long_name": "Degree of processing the data have passed through",
           "conventions": "Argo reference table 6"})
    _char(ds, "PLATFORM_TYPE", external_meta.platform_type, "STRING32",
          {"long_name": "Type of float",
           "conventions": "Argo reference table 23"})
    _char(ds, "FLOAT_SERIAL_NO", external_meta.float_serial_no, "STRING32",
          {"long_name": "Serial number of the float"})
    _char(ds, "FIRMWARE_VERSION", external_meta.firmware_version, "STRING64",
          {"long_name": "Instrument firmware version"})
    _char(ds, "WMO_INST_TYPE", external_meta.wmo_inst_type, "STRING4",
          {"long_name": "Coded instrument type",
           "conventions": "Argo reference table 8"})
    _pos = (external_meta.positioning_system or ("GPS",))[0]
    _char(ds, "POSITIONING_SYSTEM", _pos, "STRING8",
          {"long_name": "Positioning system"})

    # ---- measurement block --------------------------------------------------
    def col_d(name, values, fill=D_FILL, attrs=None):
        v = ds.createVariable(name, "f8", ("N_MEASUREMENT",), fill_value=fill)
        v[:] = np.asarray(values, dtype=np.float64)
        for k, a in (attrs or {}).items():
            v.setncattr(k, a)
        return v

    def col_f(name, values, attrs=None):
        v = ds.createVariable(name, "f4", ("N_MEASUREMENT",),
                              fill_value=float(F_FILL))
        v[:] = np.asarray(values, dtype=np.float32)
        for k, a in (attrs or {}).items():
            v.setncattr(k, a)
        return v

    def col_s1(name, values, attrs=None):
        v = ds.createVariable(name, "S1", ("N_MEASUREMENT",), fill_value=b" ")
        arr = np.array([str(x).encode("ascii")[:1].ljust(1, b" ")
                        for x in values], dtype="S1")
        v[:] = arr
        for k, a in (attrs or {}).items():
            v.setncattr(k, a)
        return v

    col_d("JULD", [r.juld for r in rows], JULD_FILL,
          {"long_name": "Julian day (UTC) of each measurement relative to REFERENCE_DATE_TIME",
           "standard_name": "time",
           "conventions": "Relative julian days with decimal part (as parts of day)",
           "units": "days since 1950-01-01 00:00:00 UTC",
           "C_format": "%17.5f",
           "FORTRAN_format": "F17.5", "resolution": 0.00001, "axis": "T"})
    col_s1("JULD_STATUS", [r.juld_status for r in rows],
           {"long_name": "Status of the date and time",
            "conventions": "Argo reference table 19"})
    col_s1("JULD_QC", [r.juld_qc for r in rows],
           {"long_name": "Quality on date and time",
            "conventions": "Argo reference table 2"})
    col_d("JULD_ADJUSTED", [JULD_FILL] * n, JULD_FILL,
          {"long_name": "Adjusted julian day (UTC) of each measurement relative to REFERENCE_DATE_TIME",
           "standard_name": "time",
           "conventions": "Relative julian days with decimal part (as parts of day)",
           "units": "days since 1950-01-01 00:00:00 UTC",
           "C_format": "%17.5f", "FORTRAN_format": "F17.5",
           "resolution": 0.00001, "axis": "T"})
    col_s1("JULD_ADJUSTED_STATUS", [" "] * n)
    col_s1("JULD_ADJUSTED_QC", [" "] * n)
    col_s1("JULD_DATA_MODE", ["R"] * n,
           {"long_name": "Delayed mode or real time data"})
    col_d("LATITUDE", [r.latitude for r in rows], D_FILL,
          {"long_name": "Latitude of each location", "units": "degree_north",
           "valid_min": -90.0, "valid_max": 90.0})
    col_d("LONGITUDE", [r.longitude for r in rows], D_FILL,
          {"long_name": "Longitude of each location",
           "units": "degree_east", "valid_min": -180.0, "valid_max": 180.0})
    col_s1("POSITION_ACCURACY", [r.position_accuracy for r in rows],
           {"long_name": "Estimated accuracy in latitude and longitude",
            "conventions": "Argo reference table 5"})
    col_s1("POSITION_QC", [r.position_qc for r in rows],
           {"long_name": "Quality on position",
            "conventions": "Argo reference table 2"})
    for nm in ("AXES_ERROR_ELLIPSE_MAJOR", "AXES_ERROR_ELLIPSE_MINOR",
               "AXES_ERROR_ELLIPSE_ANGLE"):
        col_f(nm, [99999.0] * n)
    sat = ds.createVariable("SATELLITE_NAME", "S1",
                            ("N_MEASUREMENT",), fill_value=b" ")
    sat[:] = np.full(n, b" ", dtype="S1")
    v = ds.createVariable("CYCLE_NUMBER", "i4", ("N_MEASUREMENT",),
                          fill_value=int(I_FILL))
    v[:] = np.asarray([r.cycle_number for r in rows], dtype=np.int32)
    v.setncattr("long_name", "Float cycle number of the measurement")
    v.setncattr("conventions", "0...N, 0 : launch cycle, 1 : first complete cycle")
    v2 = ds.createVariable("CYCLE_NUMBER_ADJUSTED", "i4", ("N_MEASUREMENT",),
                           fill_value=int(I_FILL))
    v2[:] = np.full(n, I_FILL, dtype=np.int32)
    v3 = ds.createVariable("MEASUREMENT_CODE", "i4", ("N_MEASUREMENT",),
                           fill_value=int(I_FILL))
    v3[:] = np.asarray([r.measurement_code for r in rows], dtype=np.int32)
    v3.setncattr("long_name", "Flag referring to a measurement event in the cycle")
    v3.setncattr("conventions", "Argo reference table 15")
    pdm = ds.createVariable("TRAJECTORY_PARAMETER_DATA_MODE", "S1",
                            ("N_MEASUREMENT", "N_PARAM"), fill_value=b" ")
    pdm_arr = np.full((n, len(TRAJ_PARAMS)), b" ", dtype="S1")
    for i, r in enumerate(rows):
        for j, pname in enumerate(TRAJ_PARAMS):
            filled = (pname == "PRES" and r.pres < 90000) or (
                pname != "PRES" and pname in r.params)
            pdm_arr[i, j] = b"R" if filled else b" "
    pdm[:] = pdm_arr
    col_f("PRES", [r.pres for r in rows],
          {"long_name": "Sea water pressure, equals 0 at sea-level",
           "standard_name": "sea_water_pressure", "units": "decibar",
           "valid_min": 0.0, "valid_max": 12000.0, "axis": "Z",
           "C_format": "%7.1f", "FORTRAN_format": "F7.1",
           "resolution": np.float32(0.1)})
    col_s1("PRES_QC", ["1" if r.pres < 90000 else " " for r in rows],
           {"long_name": "quality flag",
            "conventions": "Argo reference table 2"})
    col_f("PRES_ADJUSTED", [99999.0] * n,
          {"long_name": "Sea water pressure, equals 0 at sea-level",
           "standard_name": "sea_water_pressure", "units": "decibar",
           "valid_min": 0.0, "valid_max": 12000.0, "axis": "Z",
           "C_format": "%7.1f", "FORTRAN_format": "F7.1",
           "resolution": np.float32(0.1)})
    col_s1("PRES_ADJUSTED_QC", [" "] * n,
           {"long_name": "quality flag",
            "conventions": "Argo reference table 2"})
    col_f("PRES_ADJUSTED_ERROR", [99999.0] * n,
          {"long_name": "Contains the error on the adjusted values as "
                        "determined by the delayed mode QC process",
           "units": "decibar", "C_format": "%7.1f",
           "FORTRAN_format": "F7.1", "resolution": np.float32(0.1)})

    _traj_ln = {
        "FLUORESCENCE_CHLA": "Chlorophyll-A signal from fluorescence sensor",
        "BETA_BACKSCATTERING700": "Total angle specific volume from backscattering sensor at 700 nanometers",
        "CHLA": "Chlorophyll-A",
        "CHLA_FLUORESCENCE": "Chlorophyll fluorescence with factory calibration",
        "BBP700": "Particle backscattering at 700 nanometers",
        "C1PHASE_DOXY": "Uncalibrated phase shift reported by oxygen sensor",
        "C2PHASE_DOXY": "Uncalibrated phase shift reported by oxygen sensor",
        "TEMP_DOXY": "Sea temperature from oxygen sensor ITS-90 scale",
        "DOXY": "Dissolved oxygen",
        "TEMP": "Sea temperature in-situ ITS-90 scale",
        "PSAL": "Practical salinity",
    }
    for pname in TRAJ_PARAMS[1:]:
        units, cfmt = PARAM_UNITS[pname]
        ffmt = ("F" + cfmt[1:]) if cfmt.startswith("%") else "F9.3"
        _base_attrs = {"long_name": _traj_ln[pname], "units": units,
                       "C_format": cfmt, "FORTRAN_format": ffmt,
                       "resolution": np.float32(0.001)}
        if pname == "TEMP_DOXY":
            _base_attrs["standard_name"] = ("temperature_of_sensor_for_oxygen"
                                            "_in_sea_water")
            _base_attrs["valid_min"] = np.float32(-2.0)
            _base_attrs["valid_max"] = np.float32(40.0)
        elif pname in ("TEMP",):
            _base_attrs["standard_name"] = "sea_water_temperature"
            _base_attrs["valid_min"] = np.float32(-2.5)
            _base_attrs["valid_max"] = np.float32(40.0)
        elif pname == "PSAL":
            _base_attrs["standard_name"] = "sea_water_salinity"
            _base_attrs["valid_min"] = np.float32(2.0)
            _base_attrs["valid_max"] = np.float32(41.0)
        elif pname == "DOXY":
            _base_attrs["standard_name"] = ("moles_of_oxygen_per_unit_mass"
                                            "_in_sea_water")
            _base_attrs["valid_min"] = np.float32(-5.0)
            _base_attrs["valid_max"] = np.float32(600.0)
        elif pname == "C1PHASE_DOXY":
            _base_attrs["valid_min"] = np.float32(10.0)
            _base_attrs["valid_max"] = np.float32(70.0)
        elif pname == "C2PHASE_DOXY":
            _base_attrs["valid_min"] = np.float32(0.0)
            _base_attrs["valid_max"] = np.float32(15.0)
        elif pname == "CHLA_FLUORESCENCE":
            _base_attrs["valid_min"] = np.float32(-0.2)
            _base_attrs["valid_max"] = np.float32(100.0)
        elif pname == "CHLA":
            _base_attrs["standard_name"] = ("mass_concentration_of_"
                                            "chlorophyll_a_in_sea_water")
            # No valid_min/valid_max: the INCOIS spec does not permit them on
            # CHLA (FileChecker "Attribute is not allowed ... WILL BECOME AN
            # ERROR"), matching the BR writer fix.
        col_f(pname, [r.params.get(pname, 99999.0) for r in rows], _base_attrs)
        # Argo reference table 2: '0' = no QC was performed, '1' = good. A
        # real-time trajectory has had no quality control run on it, so
        # Coriolis initialises every parameter's QC to g_decArgo_qcStrNoQc
        # ('0') and only RTQC ever upgrades it (add_rtqc_to_profile_file.m:
        # 1809-1816, init_default_values.m:1015). The four raw channels keep
        # '0' permanently; TEMP_DOXY / DOXY / CHLA reach '1' or '3'. Verified
        # against INCOIS 2902093 Rtraj, which publishes exactly that split.
        _row_qc = ("0" if pname in _NO_QC_PERFORMED_PARAMS else "1")
        col_s1(f"{pname}_QC",
               [_row_qc if pname in r.params else " " for r in rows],
               {"long_name": "quality flag",
                "conventions": "Argo reference table 2"})
        if pname in ADJUSTED_PARAMS:
            col_f(f"{pname}_ADJUSTED", [99999.0] * n, dict(_base_attrs))
            col_s1(f"{pname}_ADJUSTED_QC", [" "] * n,
                   {"long_name": "quality flag",
                    "conventions": "Argo reference table 2"})
            _err = dict(_base_attrs)
            _err["long_name"] = ("Contains the error on the adjusted values "
                                 "as determined by the delayed mode QC process")
            col_f(f"{pname}_ADJUSTED_ERROR", [99999.0] * n, _err)

    # ---- N_CYCLE summary block ----------------------------------------------
    def cyc_d(name, values, fill=D_FILL):
        v = ds.createVariable(name, "f8", ("N_CYCLE",), fill_value=fill)
        v[:] = np.asarray(values, dtype=np.float64)
        return v

    def cyc_s1(name, values):
        v = ds.createVariable(name, "S1", ("N_CYCLE",), fill_value=b" ")
        v[:] = np.array([str(x).encode("ascii")[:1].ljust(1, b" ")
                         for x in values], dtype="S1")
        return v

    for nm in _NCYCLE_JULDS:
        _v = cyc_d(nm, [getattr(c, nm.lower(), JULD_FILL) for c in cycle_summaries],
                   JULD_FILL)
        _v.setncattr("resolution", np.float64(1e-5))
        cyc_s1(f"{nm}_STATUS",
               [getattr(c, f"{nm.lower()}_status", " ") for c in cycle_summaries])
    _v = cyc_d("CLOCK_OFFSET", [JULD_FILL] * ncyc, JULD_FILL)
    _v.setncattr("resolution", np.float64(1e-5))
    cyc_s1("GROUNDED", [getattr(c, "grounded", " ") for c in cycle_summaries])
    v = ds.createVariable("REPRESENTATIVE_PARK_PRESSURE", "f4", ("N_CYCLE",),
                          fill_value=float(F_FILL))
    v[:] = np.asarray([getattr(c, "representative_park_pressure", 99999.0)
                       for c in cycle_summaries], dtype=np.float32)
    cyc_s1("REPRESENTATIVE_PARK_PRESSURE_STATUS",
           [getattr(c, "representative_park_pressure_status", " ")
            for c in cycle_summaries])
    v = ds.createVariable("CONFIG_MISSION_NUMBER", "i4", ("N_CYCLE",),
                          fill_value=int(I_FILL))
    v[:] = np.asarray([getattr(c, "config_mission_number", 99999)
                       for c in cycle_summaries], dtype=np.int32)
    v = ds.createVariable("CYCLE_NUMBER_INDEX", "i4", ("N_CYCLE",),
                          fill_value=int(I_FILL))
    v[:] = np.asarray([c.cycle_number_index for c in cycle_summaries],
                      dtype=np.int32)
    v = ds.createVariable("CYCLE_NUMBER_INDEX_ADJUSTED", "i4", ("N_CYCLE",),
                          fill_value=int(I_FILL))
    v[:] = np.full(ncyc, I_FILL, dtype=np.int32)
    cyc_s1("DATA_MODE", [c.data_mode for c in cycle_summaries])

    # ---- calibration + history ----------------------------------------------
    def cal256(name, values):
        v = ds.createVariable(name, "S1",
                              ("N_CALIB_PARAM", "N_PARAM", "STRING256"),
                              fill_value=b" ")
        arr = np.full((1, len(TRAJ_PARAMS), 256), b" ", dtype="S1")
        for j, pname in enumerate(TRAJ_PARAMS):
            s = (values.get(pname, "") or "").ljust(256)[:256]
            arr[0, j] = np.frombuffer(s.encode("ascii", "replace"), dtype="S1")
        v[:] = arr
        return v

    calib_by_param = calib_by_param or {}
    v = ds.createVariable("SCIENTIFIC_CALIB_PARAMETER", "S1",
                          ("N_CALIB_PARAM", "N_PARAM", "STRING64"),
                          fill_value=b" ")
    arr = np.full((1, len(TRAJ_PARAMS), 64), b" ", dtype="S1")
    for j, pname in enumerate(TRAJ_PARAMS):
        arr[0, j] = np.frombuffer(pname.ljust(64).encode("ascii"), dtype="S1")
    v[:] = arr
    v.setncattr("long_name", "List of parameters with calibration information")
    v.setncattr("conventions", "Argo reference table 3")
    cal256("SCIENTIFIC_CALIB_EQUATION",
           {p: calib_by_param.get(p, {}).get("equation", "") for p in TRAJ_PARAMS})
    cal256("SCIENTIFIC_CALIB_COEFFICIENT",
           {p: calib_by_param.get(p, {}).get("coefficient", "") for p in TRAJ_PARAMS})
    cal256("SCIENTIFIC_CALIB_COMMENT",
           {p: calib_by_param.get(p, {}).get("comment", "") for p in TRAJ_PARAMS})
    v = ds.createVariable("SCIENTIFIC_CALIB_DATE", "S1",
                          ("N_CALIB_PARAM", "N_PARAM", "DATE_TIME"),
                          fill_value=b" ")
    arr = np.full((1, len(TRAJ_PARAMS), 14), b" ", dtype="S1")
    for j, pname in enumerate(TRAJ_PARAMS):
        s = (calib_by_param.get(pname, {}).get("date", "") or "").ljust(14)[:14]
        arr[0, j] = np.frombuffer(s.encode("ascii", "replace"), dtype="S1")
    v[:] = arr
    for nm in ("JULD_CALIB_EQUATION", "JULD_CALIB_COEFFICIENT",
               "JULD_CALIB_COMMENT"):
        vv = ds.createVariable(nm, "S1", ("N_CALIB_JULD", "STRING256"),
                               fill_value=b" ")
        vv[:] = np.full((1, 256), b" ", dtype="S1")
    vv = ds.createVariable("JULD_CALIB_DATE", "S1",
                           ("N_CALIB_JULD", "DATE_TIME"), fill_value=b" ")
    vv[:] = np.full((1, 14), b" ", dtype="S1")

    hist_strings = {
        "HISTORY_INSTITUTION": institution,
        "HISTORY_STEP": " ",
        "HISTORY_SOFTWARE": "PY301",
        "HISTORY_SOFTWARE_RELEASE": decoder_version,
        "HISTORY_REFERENCE": " ",
        "HISTORY_ACTION": "C",
        "HISTORY_PARAMETER": " ",
        "HISTORY_INDEX_DIMENSION": " ",
        "HISTORY_QCTEST": " ",
    }
    for nm, val in hist_strings.items():
        if nm == "HISTORY_INDEX_DIMENSION":
            continue
        dim = "STRING64" if nm in ("HISTORY_REFERENCE", "HISTORY_PARAMETER") \
            else "STRING16" if nm == "HISTORY_QCTEST" else "STRING4"
        v = ds.createVariable(nm, "S1", ("N_HISTORY", dim), fill_value=b" ")
        arr = np.full((1, _STRING_DIMS[dim]), b" ", dtype="S1")
        arr[0] = np.frombuffer(str(val).ljust(_STRING_DIMS[dim])[
            :_STRING_DIMS[dim]].encode("ascii"), dtype="S1")
        v[:] = arr
    v = ds.createVariable("HISTORY_INDEX_DIMENSION", "S1", ("N_HISTORY",),
                          fill_value=b" ")
    v[:] = np.array([b" "], dtype="S1")
    v = ds.createVariable("HISTORY_DATE", "S1", ("N_HISTORY", "DATE_TIME"),
                          fill_value=b" ")
    arr = np.full((1, 14), b" ", dtype="S1")
    arr[0] = np.frombuffer(_now().encode("ascii"), dtype="S1")
    v[:] = arr
    v = ds.createVariable("HISTORY_PREVIOUS_VALUE", "f4", ("N_HISTORY",),
                          fill_value=float(F_FILL))
    v[:] = np.array([99999.0], dtype=np.float32)
    v.setncattr("long_name", "Parameter/Flag previous value before action")
    v = ds.createVariable("HISTORY_START_INDEX", "i4", ("N_HISTORY",),
                          fill_value=int(I_FILL))
    v[:] = np.array([1], dtype=np.int32)
    v.setncattr("long_name", "Start index action applied on")
    v = ds.createVariable("HISTORY_STOP_INDEX", "i4", ("N_HISTORY",),
                          fill_value=int(I_FILL))
    v[:] = np.array([n], dtype=np.int32)
    v.setncattr("long_name", "Stop index action applied on")

    # --- spec-attribute completion pass (trajectory v3.2 CDL) ---------------
    for _vn, _attrs in _TRAJ_SPEC_ATTRS.items():
        if _vn in ds.variables:
            _v = ds.variables[_vn]
            for _k, _val in _attrs.items():
                if _k in _v.ncattrs():
                    continue
                try:
                    _num = float(_val)
                    _v.setncattr(_k, _num)
                except (TypeError, ValueError):
                    _v.setncattr(_k, _val)
    # base -> ADJUSTED / ADJUSTED_ERROR attribute mirroring
    for _pname in ("PRES",) + TRAJ_PARAMS[1:]:
        if _pname not in ds.variables:
            continue
        _base = ds.variables[_pname]
        for _suf in ("_ADJUSTED", "_ADJUSTED_ERROR"):
            _t = ds.variables.get(_pname + _suf)
            if _t is None:
                continue
            for _k in ("standard_name", "units", "C_format", "FORTRAN_format",
                       "resolution", "valid_min", "valid_max"):
                if _k in _base.ncattrs() and _k not in _t.ncattrs():
                    _t.setncattr(_k, _base.getncattr(_k))
    ds.close()
    return path
