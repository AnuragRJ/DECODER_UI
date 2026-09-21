#!/usr/bin/env python3
"""Formal Phase 4A validation: ARVOR-I ``_tech.nc`` for floats 6990711 / 7902408.

Checks (mapping report §7.1 expectations):
  1. row counts 467 / 804 and per-cycle breakdown;
  2. parameter-id sets exactly as derived (no 135/214-221/223-226/243, no
     TECH_AUX/META rows in the file);
  3. cycle ordering ascending, within-cycle alphabetical by name;
  4. spot values re-derived independently from Tech#1/Tech#2 fields;
  5. written netCDF layout: NETCDF3_CLASSIC, dims, var order, dtypes,
     global/variable attrs, SPACE padding, unmasked round-trip equality;
  6. aux rows bookkept (99 / 208) — not silently discarded.

Writes both files to ``validation_phase4a_tech/`` next to the workspace
root and prints a PASS/FAIL ledger. Exit code 0 only if every check passes.
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import netCDF4
import numpy as np

from argo_decoder.nc.technical_arvor import (
    _GDAC_TECH_SLOTS,
    arvor_tech_publication_rows,
    write_arvor_tech_nc,
)
from argo_decoder.platforms.provor_ir_sbd.arvor_i import (
    counts_to_pres,
    read_arvor_i_eml,
    twos_complement,
)
from argo_decoder.platforms.provor_ir_sbd.arvor_i_science import reconstruct_science
from argo_decoder.platforms.provor_ir_sbd.arvor_i_tech import (
    build_arvor_tech_dataset,
    format_hhmm_dec_argo,
    format_mmss_dec_argo,
)

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
RAW_ROOT = WORKSPACE / "arvor_raw" / "ARVOR-I-raw-files" / "20260819"
OUT_DIR = WORKSPACE / "validation_phase4a_tech"

LAUNCHES = {
    6990711: datetime(2025, 3, 2, 5, 16, tzinfo=UTC),
    7902408: datetime(2026, 3, 25, 17, 44, tzinfo=UTC),
}

EXPECTED = {
    6990711: {
        "n_tech": 467,
        "n_aux": 99,
        "cycles": {c: (67 if c in (1, 2, 3, 4, 7) else 66) for c in range(1, 8)},
        "param136_cycles": {1, 2, 3, 4, 7},
    },
    7902408: {
        "n_tech": 804,
        # aux grew 182 -> 208 on 2026-08-27: trailing-buffer cycles 14/15
        # now emit TECH_AUX rows (+13/+14) and cycle 13's ParameterMessage2
        # count row is re-attributed to cycle 15 (production default
        # process_remaining_buffers=True)
        "n_aux": 208,
        "cycles": {c: 67 for c in range(1, 13)},
        "param136_cycles": set(range(1, 13)),
    },
}

VAR_ORDER = [
    "PLATFORM_NUMBER",
    "DATA_TYPE",
    "FORMAT_VERSION",
    "HANDBOOK_VERSION",
    "DATA_CENTRE",
    "DATE_CREATION",
    "DATE_UPDATE",
    "TECHNICAL_PARAMETER_NAME",
    "TECHNICAL_PARAMETER_VALUE",
    "CYCLE_NUMBER",
]

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))


def build(wmo: int):
    msgs = [read_arvor_i_eml(p) for p in sorted((RAW_ROOT / str(wmo)).glob("*.eml"))]
    science = reconstruct_science(msgs, LAUNCHES[wmo])
    return science, build_arvor_tech_dataset(science, wmo=wmo)


def validate_dataset(wmo: int, science, ds) -> Path:
    exp = EXPECTED[wmo]
    rows = ds.tech_rows
    check(
        f"{wmo}: tech row count == {exp['n_tech']}", len(rows) == exp["n_tech"], f"got {len(rows)}"
    )
    check(
        f"{wmo}: aux rows bookkept == {exp['n_aux']}",
        len(ds.aux_rows) == exp["n_aux"],
        f"got {len(ds.aux_rows)}",
    )

    per = Counter(r.cycle_number for r in rows)
    check(f"{wmo}: per-cycle counts", dict(per) == exp["cycles"], str(dict(per)))
    check(
        f"{wmo}: no cycle outside {min(exp['cycles'])}-{max(exp['cycles'])}",
        set(per) == set(exp["cycles"]),
    )

    ids = {r.param_id for r in rows}
    expected_ids = (
        set(range(100, 135)) | {136} | set(range(200, 214)) | {213, 222} | set(range(227, 243))
    )
    check(
        f"{wmo}: parameter-id set exact",
        ids == expected_ids,
        f"missing {sorted(expected_ids - ids)}, extra {sorted(ids - expected_ids)}",
    )
    for pid, why in (
        (135, "EOL flag never set"),
        (243, "no type-7 packet"),
        (214, "no grounding"),
        (223, "no emergency ascent"),
    ):
        check(f"{wmo}: param {pid} absent ({why})", pid not in ids)
    check(f"{wmo}: no 215-221/224-226", not (set(range(215, 222)) | set(range(224, 227))) & ids)

    p136 = {r.cycle_number for r in rows if r.param_id == 136}
    check(
        f"{wmo}: param 136 on GPS-valid cycles",
        p136 == exp["param136_cycles"],
        f"got {sorted(p136)}",
    )

    cycles = [r.cycle_number for r in rows]
    check(f"{wmo}: cycles ascending", cycles == sorted(cycles))
    alphabetical = all(
        [r.name for r in rows[a:b]] == sorted(r.name for r in rows[a:b])
        for a, b in _cycle_spans(rows)
    )
    check(f"{wmo}: within-cycle alphabetical", alphabetical)
    check(
        f"{wmo}: no TECH_AUX/META names in file rows",
        all(not r.name.startswith(("TECH_AUX", "META_")) for r in rows),
    )

    # independent value spot-checks, cycle 1
    cyc = next(c for c in science.cycles if c.cycle_number == 1)
    t1, t2 = cyc.tech1.fields, cyc.tech2.fields
    by_id = {r.param_id: r.value for r in rows if r.cycle_number == 1}
    spot = {
        100: f"{t1[7] + 2000:04d}{t1[6]:02d}{t1[5]:02d}",
        101: str(t1[8]),
        102: format_hhmm_dec_argo(t1[9]),
        111: f"{t1[20]:02d}",
        127: f"{twos_complement(t1[47], 8) / 10:g}",
        128: str(t1[48] * 5),
        129: f"{15 - t1[49] / 10:g}",
        132: str(t1[62]),
        200: str(t2[3]),
        204: str(t2[7]),
        212: f"{counts_to_pres(t2[15]):g}",
        236: (f"{t2[51] + 2000:04d}{t2[50]:02d}{t2[49]:02d}{t2[46]:02d}{t2[47]:02d}{t2[48]:02d}"),
        242: str(t2[57]),
    }
    bad = {k: (by_id.get(k), v) for k, v in spot.items() if by_id.get(k) != v}
    check(f"{wmo}: cycle-1 spot values ({len(spot)} params)", not bad, str(bad))
    if 136 in by_id:
        ok136 = by_id[136] == format_mmss_dec_argo(twos_complement(t1[73], 16))
        check(f"{wmo}: cycle-1 param 136 value", ok136)

    # final row: last cycle, alphabetically-last name (final order is
    # cycle-ascending then alphabetical; packet counts sit inside the
    # cycle as NUMBER_*_COUNT rows, not at the end)
    last_cycle_rows = [r for r in rows if r.cycle_number == max(per)]
    last = rows[-1]
    check(
        f"{wmo}: final row on last cycle, alphabetically last name",
        last.cycle_number == max(per) and last.name == max(r.name for r in last_cycle_rows),
    )
    check(
        f"{wmo}: packet counts present on last cycle",
        any(r.name.startswith("NUMBER_") for r in last_cycle_rows),
    )

    # ---- write + re-read -------------------------------------------------
    # The published file carries the GDAC-shape projection of the internal
    # rows (Prompt 13); the internal model itself is validated above.
    published = arvor_tech_publication_rows(rows, ds.float_times)
    slot_names = [n for n, _, _ in _GDAC_TECH_SLOTS]
    check(
        f"{wmo}: publication = 22 fixed GDAC slots per cycle",
        len(published) == 22 * len(exp["cycles"])
        and all(
            [r.name for r in published[i * 22 : (i + 1) * 22]] == slot_names
            for i in range(len(published) // 22)
        ),
        f"{len(published)} rows",
    )
    path = OUT_DIR / f"{wmo}_tech.nc"
    write_arvor_tech_nc(ds, path, date_creation="20260827000000", date_update="20260827000000")
    nc = netCDF4.Dataset(path)
    check(f"{wmo}: NETCDF3_CLASSIC", nc.data_model == "NETCDF3_CLASSIC")
    check(
        f"{wmo}: dim order",
        list(nc.dimensions)
        == ["DATE_TIME", "STRING128", "STRING32", "STRING8", "STRING4", "STRING2", "N_TECH_PARAM"],
    )
    check(f"{wmo}: N_TECH_PARAM unlimited", nc.dimensions["N_TECH_PARAM"].isunlimited())
    check(f"{wmo}: var order", list(nc.variables) == VAR_ORDER)
    nc.set_auto_mask(False)
    check(
        f"{wmo}: header values",
        bytes(nc["PLATFORM_NUMBER"][:]).decode().rstrip() == str(wmo)
        and bytes(nc["DATA_TYPE"][:]).decode().rstrip() == "Argo technical data"
        and bytes(nc["FORMAT_VERSION"][:]).decode().rstrip() == "3.1"
        and bytes(nc["HANDBOOK_VERSION"][:]) == b"1.2 "
        and bytes(nc["DATA_CENTRE"][:]) == b"  ",
    )
    check(f"{wmo}: CYCLE_NUMBER int32", nc["CYCLE_NUMBER"].dtype == np.int32)
    names = [bytes(r).decode("ascii").rstrip() for r in nc["TECHNICAL_PARAMETER_NAME"][:]]
    values = [bytes(r).decode("ascii").rstrip() for r in nc["TECHNICAL_PARAMETER_VALUE"][:]]
    check(
        f"{wmo}: file rows == published projection rows",
        names == [r.name for r in published]
        and values == [r.value for r in published]
        and np.asarray(nc["CYCLE_NUMBER"][:]).tolist() == [r.cycle_number for r in published],
    )
    padded = bytes(nc["TECHNICAL_PARAMETER_NAME"][0])
    tail = padded[len(padded.rstrip()) :]
    check(f"{wmo}: SPACE padding (no NULs)", set(tail) <= {0x20} and len(tail) > 0)
    check(
        f"{wmo}: history stamp format",
        nc.history.endswith(" (coriolis float real time data processing)"),
    )
    nc.close()
    return path


def _cycle_spans(rows):
    start = 0
    for i in range(1, len(rows) + 1):
        if i == len(rows) or rows[i].cycle_number != rows[start].cycle_number:
            yield start, i
            start = i


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    for wmo in (6990711, 7902408):
        science, ds = build(wmo)
        validate_dataset(wmo, science, ds)

    print(f"\n{'CHECK':<58} RESULT")
    print("-" * 72)
    fails = 0
    for name, ok, detail in results:
        print(f"{name:<58} {'PASS' if ok else 'FAIL'}  {detail if not ok else ''}")
        fails += not ok
    print("-" * 72)
    print(f"{len(results) - fails}/{len(results)} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
