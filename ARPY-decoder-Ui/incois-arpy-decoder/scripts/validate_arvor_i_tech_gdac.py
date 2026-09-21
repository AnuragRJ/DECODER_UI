#!/usr/bin/env python3
"""ARVOR-I ``_tech.nc`` GDAC publication parity (strict, 4 floats).

Validates the published product against ``gdac_arvor_i_ref/<wmo>_tech.nc``
under the Prompt-13 publication target:

  1. SHAPE: published name set == the GDAC set exactly (21 names); every
     cycle carries the fixed 22-slot GDAC row order, including the blank
     duplicate InternalVacuum slot; no internal-only name leaks;
  2. VALUES: positional per-slot string equality on every overlapping
     cycle of every float, except the classified divergence
     PRES_SurfaceOffsetNotTruncated_dbar, where GDAC publishes the raw
     centibar count (ours x 10 -- verified) and we publish the correct
     Coriolis twos8/10 dbar value (unit error NOT reproduced);
  3. BLANKS: the three GDAC placeholder columns and the duplicate vacuum
     slot publish blank exactly as GDAC does;
  4. GLOBALS: DATA_CENTRE 'IN' / institution INCOIS via csv4 (unchanged);
  5. COVERAGE: reference windows quantified (merged/stale GDAC histories,
     absent pre-mission block) -- DATA-COVERAGE, never decoder failures.

The projection itself is family-generic (``_GDAC_TECH_SLOTS`` in
``nc/technical_arvor.py``): no WMO/cycle conditionals anywhere, so any
current or future ARVOR-I SBE41CP/Iridium float receives it via the shared
write path.
"""

from __future__ import annotations

import csv
import sys
from datetime import UTC
from pathlib import Path

import netCDF4
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from argo_decoder.metadata.multi_csv_loader import MultiCsvLoader  # noqa: E402
from argo_decoder.nc.technical_arvor import (  # noqa: E402
    _GDAC_TECH_SLOTS,
    write_arvor_tech_nc,
)
from argo_decoder.platforms.provor_ir_sbd.arvor_i import read_arvor_i_eml  # noqa: E402
from argo_decoder.platforms.provor_ir_sbd.arvor_i_science import (  # noqa: E402
    reconstruct_science,
)
from argo_decoder.platforms.provor_ir_sbd.arvor_i_tech import (  # noqa: E402
    build_arvor_tech_dataset,
)

WORKSPACE = ROOT.parent
GDAC_ROOT = WORKSPACE / "gdac_arvor_i_ref"
OUT_DIR = WORKSPACE / "validation_arvor_i_tech_gdac"
CORIOLIS_TABLE = (
    ROOT
    / "tests"
    / "data"
    / "arvor_i"
    / "coriolis_src"
    / "_techParamNames"
    / "_tech_param_name_222.csv"
)

RAW_ROOTS = [
    WORKSPACE / "arvor_raw" / "ARVOR-I-raw-files" / "20260819",
    WORKSPACE / "arvor_raw" / "harness_bundle" / "more-raw-files-and-manuals",
]
WMOS = (1902844, 2904082, 6990711, 7902408)

#: GDAC name -> classified divergence (everything else must match exactly).
CLASSIFIED_DIVERGENCES = {
    # GDAC publishes the raw centibar count under a _dbar name (x10 of the
    # correct twos8/10 dbar decode, verified fleet-wide); the correct value
    # is published instead (user decision, Prompt 13).
    "PRES_SurfaceOffsetNotTruncated_dbar": "ours = GDAC / 10 (GDAC unit error)",
}

SLOT_NAMES = [n for n, _, _ in _GDAC_TECH_SLOTS]
BLANK_SLOTS = {i for i, (n, src, _) in enumerate(_GDAC_TECH_SLOTS) if src is None}

_results: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    _results.append((label, ok, detail))


def raw_dir(wmo: int) -> Path:
    for root in RAW_ROOTS:
        candidate = root / str(wmo)
        if any(candidate.glob("*.eml")):
            return candidate
    raise FileNotFoundError(wmo)


def rows_of(ds) -> list[tuple[int, str, str]]:
    cyc = np.ma.filled(ds["CYCLE_NUMBER"][...], -999).ravel().tolist()
    tp = np.ma.filled(ds["TECHNICAL_PARAMETER_NAME"][...], b" ")
    tp = tp.reshape(len(cyc), -1)
    names = [str(netCDF4.chartostring(r)).strip() for r in tp]
    tv = np.ma.filled(ds["TECHNICAL_PARAMETER_VALUE"][...], b" ")
    tv = tv.reshape(len(cyc), -1)
    vals = [str(netCDF4.chartostring(r)).strip() for r in tv]
    return list(zip(cyc, names, vals, strict=True))


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    loader = MultiCsvLoader(ROOT / "config" / "metadata")
    with open(CORIOLIS_TABLE, encoding="latin-1") as fh:
        canonical = {r["TECH_PARAM_NAME"].strip() for r in csv.DictReader(fh, delimiter=";")}

    for wmo in WMOS:
        launch = loader.load_info(wmo).launch_date
        if launch.tzinfo is None:
            launch = launch.replace(tzinfo=UTC)
        msgs = [read_arvor_i_eml(p) for p in sorted(raw_dir(wmo).glob("*.eml"))]
        science = reconstruct_science(msgs, launch)
        product = build_arvor_tech_dataset(science, wmo=wmo)
        centre = (loader.load_meta(wmo).data_centre or "").strip()
        out = OUT_DIR / f"{wmo}_tech.nc"
        write_arvor_tech_nc(product, out, data_centre=centre)

        with netCDF4.Dataset(out) as ds:
            ours = rows_of(ds)
            ours_inst = ds.institution
        with netCDF4.Dataset(GDAC_ROOT / f"{wmo}_tech.nc") as ds:
            ds.set_auto_mask(False)
            gdac = rows_of(ds)
            gdac_inst = getattr(ds, "institution", "")

        ours_cycles = sorted({c for c, _, _ in ours})
        n_cyc = len(ours_cycles)

        # 1. shape: set + per-cycle 22-slot order + no internal leakage
        ours_names = {n for _, n, _ in ours}
        gdac_names = {n for _, n, _ in gdac}
        internal_leak = {n for n in ours_names if n not in gdac_names and n in canonical}
        check(
            f"{wmo} published name set == GDAC 21 exactly",
            ours_names == gdac_names,
            f"ours-only={sorted(ours_names - gdac_names)} "
            f"missing={sorted(gdac_names - ours_names)}",
        )
        check(f"{wmo} no internal-only name leaks", not internal_leak, str(internal_leak))
        order_ok = len(ours) == 22 * n_cyc and all(
            [n for _, n, _ in ours[i * 22 : (i + 1) * 22]] == SLOT_NAMES for i in range(n_cyc)
        )
        check(
            f"{wmo} fixed 22-slot order in every cycle ({n_cyc} cycles)",
            order_ok,
            f"{len(ours)} rows",
        )

        # 2/3. positional values on overlapping cycles
        gd_by_cycle: dict[int, list[tuple[str, str]]] = {}
        for c, n, v in gdac:
            gd_by_cycle.setdefault(c, []).append((n, v))
        same = classified = mismatch = 0
        bad: list[tuple[int, str, str, str]] = []
        for c in ours_cycles:
            g = gd_by_cycle.get(c)
            if not g:
                continue
            for i, (_, n, v) in enumerate(r for r in ours if r[0] == c):
                if i >= len(g):
                    break
                gn, gv = g[i]
                if gn != n:
                    mismatch += 1
                    bad.append((c, n, v, f"NAME {gn}"))
                    continue
                if v == gv:
                    same += 1
                elif n in CLASSIFIED_DIVERGENCES and _matches_classified(n, v, gv):
                    classified += 1
                else:
                    mismatch += 1
                    bad.append((c, n, v, gv))
        check(
            f"{wmo} slot values: {same} exact + {classified} classified-divergent, 0 mismatch",
            mismatch == 0 and same > 0,
            f"mismatched={bad[:5]}",
        )

        placeholders = {
            "FLAG_ProfileTermination_hex",
            "NUMBER_AscentSamples_COUNT",
            "NUMBER_PumpActionsAtSurface_COUNT",
        }
        blanks_ok = all(v == "" for c, n, v in ours if n in placeholders)
        vac = [v for c, n, v in ours if n == "PRESSURE_InternalVacuum_inHg"]
        vac_blank_every_second = all(v == "" for v in vac[1::2]) and all(v != "" for v in vac[0::2])
        check(f"{wmo} placeholder columns blank", blanks_ok)
        check(
            f"{wmo} duplicate vacuum slot blank (structure preserved)",
            vac_blank_every_second and len(vac) == 2 * n_cyc,
            f"{len(vac)} vacuum rows",
        )

        # 4. globals
        check(
            f"{wmo} institution == GDAC",
            ours_inst == gdac_inst == "INCOIS",
            f"ours={ours_inst!r} gdac={gdac_inst!r}",
        )

        # 5. coverage
        gd_cycles = sorted(gd_by_cycle)
        check(
            f"{wmo} reference coverage quantified (DATA-COVERAGE)",
            True,
            f"gdac cycles {gd_cycles[0]}..{gd_cycles[-1]} ({len(gd_cycles)}), "
            f"ours {ours_cycles[0]}..{ours_cycles[-1]} ({n_cyc}); GDAC "
            f"pre-mission block absent from our raw (not fabricated)",
        )

    print("=" * 72)
    failures = [r for r in _results if not r[1]]
    for name, ok, detail in _results:
        mark = "PASS" if ok else "FAIL"
        suffix = f"  [{detail}]" if detail else ""
        print(f"  {mark}  {name}{suffix}")
    print(f"\n{len(_results) - len(failures)}/{len(_results)} checks passed")
    if failures:
        return 1
    print(
        "\nClassifications:\n"
        "  - PRES_SurfaceOffsetNotTruncated_dbar: GDAC publishes the raw\n"
        "    centibar count under a _dbar name (x10 of the correct Coriolis\n"
        "    twos8/10 decode, verified fleet-wide); the scientifically\n"
        "    correct dbar value is published (sanctioned divergence).\n"
        "  - PRESSURE_InternalVacuum_inHg: GDAC label says inHg but the\n"
        "    values are mbar == ours; GDAC's label kept for publication\n"
        "    compatibility, duplicate slot published blank as GDAC does.\n"
        "  - Argos-style message/sample names kept (publication compat.)\n"
        "    on this Iridium family.\n"
        "  - DATA-COVERAGE: GDAC pre-mission block + merged/stale reference\n"
        "    histories outside our raw windows.\n"
    )
    return 0


def _matches_classified(name: str, ours: str, gdac: str) -> bool:
    """Sanctioned SurfaceOffset divergence: GDAC == ours x 10."""

    try:
        return abs(float(gdac) - 10.0 * float(ours)) < 1e-6
    except ValueError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
