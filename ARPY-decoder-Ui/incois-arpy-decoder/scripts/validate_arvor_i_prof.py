#!/usr/bin/env python3
"""Formal Phase 5 validation: ARVOR-I mono-profiles ``R*.nc`` for 6990711 / 7902408.

Checks (mapping report ARVOR_I_MONO_PROFILE_MAPPING_2026-08-27.md §7/§8 +
first-run refinements recorded in IMPLEMENTATION_PROGRESS.md 2026-08-27):
  1. one ascent record per in-raw cycle, direct cycle numbering, filenames
     R<WMO>_<NNN>.nc; no descent files (publication policy; capability
     verified by unit/integration tests via the explicit flag);
  2. level counts == GDAC for all 22 in-raw reference files, and
     PRES/TEMP/PSAL arrays bit-exact (float32) vs GDAC;
  3. JULD == first non-pre-launch mail time: exact (<=0.5 s) vs GDAC on
     retransmitted/trailing cycles; within the classified production
     reception skew (<=35 s) on fresh cycles; 6990711 c5 classified
     (missing April mails in the raw snapshot);
  4. positions: Tech#1 GPS truncated to arc-minutes == GDAC on GPS files;
     first usable Iridium mail fix == GDAC on IRIDIUM files (c5 6990711
     classified: GDAC stale-fix reuse + missing mails);
  5. per-level QC '0' + PROFILE_<P>_QC ' ' (Coriolis semantics), fills,
     VSS constant, CONFIG_MISSION_NUMBER fill, adjusted blocks all-fill;
  6. written layout: NETCDF3_CLASSIC, 64 variables in exact GDAC order,
     dtypes and per-variable attrs equal, dims N_PROF=1/N_PARAM=3/
     N_CALIB=1/N_HISTORY unlimited, 8 standard globals, SPACE padding.

Writes the products to ``validation_phase5_prof/<wmo>/`` next to the
workspace root and prints a PASS/FAIL ledger plus the classified
publication-layer divergence set.  Exit code 0 only if every check passes.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import netCDF4
import numpy as np

from argo_decoder.platforms.provor_ir_sbd.arvor_i import read_arvor_i_eml
from argo_decoder.platforms.provor_ir_sbd.arvor_i_prof import (
    build_arvor_mono_profiles,
    write_arvor_mono_profiles,
)
from argo_decoder.platforms.provor_ir_sbd.arvor_i_science import reconstruct_science

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
RAW_ROOT = WORKSPACE / "arvor_raw" / "ARVOR-I-raw-files" / "20260819"
REF_ROOT = WORKSPACE / "gdac_arvor_i_ref" / "profiles"
OUT_ROOT = WORKSPACE / "validation_phase5_prof"

LAUNCHES = {
    6990711: datetime(2025, 3, 2, 5, 16, tzinfo=UTC),
    7902408: datetime(2026, 3, 25, 17, 44, tzinfo=UTC),
}
EPOCH = datetime(1950, 1, 1, tzinfo=UTC)

# JULD must equal GDAC to the second on these (retransmitted/trailing).
JULD_EXACT = {(6990711, 6), (7902408, 13), (7902408, 14), (7902408, 15)}
# Classified divergences (not forced; see ledger).
JULD_CLASSIFIED = {(6990711, 5)}  # missing April mails (DATA-COVERAGE)
POS_CLASSIFIED = {(6990711, 5)}  # GDAC stale c4 fix reuse + missing mails

_pass = 0
_fail = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global _pass, _fail
    status = "PASS" if ok else "FAIL"
    if ok:
        _pass += 1
    else:
        _fail += 1
    suffix = f"  [{detail}]" if detail and not ok else ""
    print(f"  {status:4s}  {label}{suffix}")


def char(d: netCDF4.Dataset, name: str) -> str:
    return bytes(np.asarray(d[name][:]).reshape(-1)).decode().rstrip()


def main() -> int:
    print("=" * 72)
    for wmo in (6990711, 7902408):
        msgs = [read_arvor_i_eml(p) for p in sorted((RAW_ROOT / str(wmo)).glob("*.eml"))]
        result = reconstruct_science(msgs, LAUNCHES[wmo])
        records = build_arvor_mono_profiles(result, wmo=wmo)
        written = write_arvor_mono_profiles(records, OUT_ROOT / str(wmo))

        asc = {r.cycle: r for r in records if r.direction == "A"}
        print(f"\n===== {wmo}: {len(records)} records, {len(written)} files")
        check(
            f"{wmo}: ascent-only publication (no D files)", all(r.direction == "A" for r in records)
        )
        check(
            f"{wmo}: direct cycle numbering + filenames",
            all(r.filename == f"R{wmo}_{r.cycle:03d}.nc" for r in records)
            and sorted(asc) == list(range(1, len(records) + 1)),
        )

        n_array_exact = 0
        n_pos_exact = 0
        n_juld_exact = 0
        n_juld_skew = 0.0
        for ref in sorted((REF_ROOT / str(wmo)).glob("R*.nc")):
            n = int(ref.stem.split("_")[1].rstrip("D"))
            ours_path = OUT_ROOT / str(wmo) / ref.name
            g = netCDF4.Dataset(ref)
            g.set_auto_mask(False)
            try:
                if n not in asc:
                    check(
                        f"{wmo} _{n:03d}: beyond raw snapshot -> not produced",
                        not ours_path.exists(),
                    )
                    continue
                rec = asc[n]
                d = netCDF4.Dataset(ours_path)
                d.set_auto_mask(False)
                try:
                    # --- structure ---
                    ok_struct = (
                        d.data_model == "NETCDF3_CLASSIC"
                        and list(d.variables) == list(g.variables)
                        and len(d.variables) == 64
                        and all(d[v].dtype == g[v].dtype for v in d.variables)
                        and len(d.dimensions["N_PROF"]) == 1
                        and len(d.dimensions["N_PARAM"]) == 3
                        and len(d.dimensions["N_CALIB"]) == 1
                        and d.dimensions["N_HISTORY"].isunlimited()
                        and len(d.dimensions["N_LEVELS"]) == len(g.dimensions["N_LEVELS"])
                        and sorted(d.ncattrs()) == sorted(g.ncattrs())
                    )
                    attr_diffs = (
                        [
                            (v, a)
                            for v in d.variables
                            for a in d[v].ncattrs()
                            if _attr(d, v, a) != _attr(g, v, a)
                        ]
                        if ok_struct
                        else _all_attr_diffs(d, g)
                    )
                    check(f"{wmo} _{n:03d}: layout (format/order/dtypes/dims/globals)", ok_struct)
                    check(
                        f"{wmo} _{n:03d}: per-variable attrs identical",
                        not attr_diffs,
                        str(attr_diffs[:3]),
                    )

                    # --- science values ---
                    arrays_exact = all(
                        np.array_equal(rec.dataset[p].values.reshape(-1), np.asarray(g[p][0]))
                        for p in ("PRES", "TEMP", "PSAL")
                    )
                    n_array_exact += arrays_exact
                    check(
                        f"{wmo} _{n:03d}: PRES/TEMP/PSAL bit-exact ({rec.n_levels} lev)",
                        arrays_exact and rec.n_levels == len(g.dimensions["N_LEVELS"]),
                    )

                    # --- header values ---
                    dt_s = abs(rec.juld - float(g["JULD"][0])) * 86400.0
                    if (wmo, n) in JULD_CLASSIFIED:
                        check(
                            f"{wmo} _{n:03d}: JULD classified (DATA-COVERAGE mails)",
                            True,
                            f"dt={dt_s:.0f}s",
                        )
                    elif (wmo, n) in JULD_EXACT:
                        n_juld_exact += dt_s <= 0.5
                        check(
                            f"{wmo} _{n:03d}: JULD first-mail exact", dt_s <= 0.5, f"dt={dt_s:.2f}s"
                        )
                    else:
                        n_juld_skew = max(n_juld_skew, dt_s)
                        check(
                            f"{wmo} _{n:03d}: JULD within production skew",
                            dt_s <= 35.0,
                            f"dt={dt_s:.2f}s",
                        )

                    pos_ok = (
                        abs(
                            float(rec.dataset["LATITUDE"].values.reshape(-1)[0])
                            - float(g["LATITUDE"][0])
                        )
                        < 5e-6
                        and abs(
                            float(rec.dataset["LONGITUDE"].values.reshape(-1)[0])
                            - float(g["LONGITUDE"][0])
                        )
                        < 5e-6
                        and rec.positioning_system == char(g, "POSITIONING_SYSTEM").strip()
                    )
                    if (wmo, n) in POS_CLASSIFIED:
                        check(f"{wmo} _{n:03d}: position classified (GDAC stale fix)", True)
                    else:
                        n_pos_exact += pos_ok
                        check(
                            f"{wmo} _{n:03d}: lat/lon/PSYS exact "
                            f"({rec.positioning_system.strip()})",
                            pos_ok,
                        )

                    dc = bytes(np.asarray(d["DATE_CREATION"][:])).decode()
                    want_dc = (EPOCH + timedelta(seconds=float(d["JULD"][0]) * 86400.0)).strftime(
                        "%Y%m%d%H%M%S"
                    )
                    check(
                        f"{wmo} _{n:03d}: DATE_CREATION == JULD",
                        dc == want_dc and char(d, "DC_REFERENCE").strip() == f"{wmo}/{n}",
                    )
                    check(
                        f"{wmo} _{n:03d}: DIRECTION/DATA_MODE/JULD_LOCATION/QC flags",
                        d["DIRECTION"][0] == b"A"
                        and d["DATA_MODE"][0] == b"R"
                        and d["JULD_LOCATION"][0] == d["JULD"][0]
                        and d["JULD_QC"][0] == b"1"
                        and d["POSITION_QC"][0] == b"1",
                    )
                    nlev = len(d.dimensions["N_LEVELS"])
                    qc_ok = all(
                        list(np.asarray(d[f"{p}_QC"][:]).reshape(-1)) == [b"0"] * nlev
                        and d[f"PROFILE_{p}_QC"][0] == b" "
                        for p in ("PRES", "TEMP", "PSAL")
                    )
                    adj_ok = all(
                        bool(np.all(np.asarray(d[v][0]) == 99999.0))
                        for v in (
                            "PRES_ADJUSTED",
                            "TEMP_ADJUSTED",
                            "PSAL_ADJUSTED",
                            "PRES_ADJUSTED_ERROR",
                            "TEMP_ADJUSTED_ERROR",
                            "PSAL_ADJUSTED_ERROR",
                        )
                    )
                    check(f"{wmo} _{n:03d}: Coriolis QC '0'/' ' + adjusted fills", qc_ok and adj_ok)
                    check(
                        f"{wmo} _{n:03d}: VSS constant + CONFIG_MISSION_NUMBER fill",
                        char(d, "VERTICAL_SAMPLING_SCHEME").strip()
                        == "Primary sampling: averaged []"
                        and int(d["CONFIG_MISSION_NUMBER"][0]) == 99999,
                    )
                finally:
                    d.close()
            finally:
                g.close()

        n_refs = len(list((REF_ROOT / str(wmo)).glob("R*.nc")))
        n_inraw = len(asc)
        check(
            f"{wmo}: arrays exact on all in-raw refs",
            n_array_exact == n_inraw,
            f"{n_array_exact}/{n_inraw}",
        )
        check(
            f"{wmo}: positions exact except classified set",
            n_pos_exact == n_inraw - len({c for (wm, c) in POS_CLASSIFIED if wm == wmo}),
            f"{n_pos_exact} exact",
        )
        print(
            f"  [info] {wmo}: {n_refs} GDAC refs; {n_inraw} produced; "
            f"JULD exact on {len([1 for (wm, c) in JULD_EXACT if wm == wmo])}, "
            f"max fresh skew {n_juld_skew:.0f}s"
        )

    print("\n" + "=" * 72)
    print(f"{_pass}/{_pass + _fail} checks passed")
    if _fail:
        return 1
    print(
        "\nClassified publication-layer differences (NOT reproduced; ledger):\n"
        "  - GDAC level QC '1'/'A' + one TEMP '3' (R7902408_011 lev 28): INCOIS\n"
        "    RTQC re-flags (TOOL-AVAILABILITY); ours: Coriolis '0'/' '.\n"
        "  - CONFIG_MISSION_NUMBER 1 on GDAC (production USE table): ours fill.\n"
        "  - Metadata strings (PROJECT/PI/serial/FW/WMO_INST_TYPE/DATA_CENTRE),\n"
        "    institution=INCOIS, INQC HISTORY rows (N_HISTORY 6 vs ours 2),\n"
        "    DATE_UPDATE batches: float-json/DAC publication metadata.\n"
        "  - Fresh-cycle JULD 7-32 s before our mail Date: header (production\n"
        "    reception timestamp; mapping §4 quantified).\n"
        "  - 6990711 c5: JULD/position (April mails missing from raw snapshot\n"
        "    DATA-COVERAGE; GDAC reused cycle-4 GPS fix).\n"
        "  - R7902408_016 beyond raw snapshot (DATA-COVERAGE).\n"
        "  - No R*_001D.nc published by GDAC though c1 descents exist in raw\n"
        "    (UNKNOWN publication/production): descent emission suppressed by\n"
        "    explicit policy flag PUBLISH_DESCENT_PROFILES=False."
    )
    return 0


def _attr(d: netCDF4.Dataset, v: str, a: str) -> object:
    value = d[v].getncattr(a)
    return value.decode() if isinstance(value, bytes) else value


def _all_attr_diffs(d: netCDF4.Dataset, g: netCDF4.Dataset) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for v in d.variables:
        for a in d[v].ncattrs():
            if _attr(d, v, a) != _attr(g, v, a):
                out.append((v, a))
    return out


if __name__ == "__main__":
    sys.exit(main())
