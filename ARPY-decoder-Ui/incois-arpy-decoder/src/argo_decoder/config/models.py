"""Configuration models (Pydantic v2).

Mirrors the JSON configuration consumed by the MATLAB decoder
(``decoder_conf.json``), but with proper types, defaults and validation. Paths
are kept as strings to stay byte-compatible with the MATLAB JSON contract.
"""

from __future__ import annotations

import os
import sys
from enum import IntEnum
from pathlib import Path
from tempfile import gettempdir
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


def _host_temp_dir() -> Path:
    """Return the OS-appropriate temporary directory.

    Uses :func:`tempfile.gettempdir` so that Linux returns ``/tmp`` and
    Windows returns ``%TEMP%`` (``C:\\Users\\<user>\\AppData\\Local\\Temp``)
    rather than a hard-coded POSIX path.
    """
    return Path(gettempdir())


def _default_paths_host() -> dict[str, Path]:
    """Return sane host-local defaults when running outside the Docker container.

    When running on a developer laptop (Linux or Windows) there is no
    ``/mnt/data`` or ``/app`` tree; we place everything under a working
    directory tree rooted in the system temp directory. These defaults are
    always overridden in practice by either an explicit config file or CLI
    flags; they exist only so ``DecoderConfig()`` is usable on any OS.
    """
    tmp = _host_temp_dir() / "argo_decoder"
    return {
        "rsync_data_dir": tmp / "rsync" / "archive" / "cycle",
        "rsync_log_dir": tmp / "rsync" / "rsync_list",
        "config_dir": tmp / "config",
        "float_info_dir": tmp / "config" / "json_float_info",
        "float_meta_dir": tmp / "config" / "json_float_meta_ir_sbd",
        "dm_buffer_list_dir": tmp / "config" / "float_dm_buffer_lists",
        "tech_label_dir": tmp / "config" / "_techParamNames",
        "config_label_dir": tmp / "config" / "_configParamNames",
        "iridium_decoded_dir": tmp / "output" / "iridium",
        "log_dir": tmp / "output" / "log",
        "csv_dir": tmp / "output" / "csv",
        "xml_dir": tmp / "output" / "xml",
        "nc_dir": tmp / "output" / "nc",
        "nc_traj_3_1_dir": tmp / "output" / "nc",
        "nc_traj_3_2_dir": tmp / "output" / "nc",
        "temporary_dir": tmp / "tmp",
    }


def _container_default_paths() -> dict[str, Path]:
    """Paths used inside the official Docker container (POSIX)."""
    return {
        "rsync_data_dir": Path("/mnt/data/rsync/archive/cycle/"),
        "rsync_log_dir": Path("/mnt/data/rsync/rsync_list/"),
        "config_dir": Path("/mnt/data/config/"),
        "float_info_dir": Path("/mnt/data/config/decArgo_config_floats/json_float_info/"),
        "float_meta_dir": Path("/mnt/data/config/decArgo_config_floats/json_float_meta_ir_sbd/"),
        "dm_buffer_list_dir": Path("/mnt/data/config/decArgo_config_floats/float_dm_buffer_lists"),
        "tech_label_dir": Path("/app/config/_techParamNames/"),
        "config_label_dir": Path("/app/config/_configParamNames/"),
        "iridium_decoded_dir": Path("/mnt/data/output/iridium/"),
        "log_dir": Path("/mnt/data/output/log/"),
        "csv_dir": Path("/mnt/data/output/csv/"),
        "xml_dir": Path("/mnt/data/output/xml/"),
        "nc_dir": Path("/mnt/data/output/nc/"),
        "nc_traj_3_1_dir": Path("/mnt/data/output/nc/"),
        "nc_traj_3_2_dir": Path("/mnt/data/output/nc/"),
        "temporary_dir": _host_temp_dir(),
    }


def _default_paths() -> dict[str, Path]:
    """Pick defaults based on whether we appear to be inside the container."""
    # ARGO_DECODER_CONTAINER=1 is set by the production Dockerfile (see
    # deploy/Dockerfile, Phase 1). When unset, detect by existence of the
    # container mount points.
    if os.environ.get("ARGO_DECODER_CONTAINER", "").lower() in {"1", "true", "yes"}:
        return _container_default_paths()
    if sys.platform != "win32" and Path("/mnt/data/config").exists():
        return _container_default_paths()
    return _default_paths_host()


class TransmissionType(IntEnum):
    """Argo float transmission family. Values match MATLAB constants."""

    ARGOS = 1
    IRIDIUM_RUDICS = 2
    IRIDIUM_SBD = 3
    IRIDIUM_SBD_REMOCEAN = 4


class NcGenerationFlags(BaseModel):
    """Flags controlling which NetCDF products are generated.

    The MATLAB config uses string integers ``"0"``/``"2"`` where ``"2"`` means
    "generate" and ``"0"`` means "skip". In Python we use booleans; the loader
    translates the stringly-typed JSON.
    """

    multi_prof: bool = False
    mono_prof: bool = True
    tech: bool = True
    meta: bool = True
    traj_3_1: bool = False
    traj_3_2: bool = True


class RtqcTestFlags(BaseModel):
    """Per-RTQC-test enable flags. Defaults follow the docker sample config."""

    platform_identification: bool = True
    impossible_date: bool = True
    impossible_location: bool = True
    position_on_land: bool = True
    impossible_speed: bool = True
    global_range: bool = True
    regional_range: bool = True
    pressure_increasing: bool = True
    spike: bool = True
    gradient: bool = True
    digit_rollover: bool = True
    stuck_value: bool = True
    density_inversion: bool = True
    exclusion_list: bool = True
    gross_salinity_or_temp_sensor_drift: bool = False
    frozen_pressure: bool = False
    deepest_pressure: bool = True
    questionable_argos_position: bool = True
    ns_unpumped_salinity: bool = True
    ns_mixed_air_water: bool = True
    deep_float: bool = True
    rbr_float: bool = True
    medd: bool = True
    temp_cndc: bool = True
    ph: bool = True
    doxy: bool = True
    nitrate: bool = True
    par: bool = False
    irradiance: bool = False
    bbp: bool = True
    chla: bool = True


class RtqcReferenceFiles(BaseModel):
    """Paths of reference datasets used by RTQC.

    Defaults are computed lazily so that non-container environments (Linux
    dev boxes, Windows) get a writable temp path for the exclusion list
    rather than a hard-coded ``/tmp``.
    """

    gebco_file: Path = Path("/mnt/ref/gebco.nc")
    exclusion_list_file: Path = Field(
        default_factory=lambda: _host_temp_dir() / "ar_exclusionlist.txt"
    )
    woa_file: Path = Path("/mnt/ref/woa13_all_n00_01.nc")
    chla_correction_file: Path = Path("/mnt/ref/SLOPE_RT_2024.txt")


class RtqcConfig(BaseModel):
    """Top-level RTQC configuration."""

    apply_rtqc: bool = False
    tests: RtqcTestFlags = Field(default_factory=RtqcTestFlags)
    reference_files: RtqcReferenceFiles = Field(default_factory=RtqcReferenceFiles)


class MetadataBackend(str):
    CSV = "csv"
    #: Four-CSV operational metadata (meta / sensor-info / calib /
    #: config_params), joined on WMO. ``registry_path`` points at the
    #: directory holding them.
    CSV4 = "csv4"
    SQLITE = "sqlite"
    POSTGRES = "postgres"
    JSON = "json"  # legacy; read existing meta/info JSON files directly


class MetadataConfig(BaseModel):
    """Metadata-registry configuration (Phase 1 feature - partial in Phase 0)."""

    backend: Literal["csv", "csv4", "sqlite", "postgres", "json"] = "json"
    registry_path: Path | None = None  # CSV / SQLite file, or csv4 directory
    materialized_dir: Path | None = None  # generated JSON cache (written each run)
    schema_version: str = "1.0.0"


class PathSet(BaseModel):
    """Container-relevant paths (all absolute). Mirrors the MATLAB JSON paths.

    Defaults are OS-aware: inside the Docker container they resolve to the
    POSIX ``/mnt/...`` tree; on a developer machine (Linux or Windows) they
    resolve under the system temporary directory so ``DecoderConfig()``
    works without any additional setup.
    """

    rsync_data_dir: Path = Field(default_factory=lambda: _default_paths()["rsync_data_dir"])
    rsync_log_dir: Path = Field(default_factory=lambda: _default_paths()["rsync_log_dir"])
    config_dir: Path = Field(default_factory=lambda: _default_paths()["config_dir"])
    float_info_dir: Path = Field(default_factory=lambda: _default_paths()["float_info_dir"])
    # Note: meta dir changes with transmission type; default matches Iridium SBD.
    float_meta_dir: Path = Field(default_factory=lambda: _default_paths()["float_meta_dir"])
    dm_buffer_list_dir: Path = Field(default_factory=lambda: _default_paths()["dm_buffer_list_dir"])
    tech_label_dir: Path = Field(default_factory=lambda: _default_paths()["tech_label_dir"])
    config_label_dir: Path = Field(default_factory=lambda: _default_paths()["config_label_dir"])
    iridium_decoded_dir: Path = Field(
        default_factory=lambda: _default_paths()["iridium_decoded_dir"]
    )
    log_dir: Path = Field(default_factory=lambda: _default_paths()["log_dir"])
    csv_dir: Path = Field(default_factory=lambda: _default_paths()["csv_dir"])
    xml_dir: Path = Field(default_factory=lambda: _default_paths()["xml_dir"])
    nc_dir: Path = Field(default_factory=lambda: _default_paths()["nc_dir"])
    nc_traj_3_1_dir: Path = Field(default_factory=lambda: _default_paths()["nc_traj_3_1_dir"])
    nc_traj_3_2_dir: Path = Field(default_factory=lambda: _default_paths()["nc_traj_3_2_dir"])
    temporary_dir: Path = Field(default_factory=lambda: _default_paths()["temporary_dir"])


class OutputFlags(NcGenerationFlags):
    """Alias for backwards-compatible naming with an added ``process_remaining_buffers``."""

    process_remaining_buffers: bool = False
    add_argos_error_ellipses: bool = False
    add_three_minutes: bool = False
    expected_cycle_list: str = "99999"
    float_list_file: str = ""


class _BaseModelCompat(BaseModel):
    """Helper that translates the MATLAB string-integer booleans and ignores
    unknown JSON keys present in existing config files.
    """

    model_config = {
        "populate_by_name": True,
        "extra": "ignore",
        "use_enum_values": False,
    }


class DecoderConfig(_BaseModelCompat):
    """Top-level decoder configuration."""

    transmission_type: TransmissionType = TransmissionType.IRIDIUM_SBD
    paths: PathSet = Field(default_factory=PathSet)
    outputs: OutputFlags = Field(default_factory=OutputFlags)
    rtqc: RtqcConfig = Field(default_factory=RtqcConfig)
    metadata: MetadataConfig = Field(default_factory=MetadataConfig)

    # Runtime-only parameters (populated from CLI, not JSON):
    xml_report_filename: str | None = None
    float_wmo: int | None = None
    rsynclog: str = "all"

    @field_validator("transmission_type", mode="before")
    @classmethod
    def _coerce_transmission(cls, v: object) -> object:
        if isinstance(v, str):
            return int(v)
        return v

    @model_validator(mode="before")
    @classmethod
    def _flatten_matlab_keys(cls, data: object) -> object:
        """Translate the flat MATLAB JSON (all caps snake_case keys) into our nested model."""
        if not isinstance(data, dict):
            return data

        def _bool(key: str, default: bool = False) -> bool:
            val = data.pop(key, None)
            if val is None:
                return default
            if isinstance(val, bool):
                return val
            return str(val) == "2" or str(val) == "1"

        def _str(key: str, default: str = "") -> str:
            val = data.pop(key, None)
            return str(val) if val is not None else default

        def _path(key: str, default: Path) -> Path:
            val = data.pop(key, None)
            return Path(str(val)) if val else default

        defaults = _default_paths()
        paths = {
            "rsync_data_dir": _path("DIR_INPUT_RSYNC_DATA", defaults["rsync_data_dir"]),
            "rsync_log_dir": _path("DIR_INPUT_RSYNC_LOG", defaults["rsync_log_dir"]),
            "float_info_dir": _path(
                "DIR_INPUT_JSON_FLOAT_DECODING_PARAMETERS_FILE",
                defaults["float_info_dir"],
            ),
            "float_meta_dir": _path(
                "DIR_INPUT_JSON_FLOAT_META_DATA_FILE",
                defaults["float_meta_dir"],
            ),
            "dm_buffer_list_dir": _path(
                "DIR_INPUT_DM_BUFFER_LIST",
                defaults["dm_buffer_list_dir"],
            ),
            "tech_label_dir": _path("DIR_INPUT_JSON_TECH_LABEL_FILE", defaults["tech_label_dir"]),
            "config_label_dir": _path(
                "DIR_INPUT_JSON_CONF_LABEL_FILE", defaults["config_label_dir"]
            ),
            "iridium_decoded_dir": _path("IRIDIUM_DATA_DIRECTORY", defaults["iridium_decoded_dir"]),
            "log_dir": _path("DIR_OUTPUT_LOG_FILE", defaults["log_dir"]),
            "csv_dir": _path("DIR_OUTPUT_CSV_FILE", defaults["csv_dir"]),
            "xml_dir": _path("DIR_OUTPUT_XML_FILE", defaults["xml_dir"]),
            "nc_dir": _path("DIR_OUTPUT_NETCDF_FILE", defaults["nc_dir"]),
            "nc_traj_3_1_dir": _path(
                "DIR_OUTPUT_NETCDF_TRAJ_3_1_FILE", defaults["nc_traj_3_1_dir"]
            ),
            "nc_traj_3_2_dir": _path(
                "DIR_OUTPUT_NETCDF_TRAJ_3_2_FILE", defaults["nc_traj_3_2_dir"]
            ),
            "temporary_dir": _path("DIR_OUTPUT_TEMPORARY", defaults["temporary_dir"]),
        }

        outputs = {
            "multi_prof": _bool("GENERATE_NC_MULTI_PROF"),
            "mono_prof": _bool("GENERATE_NC_MONO_PROF", True),
            "tech": _bool("GENERATE_NC_TECH", True),
            "meta": _bool("GENERATE_NC_META", True),
            "traj_3_1": _bool("GENERATE_NC_TRAJ_3_1"),
            "traj_3_2": _bool("GENERATE_NC_TRAJ_3_2", True),
            "process_remaining_buffers": _bool("PROCESS_REMAINING_BUFFERS"),
            "add_argos_error_ellipses": _bool("ADD_ARGOS_ERROR_ELLIPSES"),
            "add_three_minutes": _bool("ADD_THREE_MINUTES"),
            "expected_cycle_list": _str("EXPECTED_CYCLE_LIST", "99999"),
            "float_list_file": _str("FLOAT_LIST_FILE_NAME", ""),
        }

        rtqc_tests = {
            "platform_identification": _bool("TEST001_PLATFORM_IDENTIFICATION", True),
            "impossible_date": _bool("TEST002_IMPOSSIBLE_DATE", True),
            "impossible_location": _bool("TEST003_IMPOSSIBLE_LOCATION", True),
            "position_on_land": _bool("TEST004_POSITION_ON_LAND", True),
            "impossible_speed": _bool("TEST005_IMPOSSIBLE_SPEED", True),
            "global_range": _bool("TEST006_GLOBAL_RANGE", True),
            "regional_range": _bool("TEST007_REGIONAL_RANGE", True),
            "pressure_increasing": _bool("TEST008_PRESSURE_INCREASING", True),
            "spike": _bool("TEST009_SPIKE", True),
            "gradient": _bool("TEST011_GRADIENT", True),
            "digit_rollover": _bool("TEST012_DIGIT_ROLLOVER", True),
            "stuck_value": _bool("TEST013_STUCK_VALUE", True),
            "density_inversion": _bool("TEST014_DENSITY_INVERSION", True),
            "exclusion_list": _bool("TEST015_EXCLUSION_LIST", True),
            "gross_salinity_or_temp_sensor_drift": _bool(
                "TEST016_GROSS_SALINITY_OR_TEMPERATURE_SENSOR_DRIFT"
            ),
            "frozen_pressure": _bool("TEST018_FROZEN_PRESSURE"),
            "deepest_pressure": _bool("TEST019_DEEPEST_PRESSURE", True),
            "questionable_argos_position": _bool("TEST020_QUESTIONABLE_ARGOS_POSITION", True),
            "ns_unpumped_salinity": _bool("TEST021_NS_UNPUMPED_SALINITY", True),
            "ns_mixed_air_water": _bool("TEST022_NS_MIXED_AIR_WATER", True),
            "deep_float": _bool("TEST023_DEEP_FLOAT", True),
            "rbr_float": _bool("TEST024_RBR_FLOAT", True),
            "medd": _bool("TEST025_MEDD", True),
            "temp_cndc": _bool("TEST026_TEMP_CNDC", True),
            "ph": _bool("TEST056_PH", True),
            "doxy": _bool("TEST057_DOXY", True),
            "nitrate": _bool("TEST059_NITRATE", True),
            "par": _bool("TEST060_PAR"),
            "irradiance": _bool("TEST061_IRRADIANCE"),
            "bbp": _bool("TEST062_BBP", True),
            "chla": _bool("TEST063_CHLA", True),
        }
        rtqc_refs = {
            "gebco_file": _path("TEST004_GEBCO_FILE", Path("/mnt/ref/gebco.nc")),
            "exclusion_list_file": _path(
                "TEST015_EXCLUSION_LIST_FILE",
                _host_temp_dir() / "ar_exclusionlist.txt",
            ),
            "woa_file": _path("WOA_FILE", Path("/mnt/ref/woa13_all_n00_01.nc")),
            "chla_correction_file": _path("CHLA_COR_FACT_FILE", Path("/mnt/ref/SLOPE_RT_2024.txt")),
        }
        rtqc = {
            "apply_rtqc": _bool("APPLY_RTQC"),
            "tests": rtqc_tests,
            "reference_files": rtqc_refs,
        }

        trans = data.pop("FLOAT_TRANSMISSION_TYPE", None)
        if trans is not None:
            trans = int(trans) if str(trans).isdigit() else trans

        out: dict[str, object] = {
            "paths": paths,
            "outputs": outputs,
            "rtqc": rtqc,
        }
        if trans is not None:
            out["transmission_type"] = trans
        # Remaining keys in `data` are ignored (`extra = "ignore"`) so future/unknown
        # MATLAB keys do not crash loading.
        return out
