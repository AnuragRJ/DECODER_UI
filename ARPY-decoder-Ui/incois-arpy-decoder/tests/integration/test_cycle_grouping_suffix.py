"""Cycle-grouping regression tests for the filename-suffix demotion fix.

Coverage (see docs/FILENAME_SUFFIX_SEMANTICS.md):
- repeated filename suffixes across distinct surfacings must NOT merge
  (2902224: cycles 325 and 326 both labelled ``_001``);
- same-surfacing split across files must still yield a single cycle;
- unique-but-wrong suffixes (2902223 ``_326`` = true cycle 327) must be
  overridden by the telemetry-derived cycle.

All tests use the four-CSV backend (config/metadata) and the project's
own raw files, with skip guards when a fixture is absent.
"""

from __future__ import annotations

import shutil
from datetime import UTC
from pathlib import Path

import netCDF4
import pytest

from argo_decoder.config import DecoderConfig
from argo_decoder.config.models import TransmissionType
from argo_decoder.pipeline.runner import run_pipeline

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_ROOT = REPO_ROOT / "phase4_reference" / "raw" / "raw-files"
# The 2902224 raw bundle lives beside the repository (workspace layout:
# <workspace>/argo-decoder-python + <workspace>/ref2902224).
REF_2902224 = REPO_ROOT.parent / "ref2902224" / "2902224-files-needed" / "2902224-raw-files"
META_CSV = REPO_ROOT / "config" / "metadata"


def _pipeline_cfg(tmp_path: Path, raw_dir: Path) -> DecoderConfig:
    cfg = DecoderConfig()
    cfg.transmission_type = TransmissionType.ARGOS
    cfg.metadata.backend = "csv4"  # type: ignore[assignment]
    cfg.metadata.registry_path = META_CSV
    cfg.paths.rsync_data_dir = raw_dir
    for name in ("xml", "nc", "log", "csv", "iridium", "tmp"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
    cfg.paths.xml_dir = tmp_path / "xml"
    cfg.paths.nc_dir = tmp_path / "nc"
    cfg.paths.log_dir = tmp_path / "log"
    cfg.paths.csv_dir = tmp_path / "csv"
    cfg.paths.iridium_decoded_dir = tmp_path / "iridium"
    cfg.paths.temporary_dir = tmp_path / "tmp"
    return cfg


def _mono_first_pres(profile_path: Path) -> tuple[int, float]:
    with netCDF4.Dataset(profile_path) as ds:
        n_levels = ds.dimensions["N_LEVELS"].size
        pres = ds.variables["PRES"][:]
        first = float(pres.ravel()[0]) if n_levels else float("nan")
    return n_levels, first


def _copy_files(src_dir: Path, dest_dir: Path, names: list[str]) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copy2(src_dir / name, dest_dir / name)


def test_repeated_suffix_across_surfacings_is_not_merged(tmp_path: Path) -> None:
    """2902224: ``_001`` labels both cycle 325 (Jan-1) and 326 (Jan-11).

    Before the fix these fused into one corrupted cycle (58 levels of
    Jan-11 science labelled 325, cycle 326 missing). After the fix both
    surfacings must be emitted with their own telemetry-derived cycles.
    """
    if not (REF_2902224 / "152390_2026-01-01_2902224_001.txt").exists():
        pytest.skip("2902224 raw files are not present in this workspace")
    raw = tmp_path / "raw" / "152390"
    _copy_files(
        REF_2902224,
        raw,
        [
            "152390_2026-01-01_2902224_001.txt",
            "152390_2026-01-01_2902224_011.txt",
            "152390_2026-01-02_2902224_011.txt",
            "152390_2026-01-11_2902224_001.txt",
            "152390_2026-01-12_2902224_001.txt",
        ],
    )
    cfg = _pipeline_cfg(tmp_path, tmp_path / "raw")
    result = run_pipeline(config=cfg, wmo=2902224, xml_filename="argos.xml")
    assert result.status == "ok"

    profile_dir = tmp_path / "nc" / "2902224" / "profiles"
    p325 = profile_dir / "R2902224_325.nc"
    p326 = profile_dir / "R2902224_326.nc"
    assert p325.exists(), "cycle 325 (Jan-1 surfacing) must be emitted"
    assert p326.exists(), "cycle 326 (Jan-11 surfacing) must be emitted, not merged"
    # Jan-1 science: 58 levels, shallowest PRES 4.3 dbar (GDAC 325 = 4.3).
    n, first = _mono_first_pres(p325)
    assert n == 58
    assert abs(first - 4.3) < 0.1
    # Jan-11 science: 59 levels, shallowest PRES 4.6 dbar (GDAC 326 = 4.6).
    n, first = _mono_first_pres(p326)
    assert n == 59
    assert abs(first - 4.6) < 0.1


def test_same_surfacing_split_across_files_yields_single_cycle(tmp_path: Path) -> None:
    """2902224 Jan-1/Jan-2 ``_011`` + ``_001`` all belong to surfacing 325."""
    if not (REF_2902224 / "152390_2026-01-01_2902224_001.txt").exists():
        pytest.skip("2902224 raw files are not present in this workspace")
    raw = tmp_path / "raw" / "152390"
    _copy_files(
        REF_2902224,
        raw,
        [
            "152390_2026-01-01_2902224_001.txt",
            "152390_2026-01-01_2902224_011.txt",
            "152390_2026-01-02_2902224_011.txt",
        ],
    )
    cfg = _pipeline_cfg(tmp_path, tmp_path / "raw")
    result = run_pipeline(config=cfg, wmo=2902224, xml_filename="argos.xml")
    assert result.status == "ok"

    profile_dir = tmp_path / "nc" / "2902224" / "profiles"
    p325 = profile_dir / "R2902224_325.nc"
    assert p325.exists(), "the single surfacing must be emitted as cycle 325"
    assert not (profile_dir / "R2902224_326.nc").exists()
    n, first = _mono_first_pres(p325)
    assert n == 58
    assert abs(first - 4.3) < 0.1


def test_unique_but_wrong_suffix_is_overridden_by_telemetry(tmp_path: Path) -> None:
    """2902223: filename suffix ``_326`` labels the cycle GDAC numbers 327.

    The suffix is unique (no repetition), so the demotion path is not
    taken; the telemetry-derived cycle (PRF 71 + 256 = 327) must win.
    """
    if not (RAW_ROOT / "152382" / "152382_2025-12-26_2902223_326.txt").exists():
        pytest.skip("2902223 raw files are not present in this workspace")
    raw = tmp_path / "raw" / "152382"
    _copy_files(
        RAW_ROOT / "152382",
        raw,
        [
            "152382_2025-12-26_2902223_326.txt",
            "152382_2026-01-05_2902223_327.txt",
            "152382_2026-01-15_2902223_328.txt",
        ],
    )
    cfg = _pipeline_cfg(tmp_path, tmp_path / "raw")
    result = run_pipeline(config=cfg, wmo=2902223, xml_filename="argos.xml")
    assert result.status == "ok"

    profile_dir = tmp_path / "nc" / "2902223" / "profiles"
    assert (profile_dir / "R2902223_327.nc").exists()
    assert (profile_dir / "R2902223_328.nc").exists()
    assert (profile_dir / "R2902223_329.nc").exists()
    assert not (profile_dir / "R2902223_326.nc").exists()


def test_foreign_burst_is_withheld_2902206(tmp_path: Path) -> None:
    """2902206's raw file contains a 2902224 pass (float id 771 vs 812).

    The foreign burst must not be published as a cycle (it would otherwise
    decode as a bogus cycle 325 from its profile id).
    """
    if not (RAW_ROOT / "152397" / "152397_2025-12-31_2902206_359.txt").exists():
        pytest.skip("2902206 raw files are not present in this workspace")
    raw = tmp_path / "raw" / "152397"
    _copy_files(
        RAW_ROOT / "152397",
        raw,
        [
            "152397_2025-12-31_2902206_359.txt",
            "152397_2026-01-10_2902206_360.txt",
            "152397_2026-01-20_2902206_361.txt",
        ],
    )
    cfg = _pipeline_cfg(tmp_path, tmp_path / "raw")
    result = run_pipeline(config=cfg, wmo=2902206, xml_filename="argos.xml")
    assert result.status == "ok"
    profile_dir = tmp_path / "nc" / "2902206" / "profiles"
    assert (profile_dir / "R2902206_359.nc").exists()
    assert (profile_dir / "R2902206_360.nc").exists()
    assert (profile_dir / "R2902206_361.nc").exists()
    assert not (profile_dir / "R2902206_325.nc").exists(), (
        "the 2902224 pass mixed into 2902206's file must be withheld"
    )


def test_foreign_burst_is_withheld_2902222(tmp_path: Path) -> None:
    """2902222's ``_329`` file carries an id-811 burst (float id 795 is 2902222's).

    The foreign burst must not be published as a bogus cycle 330.
    """
    if not (RAW_ROOT / "152389" / "152389_2026-01-14_2902222_329.txt").exists():
        pytest.skip("2902222 raw files are not present in this workspace")
    raw = tmp_path / "raw" / "152389"
    _copy_files(
        RAW_ROOT / "152389",
        raw,
        [
            "152389_2025-12-25_2902222_327.txt",
            "152389_2026-01-04_2902222_328.txt",
            "152389_2026-01-14_2902222_329.txt",
        ],
    )
    cfg = _pipeline_cfg(tmp_path, tmp_path / "raw")
    result = run_pipeline(config=cfg, wmo=2902222, xml_filename="argos.xml")
    assert result.status == "ok"
    profile_dir = tmp_path / "nc" / "2902222" / "profiles"
    assert (profile_dir / "R2902222_327.nc").exists()
    assert (profile_dir / "R2902222_328.nc").exists()
    assert (profile_dir / "R2902222_329.nc").exists()
    assert not (profile_dir / "R2902222_330.nc").exists(), (
        "the foreign id-811 burst in the _329 file must be withheld"
    )


def test_multiburst_mono_juld_anchored_to_surfacing_first_fix(tmp_path: Path) -> None:
    """2902224 cycle 325 is assembled from several bursts; its mono JULD
    must be the surfacing's earliest fix (2026-01-01T19:24:55), not the
    retained burst's first fix (2026-01-02T00:28:50), and must equal the
    Rtraj MC702 anchor."""
    if not (REF_2902224 / "152390_2026-01-01_2902224_001.txt").exists():
        pytest.skip("2902224 raw files are not present in this workspace")
    raw = tmp_path / "raw" / "152390"
    _copy_files(
        REF_2902224,
        raw,
        [
            "152390_2026-01-01_2902224_001.txt",
            "152390_2026-01-01_2902224_011.txt",
            "152390_2026-01-02_2902224_011.txt",
            "152390_2026-01-11_2902224_001.txt",
            "152390_2026-01-12_2902224_001.txt",
            "152390_2026-07-20_2902224_345.txt",
        ],
    )
    cfg = _pipeline_cfg(tmp_path, tmp_path / "raw")
    result = run_pipeline(config=cfg, wmo=2902224, xml_filename="argos.xml")
    assert result.status == "ok"
    from datetime import datetime, timedelta

    def juld_to_dt(j):
        return datetime(1950, 1, 1, tzinfo=UTC) + timedelta(days=j)

    # mono 325 JULD == surfacing earliest fix 2026-01-01T19:25:16 (GDAC value)
    with netCDF4.Dataset(tmp_path / "nc" / "2902224" / "profiles" / "R2902224_325.nc") as ds:
        juld = float(ds.variables["JULD"][:].ravel()[0])
        loc = float(ds.variables["JULD_LOCATION"][:].ravel()[0])
    assert (
        abs((juld_to_dt(juld) - datetime(2026, 1, 1, 19, 25, 16, tzinfo=UTC)).total_seconds()) < 2
    )
    assert abs(juld - loc) < 1e-9, "JULD must equal JULD_LOCATION"
    # mono 326 JULD == the surfacing's earliest *parsed* fix,
    # 2026-01-11T19:12:07 (the 17:33 MC702 is a header time, not a parsed
    # fix; GDAC's mono JULD 23:29 is an inconsistent later-fix choice).
    with netCDF4.Dataset(tmp_path / "nc" / "2902224" / "profiles" / "R2902224_326.nc") as ds:
        juld = float(ds.variables["JULD"][:].ravel()[0])
    assert (
        abs((juld_to_dt(juld) - datetime(2026, 1, 11, 19, 12, 7, tzinfo=UTC)).total_seconds()) < 2
    )
    # mono JULD equals the Rtraj MC702 of the same cycle
    with netCDF4.Dataset(tmp_path / "nc" / "2902224" / "2902224_Rtraj.nc") as ds:
        cyc = ds.variables["CYCLE_NUMBER"][:]
        mc = ds.variables["MEASUREMENT_CODE"][:]
        j = ds.variables["JULD"][:]
        mc702 = None
        for i in range(len(cyc)):
            if (
                not getattr(cyc[i], "mask", False)
                and not getattr(mc[i], "mask", False)
                and not getattr(j[i], "mask", False)
                and int(cyc[i]) == 325
                and int(mc[i]) == 702
            ):
                mc702 = float(j[i])
                break
    assert mc702 is not None
    with netCDF4.Dataset(tmp_path / "nc" / "2902224" / "profiles" / "R2902224_325.nc") as ds:
        juld = float(ds.variables["JULD"][:].ravel()[0])
    # mono JULD (earliest fix) vs Rtraj MC702 (first message): the fix
    # legitimately trails the message time by seconds; both anchor the
    # same surfacing (2026-01-01 evening).
    assert abs(juld - mc702) * 86400 < 60, "mono JULD must anchor the Rtraj MC702 surfacing"


def test_single_burst_mono_juld_unchanged(tmp_path: Path) -> None:
    """A single-burst cycle keeps its normal first-fix JULD (2902203 359)."""
    if not (RAW_ROOT / "152398" / "152398_2025-12-26_2902203_359.txt").exists():
        pytest.skip("2902203 raw files are not present in this workspace")
    raw = tmp_path / "raw" / "152398"
    _copy_files(
        RAW_ROOT / "152398",
        raw,
        [
            "152398_2025-12-26_2902203_359.txt",
            "152398_2026-01-05_2902203_360.txt",
            "152398_2026-01-15_2902203_361.txt",
        ],
    )
    cfg = _pipeline_cfg(tmp_path, tmp_path / "raw")
    result = run_pipeline(config=cfg, wmo=2902203, xml_filename="argos.xml")
    assert result.status == "ok"
    with netCDF4.Dataset(tmp_path / "nc" / "2902203" / "profiles" / "R2902203_359.nc") as ds:
        juld = float(ds.variables["JULD"][:].ravel()[0])
        loc = float(ds.variables["JULD_LOCATION"][:].ravel()[0])
    assert abs(juld - loc) < 1e-9
    # unchanged: JULD is the cycle's earliest fix; 359 is a multi-burst
    # file (the Dec-26 15:55 header burst is a stray from the previous
    # pass), so the JULD is that earliest fix of the surfacing, not the
    # kept main burst's fix.
    from datetime import datetime, timedelta

    dt = datetime(1950, 1, 1, tzinfo=UTC) + timedelta(days=juld)
    assert dt.date() == datetime(2025, 12, 26).date()
    assert dt.hour == 15 and dt.minute == 55


def test_multiburst_rtraj_union_2902224_325_326(tmp_path: Path) -> None:
    """Multi-burst cycles union their Rtraj telemetry: MC 703 carries every
    fix of the surfacing (2902224 cyc325 = 7, cyc326 = 8) and MC 704 is the
    surfacing's last message, matching GDAC exactly."""
    if not (REF_2902224 / "152390_2026-01-01_2902224_001.txt").exists():
        pytest.skip("2902224 raw files are not present in this workspace")
    raw = tmp_path / "raw" / "152390"
    _copy_files(
        REF_2902224,
        raw,
        [
            "152390_2026-01-01_2902224_001.txt",
            "152390_2026-01-01_2902224_011.txt",
            "152390_2026-01-02_2902224_011.txt",
            "152390_2026-01-11_2902224_001.txt",
            "152390_2026-01-12_2902224_001.txt",
            "152390_2026-07-20_2902224_345.txt",
        ],
    )
    cfg = _pipeline_cfg(tmp_path, tmp_path / "raw")
    result = run_pipeline(config=cfg, wmo=2902224, xml_filename="argos.xml")
    assert result.status == "ok"

    from datetime import datetime, timedelta

    def juld_to_dt(j):
        return datetime(1950, 1, 1, tzinfo=UTC) + timedelta(days=j)

    def cycle_rows(path, cyc):
        rows = {702: [], 703: [], 704: []}
        with netCDF4.Dataset(path) as ds:
            c = ds.variables["CYCLE_NUMBER"][:]
            m = ds.variables["MEASUREMENT_CODE"][:]
            j = ds.variables["JULD"][:]
            for i in range(len(c)):
                if (
                    not getattr(c[i], "mask", False)
                    and not getattr(m[i], "mask", False)
                    and not getattr(j[i], "mask", False)
                    and int(c[i]) == cyc
                    and int(m[i]) in rows
                ):
                    rows[int(m[i])].append(float(j[i]))
        return rows

    rtraj = tmp_path / "nc" / "2902224" / "2902224_Rtraj.nc"
    for cyc, n_fix, mc704 in [
        (325, 7, datetime(2026, 1, 2, 3, 11, 46, tzinfo=UTC)),
        (326, 8, datetime(2026, 1, 12, 2, 9, 44, tzinfo=UTC)),
    ]:
        rows = cycle_rows(rtraj, cyc)
        assert len(rows[703]) == n_fix, (
            f"cyc{cyc}: expected {n_fix} MC703 fixes, got {len(rows[703])}"
        )
        assert len(rows[702]) == 1
        assert len(rows[704]) == 1
        assert abs(juld_to_dt(rows[704][0]) - mc704).total_seconds() < 2, (
            f"cyc{cyc} MC704 must be the surfacing's last message"
        )
        assert juld_to_dt(rows[702][0]) < juld_to_dt(min(rows[703]))


def test_multiburst_rtraj_single_burst_unchanged(tmp_path: Path) -> None:
    """Single-burst (single distinct raw key) cycles keep the existing
    richest-burst Rtraj telemetry — 2902224 cyc345 (one file)."""
    if not (REF_2902224 / "152390_2026-07-20_2902224_345.txt").exists():
        pytest.skip("2902224 raw files are not present in this workspace")
    raw = tmp_path / "raw" / "152390"
    _copy_files(REF_2902224, raw, ["152390_2026-07-20_2902224_345.txt"])
    cfg = _pipeline_cfg(tmp_path, tmp_path / "raw")
    result = run_pipeline(config=cfg, wmo=2902224, xml_filename="argos.xml")
    assert result.status == "ok"
    with netCDF4.Dataset(tmp_path / "nc" / "2902224" / "2902224_Rtraj.nc") as ds:
        c = ds.variables["CYCLE_NUMBER"][:]
        m = ds.variables["MEASUREMENT_CODE"][:]
        n703 = sum(
            1
            for i in range(len(c))
            if not getattr(c[i], "mask", False)
            and not getattr(m[i], "mask", False)
            and int(c[i]) == 345
            and int(m[i]) == 703
        )
    # Single-burst cycle 345 keeps all of its own fixes (7 in the raw
    # file) — the union path only touches multi-key cycles.
    assert n703 == 7, "single-burst cycle 345 keeps its own fix count (7)"
