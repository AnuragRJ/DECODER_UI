#!/usr/bin/env python3
"""Derive a ``registry.csv`` row from an official GDAC ``<wmo>_meta.nc``.

Every field is copied from the reference metadata file, so nothing is
invented. Fields the reference leaves blank stay blank rather than being
guessed. Intended for onboarding a float whose GDAC metadata is
available but which is not yet in the registry.

Usage::

    python scripts/registry_row_from_meta_nc.py <wmo>_meta.nc [--append]
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from pathlib import Path
from typing import Any

import netCDF4  # type: ignore[import-untyped]
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY = REPO_ROOT / "config" / "registry.csv"

#: GDAC ``DAC_FORMAT_ID`` is the INCOIS numbering, which is not the
#: Coriolis decoder id. Firmware revision is the reliable key.
_FIRMWARE_TO_DECODER: dict[str, int] = {
    "061810": 1005,
    "110613": 1010,
    "090413": 1010,
    "102015": 1010,
    "091515": 1010,
    "091615": 1010,
    # Firmware 100410 was previously mapped to 1010. That is wrong, and
    # the error is visible in the telemetry rather than only against a
    # reference: decoded with the 1010 layout (apf9_ctd_19) WMO 2901328
    # yields plausible pressure on 1.7% of levels, with pressure landing
    # in the temperature slot; with the 1005 layout (apf9_ctd_23) it is
    # 100%, and the result is bit-identical to GDAC over 5088 levels.
    # GDAC's own DAC_FORMAT_ID says 1010 for this float, so that field
    # is not the decoder id -- firmware is the reliable key.
    "100410": 1005,
    "020811": 1010,
}


def _decoder_for_firmware(firmware: str) -> str:
    """Map a GDAC ``FIRMWARE_VERSION`` to a Coriolis decoder id.

    GDAC stores the revision without leading zeros -- ``61810`` for what
    the Coriolis tables call ``061810`` -- so the raw string misses the
    table and the row is written with an empty ``decoder_id``. Observed
    on WMO 2901350; WMO 2901339 is an established 1005 float carrying the
    same unpadded value, so this is the norm rather than an exception.
    """
    key = firmware.strip()
    if not key:
        return ""
    for candidate in (key, key.zfill(6)):
        if candidate in _FIRMWARE_TO_DECODER:
            return str(_FIRMWARE_TO_DECODER[candidate])
    return ""


def _text(ds: netCDF4.Dataset, name: str) -> str:
    if name not in ds.variables:
        return ""
    raw = ds[name][:]
    joined = b"".join(np.ma.filled(np.asarray(raw), b" ").astype("S1"))
    return joined.decode("ascii", "replace").strip("\x00 ")


def _number(ds: netCDF4.Dataset, name: str) -> float | None:
    if name not in ds.variables:
        return None
    value = ds[name][:]
    flat = np.ma.filled(np.asarray(value), np.nan).ravel()
    return None if not flat.size or np.isnan(flat[0]) else float(flat[0])


def _iso(stamp: str) -> str:
    """Convert an Argo ``YYYYMMDDHHMMSS`` stamp to ISO-8601 UTC."""
    stamp = stamp.strip()
    if len(stamp) < 14 or not stamp[:14].isdigit():
        return ""
    parsed = dt.datetime.strptime(stamp[:14], "%Y%m%d%H%M%S").replace(tzinfo=dt.UTC)
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def row_from_meta(path: Path) -> dict[str, Any]:
    with netCDF4.Dataset(path) as ds:
        firmware = _text(ds, "FIRMWARE_VERSION")
        launch = _iso(_text(ds, "LAUNCH_DATE"))
        start = _iso(_text(ds, "START_DATE"))
        sensors = [s for s in ("CTD_PRES", "CTD_TEMP", "CTD_CNDC")]
        return {
            "wmo": _text(ds, "PLATFORM_NUMBER"),
            "ptt": _text(ds, "PTT").split()[0] if _text(ds, "PTT") else "",
            "imei": "",
            "platform_maker": _text(ds, "PLATFORM_MAKER"),
            "platform_type": _text(ds, "PLATFORM_TYPE"),
            "platform_family": "FLOAT",
            "transmission_type": "1",
            "decoder_id": _decoder_for_firmware(firmware),
            "decoder_version": firmware,
            "firmware_version": firmware,
            "manual_version": firmware,
            "frame_length": "31",
            "cycle_length_hours": "240",
            "drift_sampling_period_hours": "240.0",
            "delay_before_mission_minutes": "-1",
            "launch_date_utc": launch,
            "launch_lon": str(_number(ds, "LAUNCH_LONGITUDE") or ""),
            "launch_lat": str(_number(ds, "LAUNCH_LATITUDE") or ""),
            "launch_qc": "1",
            "start_date_utc": start or launch,
            "reference_day": launch[:10] if launch else "",
            "end_decoding_date": "9999-12-31T23:59:59Z",
            "dm_flag": "False",
            "argo_user_manual_version": "3.1",
            "wmo_inst_type": _text(ds, "WMO_INST_TYPE"),
            "data_centre": _text(ds, "DATA_CENTRE"),
            "pi_name": _text(ds, "PI_NAME"),
            "project_name": _text(ds, "PROJECT_NAME"),
            "float_owner": _text(ds, "FLOAT_OWNER"),
            "operating_institution": _text(ds, "OPERATING_INSTITUTION"),
            "battery_type": _text(ds, "BATTERY_TYPE"),
            "battery_packs": _text(ds, "BATTERY_PACKS"),
            "controller_board_primary_type": _text(ds, "CONTROLLER_BOARD_TYPE_PRIMARY"),
            "controller_board_primary_serial": _text(ds, "CONTROLLER_BOARD_SERIAL_NO_PRIMARY"),
            "deployment_platform": _text(ds, "DEPLOYMENT_PLATFORM"),
            "deployment_cruise_id": _text(ds, "DEPLOYMENT_CRUISE_ID"),
            "deployment_station_id": "",
            "float_serial_no": _text(ds, "FLOAT_SERIAL_NO"),
            "sensors": json.dumps(sensors),
            "transmission_system": json.dumps(["ARGOS"]),
            "positioning_system": json.dumps(["ARGOS"]),
            "config_profile_ref": "",
            "notes": f"derived from GDAC {path.name}",
            "registry_schema_version": "1.0.0",
            "registry_row_updated_utc": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("meta_nc", type=Path)
    ap.add_argument("--append", action="store_true", help="append to config/registry.csv")
    args = ap.parse_args()

    row = row_from_meta(args.meta_nc)
    existing = list(csv.DictReader(REGISTRY.open(newline="")))
    fieldnames = list(existing[0].keys())
    missing = [k for k in fieldnames if k not in row]
    if missing:
        raise SystemExit(f"row is missing registry columns: {missing}")

    if not args.append:
        print(json.dumps(row, indent=2))
        return
    if any(r["wmo"] == row["wmo"] for r in existing):
        print(f"WMO {row['wmo']} already present; nothing appended")
        return
    existing.append(row)
    with REGISTRY.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(existing)
    print(f"appended WMO {row['wmo']} to {REGISTRY}")


if __name__ == "__main__":
    main()
