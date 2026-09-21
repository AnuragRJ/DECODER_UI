#!/usr/bin/env python3
"""Audit APEX engineering decoding across the whole raw archive.

Phase 6A.3 validation tool. Decodes every archived ARGOS cycle and
classifies the result, so the decoder's coverage stays reproducible.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from argo_decoder.platforms.apex_argos.engineering import decode_engineering
from argo_decoder.platforms.apex_argos.frames import (
    iter_argos_messages_from_payload,
    select_redundant_messages,
)

#: PTT -> MATLAB decoder id for the Phase 4A scoped floats.
DECODER_BY_PTT = {"102510": 1005, "152389": 1010, "152382": 1010, "152399": 1010}

PLAUSIBLE_SP_DBAR = 20.0
# The GDAC technical references report TIME_PumpMotor_seconds up to
# 65477 s for WMO 2901339, so the only implausible value is a negative
# one. An earlier, tighter bound here was wrong and is not reinstated.
PLAUSIBLE_PUMP_S = 65536


def audit(raw_root: Path, report_dir: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for raw in sorted(raw_root.glob("*/*.txt")):
        ptt = raw.parent.name
        decoder_id = DECODER_BY_PTT.get(ptt)
        if decoder_id is None:
            continue
        selected = select_redundant_messages(
            iter_argos_messages_from_payload(raw.read_bytes(), frame_length=31)
        )
        data = decode_engineering(selected, decoder_id=decoder_id)
        if data is None:
            records.append({"file": raw.name, "status": "no_engineering_messages"})
            continue
        sp = data.surface_pressure_dbar
        pump = data.pump_motor_time_s
        plausible = (
            sp is not None
            and abs(sp) < PLAUSIBLE_SP_DBAR
            and pump is not None
            and 0 <= pump < PLAUSIBLE_PUMP_S
        )
        if plausible:
            status = "decoded"
        elif data.status_flags.get("prelude_message"):
            status = "prelude_message"
        elif sp is None:
            status = "sentinel_value"
        else:
            status = "unexplained"
        records.append(
            {
                "file": raw.name,
                "decoder_id": decoder_id,
                "status": status,
                "profile_id": data.profile_id,
                "profile_id_overflow": data.profile_id_overflow,
                "surface_pressure_dbar": sp,
                "pump_motor_time_s": pump,
                "down_time_expiry": (
                    data.down_time_expiry.isoformat() if data.down_time_expiry else None
                ),
                "telemetry_init_minutes": data.telemetry_init_minutes,
                "active_status_flags": sorted(k for k, v in data.status_flags.items() if v),
            }
        )

    summary: dict[str, int] = {}
    for rec in records:
        summary[rec["status"]] = summary.get(rec["status"], 0) + 1
    payload = {"summary": summary, "records": records}
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "phase6a3_engineering_audit.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw-root", type=Path, default=Path("phase4_reference/raw/raw-files"))
    ap.add_argument("--report-dir", type=Path, default=Path("docs/phase_reports"))
    args = ap.parse_args()
    payload = audit(args.raw_root, args.report_dir)
    print(f"engineering decode audit: {payload['summary']}")
    unexplained = [r for r in payload["records"] if r["status"] == "unexplained"]
    for rec in unexplained:
        print(f"  UNEXPLAINED {rec['file']}: SP={rec['surface_pressure_dbar']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
