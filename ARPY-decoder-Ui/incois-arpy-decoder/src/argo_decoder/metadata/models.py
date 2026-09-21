"""Typed metadata models.

Three contracts live here:

* :class:`FloatInfo`  — byte-compatible mirror of the legacy
  ``<wmo>_<ptt>_info.json`` consumed by the decoder.
* :class:`FloatMeta`  — byte-compatible mirror of ``<wmo>_meta.json``
  (Argo meta-file variables).
* :class:`FloatRegistryRow` — the **single source of truth** row in the
  central metadata registry (see MIGRATION_DIRECT_PLAN §4.5.4). All
  metadata backends (CSV today, SQLite/Postgres later) emit this type.

The builder (see :mod:`argo_decoder.metadata.builder`) maps a
:class:`FloatRegistryRow` to a :class:`FloatInfo` + :class:`FloatMeta`
pair; the decoder imports only those two JSON-contract types and never
sees the registry row directly.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Sentinel end-decoding date used in Coriolis legacy files.
END_DECODING_SENTINEL = datetime(9999, 12, 31, 23, 59, 59, tzinfo=None)


# ---------------------------------------------------------------------------
# FloatInfo  (mirror of *_info.json)
# ---------------------------------------------------------------------------


class FloatInfo(BaseModel):
    """Decoding parameters for one float (mirror of ``<wmo>_<ptt>_info.json``).

    The model keeps the legacy all-caps JSON keys via ``alias=`` and is
    tolerant of extra keys (``extra="allow"``) so future MATLAB-side
    additions do not crash loading.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    wmo: int = Field(alias="WMO")
    ptt: str = Field(alias="PTT")
    float_type: str = Field(alias="FLOAT_TYPE")
    decoder_version: str = Field(alias="DECODER_VERSION")
    decoder_id: int = Field(alias="DECODER_ID")
    frame_length: int = Field(alias="FRAME_LENGTH")
    cycle_length_hours: int = Field(alias="CYCLE_LENGTH")
    drift_sampling_period_hours: float = Field(alias="DRIFT_SAMPLING_PERIOD")
    delay_minutes: int = Field(alias="DELAI", default=-1)
    launch_date: datetime = Field(alias="LAUNCH_DATE")
    launch_lon: float = Field(alias="LAUNCH_LON")
    launch_lat: float = Field(alias="LAUNCH_LAT")
    end_decoding_date: datetime = Field(alias="END_DECODING_DATE", default=END_DECODING_SENTINEL)
    reference_day: date = Field(alias="REFERENCE_DAY")
    dm_flag: bool = Field(alias="DM_FLAG", default=False)
    #: Wire-protocol family (e.g. ``arvor_i_sbe41cp``), set by the four-CSV
    #: backend from the sheet family signature (manufacturer + CTD model +
    #: comms). Family-level routing key: the numeric engine id inside a
    #: family comes from telemetry (Tech#1 firmware checksum), never from
    #: metadata. Empty for legacy info.json files, which keep routing by
    #: ``DECODER_ID``.
    profile_class: str = Field(alias="PROFILE_CLASS", default="")
    profile_count_offset: int = Field(alias="NP0", default=0)
    """Per-deployment cycle offset (the operator sheets' ``np0``).

    The float transmits a profile counter; the DAC publishes
    ``cycle = profile_id + wrap + np0``. ``wrap`` is a firmware property
    (the 8-bit counter roll-over), whereas ``np0`` is chosen per
    deployment: WMO 2901339 and 2901304 share firmware 061810 yet need
    -1 and 0 respectively. Defaults to 0 so floats whose registry has no
    value keep the layout's own offset.
    """

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------
    @classmethod
    def from_json_file(cls, path: str | Any) -> FloatInfo:
        p = str(path) if not isinstance(path, str) else path
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
        return cls.from_legacy_dict(data)

    @classmethod
    def from_legacy_dict(cls, data: dict[str, Any]) -> FloatInfo:
        """Parse a raw dict as produced by ``json.load`` on a legacy info file."""
        for key, fmt in (
            ("LAUNCH_DATE", "%Y%m%d%H%M%S"),
            ("END_DECODING_DATE", "%Y%m%d%H%M%S"),
        ):
            if key in data:
                v = str(data[key])
                if v == "99999999999999":
                    data[key] = END_DECODING_SENTINEL
                else:
                    data[key] = datetime.strptime(v, fmt)
        if "REFERENCE_DAY" in data:
            v = str(data["REFERENCE_DAY"])
            data["REFERENCE_DAY"] = datetime.strptime(v, "%Y%m%d").date()
        for int_key in ("WMO", "DECODER_ID", "FRAME_LENGTH", "CYCLE_LENGTH"):
            if int_key in data:
                data[int_key] = int(str(data[int_key]))
        for float_key in ("DRIFT_SAMPLING_PERIOD", "LAUNCH_LON", "LAUNCH_LAT"):
            if float_key in data:
                data[float_key] = float(str(data[float_key]))
        if "DELAI" in data:
            data["DELAI"] = int(str(data["DELAI"]))
        if "DM_FLAG" in data:
            data["DM_FLAG"] = str(data["DM_FLAG"]) not in ("0", "false", "False", "")
        return cls.model_validate(data)

    def to_legacy_dict(self) -> dict[str, str]:
        """Serialize back to the exact MATLAB-compatible flat JSON shape."""
        out: dict[str, str] = {
            "WMO": str(self.wmo),
            "PTT": self.ptt,
            "FLOAT_TYPE": self.float_type,
            "DECODER_VERSION": self.decoder_version,
            "DECODER_ID": str(self.decoder_id),
            "FRAME_LENGTH": str(self.frame_length),
            "CYCLE_LENGTH": str(self.cycle_length_hours),
            "DRIFT_SAMPLING_PERIOD": str(self.drift_sampling_period_hours),
            "DELAI": str(self.delay_minutes),
            "LAUNCH_DATE": self.launch_date.strftime("%Y%m%d%H%M%S"),
            "LAUNCH_LON": f"{self.launch_lon:.6f}".rstrip("0").rstrip("."),
            "LAUNCH_LAT": f"{self.launch_lat:.6f}".rstrip("0").rstrip("."),
            "REFERENCE_DAY": self.reference_day.strftime("%Y%m%d"),
            "DM_FLAG": "1" if self.dm_flag else "0",
        }
        if self.end_decoding_date == END_DECODING_SENTINEL:
            out["END_DECODING_DATE"] = "99999999999999"
        else:
            out["END_DECODING_DATE"] = self.end_decoding_date.strftime("%Y%m%d%H%M%S")
        return out


# ---------------------------------------------------------------------------
# FloatMeta  (mirror of *_meta.json)
# ---------------------------------------------------------------------------


class FloatMeta(BaseModel):
    """Argo metadata record (mirror of ``<wmo>_meta.json``).

    The model accepts the existing MATLAB-produced shape via aliases but
    the builder populates it from a :class:`FloatRegistryRow`. Free-form
    sensor/calibration/configuration blocks are kept as ``extra`` fields
    so we can round-trip meta files without losing information.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    argo_user_manual_version: str = Field(alias="ARGO_USER_MANUAL_VERSION", default="3.1")
    platform_number: str = Field(alias="PLATFORM_NUMBER", default="")
    ptt: str = Field(alias="PTT", default="")
    imei: str = Field(alias="IMEI", default="")
    trans_system: list[dict[str, str]] = Field(alias="TRANS_SYSTEM", default_factory=list)
    trans_system_id: list[dict[str, str]] = Field(alias="TRANS_SYSTEM_ID", default_factory=list)
    trans_frequency: list[dict[str, str]] = Field(alias="TRANS_FREQUENCY", default_factory=list)
    positioning_system: list[dict[str, str]] = Field(
        alias="POSITIONING_SYSTEM", default_factory=list
    )
    platform_family: str = Field(alias="PLATFORM_FAMILY", default="FLOAT")
    platform_type: str = Field(alias="PLATFORM_TYPE", default="")
    platform_maker: str = Field(alias="PLATFORM_MAKER", default="NKE")
    firmware_version: str = Field(alias="FIRMWARE_VERSION", default="")
    manual_version: str = Field(alias="MANUAL_VERSION", default="")
    float_serial_no: str = Field(alias="FLOAT_SERIAL_NO", default="")
    standard_format_id: str = Field(alias="STANDARD_FORMAT_ID", default="n/a")
    dac_format_id: str = Field(alias="DAC_FORMAT_ID", default="")
    wmo_inst_type: str = Field(alias="WMO_INST_TYPE", default="")
    project_name: str = Field(alias="PROJECT_NAME", default="")
    data_centre: str = Field(alias="DATA_CENTRE", default="IF")
    pi_name: str = Field(alias="PI_NAME", default="")
    anomaly: str = Field(alias="ANOMALY", default="")
    battery_type: str = Field(alias="BATTERY_TYPE", default="n/a")
    battery_packs: str = Field(alias="BATTERY_PACKS", default="")
    controller_board_type_primary: str = Field(alias="CONTROLLER_BOARD_TYPE_PRIMARY", default="")
    controller_board_type_secondary: str = Field(
        alias="CONTROLLER_BOARD_TYPE_SECONDARY", default=""
    )
    controller_board_serial_no_primary: str = Field(
        alias="CONTROLLER_BOARD_SERIAL_NO_PRIMARY", default=""
    )
    controller_board_serial_no_secondary: str = Field(
        alias="CONTROLLER_BOARD_SERIAL_NO_SECONDARY", default=""
    )
    special_features: str = Field(alias="SPECIAL_FEATURES", default="")
    float_owner: str = Field(alias="FLOAT_OWNER", default="IFREMER")
    operating_institution: str = Field(alias="OPERATING_INSTITUTION", default="")
    customisation: str = Field(alias="CUSTOMISATION", default="")
    launch_date: str = Field(alias="LAUNCH_DATE", default="")
    launch_latitude: float = Field(alias="LAUNCH_LATITUDE", default=0.0)
    launch_longitude: float = Field(alias="LAUNCH_LONGITUDE", default=0.0)
    launch_qc: str = Field(alias="LAUNCH_QC", default="1")
    start_date: str = Field(alias="START_DATE", default="")
    start_date_qc: str = Field(alias="START_DATE_QC", default="1")
    startup_date: str = Field(alias="STARTUP_DATE", default="")
    startup_date_qc: str = Field(alias="STARTUP_DATE_QC", default="")
    deployment_platform: str = Field(alias="DEPLOYMENT_PLATFORM", default="")
    deployment_cruise_id: str = Field(alias="DEPLOYMENT_CRUISE_ID", default="")
    deployment_reference_station_id: str = Field(
        alias="DEPLOYMENT_REFERENCE_STATION_ID", default=""
    )
    end_mission_date: str = Field(alias="END_MISSION_DATE", default="")
    end_mission_status: str = Field(alias="END_MISSION_STATUS", default="")
    end_decoding_date: str = Field(alias="END_DECODING_DATE", default="")

    @classmethod
    def from_json_file(cls, path: str | Any) -> FloatMeta:
        p = str(path) if not isinstance(path, str) else path
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
        return cls.model_validate(data)


# ---------------------------------------------------------------------------
# Sensor / calibration types (used by the registry row)
# ---------------------------------------------------------------------------


class SensorCalibration(BaseModel):
    """One calibration entry for a sensor parameter.

    In the central registry calibrations are stored as structured
    records; the builder expands them to the Argo meta-file
    ``PREDEPLOYMENT_CALIB_*`` / ``CALIBRATION_COEFFICIENT`` blocks.
    """

    model_config = ConfigDict(extra="allow")

    parameter: str = ""
    equation: str = "n/a"
    coefficients: dict[str, float] = Field(default_factory=dict)
    comment: str = ""
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class SensorEntry(BaseModel):
    """One sensor mounted on a float."""

    model_config = ConfigDict(extra="allow")

    sensor: str
    """Sensor family as known to the decoder, e.g. ``"CTD_PRES"``, ``"OPTODE_DOXY"``."""
    make: str = ""
    model: str = ""
    serial: str = ""
    calibration: list[SensorCalibration] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# FloatRegistryRow — central registry schema (v1)
# ---------------------------------------------------------------------------


_PLATFORM_MAKERS = {"NKE", "APEX", "NEMO", "NOVA", "METOCEAN", "REMOTE_SENSING", "PFV2", "WRC"}
_PLATFORM_TYPES = {
    "PROVOR",
    "ARVOR",
    "ARVOR_D",
    "ARVOR_C",
    "ARVOR_I",
    "ARVOR_I_ICE",
    "ARVOR_N",
    "PROVOR_CTS4",
    "PROVOR_CTS5",
    "APEX",
    "APEX_APF9",
    "APEX_APF11",
    "NEMO",
    "NOVA",
    "REMOTE_SENSING",
    "PFV2",
}
_PLATFORM_FAMILIES = {"FLOAT", "FLOAT_DEEP", "FLOAT_BGC", "FLOAT_ICE"}
_TRANSMISSION_TYPES = {1, 2, 3, 4}
_DATA_CENTRES = {"IF", "AO", "BO", "CJ", "CS", "GE", "HZ", "IN", "JK", "KM", "ME", "NM"}


class FloatRegistryRow(BaseModel):
    """Canonical central-registry row (schema v1).

    The full column list matches ``MIGRATION_DIRECT_PLAN.md`` §4.5.4.
    Required fields are enforced by Pydantic; the CSV loader returns
    instances of this class and validators check cross-field invariants.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    # --- identity ---
    wmo: int
    ptt: str
    imei: str = ""
    platform_maker: str = "NKE"
    platform_type: str = "PROVOR"
    platform_family: str = "FLOAT"
    transmission_type: int = 3  # IRIDIUM_SBD

    # --- decoder routing ---
    decoder_id: int = 0
    decoder_version: str = ""
    firmware_version: str = ""
    manual_version: str = ""

    # --- mission parameters ---
    frame_length: int = 31
    cycle_length_hours: int = 240
    drift_sampling_period_hours: float = 3.0
    delay_before_mission_minutes: int = -1

    # --- launch / reference times ---
    launch_date_utc: datetime
    launch_lon: float = 0.0
    launch_lat: float = 0.0
    launch_qc: int = 1
    start_date_utc: datetime | None = None
    reference_day: date
    end_decoding_date: datetime = END_DECODING_SENTINEL
    dm_flag: bool = False

    # --- Argo bookkeeping ---
    argo_user_manual_version: str = "3.1"
    wmo_inst_type: str = ""
    data_centre: str = "IF"
    pi_name: str = ""
    project_name: str = ""
    float_owner: str = "IFREMER"
    operating_institution: str = ""

    # --- hardware ---
    battery_type: str = ""
    battery_packs: str = ""
    controller_board_primary_type: str = ""
    controller_board_primary_serial: str = ""
    float_serial_no: str = ""
    deployment_platform: str = ""
    deployment_cruise_id: str = ""
    deployment_station_id: str = ""

    # --- sensors / configuration ---
    sensors: list[SensorEntry] = Field(default_factory=list)
    transmission_system: list[str] = Field(default_factory=lambda: ["IRIDIUM"])
    positioning_system: list[str] = Field(default_factory=lambda: ["GPS", "IRIDIUM"])
    config_profile_ref: str = ""
    profile_count_offset: int = 0
    """Per-deployment cycle offset (``np0`` in the operator sheets).

    Added to the transmitted profile counter after the firmware's
    roll-over correction: ``cycle = profile_id + wrap + np0``.
    """

    # --- audit ---
    notes: str = ""
    registry_schema_version: str = "1.0.0"
    registry_row_updated_utc: datetime = Field(
        default_factory=lambda: datetime.now(UTC).replace(tzinfo=None)
    )

    # ----- validators -----------------------------------------------------
    @field_validator("launch_date_utc", "start_date_utc", "end_decoding_date", mode="before")
    @classmethod
    def _parse_dt(cls, v: Any) -> Any:
        if v is None or v == "":
            return None
        if isinstance(v, datetime):
            return v.replace(tzinfo=None) if v.tzinfo else v
        s = str(v).strip()
        if not s:
            return None
        # ISO 8601 with optional trailing Z
        if s.endswith("Z"):
            s = s[:-1]
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        # YYYYMMDDHHMMSS (Coriolis style)
        if len(s) == 14 and s.isdigit():
            return datetime.strptime(s, "%Y%m%d%H%M%S")
        raise ValueError(f"Unrecognised datetime: {v!r}")

    @field_validator("reference_day", mode="before")
    @classmethod
    def _parse_date(cls, v: Any) -> Any:
        if v is None or v == "":
            return None
        if isinstance(v, date) and not isinstance(v, datetime):
            return v
        s = str(v).strip()
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        raise ValueError(f"Unrecognised date: {v!r}")

    @field_validator("sensors", mode="before")
    @classmethod
    def _parse_sensors(cls, v: Any) -> Any:
        if isinstance(v, list):
            out: list[Any] = []
            for item in v:
                if isinstance(item, str):
                    out.append({"sensor": item})
                elif isinstance(item, dict):
                    out.append(item)
                else:
                    out.append(item)
            return out
        if isinstance(v, str):
            if not v.strip():
                return []
            data = json.loads(v)
            if not isinstance(data, list):
                raise ValueError("sensors must be a JSON list")
            return [{"sensor": s} if isinstance(s, str) else s for s in data]
        return v

    @field_validator("transmission_system", "positioning_system", mode="before")
    @classmethod
    def _parse_strlist(cls, v: Any) -> Any:
        if isinstance(v, list):
            return [str(x) for x in v]
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return []
            data = json.loads(s)
            if not isinstance(data, list):
                raise ValueError("expected JSON list")
            return [str(x) for x in data]
        return v

    @field_validator(
        "launch_lon",
        "launch_lat",
        "drift_sampling_period_hours",
        mode="before",
    )
    @classmethod
    def _parse_float(cls, v: Any) -> Any:
        if v is None or v == "":
            return 0.0
        return float(v)

    @field_validator(
        "wmo",
        "transmission_type",
        "decoder_id",
        "frame_length",
        "cycle_length_hours",
        "delay_before_mission_minutes",
        "launch_qc",
        mode="before",
    )
    @classmethod
    def _parse_int(cls, v: Any) -> Any:
        if v is None or v == "":
            return 0
        return int(float(str(v)))

    @field_validator("dm_flag", mode="before")
    @classmethod
    def _parse_bool(cls, v: Any) -> Any:
        if isinstance(v, bool):
            return v
        s = str(v).strip().lower()
        return s in {"1", "true", "yes", "y"}

    @model_validator(mode="after")
    def _fill_defaults(self) -> FloatRegistryRow:
        if not self.imei and self.ptt:
            self.imei = self.ptt
        # transmission_type defaults by platform family (best-effort)
        if not self.transmission_system:
            self.transmission_system = (
                ["IRIDIUM"] if self.transmission_type in {2, 3, 4} else ["ARGOS"]
            )
        if not self.positioning_system:
            self.positioning_system = (
                ["GPS", "IRIDIUM"] if self.transmission_type in {2, 3, 4} else ["ARGOS"]
            )
        return self
