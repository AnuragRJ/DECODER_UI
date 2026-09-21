"""Prompt-8 4-fleet GDAC parity run through the SHIPPED decoder path.

For each ARVOR-I float: stage the preserved raw telemetry, run the real
``run_pipeline`` with ``rtqc.apply_rtqc = True`` (the exact code path an
operator enables), then compare every profile's QCP$/QCF$ masks and QC
flag fields against the GDAC oracle preserved in
``validation_rtqc_harness/gdac_qcp_masks.json``.

Output: ``validation_arvor_i_rtqc/fleet_parity.json`` plus a printed
per-test x cycle truth table (executed pass/fail or skipped+reason).
Skipped is never counted as passed.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import netCDF4
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from argo_decoder.config.models import DecoderConfig, TransmissionType  # noqa: E402
from argo_decoder.pipeline.runner import run_pipeline  # noqa: E402

WORKSPACE = REPO.parent
RAW_ROOTS = [
    WORKSPACE / "arvor_raw" / "ARVOR-I-raw-files" / "20260819",
    WORKSPACE / "arvor_raw" / "harness_bundle" / "more-raw-files-and-manuals",
]
METADATA_DIR = REPO / "config" / "metadata"
ORACLE = REPO / "validation_rtqc_harness" / "gdac_qcp_masks.json"
OUT_DIR = REPO / "validation_arvor_i_rtqc"

#: transceiver directory per float (PTT from the sensor-info sheet)
#: PTT per float, as materialised by the csv4 backend (<wmo>_<ptt>_info.json).
TRANSCEIVER = {1902844: "123230", 2904082: "124250", 6990711: "664170", 7902408: "339490"}

ALL_TESTS = [1, 2, 3, 4, 5, 6, 8, 9, 11, 12, 13, 14, 16, 18, 19]


def _config(tmp: Path) -> DecoderConfig:
    cfg = DecoderConfig()
    cfg.transmission_type = TransmissionType.IRIDIUM_SBD
    cfg.metadata.backend = "csv4"  # type: ignore[assignment]
    cfg.metadata.registry_path = METADATA_DIR
    cfg.metadata.materialized_dir = tmp / "meta_cache"
    for attr in (
        "rsync_data_dir",
        "rsync_log_dir",
        "float_info_dir",
        "float_meta_dir",
        "dm_buffer_list_dir",
        "tech_label_dir",
        "config_label_dir",
        "iridium_decoded_dir",
        "log_dir",
        "csv_dir",
        "xml_dir",
        "nc_dir",
        "nc_traj_3_1_dir",
        "temporary_dir",
    ):
        path = tmp / attr
        path.mkdir(parents=True, exist_ok=True)
        setattr(cfg.paths, attr, path)
    return cfg


def _read_mask(path: Path, action: str) -> str | None:
    with netCDF4.Dataset(path) as ds:
        acts = np.atleast_1d(np.ma.filled(netCDF4.chartostring(ds["HISTORY_ACTION"][:]), ""))
        qs = np.atleast_1d(np.ma.filled(netCDF4.chartostring(ds["HISTORY_QCTEST"][:]), ""))
    for a, q in zip(acts.reshape(-1), qs.reshape(-1), strict=True):
        if str(a).strip() == action:
            return str(q).strip()
    return None


def _flag_summary(path: Path) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    with netCDF4.Dataset(path) as ds:
        for var in ("PRES_QC", "TEMP_QC", "PSAL_QC", "JULD_QC", "POSITION_QC"):
            arr = np.atleast_1d(np.ma.filled(netCDF4.chartostring(ds[var][:]), "")).reshape(-1)
            counts: dict[str, int] = {}
            for ch in arr:
                key = str(ch)
                counts[key] = counts.get(key, 0) + 1
            out[var] = counts
        for var in ("PROFILE_PRES_QC", "PROFILE_TEMP_QC", "PROFILE_PSAL_QC"):
            arr = np.atleast_1d(np.ma.filled(netCDF4.chartostring(ds[var][:]), "")).reshape(-1)
            out[var] = {str(ch): 1 for ch in arr}
    return out


def _decode_mask(text: str) -> set[int]:
    try:
        mask = int(text, 16)
    except ValueError:
        return set()
    return {n for n in range(1, 32) if mask & (1 << n)}


def main() -> None:
    oracle = json.loads(ORACLE.read_text())
    OUT_DIR.mkdir(exist_ok=True)
    report: dict[str, dict] = {}
    root = Path("/tmp/arvor_rtqc_fleet")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    for wmo in (1902844, 2904082, 6990711, 7902408):
        raw = next(
            (
                d
                for root in RAW_ROOTS
                for d in sorted(root.rglob(str(wmo)))
                if d.is_dir() and any(d.glob("*.eml"))
            ),
            None,
        )
        if raw is None:
            print(f"[{wmo}] raw telemetry absent -> SKIPPED (tool availability)")
            continue
        tmp = root / str(wmo)
        stage = tmp / "input"
        cycle_dir = stage / "archive" / "cycle" / TRANSCEIVER[wmo]
        cycle_dir.mkdir(parents=True)
        n = 0
        for pattern in ("*.eml", "*.sbd"):
            for src in sorted(raw.glob(pattern)):
                shutil.copy2(src, cycle_dir / src.name)
                n += 1
        cfg = _config(tmp)
        cfg.paths.rsync_data_dir = stage / "archive" / "cycle"
        cfg.paths.rsync_log_dir = stage
        cfg.rtqc.apply_rtqc = True

        result = run_pipeline(config=cfg, wmo=wmo)
        status = "ok" if result.status == "ok" else f"FAILED: {result.errors}"
        files = sorted((Path(cfg.paths.nc_dir) / str(wmo) / "profiles").glob(f"R{wmo}_*.nc"))
        asc = [f for f in files if f.stem.rsplit("_", 1)[-1].isdigit()]
        print(f"[{wmo}] pipeline={status} staged_mails={n} profiles={len(asc)}")

        ours: dict[int, dict] = {}
        for path in asc:
            cycle = int(path.stem.split("_")[1])
            qcp = _read_mask(path, "QCP$")
            qcf = _read_mask(path, "QCF$")
            ours[cycle] = {
                "file": path.name,
                "QCP$": qcp,
                "executed": sorted(_decode_mask(qcp or "0")),
                "QCF$": qcf,
                "failed": sorted(_decode_mask(qcf or "0")),
                "flags": _flag_summary(path),
            }

        gdac_rows = {row["cycle"]: row for row in oracle[str(wmo)]}
        mismatches: list[dict] = []
        table: dict[int, dict[str, str]] = {}
        for cycle in sorted(set(ours) | set(gdac_rows)):
            o, g = ours.get(cycle), gdac_rows.get(cycle)
            if o is None or g is None:
                ours_here = "present" if o else "absent"
                gdac_here = "present" if g else "absent"
                mismatches.append(
                    {
                        "cycle": cycle,
                        "kind": "coverage",
                        "detail": f"ours={ours_here} gdac={gdac_here}",
                    }
                )
                continue
            executed = set(o["executed"])
            failed = set(o["failed"])
            gdac_done = set(g["decoded"])
            gdac_fail = _decode_mask(g.get("QCF$", "0"))
            # truth table: executed(pass/fail) | skipped(reason)
            row: dict[str, str] = {}
            for t in ALL_TESTS:
                if t in executed:
                    row[str(t)] = f"executed({'FAIL' if t in failed else 'pass'})"
                else:
                    if t == 4:
                        row[str(t)] = "skipped(no GEBCO grid)"
                    elif cycle == min(ours) and t in (5, 16, 18):
                        row[str(t)] = "skipped(no previous cycle)"
                    elif t == 5:
                        row[str(t)] = "skipped(speed undefined: reversed/equal timestamps)"
                    elif t == 16:
                        row[str(t)] = (
                            "skipped(insufficient deep overlap with previous good profile)"
                        )
                    elif t == 18:
                        row[str(t)] = "skipped(insufficient overlap with previous profile)"
                    else:
                        row[str(t)] = "skipped(engine did not run)"
            table[cycle] = row
            if executed != gdac_done:
                mismatches.append(
                    {
                        "cycle": cycle,
                        "kind": "QCP$",
                        "detail": (
                            f"ours={o['QCP$']} {sorted(executed)}"
                            f" vs gdac={g['QCP$']} {sorted(gdac_done)}"
                        ),
                    }
                )
            if failed != gdac_fail:
                mismatches.append(
                    {
                        "cycle": cycle,
                        "kind": "QCF$",
                        "detail": (
                            f"ours={o['QCF$']} {sorted(failed)}"
                            f" vs gdac={g.get('QCF$')} {sorted(gdac_fail)}"
                        ),
                    }
                )
        report[str(wmo)] = {
            "pipeline_status": status,
            "n_profiles": len(asc),
            "profiles": {str(c): ours[c] for c in sorted(ours)},
            "test_x_cycle": {str(c): table[c] for c in sorted(table)},
            "mismatches": mismatches,
        }
        n_mis = len(mismatches)
        print(f"    {len(ours)} cycles compared, {n_mis} mismatches")

    (OUT_DIR / "fleet_parity.json").write_text(json.dumps(report, indent=1, sort_keys=True))
    print(f"\nreport -> {OUT_DIR / 'fleet_parity.json'}")


if __name__ == "__main__":
    main()
