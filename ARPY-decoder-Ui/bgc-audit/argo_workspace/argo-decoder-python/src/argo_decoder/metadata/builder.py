"""Metadata builder — translate a :class:`FloatRegistryRow` into the
``info.json`` / ``meta.json`` pair consumed by the decoder (and, during
transition, by MATLAB).

The builder is the *only* module that knows the mapping between canonical
registry field names and the legacy MATLAB JSON keys. When we eventually
stop materialising JSON and pass :class:`FloatInfo` / :class:`FloatMeta`
to the decoder in-memory, only this module and its tests will go away —
all decoder code imports the JSON-contract models.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from argo_decoder.metadata.models import (
    END_DECODING_SENTINEL,
    FloatInfo,
    FloatMeta,
    FloatRegistryRow,
    SensorEntry,
)

# ---------------------------------------------------------------------------
# Info builder
# ---------------------------------------------------------------------------


def build_info(row: FloatRegistryRow) -> FloatInfo:
    """Translate a registry row into a ``*_info.json``-compatible record."""
    data: dict[str, Any] = {
        "WMO": row.wmo,
        "PTT": row.ptt,
        "FLOAT_TYPE": row.platform_type,
        "DECODER_VERSION": row.decoder_version,
        "DECODER_ID": row.decoder_id,
        "FRAME_LENGTH": row.frame_length,
        "CYCLE_LENGTH": row.cycle_length_hours,
        "DRIFT_SAMPLING_PERIOD": row.drift_sampling_period_hours,
        "DELAI": row.delay_before_mission_minutes,
        "LAUNCH_DATE": row.launch_date_utc,
        "LAUNCH_LON": row.launch_lon,
        "LAUNCH_LAT": row.launch_lat,
        "END_DECODING_DATE": row.end_decoding_date or END_DECODING_SENTINEL,
        "REFERENCE_DAY": row.reference_day,
        "DM_FLAG": row.dm_flag,
        # Per-deployment cycle offset. Only the four-CSV backend supplies
        # it; the single-registry backend has no such column and the
        # FloatInfo default of 0 preserves the previous behaviour.
        "NP0": _row_extra(row, "profile_count_offset", "0") or "0",
        # Wire-protocol family (four-CSV backend only); empty for legacy rows.
        "PROFILE_CLASS": _row_extra(row, "profile_class", ""),
    }
    return FloatInfo.model_validate(data)


def write_info_json(info: FloatInfo, out_dir: Path | str) -> Path:
    """Write ``<wmo>_<ptt>_info.json`` in legacy MATLAB layout. Returns path."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{info.wmo}_{info.ptt}_info.json"
    path.write_text(
        json.dumps(info.to_legacy_dict(), indent=3, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# Meta builder
# ---------------------------------------------------------------------------


def _numed_list(values: list[str], prefix: str) -> list[dict[str, str]]:
    """Convert ``["A","B"]`` to MATLAB-style ``[{"PREFIX_1":"A","PREFIX_2":"B"}]``."""
    if not values:
        return []
    return [{f"{prefix}_{i + 1}": str(v) for i, v in enumerate(values)}]


def _numed_lists(values: list[str], *prefixes: str) -> list[list[dict[str, str]]]:
    return [_numed_list(values, p) for p in prefixes]


def _sensor_vectors(sensors: list[SensorEntry]) -> dict[str, list[dict[str, str]]]:
    """Render SENSOR / SENSOR_MAKER / SENSOR_MODEL / SENSOR_SERIAL_NO blocks."""
    names: list[str] = []
    makers: list[str] = []
    models: list[str] = []
    serials: list[str] = []
    for s in sensors:
        names.append(s.sensor)
        makers.append(s.make or "n/a")
        models.append(s.model or "n/a")
        serials.append(s.serial or "n/a")
    return {
        "SENSOR": _numed_list(names, "SENSOR"),
        "SENSOR_MAKER": _numed_list(makers, "SENSOR_MAKER"),
        "SENSOR_MODEL": _numed_list(models, "SENSOR_MODEL"),
        "SENSOR_SERIAL_NO": _numed_list(serials, "SENSOR_SERIAL_NO"),
    }


# Conservative sensor→primary-parameter mapping used by the Phase 1 builder.
# One PARAMETER entry per sensor; full scientific parameter expansion is added
# alongside each sensor module in Phase 3+.
#
# ``CTD_CNDC`` maps to the *reported* parameter ``PSAL``, not ``CNDC``.
# The sensor measures conductivity but the DAC publishes the derived
# practical salinity, so ``PARAMETER_SENSOR`` stays ``CTD_CNDC`` while
# ``PARAMETER`` reads ``PSAL``. Verified in 10/10 GDAC ``_meta.nc``
# references spanning four DACs (incois, coriolis, bodc, aoml) and three
# platform families (APEX, ARVOR, PROVOR_III): not one publishes ``CNDC``
# as a PARAMETER entry. This mirrors the CNDC-not-exported decision
# already taken in the profile writer (``mono_profile._EXPORTED_PARAMS``).
#
# The unit strings follow the INCOIS house convention -- ``deg C``,
# ``Siemens/meter``, ``decibars`` -- observed in 5/5 INCOIS APEX/ARVOR
# floats. Note this is a DAC convention, *not* the Argo NVS R03
# controlled vocabulary, which specifies ``degree_Celsius``/``psu``/
# ``decibar`` and is what coriolis, bodc and aoml emit. We match our
# publishing DAC because the goal is INCOIS GDAC parity; the file checker
# does not validate PARAMETER_UNITS against any table.
_DEFAULT_PARAM_MAP = {
    "CTD_PRES": ("PRES", "decibars", "2.4", "0.1"),
    "CTD_TEMP": ("TEMP", "deg C", "0.002", "0.001"),
    "CTD_CNDC": ("PSAL", "Siemens/meter", "0.005", "0.001"),
    "OPTODE_DOXY": ("DOXY", "micromole/kg", "8 umol/kg or 10%", "1 umol/kg"),
    "FLUOR_CHLA": ("CHLA", "mg/m3", "n/a", "n/a"),
    "BBP": ("BBP700", "1/m", "n/a", "n/a"),
    "PH": ("PH_IN_SITU_TOTAL", "pH", "n/a", "n/a"),
    "NITRATE": ("NITRATE", "micromole/kg", "n/a", "n/a"),
}


def _parameter_vectors(sensors: list[SensorEntry]) -> dict[str, list[dict[str, str]]]:
    """Render PARAMETER / PARAMETER_SENSOR / PARAMETER_UNITS / ... blocks."""
    psensor: list[str] = []
    punits: list[str] = []
    paccuracy: list[str] = []
    presolution: list[str] = []
    pname: list[str] = []
    peq: list[str] = []
    pcoeff: list[str] = []
    for s in sensors:
        param, unit, acc, res = _DEFAULT_PARAM_MAP.get(s.sensor, (s.sensor, "n/a", "n/a", "n/a"))
        pname.append(param)
        psensor.append(s.sensor)
        punits.append(unit)
        # Measured accuracy/resolution when the calibration sheet supplies
        # it, else the manufacturer figures above. INCOIS publishes the
        # measured values, which are zeros for these CTDs.
        paccuracy.append(str(getattr(s, "accuracy", "") or acc))
        presolution.append(str(getattr(s, "resolution", "") or res))
        # Pre-deployment calibration, when the registry carries it. The
        # equation is a per-sensor-model constant and the coefficients are
        # per-float; both are supplied by the metadata backend rather than
        # synthesised here. Absent calibration stays "n/a" -- never invented.
        calibration = s.calibration[0] if s.calibration else None
        peq.append(calibration.equation if calibration and calibration.equation else "n/a")
        pcoeff.append(calibration.comment if calibration and calibration.comment else "n/a")
    return {
        "PARAMETER": _numed_list(pname, "PARAMETER"),
        "PARAMETER_SENSOR": _numed_list(psensor, "PARAMETER_SENSOR"),
        "PARAMETER_UNITS": _numed_list(punits, "PARAMETER_UNITS"),
        "PARAMETER_ACCURACY": _numed_list(paccuracy, "PARAMETER_ACCURACY"),
        "PARAMETER_RESOLUTION": _numed_list(presolution, "PARAMETER_RESOLUTION"),
        "PREDEPLOYMENT_CALIB_EQUATION": _numed_list(peq, "PREDEPLOYMENT_CALIB_EQUATION"),
        "PREDEPLOYMENT_CALIB_COEFFICIENT": _numed_list(pcoeff, "PREDEPLOYMENT_CALIB_COEFFICIENT"),
    }


def _config_pairs(row: FloatRegistryRow) -> list[tuple[str, str]]:
    """Return the ``(CONFIG_name, value)`` pairs carried by the registry row.

    The four-CSV backend attaches these as a row extra; the single-CSV
    registry has no configuration block and yields an empty list, which
    preserves the previous behaviour exactly.
    """
    pairs = getattr(row, "config_parameters", None)
    if not pairs:
        return []
    return [(str(name), str(value)) for name, value in pairs]


def _config_names(row: FloatRegistryRow) -> list[str]:
    return [name for name, _ in _config_pairs(row)]


def _config_values(row: FloatRegistryRow) -> list[str]:
    return [value for _, value in _config_pairs(row)]


def _row_extra(row: FloatRegistryRow, name: str, default: str = "") -> str:
    """Read an optional registry extra as a string."""
    value = getattr(row, name, None)
    return default if value in (None, "") else str(value)


def _format_meta_dt(dt: datetime | None, sentinel_open: bool = False) -> str:
    if dt is None:
        return ""
    if sentinel_open and dt == END_DECODING_SENTINEL:
        return ""
    return dt.strftime("%d/%m/%Y %H:%M:%S")


def build_meta(row: FloatRegistryRow) -> FloatMeta:
    """Translate a registry row into a ``*_meta.json``-compatible record."""
    # Short PTT used inside *_meta.json (MATLAB stores a suffix, not the full IMEI).
    short_ptt = row.ptt
    if row.imei and row.imei.endswith(row.ptt):
        # ptt is already the short suffix (already last 6 or so digits)
        pass

    launch = row.launch_date_utc
    # START_DATE is "date of the first descent" (Argo User Manual v3.3
    # §2.4), a different instant from the launch -- the manual defines
    # LAUNCH_DATE, STARTUP_DATE and START_DATE separately. Falling back
    # to the launch time published a value the registry never stated, so
    # an absent start date stays absent; the platform layer supplies its
    # own fallback and the field is not mandatory (§2.4.9).
    start = row.start_date_utc
    end_decoding = (
        ""
        if row.end_decoding_date == END_DECODING_SENTINEL
        else _format_meta_dt(row.end_decoding_date)
    )

    sensors_block = _sensor_vectors(row.sensors)
    param_block = _parameter_vectors(row.sensors)

    data = {
        "ARGO_USER_MANUAL_VERSION": row.argo_user_manual_version,
        "PLATFORM_NUMBER": str(row.wmo),
        "PTT": short_ptt,
        "IMEI": row.imei or short_ptt,
        "FLOAT_TRANSMISSION_TYPE": str(row.transmission_type) if row.transmission_type else "",
        "TRANS_SYSTEM": _numed_list(row.transmission_system, "TRANS_SYSTEM"),
        "TRANS_SYSTEM_ID": _numed_list(
            [_row_extra(row, "trans_system_id", "n/a")] * len(row.transmission_system),
            "TRANS_SYSTEM_ID",
        ),
        "TRANS_FREQUENCY": _numed_list(
            [_row_extra(row, "trans_frequency", "n/a")] * len(row.transmission_system),
            "TRANS_FREQUENCY",
        ),
        "POSITIONING_SYSTEM": _numed_list(row.positioning_system, "POSITIONING_SYSTEM"),
        "PLATFORM_FAMILY": row.platform_family,
        "PLATFORM_TYPE": row.platform_type,
        "PLATFORM_MAKER": row.platform_maker,
        "FIRMWARE_VERSION": row.firmware_version,
        "MANUAL_VERSION": row.manual_version,
        "FLOAT_SERIAL_NO": row.float_serial_no,
        "STANDARD_FORMAT_ID": _row_extra(row, "standard_format_id", "n/a"),
        "DAC_FORMAT_ID": _row_extra(row, "dac_format_id", row.decoder_version),
        "WMO_INST_TYPE": row.wmo_inst_type,
        "PROJECT_NAME": row.project_name,
        "DATA_CENTRE": row.data_centre,
        "PI_NAME": row.pi_name,
        "ANOMALY": "",
        "BATTERY_TYPE": row.battery_type or "n/a",
        "BATTERY_PACKS": row.battery_packs,
        "CONTROLLER_BOARD_TYPE_PRIMARY": row.controller_board_primary_type,
        "CONTROLLER_BOARD_TYPE_SECONDARY": "",
        "CONTROLLER_BOARD_SERIAL_NO_PRIMARY": row.controller_board_primary_serial,
        "CONTROLLER_BOARD_SERIAL_NO_SECONDARY": "",
        "SPECIAL_FEATURES": "",
        "FLOAT_OWNER": row.float_owner,
        "OPERATING_INSTITUTION": row.operating_institution,
        "CUSTOMISATION": "",
        "LAUNCH_DATE": _format_meta_dt(launch),
        "LAUNCH_LATITUDE": f"{row.launch_lat:.4f}",
        "LAUNCH_LONGITUDE": f"{row.launch_lon:.4f}",
        "LAUNCH_QC": str(row.launch_qc),
        "START_DATE": _format_meta_dt(start),
        # START_DATE_QC carries a code from Argo reference table 2.
        #
        # Standards basis (verified 2026-09-08):
        #   * Argo User's Manual 3.44.0 (10 Jul 2025) §2.4.5 -- START_DATE
        #     is "Date (UTC) of the first descent of the float";
        #     START_DATE_QC is "Quality flag on start date", conventions
        #     "Argo reference table 2".
        #   * Argo QC Manual 3.9 §6.1 Reference Table 2 --
        #       '9' = "Missing value. Data parameter will record
        #             FillValue."
        #       '1' = "Good data. All Argo real-time QC tests passed."
        #     '9' is the only code whose published definition describes a
        #     parameter holding FillValue, which is exactly our case.
        #   * UM 3.44.0 §2.4.9 lists the mandatory metadata; START_DATE is
        #     NOT among them (LAUNCH_DATE is), so leaving it at fill is
        #     permitted.
        #
        # '1' would assert "Good data ... all real-time QC tests passed"
        # about a value that was never published -- logically vacuous and
        # actively misleading to a downstream user. Blank is rejected
        # outright by the GDAC FileChecker (CK_0122, "START_DATE_QC: ' '
        # Status: Invalid") because it is not a table-2 altLabel.
        #
        # The flag therefore describes the true state of the date rather
        # than being copied from the reference product.
        "START_DATE_QC": "1" if _format_meta_dt(start) else "9",
        "STARTUP_DATE": "",
        "STARTUP_DATE_QC": "",
        "DEPLOYMENT_PLATFORM": row.deployment_platform,
        "DEPLOYMENT_CRUISE_ID": row.deployment_cruise_id,
        "DEPLOYMENT_REFERENCE_STATION_ID": row.deployment_station_id,
        "END_MISSION_DATE": _row_extra(row, "end_mission_date"),
        "END_MISSION_STATUS": _row_extra(row, "end_mission_status"),
        "END_DECODING_DATE": end_decoding,
        # The launch configuration is the mission configuration for a float
        # that was never reprogrammed. Verified on the INCOIS GDAC sample:
        # 10/11 floats carry byte-identical LAUNCH_CONFIG_* and
        # CONFIG_PARAMETER_* blocks; the single exception (2902276) is a BGC
        # float with a mid-life mission change, which is out of scope for the
        # current one-mission-per-float model.
        "LAUNCH_CONFIG_PARAMETER_NAME": _numed_list(
            _config_names(row), "LAUNCH_CONFIG_PARAMETER_NAME"
        ),
        "LAUNCH_CONFIG_PARAMETER_VALUE": _numed_list(
            _config_values(row), "LAUNCH_CONFIG_PARAMETER_VALUE"
        ),
        "CONFIG_PARAMETER_NAME": _numed_list(_config_names(row), "CONFIG_PARAMETER_NAME"),
        "CONFIG_PARAMETER_VALUE": _numed_list(_config_values(row), "CONFIG_PARAMETER_VALUE"),
        "CONFIG_MISSION_NUMBER": [{"CONFIG_MISSION_NUMBER_1": "0"}],
        "CONFIG_MISSION_COMMENT": [],
        "CONFIG_REPETITION_RATE": [],
        "SENSOR_MOUNTED_ON_FLOAT": _numed_list(
            _mounted_sensors(row.sensors), "SENSOR_MOUNTED_ON_FLOAT"
        ),
        "PREDEPLOYMENT_CALIB_COMMENT": [],
        "CALIB_RT_PARAMETER": [],
        "CALIB_RT_EQUATION": [],
        "CALIB_RT_COEFFICIENT": [],
        "CALIB_RT_COMMENT": [],
        "CALIB_RT_ADJUSTED_ERROR": [],
        "CALIB_RT_ADJ_ERROR_METHOD": [],
        "CALIB_RT_DATE": [],
        "CALIBRATION_COEFFICIENT": [],
        "CP_COR": [],
        "RT_OFFSET": [],
    }
    data.update(sensors_block)
    data.update(param_block)

    return FloatMeta.model_validate(data)


def _mounted_sensors(sensors: list[SensorEntry]) -> list[str]:
    """Collapse detailed sensor names to the coarse ``SENSOR_MOUNTED_ON_FLOAT``
    list (e.g. ``CTD_PRES, CTD_TEMP, CTD_CNDC -> CTD``)."""
    seen: list[str] = []
    for s in sensors:
        base = s.sensor.split("_", 1)[0] if "_" in s.sensor else s.sensor
        # Collapse CTD_PRES/CTD_TEMP/CTD_CNDC to CTD
        if base in {"CTD", "OPTODE", "FLUOR", "BBP", "PH", "NITRATE", "PHSEN", "IRRAD", "PAR"}:
            short = {"OPTODE": "OPTODE", "FLUOR": "FLUOR", "BBP": "BBP"}.get(base, base)
        else:
            short = base
        if short not in seen:
            seen.append(short)
    return seen


def write_meta_json(meta: FloatMeta, out_dir: Path | str) -> Path:
    """Write ``<wmo>_meta.json`` in legacy MATLAB layout. Returns path."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{meta.platform_number}_meta.json"
    # serialise via alias -> dump JSON
    data = meta.model_dump(by_alias=True, exclude_none=True)
    path.write_text(json.dumps(data, indent=3, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Convenience: materialise both JSON files for a WMO
# ---------------------------------------------------------------------------


def materialize(
    row: FloatRegistryRow,
    out_dir: Path | str,
    *,
    meta_dir: Path | str | None = None,
) -> tuple[Path, Path]:
    """Write both info.json and meta.json for a registry row.

    Parameters
    ----------
    row:
        Registry row to materialize.
    out_dir:
        Directory to write ``<wmo>_<ptt>_info.json`` into.
    meta_dir:
        Optional separate directory for ``<wmo>_meta.json``; defaults to
        ``out_dir`` (useful when the legacy tree splits info/meta into
        separate folders, which it always does in practice).
    """
    out_dir = Path(out_dir)
    meta_out_dir = Path(meta_dir) if meta_dir is not None else out_dir
    info = build_info(row)
    meta = build_meta(row)
    return write_info_json(info, out_dir), write_meta_json(meta, meta_out_dir)
