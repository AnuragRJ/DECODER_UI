"""ADMT metadata (``<wmo>_meta.nc``) builder.

Implements Phase 6A.2. The metadata file is the static description of a
float: platform identity, transmission and positioning systems, launch
and deployment details, mission configuration, sensors and parameters.

Structure, variable order, dtypes, attributes and fill conventions were
transcribed from the six supplied GDAC ``<wmo>_meta.nc`` references
(2901339, 2902201, 2902203, 2902206, 2902222, 2902223), which share an
identical 65-variable layout and ordering.

Unlike the profile and trajectory products there is **no** ``HISTORY_*``
group and no ``N_HISTORY`` dimension.

Provenance
----------

Almost every field maps onto :class:`FloatMeta` (typed attributes for
the scalars, MATLAB-style numbered blocks in ``model_extra`` for the
sensor/parameter vectors). Fields the registry does not carry are
emitted blank, which is what the ADMT ``_FillValue`` of ``' '`` means
and what the references themselves do for unknown values.

The ``CONFIG_*`` / ``LAUNCH_CONFIG_*`` mission-programming blocks come
from the float's configuration, which the registry does not currently
populate; see the Phase 6A.2 progress entry for the classification.

The builder is a pure function of the metadata; only
:func:`write_metadata_file` touches the filesystem.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from argo_decoder.metadata.models import FloatMeta
from argo_decoder.nc.admt import (
    DATE_TIME_LEN,
    DOUBLE_FILL,
    INT_FILL,
    STRING2,
    STRING4,
    STRING8,
    STRING16,
    STRING32,
    STRING64,
    STRING128,
    STRING256,
    STRING1024,
    char_column,
    date_char,
    scalar_char,
    scalar_flag,
    standard_globals,
    utc_stamp,
    write_admt_dataset,
)

#: Sensor/parameter vector blocks, as MATLAB-style numbered metadata.
_SENSOR_KEYS = ("SENSOR", "SENSOR_MAKER", "SENSOR_MODEL", "SENSOR_SERIAL_NO")
_PARAM_KEYS = (
    "PARAMETER",
    "PARAMETER_SENSOR",
    "PARAMETER_UNITS",
    "PARAMETER_ACCURACY",
    "PARAMETER_RESOLUTION",
    "PREDEPLOYMENT_CALIB_EQUATION",
    "PREDEPLOYMENT_CALIB_COEFFICIENT",
    "PREDEPLOYMENT_CALIB_COMMENT",
)

# Registry placeholder meaning "not recorded". The references leave such
# fields blank rather than writing the literal token.
_NOT_AVAILABLE = {"n/a", "N/A", "na", "NA", "none", "None", "-"}

# Blocks whose leading whitespace is part of the published value rather
# than spreadsheet noise. Every GDAC reference sampled (2901304, 2901305,
# 2901339, 2902201, 2902222, 2902223, 2902224) emits the SBE41
# conductivity equation with a leading space, so this block is copied
# verbatim instead of being stripped.
_WHITESPACE_SIGNIFICANT_KEYS = frozenset({"PREDEPLOYMENT_CALIB_EQUATION"})

# Fields where ``n/a`` is a *meaningful published value* rather than a
# spreadsheet placeholder, so it must survive :func:`_clean`.
#
# Argo User's Manual 3.44.0 §2.4.4 sanctions an explicit not-applicable
# marker for the transmission-subscription fields on platforms that have
# no ARGOS subscription: "DACs can use N/A or alternative of their choice
# when not applicable (e.g. : Iridium or Orbcomm)". Blanking the token
# there would lose the distinction between "not applicable to this
# platform" and "we failed to record it".
#
# CONTROLLER_BOARD_TYPE_PRIMARY joins them because Argo reference table
# 28 has no code for a board the sheets identify only by a placeholder
# serial; publishing ``n/a`` states that honestly instead of inventing an
# R28 value.
_NOT_AVAILABLE_SIGNIFICANT_KEYS = frozenset(
    {
        "TRANS_SYSTEM_ID",
        "TRANS_FREQUENCY",
        "CONTROLLER_BOARD_TYPE_PRIMARY",
    }
)


#: Sensor ordering used by every supplied GDAC reference. All six files
#: list the CTD sensors as TEMP, CNDC, PRES, and ``PARAMETER_SENSOR``
#: follows the same order. The registry stores them PRES, TEMP, CNDC, so
#: the vector blocks are reordered to the published convention rather
#: than emitted in registry order.
_SENSOR_ORDER = ("CTD_TEMP", "CTD_CNDC", "CTD_PRES")


def _sensor_permutation(sensor_names: list[str]) -> list[int]:
    """Return indices that reorder ``sensor_names`` to the ADMT order.

    Sensors outside the known CTD triple keep their relative position at
    the end, so a future BGC sensor is never silently dropped.
    """
    remaining = list(range(len(sensor_names)))
    order: list[int] = []
    for wanted in _SENSOR_ORDER:
        for idx in remaining:
            if sensor_names[idx].strip().upper() == wanted:
                order.append(idx)
                remaining.remove(idx)
                break
    order.extend(remaining)
    return order


def _permute(values: list[str], order: list[int]) -> list[str]:
    out = [values[i] for i in order if i < len(values)]
    out.extend(values[len(order) :])
    return out


def _clean(
    value: Any,
    *,
    keep_leading_space: bool = False,
    keep_not_available: bool = False,
) -> str:
    """Normalise a metadata value, mapping 'not available' tokens to blank.

    ``keep_leading_space`` preserves leading whitespace for the blocks in
    :data:`_WHITESPACE_SIGNIFICANT_KEYS`, where the reference carries it.
    Trailing whitespace is always dropped: the NetCDF character arrays are
    space-padded, so it cannot be distinguished on read-back anyway.

    ``keep_not_available`` suppresses the placeholder mapping for the
    fields in :data:`_NOT_AVAILABLE_SIGNIFICANT_KEYS`, where ``n/a`` is
    the value the Argo User's Manual asks for rather than missing data.
    """
    if value is None:
        return ""
    text = str(value).rstrip() if keep_leading_space else str(value).strip()
    if keep_not_available:
        return text
    return "" if text.strip() in _NOT_AVAILABLE else text


def numbered_block(meta: FloatMeta | None, key: str) -> list[str]:
    """Read a MATLAB-style numbered metadata block into an ordered list.

    ``*_meta.json`` and the CSV registry store vector metadata as a
    single-element list of dicts keyed ``<KEY>_1``, ``<KEY>_2``, ...
    """
    if meta is None:
        return []
    raw = getattr(meta, key.lower(), None)
    if raw is None:
        raw = (meta.model_extra or {}).get(key)
    if not raw:
        return []
    keep_leading_space = key.upper() in _WHITESPACE_SIGNIFICANT_KEYS
    keep_not_available = key.upper() in _NOT_AVAILABLE_SIGNIFICANT_KEYS
    values: list[str] = []
    for row in raw:
        if not isinstance(row, dict):
            continue

        def _index(item: tuple[str, Any]) -> int:
            suffix = item[0].rsplit("_", 1)[-1]
            return int(suffix) if suffix.isdigit() else 0

        for _, value in sorted(row.items(), key=_index):
            values.append(
                _clean(
                    value,
                    keep_leading_space=keep_leading_space,
                    keep_not_available=keep_not_available,
                )
            )
    return values


def _normalise_date(raw: str) -> str:
    """Return a ``YYYYMMDDHHMMSS`` stamp, or blank when unparseable.

    The registry stores dates in several shapes (``DD/MM/YYYY HH:MM:SS``
    from CSV, ISO from JSON, already-compact from MATLAB exports).
    """
    from datetime import datetime

    text = str(raw).strip()
    if not text:
        return ""
    if len(text) == 14 and text.isdigit():
        return text
    for fmt in (
        "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%Y%m%d",
    ):
        try:
            return datetime.strptime(text, fmt).strftime("%Y%m%d%H%M%S")
        except ValueError:
            continue
    return ""


def _padded(values: list[str], length: int) -> list[str]:
    """Pad/truncate a vector block to exactly ``length`` entries."""
    out = list(values[:length])
    out.extend([""] * (length - len(out)))
    return out


def build_metadata_dataset(
    *,
    wmo: int,
    meta: FloatMeta | None = None,
    institution: str = "IF",
    date_creation: str | None = None,
    date_update: str | None = None,
    start_date: str | None = None,
) -> xr.Dataset:
    """Build the ADMT ``<wmo>_meta.nc`` dataset.

    Variable insertion order matches the references exactly, since
    :func:`write_admt_dataset` preserves it on disk.

    ``start_date`` is the platform layer's fallback for ``START_DATE``,
    as ``YYYYMMDDHHMMSS``, used only when the metadata backend carries no
    operator-declared value. Precedence is therefore:

    1. the backend's ``start_date`` (what Coriolis always uses);
    2. this argument -- cycle 1's ``JULD_LOCATION`` for APEX/ARGOS, a DAC
       convention rather than the literal "first descent"; see
       :func:`argo_decoder.platforms.apex_argos.decoder._cycle_one_start_date`;
    3. the ``_FillValue``, which the manual permits -- §2.4.9 does not
       list ``START_DATE`` among the mandatory metadata.

    Passing ``None`` selects rule 1 or 3.
    """
    now = utc_stamp()
    created = date_creation or now
    updated = date_update or now

    def m(attr: str) -> str:
        if meta is None:
            return ""
        return _clean(
            getattr(meta, attr, ""),
            keep_not_available=attr.upper() in _NOT_AVAILABLE_SIGNIFICANT_KEYS,
        )

    sensors = {key: numbered_block(meta, key) for key in _SENSOR_KEYS}
    params = {key: numbered_block(meta, key) for key in _PARAM_KEYS}
    # Reorder both vector blocks to the published ADMT sensor order.
    sensor_order = _sensor_permutation(sensors.get("SENSOR", []))
    if sensor_order:
        sensors = {k: _permute(v, sensor_order) for k, v in sensors.items()}
    param_order = _sensor_permutation(params.get("PARAMETER_SENSOR", []))
    if param_order:
        # The PREDEPLOYMENT_CALIB_* triple is *not* permuted with the rest.
        # Every GDAC reference emits it in pressure, temperature,
        # conductivity order while PARAMETER/PARAMETER_SENSOR follow the
        # published TEMP, CNDC, PRES order (verified on 2901304, 2901339 and
        # 2902222: index 0 pairs SENSOR=CTD_TEMP with the *pressure*
        # equation and pressure coefficients).
        unpermuted_keys: tuple[str, ...] = (
            "PREDEPLOYMENT_CALIB_EQUATION",
            "PREDEPLOYMENT_CALIB_COEFFICIENT",
            "PREDEPLOYMENT_CALIB_COMMENT",
        )
        preserved: dict[str, list[str]] = {
            key: params[key] for key in unpermuted_keys if key in params
        }
        params = {k: _permute(v, param_order) for k, v in params.items()}
        params.update(preserved)
    # Clamped to >=1 for the same reason as the config blocks below: a
    # zero-length dimension becomes a second record dimension.
    n_sensor = max((len(v) for v in sensors.values()), default=0) or 1
    n_param = max((len(v) for v in params.values()), default=0) or 1

    trans_system = numbered_block(meta, "TRANS_SYSTEM")
    trans_system_id = numbered_block(meta, "TRANS_SYSTEM_ID")
    trans_frequency = numbered_block(meta, "TRANS_FREQUENCY")
    positioning = numbered_block(meta, "POSITIONING_SYSTEM")
    n_trans = max(len(trans_system), len(trans_system_id), len(trans_frequency), 1)
    n_pos = max(len(positioning), 1)

    config_names = numbered_block(meta, "CONFIG_PARAMETER_NAME")
    config_values = numbered_block(meta, "CONFIG_PARAMETER_VALUE")
    launch_names = numbered_block(meta, "LAUNCH_CONFIG_PARAMETER_NAME")
    launch_values = numbered_block(meta, "LAUNCH_CONFIG_PARAMETER_VALUE")
    mission_numbers = numbered_block(meta, "CONFIG_MISSION_NUMBER")
    mission_comments = numbered_block(meta, "CONFIG_MISSION_COMMENT")
    # A zero-length dimension is written by netCDF4 as NC_UNLIMITED, which
    # would give the file three record dimensions. NETCDF3_CLASSIC permits
    # exactly one, and no GDAC reference carries a zero-length dimension.
    # The Coriolis chain clamps the same counts to one before defining the
    # dimension (create_nc_meta_file_3_1_from_json_float_meta.m:248-256),
    # emitting a single fill-valued entry. Clamp the block length here so
    # the data and the dimension stay in lockstep.
    n_config = max(len(config_names), len(config_values), 1)
    n_launch_config = max(len(launch_names), len(launch_values), 1)
    n_missions = max(len(mission_numbers), 1)

    data_vars: dict[str, xr.DataArray] = {}

    def _scalar(name: str, value: str, width: int, attrs: dict[str, Any]) -> None:
        data_vars[name] = scalar_char(value, width)
        data_vars[name].attrs = {**attrs, "_FillValue": b" "}

    def _date(name: str, value: str, attrs: dict[str, Any]) -> None:
        data_vars[name] = date_char(value)
        data_vars[name].attrs = {**attrs, "_FillValue": b" "}

    def _flag(name: str, value: str, attrs: dict[str, Any]) -> None:
        data_vars[name] = scalar_flag(value)
        data_vars[name].attrs = {**attrs, "_FillValue": b" "}

    def _vector(name: str, values: list[str], width: int, dim: str, attrs: dict[str, Any]) -> None:
        data_vars[name] = char_column(values, width, dim)
        data_vars[name].attrs = {**attrs, "_FillValue": b" "}

    # ---- file identity ----
    _scalar(
        "DATA_TYPE",
        "Argo meta-data",
        STRING16,
        {"long_name": "Data type", "conventions": "Argo reference table 1"},
    )
    _scalar("FORMAT_VERSION", "3.1", STRING4, {"long_name": "File format version"})
    _scalar("HANDBOOK_VERSION", "1.2", STRING4, {"long_name": "Data handbook version"})
    _date(
        "DATE_CREATION",
        created,
        {"long_name": "Date of file creation", "conventions": "YYYYMMDDHHMISS"},
    )
    _date(
        "DATE_UPDATE",
        updated,
        {"long_name": "Date of update of this file", "conventions": "YYYYMMDDHHMISS"},
    )

    # ---- platform identity ----
    _scalar(
        "PLATFORM_NUMBER",
        str(wmo),
        STRING8,
        {
            "long_name": "Float unique identifier",
            "conventions": "WMO float identifier : A9IIIII",
        },
    )
    _scalar(
        "PTT",
        m("ptt"),
        STRING256,
        {"long_name": "Transmission identifier (ARGOS, ORBCOMM, etc.)"},
    )
    _vector(
        "TRANS_SYSTEM",
        _padded(trans_system, n_trans),
        STRING16,
        "N_TRANS_SYSTEM",
        {"long_name": "Telecommunications system used"},
    )
    _vector(
        "TRANS_SYSTEM_ID",
        _padded(trans_system_id, n_trans),
        STRING32,
        "N_TRANS_SYSTEM",
        {"long_name": "Program identifier used by the transmission system"},
    )
    _vector(
        "TRANS_FREQUENCY",
        _padded(trans_frequency, n_trans),
        STRING16,
        "N_TRANS_SYSTEM",
        {"long_name": "Frequency of transmission from the float", "units": "hertz"},
    )
    _vector(
        "POSITIONING_SYSTEM",
        _padded(positioning, n_pos),
        STRING8,
        "N_POSITIONING_SYSTEM",
        {"long_name": "Positioning system"},
    )
    _scalar(
        "PLATFORM_FAMILY",
        m("platform_family"),
        STRING256,
        {"long_name": "Category of instrument", "conventions": "Argo reference table 22"},
    )
    _scalar(
        "PLATFORM_TYPE",
        m("platform_type"),
        STRING32,
        {"long_name": "Type of float", "conventions": "Argo reference table 23"},
    )
    _scalar(
        "PLATFORM_MAKER",
        m("platform_maker"),
        STRING256,
        {"long_name": "Name of the manufacturer", "conventions": "Argo reference table 24"},
    )
    _scalar(
        "FIRMWARE_VERSION",
        m("firmware_version"),
        STRING32,
        {"long_name": "Firmware version for the float"},
    )
    _scalar(
        "MANUAL_VERSION",
        m("manual_version"),
        STRING16,
        {"long_name": "Manual version for the float"},
    )
    _scalar(
        "FLOAT_SERIAL_NO",
        m("float_serial_no"),
        STRING32,
        {"long_name": "Serial number of the float"},
    )
    _scalar(
        "STANDARD_FORMAT_ID",
        m("standard_format_id"),
        STRING16,
        {"long_name": "Standard format number to describe the data format type for each float"},
    )
    _scalar(
        "DAC_FORMAT_ID",
        m("dac_format_id"),
        STRING16,
        {
            "long_name": (
                "Format number used by the DAC to describe the data format type for each float"
            )
        },
    )
    _scalar(
        "WMO_INST_TYPE",
        m("wmo_inst_type"),
        STRING4,
        {"long_name": "Coded instrument type", "conventions": "Argo reference table 8"},
    )
    _scalar(
        "PROJECT_NAME",
        m("project_name"),
        STRING64,
        {"long_name": "Program under which the float was deployed"},
    )
    _scalar(
        "DATA_CENTRE",
        m("data_centre") or institution,
        STRING2,
        {
            "long_name": "Data centre in charge of float real-time processing",
            "conventions": "Argo reference table 4",
        },
    )
    _scalar("PI_NAME", m("pi_name"), STRING64, {"long_name": "Name of the principal investigator"})
    _scalar(
        "ANOMALY",
        m("anomaly"),
        STRING256,
        {"long_name": "Describe any anomalies or problems the float may have had"},
    )
    _scalar(
        "BATTERY_TYPE",
        m("battery_type"),
        STRING64,
        {"long_name": "Type of battery packs in the float"},
    )
    _scalar(
        "BATTERY_PACKS",
        m("battery_packs"),
        STRING64,
        {"long_name": "Configuration of battery packs in the float"},
    )
    _scalar(
        "CONTROLLER_BOARD_TYPE_PRIMARY",
        m("controller_board_type_primary"),
        STRING32,
        {"long_name": "Type of primary controller board"},
    )
    _scalar(
        "CONTROLLER_BOARD_TYPE_SECONDARY",
        m("controller_board_type_secondary"),
        STRING32,
        {"long_name": "Type of secondary controller board"},
    )
    _scalar(
        "CONTROLLER_BOARD_SERIAL_NO_PRIMARY",
        m("controller_board_serial_no_primary"),
        STRING32,
        {"long_name": "Serial number of the primary controller board"},
    )
    _scalar(
        "CONTROLLER_BOARD_SERIAL_NO_SECONDARY",
        m("controller_board_serial_no_secondary"),
        STRING32,
        {"long_name": "Serial number of the secondary controller board"},
    )
    _scalar(
        "SPECIAL_FEATURES",
        m("special_features"),
        STRING1024,
        {"long_name": "Extra features of the float (algorithms, compressee etc.)"},
    )
    _scalar("FLOAT_OWNER", m("float_owner"), STRING64, {"long_name": "Float owner"})
    _scalar(
        "OPERATING_INSTITUTION",
        m("operating_institution"),
        STRING64,
        {"long_name": "Operating institution of the float"},
    )
    _scalar(
        "CUSTOMISATION",
        m("customisation"),
        STRING1024,
        {"long_name": "Float customisation, i.e. (institution and modifications)"},
    )

    # ---- deployment ----
    _date(
        "LAUNCH_DATE",
        _normalise_date(m("launch_date")),
        {"long_name": "Date (UTC) of the deployment", "conventions": "YYYYMMDDHHMISS"},
    )
    launch_lat = getattr(meta, "launch_latitude", None) if meta is not None else None
    launch_lon = getattr(meta, "launch_longitude", None) if meta is not None else None
    data_vars["LAUNCH_LATITUDE"] = xr.DataArray(
        np.float64(launch_lat if launch_lat is not None else DOUBLE_FILL),
        attrs={
            "long_name": "Latitude of the float when deployed",
            "units": "degree_north",
            "_FillValue": DOUBLE_FILL,
            "valid_min": np.float64(-90.0),
            "valid_max": np.float64(90.0),
        },
    )
    data_vars["LAUNCH_LONGITUDE"] = xr.DataArray(
        np.float64(launch_lon if launch_lon is not None else DOUBLE_FILL),
        attrs={
            "long_name": "Longitude of the float when deployed",
            "units": "degree_east",
            "_FillValue": DOUBLE_FILL,
            "valid_min": np.float64(-180.0),
            "valid_max": np.float64(180.0),
        },
    )
    _flag(
        "LAUNCH_QC",
        m("launch_qc"),
        {
            "long_name": "Quality on launch date, time and location",
            "conventions": "Argo reference table 2",
        },
    )
    _date(
        "START_DATE",
        start_date or _normalise_date(m("start_date")),
        {
            "long_name": "Date (UTC) of the first descent of the float",
            "conventions": "YYYYMMDDHHMISS",
        },
    )
    _flag(
        "START_DATE_QC",
        m("start_date_qc"),
        {"long_name": "Quality on start date", "conventions": "Argo reference table 2"},
    )
    _date(
        "STARTUP_DATE",
        _normalise_date(m("startup_date")),
        {
            "long_name": "Date (UTC) of the activation of the float",
            "conventions": "YYYYMMDDHHMISS",
        },
    )
    _flag(
        "STARTUP_DATE_QC",
        m("startup_date_qc"),
        {"long_name": "Quality on startup date", "conventions": "Argo reference table 2"},
    )
    _scalar(
        "DEPLOYMENT_PLATFORM",
        m("deployment_platform"),
        STRING32,
        {"long_name": "Identifier of the deployment platform"},
    )
    _scalar(
        "DEPLOYMENT_CRUISE_ID",
        m("deployment_cruise_id"),
        STRING32,
        {
            "long_name": (
                "Identification number or reference number of the cruise used to deploy the float"
            )
        },
    )
    _scalar(
        "DEPLOYMENT_REFERENCE_STATION_ID",
        m("deployment_reference_station_id"),
        STRING256,
        {
            "long_name": (
                "Identifier or reference number of co-located "
                "stations used to verify the first profile"
            )
        },
    )
    _date(
        "END_MISSION_DATE",
        _normalise_date(m("end_mission_date")),
        {
            "long_name": "Date (UTC) of the end of mission of the float",
            "conventions": "YYYYMMDDHHMISS",
        },
    )
    _flag(
        "END_MISSION_STATUS",
        m("end_mission_status"),
        {
            "long_name": "Status of the end of mission of the float",
            "conventions": "T:No more transmission received, R:Retrieved",
        },
    )

    # ---- configuration ----
    _vector(
        "LAUNCH_CONFIG_PARAMETER_NAME",
        _padded(launch_names, n_launch_config),
        STRING128,
        "N_LAUNCH_CONFIG_PARAM",
        {"long_name": "Name of configuration parameter at launch"},
    )
    data_vars["LAUNCH_CONFIG_PARAMETER_VALUE"] = xr.DataArray(
        _numeric(launch_values, n_launch_config),
        dims=("N_LAUNCH_CONFIG_PARAM",),
        attrs={
            "long_name": "Value of configuration parameter at launch",
            "_FillValue": DOUBLE_FILL,
        },
    )
    _vector(
        "CONFIG_PARAMETER_NAME",
        _padded(config_names, n_config),
        STRING128,
        "N_CONFIG_PARAM",
        {"long_name": "Name of configuration parameter"},
    )
    data_vars["CONFIG_PARAMETER_VALUE"] = xr.DataArray(
        _numeric(config_values, n_config).reshape(1, n_config).repeat(n_missions, axis=0),
        dims=("N_MISSIONS", "N_CONFIG_PARAM"),
        attrs={"long_name": "Value of configuration parameter", "_FillValue": DOUBLE_FILL},
    )
    # CONFIG_MISSION_NUMBER is 1-based by its own stated convention
    # ("1 : first complete mission") and every reference carries 1. Some
    # registry rows store a 0-based counter; normalise rather than emit
    # a value that contradicts the variable's conventions attribute.
    mission_ints = np.full(n_missions, INT_FILL, dtype=np.int32)
    for i, value in enumerate(mission_numbers[:n_missions]):
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            continue
        mission_ints[i] = np.int32(number + 1 if number < 1 else number)
    if not mission_numbers:
        mission_ints[:] = np.arange(1, n_missions + 1, dtype=np.int32)
    data_vars["CONFIG_MISSION_NUMBER"] = xr.DataArray(
        mission_ints,
        dims=("N_MISSIONS",),
        attrs={
            "long_name": "Unique number denoting the missions performed by the float",
            "conventions": "1...N, 1 : first complete mission",
            "_FillValue": INT_FILL,
        },
    )
    _vector(
        "CONFIG_MISSION_COMMENT",
        _padded(mission_comments, n_missions),
        STRING256,
        "N_MISSIONS",
        {"long_name": "Comment on configuration"},
    )

    # ---- sensors ----
    _vector(
        "SENSOR",
        _padded(sensors["SENSOR"], n_sensor),
        STRING32,
        "N_SENSOR",
        {
            "long_name": "Name of the sensor mounted on the float",
            "conventions": "Argo reference table 25",
        },
    )
    _vector(
        "SENSOR_MAKER",
        _padded(sensors["SENSOR_MAKER"], n_sensor),
        STRING256,
        "N_SENSOR",
        {"long_name": "Name of the sensor manufacturer", "conventions": "Argo reference table 26"},
    )
    _vector(
        "SENSOR_MODEL",
        _padded(sensors["SENSOR_MODEL"], n_sensor),
        STRING256,
        "N_SENSOR",
        {"long_name": "Type of sensor", "conventions": "Argo reference table 27"},
    )
    _vector(
        "SENSOR_SERIAL_NO",
        _padded(sensors["SENSOR_SERIAL_NO"], n_sensor),
        STRING16,
        "N_SENSOR",
        {"long_name": "Serial number of the sensor"},
    )

    # ---- parameters ----
    _vector(
        "PARAMETER",
        _padded(params["PARAMETER"], n_param),
        STRING64,
        "N_PARAM",
        {
            "long_name": "Name of parameter computed from float measurements",
            "conventions": "Argo reference table 3",
        },
    )
    _vector(
        "PARAMETER_SENSOR",
        _padded(params["PARAMETER_SENSOR"], n_param),
        STRING128,
        "N_PARAM",
        {
            "long_name": "Name of the sensor that measures this parameter",
            "conventions": "Argo reference table 25",
        },
    )
    _vector(
        "PARAMETER_UNITS",
        _padded(params["PARAMETER_UNITS"], n_param),
        STRING32,
        "N_PARAM",
        {"long_name": "Units of accuracy and resolution of the parameter"},
    )
    _vector(
        "PARAMETER_ACCURACY",
        _padded(params["PARAMETER_ACCURACY"], n_param),
        STRING32,
        "N_PARAM",
        {"long_name": "Accuracy of the parameter"},
    )
    _vector(
        "PARAMETER_RESOLUTION",
        _padded(params["PARAMETER_RESOLUTION"], n_param),
        STRING32,
        "N_PARAM",
        {"long_name": "Resolution of the parameter"},
    )
    _vector(
        "PREDEPLOYMENT_CALIB_EQUATION",
        _padded(params["PREDEPLOYMENT_CALIB_EQUATION"], n_param),
        STRING1024,
        "N_PARAM",
        {"long_name": "Calibration equation for this parameter"},
    )
    _vector(
        "PREDEPLOYMENT_CALIB_COEFFICIENT",
        _padded(params["PREDEPLOYMENT_CALIB_COEFFICIENT"], n_param),
        STRING1024,
        "N_PARAM",
        {"long_name": "Calibration coefficients for this equation"},
    )
    _vector(
        "PREDEPLOYMENT_CALIB_COMMENT",
        _padded(params["PREDEPLOYMENT_CALIB_COMMENT"], n_param),
        STRING1024,
        "N_PARAM",
        {"long_name": "Comment applying to this parameter calibration"},
    )

    out = xr.Dataset(data_vars)
    globals_ = standard_globals(
        title="Argo float metadata file",
        institution=m("data_centre") or institution,
        feature_type="",
    )
    # The metadata references carry no featureType (there is no
    # geophysical feature in this product).
    globals_.pop("featureType", None)
    out.attrs.update(globals_)
    return out


def _numeric(values: list[str], length: int) -> np.ndarray:
    """Convert a numbered text block to a float64 column of ``length``."""
    out = np.full(length, DOUBLE_FILL, dtype=np.float64)
    for i, value in enumerate(values[:length]):
        try:
            out[i] = np.float64(float(value))
        except (TypeError, ValueError):
            continue
    return out


def write_metadata_file(ds: xr.Dataset, path: Path) -> None:
    """Write a metadata dataset to ``path`` in ADMT dimension order."""
    fixed: dict[str, int | None] = {
        "STRING2": STRING2,
        "STRING4": STRING4,
        "STRING8": STRING8,
        "STRING16": STRING16,
        "STRING32": STRING32,
        "STRING64": STRING64,
        "STRING128": STRING128,
        "STRING256": STRING256,
        "STRING1024": STRING1024,
        "DATE_TIME": DATE_TIME_LEN,
        # Unlimited, matching the references.
        "N_MISSIONS": None,
        "N_POSITIONING_SYSTEM": int(ds.sizes.get("N_POSITIONING_SYSTEM", 1)),
        "N_TRANS_SYSTEM": int(ds.sizes.get("N_TRANS_SYSTEM", 1)),
        # Clamped to >=1: netCDF4 turns a zero-length dimension into a
        # second record dimension, which NETCDF3_CLASSIC rejects outright.
        "N_CONFIG_PARAM": max(int(ds.sizes.get("N_CONFIG_PARAM", 0)), 1),
        "N_LAUNCH_CONFIG_PARAM": max(int(ds.sizes.get("N_LAUNCH_CONFIG_PARAM", 0)), 1),
        "N_PARAM": max(int(ds.sizes.get("N_PARAM", 0)), 1),
        "N_SENSOR": max(int(ds.sizes.get("N_SENSOR", 0)), 1),
    }
    write_admt_dataset(
        ds,
        path,
        fixed_dims=fixed,
        dim_order=(
            "STRING2",
            "STRING4",
            "STRING8",
            "STRING16",
            "STRING32",
            "STRING64",
            "STRING128",
            "STRING256",
            "STRING1024",
            "DATE_TIME",
            "N_MISSIONS",
            "N_POSITIONING_SYSTEM",
            "N_TRANS_SYSTEM",
            "N_CONFIG_PARAM",
            "N_LAUNCH_CONFIG_PARAM",
            "N_PARAM",
            "N_SENSOR",
        ),
    )


__all__ = [
    "build_metadata_dataset",
    "numbered_block",
    "write_metadata_file",
]
