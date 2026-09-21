"""ARVOR-I RTQC on/off integration through the generic pipeline.

Runs the real ``run_pipeline`` on preserved ARVOR-I telemetry (csv4
metadata backend) twice:

* **off** (the default): the products must match the validated
  pre-RTQC baseline -- no QCP$/QCF$ provenance is claimed and the
  seeded level flags stay NO_QC ('0');
* **on** (``rtqc.apply_rtqc = True``): every profile carries truthful
  QCP$/QCF$ records from the common engine. Tests that cannot run are
  absent from the mask -- TEST004 without a GEBCO grid, TEST005 where
  reception timestamps make speed undefined -- and skipped is never
  counted as performed.

The assertions on test-5 outcomes are bound to the preserved 6990711
raw tree: cycles 5/6 share one late-mail batch (JULDs
27514.99970/27515.00041), so the 60 s / ~13 km hop is a genuine
impossible speed for *our* timestamps and both endpoints are degraded,
while cycle 7's reversed dt leaves TEST005 not-run. This divergence
against the GDAC oracle (which fails test 5 on c7 only) is recorded in
IMPLEMENTATION_PROGRESS.md as DATA-COVERAGE, not silently normalised.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import netCDF4
import numpy as np
import pytest

from argo_decoder.config.models import DecoderConfig, TransmissionType
from argo_decoder.pipeline.runner import run_pipeline

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = REPO_ROOT.parent
RAW_ROOT = WORKSPACE / "arvor_raw" / "ARVOR-I-raw-files" / "20260819" / "6990711"
METADATA_DIR = REPO_ROOT / "config" / "metadata"

pytestmark = pytest.mark.skipif(
    not (RAW_ROOT.exists() and (METADATA_DIR / "meta.csv").exists()),
    reason="ARVOR-I raw telemetry / fleet CSVs not present",
)

#: QCP$ bits of the tests this configuration really executes:
#: 1,2,3 (scalar) + 6,8,9,11,12,13,14,19 (profile) + 16,18 (cross-cycle
#: from cycle 2 on). TEST004 needs a GEBCO grid, TEST005 a defined
#: elapsed time -- neither runs here.
_EXPECTED_EXECUTED = {1, 2, 3, 5, 6, 8, 9, 11, 12, 13, 14, 16, 18, 19}


def _stage_input(raw_dir: Path, tmp: Path, transceiver: str) -> Path:
    cycle_dir = tmp / "input" / "archive" / "cycle" / transceiver
    cycle_dir.mkdir(parents=True)
    n = 0
    for pattern in ("*.eml", "*.sbd"):
        for src in sorted(raw_dir.glob(pattern)):
            shutil.copy2(src, cycle_dir / src.name)
            n += 1
    assert n >= 2, "no telemetry staged"
    return tmp / "input"


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


def _profile_files(cfg: DecoderConfig) -> list[Path]:
    out = Path(cfg.paths.nc_dir) / "6990711" / "profiles"
    files = sorted(out.glob("R6990711_[0-9][0-9][0-9].nc"))  # ascending only
    assert files, "no mono profiles written"
    return files


def _history(path: Path, action_var: str, test_var: str) -> list[tuple[str, str]]:
    with netCDF4.Dataset(path) as ds:
        acts = np.atleast_1d(np.ma.filled(netCDF4.chartostring(ds[action_var][:]), ""))
        qs = np.atleast_1d(np.ma.filled(netCDF4.chartostring(ds[test_var][:]), ""))
    return [
        (str(a).strip(), str(q).strip())
        for a, q in zip(acts.reshape(-1), qs.reshape(-1), strict=True)
    ]


def test_rtqc_defaults_to_off() -> None:
    cfg = DecoderConfig()
    assert cfg.rtqc.apply_rtqc is False


def test_pipeline_off_keeps_pre_rtqc_baseline(tmp_path: Path) -> None:
    staged = _stage_input(RAW_ROOT, tmp_path, "664170")
    cfg = _config(tmp_path)
    cfg.paths.rsync_data_dir = staged / "archive" / "cycle"
    cfg.paths.rsync_log_dir = staged

    result = run_pipeline(config=cfg, wmo=6990711)
    assert result.status == "ok", result.errors

    for path in _profile_files(cfg):
        pairs = _history(path, "HISTORY_ACTION", "HISTORY_QCTEST")
        actions = {a for a, _ in pairs}
        assert "QCP$" not in actions, f"RTQC provenance claimed while OFF: {path.name}"
        assert "QCF$" not in actions, f"RTQC provenance claimed while OFF: {path.name}"
        with netCDF4.Dataset(path) as ds:
            arr = np.atleast_1d(np.ma.filled(netCDF4.chartostring(ds["TEMP_QC"][:]), ""))
        joined = "".join(str(x) for x in arr.reshape(-1))
        assert set(joined) <= {"0"}, f"baseline TEMP_QC not NO_QC seed: {path.name}"


def test_pipeline_on_executes_common_rtqc(tmp_path: Path) -> None:
    staged = _stage_input(RAW_ROOT, tmp_path, "664170")
    cfg = _config(tmp_path)
    cfg.paths.rsync_data_dir = staged / "archive" / "cycle"
    cfg.paths.rsync_log_dir = staged
    cfg.rtqc.apply_rtqc = True

    result = run_pipeline(config=cfg, wmo=6990711)
    assert result.status == "ok", result.errors

    files = _profile_files(cfg)
    cycles = [int(p.stem.split("_")[1]) for p in files]
    assert cycles == sorted(cycles)

    for path, cycle in zip(files, cycles, strict=True):
        pairs = dict(_history(path, "HISTORY_ACTION", "HISTORY_QCTEST"))
        assert "QCP$" in pairs, f"no QCP$ record: {path.name}"
        mask = int(pairs["QCP$"], 16)
        executed = {n for n in range(1, 20) if mask & (1 << n)}

        # TEST004 is honestly skipped (no GEBCO grid configured) -- its
        # bit must be absent, not silently performed.
        assert 4 not in executed, f"TEST004 claimed without bathymetry: {path.name}"
        # Every other applicable test ran on every profile...
        expected = set(_EXPECTED_EXECUTED)
        if cycle == min(cycles):
            # First profile: no previous cycle exists for 5/16/18.
            expected -= {5, 16, 18}
        if cycle in (7,):
            # Reversed reception dt leaves speed undefined for TEST005.
            expected -= {5}
            assert 5 not in executed
        assert executed == expected, f"c{cycle}: executed {sorted(executed)} != {sorted(expected)}"

        # QCF$ is always emitted alongside QCP$ (truthful zero when
        # nothing failed).
        assert "QCF$" in pairs
        failed_mask = int(pairs["QCF$"], 16)

        def _flags(profile_path: Path, var: str) -> str:
            with netCDF4.Dataset(profile_path) as ds:
                arr = np.atleast_1d(np.ma.filled(netCDF4.chartostring(ds[var][:]), "")).reshape(-1)
            return "".join(str(x) for x in arr)

        temp_qc = _flags(path, "TEMP_QC")
        psal_qc = _flags(path, "PSAL_QC")
        pos_qc = _flags(path, "POSITION_QC")
        # Tests that ran and passed leave GOOD ('1'); executed tests
        # never leave the NO_QC seed behind on measured levels.
        assert set(temp_qc) <= {"1", "3", "4"}, f"c{cycle} TEMP_QC={set(temp_qc)}"
        assert set(psal_qc) <= {"1", "3", "4"}, f"c{cycle} PSAL_QC={set(psal_qc)}"

        if cycle in (5, 6):
            # Genuine impossible speed across the compressed reception
            # timestamps: POSITION_QC degrades on both endpoints, while
            # the QCF$ mask bit is attributed to the later cycle of the
            # pair (the Coriolis convention the GDAC references carry).
            assert pos_qc == "4", f"c{cycle} POSITION_QC={pos_qc}"
            if cycle == 6:
                assert failed_mask & (1 << 5), f"c{cycle} expected TEST005 failure"
        else:
            assert not (failed_mask & (1 << 5)), f"c{cycle} unexpected TEST005 failure"
            assert pos_qc == "1", f"c{cycle} POSITION_QC={pos_qc}"
