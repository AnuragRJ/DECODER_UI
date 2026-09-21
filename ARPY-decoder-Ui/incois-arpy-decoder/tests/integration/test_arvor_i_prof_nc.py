"""Integration tests: ARVOR-I mono-profile ``R*.nc`` product over both raw datasets.

Phase-5 validation, pinned to the expectations fixed in
``docs/phase_reports/ARVOR_I_MONO_PROFILE_MAPPING_2026-08-27.md`` (§8
compatibility matrix, PROVEN) and refined by the first product run
(2026-08-27, recorded in ``IMPLEMENTATION_PROGRESS.md``):

* level counts equal the GDAC references for every in-raw cycle,
  including trailing-buffer cycles 14/15 of 7902408 (15 / 73 levels)
  recovered by the ``process_remaining_buffers=True`` baseline;
* ``PRES``/``TEMP``/``PSAL`` arrays are bit-exact vs GDAC float32;
* JULD = first non-pre-launch mail time; exact vs GDAC on
  retransmitted/trailing cycles, within the classified production
  reception skew (7-32 s) on fresh cycles;
* positions: Tech#1 GPS truncated to arc-minutes (``GPS``) on fresh
  cycles; first usable Iridium mail fix (``IRIDIUM``) otherwise - both
  GDAC-exact except 6990711 cycle 5 (classified: missing April mails +
  GDAC stale-fix reuse);
* descent publication policy: suppressed by default, reachable via the
  explicit flag (cycle-1 descents 54 / 52 levels exist in raw).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import netCDF4
import numpy as np
import pytest

from argo_decoder.metadata.multi_csv_loader import MultiCsvLoader
from argo_decoder.platforms.provor_ir_sbd.arvor_i import read_arvor_i_eml
from argo_decoder.platforms.provor_ir_sbd.arvor_i_prof import (
    build_arvor_mono_profiles,
    write_arvor_mono_profiles,
)
from argo_decoder.platforms.provor_ir_sbd.arvor_i_science import reconstruct_science

ARGO_PY_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ARGO_PY_ROOT.parent
RAW_ROOT = WORKSPACE / "arvor_raw" / "ARVOR-I-raw-files" / "20260819"
REF_ROOT = WORKSPACE / "gdac_arvor_i_ref" / "profiles"

LAUNCH_6990711 = datetime(2025, 3, 2, 5, 16, tzinfo=UTC)
LAUNCH_7902408 = datetime(2026, 3, 25, 17, 44, tzinfo=UTC)
EPOCH = datetime(1950, 1, 1, tzinfo=UTC)

# Mapping report §8 (PROVEN) + first-run verification 2026-08-27.
EXPECTED_LEVELS = {
    6990711: {1: 102, 2: 103, 3: 104, 4: 104, 5: 101, 6: 105, 7: 101},
    7902408: {
        1: 104,
        2: 73,
        3: 75,
        4: 103,
        5: 73,
        6: 75,
        7: 102,
        8: 30,
        9: 103,
        10: 75,
        11: 58,
        12: 103,
        13: 30,
        14: 15,
        15: 73,
    },
}

# GDAC-exact JULDs (retransmitted / trailing-buffer cycles; seconds UTC).
EXPECTED_JULD_DATES = {
    (6990711, 6): datetime(2025, 5, 2, 0, 0, 35, tzinfo=UTC),
    (7902408, 13): datetime(2026, 7, 22, 18, 7, 28, tzinfo=UTC),
    (7902408, 14): datetime(2026, 8, 1, 13, 13, 16, tzinfo=UTC),
    (7902408, 15): datetime(2026, 8, 11, 7, 56, 52, tzinfo=UTC),
}

pytestmark = pytest.mark.skipif(not RAW_ROOT.exists(), reason="ARVOR-I raw datasets not present")


@pytest.fixture(scope="module")
def records() -> dict[int, dict[int, object]]:
    out: dict[int, dict[int, object]] = {}
    for wmo, launch in ((6990711, LAUNCH_6990711), (7902408, LAUNCH_7902408)):
        msgs = [read_arvor_i_eml(p) for p in sorted((RAW_ROOT / str(wmo)).glob("*.eml"))]
        res = reconstruct_science(msgs, launch)
        loader = MultiCsvLoader(ARGO_PY_ROOT / "config" / "metadata")
        recs = build_arvor_mono_profiles(
            res,
            wmo=wmo,
            meta=loader.load_meta(wmo),
            firmware_version=getattr(loader.get_float(wmo), "sensor_firmware_version", None),
        )
        out[wmo] = {r.cycle: r for r in recs}
    return out


def test_record_counts_and_naming(records: dict[int, dict[int, object]]) -> None:
    assert sorted(records[6990711]) == list(range(1, 8))
    assert sorted(records[7902408]) == list(range(1, 16))
    for wmo, bycyc in records.items():
        for cycle, rec in bycyc.items():
            assert rec.filename == f"R{wmo}_{cycle:03d}.nc"  # type: ignore[attr-defined]


def test_level_counts_match_gdac_matrix(records: dict[int, dict[int, object]]) -> None:
    for wmo, expected in EXPECTED_LEVELS.items():
        got = {c: r.n_levels for c, r in records[wmo].items()}  # type: ignore[attr-defined]
        assert got == expected


def test_ascent_arrays_bit_exact_vs_gdac(records: dict[int, dict[int, object]]) -> None:
    if not REF_ROOT.exists():
        pytest.skip("GDAC reference profiles not present")
    checked = 0
    for wmo in (6990711, 7902408):
        for ref in sorted((REF_ROOT / str(wmo)).glob("R*.nc")):
            n = int(ref.stem.split("_")[1].rstrip("D"))
            if n not in records[wmo]:
                continue  # _016: beyond raw snapshot (classified)
            d = netCDF4.Dataset(ref)
            d.set_auto_mask(False)
            ours = records[wmo][n].dataset  # type: ignore[attr-defined]
            assert ours.sizes["N_LEVELS"] == len(d.dimensions["N_LEVELS"])
            for p in ("PRES", "TEMP", "PSAL"):
                ov = ours[p].values.reshape(-1)
                gv = np.asarray(d[p][0])
                assert np.array_equal(ov, gv), (ref.name, p)
            checked += 1
            d.close()
    assert checked == 22  # 7 + 15 in-raw reference files (_016 beyond raw)


def test_juld_first_mail_rule(records: dict[int, dict[int, object]]) -> None:
    for (wmo, cycle), want in EXPECTED_JULD_DATES.items():
        rec = records[wmo][cycle]
        got = EPOCH + timedelta(days=rec.juld)  # type: ignore[attr-defined]
        assert abs((got - want).total_seconds()) < 0.5, (wmo, cycle, got)


def test_positions_and_positioning_system(records: dict[int, dict[int, object]]) -> None:
    # Fresh GPS cycles: Tech#1 fix truncated to arc-minutes (GDAC-exact).
    for wmo, cycle, lat, lon in (
        (6990711, 1, -(64.0 + 32 / 60), 70.0 + 4 / 60),
        (7902408, 1, 2.0 + 56 / 60, 82.0 + 58 / 60),
    ):
        rec = records[wmo][cycle]
        assert rec.positioning_system == "GPS"  # type: ignore[attr-defined]
        assert rec.dataset["LATITUDE"].values.item() == pytest.approx(lat, abs=1e-9)
        assert rec.dataset["LONGITUDE"].values.item() == pytest.approx(lon, abs=1e-9)

    # No fresh GPS: first usable Iridium mail fix, full precision.
    rec13 = records[7902408][13]
    assert rec13.positioning_system == "IRIDIUM"  # type: ignore[attr-defined]
    assert rec13.position_source == "first-mail-fix"  # type: ignore[attr-defined]
    assert rec13.dataset["LATITUDE"].values.item() == pytest.approx(2.49729, abs=1e-6)
    assert rec13.dataset["LONGITUDE"].values.item() == pytest.approx(80.96940, abs=1e-6)


def test_coriolis_qc_semantics(records: dict[int, dict[int, object]]) -> None:
    rec = records[7902408][14]
    ds = rec.dataset  # type: ignore[attr-defined]
    n = ds.sizes["N_LEVELS"]
    for p in ("PRES", "TEMP", "PSAL"):
        assert list(np.asarray(ds[f"{p}_QC"].values).reshape(-1)) == [b"0"] * n
        assert ds[f"PROFILE_{p}_QC"].values.item() == b" "
    # Launch mission: these floats never left their deployment config, and
    # the GDAC reference files publish 1 (the fill 99999 was a placeholder).
    assert int(ds["CONFIG_MISSION_NUMBER"].values.item()) == 1
    # csv4 metadata reaches the product: INCOIS identity end to end.
    assert ds.attrs["institution"] == "INCOIS"
    assert (
        str(netCDF4.chartostring(np.asarray(ds["DATA_CENTRE"].values)).ravel()[0]).strip() == "IN"
    )
    vss = bytes(np.asarray(ds["VERTICAL_SAMPLING_SCHEME"].values).reshape(-1)).decode()
    assert vss.strip() == "Primary sampling: averaged []"


def test_written_file_layout_gdac_order(
    records: dict[int, dict[int, object]], tmp_path: Path
) -> None:
    if not (REF_ROOT / "7902408" / "R7902408_013.nc").exists():
        pytest.skip("GDAC reference profiles not present")
    recs = [records[7902408][c] for c in sorted(records[7902408])]  # type: ignore[index]
    written = write_arvor_mono_profiles(recs, tmp_path)
    assert len(written) == 15

    d = netCDF4.Dataset(tmp_path / "R7902408_013.nc")
    g = netCDF4.Dataset(REF_ROOT / "7902408" / "R7902408_013.nc")
    try:
        assert d.data_model == "NETCDF3_CLASSIC"
        assert list(d.variables) == list(g.variables)
        assert all(d[v].dtype == g[v].dtype for v in d.variables)
        assert len(d.variables) == 64
        assert len(d.dimensions["N_PROF"]) == 1
        assert len(d.dimensions["N_PARAM"]) == 3
        assert len(d.dimensions["N_CALIB"]) == 1
        assert d.dimensions["N_HISTORY"].isunlimited()
        dc = bytes(np.asarray(d["DATE_CREATION"][:])).decode()
        juld_s = float(d["JULD"][0]) * 86400.0
        want = EPOCH + timedelta(seconds=juld_s)
        assert dc == want.strftime("%Y%m%d%H%M%S")
        ref = bytes(np.asarray(d["DC_REFERENCE"][:]).reshape(-1)).decode().strip()
        assert ref == "7902408/13"
        assert sorted(d.ncattrs()) == sorted(g.ncattrs())
    finally:
        d.close()
        g.close()


def test_descent_policy_flag_keeps_capability() -> None:
    msgs = [read_arvor_i_eml(p) for p in sorted((RAW_ROOT / "7902408").glob("*.eml"))]
    res = reconstruct_science(msgs, LAUNCH_7902408)
    default_records = build_arvor_mono_profiles(res, wmo=7902408)
    assert not any(r.direction == "D" for r in default_records)

    with_desc = build_arvor_mono_profiles(res, wmo=7902408, publish_descent=True)
    desc = [r for r in with_desc if r.direction == "D"]
    assert [(r.cycle, r.n_levels, r.filename) for r in desc] == [(1, 52, "R7902408_001D.nc")]


def test_6990711_cycle5_divergence_is_the_classified_one(
    records: dict[int, dict[int, object]],
) -> None:
    """c5: first [5]-tagged mail of the (gapped) snapshot + GDAC stale-fix."""
    rec = records[6990711][5]
    got = EPOCH + timedelta(days=rec.juld)  # type: ignore[attr-defined]
    assert got == datetime(2025, 5, 1, 23, 59, 34, tzinfo=UTC)
    # GDAC reuses cycle 4's GPS fix (publication-layer); ours follows the
    # chain rule (first usable mail fix) - classified, not forced.
    assert rec.positioning_system == "IRIDIUM"  # type: ignore[attr-defined]
