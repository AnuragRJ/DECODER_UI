#!/usr/bin/env python3
"""Audit supplied WRC/APEX ARGOS raw files against local/GDAC profile references.

The script is intentionally read-only for science code: it uses the package
parsers exactly as the pipeline does, writes JSON/Markdown reports, and can
optionally download missing GDAC reference profiles for the decoded output
cycles.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import netCDF4
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from argo_decoder.config import get_decoder_table  # noqa: E402
from argo_decoder.metadata.csv_loader import load_registry_csv  # noqa: E402
from argo_decoder.metadata.models import FloatRegistryRow  # noqa: E402
from argo_decoder.platforms.apex_argos.frames import (  # noqa: E402
    iter_argos_messages_from_payload,
    select_redundant_messages,
)
from argo_decoder.platforms.apex_argos.profile import (  # noqa: E402
    decode_profile,
    layout_for_decoder,
)

PARAMS = ("PRES", "TEMP", "PSAL")
TOLERANCES = {"PRES": 1e-3, "TEMP": 1e-6, "PSAL": 2e-6}


@dataclass(frozen=True)
class ArgosAuditRecord:
    wmo: int
    ptt: str
    raw_file: str
    raw_cycle: int
    decoder_id: int
    decoder_version: str
    profile_class: str
    profile_number: int | None
    output_cycle: int
    messages: int
    crc_ok_messages: int
    selected_messages: int
    levels: int
    pressure_min: float | None
    pressure_max: float | None
    reference_file: str | None
    status: str
    max_abs_diff: dict[str, float]
    notes: str


def _raw_cycle_from_name(path: Path) -> int:
    try:
        return int(path.stem.rsplit("_", 1)[1])
    except (IndexError, ValueError) as exc:
        raise ValueError(f"Cannot parse cycle from {path.name}") from exc


def _reference_prefixes(wmo: int) -> tuple[str, ...]:
    # WMO 2901339 has only delayed-mode D profiles on GDAC; the others in the
    # supplied raw archive have real-time R profiles.
    if wmo == 2901339:
        return ("D", "R")
    return ("R", "D")


def _reference_path(gdac_dir: Path, wmo: int, cycle: int) -> Path | None:
    for prefix in _reference_prefixes(wmo):
        path = gdac_dir / f"{prefix}{wmo}_{cycle:03d}.nc"
        if path.exists():
            return path
    return None


def _download_reference(gdac_dir: Path, wmo: int, cycle: int) -> Path | None:
    gdac_dir.mkdir(parents=True, exist_ok=True)
    for prefix in _reference_prefixes(wmo):
        path = gdac_dir / f"{prefix}{wmo}_{cycle:03d}.nc"
        if path.exists():
            return path
        url = f"https://data-argo.ifremer.fr/dac/incois/{wmo}/profiles/{prefix}{wmo}_{cycle:03d}.nc"
        try:
            urllib.request.urlretrieve(url, path)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            if path.exists():
                path.unlink()
            continue
        return path
    return None


def _actual_matrix(record: Any) -> np.ndarray:
    actual = np.array(
        list(
            zip(
                record.pressure_dbar,
                record.temperature_deg_c,
                record.salinity_psu,
                strict=True,
            )
        ),
        dtype=np.float64,
    )
    if actual.size == 0:
        return np.empty((0, 3), dtype=np.float64)
    return actual[np.argsort(actual[:, 0])]


def _reference_matrix(path: Path) -> np.ndarray:
    with netCDF4.Dataset(path) as ds:
        return np.column_stack(
            [
                np.ma.filled(ds.variables[name][:], np.nan).ravel().astype(np.float64)
                for name in PARAMS
            ]
        )


def _compare(actual: np.ndarray, reference: np.ndarray) -> tuple[str, dict[str, float], str]:
    if actual.shape != reference.shape:
        return (
            "fail",
            {},
            f"shape mismatch actual={tuple(actual.shape)} reference={tuple(reference.shape)}",
        )
    diffs = {
        name: float(np.nanmax(np.abs(actual[:, idx] - reference[:, idx])))
        for idx, name in enumerate(PARAMS)
    }
    failed = [name for name, diff in diffs.items() if diff > TOLERANCES[name]]
    if failed:
        return "fail", diffs, "tolerance exceeded: " + ", ".join(failed)
    return "pass", diffs, ""


def _audit_raw_file(
    row: FloatRegistryRow,
    raw_path: Path,
    *,
    gdac_dir: Path,
    download_missing: bool,
) -> ArgosAuditRecord:
    table = get_decoder_table()
    entry = table.by_platform_version(row.platform_type, row.decoder_version)
    layout = layout_for_decoder(row.decoder_id, entry.profile_class)
    messages = iter_argos_messages_from_payload(
        raw_path.read_bytes(), frame_length=entry.frame_length
    )
    selected = select_redundant_messages(messages)
    decoded = decode_profile(selected, layout=layout)
    raw_cycle = _raw_cycle_from_name(raw_path)
    output_cycle = (
        decoded.output_cycle_number if decoded.output_cycle_number is not None else raw_cycle
    )
    actual = _actual_matrix(decoded)
    pressure_min = float(np.nanmin(actual[:, 0])) if actual.size else None
    pressure_max = float(np.nanmax(actual[:, 0])) if actual.size else None

    ref_path = _reference_path(gdac_dir, row.wmo, output_cycle)
    if ref_path is None and download_missing:
        ref_path = _download_reference(gdac_dir, row.wmo, output_cycle)

    status = "missing_reference"
    diffs: dict[str, float] = {}
    notes = ""
    if ref_path is not None:
        status, diffs, notes = _compare(actual, _reference_matrix(ref_path))

    return ArgosAuditRecord(
        wmo=row.wmo,
        ptt=row.ptt,
        raw_file=str(raw_path.relative_to(REPO_ROOT)),
        raw_cycle=raw_cycle,
        decoder_id=row.decoder_id,
        decoder_version=row.decoder_version,
        profile_class=layout.profile_class,
        profile_number=decoded.profile_number,
        output_cycle=output_cycle,
        messages=len(messages),
        crc_ok_messages=sum(1 for msg in messages if msg.crc_ok),
        selected_messages=len(selected),
        levels=len(decoded.pressure_dbar),
        pressure_min=pressure_min,
        pressure_max=pressure_max,
        reference_file=str(ref_path.relative_to(REPO_ROOT)) if ref_path is not None else None,
        status=status,
        max_abs_diff=diffs,
        notes=notes,
    )


def _markdown(records: list[ArgosAuditRecord]) -> str:
    lines = [
        "# Phase 4 APEX ARGOS raw-cycle audit",
        "",
        "| WMO | Raw cycle | Output cycle | Decoder | Levels | Ref | Status | Max diffs | Notes |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |",
    ]
    for rec in records:
        diffs = ", ".join(f"{key}={value:.3g}" for key, value in rec.max_abs_diff.items())
        lines.append(
            "| "
            f"{rec.wmo} | {rec.raw_cycle} | {rec.output_cycle} | {rec.decoder_id} | "
            f"{rec.levels} | {rec.reference_file or ''} | {rec.status} | {diffs} | {rec.notes} |"
        )
    summary: dict[str, int] = {}
    for rec in records:
        summary[rec.status] = summary.get(rec.status, 0) + 1
    lines.extend(["", "## Summary", ""])
    for key in sorted(summary):
        lines.append(f"- {key}: {summary[key]}")
    return "\n".join(lines) + "\n"


def audit(
    *,
    raw_root: Path,
    registry_path: Path,
    gdac_dir: Path,
    report_dir: Path,
    download_missing: bool,
) -> list[ArgosAuditRecord]:
    rows = [row for row in load_registry_csv(registry_path) if row.transmission_type == 1]
    records: list[ArgosAuditRecord] = []
    for row in rows:
        ptt_dir = raw_root / row.ptt
        if not ptt_dir.exists():
            continue
        for raw_path in sorted(ptt_dir.glob("*.txt")):
            records.append(
                _audit_raw_file(
                    row,
                    raw_path,
                    gdac_dir=gdac_dir,
                    download_missing=download_missing,
                )
            )

    pass_keys = {(rec.wmo, rec.output_cycle) for rec in records if rec.status == "pass"}
    records = [
        replace(
            rec,
            status="superseded_by_pass",
            notes=(
                rec.notes
                + "; "
                + "another raw file for this WMO/output cycle matches the GDAC reference"
            ).lstrip("; "),
        )
        if rec.status == "fail" and (rec.wmo, rec.output_cycle) in pass_keys
        else rec
        for rec in records
    ]

    report_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": {
            status: sum(1 for rec in records if rec.status == status)
            for status in sorted({rec.status for rec in records})
        },
        "records": [asdict(rec) for rec in records],
    }
    (report_dir / "phase4_argos_raw_audit.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (report_dir / "phase4_argos_raw_audit.md").write_text(_markdown(records), encoding="utf-8")
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw-root", type=Path, default=REPO_ROOT / "phase4_reference" / "raw" / "raw-files"
    )
    parser.add_argument("--registry", type=Path, default=REPO_ROOT / "config" / "registry.csv")
    parser.add_argument(
        "--gdac-dir", type=Path, default=REPO_ROOT / "phase4_reference" / "gdac_profiles"
    )
    parser.add_argument("--report-dir", type=Path, default=REPO_ROOT / "docs" / "phase_reports")
    parser.add_argument("--download-missing", action="store_true")
    args = parser.parse_args()
    records = audit(
        raw_root=args.raw_root,
        registry_path=args.registry,
        gdac_dir=args.gdac_dir,
        report_dir=args.report_dir,
        download_missing=args.download_missing,
    )
    summary: dict[str, int] = {}
    for rec in records:
        summary[rec.status] = summary.get(rec.status, 0) + 1
    print(f"audited {len(records)} raw ARGOS files: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
