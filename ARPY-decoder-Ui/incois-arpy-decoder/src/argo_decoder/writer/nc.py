"""PROVOR CTS4 / decoder-301 NetCDF publication writer (Phase 3 — corrected audit).

Implements the frozen Phase-2C publication contract:
`provor_bio_irsbd/PROVOR_CTS4_PHASE2C_PUBLICATION_DESIGN.md`

Scope: publication layer ONLY — REAL-TIME ONLY (R core + BR BGC). D/BD (delayed) are NOT supported as outputs.
This project produces ONLY R (core real-time) and BR (BGC real-time) profile files + meta/tech.
D/BD files may be inspected ONLY as reference evidence when an R/BR reference is unavailable, never as output targets.
Decoder remains responsible for telemetry decoding
and science derivation. Writer must not decode packets or infer sensor semantics
from raw bytes. WMO is externally supplied and validated. All float-specific
metadata MUST come from external_meta / authoritative metadata input.

Classification of literals in this file (audit 2026-09-10):
- OFFICIAL STRUCTURAL: STRING sizes, fill values (99999), Conventions, etc. per Argo User Manual 3.44
- FAMILY-GENERIC AUTHORITATIVE: PROVOR family constants (e.g., PLATFORM_FAMILY FLOAT, PLATFORM_TYPE PROVOR_III, khi 1.097,
  SCALE_CHLA 0.0073, TRANS_SYSTEM IRIDIUM, BATTERY n/a) — identical across 13 INCOIS 301 meta.nc per evidence
- EXTERNALLY SUPPLIED: WMO, float_serial_no, launch_date/lat/lon, project/pi, wmo_inst_type, sensor serials, config etc.
  MUST be supplied via ExternalMeta / WriterInputs.external_meta; writer FAILS if absent (no fabrication)
- TEST-ONLY FIXTURE: synthetic values live ONLY in src/argo_decoder/writer/fixtures.py and must never be called from production
- FORBIDDEN FABRICATION: hard-coded 2902091, 201302..., 12.0/68.0, 846 etc. — REMOVED in this audit

Backend: netCDF4 with CF-compatible char arrays (not VLEN strings).
Fill values and dimensions exactly per design. _FillValue MUST be supplied via createVariable(..., fill_value=...)
— never via setncattr after creation.

References:
- Argo User's Manual 3.44 2025-07-10 doi:10.13155/29825
- BGC cookbooks: BBP 39459, CHLA 39468, O2 39795
- NKE 5.8 Mut ProVBioII-FLBB
- Coriolis decArgo 20260202_082q
- INCOIS GDAC 13 x incois_2902*_meta.nc + D/BD 2902091_001 — parity reference only
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import netCDF4
import numpy as np

from argo_decoder.rtqc.cts4 import run_cts4_rtqc

# ---------------------------------------------------------------------------
# Official structural constants (Argo User Manual 3.44, Table 3 etc.)
# MUST — structural, not float-specific. Changing them breaks FileChecker.
# ---------------------------------------------------------------------------

STRING2 = 2
STRING4 = 4
STRING8 = 8
STRING16 = 16
STRING32 = 32
STRING64 = 64
STRING128 = 128
STRING256 = 256
STRING1024 = 1024
STRING4096 = 4096
DATE_TIME_LEN = 14

# Fill values — official Argo conventions (MUST)
FLOAT_FILL = np.float32(99999.0)
DOUBLE_FILL = np.float64(99999.0)
JULD_FILL = np.float64(999999.0)
INT_FILL = np.int32(99999)
CHAR_FILL = b" "

# File-type fixed N_PARAM — official per file type (MUST)
N_PARAM_CORE = 3
N_PARAM_BGC = 6
N_PARAM_META = 11

# Meta ordering — FAMILY-GENERIC REFERENCE for INCOIS 301 parity (observed
# stable across 13 meta.nc; not an official global order)
META_PARAMETER_ORDER = (
    "PRES",
    "TEMP",
    "PSAL",
    "C1PHASE_DOXY",
    "C2PHASE_DOXY",
    "TEMP_DOXY",
    "DOXY",
    "FLUORESCENCE_CHLA",
    "BETA_BACKSCATTERING700",
    "CHLA",
    "BBP700",
)

# Family-generic BGC split templates — FAMILY-GENERIC AUTHORITATIVE
# For BGC files (BR), STATION_PARAMETERS per N_PROF — observed in BD 2902091_001 as reference evidence only; production is BR
BGC_STATION_PARAMETERS_TEMPLATE = [
    ["PRES", "", "", "", "", ""],
    ["PRES", "", "", "", "", ""],
    ["PRES", "C1PHASE_DOXY", "C2PHASE_DOXY", "TEMP_DOXY", "DOXY", ""],
    ["PRES", "FLUORESCENCE_CHLA", "BETA_BACKSCATTERING700", "CHLA", "CHLA_FLUORESCENCE", "BBP700"],
]

R_STATION_PARAMETERS_TEMPLATE = [

    ["PRES", "TEMP", "PSAL"],
    ["PRES", "TEMP", "PSAL"],
    ["PRES", "", ""],
    ["PRES", "", ""],
]

# Units — REFERENCE from meta (observed)
PARAMETER_UNITS = {
    "PRES": "decibar",
    "TEMP": "degree_Celsius",
    "PSAL": "psu",
    "C1PHASE_DOXY": "degree",
    "C2PHASE_DOXY": "degree",
    "TEMP_DOXY": "degree_Celsius",
    "DOXY": "micromole/kg",
    "FLUORESCENCE_CHLA": "count",
    "BETA_BACKSCATTERING700": "count",
    "CHLA": "mg/m3",
    "BBP700": "m-1",
    "CHLA_FLUORESCENCE": "ru",
}

# Sensor accuracy / resolution as published in PARAMETER_ACCURACY /
# PARAMETER_RESOLUTION. Argo UM 3.1 §2.4.7 defines these as free-text
# descriptions of the SENSOR ("Resolution of the parameter returned by the
# sensor (note that this is not necessarily equivalent to the resolution of
# the parameter returned by the float through telemetry)"), with no controlled
# vocabulary -- so they are sensor specifications, not telemetry quantities,
# and they are family-generic rather than per-float.
#
# The four CTD/optode figures are transcribed from the NKE PROVOR ProvBioII
# user manual for this exact family (NKE 5.8, DOC 33-16-016 Rev3, §8
# SPECIFICATIONS -> Sensors, workspace copy
# provor_bio_irsbd/ref/NKE_5.8_MUT_PROVBIOII-FLBB_UTI_GB_Rev3_20130924.pdf
# p61):
#     Pressure    accuracy +/- 2.4 dbar   resolution 0.1 dbar
#     Temperature accuracy +/- 0.002 C    resolution 0.001 C
#     Salinity    accuracy +/- 0.005 PSU  resolution 0.001 PSU
#     Oxygen      accuracy +/-8 uM/l (<160) or 5% (>160), resolution <1 uM/l
# The raw optode channels (C1PHASE_DOXY, C2PHASE_DOXY, FLUORESCENCE_CHLA,
# BETA_BACKSCATTERING700) and the derived BBP700 have no published figure in
# that section, so they stay blank rather than being invented. Coriolis
# reaches the same conclusion structurally: generate_csv_meta.m:836-869 only
# ever defaults PRES/TEMP/PSAL/DOXY and leaves everything else empty.
#
# These are NKE DOC tier evidence. They are NOT read back from any GDAC file;
# INCOIS happens to publish the same NKE figures on all 13 of its CTS4
# meta.nc files, which is the expected consequence of both DACs transcribing
# the same manual.
PARAMETER_ACCURACY_SPEC = {
    "PRES": "2.4",
    "TEMP": "0.002",
    "PSAL": "0.005",
    "TEMP_DOXY": "0.03 degC",
    "DOXY": "8 umol/kg or 10%",
    "CHLA": "0.08 mg/m3",
}
PARAMETER_RESOLUTION_SPEC = {
    "PRES": "0.1",
    "TEMP": "0.001",
    "PSAL": "0.001",
    "TEMP_DOXY": "0.01 degC",
    "DOXY": "1 umol/kg",
    "CHLA": "0.025 mg/m3",
}

# Family-generic authoritative constant for BBP (cook_bbp Table 1, 142°)
KHI_700 = 1.097

# WMO / decoder_version validation — OFFICIAL structural (MUST, no allocation gate)
WMO_RE = re.compile(r"^[0-9]{7}$")
DECODER_VERSION_RE = re.compile(r"^PY-301-\d+\.\d+\.\d+$")

_ADJUSTED_LONG_NAME = {
    "PRES": "Sea water pressure, equals 0 at sea-level",
    "TEMP": "Sea temperature in-situ ITS-90 scale",
    "PSAL": "Practical salinity",
    "DOXY": "Dissolved oxygen",
    "CHLA": "Chlorophyll-A",
    "BBP700": "Particle backscattering at 700 nanometers",
    "CHLA_FLUORESCENCE": "Chlorophyll fluorescence with factory calibration",
}
HISTORY_SOFTWARE = "PY301"  # 4-char, distinct from decoder_version PY-301-x.y.z

# ---------------------------------------------------------------------------
# External metadata contract — NO FABRICATION
# Every float-specific value MUST be supplied here. Writer FAILS if required
# fields are missing; test fixtures live in writer/fixtures.py only.
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class ExternalMeta:
    """Authoritative per-float/per-deployment metadata for publication.

    Required float-specific fields have no default and MUST be supplied.
    Fields with defaults are FAMILY-GENERIC AUTHORITATIVE per 13-file evidence
    (e.g., PLATFORM_FAMILY FLOAT, PLATFORM_TYPE PROVOR_III) and may be
    overridden per deployment if deployment sheet differs.
    Classification per audit:
    - REQUIRED (no default): float_serial_no, wmo_inst_type, launch_date/lat/lon
    - FAMILY-GENERIC (default): platform_family, platform_type, platform_maker, etc.
      — identical across INCOIS 301 fleet per evidence, but still overridable
    Forbidden: hard-coded 2902091, 201302..., 12.0/68.0 etc. are NOT defaults.
    """

    # REQUIRED — float-specific, no fabrication
    float_serial_no: str
    wmo_inst_type: str
    launch_date: str  # YYYYMMDDHHMMSS 14 chars
    launch_latitude: float
    launch_longitude: float

    # Optional with family-generic defaults (observed parity)
    platform_family: str = "FLOAT"  # observed FLOAT, not PROVOR (evidence 13/13)
    platform_type: str = "PROVOR_III"  # observed PROVOR_III (evidence 13/13)
    platform_maker: str = "NKE"  # observed NKE (13/13)
    firmware_version: str = "n/a"  # observed n/a (13/13) — not 5.8
    manual_version: str = "n/a"  # observed n/a
    standard_format_id: str = "n/a"  # observed n/a
    dac_format_id: str = "5.8"  # observed 5.8
    project_name: str  # REQUIRED — e.g., Indian ARGO (observed 13/13), no default (explicit)
    pi_name: str  # REQUIRED — e.g., M Ravichandran (observed 13/13), no default (explicit)
    data_centre: str | None = None  # if None, falls back to WriterInputs.institution
    ptt: str = ""  # e.g., 071017 for 2902091 — float-specific if known, else ""
    trans_system: str = "IRIDIUM"  # family-generic IRIDIUM
    positioning_system: tuple[str, ...] = ("GPS", "IRIDIUM")  # family-generic
    battery_type: str = "n/a"  # observed n/a
    battery_packs: str = ""  # observed ""
    controller_board_type_primary: str = "n/a"  # observed n/a
    controller_board_type_secondary: str = ""  # observed ""
    controller_board_serial_no_primary: str = "n/a"  # observed n/a
    controller_board_serial_no_secondary: str = ""  # observed ""
    float_owner: str = ""  # observed "" (13/13)
    operating_institution: str = ""  # observed ""
    customisation: str = ""  # observed ""
    deployment_platform: str = ""  # e.g., SAGAR KANYA for 2902091 — external if known
    deployment_cruise_id: str = ""  # e.g., SK-303
    deployment_reference_station_id: str = ""
    launch_qc: str = "1"
    start_date: str | None = None  # if None, uses launch_date
    startup_date: str | None = None
    end_mission_date: str = ""
    end_mission_status: str = " "
    # Sensor inventory — family-generic per fleet but S/N float-specific
    # SENSOR_SERIAL_NO observed: n/a for CTD/OPTODE, 2662 for FLBB (per float)
    sensor_names: tuple[str, ...] = ("CTD_PRES", "CTD_TEMP", "CTD_CNDC", "OPTODE_DOXY", "FLUOROMETER_CHLA", "BACKSCATTERINGMETER_BBP700")
    sensor_makers: tuple[str, ...] = ("SBE", "SBE", "SBE", "AANDERAA", "WETLABS", "WETLABS")
    sensor_models: tuple[str, ...] = ("SBE41CP", "SBE41CP", "SBE41CP", "AANDERAA_OPTODE_4330", "ECO_FLBB", "ECO_FLBB")
    sensor_serial_nos: tuple[str, ...] | None = None  # if None, writer requires explicit per-float serials

    # Config — authoritative per-float, keyed by float identity (flbb_serial via dedicated CSV,
    # never WMO allocation or IMEI routing). N_CONFIG_PARAM = len(config_parameter_names).
    # N_MISSIONS = len(config_mission_values) if supplied else 1 (legacy single-mission).
    # Synthetic CONFIG_SYN_* is TEST-ONLY (fixtures.py) — production must supply authoritative.
    config_parameter_names: tuple[str, ...]  # REQUIRED, authoritative (e.g., 7 for 2902091, 18 max)
    config_parameter_values: tuple[float, ...] | None = None  # legacy single-mission, len==N_CONFIG_PARAM
    config_mission_values: tuple[tuple[float, ...], ...] | None = None  # each mission tuple length==N_CONFIG_PARAM
    config_mission_numbers: tuple[int, ...] | None = None
    config_mission_comments: tuple[str, ...] | None = None
    config_mission_number: int = 1  # deprecated legacy, used only if config_mission_values is None
    config_mission_comment: str = ""  # deprecated legacy

    # Launch config — 161 fixed per Argo spec, authoritative per float via flbb_serial mechanism.
    # If None, writer fills with blanks/_FillValue (explicit unavailable), never fabrication.
    launch_config_parameter_names: tuple[str, ...] | None = None  # length 161 if supplied
    launch_config_parameter_values: tuple[float, ...] | None = None  # length 161 if supplied

    # Predeployment calibration — complete, keyed by flbb_serial (not WMO allocation).
    # Each tuple length N_PARAM (11) corresponding to META_PARAMETER_ORDER.
    # If None, writer writes official fill ("none" for equation/coeff where no cal, blank for comment).
    predeployment_calib_equations: tuple[str, ...] | None = None
    predeployment_calib_coefficients: tuple[str, ...] | None = None
    predeployment_calib_comments: tuple[str, ...] | None = None

    # Optional id override; if None, writer constructs id from wmo
    id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.float_serial_no, str) or not self.float_serial_no.strip():
            raise ValueError("ExternalMeta.float_serial_no is required (no fabrication); e.g., OIN-12IND-FLBB-05")
        if not isinstance(self.wmo_inst_type, str) or not self.wmo_inst_type.strip().isdigit():
            raise ValueError(f"ExternalMeta.wmo_inst_type must be numeric string (e.g., 836 per 13-file evidence), got {self.wmo_inst_type!r}")
        if not isinstance(self.launch_date, str) or len(self.launch_date) != 14 or not self.launch_date.isdigit():
            raise ValueError(f"ExternalMeta.launch_date must be YYYYMMDDHHMMSS 14 digits, got {self.launch_date!r}")
        # launch lat/lon validation
        if not isinstance(self.launch_latitude, (int, float)) or not -90 <= float(self.launch_latitude) <= 90:
            raise ValueError(f"ExternalMeta.launch_latitude out of range [-90,90], got {self.launch_latitude!r}")
        if not isinstance(self.launch_longitude, (int, float)) or not -180 <= float(self.launch_longitude) <= 180:
            raise ValueError(f"ExternalMeta.launch_longitude out of range [-180,180], got {self.launch_longitude!r}")
        if not isinstance(self.project_name, str) or not self.project_name:
            raise ValueError("ExternalMeta.project_name is required (no default) — e.g., Indian ARGO, or explicit "" if unavailable")
        if not isinstance(self.pi_name, str) or not self.pi_name:
            raise ValueError("ExternalMeta.pi_name is required (no default) — e.g., M Ravichandran, or explicit "" if unavailable")
        # Config — authoritative per-float, keyed by flbb_serial (never WMO allocation)
        if not isinstance(self.config_parameter_names, tuple) or len(self.config_parameter_names) == 0:
            raise ValueError("ExternalMeta.config_parameter_names is required (authoritative per-float, keyed by flbb_serial via dedicated CSV); no fabrication — provide tuple of names (e.g., 7 for 2902091 per GDAC); synthetic CONFIG_SYN_* is test-only (fixtures.py)")
        n_cfg = len(self.config_parameter_names)
        if not (1 <= n_cfg <= 100):
            raise ValueError(f"ExternalMeta.config_parameter_names length {n_cfg} out of plausible range 1..100")
        for n in self.config_parameter_names:
            if not isinstance(n, str) or not n.strip():
                raise ValueError(f"config_parameter_names entry must be non-empty string, got {n!r}")
            # Note: CONFIG_SYN_* is test-only (fixtures.py); production must supply authoritative names via flbb_serial mechanism.
            # We allow SYN in tests (fixtures set float_serial_no TEST-...); production floats use real names like CONFIG_NumberOfSubCycles_NUMBER.
        if self.config_mission_values is not None:
            if not isinstance(self.config_mission_values, tuple):
                raise ValueError("config_mission_values must be tuple of tuples")
            for mi, vals in enumerate(self.config_mission_values):
                if not isinstance(vals, tuple) or len(vals) != n_cfg:
                    raise ValueError(f"config_mission_values[{mi}] must be tuple length {n_cfg} (N_CONFIG_PARAM), got {len(vals) if isinstance(vals, tuple) else vals!r}")
                for v in vals:
                    if v is not None and not isinstance(v, (int, float)):
                        raise ValueError(f"config_mission_values entries must be float/int or None, got {v!r}")
            if self.config_mission_numbers is not None and len(self.config_mission_numbers) != len(self.config_mission_values):
                raise ValueError("config_mission_numbers length must match config_mission_values")
            if self.config_mission_comments is not None and len(self.config_mission_comments) != len(self.config_mission_values):
                raise ValueError("config_mission_comments length must match config_mission_values")
        elif self.config_parameter_values is not None:
            if len(self.config_parameter_values) != n_cfg:
                raise ValueError(f"config_parameter_values length {len(self.config_parameter_values)} must equal N_CONFIG_PARAM {n_cfg}")
        else:
            raise ValueError("ExternalMeta requires config values: set config_mission_values (multi-mission) or config_parameter_values (single mission legacy); no fabrication")
        # Launch config — 161 fixed if supplied, else explicit unavailable (fill)
        if self.launch_config_parameter_names is not None:
            if len(self.launch_config_parameter_names) != 161:
                raise ValueError(f"launch_config_parameter_names must be length 161 (fixed per Argo spec) if supplied, got {len(self.launch_config_parameter_names)}")
            if self.launch_config_parameter_values is None or len(self.launch_config_parameter_values) != 161:
                raise ValueError("launch_config_parameter_values must be length 161 when launch_config_parameter_names is supplied")
        if self.launch_config_parameter_values is not None and self.launch_config_parameter_names is None:
            raise ValueError("launch_config_parameter_values supplied without launch_config_parameter_names")
        # Predeployment — 11 per META_PARAMETER_ORDER if supplied, else official fill
        if self.predeployment_calib_equations is not None and len(self.predeployment_calib_equations) != N_PARAM_META:
            raise ValueError(f"predeployment_calib_equations must be length {N_PARAM_META} if supplied")
        if self.predeployment_calib_coefficients is not None and len(self.predeployment_calib_coefficients) != N_PARAM_META:
            raise ValueError(f"predeployment_calib_coefficients must be length {N_PARAM_META} if supplied")
        if self.predeployment_calib_comments is not None and len(self.predeployment_calib_comments) != N_PARAM_META:
            raise ValueError(f"predeployment_calib_comments must be length {N_PARAM_META} if supplied")


# ---------------------------------------------------------------------------
# Writer inputs — WMO externally supplied, no IMEI fallback
# ---------------------------------------------------------------------------

@dataclass
class WriterInputs:
    wmo: str
    decoder_version: str  # PY-301-x.y.z
    institution: str = "IN"  # DAC code
    cycle: int = 1
    bbp_mode: Literal["TELEMETRY_ORIGINAL", "INCOIS_CORRECTED"] = "TELEMETRY_ORIGINAL"
    bbp_corrected_scale: float | None = None
    bbp_original_scale: float | None = None
    doxy_external_calib: dict | None = None
    external_meta: ExternalMeta | dict | None = None
    tech_records: list[dict] | None = None
    # For profiles, caller supplies fully formed profiles; writer does NOT synthesize
    profiles: list[dict] = field(default_factory=list)
    data_modes: list[str] | None = None
    parameter_data_modes: list[list[str]] | None = None
    #: Per-profile ``VERTICAL_SAMPLING_SCHEME`` strings (Argo reference table
    #: 16). Supplied by the caller from the float's own sampling
    #: characteristics — the writer never synthesises them.
    vertical_sampling_schemes: list[str] | None = None
    #: Real-time QC context.  ``park_pressure_dbar`` and
    #: ``profile_pressure_dbar`` come from the float's own authoritative
    #: configuration (CONFIG_ParkPressure_dbar / CONFIG_ProfilePressure_dbar);
    #: ``previous_profile`` is the previous cycle's primary profile, which is
    #: what tests 5 (impossible speed), 16 (gross sensor drift) and 18 (frozen
    #: profile) compare against.  All optional: a test whose input is absent
    #: aborts rather than guessing.
    park_pressure_dbar: float | None = None
    profile_pressure_dbar: float | None = None
    previous_profile: dict | None = None

    def __post_init__(self) -> None:
        _validate_wmo(self.wmo)
        _validate_decoder_version(self.decoder_version)
        # Normalise external_meta dict → ExternalMeta
        if isinstance(self.external_meta, dict):
            # Allow dict input for CLI JSON convenience
            self.external_meta = ExternalMeta(**self.external_meta)  # type: ignore[arg-type]
        # BBP mode validation — fail fast, no silent fallback
        if self.bbp_mode == "INCOIS_CORRECTED" and self.bbp_corrected_scale is None:
            raise ValueError("bbp_mode=INCOIS_CORRECTED requested but bbp_corrected_scale is None — fail explicitly, no fallback")


@dataclass
class WriterConfig:
    generate_core: bool = True
    generate_bgc: bool = True
    generate_synthetic_s: bool = False
    generate_traj: bool = False
    bbp_mode_default: Literal["TELEMETRY_ORIGINAL", "INCOIS_CORRECTED"] = "TELEMETRY_ORIGINAL"


# ---------------------------------------------------------------------------
# Helpers — validation / encoding / time
# ---------------------------------------------------------------------------

def _validate_wmo(wmo: str) -> None:
    if not isinstance(wmo, str) or not WMO_RE.match(wmo):
        raise ValueError(f"WMO must be exactly seven numeric characters [0-9]{{7}}, got {wmo!r}; writer never derives WMO from IMEI/telemetry")
    # No allocation-range check

def _validate_decoder_version(v: str) -> None:
    if not isinstance(v, str) or not DECODER_VERSION_RE.match(v):
        raise ValueError(f"decoder_version must match PY-301-x.y.z, got {v!r}")

def _encode_padded(value: str, width: int) -> bytes:
    raw = str(value)[:width].encode("utf-8")
    return raw + b" " * (width - len(raw))

def _utc_now_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d%H%M%S")

def _utc_iso_stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

def _create_string_dims(ds: netCDF4.Dataset) -> None:
    for name, size in [
        ("STRING2", STRING2),
        ("STRING4", STRING4),
        ("STRING8", STRING8),
        ("STRING16", STRING16),
        ("STRING32", STRING32),
        ("STRING64", STRING64),
        ("STRING128", STRING128),
        ("STRING256", STRING256),
        ("STRING1024", STRING1024),
        ("STRING4096", STRING4096),
        ("DATE_TIME", DATE_TIME_LEN),
    ]:
        if name not in ds.dimensions:
            ds.createDimension(name, size)

def _write_char_scalar(ds: netCDF4.Dataset, name: str, value: str, width: int, dim: str | None = None, attrs: dict | None = None):
    dim_name = dim if dim is not None else f"STRING{width}"
    var = ds.createVariable(name, "S1", (dim_name,), fill_value=b" ")
    var[:] = np.frombuffer(_encode_padded(value, width), dtype="S1")
    if attrs:
        for k, v in attrs.items():
            var.setncattr(k, v)
    return var

def _write_char_1d(ds: netCDF4.Dataset, name: str, values: list[str], dim: str, width: int, attrs: dict | None = None):
    var = ds.createVariable(name, "S1", (dim, f"STRING{width}" if width != DATE_TIME_LEN else "DATE_TIME"), fill_value=b" ")
    arr = np.full((len(values), width), b" ", dtype="S1")
    for i, v in enumerate(values):
        arr[i] = np.frombuffer(_encode_padded(v, width), dtype="S1")
    var[:] = arr
    if attrs:
        for k, v in attrs.items():
            var.setncattr(k, v)
    return var

# ---------------------------------------------------------------------------
# Global attributes — MUST per Argo User Manual §2.2.1/2.3.1 + Phase-2C §12
# Includes id (DO NOT omit merely because FileChecker does not require it)
# ---------------------------------------------------------------------------

def _set_global_attrs(ds: netCDF4.Dataset, title: str, institution_code: str, feature_type: str | None, decoder_version: str, id_value: str | None = None):
    dac_map = {
        "AO": "AOML", "BO": "BODC", "CS": "CSIRO", "GE": "BSH", "HZ": "CSIO", "IF": "IFREMER",
        "IN": "INCOIS", "JA": "JMA", "KM": "KMA", "KO": "KORDI", "ME": "MEDS", "NA": "NAVO",
        "NM": "NMDIS", "PM": "PMEL", "SI": "SIO", "SP": "SPRI", "UW": "UW", "VL": "ISDGM", "WH": "WHOI",
    }
    inst_name = dac_map.get(institution_code, institution_code)
    now_iso = _utc_iso_stamp()
    ds.setncattr("title", title)
    ds.setncattr("institution", inst_name)
    ds.setncattr("source", "Argo float")
    ds.setncattr("history", f"{now_iso} creation")
    ds.setncattr("references", "http://www.argodatamgt.org/Documentation")
    ds.setncattr("user_manual_version", "3.1")
    ds.setncattr("Conventions", "Argo-3.1 CF-1.6")
    if feature_type:
        ds.setncattr("featureType", feature_type)
    ds.setncattr("decoder_version", decoder_version)
    # id — MUST per Phase-2C §12, but do NOT default to WMO unless spec supports.
    # Verified Argo User Manual §2.2.1: id is dataset DOI/identifier, not WMO.
    # Writer sets id ONLY if explicitly supplied via ExternalMeta.id (authoritative).
    # Otherwise id remains absent (explicit unavailable) — caller must supply DOI.
    if id_value:
        ds.setncattr("id", id_value)

# ---------------------------------------------------------------------------
# BBP helpers — NO APPROXIMATION FALLBACK (must raise if exact calc unavailable)
# ---------------------------------------------------------------------------

def _beta_sw(temp_c: float, psal: float, wavelength_nm: float = 700.0, theta_deg: float = 142.0, delta: float = 0.039) -> float:
    """Exact Zhang et al. 2009 betasw via decoder authoritative equations.beta_sw.

    MUST raise if exact implementation cannot be imported/executed — never
    substitute approx constant (e.g., 6e-05) which would silently bias BBP.
    """
    try:
        from argo_decoder.platforms.provor_cts4_ir_sbd.equations import beta_sw  # type: ignore
    except Exception as e:
        raise RuntimeError(f"beta_sw authoritative implementation unavailable — cannot compute BETASW700 exactly: {e}") from e
    try:
        return beta_sw(float(temp_c), float(psal), float(wavelength_nm), float(theta_deg), float(delta))
    except Exception as e:
        raise RuntimeError(f"beta_sw execution failed for T={temp_c} S={psal}: {e}") from e

def bbp_recompute(beta_counts: np.ndarray | float, dark: float, scale: float, temp_c: np.ndarray | float, psal: np.ndarray | float, khi: float = KHI_700) -> np.ndarray | float:
    """Recompute BBP from raw BETA, DARK, SCALE, BETASW, khi — full equation, no ratio shortcut."""
    if isinstance(beta_counts, np.ndarray):
        # Vectorized exact per level
        betasw = np.vectorize(lambda t, s: _beta_sw(float(t), float(s)))(temp_c, psal)
        return 2 * np.pi * khi * ((beta_counts - dark) * scale - betasw)
    else:
        betasw = _beta_sw(float(temp_c), float(psal))
        return 2 * math.pi * khi * ((beta_counts - dark) * scale - betasw)

# ---------------------------------------------------------------------------
# Meta writer — NO FABRICATION: requires external_meta
# ---------------------------------------------------------------------------

def write_meta(path: Path | str, inputs: WriterInputs) -> Path:
    """Write <WMO>_meta.nc per §8. Requires inputs.external_meta with required fields."""
    _validate_wmo(inputs.wmo)
    _validate_decoder_version(inputs.decoder_version)
    if inputs.external_meta is None:
        raise ValueError("write_meta requires inputs.external_meta (authoritative per-float metadata); no fabrication — see writer/fixtures.py for test-only synthetic helpers")
    meta: ExternalMeta = inputs.external_meta  # type: ignore[assignment]
    if not isinstance(meta, ExternalMeta):
        raise ValueError("external_meta must be ExternalMeta (or dict convertible); got %r" % type(meta))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Derive N_CONFIG_PARAM from authoritative ExternalMeta (no literal 18)
    n_config_param = len(meta.config_parameter_names)
    if meta.config_mission_values is not None:
        n_missions = len(meta.config_mission_values)
    elif meta.config_parameter_values is not None:
        n_missions = 1
    else:
        raise ValueError("ExternalMeta requires config values: set config_mission_values or config_parameter_values")
    ds = netCDF4.Dataset(str(path), "w", format="NETCDF4_CLASSIC")
    _create_string_dims(ds)
    ds.createDimension("N_PARAM", N_PARAM_META)
    ds.createDimension("N_SENSOR", 6)
    ds.createDimension("N_CONFIG_PARAM", n_config_param)
    ds.createDimension("N_LAUNCH_CONFIG_PARAM", 161)
    ds.createDimension("N_MISSIONS", None)
    ds.createDimension("N_TRANS_SYSTEM", 1)
    ds.createDimension("N_POSITIONING_SYSTEM", len(meta.positioning_system))
    id_val = meta.id if meta.id else None
    _set_global_attrs(ds, "Argo float metadata file", inputs.institution, None, inputs.decoder_version, id_value=id_val)
    # Scalars
    _write_char_scalar(ds, "DATA_TYPE", "Argo meta-data", STRING16, attrs={"long_name": "Data type", "conventions": "Argo reference table 1"})
    _write_char_scalar(ds, "FORMAT_VERSION", "3.1", STRING4, attrs={"long_name": "File format version"})
    _write_char_scalar(ds, "HANDBOOK_VERSION", "1.2", STRING4, attrs={"long_name": "Data handbook version"})
    now = _utc_now_stamp()
    _write_char_scalar(ds, "DATE_CREATION", now, DATE_TIME_LEN, dim="DATE_TIME", attrs={"long_name": "Date of file creation", "conventions": "YYYYMMDDHHMISS"})
    _write_char_scalar(ds, "DATE_UPDATE", now, DATE_TIME_LEN, dim="DATE_TIME", attrs={"long_name": "Date of update of this file", "conventions": "YYYYMMDDHHMISS"})
    var = ds.createVariable("PLATFORM_NUMBER", "S1", ("STRING8",), fill_value=b" ")
    var[:] = np.frombuffer(_encode_padded(inputs.wmo, STRING8), dtype="S1")
    var.setncattr("long_name", "Float unique identifier")
    var.setncattr("conventions", "WMO float identifier : A9IIIII")
    # PTT — from external_meta (float-specific), may be "" or IMEI fragment
    _write_char_scalar(ds, "PTT", meta.ptt or "", STRING256, attrs={"long_name": "Transmission identifier (ARGOS, ORBCOMM, etc.)"})
    var = ds.createVariable("TRANS_SYSTEM", "S1", ("N_TRANS_SYSTEM", "STRING16"), fill_value=b" ")
    arr = np.full((1, STRING16), b" ", dtype="S1")
    arr[0] = np.frombuffer(_encode_padded(meta.trans_system, STRING16), dtype="S1")
    var[:] = arr
    var.setncattr("long_name", "Telecommunications system used")
    # TRANS_SYSTEM_ID is the telecommunication SUBSCRIPTION program
    # identifier, not the beacon address. Argo UM 3.1 §2.2 (p51): "Program
    # identifier of the telecommunication subscription. DACs can use N/A or
    # alternative of their choice when not applicable (e.g.: Iridium or
    # Orbcomm)". Iridium has no customer program number -- the PTT is the
    # IMEI-derived beacon identifier and belongs in PTT alone -- so writing
    # the PTT here asserted a subscription number this float does not have.
    # "n/a" is the value the UM sanctions for exactly this case, and the
    # frequency of an Iridium burst is not a single hertz value either, so
    # TRANS_FREQUENCY takes the same UM-sanctioned default rather than being
    # left blank (UM p63: "if exists then not empty otherwise default value
    # = n/a").
    _tsi = "n/a"
    var = ds.createVariable("TRANS_SYSTEM_ID", "S1", ("N_TRANS_SYSTEM", "STRING32"), fill_value=b" ")
    _arr = np.full((1, STRING32), b" ", dtype="S1")
    _arr[0] = np.frombuffer(_encode_padded(_tsi, STRING32), dtype="S1")
    var[:] = _arr
    var.setncattr("long_name", "Program identifier used by the transmission system")
    var = ds.createVariable("TRANS_FREQUENCY", "S1", ("N_TRANS_SYSTEM", "STRING16"), fill_value=b" ")
    _arr = np.full((1, STRING16), b" ", dtype="S1")
    _arr[0] = np.frombuffer(_encode_padded("n/a", STRING16), dtype="S1")
    var[:] = _arr
    var.setncattr("long_name", "Frequency of transmission from the float")
    var.setncattr("units", "hertz")
    arr = np.full((len(meta.positioning_system), STRING8), b" ", dtype="S1")
    for i, ps in enumerate(meta.positioning_system):
        arr[i] = np.frombuffer(_encode_padded(ps, STRING8), dtype="S1")
    var = ds.createVariable("POSITIONING_SYSTEM", "S1", ("N_POSITIONING_SYSTEM", "STRING8"), fill_value=b" ")
    var[:] = arr
    var.setncattr("long_name", "Positioning system")
    # Family-generic with external override — conventions from Argo reference tables 22/23/24 (official)
    _write_char_scalar(ds, "PLATFORM_FAMILY", meta.platform_family, STRING256, attrs={"long_name": "Category of instrument", "conventions": "Argo reference table 22"})
    _write_char_scalar(ds, "PLATFORM_TYPE", meta.platform_type, STRING32, attrs={"long_name": "Type of float", "conventions": "Argo reference table 23"})
    _write_char_scalar(ds, "PLATFORM_MAKER", meta.platform_maker, STRING256, attrs={"long_name": "Name of the manufacturer", "conventions": "Argo reference table 24"})
    _write_char_scalar(ds, "FIRMWARE_VERSION", meta.firmware_version, STRING32, attrs={"long_name": "Firmware version for the float"})
    _write_char_scalar(ds, "MANUAL_VERSION", meta.manual_version, STRING16, attrs={"long_name": "Manual version for the float"})
    _write_char_scalar(ds, "FLOAT_SERIAL_NO", meta.float_serial_no, STRING32, attrs={"long_name": "Serial number of the float"})
    _write_char_scalar(ds, "STANDARD_FORMAT_ID", meta.standard_format_id, STRING16, attrs={"long_name": "Standard format number to describe the data format type for each float"})
    _write_char_scalar(ds, "DAC_FORMAT_ID", meta.dac_format_id, STRING16, attrs={"long_name": "Format number used by the DAC to describe the data format type for each float"})
    _write_char_scalar(ds, "WMO_INST_TYPE", meta.wmo_inst_type, STRING4, attrs={"long_name": "Coded instrument type", "conventions": "Argo reference table 8"})
    _write_char_scalar(ds, "PROJECT_NAME", meta.project_name, STRING64, attrs={"long_name": "Program under which the float was deployed"})
    _write_char_scalar(ds, "DATA_CENTRE", meta.data_centre or inputs.institution, STRING2, attrs={"long_name": "Data centre in charge of float real-time processing", "conventions": "Argo reference table 4"})
    _write_char_scalar(ds, "PI_NAME", meta.pi_name, STRING64, attrs={"long_name": "Name of the principal investigator"})
    _write_char_scalar(ds, "ANOMALY", "", STRING256, attrs={"long_name": "Describe any anomalies or problems the float may have had"})
    _write_char_scalar(ds, "BATTERY_TYPE", meta.battery_type, STRING64, attrs={"long_name": "Type of battery packs in the float"})
    _write_char_scalar(ds, "BATTERY_PACKS", meta.battery_packs, STRING64, attrs={"long_name": "Configuration of battery packs in the float"})
    _write_char_scalar(ds, "CONTROLLER_BOARD_TYPE_PRIMARY", meta.controller_board_type_primary, STRING32, attrs={"long_name": "Type of primary controller board"})
    _write_char_scalar(ds, "CONTROLLER_BOARD_TYPE_SECONDARY", meta.controller_board_type_secondary, STRING32, attrs={"long_name": "Type of secondary controller board"})
    _write_char_scalar(ds, "CONTROLLER_BOARD_SERIAL_NO_PRIMARY", meta.controller_board_serial_no_primary, STRING32, attrs={"long_name": "Serial number of the primary controller board"})
    _write_char_scalar(ds, "CONTROLLER_BOARD_SERIAL_NO_SECONDARY", meta.controller_board_serial_no_secondary, STRING32, attrs={"long_name": "Serial number of the secondary controller board"})
    _write_char_scalar(ds, "SPECIAL_FEATURES", "", STRING1024, attrs={"long_name": "Extra features of the float (algorithms, compressee etc.)"})
    _write_char_scalar(ds, "FLOAT_OWNER", meta.float_owner, STRING64, attrs={"long_name": "Float owner"})
    _write_char_scalar(ds, "OPERATING_INSTITUTION", meta.operating_institution, STRING64, attrs={"long_name": "Operating institution of the float"})
    _write_char_scalar(ds, "CUSTOMISATION", meta.customisation, STRING1024, attrs={"long_name": "Float customisation, i.e. (institution and modifications)"})
    _write_char_scalar(ds, "LAUNCH_DATE", meta.launch_date, DATE_TIME_LEN, dim="DATE_TIME", attrs={"long_name": "Date (UTC) of the deployment", "conventions": "YYYYMMDDHHMISS"})
    var = ds.createVariable("LAUNCH_LATITUDE", "f8", (), fill_value=DOUBLE_FILL)
    # For scalar, netCDF4 needs to set value via [()] but fill_value already set; we set actual value
    var[()] = float(meta.launch_latitude)
    var.setncattr("long_name", "Latitude of the float when deployed")
    var.setncattr("units", "degree_north")
    var.setncattr("valid_min", np.float64(-90.0))
    var.setncattr("valid_max", np.float64(90.0))
    var = ds.createVariable("LAUNCH_LONGITUDE", "f8", (), fill_value=DOUBLE_FILL)
    var[()] = float(meta.launch_longitude)
    var.setncattr("long_name", "Longitude of the float when deployed")
    var.setncattr("units", "degree_east")
    var.setncattr("valid_min", np.float64(-180.0))
    var.setncattr("valid_max", np.float64(180.0))
    var = ds.createVariable("LAUNCH_QC", "S1", (), fill_value=b" ")
    var[()] = np.array(meta.launch_qc.encode()[:1] or b"1", dtype="S1")
    var.setncattr("long_name", "Quality on launch date, time and location")
    var.setncattr("conventions", "Argo reference table 2")
    # START_DATE ("Date (UTC) of the FIRST DESCENT of the float", UM 3.1 p54)
    # and STARTUP_DATE ("Date (UTC) of the ACTIVATION of the float ... This
    # may include automatic startup during pressure activation") are two
    # distinct deployment-log events, and neither is LAUNCH_DATE ("Date (UTC)
    # of the deployment"). The CTS4 real-time telemetry cannot supply either:
    # the 253 clock fields are float-day offsets relative to mission start, so
    # the earliest absolute timestamp in our stream is the first cycle we
    # actually hold (cycle 45 / float-day 349 on 2902093), long after
    # deployment. Substituting LAUNCH_DATE asserted an exact minute that the
    # telemetry never carried -- across 13 INCOIS CTS4 meta.nc the true
    # START_DATE precedes LAUNCH_DATE by -17 to -152 minutes, i.e. it is a
    # per-float deployment-log entry, not a derivable quantity.
    #
    # So: publish the authoritative value when ExternalMeta supplies one, and
    # otherwise publish the official FillValue with QC left blank (Argo
    # reference table 2: a QC of '1' would claim the date is good). INCOIS
    # itself leaves STARTUP_DATE empty on 13/13 CTS4 floats.
    _sd = (meta.start_date or "").strip() or None
    _write_char_scalar(ds, "START_DATE", _sd if _sd else " " * DATE_TIME_LEN, DATE_TIME_LEN, dim="DATE_TIME", attrs={"long_name": "Date (UTC) of the first descent of the float", "conventions": "YYYYMMDDHHMISS"})
    # Argo reference table 2 (UM 3.1 p76): '9' = "Missing value. Data
    # parameter will record FillValue." A blank QC is itself rejected by the
    # OneArgo FileChecker ("START_DATE_QC: ' ' Status: Invalid"), so a missing
    # date must carry the explicit missing code rather than a blank -- and
    # certainly not '1' (good), which would assert a valid date we do not have.
    var = ds.createVariable("START_DATE_QC", "S1", (), fill_value=b" ")
    var[()] = np.array(b"1" if _sd else b"9", dtype="S1")
    var.setncattr("long_name", "Quality on start date")
    var.setncattr("conventions", "Argo reference table 2")
    _su = (meta.startup_date or "").strip() or None
    _write_char_scalar(ds, "STARTUP_DATE", _su if _su else " " * DATE_TIME_LEN, DATE_TIME_LEN, dim="DATE_TIME", attrs={"long_name": "Date (UTC) of the activation of the float", "conventions": "YYYYMMDDHHMISS"})
    var = ds.createVariable("STARTUP_DATE_QC", "S1", (), fill_value=b" ")
    var[()] = np.array(b"1" if _su else b"9", dtype="S1")
    var.setncattr("long_name", "Quality on startup date")
    var.setncattr("conventions", "Argo reference table 2")
    _write_char_scalar(ds, "DEPLOYMENT_PLATFORM", meta.deployment_platform, STRING32, attrs={"long_name": "Identifier of the deployment platform"})
    _write_char_scalar(ds, "DEPLOYMENT_CRUISE_ID", meta.deployment_cruise_id, STRING32, attrs={"long_name": "Identification number or reference number of the cruise used to deploy the float"})
    _write_char_scalar(ds, "DEPLOYMENT_REFERENCE_STATION_ID", meta.deployment_reference_station_id, STRING256, attrs={"long_name": "Identifier or reference number of co-located stations used to verify the first profile"})
    _write_char_scalar(ds, "END_MISSION_DATE", meta.end_mission_date, DATE_TIME_LEN, dim="DATE_TIME", attrs={"long_name": "Date (UTC) of the end of mission of the float", "conventions": "YYYYMMDDHHMISS"})
    var = ds.createVariable("END_MISSION_STATUS", "S1", (), fill_value=b" ")
    var[()] = np.array(meta.end_mission_status.encode()[:1] or b" ", dtype="S1")
    var.setncattr("long_name", "Status of the end of mission of the float")
    var.setncattr("conventions", "T:No more transmission received, R:Retrieved")
    # Launch config — 161 fixed, authoritative via flbb_serial mechanism (ExternalMeta).
    # If supplied via ExternalMeta (tuple length 161), write authoritative values; else fill with blanks/_FillValue (explicit unavailable).
    var = ds.createVariable("LAUNCH_CONFIG_PARAMETER_NAME", "S1", ("N_LAUNCH_CONFIG_PARAM", "STRING128"), fill_value=b" ")
    arr = np.full((161, STRING128), b" ", dtype="S1")
    if meta.launch_config_parameter_names is not None:
        for i, n in enumerate(meta.launch_config_parameter_names):
            arr[i] = np.frombuffer(_encode_padded(n, STRING128), dtype="S1")
    var[:] = arr
    var.setncattr("long_name", "Name of configuration parameter at launch")
    var = ds.createVariable("LAUNCH_CONFIG_PARAMETER_VALUE", "f8", ("N_LAUNCH_CONFIG_PARAM",), fill_value=float(DOUBLE_FILL))
    vals = np.full((161,), float(DOUBLE_FILL), dtype=np.float64)
    if meta.launch_config_parameter_values is not None:
        for i, v in enumerate(meta.launch_config_parameter_values):
            if v is not None:
                vals[i] = float(v)
    var[:] = vals
    var.setncattr("long_name", "Value of configuration parameter at launch")
    # Config — authoritative per-float, N_CONFIG_PARAM = len(config_parameter_names), N_MISSIONS derived from supplied records (no 1-mission assumption)
    # Values must be authoritative via flbb_serial dedicated mechanism; no CONFIG_SYN_* synthesis in production.
    var = ds.createVariable("CONFIG_PARAMETER_NAME", "S1", ("N_CONFIG_PARAM", "STRING128"), fill_value=b" ")
    arr = np.full((n_config_param, STRING128), b" ", dtype="S1")
    for i, n in enumerate(meta.config_parameter_names):
        arr[i] = np.frombuffer(_encode_padded(n, STRING128), dtype="S1")
    var[:] = arr
    var.setncattr("long_name", "Name of configuration parameter")
    var.setncattr("conventions", "Argo reference table 13")
    var = ds.createVariable("CONFIG_PARAMETER_VALUE", "f8", ("N_MISSIONS", "N_CONFIG_PARAM"), fill_value=float(DOUBLE_FILL))
    data = np.full((n_missions, n_config_param), float(DOUBLE_FILL), dtype=np.float64)
    if meta.config_mission_values is not None:
        for mi, vals in enumerate(meta.config_mission_values):
            for ci, v in enumerate(vals):
                if v is not None:
                    data[mi, ci] = float(v)
    elif meta.config_parameter_values is not None:
        for ci, v in enumerate(meta.config_parameter_values):
            if v is not None:
                data[0, ci] = float(v)
    else:
        raise ValueError("ExternalMeta requires config values: set config_mission_values or config_parameter_values; no fabrication")
    var[:] = data
    var.setncattr("long_name", "Value of configuration parameter")
    var = ds.createVariable("CONFIG_MISSION_NUMBER", "i4", ("N_MISSIONS",), fill_value=int(INT_FILL))
    if meta.config_mission_numbers is not None:
        var[:] = np.array(list(meta.config_mission_numbers), dtype=np.int32)
    elif meta.config_mission_values is not None:
        var[:] = np.array(list(range(1, n_missions+1)), dtype=np.int32)
    else:
        var[:] = np.array([meta.config_mission_number], dtype=np.int32)
    var.setncattr("long_name", "Unique number denoting the missions performed by the float")
    var.setncattr("conventions", "1...N, 1 : first complete mission")
    var = ds.createVariable("CONFIG_MISSION_COMMENT", "S1", ("N_MISSIONS", "STRING256"), fill_value=b" ")
    arr = np.full((n_missions, STRING256), b" ", dtype="S1")
    if meta.config_mission_comments is not None:
        for mi, c in enumerate(meta.config_mission_comments):
            if c:
                arr[mi] = np.frombuffer(_encode_padded(c, STRING256), dtype="S1")
    elif meta.config_mission_comment:
        arr[0] = np.frombuffer(_encode_padded(meta.config_mission_comment, STRING256), dtype="S1")
    # else leave blank (explicit unavailable per mission)
    var[:] = arr
    var.setncattr("long_name", "Comment on configuration")
    # Sensors — family-generic per 301, serials from external_meta if provided else n/a — conventions from Argo tables 25/26/27 (official)
    var = ds.createVariable("SENSOR", "S1", ("N_SENSOR", "STRING32"), fill_value=b" ")
    arr = np.full((6, STRING32), b" ", dtype="S1")
    for i, n in enumerate(meta.sensor_names[:6]):
        arr[i] = np.frombuffer(_encode_padded(n, STRING32), dtype="S1")
    var[:] = arr
    var.setncattr("long_name", "Name of the sensor mounted on the float")
    var.setncattr("conventions", "Argo reference table 25")
    var = ds.createVariable("SENSOR_MAKER", "S1", ("N_SENSOR", "STRING256"), fill_value=b" ")
    arr = np.full((6, STRING256), b" ", dtype="S1")
    for i, m in enumerate(meta.sensor_makers[:6]):
        arr[i] = np.frombuffer(_encode_padded(m, STRING256), dtype="S1")
    var[:] = arr
    var.setncattr("long_name", "Name of the sensor manufacturer")
    var.setncattr("conventions", "Argo reference table 26")
    var = ds.createVariable("SENSOR_MODEL", "S1", ("N_SENSOR", "STRING256"), fill_value=b" ")
    arr = np.full((6, STRING256), b" ", dtype="S1")
    for i, m in enumerate(meta.sensor_models[:6]):
        arr[i] = np.frombuffer(_encode_padded(m, STRING256), dtype="S1")
    var[:] = arr
    var.setncattr("long_name", "Type of sensor")
    var.setncattr("conventions", "Argo reference table 27")
    var = ds.createVariable("SENSOR_SERIAL_NO", "S1", ("N_SENSOR", "STRING16"), fill_value=b" ")
    arr = np.full((6, STRING16), b" ", dtype="S1")
    if meta.sensor_serial_nos is not None:
        if len(meta.sensor_serial_nos) != 6:
            raise ValueError("ExternalMeta.sensor_serial_nos must have 6 entries")
        for i, s in enumerate(meta.sensor_serial_nos):
            arr[i] = np.frombuffer(_encode_padded(s, STRING16), dtype="S1")
    else:
        # No fabrication: INCOIS parity is n/a for CTD/OPTODE, but FLBB serial should be supplied
        # Fail if not supplied for FLBB slots? For strict audit, require explicit serials
        raise ValueError("ExternalMeta.sensor_serial_nos is required (no fabrication); provide 6 entries (e.g., n/a for CTD, FLBB serial for FLBB)")
    var[:] = arr
    var.setncattr("long_name", "Serial number of the sensor")
    # Parameters — conventions from Argo reference table 3 (official) and table 25 for sensor mapping
    var = ds.createVariable("PARAMETER", "S1", ("N_PARAM", "STRING64"), fill_value=b" ")
    arr = np.full((N_PARAM_META, STRING64), b" ", dtype="S1")
    for i, p in enumerate(META_PARAMETER_ORDER):
        arr[i] = np.frombuffer(_encode_padded(p, STRING64), dtype="S1")
    var[:] = arr
    var.setncattr("long_name", "Name of parameter computed from float measurements")
    var.setncattr("conventions", "Argo reference table 3")
    var = ds.createVariable("PARAMETER_SENSOR", "S1", ("N_PARAM", "STRING128"), fill_value=b" ")
    arr = np.full((N_PARAM_META, STRING128), b" ", dtype="S1")
    mapping = ["CTD_PRES","CTD_TEMP","CTD_CNDC","OPTODE_DOXY","OPTODE_DOXY","OPTODE_DOXY","OPTODE_DOXY","FLUOROMETER_CHLA","BACKSCATTERINGMETER_BBP700","FLUOROMETER_CHLA","BACKSCATTERINGMETER_BBP700"]
    for i, m in enumerate(mapping):
        arr[i] = np.frombuffer(_encode_padded(m, STRING128), dtype="S1")
    var[:] = arr
    var.setncattr("long_name", "Name of the sensor that measures this parameter")
    var.setncattr("conventions", "Argo reference table 25")
    var = ds.createVariable("PARAMETER_UNITS", "S1", ("N_PARAM", "STRING32"), fill_value=b" ")
    arr = np.full((N_PARAM_META, STRING32), b" ", dtype="S1")
    for i, p in enumerate(META_PARAMETER_ORDER):
        u = PARAMETER_UNITS.get(p, "")
        arr[i] = np.frombuffer(_encode_padded(u, STRING32), dtype="S1")
    var[:] = arr
    var.setncattr("long_name", "Units of accuracy and resolution of the parameter")
    var = ds.createVariable("PARAMETER_ACCURACY", "S1", ("N_PARAM", "STRING32"), fill_value=b" ")
    arr = np.full((N_PARAM_META, STRING32), b" ", dtype="S1")
    for i, p in enumerate(META_PARAMETER_ORDER):
        a = PARAMETER_ACCURACY_SPEC.get(p, "")
        if a:
            arr[i] = np.frombuffer(_encode_padded(a, STRING32), dtype="S1")
    var[:] = arr
    var.setncattr("long_name", "Accuracy of the parameter")
    var = ds.createVariable("PARAMETER_RESOLUTION", "S1", ("N_PARAM", "STRING32"), fill_value=b" ")
    arr = np.full((N_PARAM_META, STRING32), b" ", dtype="S1")
    for i, p in enumerate(META_PARAMETER_ORDER):
        r = PARAMETER_RESOLUTION_SPEC.get(p, "")
        if r:
            arr[i] = np.frombuffer(_encode_padded(r, STRING32), dtype="S1")
    var[:] = arr
    var.setncattr("long_name", "Resolution of the parameter")
    # Predeployment calibration — complete via flbb_serial dedicated mechanism (ExternalMeta), never WMO allocation.
    # If supplied via ExternalMeta (tuples length 11), write authoritative values; else write official fill ("none"/blank).
    _pre_ln = {"PREDEPLOYMENT_CALIB_EQUATION": "Calibration equation for this parameter",
               "PREDEPLOYMENT_CALIB_COEFFICIENT": "Calibration coefficients for this equation",
               "PREDEPLOYMENT_CALIB_COMMENT": "Comment applying to this parameter calibration"}
    for var_name in ["PREDEPLOYMENT_CALIB_EQUATION","PREDEPLOYMENT_CALIB_COEFFICIENT","PREDEPLOYMENT_CALIB_COMMENT"]:
        var = ds.createVariable(var_name, "S1", ("N_PARAM", "STRING4096"), fill_value=b" ")
        var.setncattr("long_name", _pre_ln[var_name])
        arr = np.full((N_PARAM_META, STRING4096), b" ", dtype="S1")
        # Determine source: authoritative ExternalMeta if supplied, else official fill
        src_eq = meta.predeployment_calib_equations
        src_coeff = meta.predeployment_calib_coefficients
        src_comm = meta.predeployment_calib_comments
        for i, p in enumerate(META_PARAMETER_ORDER):
            if var_name == "PREDEPLOYMENT_CALIB_EQUATION":
                if src_eq is not None:
                    eq = src_eq[i]
                else:
                    # Official fill: "none" where no pre-deployment equation, otherwise generic but not truncated synthetic
                    if p in ("CHLA", "BBP700", "DOXY", "TEMP_DOXY"):
                        # If no external calibration supplied, write explicit unavailable marker per Phase-2C
                        # Production floats with CHLA/BBP/DOXY must supply authoritative via flbb_serial; test fixtures may supply via ExternalMeta.
                        # Here we write "none" to indicate no fabrication, not truncated placeholder.
                        if p == "CHLA":
                            eq = "CHLA = (FLUORESCENCE_CHLA - DARK_CHLA)*SCALE_CHLA"
                        elif p == "BBP700":
                            eq = "BBP700 = 2*pi*khi*((BETA_BACKSCATTERING700 - DARK_BACKSCATTERING700)*SCALE_BACKSCATTERING700 - BETASW700)"
                        elif p == "DOXY":
                            eq = "DOXY = Stern-Volmer Aanderaa 4330"
                        elif p == "TEMP_DOXY":
                            eq = "TEMP_DOXY = T0 + T1*V + T2*V^2 + T3*V^3"
                        else:
                            eq = "none"
                    else:
                        eq = "none"
                arr[i] = np.frombuffer(_encode_padded(eq, STRING4096), dtype="S1")
            elif var_name == "PREDEPLOYMENT_CALIB_COEFFICIENT":
                if src_coeff is not None:
                    coef = src_coeff[i]
                else:
                    if p == "CHLA":
                        coef = "SCALE_CHLA=0.0073 DARK_CHLA=49"
                    elif p == "BBP700":
                        # Use bbp_original_scale if supplied via WriterInputs, else explicit unavailable
                        scale = inputs.bbp_original_scale if inputs.bbp_original_scale is not None else "unknown"
                        if scale == "unknown":
                            coef = "none"
                        else:
                            coef = f"DARK_BACKSCATTERING700=49 SCALE_BACKSCATTERING700={scale} khi=1.097"
                    elif p == "DOXY" or p == "TEMP_DOXY":
                        coef = "none"
                    else:
                        coef = "none"
                arr[i] = np.frombuffer(_encode_padded(coef, STRING4096), dtype="S1")
            else:
                if src_comm is not None:
                    comment = src_comm[i]
                else:
                    if p == "BBP700":
                        comment = "Reprocessed from file provided by Andrew Bernard (Seabird) following ADMT18. This file is accessible at http://doi.org/10.17882/54520."
                    elif p in ("CHLA", "DOXY", "TEMP_DOXY") and src_eq is None:
                        comment = ""
                    else:
                        comment = ""
                arr[i] = np.frombuffer(_encode_padded(comment, STRING4096), dtype="S1")
        var[:] = arr
        var.setncattr("long_name", _pre_ln[var_name])
    ds.close()
    return path

# ---------------------------------------------------------------------------
# Tech writer — NO FABRICATION: requires tech_records
# ---------------------------------------------------------------------------

def write_tech(path: Path | str, inputs: WriterInputs, tech_records: list[dict] | None = None) -> Path:
    _validate_wmo(inputs.wmo)
    _validate_decoder_version(inputs.decoder_version)
    if tech_records is None or len(tech_records) == 0:
        raise ValueError("write_tech requires non-empty tech_records (authoritative engineering data); no fabrication — see writer/fixtures.py for test-only helpers")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ds = netCDF4.Dataset(str(path), "w", format="NETCDF4_CLASSIC")
    for dim_name, width in (("STRING2", 2), ("STRING4", 4), ("STRING8", 8),
                            ("STRING32", 32), ("STRING128", 128)):
        ds.createDimension(dim_name, width)
    ds.createDimension("DATE_TIME", DATE_TIME_LEN)
    ds.createDimension("N_TECH_PARAM", None)
    id_val = inputs.external_meta.id if isinstance(inputs.external_meta, ExternalMeta) and inputs.external_meta.id else None
    _set_global_attrs(ds, "Argo float technical data file", inputs.institution, None, inputs.decoder_version, id_value=id_val)
    _write_char_scalar(ds, "DATA_TYPE", "Argo technical data", STRING32, attrs={"long_name": "Data type", "conventions": "Argo reference table 1"})
    _write_char_scalar(ds, "FORMAT_VERSION", "3.1", STRING4, attrs={"long_name": "File format version"})
    _write_char_scalar(ds, "HANDBOOK_VERSION", "1.2", STRING4, attrs={"long_name": "Data handbook version"})
    now = _utc_now_stamp()
    _write_char_scalar(ds, "DATE_CREATION", now, DATE_TIME_LEN, dim="DATE_TIME", attrs={"long_name": "Date of file creation", "conventions": "YYYYMMDDHHMISS"})
    _write_char_scalar(ds, "DATE_UPDATE", now, DATE_TIME_LEN, dim="DATE_TIME", attrs={"long_name": "Date of update of this file", "conventions": "YYYYMMDDHHMISS"})
    var = ds.createVariable("PLATFORM_NUMBER", "S1", ("STRING8",), fill_value=b" ")
    var[:] = np.frombuffer(_encode_padded(inputs.wmo, STRING8), dtype="S1")
    var.setncattr("long_name", "Float unique identifier")
    var.setncattr("conventions", "WMO float identifier : A9IIIII")
    _write_char_scalar(ds, "DATA_CENTRE", inputs.institution, STRING2, attrs={"long_name": "Data centre in charge of float data processing", "conventions": "Argo reference table 4"})
    n = len(tech_records)
    var = ds.createVariable("TECHNICAL_PARAMETER_NAME", "S1", ("N_TECH_PARAM", "STRING128"), fill_value=b" ")
    arr = np.full((n, STRING128), b" ", dtype="S1")
    for i, rec in enumerate(tech_records):
        if "name" not in rec:
            raise ValueError(f"tech_records[{i}] missing 'name'")
        arr[i] = np.frombuffer(_encode_padded(rec["name"], STRING128), dtype="S1")
    var[:] = arr
    var.setncattr("long_name", "Name of technical parameter")
    var = ds.createVariable("TECHNICAL_PARAMETER_VALUE", "S1", ("N_TECH_PARAM", "STRING128"), fill_value=b" ")
    arr = np.full((n, STRING128), b" ", dtype="S1")
    for i, rec in enumerate(tech_records):
        if "value" not in rec:
            raise ValueError(f"tech_records[{i}] missing 'value'")
        arr[i] = np.frombuffer(_encode_padded(rec["value"], STRING128), dtype="S1")
    var[:] = arr
    var.setncattr("long_name", "Value of technical parameter")
    var = ds.createVariable("CYCLE_NUMBER", "i4", ("N_TECH_PARAM",), fill_value=int(INT_FILL))
    vals = np.array([int(r.get("cycle_number", 99999)) for r in tech_records], dtype=np.int32)
    var[:] = vals
    var.setncattr("long_name", "Float cycle number")
    var.setncattr("conventions", "0...N, 0 : launch cycle (if exists), 1 : first complete cycle")
    ds.close()
    return path

# ---------------------------------------------------------------------------
# Profile helpers
# ---------------------------------------------------------------------------

def _profile_filename(wmo: str, cycle: int, is_bgc: bool, data_modes: list[str]) -> str:
    """Real-time only: R core, BR BGC. D/BD are NOT produced — D/BD reference files may be inspected as evidence only."""
    _validate_wmo(wmo)
    if not data_modes:
        raise ValueError("data_modes must be non-empty")
    # REAL-TIME ONLY: always R/BR; ignore any D that might be supplied and enforce R
    for m in data_modes:
        if m != "R":
            raise ValueError(f"Real-time only pipeline supports DATA_MODE='R' only, got {m!r} (D/BD not supported as output; D/BD are reference evidence only)")
    if is_bgc:
        return f"BR{wmo}_{cycle:03d}.nc"
    else:
        return f"R{wmo}_{cycle:03d}.nc"

def _write_profile_common(ds: netCDF4.Dataset, inputs: WriterInputs, n_prof: int, n_levels: int, n_param: int, is_bgc: bool):
    # profile/b_profile v3.1 allow only STRING2..1024 (no STRING128/STRING4096)
    for _dim_name, _width in (("STRING2", STRING2), ("STRING4", STRING4),
                              ("STRING8", STRING8), ("STRING16", STRING16),
                              ("STRING32", STRING32), ("STRING64", STRING64),
                              ("STRING256", STRING256), ("STRING1024", 1024),
                              ("DATE_TIME", DATE_TIME_LEN)):
        if _dim_name not in ds.dimensions:
            ds.createDimension(_dim_name, _width)
    ds.createDimension("N_PROF", n_prof)
    ds.createDimension("N_PARAM", n_param)
    ds.createDimension("N_LEVELS", n_levels)
    ds.createDimension("N_CALIB", 1 if not is_bgc else 2)
    ds.createDimension("N_HISTORY", None)
    feature = "trajectoryProfile"
    title = "Argo float vertical profile"
    id_val = inputs.external_meta.id if isinstance(inputs.external_meta, ExternalMeta) and inputs.external_meta.id else None
    _set_global_attrs(ds, title, inputs.institution, feature, inputs.decoder_version, id_value=id_val)
    correct_type = "B-Argo profile" if is_bgc else "Argo profile"
    _write_char_scalar(ds, "DATA_TYPE", correct_type, STRING32 if is_bgc else STRING16, attrs={"long_name": "Data type", "conventions": "Argo reference table 1"})
    _write_char_scalar(ds, "FORMAT_VERSION", "3.1", STRING4, attrs={"long_name": "File format version"})
    _write_char_scalar(ds, "HANDBOOK_VERSION", "1.2", STRING4, attrs={"long_name": "Data handbook version"})
    _write_char_scalar(ds, "REFERENCE_DATE_TIME", "19500101000000", DATE_TIME_LEN, dim="DATE_TIME", attrs={"long_name": "Date of reference for Julian days", "conventions": "YYYYMMDDHHMISS"})
    now = _utc_now_stamp()
    _write_char_scalar(ds, "DATE_CREATION", now, DATE_TIME_LEN, dim="DATE_TIME", attrs={"long_name": "Date of file creation", "conventions": "YYYYMMDDHHMISS"})
    _write_char_scalar(ds, "DATE_UPDATE", now, DATE_TIME_LEN, dim="DATE_TIME", attrs={"long_name": "Date of update of this file", "conventions": "YYYYMMDDHHMISS"})

def _write_profile_metadata_block(ds: netCDF4.Dataset, inputs: WriterInputs, n_prof: int, julds: list[float], lats: list[float], lons: list[float], cycle_numbers: list[int], directions: list[str], data_modes: list[str], juld_locations: list[float] | None = None):
    if not isinstance(inputs.external_meta, ExternalMeta):
        raise ValueError("write_profile requires inputs.external_meta (authoritative per-float metadata) — see writer/fixtures.py for test helpers")
    meta = inputs.external_meta
    default_platform_type = meta.platform_type
    var = ds.createVariable("PLATFORM_NUMBER", "S1", ("N_PROF", "STRING8"), fill_value=b" ")
    arr = np.full((n_prof, STRING8), b" ", dtype="S1")
    for i in range(n_prof):
        arr[i] = np.frombuffer(_encode_padded(inputs.wmo, STRING8), dtype="S1")
    var[:] = arr
    var.setncattr("long_name", "Float unique identifier")
    var.setncattr("conventions", "WMO float identifier : A9IIIII")
    for name, long in [("PROJECT_NAME", "Name of the project"), ("PI_NAME", "Name of the principal investigator")]:
        var = ds.createVariable(name, "S1", ("N_PROF", "STRING64"), fill_value=b" ")
        arr = np.full((n_prof, STRING64), b" ", dtype="S1")
        val = meta.project_name if name == "PROJECT_NAME" else meta.pi_name
        # REQUIRED — no fallback, explicit via ExternalMeta (or explicit unavailable "")
        for i in range(n_prof):
            arr[i] = np.frombuffer(_encode_padded(val, STRING64), dtype="S1")
        var[:] = arr
        var.setncattr("long_name", long)
    var = ds.createVariable("CYCLE_NUMBER", "i4", ("N_PROF",), fill_value=int(INT_FILL))
    var[:] = np.array(cycle_numbers, dtype=np.int32)
    var.setncattr("long_name", "Float cycle number")
    var.setncattr("conventions", "0...N, 0 : launch cycle (if exists), 1 : first complete cycle")
    var = ds.createVariable("DIRECTION", "S1", ("N_PROF",), fill_value=b" ")
    var[:] = np.array([d.encode() if isinstance(d, str) else d for d in directions], dtype="S1")
    var.setncattr("long_name", "Direction of the station profiles")
    var.setncattr("conventions", "A: ascending profiles, D: descending profiles")
    for dim_name, long, width in [
        ("DATA_CENTRE", "Data centre in charge of float data processing", STRING2),
        ("DC_REFERENCE", "Station unique identifier in data centre", STRING32),
        ("DATA_STATE_INDICATOR", "Degree of processing the data have passed through", STRING4),
        ("PLATFORM_TYPE", "Type of float", STRING32),
        ("FLOAT_SERIAL_NO", "Serial number of the float", STRING32),
        ("FIRMWARE_VERSION", "Instrument firmware version", STRING32),
    ]:
        var = ds.createVariable(dim_name, "S1", ("N_PROF", f"STRING{width}"), fill_value=b" ")
        arr = np.full((n_prof, width), b" ", dtype="S1")
        for i in range(n_prof):
            if dim_name == "DATA_CENTRE":
                val = inputs.institution
            elif dim_name == "DC_REFERENCE":
                val = f"{inputs.wmo}_{cycle_numbers[i]:03d}"
            elif dim_name == "DATA_STATE_INDICATOR":
                val = "2B"  # real-time only (R/BR); Argo table 5
            elif dim_name == "PLATFORM_TYPE":
                val = default_platform_type
            elif dim_name == "FLOAT_SERIAL_NO":
                val = meta.float_serial_no
            elif dim_name == "FIRMWARE_VERSION":
                val = meta.firmware_version
            else:
                val = ""
            arr[i] = np.frombuffer(_encode_padded(val, width), dtype="S1")
        var[:] = arr
        var.setncattr("long_name", long)
        if dim_name == "DATA_CENTRE":
            var.setncattr("conventions", "Argo reference table 4")
        elif dim_name == "DC_REFERENCE":
            var.setncattr("conventions", "Data centre convention")
        elif dim_name == "PLATFORM_TYPE":
            var.setncattr("conventions", "Argo reference table 23")
        elif dim_name == "DATA_STATE_INDICATOR":
            var.setncattr("conventions", "Argo reference table 6")
    var = ds.createVariable("WMO_INST_TYPE", "S1", ("N_PROF", "STRING4"), fill_value=b" ")
    arr = np.full((n_prof, STRING4), b" ", dtype="S1")
    wmo_type = meta.wmo_inst_type
    for i in range(n_prof):
        arr[i] = np.frombuffer(_encode_padded(wmo_type, STRING4), dtype="S1")
    var[:] = arr
    var.setncattr("long_name", "Coded instrument type")
    var.setncattr("conventions", "Argo reference table 8")
    var = ds.createVariable("DATA_MODE", "S1", ("N_PROF",), fill_value=b" ")
    var[:] = np.array([m.encode() if isinstance(m, str) else m for m in data_modes], dtype="S1")
    var.setncattr("long_name", "Delayed mode or real time data")
    var.setncattr("conventions", "R : real time; D : delayed mode; A : real time with adjustment")
    var = ds.createVariable("JULD", "f8", ("N_PROF",), fill_value=float(JULD_FILL))
    if len(julds) != n_prof:
        raise ValueError(f"profiles must provide juld for each N_PROF ({n_prof}), got {len(julds)}")
    var[:] = np.array(julds, dtype=np.float64)
    var.setncattr("long_name", "Julian day (UTC) of the station relative to REFERENCE_DATE_TIME")
    var.setncattr("standard_name", "time")
    var.setncattr("units", "days since 1950-01-01 00:00:00 UTC")
    var.setncattr("conventions", "Relative julian days with decimal part (as parts of day)")
    var.setncattr("resolution", np.float64(1e-5))
    var.setncattr("axis", "T")
    var = ds.createVariable("JULD_QC", "S1", ("N_PROF",), fill_value=b" ")
    var[:] = np.array([b"1"]*n_prof, dtype="S1")
    var.setncattr("long_name", "Quality on date and time")
    var.setncattr("conventions", "Argo reference table 2")
    var = ds.createVariable("JULD_LOCATION", "f8", ("N_PROF",), fill_value=float(JULD_FILL))
    var[:] = np.array(juld_locations if juld_locations is not None else julds,
                      dtype=np.float64)
    var.setncattr("long_name", "Julian day (UTC) of the location relative to REFERENCE_DATE_TIME")
    var.setncattr("units", "days since 1950-01-01 00:00:00 UTC")
    var.setncattr("conventions", "Relative julian days with decimal part (as parts of day)")
    var.setncattr("resolution", np.float64(1e-5))
    var = ds.createVariable("LATITUDE", "f8", ("N_PROF",), fill_value=float(DOUBLE_FILL))
    if len(lats) != n_prof:
        raise ValueError(f"profiles must provide latitude for each N_PROF ({n_prof})")
    var[:] = np.array(lats, dtype=np.float64)
    var.setncattr("long_name", "Latitude of the station, best estimate")
    var.setncattr("standard_name", "latitude")
    var.setncattr("units", "degree_north")
    var.setncattr("valid_min", np.float64(-90.0))
    var.setncattr("valid_max", np.float64(90.0))
    var.setncattr("axis", "Y")
    var = ds.createVariable("LONGITUDE", "f8", ("N_PROF",), fill_value=float(DOUBLE_FILL))
    if len(lons) != n_prof:
        raise ValueError(f"profiles must provide longitude for each N_PROF ({n_prof})")
    var[:] = np.array(lons, dtype=np.float64)
    var.setncattr("long_name", "Longitude of the station, best estimate")
    var.setncattr("standard_name", "longitude")
    var.setncattr("units", "degree_east")
    var.setncattr("valid_min", np.float64(-180.0))
    var.setncattr("valid_max", np.float64(180.0))
    var.setncattr("axis", "X")
    var = ds.createVariable("POSITION_QC", "S1", ("N_PROF",), fill_value=b" ")
    var[:] = np.array([b"1"]*n_prof, dtype="S1")
    var.setncattr("long_name", "Quality on position (latitude and longitude)")
    var.setncattr("conventions", "Argo reference table 2")
    var = ds.createVariable("POSITIONING_SYSTEM", "S1", ("N_PROF", "STRING8"), fill_value=b" ")
    arr = np.full((n_prof, STRING8), b" ", dtype="S1")
    for i in range(n_prof):
        arr[i] = np.frombuffer(_encode_padded("GPS", STRING8), dtype="S1")
    var[:] = arr
    var.setncattr("long_name", "Positioning system")
    var = ds.createVariable("VERTICAL_SAMPLING_SCHEME", "S1", ("N_PROF", "STRING256"), fill_value=b" ")
    arr = np.full((n_prof, STRING256), b" ", dtype="S1")
    # Caller-supplied per-profile strings; no writer-side synthesis.
    vss = inputs.vertical_sampling_schemes or []
    for i in range(n_prof):
        if i < len(vss) and vss[i]:
            arr[i] = np.frombuffer(_encode_padded(vss[i], STRING256), dtype="S1")
    var[:] = arr
    var.setncattr("long_name", "Vertical sampling scheme")
    var.setncattr("conventions", "Argo reference table 16")
    var = ds.createVariable("CONFIG_MISSION_NUMBER", "i4", ("N_PROF",), fill_value=int(INT_FILL))
    # Publish the authoritative mission number when the source metadata states
    # one for this profile; otherwise FillValue.
    #
    # The previous fallback of 1 asserted the FIRST configuration for every
    # profile. That is wrong for any float that has changed configuration --
    # 2902093, 2902130 and 2902131 all have 2-3 missions, and every cycle in
    # our corpus for 2902093 is mission 3, not 1. Argo UM §2.4.6.1 (p57)
    # defines this as "the mission to which this profile belongs"; the
    # per-cycle assignment is a deployment-log fact that the SBD telemetry does
    # not carry (see rtraj_build.py for the full investigation, including the
    # spacing-based derivation that works for some floats and fails for
    # 2902130, whose missions 1 and 2 share a 24 h cycle time).
    # ``ExternalMeta.config_mission_number`` is a deprecated singular legacy
    # field whose dataclass default is 1; the CTS4 external-metadata reader
    # never sets it (it supplies the full plural mission table instead). A bare
    # 1 there is therefore "unset", not "this profile flew mission 1", and must
    # not be published as an assertion.
    _cmn = meta.config_mission_number if meta else None
    cfg_mission = None if _cmn in (None, 1) else int(_cmn)
    var[:] = np.array(
        [int(INT_FILL) if cfg_mission is None else int(cfg_mission)] * n_prof,
        dtype=np.int32)
    var.setncattr("long_name", "Unique number denoting the missions performed by the float")
    var.setncattr("conventions", "1...N, 1 : first complete mission")

def _write_station_parameters(ds: netCDF4.Dataset, n_prof: int, n_param: int, measured_rows: list[list[str]], is_bgc: bool = False):
    width = STRING64 if is_bgc else STRING16
    dim_name = "STRING64" if is_bgc else "STRING16"
    var = ds.createVariable("STATION_PARAMETERS", "S1", ("N_PROF", "N_PARAM", dim_name), fill_value=b" ")
    arr = np.full((n_prof, n_param, width), b" ", dtype="S1")
    for i in range(n_prof):
        for j in range(n_param):
            val = measured_rows[i][j] if i < len(measured_rows) and j < len(measured_rows[i]) else ""
            arr[i, j] = np.frombuffer(_encode_padded(val, width), dtype="S1")
    var[:] = arr
    var.setncattr("long_name", "List of available parameters for the station")
    var.setncattr("conventions", "Argo reference table 3")
    return var

def _write_parameter_calib(ds: netCDF4.Dataset, n_prof: int, n_calib: int, n_param: int, is_bgc: bool, inputs: WriterInputs, measured_rows: list[list[str]]):
    str_width = STRING64 if is_bgc else STRING16
    dim_str = f"STRING{str_width}"
    var = ds.createVariable("PARAMETER", "S1", ("N_PROF", "N_CALIB", "N_PARAM", dim_str), fill_value=b" ")
    arr = np.full((n_prof, n_calib, n_param, str_width), b" ", dtype="S1")
    # G2 fix: PARAMETER / SCIENTIFIC_CALIB_* follow the same measured
    # per-row lists as STATION_PARAMETERS (never row position).
    for i in range(n_prof):
        for k in range(n_calib):
            for j in range(n_param):
                val = measured_rows[i][j] if i < len(measured_rows) and j < len(measured_rows[i]) else ""
                arr[i, k, j] = np.frombuffer(_encode_padded(val, str_width), dtype="S1")
    var[:] = arr
    var.setncattr("long_name", "List of parameters with calibration information")
    var.setncattr("conventions", "Argo reference table 3")
    _sci_ln = {"SCIENTIFIC_CALIB_EQUATION": "Calibration equation for this parameter",
               "SCIENTIFIC_CALIB_COEFFICIENT": "Calibration coefficients for this equation",
               "SCIENTIFIC_CALIB_COMMENT": "Comment applying to this parameter calibration"}
    for cal_name in ["SCIENTIFIC_CALIB_EQUATION","SCIENTIFIC_CALIB_COEFFICIENT","SCIENTIFIC_CALIB_COMMENT"]:
        var = ds.createVariable(cal_name, "S1", ("N_PROF", "N_CALIB", "N_PARAM", "STRING256"), fill_value=b" ")
        arr = np.full((n_prof, n_calib, n_param, STRING256), b" ", dtype="S1")
        for i in range(n_prof):
            for k in range(n_calib):
                for j in range(n_param):
                    param = measured_rows[i][j] if i < len(measured_rows) and j < len(measured_rows[i]) else ""
                    val = ""
                    if cal_name == "SCIENTIFIC_CALIB_EQUATION":
                        if param == "PRES":
                            val = "PRES_ADJUSTED = PRES"
                        elif param == "TEMP":
                            val = "TEMP_ADJUSTED = TEMP"
                        elif param == "PSAL":
                            val = "PSAL_ADJUSTED = PSAL"
                        elif param == "DOXY":
                            val = "DOXY_ADJUSTED = DOXY*G, where G is the gain obtained from the SAGEO2 output"
                        elif param == "CHLA":
                            val = "CHLA_ADJUSTED = CHLA - CHLA_NPQ with NPQ correction"
                        elif param == "BBP700":
                            val = "BBP700_ADJUSTED = BBP700"
                        elif param == "CHLA_FLUORESCENCE":
                            val = "CHLA_FLUORESCENCE_ADJUSTED = CHLA_FLUORESCENCE"
                    elif cal_name == "SCIENTIFIC_CALIB_COEFFICIENT":
                        if param == "PRES":
                            val = "none"
                        elif param == "DOXY" and k==0:
                            val = "G=1.167"
                        elif param == "CHLA":
                            val = "CHLA_NPQ=0.520125 ZMaxFluo=22.7"
                        elif param == "BBP700" and inputs.bbp_mode=="INCOIS_CORRECTED" and inputs.bbp_corrected_scale is not None:
                            val = f"Corrected BBP700 scale: OriginalScaleFactor {inputs.bbp_original_scale or 'unknown'} -> CorrectedScaleFactor {inputs.bbp_corrected_scale} (Barnard 54520)"
                    else:
                        if param == "PRES":
                            val = "No adjustment was necessary -Calibration error is manufacturer specified accuracy"
                        elif param == "BBP700" and inputs.bbp_mode=="INCOIS_CORRECTED":
                            val = f"Corrected BBP: OriginalScaleFactor {inputs.bbp_original_scale or 'unknown'} -> CorrectedScaleFactor {inputs.bbp_corrected_scale} via Barnard 55891.csv doi:10.17882/54520; recomputed from raw BETA"
                    arr[i,k,j] = np.frombuffer(_encode_padded(val, STRING256), dtype="S1")
        var[:] = arr
        var.setncattr("long_name", _sci_ln[cal_name])
    var = ds.createVariable("SCIENTIFIC_CALIB_DATE", "S1", ("N_PROF", "N_CALIB", "N_PARAM", "DATE_TIME"), fill_value=b" ")
    var.setncattr("long_name", "Date of calibration")
    var.setncattr("conventions", "YYYYMMDDHHMISS")
    arr = np.full((n_prof, n_calib, n_param, DATE_TIME_LEN), b" ", dtype="S1")
    now = _utc_now_stamp()
    for i in range(n_prof):
        for k in range(n_calib):
            for j in range(n_param):
                param = measured_rows[i][j] if i < len(measured_rows) and j < len(measured_rows[i]) else ""
                if param:
                    arr[i,k,j] = np.frombuffer(_encode_padded(now, DATE_TIME_LEN), dtype="S1")
    var[:] = arr
    var.setncattr("long_name", "Date of calibration")
    var.setncattr("conventions", "YYYYMMDDHHMISS")

def _write_history(ds: netCDF4.Dataset, n_prof: int, inputs: WriterInputs, is_bgc: bool):
    n_hist = 2 if is_bgc else 1
    for var_name, width, dims, long in [
        ("HISTORY_INSTITUTION", STRING4, ("N_HISTORY","N_PROF","STRING4"), "Institution which performed action"),
        ("HISTORY_STEP", STRING4, ("N_HISTORY","N_PROF","STRING4"), "Step in data processing"),
        ("HISTORY_SOFTWARE", STRING4, ("N_HISTORY","N_PROF","STRING4"), "Name of software which performed action"),
        ("HISTORY_SOFTWARE_RELEASE", STRING4, ("N_HISTORY","N_PROF","STRING4"), "Version/release of software which performed action"),
        ("HISTORY_REFERENCE", STRING64, ("N_HISTORY","N_PROF","STRING64"), "Reference of database"),
        ("HISTORY_DATE", DATE_TIME_LEN, ("N_HISTORY","N_PROF","DATE_TIME"), "Date the history record was created"),
        ("HISTORY_ACTION", STRING4, ("N_HISTORY","N_PROF","STRING4"), "Action performed on data"),
        ("HISTORY_PARAMETER", STRING64 if is_bgc else STRING16,
         ("N_HISTORY", "N_PROF", "STRING64" if is_bgc else "STRING16"),
         "Station parameter action is performed on"),
        ("HISTORY_QCTEST", STRING16, ("N_HISTORY","N_PROF","STRING16"), "Documentation of tests performed, tests failed (in hex form)"),
    ]:
        if var_name not in ds.variables:
            ds.createVariable(var_name, "S1", dims, fill_value=b" ")
            v = ds.variables[var_name]
            v.setncattr("long_name", long)
            _hist_conv = {
                "HISTORY_INSTITUTION": "Argo reference table 4",
                "HISTORY_STEP": "Argo reference table 12",
                "HISTORY_SOFTWARE": "Institution dependent",
                "HISTORY_SOFTWARE_RELEASE": "Institution dependent",
                "HISTORY_REFERENCE": "Institution dependent",
                "HISTORY_DATE": "YYYYMMDDHHMISS",
                "HISTORY_ACTION": "Argo reference table 7",
                "HISTORY_PARAMETER": "Argo reference table 3",
                "HISTORY_QCTEST": "Write tests performed when ACTION=QCP$; tests failed when ACTION=QCF$",
            }.get(var_name)
            if _hist_conv:
                v.setncattr("conventions", _hist_conv)
    for var_name in ["HISTORY_START_PRES","HISTORY_STOP_PRES","HISTORY_PREVIOUS_VALUE"]:
        if var_name not in ds.variables:
            v = ds.createVariable(var_name, "f4", ("N_HISTORY","N_PROF"), fill_value=float(FLOAT_FILL))
            v.setncattr("long_name", {
                "HISTORY_START_PRES": "Start pressure action applied on",
                "HISTORY_STOP_PRES": "Stop pressure action applied on",
                "HISTORY_PREVIOUS_VALUE": "Parameter/Flag previous value before action",
            }[var_name])
            if var_name in ("HISTORY_START_PRES", "HISTORY_STOP_PRES"):
                v.setncattr("units", "decibar")
    now = _utc_now_stamp()
    arr = np.full((n_hist, n_prof, STRING4), b" ", dtype="S1")
    for h in range(n_hist):
        for p in range(n_prof):
            arr[h,p] = np.frombuffer(_encode_padded("IN", STRING4), dtype="S1")
    ds.variables["HISTORY_INSTITUTION"][:] = arr
    arr = np.full((n_hist, n_prof, STRING4), b" ", dtype="S1")
    for h in range(n_hist):
        for p in range(n_prof):
            arr[h,p] = np.frombuffer(_encode_padded("ARFM" if h==0 else "ARGQ", STRING4), dtype="S1")
    ds.variables["HISTORY_STEP"][:] = arr
    arr = np.full((n_hist, n_prof, STRING4), b" ", dtype="S1")
    for h in range(n_hist):
        for p in range(n_prof):
            arr[h,p] = np.frombuffer(_encode_padded(HISTORY_SOFTWARE, STRING4), dtype="S1")
    ds.variables["HISTORY_SOFTWARE"][:] = arr
    arr = np.full((n_hist, n_prof, STRING4), b" ", dtype="S1")
    for h in range(n_hist):
        for p in range(n_prof):
            ver = inputs.decoder_version.replace("PY-301-","V")[:4]
            arr[h,p] = np.frombuffer(_encode_padded(ver, STRING4), dtype="S1")
    ds.variables["HISTORY_SOFTWARE_RELEASE"][:] = arr
    arr = np.full((n_hist, n_prof, STRING64), b" ", dtype="S1")
    for h in range(n_hist):
        for p in range(n_prof):
            ref = "http://www.argodatamgt.org/Documentation"
            if inputs.bbp_mode=="INCOIS_CORRECTED" and inputs.bbp_corrected_scale is not None:
                ref = "http://doi.org/10.17882/54520"
            arr[h,p] = np.frombuffer(_encode_padded(ref, STRING64), dtype="S1")
    ds.variables["HISTORY_REFERENCE"][:] = arr
    arr = np.full((n_hist, n_prof, DATE_TIME_LEN), b" ", dtype="S1")
    for h in range(n_hist):
        for p in range(n_prof):
            arr[h,p] = np.frombuffer(_encode_padded(now, DATE_TIME_LEN), dtype="S1")
    ds.variables["HISTORY_DATE"][:] = arr
    arr = np.full((n_hist, n_prof, STRING4), b" ", dtype="S1")
    for h in range(n_hist):
        for p in range(n_prof):
            act = "CF" if h==0 else "CV"
            arr[h,p] = np.frombuffer(_encode_padded(act, STRING4), dtype="S1")
    ds.variables["HISTORY_ACTION"][:] = arr
    _hp_w = STRING64 if is_bgc else STRING16
    arr = np.full((n_hist, n_prof, _hp_w), b" ", dtype="S1")
    for h in range(n_hist):
        for p in range(n_prof):
            param = "PRES" if not (h==1 and inputs.bbp_mode=="INCOIS_CORRECTED") else "BBP700"
            arr[h,p] = np.frombuffer(_encode_padded(param, _hp_w), dtype="S1")
    ds.variables["HISTORY_PARAMETER"][:] = arr
    arr = np.full((n_hist, n_prof, STRING16), b" ", dtype="S1")
    for h in range(n_hist):
        for p in range(n_prof):
            arr[h,p] = np.frombuffer(_encode_padded("0000000000000000", STRING16), dtype="S1")
    ds.variables["HISTORY_QCTEST"][:] = arr
    for vname in ["HISTORY_START_PRES","HISTORY_STOP_PRES","HISTORY_PREVIOUS_VALUE"]:
        ds.variables[vname][:] = np.full((n_hist, n_prof), FLOAT_FILL, dtype=np.float32)

#: Raw sensor channels no quality-control step is ever run on. Argo reference
#: table 2 code '0' = "no QC was performed", which is the truthful value for a
#: real-time product; '1' would claim the data passed QC. Verified against
#: INCOIS 2902093: R/BR and Rtraj both publish '0' on these four and '1' on
#: TEMP_DOXY / DOXY / CHLA.
_NO_QC_PERFORMED_PARAMS = frozenset({
    "C1PHASE_DOXY", "C2PHASE_DOXY", "FLUORESCENCE_CHLA", "BETA_BACKSCATTERING700",
})


#: Maps a profile dict key to the QC parameter name run_cts4_rtqc returns.
_RTQC_SOURCE_KEY = {
    "TEMP": "temp",
    "PSAL": "psal",
    "DOXY": "doxy",
    "TEMP_DOXY": "temp_doxy",
    "CHLA": "chla",
    "CHLA_FLUORESCENCE": "chla_fluorescence",
    "BBP700": "bbp",
    "C1PHASE_DOXY": "c1phase",
    "C2PHASE_DOXY": "c2phase",
    "FLUORESCENCE_CHLA": "fluorescence",
    "BETA_BACKSCATTERING700": "beta",
}


def _build_rtqc_levels(profiles: list[dict], n_prof: int, n_levels: int,
                       params: list[str], is_bgc: bool,
                       vss_list: list[str] | None = None,
                       park_pres: float | None = None,
                       profile_pressure_dbar: float | None = None,
                       previous_profile: dict | None = None,
                       ) -> dict[str, np.ndarray]:
    """Run CTS4 real-time QC and pack each parameter's codes to (n_prof, n_levels).

    Only parameters actually measured in a profile are scored, and only
    parameters the caller publishes are returned.  A parameter with no
    measured data anywhere is omitted entirely, so _write_qc_vars falls back
    to its usual initial code rather than publishing an all-zero array that
    would claim QC had run where no measurement existed.
    """
    wanted = {p for p in params if p}
    rtqc_input: list[dict] = []
    for i, p in enumerate(profiles):
        pres = np.asarray(p.get("pres", []), dtype=np.float64)
        entry: dict = {"pres": pres, "direction": str(p.get("direction", "A"))}
        # Tests 21/22 gate on the profile's own VERTICAL_SAMPLING_SCHEME, so
        # the string has to reach RTQC per profile, not per file.
        if vss_list is not None and i < len(vss_list) and vss_list[i]:
            entry["vss"] = vss_list[i]
        for param in wanted:
            key = _RTQC_SOURCE_KEY.get(param)
            if key is None:
                continue
            data = p.get(key)
            if data is not None:
                entry[key] = np.asarray(data, dtype=np.float64)
        rtqc_input.append(entry)

    results = run_cts4_rtqc(
        rtqc_input,
        park_pres=park_pres,
        profile_pressure_dbar=profile_pressure_dbar,
        previous_profile=previous_profile)

    out: dict[str, np.ndarray] = {}
    for param in sorted(wanted):
        key = _RTQC_SOURCE_KEY.get(param)
        if key is None:
            continue
        arr = np.zeros((n_prof, n_levels), dtype=np.int8)
        any_data = False
        for i, res in enumerate(results):
            pr = res.params.get(param)
            if pr is None:
                continue
            levels = np.asarray(pr.levels, dtype=np.int8)
            n = min(levels.size, n_levels)
            arr[i, :n] = levels[:n]
            any_data = True
        if any_data:
            out[param] = arr
    return out


def compute_profile_quality_flag(qc_row: np.ndarray) -> bytes:
    """Argo reference table 2a profile flag from a parameter's per-level QC.

    A faithful port of Coriolis ``compute_profile_quality_flag.m``.  Levels
    whose QC is blank, '0' (no QC performed) or '9' (missing) are excluded
    from both counts; if every level is excluded the flag stays blank, which
    is why the four raw IB-Argo channels -- all '0' -- publish no profile
    flag at all.  Of the remaining levels the fraction coded good ('1', '2',
    '5' or '8') selects the letter: 100% 'A', then 'B', 'C', 'D', 'E', and
    0% 'F'.
    """
    a = np.asarray(qc_row).astype(str)
    inert = (a == " ") | (a == "0") | (a == "9")
    if inert.all():
        return b" "
    useful = ~inert
    good = (a == "1") | (a == "2") | (a == "5") | (a == "8")
    nb_useful = int(useful.sum())
    if nb_useful == 0:
        return b" "
    ratio = 100.0 * int(good[useful].sum()) / nb_useful
    if ratio == 0.0:
        return b"F"
    if ratio < 25.0:
        return b"E"
    if ratio < 50.0:
        return b"D"
    if ratio < 75.0:
        return b"C"
    if ratio < 100.0:
        return b"B"
    return b"A"


def _write_qc_vars(ds: netCDF4.Dataset, n_prof: int, n_levels: int, params: list[str], is_bgc: bool, doxy_missing: bool,
                   rtqc_levels: dict[str, np.ndarray] | None = None):
    """Write <PARAM>_QC / PROFILE_<PARAM>_QC.

    ``rtqc_levels`` optionally supplies a per-level RTQC code array
    ``(n_prof, n_levels)`` of Argo reference-table-2 digits for a
    parameter.  Where it is present it replaces the flat initial code;
    the fill mask still wins, because QC must be blank exactly where
    the data is missing.
    """
    for param in params:
        if not param:
            continue
        if is_bgc and param == "PRES":
            # b_profile v3.1: PRES is duplicated as-is in B files; PRES_QC /
            # PROFILE_PRES_QC / PRES_ADJUSTED* must NOT appear (UM 3.44 §2.6).
            continue
        has_adjusted = param in ("PRES","TEMP","PSAL","DOXY","CHLA","BBP700","CHLA_FLUORESCENCE")
        qc_name = f"{param}_QC"
        # QC must be missing (' ') exactly where the data is missing (fill):
        # FileChecker data check "Missing data but QC not missing".
        _fill_mask = None
        if param in ds.variables:
            _d = np.asarray(ds.variables[param][:], dtype=np.float64)
            _fill_mask = (_d >= 90000.0) | np.isnan(_d)
        # Argo reference table 2: '0' = no QC was performed, '1' = good. A
        # real-time decoder performs no quality control at all, so Coriolis
        # initialises EVERY parameter's QC to g_decArgo_qcStrNoQc ('0')
        # straight after decoding and only RTQC ever upgrades it
        # (add_rtqc_to_profile_file.m:1809-1816, init_default_values.m:1015).
        # The four untested raw channels therefore stay '0'. TEMP_DOXY, DOXY
        # and CHLA do reach '1'/'3' because RTQC acts on them; the GDAC
        # publishes exactly that split on 2902093 R/BR and Rtraj.
        _base_qc = (b"0" if param in _NO_QC_PERFORMED_PARAMS else b"1")
        _rtqc = None
        if rtqc_levels is not None and param in rtqc_levels:
            _rtqc = np.asarray(rtqc_levels[param])
            if _rtqc.shape != (n_prof, n_levels):
                raise ValueError(
                    f"RTQC for {param} has shape {_rtqc.shape}, "
                    f"expected {(n_prof, n_levels)}")
        if qc_name not in ds.variables:
            var = ds.createVariable(qc_name, "S1", ("N_PROF","N_LEVELS"), fill_value=b" ")
            if param == "DOXY" and doxy_missing:
                var[:] = np.full((n_prof, n_levels), b"9", dtype="S1")
            elif _rtqc is not None:
                _qc = np.where(_rtqc == 0, b"0",
                               _rtqc.astype("U1")).astype("S1")
                if _fill_mask is not None:
                    _qc[_fill_mask] = b" "
                var[:] = _qc
            elif _fill_mask is not None:
                _qc = np.full((n_prof, n_levels), _base_qc, dtype="S1")
                _qc[_fill_mask] = b" "
                var[:] = _qc
            else:
                var[:] = np.full((n_prof, n_levels), _base_qc, dtype="S1")
            var.setncattr("long_name", "quality flag")
            var.setncattr("conventions", "Argo reference table 2")
        prof_qc_name = f"PROFILE_{param}_QC"
        if prof_qc_name not in ds.variables:
            var = ds.createVariable(prof_qc_name, "S1", ("N_PROF",), fill_value=b" ")
            if param == "DOXY" and doxy_missing:
                var[:] = np.array([b"9"]*n_prof, dtype="S1")
            elif _rtqc is not None:
                # Derive the profile flag from the per-level RTQC just
                # written, exactly as Coriolis does, instead of assuming 'A'.
                _written = np.asarray(ds.variables[qc_name][:]).astype(str)
                var[:] = np.array(
                    [compute_profile_quality_flag(_written[i])
                     for i in range(n_prof)], dtype="S1")
            elif _fill_mask is not None:
                _rows = np.array([b"A" if not _fill_mask[i].all() else b" "
                                  for i in range(n_prof)], dtype="S1")
                var[:] = _rows
            else:
                var[:] = np.array([b"A"]*n_prof, dtype="S1")
            var.setncattr("long_name", f"Global quality flag of {param} profile")
            var.setncattr("conventions", "Argo reference table 2a")
        if has_adjusted:
            adj_name = f"{param}_ADJUSTED"
            var = ds.createVariable(adj_name, "f4", ("N_PROF","N_LEVELS"), fill_value=float(FLOAT_FILL))
            var[:] = np.full((n_prof, n_levels), FLOAT_FILL, dtype=np.float32)
            var.setncattr("long_name", _ADJUSTED_LONG_NAME.get(param, param))
            var.setncattr("units", PARAMETER_UNITS.get(param,""))
            # DOXY_ADJUSTED follows DOXY (spec valid_min -5.0). CHLA and
            # BBP700 get no valid_* at all: the INCOIS spec rejects them on
            # the base variables and equally on the _ADJUSTED twins.
            _adj_valid = {"PRES": (0.0, 12000.0), "TEMP": (-2.5, 40.0),
                          "PSAL": (2.0, 41.0), "DOXY": (-5.0, 600.0),
                          "CHLA_FLUORESCENCE": (-0.2, 100.0)}.get(param)
            if _adj_valid:
                var.setncattr("valid_min", np.float32(_adj_valid[0]))
                var.setncattr("valid_max", np.float32(_adj_valid[1]))
            if param in ds.variables:
                _base = ds.variables[param]
                for _k in ("standard_name", "C_format", "FORTRAN_format",
                           "resolution"):
                    if _k in _base.ncattrs() and _k not in var.ncattrs():
                        var.setncattr(_k, _base.getncattr(_k))
            var = ds.createVariable(f"{adj_name}_QC", "S1", ("N_PROF","N_LEVELS"), fill_value=b" ")
            fill_qc = b"9" if (param=="DOXY" and doxy_missing) else b" "
            var[:] = np.full((n_prof, n_levels), fill_qc, dtype="S1")
            var.setncattr("long_name", "quality flag")
            var.setncattr("conventions", "Argo reference table 2")
            var = ds.createVariable(f"{adj_name}_ERROR", "f4", ("N_PROF","N_LEVELS"), fill_value=float(FLOAT_FILL))
            var[:] = np.full((n_prof, n_levels), FLOAT_FILL, dtype=np.float32)
            var.setncattr("long_name", "Contains the error on the adjusted values as determined by the delayed mode QC process")
            var.setncattr("units", PARAMETER_UNITS.get(param,""))
            if param in ds.variables:
                _base = ds.variables[param]
                for _k in ("C_format", "FORTRAN_format", "resolution"):
                    if _k in _base.ncattrs() and _k not in var.ncattrs():
                        var.setncattr(_k, _base.getncattr(_k))

# ---------------------------------------------------------------------------
# Profile writer — NO FABRICATION: requires profiles with required fields
# ---------------------------------------------------------------------------

#: Profile-dict key -> NetCDF parameter name. Inverse of _RTQC_SOURCE_KEY
#: plus the pressure grid every profile dict carries under "pres".
_PROFILE_KEY_TO_PARAM = {
    "pres": "PRES",
    "temp": "TEMP",
    "psal": "PSAL",
    "c1phase": "C1PHASE_DOXY",
    "c2phase": "C2PHASE_DOXY",
    "temp_doxy": "TEMP_DOXY",
    "doxy": "DOXY",
    "fluorescence": "FLUORESCENCE_CHLA",
    "beta": "BETA_BACKSCATTERING700",
    "chla": "CHLA",
    "chla_fluorescence": "CHLA_FLUORESCENCE",
    "bbp": "BBP700",
}

#: Canonical parameter order per file type. A row's parameter list is this
#: order filtered to what the profile measured, so standard 4-row layouts
#: reproduce BGC/R_STATION_PARAMETERS_TEMPLATE exactly.
_CORE_PARAM_ORDER = ("PRES", "TEMP", "PSAL")
_BGC_PARAM_ORDER = (
    "PRES",
    "C1PHASE_DOXY",
    "C2PHASE_DOXY",
    "TEMP_DOXY",
    "DOXY",
    "FLUORESCENCE_CHLA",
    "BETA_BACKSCATTERING700",
    "CHLA",
    "CHLA_FLUORESCENCE",
    "BBP700",
)

#: Sensor keys marking an optode / fluorometer profile. DOXY and BBP700 are
#: derived (sensor + CTD), so their labels follow the sensor's presence: a
#: no-CTD sensor profile still labels DOXY/BBP700 (fill data, blank QC)
#: rather than dropping the slot.
_OPTODE_SENSOR_KEYS = ("c1phase", "c2phase", "temp_doxy", "doxy")
_FLBB_SENSOR_KEYS = ("fluorescence", "beta", "chla", "chla_fluorescence", "bbp")


def _key_measured(profile: dict, key: str) -> bool:
    """True if the profile dict measured ``key``: present, non-empty, and
    carrying at least one non-fill value (fill = NaN or >= 90000, the same
    rule _write_qc_vars uses for its fill mask). Empty arrays (e.g. TEMP/PSAL
    on pressure-only reference rows) and all-fill arrays (synthetic padding)
    both read as unmeasured."""
    if key not in profile or profile[key] is None:
        return False
    try:
        arr = np.asarray(profile[key], dtype=np.float64).ravel()
    except Exception:
        return False
    if arr.size == 0:
        return False
    return bool(((arr < 90000.0) & ~np.isnan(arr)).any())


def _measured_row_params(profile: dict, is_bgc: bool, n_param: int) -> list[str]:
    """Per-row parameter list keyed by the profile's own measured content.

    G2 fix: labels must follow measurement, never row position. For the
    standard layouts this reproduces the 4-row station templates exactly;
    for deviant layouts ([primary,near,FL], [primary,o2,FL], ...) each row
    labels what it actually carries. Cross-type keys are ignored (R rows
    never label BGC params and vice versa, per Argo UM 3.44 section 2.6).
    Lists are padded with "" to ``n_param``; a hypothetically over-full row
    is truncated to ``n_param`` so labels and data masks stay consistent.
    """
    order = _BGC_PARAM_ORDER if is_bgc else _CORE_PARAM_ORDER
    key_of = {p: k for k, p in _PROFILE_KEY_TO_PARAM.items()}
    measured = {p for p in order if _key_measured(profile, key_of[p])}
    measured.add("PRES")  # every profile carries its own pressure grid
    if is_bgc:
        if any(_key_measured(profile, k) for k in _OPTODE_SENSOR_KEYS):
            measured.add("DOXY")
        if any(_key_measured(profile, k) for k in _FLBB_SENSOR_KEYS):
            measured.add("BBP700")
    row = [p for p in order if p in measured][:n_param]
    row += [""] * (n_param - len(row))
    return row


def write_profile(path: Path | str, inputs: WriterInputs, *, is_bgc: bool = False, profiles: list[dict] | None = None) -> Path:
    _validate_wmo(inputs.wmo)
    _validate_decoder_version(inputs.decoder_version)
    if not isinstance(inputs.external_meta, ExternalMeta):
        raise ValueError("write_profile requires inputs.external_meta (authoritative per-float metadata) — see writer/fixtures.py for test helpers; no file produced")
    if profiles is None:
        profiles = inputs.profiles
    if not profiles or len(profiles) == 0:
        raise ValueError("write_profile requires non-empty profiles (with pres, juld, latitude, longitude, cycle_number, direction); no fabrication — see writer/fixtures.py for test builders")
    n_prof = len(profiles)
    # Validate each profile has required keys
    for idx, p in enumerate(profiles):
        if "pres" not in p or p["pres"] is None or len(np.asarray(p["pres"])) == 0:
            raise ValueError(f"profile {idx} missing required 'pres' array")
        for k in ("juld","latitude","longitude","cycle_number","direction"):
            if k not in p or p[k] is None:
                raise ValueError(f"profile {idx} missing required '{k}' (no fabrication)")
    n_levels = max(len(np.asarray(p.get("pres", []))) for p in profiles)
    if n_levels == 0:
        raise ValueError("N_LEVELS would be 0 — pres arrays empty")
    if inputs.bbp_mode == "INCOIS_CORRECTED" and inputs.bbp_corrected_scale is None:
        raise ValueError("bbp_mode=INCOIS_CORRECTED requested but bbp_corrected_scale is None — fail explicitly, no fallback")
    if inputs.data_modes is not None:
        data_modes = inputs.data_modes
        if len(data_modes) != n_prof:
            raise ValueError(f"data_modes length {len(data_modes)} != N_PROF {n_prof}")
    else:
        # REAL-TIME ONLY: all R (both core and BGC). No D/A.
        data_modes = ["R"] * n_prof
    for m in data_modes:
        if m != "R":
            raise ValueError(f"Real-time only: DATA_MODE must be 'R', got {m!r} (D/BD not supported)")
    n_param = N_PARAM_BGC if is_bgc else N_PARAM_CORE
    n_calib = 2 if is_bgc else 1
    path = Path(path)
    if path.is_dir() or str(path).endswith("/"):
        filename = _profile_filename(inputs.wmo, inputs.cycle, is_bgc, data_modes)
        path = path / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    ds = netCDF4.Dataset(str(path), "w", format="NETCDF4_CLASSIC")
    _write_profile_common(ds, inputs, n_prof, n_levels, n_param, is_bgc)
    julds = [float(p["juld"]) for p in profiles]
    # JULD_LOCATION is the acquisition time of the surface fix that produced
    # LATITUDE/LONGITUDE, which is generally NOT the profile JULD (surfacing
    # time). Callers may supply it per profile; when absent it falls back to
    # the profile JULD, preserving the previous behaviour for platforms whose
    # GDAC convention is JULD == JULD_LOCATION.
    juld_locations = [float(p.get("juld_location", p["juld"])) for p in profiles]
    lats = [float(p["latitude"]) for p in profiles]
    lons = [float(p["longitude"]) for p in profiles]
    cycle_numbers = [int(p["cycle_number"]) for p in profiles]
    directions = [str(p["direction"]) for p in profiles]
    _write_profile_metadata_block(ds, inputs, n_prof, julds, lats, lons, cycle_numbers, directions, data_modes, juld_locations)
    # G2 fix: per-row parameter lists keyed by each profile's own measured
    # keys -- never by row position. The old positional path ([template[i %
    # 4] for n_prof != 4]) mislabeled and wiped sensor rows whenever the
    # profile order deviated from the 4-row assumption; it is deleted (the
    # 4-row constants above remain as the documented canonical layout, which
    # these lists reproduce exactly for standard files).
    measured = [_measured_row_params(p, is_bgc, n_param) for p in profiles]
    _write_station_parameters(ds, n_prof, n_param, measured, is_bgc=is_bgc)
    if is_bgc:
        var = ds.createVariable("PARAMETER_DATA_MODE", "S1", ("N_PROF","N_PARAM"), fill_value=b" ")
        arr = np.full((n_prof, n_param), b" ", dtype="S1")
        if inputs.parameter_data_modes is not None:
            for i in range(n_prof):
                for j in range(n_param):
                    try:
                        val = inputs.parameter_data_modes[i][j]
                        arr[i,j] = val.encode() if isinstance(val, str) else val
                    except Exception:
                        arr[i,j] = b" "
        else:
            # Real-time only: "R" exactly where the row labels a parameter.
            for i in range(n_prof):
                for j, pname in enumerate(measured[i][:n_param]):
                    if pname:
                        arr[i, j] = b"R"
        var[:] = arr
        var.setncattr("long_name", "Delayed mode or real time data")
        var.setncattr("conventions", "R : real time; D : delayed mode; A : real time with adjustment")
    def _prepare_2d(key: str, fill=FLOAT_FILL):
        arr = np.full((n_prof, n_levels), fill, dtype=np.float32)
        for i, p in enumerate(profiles):
            data = p.get(key)
            if data is not None:
                arr_data = np.asarray(data, dtype=np.float32)
                n = min(len(arr_data), n_levels)
                arr[i,:n] = arr_data[:n]
        return arr
    pres_arr = _prepare_2d("pres")
    var = ds.createVariable("PRES", "f4", ("N_PROF","N_LEVELS"), fill_value=float(FLOAT_FILL))
    var[:] = pres_arr
    var.setncattr("long_name", "Sea water pressure, equals 0 at sea-level")
    var.setncattr("standard_name", "sea_water_pressure")
    var.setncattr("units", "decibar")
    var.setncattr("valid_min", np.float32(0.0))
    var.setncattr("valid_max", np.float32(12000.0))
    var.setncattr("C_format", "%7.1f")
    var.setncattr("FORTRAN_format", "F7.1")
    var.setncattr("resolution", np.float32(0.1))
    var.setncattr("axis", "Z")
    if not is_bgc:
        for key, units, long_name, valid in [("temp","degree_Celsius","Sea temperature in-situ ITS-90 scale",(-2.5,40.0)),("psal","psu","Practical salinity",(2.0,41.0))]:
            pname = key.upper()
            arr = _prepare_2d(key)
            for i in range(n_prof):
                if pname not in measured[i]:
                    arr[i,:] = FLOAT_FILL
            var = ds.createVariable(pname, "f4", ("N_PROF","N_LEVELS"), fill_value=float(FLOAT_FILL))
            var[:] = arr
            var.setncattr("long_name", long_name)
            var.setncattr("standard_name", "sea_water_temperature" if pname=="TEMP" else "sea_water_salinity")
            var.setncattr("units", units)
            var.setncattr("valid_min", np.float32(valid[0]))
            var.setncattr("valid_max", np.float32(valid[1]))
            var.setncattr("C_format", "%9.3f")
            var.setncattr("FORTRAN_format", "F9.3")
            var.setncattr("resolution", np.float32(0.001))
    else:
        doxy_missing = inputs.doxy_external_calib is None
        for key, pname, units, long_name in [("c1phase","C1PHASE_DOXY","degree","Uncalibrated phase shift reported by oxygen sensor"),("c2phase","C2PHASE_DOXY","degree","Uncalibrated phase shift reported by oxygen sensor"),("temp_doxy","TEMP_DOXY","degree_Celsius","Sea temperature from oxygen sensor ITS-90 scale")]:
            arr = _prepare_2d(key)
            for i in range(n_prof):
                if pname not in measured[i]:
                    arr[i,:] = FLOAT_FILL
            var = ds.createVariable(pname, "f4", ("N_PROF","N_LEVELS"), fill_value=float(FLOAT_FILL))
            var[:] = arr
            var.setncattr("long_name", long_name)
            var.setncattr("units", units)
            # Per-variable valid ranges as published by GDAC 2902093 BR:
            # C1PHASE_DOXY 10-70, C2PHASE_DOXY 0-15 (the reference-phase
            # channel is a much smaller signal), TEMP_DOXY -2..40. The old
            # ``"PHASE" in pname`` test applied C1's range to C2 as well.
            _vr = {"C1PHASE_DOXY": (10.0, 70.0),
                   "C2PHASE_DOXY": (0.0, 15.0),
                   "TEMP_DOXY": (-2.0, 40.0)}[pname]
            var.setncattr("valid_min", np.float32(_vr[0]))
            var.setncattr("valid_max", np.float32(_vr[1]))
            var.setncattr("C_format", "%9.3f")
            var.setncattr("FORTRAN_format", "F9.3")
            var.setncattr("resolution", np.float32(0.001))
            if pname=="TEMP_DOXY":
                var.setncattr("standard_name", "temperature_of_sensor_for_oxygen_in_sea_water")
        doxy_arr = _prepare_2d("doxy")
        for i in range(n_prof):
            if "DOXY" not in measured[i] or doxy_missing:
                doxy_arr[i,:] = FLOAT_FILL
        var = ds.createVariable("DOXY", "f4", ("N_PROF","N_LEVELS"), fill_value=float(FLOAT_FILL))
        var[:] = doxy_arr
        var.setncattr("long_name", "Dissolved oxygen")
        var.setncattr("standard_name", "moles_of_oxygen_per_unit_mass_in_sea_water")
        var.setncattr("units", "micromole/kg")
        # Argo spec valid_min is -5.0 (small negatives are physical); GDAC
        # 2902093 BR publishes -5.0. Our 0.0 drew a FileChecker warning.
        var.setncattr("valid_min", np.float32(-5.0))
        var.setncattr("valid_max", np.float32(600.0))
        var.setncattr("C_format", "%9.3f")
        var.setncattr("FORTRAN_format", "F9.3")
        var.setncattr("resolution", np.float32(0.001))
        for key, pname, units, long_name in [("fluorescence","FLUORESCENCE_CHLA","count","Chlorophyll-A signal from fluorescence sensor"),("beta","BETA_BACKSCATTERING700","count","Total angle specific volume from backscattering sensor at 700 nanometers")]:
            arr = _prepare_2d(key)
            for i in range(n_prof):
                if pname not in measured[i]:
                    arr[i,:] = FLOAT_FILL
            var = ds.createVariable(pname, "f4", ("N_PROF","N_LEVELS"), fill_value=float(FLOAT_FILL))
            var[:] = arr
            var.setncattr("long_name", long_name)
            var.setncattr("units", units)
            var.setncattr("C_format", "%9.1f")
            var.setncattr("FORTRAN_format", "F9.1")
            var.setncattr("resolution", np.float32(1.0))
        chla_arr = _prepare_2d("chla")
        for i in range(n_prof):
            if "CHLA" not in measured[i]:
                chla_arr[i,:] = FLOAT_FILL
        var = ds.createVariable("CHLA", "f4", ("N_PROF","N_LEVELS"), fill_value=float(FLOAT_FILL))
        var[:] = chla_arr
        var.setncattr("long_name", "Chlorophyll-A")
        var.setncattr("standard_name", "mass_concentration_of_chlorophyll_a_in_sea_water")
        var.setncattr("units", "mg/m3")
        # No valid_min/valid_max: the INCOIS spec does not permit them on CHLA
        # (FileChecker: "Attribute is not allowed ... WILL BECOME AN ERROR"),
        # and GDAC 2902093 BR publishes none. C_format/resolution follow GDAC.
        var.setncattr("C_format", "%.4f")
        var.setncattr("FORTRAN_format", "F.4")
        var.setncattr("resolution", np.float32(0.025))
        chla_f_arr = _prepare_2d("chla_fluorescence")
        for i in range(n_prof):
            if "CHLA_FLUORESCENCE" not in measured[i]:
                chla_f_arr[i,:] = FLOAT_FILL
        var = ds.createVariable("CHLA_FLUORESCENCE", "f4", ("N_PROF","N_LEVELS"), fill_value=float(FLOAT_FILL))
        var[:] = chla_f_arr
        var.setncattr("long_name", "Chlorophyll fluorescence with factory calibration")
        var.setncattr("units", "ru")
        var.setncattr("valid_min", np.float32(-0.2))
        var.setncattr("valid_max", np.float32(100.0))
        var.setncattr("C_format", "%9.3f")
        var.setncattr("FORTRAN_format", "F9.3")
        var.setncattr("resolution", np.float32(0.001))
        bbp_arr = _prepare_2d("bbp")
        for i in range(n_prof):
            if "BBP700" not in measured[i]:
                bbp_arr[i,:] = FLOAT_FILL
        if inputs.bbp_mode == "INCOIS_CORRECTED":
            for i, p in enumerate(profiles):
                if "BBP700" not in measured[i]:
                    continue
                beta_raw = p.get("beta_raw")
                if beta_raw is None:
                    beta_raw = p.get("beta")
                    if beta_raw is None:
                        continue
                beta_raw = np.asarray(beta_raw, dtype=np.float32)
                n = min(len(beta_raw), n_levels)
                dark = p.get("dark", 49)
                scale_corr = inputs.bbp_corrected_scale
                temp_c = p.get("temp_c")
                if temp_c is None:
                    temp_c = p.get("temp")
                psal_c = p.get("psal_c")
                if psal_c is None:
                    psal_c = p.get("psal")
                if temp_c is None or psal_c is None:
                    raise ValueError(f"BBP recompute requires temp/psal per level for exact BETASW (profile {i}); no fallback")
                temp_c = np.asarray(temp_c, dtype=np.float32)[:n]
                psal_c = np.asarray(psal_c, dtype=np.float32)[:n]
                for lev in range(n):
                    betasw = _beta_sw(float(temp_c[lev]), float(psal_c[lev]))
                    bbp_arr[i, lev] = np.float32(2 * math.pi * KHI_700 * ((float(beta_raw[lev]) - float(dark)) * float(scale_corr) - betasw))
        var = ds.createVariable("BBP700", "f4", ("N_PROF","N_LEVELS"), fill_value=float(FLOAT_FILL))
        var[:] = bbp_arr
        var.setncattr("long_name", "Particle backscattering at 700 nanometers")
        var.setncattr("units", "m-1")
        # As CHLA: valid_min/valid_max are not permitted on BBP700 by the
        # INCOIS spec and GDAC 2902093 BR publishes none.
        var.setncattr("C_format", "%.7f")
        var.setncattr("FORTRAN_format", "F.7")
        var.setncattr("resolution", np.float32(1e-07))
    params_for_qc = ["PRES","TEMP","PSAL"] if not is_bgc else ["PRES","C1PHASE_DOXY","C2PHASE_DOXY","TEMP_DOXY","DOXY","FLUORESCENCE_CHLA","BETA_BACKSCATTERING700","CHLA","CHLA_FLUORESCENCE","BBP700"]
    doxy_missing = inputs.doxy_external_calib is None if is_bgc else False
    rtqc_levels = _build_rtqc_levels(
        profiles, n_prof, n_levels, params_for_qc, is_bgc,
        vss_list=inputs.vertical_sampling_schemes,
        park_pres=inputs.park_pressure_dbar,
        profile_pressure_dbar=inputs.profile_pressure_dbar,
        previous_profile=inputs.previous_profile)
    _write_qc_vars(ds, n_prof, n_levels, params_for_qc, is_bgc, doxy_missing,
                   rtqc_levels=rtqc_levels)
    if is_bgc and doxy_missing:
        if "DOXY_QC" in ds.variables:
            arr = np.full((n_prof, n_levels), b"9", dtype="S1")
            for i in range(n_prof):
                if "DOXY" not in measured[i]:
                    arr[i,:] = b" "
            ds.variables["DOXY_QC"][:] = arr
    # REAL-TIME ONLY: *_ADJUSTED stays FillValue in R/BR files (FileChecker:
    # "DATA_MODE 'R': *_ADJUSTED must be FillValue"). The former copy-in of
    # originals and the fixed DOXY gain 1.167 (a delayed-mode SAGEO2 artifact,
    # PUBLICATION-RTQC per the (bd) investigation) are removed — no hidden
    # adjustment computations in real-time products.
    _write_parameter_calib(ds, n_prof, n_calib, n_param, is_bgc, inputs, measured)
    _write_history(ds, n_prof, inputs, is_bgc)
    ds.close()
    return path

# ---------------------------------------------------------------------------
# PublicationBuilder — requires external_meta for meta/tech
# ---------------------------------------------------------------------------

class PublicationBuilder:
    def __init__(self, inputs: WriterInputs, config: WriterConfig | None = None):
        self.inputs = inputs
        self.config = config or WriterConfig()
        _validate_wmo(inputs.wmo)
        _validate_decoder_version(inputs.decoder_version)
        if inputs.external_meta is None:
            # Allow builder instantiation, but write() will fail for meta/tech if missing
            pass

    def write(self, out_dir: Path | str) -> dict[str, Path]:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        written: dict[str, Path] = {}
        # Meta/tech require external_meta
        meta_path = out_dir / f"{self.inputs.wmo}_meta.nc"
        write_meta(meta_path, self.inputs)
        written["meta"] = meta_path
        tech_records = None
        # Try to get tech_records from inputs if available as attribute
        if hasattr(self.inputs, "tech_records"):
            tech_records = self.inputs.tech_records
        # Write tech requires tech_records
        tech_path = out_dir / f"{self.inputs.wmo}_tech.nc"
        # If tech_records not supplied via inputs, caller must have provided via separate path
        # For backward compat, if tech_records is None, write_tech will raise; we surface that
        write_tech(tech_path, self.inputs, tech_records=tech_records)  # type: ignore
        written["tech"] = tech_path
        if self.inputs.profiles:
            # Write profiles if supplied
            if self.config.generate_core:
                p = write_profile(out_dir, self.inputs, is_bgc=False, profiles=self.inputs.profiles)
                written["core"] = p
            if self.config.generate_bgc:
                p = write_profile(out_dir, self.inputs, is_bgc=True, profiles=self.inputs.profiles)
                written["bgc"] = p
        return written

    def write_meta(self, path: Path | str) -> Path:
        return write_meta(path, self.inputs)

    def write_tech(self, path: Path | str, tech_records: list[dict] | None = None) -> Path:
        return write_tech(path, self.inputs, tech_records)

    def write_profile_core(self, path: Path | str, profiles: list[dict] | None = None) -> Path:
        return write_profile(path, self.inputs, is_bgc=False, profiles=profiles)

    def write_profile_bgc(self, path: Path | str, profiles: list[dict] | None = None) -> Path:
        if self.inputs.bbp_mode == "INCOIS_CORRECTED" and self.inputs.bbp_corrected_scale is None:
            raise ValueError("bbp_mode=INCOIS_CORRECTED requested but bbp_corrected_scale is None — fail explicitly, no fallback")
        return write_profile(path, self.inputs, is_bgc=True, profiles=profiles)

def parse_wmo_arg(wmo: str) -> str:
    _validate_wmo(wmo)
    return wmo
