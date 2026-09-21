"""ARVOR-I ADMT trajectory (``<wmo>_Rtraj.nc``) writer — Phase 4B.

Thin NetCDF writer for the trajectory product model built by
:mod:`argo_decoder.platforms.provor_ir_sbd.arvor_i_rtraj`.  The layout,
variable order, dtypes and attributes transcribe ``create_nc_traj_c_file_
3_1.m`` (the Coriolis 076a chain's ``_Rtraj.nc`` writer) cross-checked
cell-for-cell against both GDAC references
(``gdac_arvor_i_ref/{6990711,7902408}_Rtraj.nc``, Argo Trajectory 3.1;
see the Phase 4B mapping report §5):

* dimensions ``DATE_TIME``/``STRING64``/``STRING32``/``STRING16``/
  ``STRING8``/``STRING4``/``STRING2``/``N_PARAM``/``N_CYCLE``/``N_HISTORY``
  and ``N_MEASUREMENT`` (unlimited), in writer definition order;
* 102 variables in the fixed reference order (header block, N_MEASUREMENT
  block, N_CYCLE block, HISTORY block), attrs from the MATLAB writer;
* a fresh file carries a single blank HISTORY row (the MATLAB chain only
  appends history when updating an existing file);
* ``JULD_ADJUSTED`` is written only for cycles whose ``DATA_MODE`` is
  ``'A'`` (clock offset known), matching the writer's ``adjustedCycle``
  gate; missing values stay at the NetCDF fill (``999999.0`` for JULD,
  ``99999``/``99999.0`` elsewhere, ``' '`` for characters).

The APEX writer (``nc/trajectory.py``) is untouched; it serves the
ARGOS-subset layout only.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import xarray as xr

from argo_decoder.nc.admt import (
    DATE_TIME_LEN,
    STRING2,
    STRING4,
    STRING8,
    STRING16,
    STRING32,
    STRING64,
    char_column,
    flag_column,
    institution_for_data_centre,
    scalar_char,
    utc_stamp,
    write_admt_dataset,
)
from argo_decoder.platforms.provor_ir_sbd.arvor_i_prof import truncate_arc_minutes
from argo_decoder.platforms.provor_ir_sbd.arvor_i_rtraj import (
    NCYCLE_FIELD_BY_MC,
    ArvorRtrajDataset,
    RtrajRow,
)
from argo_decoder.rtqc.trajectory import apply_trajectory_rtqc

_MEAS = "N_MEASUREMENT"
_CYC = "N_CYCLE"
JULD_FILL = np.float64(999999.0)

#: Reference global attributes (create_nc_traj_c_file_3_1.m).
GLOBAL_ATTRS: dict[str, str] = {
    "title": "Argo float trajectory file",
    "source": "Argo float",
    "references": "http://www.argodatamgt.org/Documentation",
    "user_manual_version": "3.1",
    "Conventions": "Argo-3.1 CF-1.6",
    "featureType": "trajectory",
    "comment_on_resolution": "PRES variable resolution depends on measurement codes",
}

#: Variable table transcribed from create_nc_traj_c_file_3_1.m and the
#: GDAC references: (name, dtype, dims, attrs) in definition order.
_VAR_SPEC: tuple[tuple[str, str, list[str], dict[str, object]], ...] = (
    (
        "DATE_CREATION",
        "S",
        ["DATE_TIME"],
        {
            "long_name": "Date of file creation",
            "conventions": "YYYYMMDDHHMISS",
            "_FillValue": " ",
        },
    ),
    (
        "DATE_UPDATE",
        "S",
        ["DATE_TIME"],
        {
            "long_name": "Date of update of this file",
            "conventions": "YYYYMMDDHHMISS",
            "_FillValue": " ",
        },
    ),
    (
        "PLATFORM_NUMBER",
        "S",
        ["STRING8"],
        {
            "long_name": "Float unique identifier",
            "conventions": "WMO float identifier : A9IIIII",
            "_FillValue": " ",
        },
    ),
    (
        "DATA_CENTRE",
        "S",
        ["STRING2"],
        {
            "long_name": "Data centre in charge of float data processing",
            "conventions": "Argo reference table 4",
            "_FillValue": " ",
        },
    ),
    (
        "WMO_INST_TYPE",
        "S",
        ["STRING4"],
        {
            "long_name": "Coded instrument type",
            "conventions": "Argo reference table 8",
            "_FillValue": " ",
        },
    ),
    ("PROJECT_NAME", "S", ["STRING64"], {"_FillValue": " ", "long_name": "Name of the project"}),
    (
        "PI_NAME",
        "S",
        ["STRING64"],
        {
            "long_name": "Name of the principal investigator",
            "_FillValue": " ",
        },
    ),
    (
        "DATA_TYPE",
        "S",
        ["STRING16"],
        {
            "long_name": "Data type",
            "conventions": "Argo reference table 1",
            "_FillValue": " ",
        },
    ),
    ("FORMAT_VERSION", "S", ["STRING4"], {"long_name": "File format version", "_FillValue": " "}),
    (
        "HANDBOOK_VERSION",
        "S",
        ["STRING4"],
        {
            "long_name": "Data handbook version",
            "_FillValue": " ",
        },
    ),
    (
        "REFERENCE_DATE_TIME",
        "S",
        ["DATE_TIME"],
        {
            "long_name": "Date of reference for Julian days",
            "conventions": "YYYYMMDDHHMISS",
            "_FillValue": " ",
        },
    ),
    (
        "POSITIONING_SYSTEM",
        "S",
        ["STRING8"],
        {
            "long_name": "Positioning system",
            "_FillValue": " ",
        },
    ),
    (
        "TRAJECTORY_PARAMETERS",
        "S",
        ["N_PARAM", "STRING16"],
        {
            "conventions": "Argo reference table 3",
            "long_name": "List of available parameters for the station",
            "_FillValue": " ",
        },
    ),
    (
        "DATA_STATE_INDICATOR",
        "S",
        ["STRING4"],
        {
            "long_name": "Degree of processing the data have passed through",
            "conventions": "Argo reference table 6",
            "_FillValue": " ",
        },
    ),
    (
        "PLATFORM_TYPE",
        "S",
        ["STRING32"],
        {
            "long_name": "Type of float",
            "conventions": "Argo reference table 23",
            "_FillValue": " ",
        },
    ),
    (
        "FLOAT_SERIAL_NO",
        "S",
        ["STRING32"],
        {
            "long_name": "Serial number of the float",
            "_FillValue": " ",
        },
    ),
    (
        "FIRMWARE_VERSION",
        "S",
        ["STRING32"],
        {
            "long_name": "Instrument firmware version",
            "_FillValue": " ",
        },
    ),
    (
        "JULD",
        "f8",
        ["N_MEASUREMENT"],
        {
            "long_name": "Julian day (UTC) of each measurement relative to REFERENCE_DATE_TIME",
            "standard_name": "time",
            "conventions": "Relative julian days with decimal part (as parts of day)",
            "units": "days since 1950-01-01 00:00:00 UTC",
            "resolution": 0.01,
            "_FillValue": 999999.0,
            "axis": "T",
        },
    ),
    (
        "JULD_STATUS",
        "S",
        ["N_MEASUREMENT"],
        {
            "long_name": "Status of the date and time",
            "conventions": "Argo reference table 19",
            "_FillValue": " ",
        },
    ),
    (
        "JULD_QC",
        "S",
        ["N_MEASUREMENT"],
        {
            "long_name": "Quality on date and time",
            "conventions": "Argo reference table 2",
            "_FillValue": " ",
        },
    ),
    (
        "JULD_ADJUSTED",
        "f8",
        ["N_MEASUREMENT"],
        {
            "long_name": (
                "Adjusted julian day (UTC) of each measurement relative to REFERENCE_DATE_TIME"
            ),
            "standard_name": "time",
            "conventions": "Relative julian days with decimal part (as parts of day)",
            "units": "days since 1950-01-01 00:00:00 UTC",
            "resolution": 0.01,
            "_FillValue": 999999.0,
            "axis": "T",
        },
    ),
    (
        "JULD_ADJUSTED_STATUS",
        "S",
        ["N_MEASUREMENT"],
        {
            "long_name": "Status of the JULD_ADJUSTED date",
            "conventions": "Argo reference table 19",
            "_FillValue": " ",
        },
    ),
    (
        "JULD_ADJUSTED_QC",
        "S",
        ["N_MEASUREMENT"],
        {
            "long_name": "Quality on adjusted date and time",
            "conventions": "Argo reference table 2",
            "_FillValue": " ",
        },
    ),
    (
        "LATITUDE",
        "f8",
        ["N_MEASUREMENT"],
        {
            "long_name": "Latitude of each location",
            "standard_name": "latitude",
            "_FillValue": 99999.0,
            "units": "degree_north",
            "valid_min": -90.0,
            "valid_max": 90.0,
            "axis": "Y",
        },
    ),
    (
        "LONGITUDE",
        "f8",
        ["N_MEASUREMENT"],
        {
            "long_name": "Longitude of each location",
            "standard_name": "longitude",
            "_FillValue": 99999.0,
            "units": "degree_east",
            "valid_min": -180.0,
            "valid_max": 180.0,
            "axis": "X",
        },
    ),
    (
        "POSITION_ACCURACY",
        "S",
        ["N_MEASUREMENT"],
        {
            "long_name": "Estimated accuracy in latitude and longitude",
            "conventions": "Argo reference table 5",
            "_FillValue": " ",
        },
    ),
    (
        "POSITION_QC",
        "S",
        ["N_MEASUREMENT"],
        {
            "long_name": "Quality on position",
            "conventions": "Argo reference table 2",
            "_FillValue": " ",
        },
    ),
    (
        "CYCLE_NUMBER",
        "i4",
        ["N_MEASUREMENT"],
        {
            "long_name": "Float cycle number of the measurement",
            "conventions": "0...N, 0 : launch cycle, 1 : first complete cycle",
            "_FillValue": 99999,
        },
    ),
    (
        "CYCLE_NUMBER_ADJUSTED",
        "i4",
        ["N_MEASUREMENT"],
        {
            "long_name": "Adjusted float cycle number of the measurement",
            "conventions": "0...N, 0 : launch cycle, 1 : first complete cycle",
            "_FillValue": 99999,
        },
    ),
    (
        "MEASUREMENT_CODE",
        "i4",
        ["N_MEASUREMENT"],
        {
            "long_name": "Flag referring to a measurement event in the cycle",
            "conventions": "Argo reference table 15",
            "_FillValue": 99999,
        },
    ),
    (
        "PRES",
        "f4",
        ["N_MEASUREMENT"],
        {
            "long_name": "Sea water pressure, equals 0 at sea-level",
            "standard_name": "sea_water_pressure",
            "_FillValue": 99999.0,
            "units": "decibar",
            "valid_min": 0.0,
            "valid_max": 12000.0,
            "C_format": "%7.1f",
            "FORTRAN_format": "F7.1",
            "axis": "Z",
            "resolution": 0.0,
        },
    ),
    (
        "PRES_QC",
        "S",
        ["N_MEASUREMENT"],
        {
            "long_name": "quality flag",
            "conventions": "Argo reference table 2",
            "_FillValue": " ",
        },
    ),
    (
        "PRES_ADJUSTED",
        "f4",
        ["N_MEASUREMENT"],
        {
            "long_name": "Sea water pressure, equals 0 at sea-level",
            "standard_name": "sea_water_pressure",
            "_FillValue": 99999.0,
            "units": "decibar",
            "valid_min": 0.0,
            "valid_max": 12000.0,
            "comment": "In situ measurement, sea surface = 0",
            "C_format": "%7.1f",
            "FORTRAN_format": "F7.1",
            "resolution": 0.0,
        },
    ),
    (
        "PRES_ADJUSTED_QC",
        "S",
        ["N_MEASUREMENT"],
        {
            "long_name": "quality flag",
            "conventions": "Argo reference table 2",
            "_FillValue": " ",
        },
    ),
    (
        "PRES_ADJUSTED_ERROR",
        "f4",
        ["N_MEASUREMENT"],
        {
            "long_name": (
                "Contains the error on the adjusted values as determined "
                "by the delayed mode QC process"
            ),
            "_FillValue": 99999.0,
            "units": "decibar",
            "C_format": "%7.1f",
            "FORTRAN_format": "F7.1",
            "resolution": 0.0,
        },
    ),
    (
        "TEMP",
        "f4",
        ["N_MEASUREMENT"],
        {
            "long_name": "Sea temperature in-situ ITS-90 scale",
            "standard_name": "sea_water_temperature",
            "_FillValue": 99999.0,
            "units": "degree_Celsius",
            "valid_min": -2.5,
            "valid_max": 40.0,
            "C_format": "%9.3f",
            "FORTRAN_format": "F9.3",
            "resolution": 1.0,
        },
    ),
    (
        "TEMP_QC",
        "S",
        ["N_MEASUREMENT"],
        {
            "long_name": "quality flag",
            "conventions": "Argo reference table 2",
            "_FillValue": " ",
        },
    ),
    (
        "TEMP_ADJUSTED",
        "f4",
        ["N_MEASUREMENT"],
        {
            "long_name": "Sea temperature in-situ ITS-90 scale",
            "standard_name": "sea_water_temperature",
            "_FillValue": 99999.0,
            "units": "degree_Celsius",
            "valid_min": -2.5,
            "valid_max": 40.0,
            "comment": "In situ measurement",
            "C_format": "%9.3f",
            "FORTRAN_format": "F9.3",
            "resolution": 1.0,
        },
    ),
    (
        "TEMP_ADJUSTED_QC",
        "S",
        ["N_MEASUREMENT"],
        {
            "long_name": "quality flag",
            "conventions": "Argo reference table 2",
            "_FillValue": " ",
        },
    ),
    (
        "TEMP_ADJUSTED_ERROR",
        "f4",
        ["N_MEASUREMENT"],
        {
            "long_name": (
                "Contains the error on the adjusted values as determined "
                "by the delayed mode QC process"
            ),
            "_FillValue": 99999.0,
            "units": "degree_Celsius",
            "C_format": "%9.3f",
            "FORTRAN_format": "F9.3",
            "resolution": 1.0,
        },
    ),
    (
        "PSAL",
        "f4",
        ["N_MEASUREMENT"],
        {
            "long_name": "Practical salinity",
            "standard_name": "sea_water_salinity",
            "_FillValue": 99999.0,
            "units": "psu",
            "valid_min": 2.0,
            "valid_max": 41.0,
            "C_format": "%9.3f",
            "FORTRAN_format": "F9.3",
            "resolution": 0.001,
        },
    ),
    (
        "PSAL_QC",
        "S",
        ["N_MEASUREMENT"],
        {
            "long_name": "quality flag",
            "conventions": "Argo reference table 2",
            "_FillValue": " ",
        },
    ),
    (
        "PSAL_ADJUSTED",
        "f4",
        ["N_MEASUREMENT"],
        {
            "long_name": "Practical salinity",
            "standard_name": "sea_water_salinity",
            "_FillValue": 99999.0,
            "units": "psu",
            "valid_min": 2.0,
            "valid_max": 41.0,
            "comment": "In situ measurement",
            "C_format": "%9.3f",
            "FORTRAN_format": "F9.3",
            "resolution": 0.001,
        },
    ),
    (
        "PSAL_ADJUSTED_QC",
        "S",
        ["N_MEASUREMENT"],
        {
            "long_name": "quality flag",
            "conventions": "Argo reference table 2",
            "_FillValue": " ",
        },
    ),
    (
        "PSAL_ADJUSTED_ERROR",
        "f4",
        ["N_MEASUREMENT"],
        {
            "long_name": (
                "Contains the error on the adjusted values as determined "
                "by the delayed mode QC process"
            ),
            "_FillValue": 99999.0,
            "units": "psu",
            "C_format": "%9.3f",
            "FORTRAN_format": "F9.3",
            "resolution": 0.001,
        },
    ),
    (
        "AXES_ERROR_ELLIPSE_MAJOR",
        "f4",
        ["N_MEASUREMENT"],
        {
            "long_name": "Major axis of error ellipse from positioning system",
            "_FillValue": 99999.0,
            "units": "meters",
        },
    ),
    (
        "AXES_ERROR_ELLIPSE_MINOR",
        "f4",
        ["N_MEASUREMENT"],
        {
            "long_name": "Minor axis of error ellipse from positioning system",
            "_FillValue": 99999.0,
            "units": "meters",
        },
    ),
    (
        "AXES_ERROR_ELLIPSE_ANGLE",
        "f4",
        ["N_MEASUREMENT"],
        {
            "long_name": "Angle of error ellipse from positioning system",
            "units": "Degrees (from North when heading East)",
            "_FillValue": 99999.0,
        },
    ),
    (
        "SATELLITE_NAME",
        "S",
        ["N_MEASUREMENT"],
        {
            "long_name": "Satellite name from positioning system",
            "_FillValue": " ",
        },
    ),
    (
        "JULD_ASCENT_START",
        "f8",
        ["N_CYCLE"],
        {
            "long_name": "Start date of the ascent to the surface",
            "standard_name": "time",
            "units": "days since 1950-01-01 00:00:00 UTC",
            "conventions": "Relative julian days with decimal part (as parts of day)",
            "resolution": 0.01,
            "_FillValue": 999999.0,
        },
    ),
    (
        "JULD_ASCENT_START_STATUS",
        "S",
        ["N_CYCLE"],
        {
            "conventions": "Argo reference table 19",
            "long_name": "Status of start date of the ascent to the surface",
            "_FillValue": " ",
        },
    ),
    (
        "JULD_ASCENT_END",
        "f8",
        ["N_CYCLE"],
        {
            "long_name": "End date of ascent to the surface",
            "standard_name": "time",
            "units": "days since 1950-01-01 00:00:00 UTC",
            "conventions": "Relative julian days with decimal part (as parts of day)",
            "resolution": 0.01,
            "_FillValue": 999999.0,
        },
    ),
    (
        "JULD_ASCENT_END_STATUS",
        "S",
        ["N_CYCLE"],
        {
            "conventions": "Argo reference table 19",
            "long_name": "Status of end date of ascent to the surface",
            "_FillValue": " ",
        },
    ),
    (
        "JULD_DESCENT_START",
        "f8",
        ["N_CYCLE"],
        {
            "long_name": "Descent start date of the cycle",
            "standard_name": "time",
            "units": "days since 1950-01-01 00:00:00 UTC",
            "conventions": "Relative julian days with decimal part (as parts of day)",
            "resolution": 0.01,
            "_FillValue": 999999.0,
        },
    ),
    (
        "JULD_DESCENT_START_STATUS",
        "S",
        ["N_CYCLE"],
        {
            "conventions": "Argo reference table 19",
            "long_name": "Status of descent start date of the cycle",
            "_FillValue": " ",
        },
    ),
    (
        "JULD_DESCENT_END",
        "f8",
        ["N_CYCLE"],
        {
            "long_name": "Descent end date of the cycle",
            "standard_name": "time",
            "units": "days since 1950-01-01 00:00:00 UTC",
            "conventions": "Relative julian days with decimal part (as parts of day)",
            "resolution": 0.01,
            "_FillValue": 999999.0,
        },
    ),
    (
        "JULD_DESCENT_END_STATUS",
        "S",
        ["N_CYCLE"],
        {
            "conventions": "Argo reference table 19",
            "long_name": "Status of descent end date of the cycle",
            "_FillValue": " ",
        },
    ),
    (
        "JULD_TRANSMISSION_START",
        "f8",
        ["N_CYCLE"],
        {
            "long_name": "Start date of transmission",
            "standard_name": "time",
            "units": "days since 1950-01-01 00:00:00 UTC",
            "conventions": "Relative julian days with decimal part (as parts of day)",
            "resolution": 0.01,
            "_FillValue": 999999.0,
        },
    ),
    (
        "JULD_TRANSMISSION_START_STATUS",
        "S",
        ["N_CYCLE"],
        {
            "conventions": "Argo reference table 19",
            "long_name": "Status of start date of transmission",
            "_FillValue": " ",
        },
    ),
    (
        "JULD_FIRST_STABILIZATION",
        "f8",
        ["N_CYCLE"],
        {
            "long_name": "Time when a float first becomes water-neutral",
            "standard_name": "time",
            "units": "days since 1950-01-01 00:00:00 UTC",
            "conventions": "Relative julian days with decimal part (as parts of day)",
            "resolution": 0.01,
            "_FillValue": 999999.0,
        },
    ),
    (
        "JULD_FIRST_STABILIZATION_STATUS",
        "S",
        ["N_CYCLE"],
        {
            "conventions": "Argo reference table 19",
            "long_name": "Status of time when a float first becomes water-neutral",
            "_FillValue": " ",
        },
    ),
    (
        "JULD_PARK_START",
        "f8",
        ["N_CYCLE"],
        {
            "long_name": "Drift start date of the cycle",
            "standard_name": "time",
            "units": "days since 1950-01-01 00:00:00 UTC",
            "conventions": "Relative julian days with decimal part (as parts of day)",
            "resolution": 0.01,
            "_FillValue": 999999.0,
        },
    ),
    (
        "JULD_PARK_START_STATUS",
        "S",
        ["N_CYCLE"],
        {
            "conventions": "Argo reference table 19",
            "long_name": "Status of drift start date of the cycle",
            "_FillValue": " ",
        },
    ),
    (
        "JULD_PARK_END",
        "f8",
        ["N_CYCLE"],
        {
            "long_name": "Drift end date of the cycle",
            "standard_name": "time",
            "units": "days since 1950-01-01 00:00:00 UTC",
            "conventions": "Relative julian days with decimal part (as parts of day)",
            "resolution": 0.01,
            "_FillValue": 999999.0,
        },
    ),
    (
        "JULD_PARK_END_STATUS",
        "S",
        ["N_CYCLE"],
        {
            "conventions": "Argo reference table 19",
            "long_name": "Status of drift end date of the cycle",
            "_FillValue": " ",
        },
    ),
    (
        "JULD_DEEP_PARK_START",
        "f8",
        ["N_CYCLE"],
        {
            "long_name": "Deep park start date of the cycle",
            "standard_name": "time",
            "units": "days since 1950-01-01 00:00:00 UTC",
            "conventions": "Relative julian days with decimal part (as parts of day)",
            "resolution": 0.01,
            "_FillValue": 999999.0,
        },
    ),
    (
        "JULD_DEEP_PARK_START_STATUS",
        "S",
        ["N_CYCLE"],
        {
            "conventions": "Argo reference table 19",
            "long_name": "Status of deep park start date of the cycle",
            "_FillValue": " ",
        },
    ),
    (
        "JULD_DEEP_DESCENT_END",
        "f8",
        ["N_CYCLE"],
        {
            "long_name": "Deep descent end date of the cycle",
            "standard_name": "time",
            "units": "days since 1950-01-01 00:00:00 UTC",
            "conventions": "Relative julian days with decimal part (as parts of day)",
            "resolution": 0.01,
            "_FillValue": 999999.0,
        },
    ),
    (
        "JULD_DEEP_DESCENT_END_STATUS",
        "S",
        ["N_CYCLE"],
        {
            "conventions": "Argo reference table 19",
            "long_name": "Status of deep descent end date of the cycle",
            "_FillValue": " ",
        },
    ),
    (
        "JULD_DEEP_ASCENT_START",
        "f8",
        ["N_CYCLE"],
        {
            "long_name": "Deep ascent start date of the cycle",
            "standard_name": "time",
            "units": "days since 1950-01-01 00:00:00 UTC",
            "conventions": "Relative julian days with decimal part (as parts of day)",
            "resolution": 0.01,
            "_FillValue": 999999.0,
        },
    ),
    (
        "JULD_DEEP_ASCENT_START_STATUS",
        "S",
        ["N_CYCLE"],
        {
            "conventions": "Argo reference table 19",
            "long_name": "Status of deep ascent start date of the cycle",
            "_FillValue": " ",
        },
    ),
    (
        "JULD_TRANSMISSION_END",
        "f8",
        ["N_CYCLE"],
        {
            "long_name": "Transmission end date",
            "standard_name": "time",
            "units": "days since 1950-01-01 00:00:00 UTC",
            "conventions": "Relative julian days with decimal part (as parts of day)",
            "resolution": 0.01,
            "_FillValue": 999999.0,
        },
    ),
    (
        "JULD_TRANSMISSION_END_STATUS",
        "S",
        ["N_CYCLE"],
        {
            "conventions": "Argo reference table 19",
            "long_name": "Status of transmission end date",
            "_FillValue": " ",
        },
    ),
    (
        "JULD_FIRST_MESSAGE",
        "f8",
        ["N_CYCLE"],
        {
            "long_name": "Date of earliest float message received",
            "standard_name": "time",
            "units": "days since 1950-01-01 00:00:00 UTC",
            "conventions": "Relative julian days with decimal part (as parts of day)",
            "resolution": 0.01,
            "_FillValue": 999999.0,
        },
    ),
    (
        "JULD_FIRST_MESSAGE_STATUS",
        "S",
        ["N_CYCLE"],
        {
            "conventions": "Argo reference table 19",
            "long_name": "Status of date of earliest float message received",
            "_FillValue": " ",
        },
    ),
    (
        "JULD_FIRST_LOCATION",
        "f8",
        ["N_CYCLE"],
        {
            "long_name": "Date of earliest location",
            "standard_name": "time",
            "units": "days since 1950-01-01 00:00:00 UTC",
            "conventions": "Relative julian days with decimal part (as parts of day)",
            "resolution": 0.01,
            "_FillValue": 999999.0,
        },
    ),
    (
        "JULD_FIRST_LOCATION_STATUS",
        "S",
        ["N_CYCLE"],
        {
            "conventions": "Argo reference table 19",
            "long_name": "Status of date of earliest location",
            "_FillValue": " ",
        },
    ),
    (
        "JULD_LAST_MESSAGE",
        "f8",
        ["N_CYCLE"],
        {
            "long_name": "Date of latest float message received",
            "standard_name": "time",
            "units": "days since 1950-01-01 00:00:00 UTC",
            "conventions": "Relative julian days with decimal part (as parts of day)",
            "resolution": 0.01,
            "_FillValue": 999999.0,
        },
    ),
    (
        "JULD_LAST_MESSAGE_STATUS",
        "S",
        ["N_CYCLE"],
        {
            "conventions": "Argo reference table 19",
            "long_name": "Status of date of latest float message received",
            "_FillValue": " ",
        },
    ),
    (
        "JULD_LAST_LOCATION",
        "f8",
        ["N_CYCLE"],
        {
            "long_name": "Date of latest location",
            "standard_name": "time",
            "units": "days since 1950-01-01 00:00:00 UTC",
            "conventions": "Relative julian days with decimal part (as parts of day)",
            "resolution": 0.01,
            "_FillValue": 999999.0,
        },
    ),
    (
        "JULD_LAST_LOCATION_STATUS",
        "S",
        ["N_CYCLE"],
        {
            "conventions": "Argo reference table 19",
            "long_name": "Status of date of latest location",
            "_FillValue": " ",
        },
    ),
    (
        "CLOCK_OFFSET",
        "f8",
        ["N_CYCLE"],
        {
            "long_name": "Time of float clock drift",
            "units": "days",
            "conventions": "Days with decimal part (as parts of day)",
            "_FillValue": 999999.0,
        },
    ),
    (
        "GROUNDED",
        "S",
        ["N_CYCLE"],
        {
            "long_name": "Did the profiler touch the ground for that cycle?",
            "conventions": "Argo reference table 20",
            "_FillValue": " ",
        },
    ),
    (
        "REPRESENTATIVE_PARK_PRESSURE",
        "f4",
        ["N_CYCLE"],
        {
            "long_name": "Best pressure value during park phase",
            "units": "decibar",
            "_FillValue": 99999.0,
        },
    ),
    (
        "REPRESENTATIVE_PARK_PRESSURE_STATUS",
        "S",
        ["N_CYCLE"],
        {
            "conventions": "Argo reference table 21",
            "long_name": "Status of best pressure value during park phase",
            "_FillValue": " ",
        },
    ),
    (
        "CONFIG_MISSION_NUMBER",
        "i4",
        ["N_CYCLE"],
        {
            "long_name": "Unique number denoting the missions performed by the float",
            "conventions": "1...N, 1 : first complete mission",
            "_FillValue": 99999,
        },
    ),
    (
        "CYCLE_NUMBER_INDEX",
        "i4",
        ["N_CYCLE"],
        {
            "long_name": "Cycle number that corresponds to the current index",
            "conventions": "0...N, 0 : launch cycle, 1 : first complete cycle",
            "_FillValue": 99999,
        },
    ),
    (
        "CYCLE_NUMBER_INDEX_ADJUSTED",
        "i4",
        ["N_CYCLE"],
        {
            "long_name": "Adjusted cycle number that corresponds to the current index",
            "conventions": "0...N, 0 : launch cycle, 1 : first complete cycle",
            "_FillValue": 99999,
        },
    ),
    (
        "DATA_MODE",
        "S",
        ["N_CYCLE"],
        {
            "long_name": "Delayed mode or real time data",
            "conventions": "R : real time; D : delayed mode; A : real time with adjustment",
            "_FillValue": " ",
        },
    ),
    (
        "HISTORY_INSTITUTION",
        "S",
        ["N_HISTORY", "STRING4"],
        {
            "long_name": "Institution which performed action",
            "conventions": "Argo reference table 4",
            "_FillValue": " ",
        },
    ),
    (
        "HISTORY_STEP",
        "S",
        ["N_HISTORY", "STRING4"],
        {
            "long_name": "Step in data processing",
            "conventions": "Argo reference table 12",
            "_FillValue": " ",
        },
    ),
    (
        "HISTORY_SOFTWARE",
        "S",
        ["N_HISTORY", "STRING4"],
        {
            "long_name": "Name of software which performed action",
            "conventions": "Institution dependent",
            "_FillValue": " ",
        },
    ),
    (
        "HISTORY_SOFTWARE_RELEASE",
        "S",
        ["N_HISTORY", "STRING4"],
        {
            "long_name": "Version/release of software which performed action",
            "conventions": "Institution dependent",
            "_FillValue": " ",
        },
    ),
    (
        "HISTORY_REFERENCE",
        "S",
        ["N_HISTORY", "STRING64"],
        {
            "long_name": "Reference of database",
            "conventions": "Institution dependent",
            "_FillValue": " ",
        },
    ),
    (
        "HISTORY_DATE",
        "S",
        ["N_HISTORY", "DATE_TIME"],
        {
            "long_name": "Date the history record was created",
            "conventions": "YYYYMMDDHHMISS",
            "_FillValue": " ",
        },
    ),
    (
        "HISTORY_ACTION",
        "S",
        ["N_HISTORY", "STRING4"],
        {
            "long_name": "Action performed on data",
            "conventions": "Argo reference table 7",
            "_FillValue": " ",
        },
    ),
    (
        "HISTORY_PARAMETER",
        "S",
        ["N_HISTORY", "STRING16"],
        {
            "long_name": "Station parameter action is performed on",
            "conventions": "Argo reference table 3",
            "_FillValue": " ",
        },
    ),
    (
        "HISTORY_PREVIOUS_VALUE",
        "f4",
        ["N_HISTORY"],
        {
            "long_name": "Parameter/Flag previous value before action",
            "_FillValue": 99999.0,
        },
    ),
    (
        "HISTORY_INDEX_DIMENSION",
        "S",
        ["N_HISTORY"],
        {
            "long_name": (
                "Name of dimension to which HISTORY_START_INDEX and HISTORY_STOP_INDEX correspond"
            ),
            "conventions": "C: N_CYCLE, M: N_MEASUREMENT",
            "_FillValue": " ",
        },
    ),
    (
        "HISTORY_START_INDEX",
        "i4",
        ["N_HISTORY"],
        {
            "long_name": "Start index action applied on",
            "_FillValue": 99999,
        },
    ),
    (
        "HISTORY_STOP_INDEX",
        "i4",
        ["N_HISTORY"],
        {
            "long_name": "Stop index action applied on",
            "_FillValue": 99999,
        },
    ),
    (
        "HISTORY_QCTEST",
        "S",
        ["N_HISTORY", "STRING16"],
        {
            "long_name": "Documentation of tests performed, tests failed (in hex form)",
            "conventions": "Write tests performed when ACTION=QCP$; tests failed when ACTION=QCF$",
            "_FillValue": " ",
        },
    ),
)

_STR_DIM = {
    "DATE_TIME": DATE_TIME_LEN,
    "STRING2": STRING2,
    "STRING4": STRING4,
    "STRING8": STRING8,
    "STRING16": STRING16,
    "STRING32": STRING32,
    "STRING64": STRING64,
}

__all__ = [
    "build_arvor_rtraj_nc_dataset",
    "write_arvor_rtraj_file",
    "write_arvor_rtraj_nc",
]


# ---------------------------------------------------------------------------
# GDAC publication projection (Phase 2; see
# validation_arvor_i_products/RTRAJ_PUBLICATION_PARITY_PHASE1.md)
# ---------------------------------------------------------------------------

_GDAC_RTRAJ_FAMILIES: tuple[int, ...] = (
    100,  # DST
    200,  # DET  (GDAC duplicate of the PST date)
    250,  # PST
    300,  # PET
    400,  # DDET (GDAC duplicate of the AST date)
    500,  # AST
    600,  # AET
    700,  # TST
    702,  # FMT
    703,  # Surface fixes
    704,  # LMT
    800,  # TET
)
"""Event families carried by the INCOIS GDAC ``_Rtraj.nc`` publication,
uniform across the four reference floats (Phase-1 census §2).  Launch
(MC 0) is carried separately, first.  The 18 Coriolis diagnostic families
(89/150/189/190/198/203/289/290/297/298/301/389/398/450/489/497/498/503/
589/590/599/710/711/901) remain internal-only."""

_GDAC_RTRAJ_ORDER: dict[int, int] = {code: i for i, code in enumerate(_GDAC_RTRAJ_FAMILIES)}

_GDAC_DATA_STATE_INDICATOR = "2B"
"""Publication-mode declaration of the GDAC reference files: every one of
the four references carries ``DATA_STATE_INDICATOR = '2B '`` ('2' realtime
mode, 'B' RTQC applied to the transmitted subset).  A file-level constant
of the publication contract — WMO-independent, not derived per float."""


def arvor_rtraj_publication_rows(rows: list[RtrajRow]) -> list[RtrajRow]:
    """Project internal trajectory rows onto the GDAC publication set.

    Pure function: input rows are never mutated, so the internal
    (full Coriolis 076a) dataset keeps every diagnostic family and the
    GPS fix row.  The published projection:

    * keeps only the GDAC families (launch MC 0 first, then cycles in
      ascending transmitted cycle order — the GDAC +1 renumbering is a
      legacy production artifact and is NOT adopted);
    * synthesizes DET 200 from the PST 250 row and DDET 400 from the
      AST 500 row (Phase-1: GDAC 200 JULD ≡ 250 and 400 ≈ 500 on every
      cycle of all four references) — the underlying dates stay the
      decoded float-clock values;
    * drops the GPS-'G' MC 703 row (GDAC publishes the Iridium mail
      locations only);
    * publishes positions on the surface events using the Phase-1-proven
      telemetry derivations: 700/702 ← first published 703 fix,
      704/800 ← last published 703 fix, 600 ← arc-minute-truncated cycle
      GPS fix (the dropped 'G' row's position); position QC is carried
      from the source row.  Absent sources leave the fill (nothing is
      fabricated — e.g. no GPS record ⇒ no 600 position).
    """

    launch = [r for r in rows if r.measurement_code == 0]
    out: list[RtrajRow] = list(launch)
    cycle_numbers = sorted({r.cycle_number for r in rows if r.measurement_code != 0})
    for cyc in cycle_numbers:
        block = [
            r for r in rows if r.cycle_number == cyc and r.measurement_code in _GDAC_RTRAJ_ORDER
        ]
        fix_rows = [r for r in block if r.measurement_code == 703 and r.pos_accuracy != "G"]
        gps_row = next(
            (r for r in block if r.measurement_code == 703 and r.pos_accuracy == "G"),
            None,
        )
        published = [r for r in block if r.measurement_code != 703] + fix_rows

        # DDET 400 is published from the internal DPST 450 row (same
        # decoded instant, descent_to_prof_end). 450 itself stays
        # internal-only -- it is not in the GDAC publication set.
        # Fall back to the (undated) 450 skeleton row so the DDET family
        # is still published as fill when the mission config never
        # arrived -- the event exists, its date is simply unknown
        # (DATA-COVERAGE), and dropping the family would silently change
        # the published inventory.
        dpst_source = next(
            (r for r in rows if r.cycle_number == cyc and r.measurement_code == 450),
            None,
        )
        if dpst_source is not None:
            published = [*published, dpst_source]

        # Positions from telemetry (copies — internal rows stay pristine).
        first_fix, last_fix = (fix_rows[0], fix_rows[-1]) if fix_rows else (None, None)
        sources: dict[int, RtrajRow] = {}
        for code, src in ((700, first_fix), (702, first_fix), (704, last_fix), (800, last_fix)):
            if src is not None and src.latitude is not None:
                sources[code] = src
        if gps_row is not None and gps_row.latitude is not None:
            sources[600] = gps_row
        new_rows: list[RtrajRow] = []
        for r in published:
            src = sources.get(r.measurement_code)
            if src is not None and r.measurement_code != 703:
                if src is gps_row:
                    lat, lon = (
                        truncate_arc_minutes(src.latitude),
                        truncate_arc_minutes(src.longitude),
                    )
                else:
                    lat, lon = src.latitude, src.longitude
                r = replace(r, latitude=lat, longitude=lon, pos_qc=src.pos_qc)
            if r.measurement_code != 450:
                new_rows.append(r)
            if r.measurement_code == 250:
                # DET 200 and PST 250 are the same instant for this
                # family: the float stops descending and starts the park
                # drift. Trajectory Cookbook 6.1 Annex 9.3 lists DET as
                # FillValue for ARVOR format ids 102002-102004, but the
                # publication carries the row, and every GDAC reference
                # cycle has 200 == 250 exactly. Publishing the PST date
                # is therefore the only non-fabricated choice.
                new_rows.append(replace(r, measurement_code=200))
            elif r.measurement_code == 450 and dpst_source is not None:
                # DDET 400 = "deep descent end" = descent_to_prof_end,
                # the instant the float reaches profile depth. That is
                # the SAME decoded quantity the internal DPST 450 row
                # carries (see _NCYCLE_FIELDS: both map to
                # descent_to_prof_end), so DDET is published from it.
                #
                # Previously DDET was synthesised from AST 500, which is
                # a different instant -- AST is the *end* of the deep
                # park drift, DDET its start. GDAC's own references show
                # 400 != 500 in 100% of cycles, and our decoded DPST
                # reproduces GDAC's 400 to the second once the legacy
                # integer-day double-anchor is removed (fractional parts
                # identical on every clean cycle). Publishing AST as
                # DDET was a genuine implementation error.
                new_rows.append(replace(r, measurement_code=400))
        new_rows.sort(key=lambda r: _GDAC_RTRAJ_ORDER[r.measurement_code])
        out.extend(new_rows)
    return out


def build_arvor_rtraj_nc_dataset(
    dataset: ArvorRtrajDataset,
    *,
    data_centre: str = "  ",
    project_name: str = "",
    pi_name: str = "",
    positioning_system: str = "GPS",
    platform_type: str = "ARVOR",
    wmo_inst_type: str = "",
    float_serial_no: str = "",
    firmware_version: str = "",
    data_state_indicator: str = _GDAC_DATA_STATE_INDICATOR,
    institution: str | None = None,
    date_creation: str | None = None,
    date_update: str | None = None,
    rtqc: bool = True,
    bathymetry=None,
) -> xr.Dataset:
    """Build the ADMT trajectory dataset from the Phase 4B product model.

    The N_MEASUREMENT block is the GDAC publication projection of the
    internal product (:func:`arvor_rtraj_publication_rows`); the internal
    dataset itself keeps the full Coriolis 076a event inventory.

    ``rtqc`` runs the Coriolis trajectory RTQC set (tests 2/3/4/20, see
    :mod:`argo_decoder.rtqc.trajectory`) over the decoded rows before the
    publication projection, which is what fills ``JULD_QC``,
    ``JULD_ADJUSTED_QC`` and ``POSITION_QC``.  ``bathymetry`` enables
    TEST004; without it the test is recorded skipped, never passed.
    """

    # RTQC runs on the internal decode *before* the publication
    # projection, so the published QC flags are the ones the tests
    # actually produced (decode -> RTQC -> publication).  Skipped tests
    # (e.g. TEST004 without a bathymetry grid) leave their flags at the
    # un-tested '0'; nothing is fabricated.
    if rtqc:
        dataset.qc_outcome = apply_trajectory_rtqc(dataset.rows, bathymetry=bathymetry)

    rows: list[RtrajRow] = arvor_rtraj_publication_rows(dataset.rows)
    cycles = dataset.cycles
    n_meas = len(rows)
    n_cycle = len(cycles)
    now = utc_stamp()
    created = date_creation or now
    updated = date_update or now
    wmo = dataset.wmo

    mode_by_cycle = {c.cycle_number: c.data_mode for c in cycles}

    # column builders -----------------------------------------------------
    def f64(values: list[float | None], fill: float = 99999.0) -> xr.DataArray:
        data = np.full(n_meas, fill, dtype=np.float64)
        for i, v in enumerate(values):
            if v is not None:
                data[i] = v
        return xr.DataArray(data, dims=(_MEAS,))

    def f32(values: list[float | None], fill: float = 99999.0) -> xr.DataArray:
        data = np.full(n_meas, fill, dtype=np.float32)
        for i, v in enumerate(values):
            if v is not None:
                data[i] = v
        return xr.DataArray(data, dims=(_MEAS,))

    def i32(values: list[int | None], fill: int = 99999) -> xr.DataArray:
        data = np.full(n_meas, fill, dtype=np.int32)
        for i, v in enumerate(values):
            if v is not None:
                data[i] = v
        return xr.DataArray(data, dims=(_MEAS,))

    def chars(values: list[str], width: int) -> xr.DataArray:
        if width == 1:
            return flag_column([v or " " for v in values], _MEAS)
        return char_column([v if v else " " for v in values], width, _MEAS)

    def cycle_f64(field: str, fill: float = 999999.0) -> xr.DataArray:
        data = np.full(n_cycle, fill, dtype=np.float64)
        for i, c in enumerate(cycles):
            v = getattr(c, field)
            if v is not None:
                data[i] = v
        return xr.DataArray(data, dims=(_CYC,))

    def cycle_status(field: str) -> xr.DataArray:
        return flag_column([getattr(c, f"{field}_status") or " " for c in cycles], _CYC)

    # header scalars ------------------------------------------------------
    header: dict[str, str] = {
        "DATE_CREATION": created,
        "DATE_UPDATE": updated,
        "PLATFORM_NUMBER": str(wmo) if wmo is not None else "",
        "DATA_CENTRE": data_centre,
        "WMO_INST_TYPE": wmo_inst_type,
        "PROJECT_NAME": project_name,
        "PI_NAME": pi_name,
        "DATA_TYPE": "Argo trajectory",
        "FORMAT_VERSION": "3.1",
        "HANDBOOK_VERSION": "3.1",
        "REFERENCE_DATE_TIME": "19500101000000",
        "POSITIONING_SYSTEM": positioning_system,
        "DATA_STATE_INDICATOR": data_state_indicator,
        "PLATFORM_TYPE": platform_type,
        "FLOAT_SERIAL_NO": float_serial_no,
        "FIRMWARE_VERSION": firmware_version,
    }

    # N_MEASUREMENT columns ------------------------------------------------
    juld_adj = np.full(n_meas, JULD_FILL, dtype=np.float64)
    juld_adj_status: list[str] = []
    juld_adj_qc: list[str] = []
    for i, row in enumerate(rows):
        adjusted_cycle = mode_by_cycle.get(row.cycle_number) == "A"
        if row.juld_adj is not None and adjusted_cycle:
            juld_adj[i] = row.juld_adj
            juld_adj_status.append(row.juld_adj_status or " ")
            juld_adj_qc.append(row.juld_adj_qc or " ")
        else:
            juld_adj_status.append(" ")
            juld_adj_qc.append(" ")

    columns: dict[str, xr.DataArray] = {
        "JULD": f64([r.juld for r in rows], JULD_FILL),
        "JULD_STATUS": chars([r.juld_status for r in rows], 1),
        "JULD_QC": chars([r.juld_qc for r in rows], 1),
        "JULD_ADJUSTED": xr.DataArray(juld_adj, dims=(_MEAS,)),
        "JULD_ADJUSTED_STATUS": chars(juld_adj_status, 1),
        "JULD_ADJUSTED_QC": chars(juld_adj_qc, 1),
        "LATITUDE": f64([r.latitude for r in rows]),
        "LONGITUDE": f64([r.longitude for r in rows]),
        "POSITION_ACCURACY": chars([r.pos_accuracy for r in rows], 1),
        "POSITION_QC": chars([r.pos_qc for r in rows], 1),
        "CYCLE_NUMBER": i32([r.cycle_number for r in rows]),
        "CYCLE_NUMBER_ADJUSTED": i32([None] * n_meas),
        "MEASUREMENT_CODE": i32([r.measurement_code for r in rows]),
        "PRES": f32([r.pres for r in rows]),
        "PRES_QC": chars([" "] * n_meas, 1),
        "PRES_ADJUSTED": f32([None] * n_meas),
        "PRES_ADJUSTED_QC": chars([" "] * n_meas, 1),
        "PRES_ADJUSTED_ERROR": f32([None] * n_meas),
        "TEMP": f32([r.temp for r in rows]),
        "TEMP_QC": chars([" "] * n_meas, 1),
        "TEMP_ADJUSTED": f32([None] * n_meas),
        "TEMP_ADJUSTED_QC": chars([" "] * n_meas, 1),
        "TEMP_ADJUSTED_ERROR": f32([None] * n_meas),
        "PSAL": f32([r.psal for r in rows]),
        "PSAL_QC": chars([" "] * n_meas, 1),
        "PSAL_ADJUSTED": f32([None] * n_meas),
        "PSAL_ADJUSTED_QC": chars([" "] * n_meas, 1),
        "PSAL_ADJUSTED_ERROR": f32([None] * n_meas),
        "AXES_ERROR_ELLIPSE_MAJOR": f32([r.axes_major for r in rows]),
        "AXES_ERROR_ELLIPSE_MINOR": f32([r.axes_minor for r in rows]),
        "AXES_ERROR_ELLIPSE_ANGLE": f32([r.axes_angle for r in rows]),
        # SATELLITE_NAME is a 1-D NC_CHAR(N_MEASUREMENT) in this format
        "SATELLITE_NAME": flag_column([r.satellite or " " for r in rows], _MEAS),
    }

    # N_CYCLE columns (reference variable order) ---------------------------
    #
    # An N_CYCLE JULD_<EVENT> summarises the N_MEASUREMENT row carrying the
    # corresponding measurement code. The GDAC FileChecker enforces that
    # pairing: a non-fill N_CYCLE date whose MC row is absent from
    # N_MEASUREMENT raises "<VAR> (MC nnn): Not FillValue where there is no
    # associated JULD". Because the publication projection narrows the file
    # to the GDAC event set, the diagnostic families (e.g. MC 150 FST,
    # MC 450 DPST) are internal-only and their N_CYCLE summaries must stay
    # at fill in the published product -- the decoded values remain intact
    # on the internal dataset.
    #
    # Generic: driven by NCYCLE_FIELD_BY_MC and the codes actually present
    # in the published N_MEASUREMENT block, so any family that enters or
    # leaves the publication set is handled automatically.
    published_codes = {int(r.measurement_code) for r in rows}
    unpublished_ncycle_fields = {
        field
        for code, (field, _) in NCYCLE_FIELD_BY_MC.items()
        if code not in published_codes and field is not None
    }

    ncycle_columns: dict[str, xr.DataArray] = {}
    for var in _VAR_SPEC:
        name = var[0]
        if var[2] == [_CYC] and name.endswith("_STATUS") and name.startswith("JULD_"):
            field = _field_of_status(name)
            if field in unpublished_ncycle_fields:
                # Same pairing rule as the JULD twin below: a status flag
                # describing an event that is not published must itself be
                # fill, or the checker reports "<VAR>_STATUS (MC nnn): Not
                # FillValue where there is no associated JULD_STATUS".
                ncycle_columns[name] = flag_column([" "] * n_cycle, _CYC)
            else:
                ncycle_columns[name] = cycle_status(field)
        elif var[2] == [_CYC] and name.startswith("JULD_"):
            field = _field_of_juld(name)
            if field in unpublished_ncycle_fields:
                ncycle_columns[name] = xr.DataArray(
                    np.full(n_cycle, 999999.0, dtype=np.float64), dims=(_CYC,)
                )
            else:
                ncycle_columns[name] = cycle_f64(field)
    ncycle_columns["CLOCK_OFFSET"] = cycle_f64("clock_offset")
    ncycle_columns["GROUNDED"] = flag_column([c.grounded or " " for c in cycles], _CYC)
    ncycle_columns["REPRESENTATIVE_PARK_PRESSURE"] = xr.DataArray(
        np.array(
            [
                c.rep_park_pres if c.rep_park_pres is not None else np.float32(99999.0)
                for c in cycles
            ],
            dtype=np.float32,
        ),
        dims=(_CYC,),
    )
    ncycle_columns["REPRESENTATIVE_PARK_PRESSURE_STATUS"] = flag_column(
        [c.rep_park_pres_status or " " for c in cycles], _CYC
    )
    ncycle_columns["CONFIG_MISSION_NUMBER"] = xr.DataArray(
        np.array(
            [
                c.config_mission_number if c.config_mission_number is not None else 99999
                for c in cycles
            ],
            dtype=np.int32,
        ),
        dims=(_CYC,),
    )
    ncycle_columns["CYCLE_NUMBER_INDEX"] = xr.DataArray(
        np.array([c.cycle_number_index for c in cycles], dtype=np.int32),
        dims=(_CYC,),
    )
    ncycle_columns["CYCLE_NUMBER_INDEX_ADJUSTED"] = xr.DataArray(
        np.full(n_cycle, 99999, dtype=np.int32), dims=(_CYC,)
    )
    ncycle_columns["DATA_MODE"] = flag_column([c.data_mode or " " for c in cycles], _CYC)

    # assemble in the fixed reference order ---------------------------------
    data_vars: dict[str, xr.DataArray] = {}
    traj_params = ["PRES", "TEMP", "PSAL"]
    for spec in _VAR_SPEC:
        name, dtype, dims, attrs = spec
        if name in header:
            width = _STR_DIM[dims[0]]
            arr = scalar_char(header[name], width, dim=dims[0])
        elif name == "TRAJECTORY_PARAMETERS":
            arr = char_column(traj_params, STRING16, "N_PARAM")
        elif dims == [_MEAS]:
            arr = columns[name]
        elif name in ncycle_columns:
            arr = ncycle_columns[name]
        else:
            # HISTORY block: one blank row on a fresh file
            arr = _history_blank(name, dims)
        final_attrs = dict(attrs)
        if dtype == "f8":
            final_attrs["_FillValue"] = np.float64(final_attrs["_FillValue"])
        elif dtype == "f4":
            final_attrs["_FillValue"] = np.float32(final_attrs["_FillValue"])
        elif dtype == "i4":
            final_attrs["_FillValue"] = np.int32(final_attrs["_FillValue"])
        arr.attrs = final_attrs
        data_vars[name] = arr

    ds = xr.Dataset(data_vars=data_vars)
    ds.attrs = dict(GLOBAL_ATTRS)
    if institution is None:
        institution = (
            institution_for_data_centre(data_centre.strip()) if data_centre.strip() else "CORIOLIS"
        )
    ds.attrs["institution"] = institution
    moment = datetime.now(UTC)
    ds.attrs["history"] = f"{moment.isoformat(timespec='seconds').replace('+00:00', 'Z')} creation"
    return ds


def _field_of_juld(name: str) -> str:
    """JULD_<EVENT> variable -> RtrajCycleRecord field name."""

    return {
        "JULD_ASCENT_START": "ascent_start",
        "JULD_ASCENT_END": "ascent_end",
        "JULD_DESCENT_START": "descent_start",
        "JULD_DESCENT_END": "descent_end",
        "JULD_TRANSMISSION_START": "trans_start",
        "JULD_FIRST_STABILIZATION": "first_stab",
        "JULD_PARK_START": "park_start",
        "JULD_PARK_END": "park_end",
        "JULD_DEEP_PARK_START": "deep_park_start",
        "JULD_DEEP_DESCENT_END": "deep_descent_end",
        "JULD_DEEP_ASCENT_START": "deep_ascent_start",
        "JULD_TRANSMISSION_END": "trans_end",
        "JULD_FIRST_MESSAGE": "first_message",
        "JULD_FIRST_LOCATION": "first_location",
        "JULD_LAST_MESSAGE": "last_message",
        "JULD_LAST_LOCATION": "last_location",
    }[name]


def _field_of_status(name: str) -> str:
    return _field_of_juld(name[: -len("_STATUS")])


def _history_blank(name: str, dims: list[str]) -> xr.DataArray:
    if name in ("HISTORY_PREVIOUS_VALUE",):
        return xr.DataArray(np.array([99999.0], dtype=np.float32), dims=("N_HISTORY",))
    if name in ("HISTORY_START_INDEX", "HISTORY_STOP_INDEX"):
        return xr.DataArray(np.array([99999], dtype=np.int32), dims=("N_HISTORY",))
    if len(dims) == 1:  # HISTORY_INDEX_DIMENSION: 1-D NC_CHAR
        return flag_column([" "], "N_HISTORY")
    width = _STR_DIM[dims[1]]
    return char_column([" " * width], width, "N_HISTORY")


def write_arvor_rtraj_file(ds: xr.Dataset, path: Path) -> None:
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
        # create_nc_traj_c_file_3_1.m L242: N_MEASUREMENT is the record
        # dimension (NC_UNLIMITED) — every GDAC trajectory file has it
        # unlimited; ``None`` maps to an unlimited dimension in the writer.
        "N_MEASUREMENT": None,
        "N_HISTORY": int(ds.sizes.get("N_HISTORY", 1)),
    }
    write_admt_dataset(ds, path, fixed_dims=fixed)


def write_arvor_rtraj_nc(
    dataset: ArvorRtrajDataset,
    path: Path,
    *,
    data_centre: str = "  ",
    date_creation: str | None = None,
    date_update: str | None = None,
    **header_kwargs: str,
) -> Path:
    """Build and write ``<wmo>_Rtraj.nc`` for a Phase 4B product model."""

    ds = build_arvor_rtraj_nc_dataset(
        dataset,
        data_centre=data_centre,
        date_creation=date_creation,
        date_update=date_update,
        **header_kwargs,
    )
    write_arvor_rtraj_file(ds, path)
    return path
