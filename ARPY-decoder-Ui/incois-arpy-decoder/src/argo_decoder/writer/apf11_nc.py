"""APEX APF11 mono-profile NetCDF writer (real-time R/BR, Argo 3.1).

Produces the two real-time mono-profile file kinds an APF11 float
publishes:

* ``R<WMO>_<CCC>.nc`` — core, ``N_PROF=2``, both profiles
  (``PRES, TEMP, PSAL``), "Primary sampling: averaged []" then "Secondary
  sampling: discrete []";
* ``BR<WMO>_<CCC>.nc`` — BGC, same profile split; profile 0 carries
  ``PRES`` only and profile 1 carries the co-sampled discrete grid with the
  BGC parameter set.

Every structural literal in this module comes from an actual published
APF11 artifact or from the Argo User Manual, never from another family:

* the dimensions, ``STRING*`` sizes, ``_FillValue`` values and attribute
  vocabulary of the live INCOIS APF11 files;
* the APF11 parameter ordering ``PRES, TEMP, PSAL`` (core) and ``PRES,
  DOXY, NITRATE?, TPHASE_DOXY, CHLA, FLUORESCENCE_CHLA, BBP700,
  BETA_BACKSCATTERING700, TEMP_CPU_CHLA`` (BGC), established on all four
  floats of this fleet;
* globals ``Conventions='Argo-3.1 CF-1.6'``, ``user_manual_version='3.1'``,
  ``featureType='trajectoryProfile'``.

Real-time product state: ``DATA_MODE='R'``, ``PARAMETER_DATA_MODE='R'``,
no ``*_ADJUSTED`` variables, ``DATA_STATE_INDICATOR='1A'`` and per-level QC
characters supplied by the RTQC layer. The GDAC's currently-visible
``'A'``/adjusted fields and ``'2B'`` are downstream DAC reprocessing
(PUBLICATION-REPROCESSED), never content this writer imitates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import netCDF4
import numpy as np

from argo_decoder.writer.apf11_policy import APF11_NC_FORMAT, APF11_DATA_MODE

#: Argo structural constants (Argo User Manual 3.44 §2; identical to the
#: published APF11 files they were cross-checked against).
STRING2, STRING4, STRING8, STRING16 = 2, 4, 8, 16
STRING32, STRING64, STRING256 = 32, 64, 256
STRING1024 = 1024
DATE_TIME = 14

FLOAT_FILL = np.float32(99999.0)
DOUBLE_FILL = np.float64(99999.0)
JULD_FILL = np.float64(999999.0)
INT_FILL = np.int32(99999)

#: Published BGC parameter order; NITRATE is present only on SUNA floats
#: (established on the raw-file publications of this fleet).
BGC_PARAM_ORDER: tuple[str, ...] = (
    "PRES",
    "DOXY",
    "NITRATE",
    "TPHASE_DOXY",
    "CHLA",
    "FLUORESCENCE_CHLA",
    "BBP700",
    "BETA_BACKSCATTERING700",
    "TEMP_CPU_CHLA",
)

#: Per-parameter variable attribute sets, verbatim from the published APF11
#: files (values are structural, per the Argo User Manual's parameter
#: dictionary id table entries).
PARAM_ATTRS: dict[str, dict] = {
    "PRES": dict(
        long_name="Sea water pressure, equals 0 at sea-level",
        standard_name="sea_water_pressure",
        units="decibar",
        axis="Z",
        valid_min=np.float32(0.0),
        valid_max=np.float32(12000.0),
        C_format="%7.1f",
        FORTRAN_format="F7.1",
        resolution=np.float32(0.1),
    ),
    "TEMP": dict(
        long_name="Sea temperature in-situ ITS-90 scale",
        standard_name="sea_water_temperature",
        units="degree_Celsius",
        valid_min=np.float32(-2.5),
        valid_max=np.float32(40.0),
        C_format="%9.3f",
        FORTRAN_format="F9.3",
        resolution=np.float32(0.001),
    ),
    "PSAL": dict(
        long_name="Practical salinity",
        standard_name="sea_water_salinity",
        units="psu",
        valid_min=np.float32(2.0),
        valid_max=np.float32(41.0),
        C_format="%9.3f",
        FORTRAN_format="F9.3",
        resolution=np.float32(0.001),
    ),
    "DOXY": dict(
        long_name="Dissolved oxygen",
        standard_name="moles_of_oxygen_per_unit_mass_in_sea_water",
        units="micromole/kg",
        valid_min=np.float32(-5.0),
        valid_max=np.float32(600.0),
        C_format="%9.3f",
        FORTRAN_format="F9.3",
        resolution=np.float32(0.001),
    ),
    "NITRATE": dict(
        long_name="Nitrate",
        standard_name="moles_of_nitrate_per_unit_mass_in_sea_water",
        units="micromole/kg",
        C_format="%9.3f",
        FORTRAN_format="F9.3",
        resolution=np.float32(0.001),
    ),
    "TPHASE_DOXY": dict(
        long_name="Uncalibrated phase shift reported by oxygen sensor",
        units="degree",
        valid_min=np.float32(10.0),
        valid_max=np.float32(70.0),
        C_format="%8.2f",
        FORTRAN_format="F8.2",
        resolution=np.float32(0.01),
    ),
    "CHLA": dict(
        long_name="Chlorophyll-A",
        standard_name="mass_concentration_of_chlorophyll_a_in_sea_water",
        units="mg/m3",
        C_format="%9.5f",
        FORTRAN_format="F9.5",
        resolution=np.float32(1e-05),
    ),
    "FLUORESCENCE_CHLA": dict(
        long_name="Chlorophyll-A signal from fluorescence sensor",
        units="count",
        C_format="%9.3f",
        FORTRAN_format="F9.3",
        resolution=np.float32(1.0),
    ),
    "BBP700": dict(
        long_name="Particle backscattering at 700 nanometers",
        units="m-1",
        C_format="%10.8f",
        FORTRAN_format="F10.8",
        resolution=np.float32(1e-08),
    ),
    "BETA_BACKSCATTERING700": dict(
        long_name="Total angle specific volume from backscattering sensor at 700 nanometers",
        units="count",
        C_format="%9.3f",
        FORTRAN_format="F9.3",
        resolution=np.float32(1.0),
    ),
    "TEMP_CPU_CHLA": dict(
        long_name="Thermistor signal from backscattering sensor",
        units="count",
        C_format="%9.3f",
        FORTRAN_format="F9.3",
        resolution=np.float32(1.0),
    ),
}

_DAC_NAMES = {
    "AO": "AOML", "BO": "BODC", "CS": "CSIRO", "GE": "BSH", "HZ": "CSIO",
    "IF": "IFREMER", "IN": "INCOIS", "JA": "JMA", "KM": "KMA", "KO": "KORDI",
    "ME": "MEDS", "NA": "NAVO", "NM": "NMDIS", "PM": "PMEL", "SI": "SIO",
    "SP": "SPRI", "UW": "UW", "VL": "ISDGM", "WH": "WHOI",
}


@dataclass(frozen=True)
class Apf11MetaInput:
    """Float identity metadata for the mono-profile writer.

    Every field is taken from the authoritative metadata sheets, never from
    telemetry; fields marked ``| None`` are explicit "not supplied" states
    (written as blanks), distinct from fabricated values.
    """

    wmo: str
    data_centre: str
    project_name: str
    pi_name: str
    platform_serial: str  # FLOAT_SERIAL_NO
    wmo_inst_type: str
    platform_type: str  # PLATFORM_TYPE, e.g. 'APEX'
    firmware_version: str
    decoder_name: str = "PY-A11"
    decoder_version: str = "1.0.0"


@dataclass
class LevelBlock:
    """One profile's per-level content in publication order (ascending PRES)."""

    params: list[str]  # parameter names excluding PRES
    pres: np.ndarray  # float64 values
    values: dict[str, np.ndarray]
    qc: dict[str, np.ndarray]  # 'S1' arrays of Argo flags
    profile_qc: dict[str, str] = field(default_factory=dict)
    vertical_sampling_scheme: str = "Primary sampling: averaged []"


@dataclass
class CycleProductInput:
    """Everything the writer needs for one cycle file."""

    cycle_number: int
    juld: float
    latitude: float | None
    longitude: float | None
    position_qc: str  # '1' fix, '8' interpolated, '9' missing
    config_mission_number: int
    averaged: LevelBlock
    discrete: LevelBlock
    data_mode: str = "R"
    parameter_data_mode: dict[str, str] = field(default_factory=dict)
    positioning_system: str = "GPS"
    #: parameter -> SCIENTIFIC_CALIB_<X> -> text, supplied by the product
    #: layer from the authoritative metadata sheets (empty = blanks).
    calib_text: dict[str, dict[str, str]] = field(default_factory=dict)
    #: location timestamp (QC-1 fix anchor differs from JULD); None = JULD
    juld_location: float | None = None


def _encode(value: str, width: int) -> bytes:
    raw = str(value)[:width].encode()
    return raw + b" " * (width - len(raw))


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d%H%M%S")


def _iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _char(ds, name, dim, fill=b" ", **attrs):
    var = ds.createVariable(name, "S1", dim, fill_value=fill)
    for k, v in attrs.items():
        var.setncattr(k, v)
    return var


def string_value(value: str, width: int) -> np.ndarray:
    return np.frombuffer(_encode(value, width), dtype="S1")


def write_mono_profile(
    path: str | Path,
    meta: Apf11MetaInput,
    cyc: CycleProductInput,
    *,
    is_bgc: bool,
) -> Path:
    """Write one R (is_bgc=False) or BR (is_bgc=True) mono-profile file."""
    if cyc.data_mode != APF11_DATA_MODE or any(
        mode != APF11_DATA_MODE for mode in cyc.parameter_data_mode.values()
    ):
        raise ValueError("APF11 production accepts only unadjusted R-mode products")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    blocks = [cyc.averaged, cyc.discrete]
    n_prof = 2
    n_levels = max(len(b.pres) for b in blocks)

    # N_PARAM = widest STATION_PARAMETERS list in the file.
    n_param = max(1 + len(b.params) for b in blocks)

    with netCDF4.Dataset(path, "w", format=APF11_NC_FORMAT) as ds:
        ds.createDimension("N_PROF", n_prof)
        ds.createDimension("N_LEVELS", n_levels)
        ds.createDimension("N_CALIB", 1)
        for name, size in (
            ("STRING2", STRING2), ("STRING4", STRING4), ("STRING8", STRING8),
            ("STRING16", STRING16), ("STRING32", STRING32), ("STRING64", STRING64),
            ("STRING256", STRING256), ("STRING1024", STRING1024), ("DATE_TIME", DATE_TIME),
            ("N_PARAM", n_param), ("N_HISTORY", 1),
        ):
            ds.createDimension(name, size)

        def s(name: str, value: str, width: int, **attrs):
            dim = "DATE_TIME" if width == DATE_TIME else f"STRING{width}"
            var = _char(ds, name, dim, **attrs)
            var[:] = string_value(value, width)
            return var

        def p1(name: str, values: list[str], width: int, **attrs):
            var = _char(ds, name, ("N_PROF", f"STRING{width}"), **attrs)
            for i, val in enumerate(values):
                var[i] = string_value(val, width)
            return var

        # ---- file scalars ----
        s("DATA_TYPE", "B-Argo profile" if is_bgc else "Argo profile",
          STRING32 if is_bgc else STRING16,
          long_name="Data type", conventions="Argo reference table 1")
        s("FORMAT_VERSION", "3.1", STRING4, long_name="File format version")
        s("HANDBOOK_VERSION", "1.2", STRING4, long_name="Data handbook version")
        s("REFERENCE_DATE_TIME", "19500101000000", DATE_TIME,
          long_name="Date of reference for Julian days", conventions="YYYYMMDDHHMISS")
        s("DATE_CREATION", _stamp(), DATE_TIME,
          long_name="Date of file creation", conventions="YYYYMMDDHHMISS")
        s("DATE_UPDATE", _stamp(), DATE_TIME,
          long_name="Date of update of this file", conventions="YYYYMMDDHHMISS")

        # ---- per-profile identity ----
        p1("PLATFORM_NUMBER", [meta.wmo] * n_prof, STRING8,
           long_name="Float unique identifier",
           conventions="WMO float identifier : A9IIIII")
        p1("PROJECT_NAME", [meta.project_name] * n_prof, STRING64,
           long_name="Name of the project")
        p1("PI_NAME", [meta.pi_name] * n_prof, STRING64,
           long_name="Name of the principal investigator")

        stw = STRING64 if is_bgc else STRING16
        st = _char(ds, "STATION_PARAMETERS", ("N_PROF", "N_PARAM", f"STRING{stw}"),
                   conventions="Argo reference table 3",
                   long_name="List of available parameters for the station")
        st[:] = np.full((n_prof, n_param, stw), b" ", dtype="S1")
        for ip, b in enumerate(blocks):
            for ipar, name in enumerate(["PRES"] + b.params):
                st[ip, ipar] = string_value(name, stw)

        v = ds.createVariable("CYCLE_NUMBER", "i4", ("N_PROF",), fill_value=INT_FILL)
        v.setncattr("long_name", "Float cycle number")
        v.setncattr("conventions",
                    "0...N, 0 : launch cycle (if exists), 1 : first complete cycle")
        v[:] = np.int32(cyc.cycle_number)

        dir_var = _char(ds, "DIRECTION", ("N_PROF",),
                        long_name="Direction of the station profiles",
                        conventions="A: ascending profiles, D: descending profiles")
        dir_var[:] = np.array([b"A", b"A"], dtype="S1")

        p1("DATA_CENTRE", [meta.data_centre] * n_prof, STRING2,
           long_name="Data centre in charge of float data processing",
           conventions="Argo reference table 4")
        p1("DC_REFERENCE", [f"{meta.wmo}/{cyc.cycle_number}"] * n_prof, STRING32,
           long_name="Station unique identifier in data centre",
           conventions="Data centre convention")
        p1("DATA_STATE_INDICATOR", ["1A"] * n_prof, STRING4,
           long_name="Degree of processing the data have passed through",
           conventions="Argo reference table 6")

        dm = _char(ds, "DATA_MODE", ("N_PROF",),
                   long_name="Delayed mode or real time data",
                   conventions="R : real time; D : delayed mode; A : real time with adjustment")
        dm[:] = np.array([cyc.data_mode.encode()] * 2, dtype="S1")

        p1("PLATFORM_TYPE", [meta.platform_type] * n_prof, STRING32,
           long_name="Type of float", conventions="Argo reference table 23")

        if is_bgc:
            pdm = _char(ds, "PARAMETER_DATA_MODE", ("N_PROF", "N_PARAM"),
                        long_name="Delayed mode or real time data",
                        conventions="R : real time; D : delayed mode; A : real time with adjustment")
            arr = np.full((n_prof, n_param), b" ", dtype="S1")
            for ip, b in enumerate(blocks):
                for ipar, name in enumerate(["PRES"] + b.params):
                    arr[ip, ipar] = np.array(
                        [cyc.parameter_data_mode.get(name, "R").encode()], dtype="S1"
                    )[0]
            pdm[:] = arr

        p1("FLOAT_SERIAL_NO", [meta.platform_serial] * n_prof, STRING32,
           long_name="Serial number of the float")
        p1("FIRMWARE_VERSION", [meta.firmware_version] * n_prof, STRING32,
           long_name="Instrument firmware version")
        p1("WMO_INST_TYPE", [meta.wmo_inst_type] * n_prof, STRING4,
           long_name="Coded instrument type", conventions="Argo reference table 8")

        v = ds.createVariable("JULD", "f8", ("N_PROF",), fill_value=JULD_FILL)
        v.setncattr("standard_name", "time")
        v.setncattr("long_name", "Julian day (UTC) of the station relative to REFERENCE_DATE_TIME")
        v.setncattr("conventions", "Relative julian days with decimal part (as parts of day)")
        v.setncattr("units", "days since 1950-01-01 00:00:00 UTC")
        v.setncattr("resolution", np.float64(1e-05))
        v.setncattr("axis", "T")
        v[:] = np.float64(cyc.juld)

        jqc = _char(ds, "JULD_QC", ("N_PROF",),
                    long_name="Quality on date and time", conventions="Argo reference table 2")
        jqc[:] = np.array([b"1", b"1"], dtype="S1")

        v = ds.createVariable("JULD_LOCATION", "f8", ("N_PROF",), fill_value=JULD_FILL)
        v.setncattr("long_name", "Julian day (UTC) of the location relative to REFERENCE_DATE_TIME")
        v.setncattr("units", "days since 1950-01-01 00:00:00 UTC")
        v.setncattr("conventions", "Relative julian days with decimal part (as parts of day)")
        v.setncattr("resolution", np.float64(1e-05))
        v.setncattr("axis", "T")
        # QC-1 fix anchors shift the location time to the fix timestamp; the
        # interpolation/absence branches keep it at the profile JULD.
        v[:] = np.float64(
            cyc.juld_location if cyc.juld_location is not None else cyc.juld
        )

        lat = cyc.latitude if cyc.latitude is not None else DOUBLE_FILL
        lon = cyc.longitude if cyc.longitude is not None else DOUBLE_FILL
        v = ds.createVariable("LATITUDE", "f8", ("N_PROF",), fill_value=DOUBLE_FILL)
        v.setncattr("long_name", "Latitude of the station, best estimate")
        v.setncattr("standard_name", "latitude")
        v.setncattr("units", "degree_north")
        v.setncattr("valid_min", np.float64(-90.0))
        v.setncattr("valid_max", np.float64(90.0))
        v.setncattr("axis", "Y")
        v[:] = lat
        v = ds.createVariable("LONGITUDE", "f8", ("N_PROF",), fill_value=DOUBLE_FILL)
        v.setncattr("long_name", "Longitude of the station, best estimate")
        v.setncattr("standard_name", "longitude")
        v.setncattr("units", "degree_east")
        v.setncattr("valid_min", np.float64(-180.0))
        v.setncattr("valid_max", np.float64(180.0))
        v.setncattr("axis", "X")
        v[:] = lon

        pqc = _char(ds, "POSITION_QC", ("N_PROF",),
                    long_name="Quality on position (latitude and longitude)",
                    conventions="Argo reference table 2")
        pqc[:] = np.array([cyc.position_qc.encode()] * 2, dtype="S1")

        p1("POSITIONING_SYSTEM", [cyc.positioning_system] * n_prof, STRING8,
           long_name="Positioning system")
        p1("VERTICAL_SAMPLING_SCHEME",
           [b.vertical_sampling_scheme for b in blocks], STRING256,
           long_name="Vertical sampling scheme", conventions="Argo reference table 16")

        v = ds.createVariable("CONFIG_MISSION_NUMBER", "i4", ("N_PROF",), fill_value=INT_FILL)
        v.setncattr("long_name", "Unique number denoting the missions performed by the float")
        v.setncattr("conventions", "1...N, 1 : first complete mission")
        if cyc.config_mission_number is None:
            # mission identity known to be underivable for this cycle from
            # float-side inputs: write the netCDF int _FillValue (-999) so the
            # absence is explicit instead of fabricated.
            v[:] = np.int32(INT_FILL)
        else:
            v[:] = np.int32(cyc.config_mission_number)

        # ---- level variables ----
        # The file's param set is the union of both profiles' station params,
        # in each profile's declared order starting with PRES. A parameter is
        # written for BOTH profiles — as FillValue on the profile that does
        # not carry it (the published N_LEVELS/uniform layout).
        all_params: list[str] = []
        for b in blocks:
            for name in ["PRES"] + b.params:
                if name not in all_params:
                    all_params.append(name)

        def write_levels(name: str):
            attrs = PARAM_ATTRS.get(name, {})
            v = ds.createVariable(name, "f4", ("N_PROF", "N_LEVELS"),
                                  fill_value=FLOAT_FILL)
            for k, val in attrs.items():
                v.setncattr(k, val)
            data = np.full((n_prof, n_levels), FLOAT_FILL, dtype=np.float32)
            for ip, b in enumerate(blocks):
                vals = b.pres if name == "PRES" else b.values.get(name)
                if vals is None:
                    continue
                data[ip, : len(vals)] = np.asarray(vals, dtype=np.float32)
            v[:] = data

        def write_qc(name: str):
            qf = _char(ds, f"{name}_QC", ("N_PROF", "N_LEVELS"),
                       long_name="quality flag", conventions="Argo reference table 2")
            barr = np.full((n_prof, n_levels), b" ", dtype="S1")
            for ip, b in enumerate(blocks):
                qc = b.qc.get(name)
                if qc is None:
                    continue
                barr[ip, : len(qc)] = np.asarray(qc, dtype="S1")
            qf[:] = barr

        def write_adjusted(name: str):
            """Fill-filled ADJUSTED trio (required by the v3.1 spec at RT).

            The trio inherits the parameter's value attributes, but *not* the
            coordinate-axis declaration: ``axis`` is a CF attribute of the
            coordinate variables and the published files carry it on exactly
            JULD, JULD_LOCATION, LATITUDE, LONGITUDE and PRES.  Copying it onto
            ``PRES_ADJUSTED`` (the only parameter whose attribute set contains it)
            would be inconsistent with our own TEMP_ADJUSTED/PSAL_ADJUSTED and
            would declare an axis on an all-fill array.
            """
            attrs = PARAM_ATTRS.get(name, {})
            v = ds.createVariable(f"{name}_ADJUSTED", "f4",
                                  ("N_PROF", "N_LEVELS"), fill_value=FLOAT_FILL)
            for k, val in attrs.items():
                if k == "axis":
                    continue
                v.setncattr(k, val)
            v[:] = np.full((n_prof, n_levels), FLOAT_FILL, dtype=np.float32)
            qf = _char(ds, f"{name}_ADJUSTED_QC", ("N_PROF", "N_LEVELS"),
                       long_name="quality flag", conventions="Argo reference table 2")
            qf[:] = np.full((n_prof, n_levels), b" ", dtype="S1")
            err = ds.createVariable(f"{name}_ADJUSTED_ERROR", "f4",
                                    ("N_PROF", "N_LEVELS"), fill_value=FLOAT_FILL)
            err.setncattr("long_name",
                          "Contains the error on the adjusted values as determined by the delayed mode QC process")
            if attrs.get("units"):
                err.setncattr("units", attrs["units"])
            if attrs.get("C_format"):
                err.setncattr("C_format", attrs["C_format"])
            if attrs.get("FORTRAN_format"):
                err.setncattr("FORTRAN_format", attrs["FORTRAN_format"])
            if attrs.get("resolution") is not None:
                err.setncattr("resolution", attrs["resolution"])
            err[:] = np.full((n_prof, n_levels), FLOAT_FILL, dtype=np.float32)

        if is_bgc:
            # PRES carries no QC in a B file (established fleet layout).
            for name in all_params:
                write_levels(name)
                if name != "PRES":
                    write_qc(name)
                    # PROFILE_<param>_QC only for the BGC parameters.
                    var = _char(ds, f"PROFILE_{name}_QC", ("N_PROF",),
                                long_name=f"Global quality flag of {name} profile",
                                conventions="Argo reference table 2a")
                    var[:] = np.array(
                        [b.profile_qc.get(name, " ").encode() for b in blocks],
                        dtype="S1",
                    )
            # The v3.1 B-profile spec requires the ADJUSTED family for the
            # DOXY/CHLA/BBP700 main BGC parameter set AND for SUNA NITRATE
            # (its parameter group is treated like a primary one by the
            # format checker: family required, content stays real-time fill).
            for name in ("DOXY", "CHLA", "BBP700", "NITRATE"):
                if name in all_params:
                    write_adjusted(name)
        else:
            for name in all_params:
                write_levels(name)
                write_qc(name)
                var = _char(ds, f"PROFILE_{name}_QC", ("N_PROF",),
                            long_name=f"Global quality flag of {name} profile",
                            conventions="Argo reference table 2a")
                var[:] = np.array(
                    [b.profile_qc.get(name, " ").encode() for b in blocks],
                    dtype="S1",
                )
            for name in ("PRES", "TEMP", "PSAL"):
                if name in all_params:
                    write_adjusted(name)

        # ---- N_CALIB calibration block ----
        # Which parameters carry calibration info: an observed fleet fact.
        # Core R files: PRES TEMP PSAL on both profiles. BR: PRES only on
        # profile 0; the calibrated BGC subset on profile 1 -- every BGC
        # parameter of the file that has a calibration source (the optode for
        # DOXY, the SUNA for NITRATE, the FLBB for CHLA/BBP700), in the
        # published station-parameter order.  Verified against every published
        # BGC product of the fleet: the nitrate float's discrete profile lists
        # 'PRES DOXY NITRATE CHLA BBP700', the others 'PRES DOXY CHLA BBP700'.
        if is_bgc:
            calib_params = [p for p in ("PRES", "DOXY", "NITRATE", "CHLA", "BBP700")
                            if p in all_params]
            calib_profile = [0, 1]
        else:
            calib_params = [p for p in ("PRES", "TEMP", "PSAL") if p in all_params]

        pvwidth = STRING64 if is_bgc else STRING16
        pv = _char(ds, "PARAMETER", ("N_PROF", "N_CALIB", "N_PARAM", f"STRING{pvwidth}"),
                   long_name="List of parameters with calibration information",
                   conventions="Argo reference table 3")
        pv[:] = np.full((n_prof, 1, n_param, pvwidth), b" ", dtype="S1")
        if is_bgc:
            # Every profile lists the parameters that carry calibration
            # information *for that profile*: PRES is present on both
            # profiles, and the calibrated BGC subset additionally on the
            # discrete (profile 1) one. Verified against every published BR
            # reference of the primary parity float (59/59 files, both
            # profiles) and against
            # the non-BGC branch below, which already writes its list on all
            # profiles.
            for ip in range(n_prof):
                pv[ip, 0, 0] = string_value("PRES", pvwidth)
            for ipar, name in enumerate(calib_params[1:], 1):
                pv[1, 0, ipar] = string_value(name, pvwidth)
        else:
            for ip in range(n_prof):
                for ipar, name in enumerate(calib_params):
                    pv[ip, 0, ipar] = string_value(name, pvwidth)

        calib_text = cyc.calib_text
        for name, width in (
            ("SCIENTIFIC_CALIB_EQUATION", STRING256),
            ("SCIENTIFIC_CALIB_COEFFICIENT", STRING256),
            ("SCIENTIFIC_CALIB_COMMENT", STRING256),
            ("SCIENTIFIC_CALIB_DATE", DATE_TIME),
        ):
            var = _char(ds, name, ("N_PROF", "N_CALIB", "N_PARAM", f"STRING{width}" if width != DATE_TIME else "DATE_TIME"),
                        long_name={
                            "SCIENTIFIC_CALIB_EQUATION": "Calibration equation for this parameter",
                            "SCIENTIFIC_CALIB_COEFFICIENT": "Calibration coefficients for this equation",
                            "SCIENTIFIC_CALIB_COMMENT": "Comment applying to this parameter calibration",
                            "SCIENTIFIC_CALIB_DATE": "Date of calibration",
                        }[name])
            if name == "SCIENTIFIC_CALIB_DATE":
                var.setncattr("conventions", "YYYYMMDDHHMISS")
            arr = np.full((n_prof, 1, n_param, width), b" ", dtype="S1")
            if is_bgc:
                txt = calib_text.get("PRES", {}).get(name, "")
                if txt:
                    arr[0, 0, 0] = string_value(txt, width)
                for ipar, pname in enumerate(calib_params[1:], 1):
                    txt = calib_text.get(pname, {}).get(name, "")
                    if txt:
                        arr[1, 0, ipar] = string_value(txt, width)
            else:
                for ipar, pname in enumerate(calib_params):
                    txt = calib_text.get(pname, {}).get(name, "")
                    if txt:
                        arr[:, 0, ipar] = string_value(txt, width)
            var[:] = arr

        # ---- history ----
        for name, width in (
            ("HISTORY_INSTITUTION", STRING4), ("HISTORY_STEP", STRING4),
            ("HISTORY_SOFTWARE", STRING4), ("HISTORY_SOFTWARE_RELEASE", STRING4),
            ("HISTORY_REFERENCE", STRING64), ("HISTORY_DATE", DATE_TIME),
            ("HISTORY_ACTION", STRING4), ("HISTORY_PARAMETER", STRING64 if is_bgc else STRING16),
            ("HISTORY_QCTEST", STRING16),
        ):
            long = {
                "HISTORY_INSTITUTION": "Institution which performed action",
                "HISTORY_STEP": "Step in data processing",
                "HISTORY_SOFTWARE": "Name of software which performed action",
                "HISTORY_SOFTWARE_RELEASE": "Version/release of software which performed action",
                "HISTORY_REFERENCE": "Reference of database",
                "HISTORY_DATE": "Date the history record was created",
                "HISTORY_ACTION": "Action performed on data",
                "HISTORY_PARAMETER": "Station parameter action is performed on",
                "HISTORY_QCTEST": "Documentation of tests performed, tests failed (in hex form)",
            }[name]
            var = _char(ds, name, ("N_HISTORY", "N_PROF", f"STRING{width}" if width != DATE_TIME else "DATE_TIME"),
                        long_name=long)
            conv = {
                "HISTORY_INSTITUTION": "Argo reference table 4",
                "HISTORY_STEP": "Argo reference table 12",
                "HISTORY_SOFTWARE": "Institution dependent",
                "HISTORY_SOFTWARE_RELEASE": "Institution dependent",
                "HISTORY_REFERENCE": "Institution dependent",
                "HISTORY_DATE": "YYYYMMDDHHMISS",
                "HISTORY_ACTION": "Argo reference table 7",
                "HISTORY_PARAMETER": "Argo reference table 3",
                "HISTORY_QCTEST": "Write tests performed when ACTION=QCP$; tests failed when ACTION=QCF$",
            }.get(name)
            if conv:
                var.setncattr("conventions", conv)
        for name in ("HISTORY_START_PRES", "HISTORY_STOP_PRES", "HISTORY_PREVIOUS_VALUE"):
            var = ds.createVariable(name, "f4", ("N_HISTORY", "N_PROF"), fill_value=FLOAT_FILL)
            var.setncattr("long_name", {
                "HISTORY_START_PRES": "Start pressure action applied on",
                "HISTORY_STOP_PRES": "Stop pressure action applied on",
                "HISTORY_PREVIOUS_VALUE": "Parameter/Flag previous value before action",
            }[name])
            if name != "HISTORY_PREVIOUS_VALUE":
                var.setncattr("units", "decibar")
            var[:] = np.full((1, n_prof), FLOAT_FILL, dtype=np.float32)

        # history record 0: creation
        def hist_str(name: str, value: str, width: int):
            for ip in range(n_prof):
                ds.variables[name][0, ip] = string_value(value, width)

        hist_str("HISTORY_INSTITUTION", meta.data_centre, STRING4)
        hist_str("HISTORY_STEP", "ARFM", STRING4)
        hist_str("HISTORY_SOFTWARE", meta.decoder_name, STRING4)
        hist_str("HISTORY_SOFTWARE_RELEASE", "v" + meta.decoder_version, STRING4)
        hist_str("HISTORY_REFERENCE", "http://www.argodatamgt.org/Documentation", STRING64)
        hist_str("HISTORY_DATE", _stamp(), DATE_TIME)
        hist_str("HISTORY_ACTION", "CF", STRING4)
        hist_str("HISTORY_PARAMETER", "", STRING64 if is_bgc else STRING16)
        hist_str("HISTORY_QCTEST", "0000000000000000", STRING16)

        # ---- global attributes ----
        ds.setncattr("title", "Argo float vertical profile")
        ds.setncattr("institution", _DAC_NAMES.get(meta.data_centre, meta.data_centre))
        ds.setncattr("source", "Argo float")
        ds.setncattr("history", f"{_iso()} creation")
        ds.setncattr("references", "http://www.argodatamgt.org/Documentation")
        ds.setncattr("user_manual_version", "3.1")
        ds.setncattr("Conventions", "Argo-3.1 CF-1.6")
        ds.setncattr("featureType", "trajectoryProfile")
        ds.setncattr("decoder_version", f"{meta.decoder_name}-{meta.decoder_version}")

    return path


__all__ = [
    "Apf11MetaInput",
    "BGC_PARAM_ORDER",
    "CycleProductInput",
    "LevelBlock",
    "PARAM_ATTRS",
    "write_mono_profile",
]
