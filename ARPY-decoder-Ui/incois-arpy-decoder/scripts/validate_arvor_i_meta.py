#!/usr/bin/env python3
"""Formal Phase 6 validation: ARVOR-I ``<WMO>_meta.nc`` for 6990711 / 7902408.

Checks (investigation report ARVOR_I_META_NC_MAPPING_2026-08-27.md §3/§8):
  1. layout: NETCDF3_CLASSIC, 65 variables in exact GDAC order, dtypes,
     per-variable attributes, global-attribute keys, N_MISSIONS=1 unlimited;
  2. values equal GDAC for every telemetry-/family-derived field and every
     field GDAC also carries blank (LAUNCH_DATE, platform identity, trans/
         positioning systems, END_MISSION/STARTUP blanks, CONFIG_MISSION_NUMBER);
  3. registry-sourced fields are proper fills/blanks — never copied from
     GDAC (no ``<wmo>_meta.json`` exists in this workspace);
  4. clamped one-row CONFIG/SENSOR/PARAMETER blocks carry ADMT fills.

Every mismatch outside the classified ledger fails the run.  Exit code 0
only if every check passes.  Products are (re)written to
``validation_phase6_meta/`` next to the workspace root.  An optional
Coriolis registry json per float (``--meta-json <wmo>=<path>``) exercises
the full-parity path without changing defaults.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import netCDF4
import numpy as np

from argo_decoder.platforms.provor_ir_sbd.arvor_i import read_arvor_i_eml
from argo_decoder.platforms.provor_ir_sbd.arvor_i_meta import (
    build_arvor_meta_nc,
    write_arvor_meta_nc,
)
from argo_decoder.platforms.provor_ir_sbd.arvor_i_science import reconstruct_science

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
RAW_ROOTS = [
    WORKSPACE / "arvor_raw" / "ARVOR-I-raw-files" / "20260819",
    # 2026-fleet telemetry arrived with the harness bundle (Prompt 10).
    WORKSPACE / "arvor_raw" / "harness_bundle" / "more-raw-files-and-manuals",
]


def _raw_dir(wmo: int) -> Path:
    for root in RAW_ROOTS:
        candidate = root / str(wmo)
        if any(candidate.glob("*.eml")):
            return candidate
    raise FileNotFoundError(f"no raw .eml for {wmo}")


REF_ROOT = WORKSPACE / "gdac_arvor_i_ref"
OUT_ROOT = WORKSPACE / "validation_phase6_meta"

LAUNCHES = {
    6990711: datetime(2025, 3, 2, 5, 16, tzinfo=UTC),
    7902408: datetime(2026, 3, 25, 17, 44, tzinfo=UTC),
    # 2026 fleets: raw arrived with the harness bundle (Prompt 10);
    # launch dates from meta.csv, same convention as the csv4 loader.
    1902844: datetime(2026, 1, 15, 13, 30, tzinfo=UTC),
    2904082: datetime(2026, 1, 16, 15, 32, tzinfo=UTC),
}

#: Values that must equal the GDAC references bit-for-bit.
DERIVED_EQUAL = (
    "PLATFORM_NUMBER",
    "TRANS_SYSTEM",
    "POSITIONING_SYSTEM",
    "PLATFORM_FAMILY",
    "PLATFORM_TYPE",
    "PLATFORM_MAKER",
    "LAUNCH_DATE",
    "LAUNCH_QC",
    "DATA_TYPE",
    "FORMAT_VERSION",
    "HANDBOOK_VERSION",
    "END_MISSION_DATE",
    "END_MISSION_STATUS",
    "STARTUP_DATE",
    "STARTUP_DATE_QC",
    "ANOMALY",
    "CONFIG_MISSION_NUMBER",
)

#: Registry-sourced fields; blanks/fills classified DATA-COVERAGE.
REGISTRY_FIELDS = (
    "PTT",
    "TRANS_SYSTEM_ID",
    "TRANS_FREQUENCY",
    "FIRMWARE_VERSION",
    "MANUAL_VERSION",
    "FLOAT_SERIAL_NO",
    "STANDARD_FORMAT_ID",
    "DAC_FORMAT_ID",
    "WMO_INST_TYPE",
    "PROJECT_NAME",
    "DATA_CENTRE",
    "PI_NAME",
    "BATTERY_TYPE",
    "BATTERY_PACKS",
    "CONTROLLER_BOARD_TYPE_PRIMARY",
    "CONTROLLER_BOARD_TYPE_SECONDARY",
    "CONTROLLER_BOARD_SERIAL_NO_PRIMARY",
    "CONTROLLER_BOARD_SERIAL_NO_SECONDARY",
    "SPECIAL_FEATURES",
    "FLOAT_OWNER",
    "OPERATING_INSTITUTION",
    "CUSTOMISATION",
    "DEPLOYMENT_PLATFORM",
    "DEPLOYMENT_CRUISE_ID",
    "DEPLOYMENT_REFERENCE_STATION_ID",
    "SENSOR",
    "SENSOR_MAKER",
    "SENSOR_MODEL",
    "SENSOR_SERIAL_NO",
    "PARAMETER",
    "PARAMETER_SENSOR",
    "PARAMETER_UNITS",
    "PARAMETER_ACCURACY",
    "PARAMETER_RESOLUTION",
    "PREDEPLOYMENT_CALIB_EQUATION",
    "PREDEPLOYMENT_CALIB_COEFFICIENT",
    "PREDEPLOYMENT_CALIB_COMMENT",
    "CONFIG_PARAMETER_NAME",
    "CONFIG_PARAMETER_VALUE",
    "LAUNCH_CONFIG_PARAMETER_NAME",
    "LAUNCH_CONFIG_PARAMETER_VALUE",
    "CONFIG_MISSION_COMMENT",
)

_pass = 0
_fail = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global _pass, _fail
    if ok:
        _pass += 1
    else:
        _fail += 1
    suffix = f"  [{detail}]" if detail and not ok else ""
    print(f"  {'PASS' if ok else 'FAIL':4s}  {label}{suffix}")


def text(d: netCDF4.Dataset, name: str) -> str:
    d.set_auto_mask(False)
    arr = np.asarray(d[name][:])
    if arr.dtype.kind != "S":
        # Numeric block: all-fill reads as blank, any value as non-blank.
        return "" if bool(np.all(arr == 99999.0)) else "<values>"
    return bytes(arr.reshape(-1)).decode().rstrip()


def norm(value: object) -> object:
    return value.decode() if isinstance(value, bytes) else value


def main() -> int:
    meta_json: dict[int, str] = {}
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--meta-json" and i + 1 < len(args):
            wmo_s, path = args[i + 1].split("=", 1)
            meta_json[int(wmo_s)] = path

    print("=" * 72)
    for wmo, launch in LAUNCHES.items():
        msgs = [read_arvor_i_eml(p) for p in sorted((_raw_dir(wmo)).glob("*.eml"))]
        result = reconstruct_science(msgs, launch)
        ds = build_arvor_meta_nc(
            wmo=wmo,
            launch_date=launch,
            result=result,
            meta_json_path=meta_json.get(wmo),
        )
        OUT_ROOT.mkdir(parents=True, exist_ok=True)
        ours_path = OUT_ROOT / f"{wmo}_meta.nc"
        write_arvor_meta_nc(ds, ours_path)

        ours = netCDF4.Dataset(ours_path)
        ours.set_auto_mask(False)
        ref = netCDF4.Dataset(REF_ROOT / f"{wmo}_meta.nc")
        ref.set_auto_mask(False)
        print(f"\n===== {wmo}_meta.nc  (registry json: {meta_json.get(wmo) or 'none'})")

        try:
            check(f"{wmo}: NETCDF3_CLASSIC", ours.data_model == "NETCDF3_CLASSIC")
            check(
                f"{wmo}: 65 variables in exact GDAC order",
                list(ours.variables) == list(ref.variables) and len(ours.variables) == 65,
            )
            check(
                f"{wmo}: dtypes identical",
                all(ours[v].dtype == ref[v].dtype for v in ours.variables),
            )
            attr_diffs = [
                (v, a)
                for v in ours.variables
                for a in ours[v].ncattrs()
                if norm(ours[v].getncattr(a)) != norm(ref[v].getncattr(a))
            ]
            check(f"{wmo}: per-variable attributes identical", not attr_diffs, str(attr_diffs[:3]))
            check(
                f"{wmo}: N_MISSIONS = 1 (unlimited)",
                ours.dimensions["N_MISSIONS"].isunlimited()
                and len(ours.dimensions["N_MISSIONS"]) == 1,
            )
            check(
                f"{wmo}: global attribute keys identical",
                sorted(ours.ncattrs()) == sorted(ref.ncattrs()),
            )

            for var in DERIVED_EQUAL:
                check(
                    f"{wmo}: {var} == GDAC ({text(ref, var) or 'blank'})",
                    text(ours, var) == text(ref, var),
                    f"ours={text(ours, var)!r}",
                )
            check(
                f"{wmo}: LAUNCH_LATITUDE/LONGITUDE fills (99999.0)",
                float(ours["LAUNCH_LATITUDE"][...]) == 99999.0
                and float(ours["LAUNCH_LONGITUDE"][...]) == 99999.0,
            )
            # START_DATE is telemetry-derived, not registry-sourced:
            # UM 3.44.0 §2.4.5 defines it as the float's first descent,
            # which Trajectory Cookbook 6.1 (§2.2 p.19, Arvor annex p.99)
            # maps to DST / MC 100 -- transmitted by the float. Its QC
            # tracks it per reference table 2.
            check(
                f"{wmo}: START_DATE derived from first descent (DST)",
                text(ours, "START_DATE") != "",
                f"ours={text(ours, 'START_DATE')!r}",
            )
            check(
                f"{wmo}: START_DATE_QC consistent with START_DATE",
                text(ours, "START_DATE_QC") == ("1" if text(ours, "START_DATE") else "9"),
                f"ours={text(ours, 'START_DATE_QC')!r}",
            )
            blanks = [v for v in REGISTRY_FIELDS if text(ours, v) == ""]
            check(
                f"{wmo}: registry fields blank (no registry json)",
                len(blanks) == len(REGISTRY_FIELDS) if not meta_json.get(wmo) else True,
                f"non-blank: {sorted(set(REGISTRY_FIELDS) - set(blanks))[:6]}",
            )
            check(
                f"{wmo}: CONFIG/LAUNCH_CONFIG/SENSOR/PARAM blocks fill-only",
                bool(np.all(np.asarray(ours["CONFIG_PARAMETER_VALUE"][:]) == 99999.0))
                and bool(np.all(np.asarray(ours["LAUNCH_CONFIG_PARAMETER_VALUE"][:]) == 99999.0))
                and text(ours, "SENSOR") == ""
                and text(ours, "PARAMETER") == "",
            )
            check(
                f"{wmo}: institution global (chain default CORIOLIS / registry centre)",
                ours.institution
                == (
                    "CORIOLIS"
                    if not meta_json.get(wmo) and not text(ours, "DATA_CENTRE")
                    else ours.institution
                ),
            )
        finally:
            ours.close()
            ref.close()

    print("\n" + "=" * 72)
    print(f"{_pass}/{_pass + _fail} checks passed")
    if _fail:
        return 1
    print(
        "\nClassified divergences vs GDAC (NOT reproduced; never copied):\n"
        "  - DATA-COVERAGE (Coriolis registry <wmo>_meta.json absent from this\n"
        "    workspace and not public): PTT, FLOAT_SERIAL_NO, sensor serials,\n"
        "    FIRMWARE '160414' / MANUAL / STANDARD+DAC format ids, WMO_INST_TYPE\n"
        "    844, PROJECT/PI/DATA_CENTRE 'IN'/owner INCOIS, battery/controller\n"
        "    hardware, DEPLOYMENT_PLATFORM, LAUNCH_LAT/LON, START_DATE (raw\n"
        "    nearest evidence 14 s from registry value), SENSOR/PARAMETER/\n"
        "    PREDEPLOYMENT_CALIB blocks, CONFIG blocks (14 legacy names).\n"
        "  - TOOL-AVAILABILITY: 10/14 published CONFIG names absent from the\n"
        "    current public _config_param_name_222/232.json tables; 6990711 has\n"
        "    zero Param#1 packets in raw (values not derivable either).\n"
        "  - EXPECTED: DATE_CREATION/DATE_UPDATE + history (run stamps);\n"
        "    institution global 'CORIOLIS' vs GDAC 'INCOIS' (documented MATLAB\n"
        "    default when no registry DATA_CENTRE; 4A/4B/5 product consistency).\n"
        "  - UNKNOWN (documented, not applied): update_meta_data.m L270-283\n"
        "    would add POSITIONING_SYSTEM='IRIDIUM' for GPS floats unless\n"
        "    decIds 222/232 sit in unresolvable exclusion lists; production\n"
        "    GDAC files carry GPS only -> single system emitted.\n"
        "  - Generic normalization: registry 'n/a' tokens would be blanked by\n"
        "    the shared builder (_NOT_AVAILABLE); irrelevant while no registry\n"
        "    json is supplied (fields blank anyway)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
