"""APEX APF11 Iridium (Bio) raw-telemetry decoding.

This package turns the Teledyne Webb ``APF-11`` raw file families into typed
per-record tables. It deliberately stops short of NetCDF production: no R/BR,
meta, tech or Rtraj writer lives here.

Family facts established from the raw files themselves, not assumed:

* ``science_log.bin`` and ``vitals_log.bin`` are binary, framed as
  ``[1-byte length][payload]`` with the record id in ``payload[0]`` and a
  4-byte little-endian Unix timestamp in ``payload[1..5]`` for most records.
* ``system_log.txt``, ``production_log.txt`` and ``suna_log.txt`` are plain
  text inside gzip. Coriolis routes every ``*.txt`` through one text
  converter, which is what this package mirrors.

Dispatch is by **record type** and **cycle**, never by WMO or float name. No
float identifier appears anywhere in this package.

Record tables are taken verbatim from the vendor ``apf11dec.py`` v2.12.2.1
(Teledyne Webb Research); see :mod:`argo_decoder.platforms.apex_apf11_ir.records`.
"""

from argo_decoder.platforms.apex_apf11_ir.association import (
    DEFAULT_TOLERANCE_S,
    O2Association,
    associate_o2_with_ctd,
)
from argo_decoder.platforms.apex_apf11_ir.attribution import (
    CycleProfile,
    FileAttribution,
    attribute_cycles,
    parse_filename,
)
from argo_decoder.platforms.apex_apf11_ir.calibration import (
    BgcCalibration,
    OptodeCalibration,
    OptodeCalibrationSource,
    load_bgc_calibration,
    load_optode_calibration_by_serial,
    optode_from_gdac_string,
    resolve_optode,
)
from argo_decoder.platforms.apex_apf11_ir.records import (
    APF11_FAMILY,
    APF11_SUBTYPE,
    CORIOLIS_DECODER_ID_RANGE,
    CORIOLIS_DECODER_ID_WITH_CONFIG,
    DECODER_ID,
    FLOAT_INFO_DECODER_ID_COLUMN,
    SCIENCE_RECORDS,
    VITALS_RECORDS,
    RecordSpec,
)
from argo_decoder.platforms.apex_apf11_ir.equations import (
    ARGO_FILL,
    DELTA_DEFAULT,
    Bbp700Result,
    DoxyResult,
    NitrateResult,
    bbp700_m1,
    betasw,
    doxy_from_phase,
    doxy_from_telemetry_o2,
    nitrate_from_suna,
    optode_air_saturation,
    optode_concentration,
    oxygen_solubility_ml_per_l,
)
from argo_decoder.platforms.apex_apf11_ir.missions import (
    IGNORED_CONFIG_NAMES,
    MissionTracker,
    config_version_missions,
    map_mission_cfg,
    map_sample_cfg,
    parse_system_log_config,
)
from argo_decoder.platforms.apex_apf11_ir.phases import (
    CyclePhases,
    juld_to_timestamp,
    parse_cycle_phases,
    timestamp_to_juld,
)
from argo_decoder.platforms.apex_apf11_ir.products import (
    BgcLevel,
    CtdLevel,
    CycleProfiles,
    build_cycle_profiles,
)
from argo_decoder.platforms.apex_apf11_ir.publish import (
    CyclePosition,
    GpsFix,
    build_bgc_product,
    build_core_product,
    resolve_cycle_position,
)
from argo_decoder.platforms.apex_apf11_ir.rtqc import (
    ProfileRtqc,
    profile_quality_letter,
    run_core_rtqc,
)
from argo_decoder.platforms.apex_apf11_ir.runner import (
    cycle_of_science_csv,
    cycle_of_system_log,
    float_science_rows,
    float_system_logs,
    read_science_csv,
)

from argo_decoder.platforms.apex_apf11_ir.science import (
    CTD_NAMES,
    FLBB_NAMES,
    CtdSample,
    FlbbSample,
    No3Sample,
    O2Sample,
    ScienceDecoded,
    decode_ctd,
    decode_ctd_bins,
    decode_flbb,
    decode_no3,
    decode_o2,
    decode_science_records,
    deduplicate_samples,
    select_ctd,
)

__all__ = [
    "APF11_FAMILY",
    "APF11_SUBTYPE",
    "CORIOLIS_DECODER_ID_RANGE",
    "CORIOLIS_DECODER_ID_WITH_CONFIG",
    "DECODER_ID",
    "FLOAT_INFO_DECODER_ID_COLUMN",
    "SCIENCE_RECORDS",
    "VITALS_RECORDS",
    "RecordSpec",
    "CtdSample",
    "FlbbSample",
    "No3Sample",
    "O2Sample",
    "decode_science_records",
    "deduplicate_samples",
    "select_ctd",
    "CyclePhases",
    "parse_cycle_phases",
    "timestamp_to_juld",
    "juld_to_timestamp",
    "IGNORED_CONFIG_NAMES",
    "MissionTracker",
    "config_version_missions",
    "map_mission_cfg",
    "map_sample_cfg",
    "parse_system_log_config",
    "BgcLevel",
    "CtdLevel",
    "CycleProfiles",
    "build_cycle_profiles",
    "CyclePosition",
    "GpsFix",
    "build_bgc_product",
    "build_core_product",
    "resolve_cycle_position",
    "ProfileRtqc",
    "profile_quality_letter",
    "run_core_rtqc",
    "cycle_of_science_csv",
    "cycle_of_system_log",
    "float_science_rows",
    "float_system_logs",
    "read_science_csv",
    "BgcCalibration",
    "OptodeCalibration",
    "OptodeCalibrationSource",
    "load_bgc_calibration",
    "load_optode_calibration_by_serial",
    "optode_from_gdac_string",
    "resolve_optode",
    "ScienceDecoded",
    "ARGO_FILL",
    "DELTA_DEFAULT",
    "Bbp700Result",
    "DoxyResult",
    "NitrateResult",
    "bbp700_m1",
    "betasw",
    "doxy_from_phase",
    "doxy_from_telemetry_o2",
    "nitrate_from_suna",
    "optode_air_saturation",
    "optode_concentration",
    "oxygen_solubility_ml_per_l",
    "DEFAULT_TOLERANCE_S",
    "O2Association",
    "associate_o2_with_ctd",
    "CycleProfile",
    "FileAttribution",
    "attribute_cycles",
    "parse_filename",
    "decode_ctd",
    "decode_ctd_bins",
    "decode_flbb",
    "decode_o2",
    "decode_no3",
    "CTD_NAMES",
    "FLBB_NAMES",
]
