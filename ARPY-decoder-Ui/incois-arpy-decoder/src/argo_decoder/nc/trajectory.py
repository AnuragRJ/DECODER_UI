"""ADMT trajectory (``<wmo>_Rtraj.nc``) builder.

Implements Phase 6A. A trajectory file records every dated *event* in a
float's life on the ``N_MEASUREMENT`` axis, plus one summary row per
cycle on the ``N_CYCLE`` axis.

Structure, variable order, dtypes, attributes and fill conventions were
transcribed from the six supplied GDAC ``<wmo>_Rtraj.nc`` references
(2901339, 2902201, 2902203, 2902206, 2902222, 2902223), which are
structurally identical to one another.

Measurement codes (Argo reference table 15) used by these APEX/ARGOS
references, in per-cycle order:

===== ======================================= =========================
Code  Event                                   Source
===== ======================================= =========================
0     Launch position                         float metadata
100   Descent start                           engineering message
250   Drift at park                           engineering message
290   Park end / ascent start (with CTD)      engineering message
296   Deep-park descent (with CTD)            engineering message
300   Descent-to-profile start                engineering message
400   Profile descent end                     engineering message
500   Ascent start                            engineering message
600   Ascent end                              engineering message
700   Transmission start                      engineering message
702   First float message of the cycle        transmission times
703   Surface location fix                    ARGOS pass headers
704   Last float message of the cycle         transmission times
800   Transmission end                        engineering message
903   Grounding / last pump action            engineering message
===== ======================================= =========================

Rows whose time comes from the APEX engineering/technical message are
still emitted -- the references emit them too -- but carry
``_FillValue`` and ``JULD_STATUS='9'`` ("not determined"). That is the
ADMT way of recording "this event is expected but its time is unknown",
which is materially different from inventing a time.

The builder is a pure function of the record lists; only
:func:`write_trajectory` touches the filesystem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from argo_decoder.metadata.models import FloatMeta
from argo_decoder.nc.admt import (
    DATE_TIME_LEN,
    FLOAT_FILL,
    INT_FILL,
    INTERNAL_ATTRS,
    JULD_FILL,
    STRING2,
    STRING4,
    STRING8,
    STRING16,
    STRING32,
    STRING64,
    char_column,
    date_char,
    flag_column,
    package_version,
    scalar_char,
    standard_globals,
    utc_stamp,
    write_admt_dataset,
)

DOUBLE_POSITION_FILL = np.float64(99999.0)


class TrajMeasurementCode:
    """Argo reference table 15 codes emitted for APEX/ARGOS floats."""

    LAUNCH = 0
    DESCENT_START = 100
    PARK_DRIFT = 250
    PARK_END = 290
    DEEP_PARK_DESCENT = 296
    DESCENT_TO_PROFILE_START = 300
    DESCENT_TO_PROFILE_END = 400
    ASCENT_START = 500
    ASCENT_END = 600
    TRANSMISSION_START = 700
    FIRST_MESSAGE = 702
    SURFACE_FIX = 703
    LAST_MESSAGE = 704
    TRANSMISSION_END = 800
    GROUNDING = 903


#: Per-cycle event template, in the order the references write it.
CYCLE_MEASUREMENT_TEMPLATE: tuple[int, ...] = (
    TrajMeasurementCode.DESCENT_START,
    TrajMeasurementCode.PARK_DRIFT,
    TrajMeasurementCode.PARK_END,
    TrajMeasurementCode.DEEP_PARK_DESCENT,
    TrajMeasurementCode.DESCENT_TO_PROFILE_START,
    TrajMeasurementCode.DESCENT_TO_PROFILE_END,
    TrajMeasurementCode.ASCENT_START,
    TrajMeasurementCode.ASCENT_END,
    TrajMeasurementCode.TRANSMISSION_START,
    TrajMeasurementCode.FIRST_MESSAGE,
    # SURFACE_FIX rows are inserted here, one per ARGOS fix.
    TrajMeasurementCode.LAST_MESSAGE,
    TrajMeasurementCode.TRANSMISSION_END,
    TrajMeasurementCode.GROUNDING,
)

# JULD_STATUS, Argo reference table 19.
JULD_STATUS_UNKNOWN = "9"  # event expected, time not determined
JULD_STATUS_TRANSMITTED = "4"  # time taken from the transmission system
JULD_STATUS_FLOAT_CLOCK = "1"  # time read from the float's own clock
JULD_STATUS_DERIVED = "3"  # time derived from the mission programming

#: ``JULD_STATUS`` (reference table 19) per measurement code.
#:
#: A per-MC constant in every reference examined -- WMO 2901304, 2902222,
#: 2902223 and 2902224 agree cell for cell, and the two floats with
#: partial cycles fall back to ``'9'`` exactly where the event has no
#: time. Codes absent from this table keep the caller's value.
JULD_STATUS_BY_MEASUREMENT_CODE: dict[int, str] = {
    0: " ",  # launch: ship-recorded, no float clock involved
    100: JULD_STATUS_UNKNOWN,
    250: JULD_STATUS_UNKNOWN,
    290: JULD_STATUS_FLOAT_CLOCK,
    296: JULD_STATUS_FLOAT_CLOCK,
    300: JULD_STATUS_UNKNOWN,
    400: JULD_STATUS_UNKNOWN,
    500: JULD_STATUS_UNKNOWN,
    600: JULD_STATUS_DERIVED,
    700: JULD_STATUS_DERIVED,
    702: JULD_STATUS_TRANSMITTED,
    703: JULD_STATUS_TRANSMITTED,
    704: JULD_STATUS_TRANSMITTED,
    800: JULD_STATUS_UNKNOWN,
    903: " ",
}

#: ``JULD_QC`` per measurement code, likewise constant across all four
#: reference floats. Note it does not track whether the row carries a
#: time: MC 400 is always ``'0'`` (no QC performed) even though its JULD
#: is always empty, while MC 100 is always blank.
JULD_QC_BY_MEASUREMENT_CODE: dict[int, str] = {
    0: "1",
    100: " ",
    250: " ",
    290: "1",
    296: "1",
    300: " ",
    400: "0",
    500: " ",
    600: "0",
    700: "0",
    702: "0",
    703: "0",
    704: "0",
    800: " ",
    903: " ",
}


@dataclass
class TrajMeasurement:
    """One row on the ``N_MEASUREMENT`` axis."""

    cycle_number: int
    measurement_code: int
    juld: float | None = None
    juld_status: str = JULD_STATUS_UNKNOWN
    juld_qc: str = " "
    latitude: float | None = None
    longitude: float | None = None
    position_accuracy: str = " "
    position_qc: str = " "
    satellite_name: str = ""
    pres: float | None = None
    temp: float | None = None
    psal: float | None = None
    #: ``JULD_ADJUSTED`` and its status, when the DAC publishes a
    #: mission-schedule time for an event the float does not timestamp.
    juld_adjusted: float | None = None
    juld_adjusted_status: str | None = None
    #: ``PRES_ADJUSTED``: the measured pressure less the cycle's surface
    #: offset. Supplied by the platform layer, which knows the offset.
    pres_adjusted: float | None = None
    #: Per-row science QC override. ``None`` keeps the default rule
    #: ("1" where a value is present, blank otherwise).
    science_qc: str | None = None


@dataclass
class TrajCycle:
    """One row on the ``N_CYCLE`` axis."""

    cycle_number: int
    juld_first_message: float | None = None
    juld_first_location: float | None = None
    juld_last_message: float | None = None
    juld_last_location: float | None = None
    juld_ascent_end: float | None = None
    juld_transmission_start: float | None = None
    #: Mission-schedule events. The float does not timestamp these; the
    #: DAC derives them from the programmed cycle timings.
    juld_descent_start: float | None = None
    juld_park_start: float | None = None
    juld_park_end: float | None = None
    juld_transmission_end: float | None = None
    config_mission_number: int = 1
    data_mode: str = "R"
    #: Argo reference table 20. Defaults to ``U`` ("unknown"); a space
    #: fill or the digit ``0`` is not a valid table-20 code.
    #:
    #: APF9 telemetry carries no grounding status bit, but the flag is
    #: still derivable from float *performance* -- a cycle that stops
    #: short of its programmed profile pressure hit the seabed. The
    #: APEX/ARGOS platform layer fills this in; see
    #: :func:`argo_decoder.platforms.apex_argos.trajectory.grounded_flag`
    #: and ``docs/GROUNDED_INVESTIGATION.md``. Platforms with no
    #: derivation leave the default.
    grounded: str = "U"


@dataclass
class TrajectoryRecords:
    """Everything needed to build one trajectory file."""

    measurements: list[TrajMeasurement] = field(default_factory=list)
    cycles: list[TrajCycle] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Variable specifications transcribed from the GDAC references
# ---------------------------------------------------------------------------

_MEAS = "N_MEASUREMENT"
_CYC = "N_CYCLE"

_JULD_ATTRS: dict[str, Any] = {
    "standard_name": "time",
    "units": "days since 1950-01-01 00:00:00 UTC",
    "conventions": "Relative julian days with decimal part (as parts of day)",
    "resolution": np.float64(0.01),
    "_FillValue": JULD_FILL,
}

# ``(name, long_name)`` for the N_CYCLE timing pairs that always exist.
# Every one of these needs the APEX engineering message; the references
# populate some of them and leave others entirely empty. We emit the
# full set as structural columns and fill the values we can derive.
_CYCLE_JULD_EVENTS: tuple[tuple[str, str], ...] = (
    ("JULD_ASCENT_START", "Start date of the ascent to the surface"),
    ("JULD_ASCENT_END", "End date of ascent to the surface"),
    ("JULD_DESCENT_START", "Descent start date of the cycle"),
    ("JULD_DESCENT_END", "Descent end date of the cycle"),
    ("JULD_TRANSMISSION_START", "Start date of transmission"),
    ("JULD_FIRST_STABILIZATION", "Time when a float first becomes water-neutral"),
    ("JULD_PARK_START", "Drift start date of the cycle"),
    ("JULD_PARK_END", "Drift end date of the cycle"),
    ("JULD_DEEP_PARK_START", "Deep park start date of the cycle"),
    ("JULD_DEEP_DESCENT_END", "Deep descent end date of the cycle"),
    ("JULD_DEEP_ASCENT_START", "Deep ascent start date of the cycle"),
    ("JULD_TRANSMISSION_END", "Transmission end date"),
    ("JULD_FIRST_MESSAGE", "Date of earliest float message received"),
    ("JULD_FIRST_LOCATION", "Date of earliest location"),
    ("JULD_LAST_MESSAGE", "Date of latest float message received"),
    ("JULD_LAST_LOCATION", "Date of latest location"),
)

#: ``<EVENT>_STATUS`` for the N_CYCLE timings this decoder populates.
#:
#: A per-event constant in every reference: the mission-schedule events
#: carry ``'1'``, the two derived from the float clock carry ``'3'``, and
#: the reception times carry ``'4'``. Verified on WMO 2901304, 2902222,
#: 2902223 and 2902224, which also confirm the fallback -- an event that
#: should have a time but does not gets ``'9'``.
CYCLE_JULD_STATUS: dict[str, str] = {
    "JULD_DESCENT_START": "1",
    "JULD_PARK_START": "1",
    "JULD_PARK_END": "1",
    "JULD_TRANSMISSION_END": "1",
    "JULD_ASCENT_END": JULD_STATUS_DERIVED,
    "JULD_TRANSMISSION_START": JULD_STATUS_DERIVED,
    "JULD_FIRST_MESSAGE": JULD_STATUS_TRANSMITTED,
    "JULD_LAST_MESSAGE": JULD_STATUS_TRANSMITTED,
    "JULD_FIRST_LOCATION": JULD_STATUS_TRANSMITTED,
    "JULD_LAST_LOCATION": JULD_STATUS_TRANSMITTED,
}

#: ``<EVENT>_STATUS`` for events this decoder never populates. The
#: references distinguish "expected but not determined" (``'9'``) from
#: "not part of this float's cycle" (blank).
CYCLE_JULD_STATUS_WHEN_ABSENT: dict[str, str] = {
    "JULD_ASCENT_START": JULD_STATUS_UNKNOWN,
    "JULD_DEEP_DESCENT_END": JULD_STATUS_UNKNOWN,
}

#: Cycle timing fields this decoder can derive, keyed by variable name.
_DERIVABLE_CYCLE_JULD: dict[str, str] = {
    "JULD_FIRST_MESSAGE": "juld_first_message",
    "JULD_FIRST_LOCATION": "juld_first_location",
    "JULD_LAST_MESSAGE": "juld_last_message",
    "JULD_LAST_LOCATION": "juld_last_location",
    # M6: derived from the float clock via the documented timing model
    # (ApexTimings.xlsx rows 27/29/31).
    "JULD_ASCENT_END": "juld_ascent_end",
    "JULD_TRANSMISSION_START": "juld_transmission_start",
    # Mission-schedule events, propagated from the programmed cycle
    # timings rather than measured; see the APEX trajectory builder.
    "JULD_DESCENT_START": "juld_descent_start",
    "JULD_PARK_START": "juld_park_start",
    "JULD_PARK_END": "juld_park_end",
    "JULD_TRANSMISSION_END": "juld_transmission_end",
}


def _floats(values: list[float | None], fill: np.floating[Any]) -> np.ndarray:
    out = np.full(len(values), fill, dtype=fill.dtype)
    for i, value in enumerate(values):
        if value is not None and np.isfinite(value):
            out[i] = value
    return out


def _ints(values: list[int | None]) -> np.ndarray:
    out = np.full(len(values), INT_FILL, dtype=np.int32)
    for i, value in enumerate(values):
        if value is not None:
            out[i] = np.int32(value)
    return out


def _param_measurement_vars(
    name: str,
    values: list[float | None],
    *,
    long_name: str,
    standard_name: str,
    units: str,
    valid_min: float,
    valid_max: float,
    c_format: str,
    fortran_format: str,
    resolution: float,
    adjusted: list[float | None] | None = None,
    qc_override: list[str | None] | None = None,
) -> dict[str, xr.DataArray]:
    """Build ``<PARAM>``, ``_QC``, ``_ADJUSTED``, ``_ADJUSTED_QC`` and
    ``_ADJUSTED_ERROR`` for one trajectory parameter.

    ``adjusted`` supplies ``<PARAM>_ADJUSTED`` where the caller can
    compute it; rows left ``None`` stay filled. ``_ADJUSTED_QC`` then
    mirrors ``_QC`` on the adjusted rows, which is what the references
    do. ``_ADJUSTED_ERROR`` is always fill: it is a delayed-mode
    quantity.
    """
    n = len(values)
    base_attrs: dict[str, Any] = {
        "long_name": long_name,
        "standard_name": standard_name,
        "_FillValue": FLOAT_FILL,
        "units": units,
        "valid_min": np.float32(valid_min),
        "valid_max": np.float32(valid_max),
        "C_format": c_format,
        "FORTRAN_format": fortran_format,
        "resolution": np.float32(resolution),
    }
    qc_attrs = {
        "long_name": "quality flag",
        "conventions": "Argo reference table 2",
        "_FillValue": b" ",
    }
    data = _floats(values, FLOAT_FILL)
    present = data != FLOAT_FILL
    out: dict[str, xr.DataArray] = {}
    out[name] = xr.DataArray(data, dims=(_MEAS,), attrs=dict(base_attrs))
    # A measured value is good (1); an absent one carries a blank flag.
    qc = np.where(present, b"1", b" ").astype("S1")
    if qc_override is not None:
        # An override only reclassifies a value that exists. An absent
        # measurement keeps its blank flag, which is what the references
        # do: MC 296 carries PSAL_QC blank because it has no salinity,
        # even though its PRES and TEMP on the same row are flagged '0'.
        for i, flag in enumerate(qc_override):
            if flag is not None and present[i]:
                qc[i] = flag.encode("ascii")
    out[f"{name}_QC"] = xr.DataArray(qc, dims=(_MEAS,), attrs=dict(qc_attrs))
    adj_attrs = dict(base_attrs)
    # The references annotate the adjusted form with a provenance
    # comment; PRES additionally states the datum.
    adj_attrs["comment"] = (
        "In situ measurement, sea surface = 0" if name == "PRES" else "In situ measurement"
    )
    adj_data = (
        _floats(adjusted, FLOAT_FILL)
        if adjusted is not None
        else np.full(n, FLOAT_FILL, dtype=np.float32)
    )
    out[f"{name}_ADJUSTED"] = xr.DataArray(adj_data, dims=(_MEAS,), attrs=adj_attrs)
    adj_qc = np.where(adj_data != FLOAT_FILL, qc, b" ").astype("S1")
    out[f"{name}_ADJUSTED_QC"] = xr.DataArray(adj_qc, dims=(_MEAS,), attrs=dict(qc_attrs))
    out[f"{name}_ADJUSTED_ERROR"] = xr.DataArray(
        np.full(n, FLOAT_FILL, dtype=np.float32),
        dims=(_MEAS,),
        attrs={
            "long_name": (
                "Contains the error on the adjusted values "
                "as determined by the delayed mode QC process"
            ),
            "_FillValue": FLOAT_FILL,
            "units": units,
            "C_format": c_format,
            "FORTRAN_format": fortran_format,
            "resolution": np.float32(resolution),
        },
    )
    return out


def build_trajectory_dataset(
    records: TrajectoryRecords,
    *,
    wmo: int,
    meta: FloatMeta | None = None,
    institution: str = "IF",
    positioning_system: str = "ARGOS",
    platform_type: str = "",
    firmware_version: str = "",
    date_creation: str | None = None,
    date_update: str | None = None,
) -> xr.Dataset:
    """Build the ADMT ``<wmo>_Rtraj.nc`` dataset from decoded records.

    The variable insertion order matches the references exactly, since
    ``write_admt_dataset`` preserves it on disk.
    """
    measurements = records.measurements
    cycles = records.cycles
    n_meas = len(measurements)
    n_cycle = len(cycles)
    now = utc_stamp()
    created = date_creation or now
    updated = date_update or now

    def m_str(attr: str) -> str:
        value = getattr(meta, attr, "") if meta is not None else ""
        return str(value) if value else ""

    data_vars: dict[str, xr.DataArray] = {}

    # ---- file-level scalars (reference order) ----
    data_vars["DATE_CREATION"] = date_char(created)
    data_vars["DATE_CREATION"].attrs = {
        "long_name": "Date of file creation",
        "conventions": "YYYYMMDDHHMISS",
        "_FillValue": b" ",
    }
    data_vars["DATE_UPDATE"] = date_char(updated)
    data_vars["DATE_UPDATE"].attrs = {
        "long_name": "Date of update of this file",
        "conventions": "YYYYMMDDHHMISS",
        "_FillValue": b" ",
    }
    data_vars["PLATFORM_NUMBER"] = scalar_char(str(wmo), STRING8)
    data_vars["PLATFORM_NUMBER"].attrs = {
        "long_name": "Float unique identifier",
        "conventions": "WMO float identifier : A9IIIII",
        "_FillValue": b" ",
    }
    data_vars["DATA_CENTRE"] = scalar_char(m_str("data_centre") or institution, STRING2)
    data_vars["DATA_CENTRE"].attrs = {
        "long_name": "Data centre in charge of float data processing",
        "conventions": "Argo reference table 4",
        "_FillValue": b" ",
    }
    data_vars["WMO_INST_TYPE"] = scalar_char(m_str("wmo_inst_type"), STRING4)
    data_vars["WMO_INST_TYPE"].attrs = {
        "long_name": "Coded instrument type",
        "conventions": "Argo reference table 8",
        "_FillValue": b" ",
    }
    data_vars["PROJECT_NAME"] = scalar_char(m_str("project_name"), STRING64)
    data_vars["PROJECT_NAME"].attrs = {
        "long_name": "Name of the project",
        "_FillValue": b" ",
    }
    data_vars["PI_NAME"] = scalar_char(m_str("pi_name"), STRING64)
    data_vars["PI_NAME"].attrs = {
        "long_name": "Name of the principal investigator",
        "_FillValue": b" ",
    }
    data_vars["DATA_TYPE"] = scalar_char("Argo trajectory", STRING16)
    data_vars["DATA_TYPE"].attrs = {
        "long_name": "Data type",
        "conventions": "Argo reference table 1",
        "_FillValue": b" ",
    }
    data_vars["FORMAT_VERSION"] = scalar_char("3.1", STRING4)
    data_vars["FORMAT_VERSION"].attrs = {
        "long_name": "File format version",
        "_FillValue": b" ",
    }
    # Right-aligned ' 3.1' in every supplied trajectory reference. Note
    # this differs from the profile files, which carry ' 1.2'.
    data_vars["HANDBOOK_VERSION"] = scalar_char(" 3.1", STRING4)
    data_vars["HANDBOOK_VERSION"].attrs = {
        "long_name": "Data handbook version",
        "_FillValue": b" ",
    }
    data_vars["REFERENCE_DATE_TIME"] = date_char("19500101000000")
    data_vars["REFERENCE_DATE_TIME"].attrs = {
        "long_name": "Date of reference for Julian days",
        "conventions": "YYYYMMDDHHMISS",
        "_FillValue": b" ",
    }
    data_vars["POSITIONING_SYSTEM"] = scalar_char(positioning_system, STRING8)
    data_vars["POSITIONING_SYSTEM"].attrs = {
        "long_name": "Positioning system",
        "_FillValue": b" ",
    }
    params = ("PRES", "TEMP", "PSAL")
    data_vars["TRAJECTORY_PARAMETERS"] = char_column(list(params), STRING16, "N_PARAM")
    data_vars["TRAJECTORY_PARAMETERS"].attrs = {
        "conventions": "Argo reference table 3",
        "long_name": "List of available parameters for the station",
        "_FillValue": b" ",
    }
    # Real-time data that has passed automatic QC (reference table 6).
    data_vars["DATA_STATE_INDICATOR"] = scalar_char("2B", STRING4)
    data_vars["DATA_STATE_INDICATOR"].attrs = {
        "long_name": "Degree of processing the data have passed through",
        "conventions": "Argo reference table 6",
        "_FillValue": b" ",
    }
    data_vars["PLATFORM_TYPE"] = scalar_char(m_str("platform_type") or platform_type, STRING32)
    data_vars["PLATFORM_TYPE"].attrs = {
        "long_name": "Type of float",
        "conventions": "Argo reference table 23",
        "_FillValue": b" ",
    }
    data_vars["FLOAT_SERIAL_NO"] = scalar_char(m_str("float_serial_no"), STRING32)
    data_vars["FLOAT_SERIAL_NO"].attrs = {
        "long_name": "Serial number of the float",
        "_FillValue": b" ",
    }
    data_vars["FIRMWARE_VERSION"] = scalar_char(
        m_str("firmware_version") or firmware_version, STRING32
    )
    data_vars["FIRMWARE_VERSION"].attrs = {
        "long_name": "Instrument firmware version",
        "_FillValue": b" ",
    }

    # ---- N_MEASUREMENT axis ----
    data_vars["JULD"] = xr.DataArray(
        _floats([m.juld for m in measurements], JULD_FILL),
        dims=(_MEAS,),
        attrs={
            "long_name": "Julian day (UTC) of each measurement relative to REFERENCE_DATE_TIME",
            **_JULD_ATTRS,
            "axis": "T",
        },
    )
    data_vars["JULD_STATUS"] = flag_column([m.juld_status for m in measurements], _MEAS)
    data_vars["JULD_STATUS"].attrs = {
        "long_name": "Status of the date and time",
        "conventions": "Argo reference table 19",
        "_FillValue": b" ",
    }
    data_vars["JULD_QC"] = flag_column([m.juld_qc for m in measurements], _MEAS)
    data_vars["JULD_QC"].attrs = {
        "long_name": "Quality on date and time",
        "conventions": "Argo reference table 2",
        "_FillValue": b" ",
    }
    data_vars["JULD_ADJUSTED"] = xr.DataArray(
        _floats([m.juld_adjusted for m in measurements], JULD_FILL),
        dims=(_MEAS,),
        attrs={
            "long_name": (
                "Adjusted julian day (UTC) of each measurement relative to REFERENCE_DATE_TIME"
            ),
            **_JULD_ATTRS,
            "axis": "T",
        },
    )
    data_vars["JULD_ADJUSTED_STATUS"] = flag_column(
        [m.juld_adjusted_status or " " for m in measurements], _MEAS
    )
    data_vars["JULD_ADJUSTED_STATUS"].attrs = {
        "long_name": "Status of the JULD_ADJUSTED date",
        "conventions": "Argo reference table 19",
        "_FillValue": b" ",
    }
    data_vars["JULD_ADJUSTED_QC"] = flag_column(
        [m.juld_qc if m.juld_adjusted is not None else " " for m in measurements], _MEAS
    )
    data_vars["JULD_ADJUSTED_QC"].attrs = {
        "long_name": "Quality on adjusted date and time",
        "conventions": "Argo reference table 2",
        "_FillValue": b" ",
    }
    data_vars["LATITUDE"] = xr.DataArray(
        _floats([m.latitude for m in measurements], DOUBLE_POSITION_FILL),
        dims=(_MEAS,),
        attrs={
            "long_name": "Latitude of each location",
            "standard_name": "latitude",
            "_FillValue": DOUBLE_POSITION_FILL,
            "units": "degree_north",
            "valid_min": np.float64(-90.0),
            "valid_max": np.float64(90.0),
            "axis": "Y",
        },
    )
    data_vars["LONGITUDE"] = xr.DataArray(
        _floats([m.longitude for m in measurements], DOUBLE_POSITION_FILL),
        dims=(_MEAS,),
        attrs={
            "long_name": "Longitude of each location",
            "standard_name": "longitude",
            "_FillValue": DOUBLE_POSITION_FILL,
            "units": "degree_east",
            "valid_min": np.float64(-180.0),
            "valid_max": np.float64(180.0),
            "axis": "X",
        },
    )
    data_vars["POSITION_ACCURACY"] = flag_column([m.position_accuracy for m in measurements], _MEAS)
    data_vars["POSITION_ACCURACY"].attrs = {
        "long_name": "Estimated accuracy in latitude and longitude",
        "conventions": "Argo reference table 5",
        "_FillValue": b" ",
    }
    data_vars["POSITION_QC"] = flag_column([m.position_qc for m in measurements], _MEAS)
    data_vars["POSITION_QC"].attrs = {
        "long_name": "Quality on position",
        "conventions": "Argo reference table 2",
        "_FillValue": b" ",
    }
    data_vars["CYCLE_NUMBER"] = xr.DataArray(
        _ints([m.cycle_number for m in measurements]),
        dims=(_MEAS,),
        attrs={
            "long_name": "Float cycle number of the measurement",
            "conventions": "0...N, 0 : launch cycle, 1 : first complete cycle",
            "_FillValue": INT_FILL,
        },
    )
    data_vars["CYCLE_NUMBER_ADJUSTED"] = xr.DataArray(
        np.full(n_meas, INT_FILL, dtype=np.int32),
        dims=(_MEAS,),
        attrs={
            "long_name": "Adjusted float cycle number of the measurement",
            "conventions": "0...N, 0 : launch cycle, 1 : first complete cycle",
            "_FillValue": INT_FILL,
        },
    )
    data_vars["MEASUREMENT_CODE"] = xr.DataArray(
        _ints([m.measurement_code for m in measurements]),
        dims=(_MEAS,),
        attrs={
            "long_name": "Flag referring to a measurement event in the cycle",
            "conventions": "Argo reference table 15",
            "_FillValue": INT_FILL,
        },
    )
    data_vars.update(
        _param_measurement_vars(
            "PRES",
            [m.pres for m in measurements],
            long_name="Sea water pressure, equals 0 at sea-level",
            standard_name="sea_water_pressure",
            units="decibar",
            valid_min=0.0,
            valid_max=12000.0,
            c_format="%7.1f",
            fortran_format="F7.1",
            resolution=0.0,
            adjusted=[m.pres_adjusted for m in measurements],
            qc_override=[m.science_qc for m in measurements],
        )
    )
    # PRES carries an axis attribute; the adjusted form does not.
    data_vars["PRES"].attrs["axis"] = "Z"
    data_vars.update(
        _param_measurement_vars(
            "TEMP",
            [m.temp for m in measurements],
            long_name="Sea temperature in-situ ITS-90 scale",
            standard_name="sea_water_temperature",
            units="degree_Celsius",
            valid_min=-2.5,
            valid_max=40.0,
            c_format="%9.3f",
            fortran_format="F9.3",
            # The trajectory references advertise TEMP resolution 1.0,
            # unlike the profile files which use 0.001.
            resolution=1.0,
            adjusted=[m.temp for m in measurements],
            qc_override=[m.science_qc for m in measurements],
        )
    )
    data_vars.update(
        _param_measurement_vars(
            "PSAL",
            [m.psal for m in measurements],
            long_name="Practical salinity",
            standard_name="sea_water_salinity",
            units="psu",
            valid_min=2.0,
            valid_max=41.0,
            c_format="%9.3f",
            fortran_format="F9.3",
            resolution=0.001,
            adjusted=[m.psal for m in measurements],
            qc_override=[m.science_qc for m in measurements],
        )
    )
    # Error-ellipse geometry is an Iridium/GPS positioning product; the
    # ARGOS references leave it entirely unset.
    for ellipse, ell_long in (
        ("AXES_ERROR_ELLIPSE_MAJOR", "Major axis of error ellipse from positioning system"),
        ("AXES_ERROR_ELLIPSE_MINOR", "Minor axis of error ellipse from positioning system"),
        ("AXES_ERROR_ELLIPSE_ANGLE", "Angle of error ellipse from positioning system"),
    ):
        units = "Degrees (from North when heading East)" if ellipse.endswith("ANGLE") else "meters"
        data_vars[ellipse] = xr.DataArray(
            np.full(n_meas, FLOAT_FILL, dtype=np.float32),
            dims=(_MEAS,),
            attrs={"long_name": ell_long, "_FillValue": FLOAT_FILL, "units": units},
        )
    data_vars["SATELLITE_NAME"] = flag_column([m.satellite_name for m in measurements], _MEAS)
    data_vars["SATELLITE_NAME"].attrs = {
        "long_name": "Satellite name from positioning system",
        "_FillValue": b" ",
    }

    # ---- N_CYCLE axis ----
    for var_name, long_name in _CYCLE_JULD_EVENTS:
        attr = _DERIVABLE_CYCLE_JULD.get(var_name)
        values: list[float | None]
        if attr is None:
            # Needs the APEX engineering message; emitted as a
            # structural column of fill values rather than invented.
            values = [None] * n_cycle
            statuses = [CYCLE_JULD_STATUS_WHEN_ABSENT.get(var_name, " ")] * n_cycle
        else:
            values = [getattr(c, attr) for c in cycles]
            derived = CYCLE_JULD_STATUS.get(var_name, JULD_STATUS_TRANSMITTED)
            statuses = [
                derived if getattr(c, attr) is not None else JULD_STATUS_UNKNOWN for c in cycles
            ]
        data_vars[var_name] = xr.DataArray(
            _floats(values, JULD_FILL),
            dims=(_CYC,),
            attrs={"long_name": long_name, **_JULD_ATTRS},
        )
        status_name = f"{var_name}_STATUS"
        data_vars[status_name] = flag_column(list(statuses), _CYC)
        data_vars[status_name].attrs = {
            "conventions": "Argo reference table 19",
            "long_name": f"Status of {long_name[0].lower()}{long_name[1:]}",
            "_FillValue": b" ",
        }
    data_vars["CLOCK_OFFSET"] = xr.DataArray(
        np.full(n_cycle, JULD_FILL, dtype=np.float64),
        dims=(_CYC,),
        attrs={
            "long_name": "Time of float clock drift",
            "units": "days",
            "conventions": "Days with decimal part (as parts of day)",
            "_FillValue": JULD_FILL,
        },
    )
    data_vars["GROUNDED"] = flag_column([c.grounded for c in cycles], _CYC)
    data_vars["GROUNDED"].attrs = {
        "long_name": "Did the profiler touch the ground for that cycle?",
        "conventions": "Argo reference table 20",
        "_FillValue": b" ",
    }
    data_vars["REPRESENTATIVE_PARK_PRESSURE"] = xr.DataArray(
        np.full(n_cycle, FLOAT_FILL, dtype=np.float32),
        dims=(_CYC,),
        attrs={
            "long_name": "Best pressure value during park phase",
            "units": "decibar",
            "_FillValue": FLOAT_FILL,
        },
    )
    data_vars["REPRESENTATIVE_PARK_PRESSURE_STATUS"] = flag_column([" "] * n_cycle, _CYC)
    data_vars["REPRESENTATIVE_PARK_PRESSURE_STATUS"].attrs = {
        "conventions": "Argo reference table 21",
        "long_name": "Status of best pressure value during park phase",
        "_FillValue": b" ",
    }
    data_vars["CONFIG_MISSION_NUMBER"] = xr.DataArray(
        _ints([c.config_mission_number for c in cycles]),
        dims=(_CYC,),
        attrs={
            "long_name": "Unique number denoting the missions performed by the float",
            "conventions": "1...N, 1 : first complete mission",
            "_FillValue": INT_FILL,
        },
    )
    data_vars["CYCLE_NUMBER_INDEX"] = xr.DataArray(
        _ints([c.cycle_number for c in cycles]),
        dims=(_CYC,),
        attrs={
            "long_name": "Cycle number that corresponds to the current index",
            "conventions": "0...N, 0 : launch cycle, 1 : first complete cycle",
            "_FillValue": INT_FILL,
        },
    )
    data_vars["CYCLE_NUMBER_INDEX_ADJUSTED"] = xr.DataArray(
        np.full(n_cycle, INT_FILL, dtype=np.int32),
        dims=(_CYC,),
        attrs={
            "long_name": "Adjusted cycle number that corresponds to the current index",
            "conventions": "0...N, 0 : launch cycle, 1 : first complete cycle",
            "_FillValue": INT_FILL,
        },
    )
    data_vars["DATA_MODE"] = flag_column([c.data_mode for c in cycles], _CYC)
    data_vars["DATA_MODE"].attrs = {
        "long_name": "Delayed mode or real time data",
        "conventions": "R : real time; D : delayed mode; A : real time with adjustment",
        "_FillValue": b" ",
    }

    # ---- HISTORY (structural; the references leave it blank) ----
    data_vars.update(_history_vars())

    out = xr.Dataset(data_vars)
    out.attrs.update(
        standard_globals(
            title="Argo float trajectory file",
            institution=m_str("data_centre") or institution,
            feature_type="trajectory",
        )
    )
    out.attrs["comment_on_resolution"] = "PRES variable resolution depends on measurement codes"
    return out


def _history_vars() -> dict[str, xr.DataArray]:
    """Build the trajectory ``HISTORY_*`` group.

    All six supplied references carry ``N_HISTORY = 1`` with every field
    blank or fill: the DAC declares the group but records no trajectory
    history action. We reproduce that rather than inventing records --
    and unlike the profile files there is no per-level QC change to
    document here.
    """
    out: dict[str, xr.DataArray] = {}
    spec: tuple[tuple[str, int, dict[str, str]], ...] = (
        (
            "HISTORY_INSTITUTION",
            STRING4,
            {
                "long_name": "Institution which performed action",
                "conventions": "Argo reference table 4",
            },
        ),
        (
            "HISTORY_STEP",
            STRING4,
            {"long_name": "Step in data processing", "conventions": "Argo reference table 12"},
        ),
        (
            "HISTORY_SOFTWARE",
            STRING4,
            {
                "long_name": "Name of software which performed action",
                "conventions": "Institution dependent",
            },
        ),
        (
            "HISTORY_SOFTWARE_RELEASE",
            STRING4,
            {
                "long_name": "Version/release of software which performed action",
                "conventions": "Institution dependent",
            },
        ),
        (
            "HISTORY_REFERENCE",
            STRING64,
            {"long_name": "Reference of database", "conventions": "Institution dependent"},
        ),
        (
            "HISTORY_DATE",
            DATE_TIME_LEN,
            {
                "long_name": "Date the history record was created",
                "conventions": "YYYYMMDDHHMISS",
            },
        ),
        (
            "HISTORY_ACTION",
            STRING4,
            {"long_name": "Action performed on data", "conventions": "Argo reference table 7"},
        ),
        (
            "HISTORY_PARAMETER",
            STRING16,
            {
                "long_name": "Station parameter action is performed on",
                "conventions": "Argo reference table 3",
            },
        ),
    )
    for name, width, attrs in spec:
        out[name] = char_column([""], width, "N_HISTORY")
        out[name].attrs = {**attrs, "_FillValue": b" "}
    out["HISTORY_PREVIOUS_VALUE"] = xr.DataArray(
        np.full(1, FLOAT_FILL, dtype=np.float32),
        dims=("N_HISTORY",),
        attrs={
            "long_name": "Parameter/Flag previous value before action",
            "_FillValue": FLOAT_FILL,
        },
    )
    out["HISTORY_INDEX_DIMENSION"] = flag_column([" "], "N_HISTORY")
    out["HISTORY_INDEX_DIMENSION"].attrs = {
        "long_name": (
            "Name of dimension to which HISTORY_START_INDEX and HISTORY_STOP_INDEX correspond"
        ),
        "conventions": "C: N_CYCLE, M: N_MEASUREMENT",
        "_FillValue": b" ",
    }
    for name, long_name in (
        ("HISTORY_START_INDEX", "Start index action applied on"),
        ("HISTORY_STOP_INDEX", "Stop index action applied on"),
    ):
        out[name] = xr.DataArray(
            np.full(1, INT_FILL, dtype=np.int32),
            dims=("N_HISTORY",),
            attrs={"long_name": long_name, "_FillValue": INT_FILL},
        )
    out["HISTORY_QCTEST"] = char_column([""], STRING16, "N_HISTORY")
    out["HISTORY_QCTEST"].attrs = {
        "long_name": "Documentation of tests performed, tests failed (in hex form)",
        "conventions": "Write tests performed when ACTION=QCP$; tests failed when ACTION=QCF$",
        "_FillValue": b" ",
    }
    return out


def write_trajectory(ds: xr.Dataset, path: Path) -> None:
    """Write a trajectory dataset to ``path`` in ADMT dimension order."""
    fixed: dict[str, int | None] = {
        "N_CYCLE": int(ds.sizes.get("N_CYCLE", 0)),
        "STRING2": STRING2,
        "STRING4": STRING4,
        "STRING8": STRING8,
        "STRING16": STRING16,
        "STRING32": STRING32,
        "STRING64": STRING64,
        "DATE_TIME": DATE_TIME_LEN,
        "N_PARAM": int(ds.sizes.get("N_PARAM", 3)),
        "N_HISTORY": int(ds.sizes.get("N_HISTORY", 1)),
        # Unlimited, matching the references.
        "N_MEASUREMENT": None,
    }
    write_admt_dataset(
        ds,
        path,
        fixed_dims=fixed,
        dim_order=(
            "N_CYCLE",
            "STRING2",
            "STRING4",
            "STRING8",
            "STRING16",
            "STRING32",
            "STRING64",
            "DATE_TIME",
            "N_PARAM",
            "N_HISTORY",
            "N_MEASUREMENT",
        ),
    )


__all__ = [
    "CYCLE_MEASUREMENT_TEMPLATE",
    "INTERNAL_ATTRS",
    "JULD_QC_BY_MEASUREMENT_CODE",
    "JULD_STATUS_BY_MEASUREMENT_CODE",
    "JULD_STATUS_DERIVED",
    "JULD_STATUS_FLOAT_CLOCK",
    "JULD_STATUS_TRANSMITTED",
    "JULD_STATUS_UNKNOWN",
    "TrajCycle",
    "TrajMeasurement",
    "TrajMeasurementCode",
    "TrajectoryRecords",
    "build_trajectory_dataset",
    "package_version",
    "write_trajectory",
]
