#!/usr/bin/env python3
"""Bootstrap a ``registry.csv`` from the existing ``*_info.json`` + ``*_meta.json``
tree shipped with the MATLAB demo dataset.

This is a one-off helper used to seed the central metadata registry for floats
that are already represented in the legacy JSON layout. It is deliberately
conservative: any field that cannot be inferred is left blank so that a human
operator can fill it in; the registry validator will flag missing required
fields.

Usage::

    python scripts/bootstrap_registry.py \
        --info-dir ../Coriolis-.../json_float_info \
        --meta-dir ../Coriolis-.../json_float_meta_ir_sbd \
        --out      ./config/registry.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path

_INFO_RE = re.compile(r"^(?P<wmo>\d+)_(?P<ptt>[^_]+)_info\.json$")

# Columns for the v1 registry schema — matches FloatRegistryRow in
# argo_decoder.metadata.models. Order matters (CSV header).
COLUMNS = [
    "wmo",
    "ptt",
    "imei",
    "platform_maker",
    "platform_type",
    "platform_family",
    "transmission_type",
    "decoder_id",
    "decoder_version",
    "firmware_version",
    "manual_version",
    "frame_length",
    "cycle_length_hours",
    "drift_sampling_period_hours",
    "delay_before_mission_minutes",
    "launch_date_utc",
    "launch_lon",
    "launch_lat",
    "launch_qc",
    "start_date_utc",
    "reference_day",
    "end_decoding_date",
    "dm_flag",
    "argo_user_manual_version",
    "wmo_inst_type",
    "data_centre",
    "pi_name",
    "project_name",
    "float_owner",
    "operating_institution",
    "battery_type",
    "battery_packs",
    "controller_board_primary_type",
    "controller_board_primary_serial",
    "deployment_platform",
    "deployment_cruise_id",
    "deployment_station_id",
    "float_serial_no",
    "sensors",  # JSON-encoded list
    "transmission_system",  # JSON list of strings
    "positioning_system",  # JSON list of strings
    "config_profile_ref",
    "notes",
    "registry_schema_version",
    "registry_row_updated_utc",
]


def _parse_coriolis_dt(s: str) -> datetime | None:
    s = (s or "").strip()
    if not s or s == "99999999999999":
        return datetime(9999, 12, 31, 23, 59, 59) if s == "99999999999999" else None
    # YYYYMMDDHHMMSS (info.json)
    if len(s) == 14 and s.isdigit():
        return datetime.strptime(s, "%Y%m%d%H%M%S")
    # DD/MM/YYYY HH:MM:SS (meta.json)
    try:
        return datetime.strptime(s, "%d/%m/%Y %H:%M:%S")
    except ValueError:
        pass
    return None


def _parse_coriolis_date(s: str) -> date | None:
    s = (s or "").strip()
    if not s:
        return None
    if len(s) == 8 and s.isdigit():
        return datetime.strptime(s, "%Y%m%d").date()
    return None


def _json_list_of_dicts_to_values(d: list[dict], key_prefix: str) -> list[str]:
    """Flatten MATLAB's ``[{"KEY_N": "v"}, ...]`` style into a flat value list."""
    out: list[str] = []
    for entry in d:
        # Entries are single-key dicts like {"SENSOR_1": "CTD_PRES", "SENSOR_2": ...}
        # Sort by numeric suffix.
        items = sorted(
            entry.items(), key=lambda kv: int(kv[0].rsplit("_", 1)[1]) if "_" in kv[0] else 0
        )
        for _k, v in items:
            if v not in ("", "n/a", None):
                out.append(str(v))
    # de-dup while preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for v in out:
        if v not in seen:
            seen.add(v)
            uniq.append(v)
    return uniq


def _row_from_files(info_path: Path, meta_path: Path | None) -> dict[str, object]:
    with info_path.open(encoding="utf-8") as fh:
        info = json.load(fh)
    meta: dict = {}
    if meta_path and meta_path.exists():
        with meta_path.open(encoding="utf-8") as fh:
            meta = json.load(fh)

    wmo = int(info["WMO"])
    ptt = str(info["PTT"])
    imei = str(meta.get("IMEI", "")) or ptt
    launch_dt = _parse_coriolis_dt(str(info.get("LAUNCH_DATE", "")))
    end_dt = _parse_coriolis_dt(str(info.get("END_DECODING_DATE", "")))
    ref_day = _parse_coriolis_date(str(info.get("REFERENCE_DAY", "")))
    start_dt = _parse_coriolis_dt(str(meta.get("START_DATE", "")))

    sensors = _json_list_of_dicts_to_values(meta.get("SENSOR", []), "SENSOR")

    trans_sys = _json_list_of_dicts_to_values(meta.get("TRANS_SYSTEM", []), "TRANS_SYSTEM")
    pos_sys = _json_list_of_dicts_to_values(
        meta.get("POSITIONING_SYSTEM", []), "POSITIONING_SYSTEM"
    )
    if not trans_sys:
        trans_sys = ["IRIDIUM"]  # default for Iridium SBD
    if not pos_sys:
        pos_sys = ["GPS", "IRIDIUM"]

    def _f(k: str, default: str = "") -> str:
        v = meta.get(k, info.get(k, default))
        if v is None:
            return default
        s = str(v)
        return "" if s == "n/a" else s

    row: dict[str, object] = {
        "wmo": wmo,
        "ptt": str(meta.get("PTT", ptt[-6:]) if meta else ptt[-min(6, len(ptt)) :]),
        "imei": imei,
        "platform_maker": _f("PLATFORM_MAKER", "NKE"),
        "platform_type": _f("PLATFORM_TYPE", info.get("FLOAT_TYPE", "")),
        "platform_family": _f("PLATFORM_FAMILY", "FLOAT"),
        "transmission_type": 3,  # IRIDIUM_SBD
        "decoder_id": int(info.get("DECODER_ID", "0")),
        "decoder_version": _f("DECODER_VERSION"),
        "firmware_version": _f("FIRMWARE_VERSION"),
        "manual_version": _f("MANUAL_VERSION"),
        "frame_length": int(info.get("FRAME_LENGTH", "0")),
        "cycle_length_hours": int(info.get("CYCLE_LENGTH", "0")),
        "drift_sampling_period_hours": float(info.get("DRIFT_SAMPLING_PERIOD", "0")),
        "delay_before_mission_minutes": int(info.get("DELAI", "-1")),
        "launch_date_utc": launch_dt.isoformat() + "Z" if launch_dt else "",
        "launch_lon": float(meta.get("LAUNCH_LONGITUDE", info.get("LAUNCH_LON", "0"))),
        "launch_lat": float(meta.get("LAUNCH_LATITUDE", info.get("LAUNCH_LAT", "0"))),
        "launch_qc": int(meta.get("LAUNCH_QC", "1") or 1),
        "start_date_utc": start_dt.isoformat() + "Z" if start_dt else "",
        "reference_day": ref_day.isoformat() if ref_day else "",
        "end_decoding_date": end_dt.isoformat() + "Z" if end_dt else "",
        "dm_flag": bool(int(info.get("DM_FLAG", "0") or 0)),
        "argo_user_manual_version": _f("ARGO_USER_MANUAL_VERSION", "3.1"),
        "wmo_inst_type": _f("WMO_INST_TYPE"),
        "data_centre": _f("DATA_CENTRE", "IF"),
        "pi_name": _f("PI_NAME"),
        "project_name": _f("PROJECT_NAME"),
        "float_owner": _f("FLOAT_OWNER", "IFREMER"),
        "operating_institution": _f("OPERATING_INSTITUTION"),
        "battery_type": _f("BATTERY_TYPE"),
        "battery_packs": _f("BATTERY_PACKS"),
        "controller_board_primary_type": _f("CONTROLLER_BOARD_TYPE_PRIMARY"),
        "controller_board_primary_serial": _f("CONTROLLER_BOARD_SERIAL_NO_PRIMARY"),
        "deployment_platform": _f("DEPLOYMENT_PLATFORM"),
        "deployment_cruise_id": _f("DEPLOYMENT_CRUISE_ID"),
        "deployment_station_id": _f("DEPLOYMENT_REFERENCE_STATION_ID"),
        "float_serial_no": _f("FLOAT_SERIAL_NO"),
        "sensors": json.dumps(sensors),
        "transmission_system": json.dumps(trans_sys),
        "positioning_system": json.dumps(pos_sys),
        "config_profile_ref": "",
        "notes": "bootstrapped from legacy json_float_info/json_float_meta",
        "registry_schema_version": "1.0.0",
        "registry_row_updated_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return row


def build_registry(info_dir: Path, meta_dir: Path | None) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for p in sorted(info_dir.glob("*_info.json")):
        m = _INFO_RE.match(p.name)
        if not m:
            continue
        wmo = int(m.group("wmo"))
        meta_path = (meta_dir / f"{wmo}_meta.json") if meta_dir else None
        rows.append(_row_from_files(p, meta_path))
    rows.sort(key=lambda r: int(r["wmo"]))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--info-dir", type=Path, required=True)
    ap.add_argument("--meta-dir", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument(
        "--append",
        action="store_true",
        help="Append rows to an existing CSV (skipping WMOs already present).",
    )
    args = ap.parse_args()

    rows = build_registry(args.info_dir, args.meta_dir)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_header = not args.out.exists() or not args.append
    mode = "a" if args.append else "w"
    existing_wmos: set[str] = set()
    if args.append and args.out.exists():
        with args.out.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for r in reader:
                existing_wmos.add(str(r.get("wmo", "")))

    with args.out.open(mode, encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        if write_header:
            writer.writeheader()
        for r in rows:
            if str(r["wmo"]) in existing_wmos:
                continue
            writer.writerow({k: r.get(k, "") for k in COLUMNS})
    print(f"wrote {len(rows)} rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
