"""Test-level RTQC execution harness for ARVOR-I decoded mono products.

Standalone diagnosis tool -- deliberately NOT wired into the production
decoder.  It takes existing decoded mono-profile products (``R*.nc``) and
runs the 15-test applicable real-time QC set test-by-test:

    1, 2, 3, 4, 5, 6, 8, 9, 11, 12, 13, 14, 16, 18, 19

(Test 7 region-conditional, 15 DAC-managed exclusion list and 20 Argos-only
are reported as skipped/not-applicable with reasons, never executed and
never counted as passed -- mirroring the INCOIS GDAC practice proven by the
``QCP$``/``D7B7E`` masks in the published reference files.)

For every test and cycle the harness reports one of:

* ``executed`` -> ``passed`` or ``failed`` (never both),
* ``skipped``  -> with an explicit reason and the missing input.

Resulting per-level QC flags, the truthful ``QCP$`` mask (tests actually
executed) and ``QCF$`` mask (tests failed) are emitted per profile, plus an
informational side-by-side with the GDAC-published masks when the
``gdac_qcp_masks.json`` oracle artifact exists.

Inputs are generic: WMOs come from the command line, launch metadata from
the four authoritative CSVs (``MultiCsvLoader``), the test-19 configuration
pressure from the decoded ``_meta.nc`` product.  No WMO-specific logic, no
registry.csv dependency.  When the products do not exist yet they are
regenerated into /tmp (regenerable) through the validated platform
pipeline; the provenance is recorded in the output.

Usage:
    python scripts/rtqc_harness.py --wmo 1902844 2904082 6990711 7902408 \\
        [--products-root DIR] [--gebco PATH] [--out DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from argo_decoder.metadata.multi_csv_loader import MultiCsvLoader  # noqa: E402
from argo_decoder.rtqc.bathymetry import open_gebco  # noqa: E402
from argo_decoder.rtqc.cross_cycle import (  # noqa: E402
    DRIFT_THRESHOLD_PSAL,
    DRIFT_THRESHOLD_TEMP,
    frozen_profile_test,
    gross_sensor_drift_test,
    impossible_speed_test,
)
from argo_decoder.rtqc.density_inversion import density_inversion_test  # noqa: E402
from argo_decoder.rtqc.non_density import (  # noqa: E402
    GLOBAL_RANGE,
    GRADIENT_THRESHOLD_DEEP,
    GRADIENT_THRESHOLD_SHALLOW,
    SPIKE_THRESHOLD_DEEP,
    SPIKE_THRESHOLD_SHALLOW,
    deepest_pressure_test,
    digit_rollover_test,
    global_range_test,
    gradient_test,
    pressure_increasing_test,
    spike_test,
    stuck_value_test,
)
from argo_decoder.rtqc.profile_scalar import run_profile_scalar_tests  # noqa: E402

WORKSPACE = ROOT.parent
#: Raw-telemetry search roots (first one holding <wmo>/*.eml wins).
RAW_ROOTS = [
    WORKSPACE / "arvor_raw" / "ARVOR-I-raw-files" / "20260819",
    Path("/tmp/rtqc_harness_bundle"),
]
METADATA_DIR = ROOT / "config" / "metadata"
DEFAULT_OUT = ROOT / "validation_rtqc_harness"

#: Argo reference table 11 test numbers (permanent identifiers).
TEST_NUMBERS: dict[str, int] = {
    "platform_identification": 1,
    "impossible_date": 2,
    "impossible_location": 3,
    "position_on_land": 4,
    "impossible_speed": 5,
    "global_range": 6,
    "regional_range": 7,
    "pressure_increasing": 8,
    "spike": 9,
    "gradient": 11,
    "digit_rollover": 12,
    "stuck_value": 13,
    "density_inversion": 14,
    "exclusion_list": 15,
    "gross_sensor_drift": 16,
    "frozen_profile": 18,
    "deepest_pressure": 19,
    "questionable_argos_position": 20,
}
APPLICABLE = sorted({1, 2, 3, 4, 5, 6, 8, 9, 11, 12, 13, 14, 16, 18, 19})

#: Tests intentionally NOT executed for this family, with public reasons.
NOT_APPLICABLE = {
    7: "region-conditional (Red Sea/Mediterranean only); float positions outside "
    "both regions -- INCOIS does not report it (absent from D7B7E)",
    15: "DAC-managed exclusion-list mechanism; no list supplied to the harness "
    "(empty list = no-op) -- INCOIS does not report it (absent from D7B7E)",
    20: "Argos-only questionable-position test; fleet is Iridium SBD",
}

ENGINE_CONFIG = {
    "global_range": {k: list(v) for k, v in GLOBAL_RANGE.items()},
    "spike_thresholds": {
        "shallow": dict(SPIKE_THRESHOLD_SHALLOW),
        "deep": dict(SPIKE_THRESHOLD_DEEP),
    },
    "gradient_thresholds": {
        "shallow": dict(GRADIENT_THRESHOLD_SHALLOW),
        "deep": dict(GRADIENT_THRESHOLD_DEEP),
    },
    "drift_thresholds": {"TEMP": DRIFT_THRESHOLD_TEMP, "PSAL": DRIFT_THRESHOLD_PSAL},
}


def encode_mask(numbers: set[int]) -> str:
    """Bit n = test n (LSB unused), hex uppercase -- get_qctest_flag.m convention."""
    mask = 0
    for n in numbers:
        mask |= 1 << int(n)
    return format(mask, "X") if mask else "0"


def _col(ds, name: str) -> np.ndarray:
    v = ds.variables[name][:]
    return np.ma.filled(v, np.nan).astype("f8").reshape(-1)


def read_mono_product(path: Path) -> dict:
    """Extract the RTQC-relevant arrays from one decoded mono product."""
    import netCDF4

    ds = netCDF4.Dataset(path)
    try:
        pres, temp, psal = (_col(ds, n) for n in ("PRES", "TEMP", "PSAL"))
        return {
            "file": path.name,
            "cycle": int(_col(ds, "CYCLE_NUMBER")[0]),
            "juld": float(_col(ds, "JULD")[0]),
            "lat": float(_col(ds, "LATITUDE")[0]),
            "lon": float(_col(ds, "LONGITUDE")[0]),
            "pres": pres,
            "temp": temp,
            "psal": psal,
        }
    finally:
        ds.close()


def build_meta(wmo: int, launch, result, meta_json_path):
    from argo_decoder.platforms.provor_ir_sbd.arvor_i_meta import build_arvor_meta_nc

    return build_arvor_meta_nc(
        wmo=wmo, launch_date=launch, result=result, meta_json_path=meta_json_path
    )


def decode_products(wmo: int, out_dir: Path, loader: MultiCsvLoader) -> dict[str, Path]:
    """Regenerate the mono products through the validated pipeline (into /tmp)."""
    from argo_decoder.platforms.provor_ir_sbd.arvor_i import read_arvor_i_eml
    from argo_decoder.platforms.provor_ir_sbd.arvor_i_prof import (
        build_arvor_mono_profiles,
        write_arvor_mono_profiles,
    )
    from argo_decoder.platforms.provor_ir_sbd.arvor_i_science import reconstruct_science

    raw_dir = next(
        (
            d
            for root in RAW_ROOTS
            for d in sorted(root.rglob(str(wmo)))
            if d.is_dir() and any(d.glob("*.eml"))
        ),
        None,
    )
    if raw_dir is None:
        raise SystemExit(f"no raw telemetry found for {wmo} under any of {RAW_ROOTS}")
    msgs = [read_arvor_i_eml(p) for p in sorted(raw_dir.glob("*.eml"))]
    info = loader.load_info(wmo)
    launch = info.launch_date
    if launch.tzinfo is None:  # CSV sheet datetimes are naive; anchor them to UTC
        launch = launch.replace(tzinfo=UTC)
    result = reconstruct_science(msgs, launch)
    records = build_arvor_mono_profiles(result, wmo=wmo)
    written = write_arvor_mono_profiles(records, out_dir / str(wmo))
    from argo_decoder.platforms.provor_ir_sbd.arvor_i_meta import write_arvor_meta_nc

    loader.load_meta(wmo)  # materializes <wmo>_meta.json via materialized_dir
    meta_json = out_dir / "float_meta" / f"{wmo}_meta.json"
    meta = build_meta(wmo=wmo, launch=launch, result=result, meta_json_path=meta_json)
    write_arvor_meta_nc(meta, out_dir / str(wmo) / f"{wmo}_meta.nc")
    return written


def meta_profile_pressure(wmo: int, meta_nc: Path | None) -> tuple[float | None, str]:
    """CONFIG_ProfilePressure_dbar from the decoded meta product (test-19 input)."""
    if meta_nc is None or not meta_nc.exists():
        return None, "decoded _meta.nc product not available"
    import netCDF4

    ds = netCDF4.Dataset(meta_nc)
    try:
        if "CONFIG_PARAMETER_NAME" not in ds.variables:
            return None, f"{meta_nc.name}: no CONFIG_PARAMETER block"
        names = np.atleast_1d(
            np.ma.filled(netCDF4.chartostring(ds["CONFIG_PARAMETER_NAME"][:]), "")
        ).reshape(-1)
        values = np.atleast_1d(np.ma.filled(ds["CONFIG_PARAMETER_VALUE"][:], np.nan)).reshape(-1)
        for name, value in zip(names, values, strict=False):
            if str(name).strip() == "CONFIG_ProfilePressure_dbar" and np.isfinite(value):
                return float(value), str(meta_nc.name)
    except (ValueError, KeyError) as exc:
        return None, f"{meta_nc.name}: {exc}"
    finally:
        ds.close()
    return None, f"{meta_nc.name}: CONFIG_ProfilePressure_dbar absent"


class _LandCheck:
    """Adapter: GebcoGrid -> profile_scalar LandCheck protocol."""

    def __init__(self, grid) -> None:
        self._grid = grid

    def is_on_land(self, latitude: float, longitude: float) -> bool | None:
        if not np.isfinite(latitude) or not np.isfinite(longitude):
            return None
        return bool(self._grid.is_on_land(latitude, longitude))


def _outcome_row(status: str, **kw) -> dict:
    row = {"status": status}
    row.update({k: v for k, v in kw.items() if v is not None})
    return row


def run_float(
    wmo: int,
    products: dict[str, Path],
    meta_nc: Path | None,
    gebco_path: Path | None,
) -> dict:
    profiles = [read_mono_product(p) for p in sorted(products.values())]
    profiles.sort(key=lambda p: p["cycle"])
    config_pp, config_src = meta_profile_pressure(wmo, meta_nc)

    grid = open_gebco(gebco_path) if gebco_path else None
    land_check = _LandCheck(grid) if grid is not None else None
    gebco_note = (
        f"{gebco_path} (supplied)"
        if grid is not None
        else "absent -- supply locally (current Coriolis chain uses GEBCO_2024.nc)"
    )

    per_cycle: list[dict] = []
    prev: dict | None = None
    prev_good: dict | None = None  # reference for test 16 (previous not-condemned)

    for prof in profiles:
        pres, temp, psal = prof["pres"], prof["temp"], prof["psal"]
        tests: dict[str, dict] = {}
        executed: set[int] = set()
        failed: set[int] = set()

        # ---- tests 1-4 (scalar; 4 via bathymetry when supplied) ----
        scalar = run_profile_scalar_tests(
            juld=prof["juld"],
            latitude=prof["lat"],
            longitude=prof["lon"],
            platform_known=True,
            bathymetry=land_check,
        )
        for key, number in (
            ("TEST001", 1),
            ("TEST002", 2),
            ("TEST003", 3),
            ("TEST004", 4),
        ):
            if any(t.startswith(key) for t in scalar.tests_done):
                is_failed = any(t.startswith(key) for t in scalar.tests_failed)
                tests[key] = _outcome_row(
                    "failed" if is_failed else "passed",
                    input="JULD/LAT/LON scalars",
                )
                executed.add(number)
                if is_failed:
                    failed.add(number)
            elif number == 4:
                tests[key] = _outcome_row(
                    "skipped",
                    reason="no bathymetry grid supplied (--gebco); Test 4 requires "
                    "GEBCO/ETOPO-class reference data",
                    input="LATITUDE/LONGITUDE",
                )
            else:  # pragma: no cover -- scalar inputs always present here
                tests[key] = _outcome_row("skipped", reason="scalar input missing")

        # ---- test 6 (global range; PRES handled via near-surface branch) ----
        for name, values in (("TEMP", temp), ("PSAL", psal)):
            outcome = global_range_test(name, pres, values)
            if outcome.n_flagged:
                failed.add(6)
            tests.setdefault("TEST006", _outcome_row("passed", input="PRES/TEMP/PSAL levels"))
            if outcome.n_flagged:
                tests["TEST006"]["status"] = "failed"
                tests["TEST006"]["n_flagged"] = tests["TEST006"].get("n_flagged", 0) + int(
                    outcome.n_flagged
                )
        executed.add(6)

        # ---- test 8 (pressure increasing) ----
        outcome = pressure_increasing_test(pres)
        tests["TEST008"] = _outcome_row(
            "failed" if outcome.n_flagged else "passed", input="PRES levels"
        )
        if outcome.n_flagged:
            tests["TEST008"]["n_flagged"] = int(outcome.n_flagged)
            failed.add(8)
        executed.add(8)

        # ---- tests 9 / 11 / 12 (per-parameter pairwise tests) ----
        for key, func, number in (
            ("TEST009", spike_test, 9),
            ("TEST011", gradient_test, 11),
            ("TEST012", digit_rollover_test, 12),
        ):
            flagged = 0
            for name, values in (("TEMP", temp), ("PSAL", psal)):
                outcome = func(name, pres, values)
                flagged += int(outcome.n_flagged)
            tests[key] = _outcome_row(
                "failed" if flagged else "passed", input="TEMP/PSAL levels + PRES"
            )
            if flagged:
                tests[key]["n_flagged"] = flagged
                failed.add(number)
            executed.add(number)

        # ---- test 13 (stuck value) ----
        flagged = 0
        for values in (temp, psal):
            outcome = stuck_value_test(pres, values)
            flagged += int(outcome.n_flagged)
        tests["TEST013"] = _outcome_row("failed" if flagged else "passed", input="TEMP/PSAL levels")
        if flagged:
            tests["TEST013"]["n_flagged"] = flagged
            failed.add(13)
        executed.add(13)

        # ---- test 14 (density inversion) ----
        upbot, botup = density_inversion_test(
            pres=pres, temp=temp, psal=psal, lat=prof["lat"], lon=prof["lon"]
        )
        flagged = int(upbot.n_flagged) + int(botup.n_flagged)
        tests["TEST014"] = _outcome_row(
            "failed" if flagged else "passed", input="PRES/TEMP/PSAL levels (TEOS-10)"
        )
        if flagged:
            tests["TEST014"]["n_flagged"] = flagged
            failed.add(14)
        executed.add(14)

        # ---- test 19 (deepest pressure) ----
        if config_pp is None:
            tests["TEST019"] = _outcome_row(
                "skipped", reason=f"CONFIG_ProfilePressure_dbar unavailable ({config_src})"
            )
        else:
            outcome = deepest_pressure_test(pres, config_pp)
            tests["TEST019"] = _outcome_row(
                "failed" if outcome.n_flagged else "passed",
                input=f"PRES levels vs CONFIG_ProfilePressure_dbar={config_pp} ({config_src})",
            )
            if outcome.n_flagged:
                tests["TEST019"]["n_flagged"] = int(outcome.n_flagged)
                failed.add(19)
            executed.add(19)

        # ---- cross-cycle tests 5 / 16 / 18 ----
        if prev is None:
            for key, _number in (("TEST005", 5), ("TEST016", 16), ("TEST018", 18)):
                tests[key] = _outcome_row(
                    "skipped", reason="no previous cycle (first profile of the run)"
                )
        else:
            pos_qc, ran = impossible_speed_test(
                juld=prof["juld"],
                latitude=prof["lat"],
                longitude=prof["lon"],
                previous_juld=prev["juld"],
                previous_latitude=prev["lat"],
                previous_longitude=prev["lon"],
            )
            tests["TEST005"] = _outcome_row(
                "skipped",
                reason="speed undefined (equal timestamps or missing endpoint)",
                input="consecutive-cycle JULD/LAT/LON",
            )
            if ran:
                executed.add(5)
                speed_ok = pos_qc in (None, b"", b"1")
                tests["TEST005"] = _outcome_row(
                    "passed" if speed_ok else "failed",
                    input="consecutive-cycle JULD/LAT/LON",
                    position_qc=(pos_qc or b"").decode("ascii", "replace") or None,
                )
                if not speed_ok:
                    failed.add(5)

            frozen, ran = frozen_profile_test(
                pres=pres,
                temp=temp,
                psal=psal,
                previous_pres=prev["pres"],
                previous_temp=prev["temp"],
                previous_psal=prev["psal"],
            )
            tests["TEST018"] = _outcome_row(
                "skipped",
                reason="insufficient overlap with previous profile",
                input="50-dbar slab means vs previous cycle",
            )
            if ran:
                executed.add(18)
                tests["TEST018"] = _outcome_row(
                    "failed" if frozen else "passed",
                    input="50-dbar slab means vs previous cycle",
                )
                if frozen:
                    failed.add(18)

            drift_flagged = 0
            for key, values, threshold in (
                ("temp", temp, DRIFT_THRESHOLD_TEMP),
                ("psal", psal, DRIFT_THRESHOLD_PSAL),
            ):
                flags, ran = gross_sensor_drift_test(
                    pres=pres,
                    values=values,
                    previous_pres=prev_good["pres"] if prev_good else None,
                    previous_values=prev_good[key] if prev_good else None,
                    threshold=threshold,
                )
                if ran and flags is not None:
                    executed.add(16)
                    drift_flagged += int(np.sum(flags >= 3))
            if 16 in executed:
                tests["TEST016"] = _outcome_row(
                    "failed" if drift_flagged else "passed",
                    input="deepest-100-dbar means vs previous good cycle",
                )
                if drift_flagged:
                    tests["TEST016"]["n_flagged"] = drift_flagged
                    failed.add(16)
            else:
                tests["TEST016"] = _outcome_row(
                    "skipped",
                    reason="no previous good profile available as drift reference",
                )

        # tests 7/15/20: documented non-execution (never counted as passed)
        for number, reason in NOT_APPLICABLE.items():
            tests[f"TEST{number:03d}"] = _outcome_row("skipped", reason=reason)

        per_cycle.append(
            {
                "cycle": prof["cycle"],
                "file": prof["file"],
                "n_levels": int(np.isfinite(pres).sum()),
                "input_nonfinite": {
                    "pres": int((~np.isfinite(pres)).sum()),
                    "temp": int((~np.isfinite(temp)).sum()),
                    "psal": int((~np.isfinite(psal)).sum()),
                },
                "tests": tests,
                "QCP$": encode_mask(executed),
                "QCP$_tests": sorted(executed),
                "QCF$": encode_mask(failed),
                "QCF$_tests": sorted(failed),
            }
        )

        prev = prof
        prev_good = prof if not failed else prev_good

    return {
        "wmo": wmo,
        "n_profiles": len(per_cycle),
        "reference_data": {
            "bathymetry_test004": gebco_note,
            "config_profile_pressure_dbar": config_pp,
            "config_source": config_src,
            "exclusion_list_test015": "not supplied (DAC-managed; no-op)",
        },
        "engine_config": ENGINE_CONFIG,
        "cycles": per_cycle,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--wmo", nargs="+", type=int, required=True)
    ap.add_argument(
        "--products-root",
        type=Path,
        default=None,
        help="Directory holding <wmo>/R*.nc mono products; decoded to /tmp when absent.",
    )
    ap.add_argument(
        "--meta-root",
        type=Path,
        default=None,
        help="Directory holding <wmo>_meta.nc products (test-19 input).",
    )
    ap.add_argument("--gebco", type=Path, default=None, help="GEBCO netCDF grid for Test 4.")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_products = Path("/tmp/rtqc_harness_products")
    loader = MultiCsvLoader(METADATA_DIR, materialized_dir=tmp_products / "float_meta")
    oracle_path = out_dir / "gdac_qcp_masks.json"
    oracle = json.loads(oracle_path.read_text()) if oracle_path.exists() else {}

    fleet = []
    for wmo in args.wmo:
        if args.products_root is not None:
            products = {p.name: p for p in sorted((args.products_root / str(wmo)).glob("R*.nc"))}
            provenance = f"existing products under {args.products_root}"
        else:
            products = decode_products(wmo, tmp_products, loader)
            provenance = f"decoded to {tmp_products}/{wmo} via validated pipeline (4-CSV metadata)"
        meta_nc = (
            args.meta_root / f"{wmo}_meta.nc"
            if args.meta_root is not None
            else products[next(iter(products))].parent / f"{wmo}_meta.nc"
        )
        report = run_float(wmo, products, meta_nc, args.gebco)
        report["provenance"] = provenance

        # informational side-by-side with the GDAC-published masks
        if str(wmo) in oracle:
            agree = disagree = 0
            for cyc in report["cycles"]:
                for entry in oracle[str(wmo)]:
                    if entry["cycle"] == cyc["cycle"]:
                        same_qcp = entry.get("QCP$") == cyc["QCP$"]
                        gdac_failed = set(entry.get("QCF$_decoded", []))
                        same_qcf = gdac_failed == set(cyc["QCF$_tests"])
                        if same_qcp and same_qcf:
                            agree += 1
                        else:
                            disagree += 1
                            cyc["gdac_oracle"] = {
                                "QCP$": entry.get("QCP$"),
                                "QCF$": entry.get("QCF$"),
                                "QCF$_tests": sorted(gdac_failed),
                            }
                        break
            report["gdac_mask_agreement"] = {"agree": agree, "differ": disagree}

        (out_dir / f"{wmo}_rtqc.json").write_text(json.dumps(report, indent=1))
        fleet.append(report)

        per_test: dict[int, dict[str, int]] = {}
        for cyc in report["cycles"]:
            for key, row in cyc["tests"].items():
                number = int(key.removeprefix("TEST"))
                if number is None:
                    continue
                bucket = per_test.setdefault(number, {"passed": 0, "failed": 0, "skipped": 0})
                status = row["status"]
                bucket[status if status in bucket else "skipped"] += 1
        print(f"===== {wmo}: {report['n_profiles']} profiles ({provenance})")
        print(f"  gebco/test004: {report['reference_data']['bathymetry_test004']}")
        print(
            f"  test19 config: {report['reference_data']['config_profile_pressure_dbar']} "
            f"({report['reference_data']['config_source']})"
        )
        for number in APPLICABLE:
            bucket = per_test.get(number, {})
            print(
                f"  TEST{number:03d}: passed={bucket.get('passed', 0):>3} "
                f"failed={bucket.get('failed', 0):>3} skipped={bucket.get('skipped', 0):>3}"
            )
        if "gdac_mask_agreement" in report:
            print(f"  GDAC QCP$/QCF$ agreement: {report['gdac_mask_agreement']}")

    (out_dir / "fleet_summary.json").write_text(
        json.dumps(
            [
                {
                    "wmo": r["wmo"],
                    "n_profiles": r["n_profiles"],
                    "gdac_mask_agreement": r.get("gdac_mask_agreement"),
                }
                for r in fleet
            ],
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
