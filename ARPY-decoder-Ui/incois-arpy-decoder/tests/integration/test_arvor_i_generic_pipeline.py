"""End-to-end generic pipeline for ARVOR-I: four CSVs -> routing -> adapter.

Runs the real ``run_pipeline`` on preserved ARVOR-I raw telemetry with the
``csv4`` metadata backend. The four CSVs are the ONLY metadata source:
their family signature (manufacturer + CTD model + comms) routes the
float to ArvorISbdDecoder via PROFILE_CLASS; registry.csv provides
nothing. The raw tree is staged into the Iridium
``archive/cycle/<transceiver>/`` layout the discovery layer documents.
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


def test_generic_pipeline_decodes_arvor_i_from_fleet_csvs(tmp_path: Path) -> None:
    staged = _stage_input(RAW_ROOT, tmp_path, "664170")  # transceiver dir = sheet PTT
    cfg = _config(tmp_path)
    cfg.paths.rsync_data_dir = staged / "archive" / "cycle"
    cfg.paths.rsync_log_dir = staged

    result = run_pipeline(config=cfg, wmo=6990711)

    assert result.status == "ok", result.errors
    out = Path(cfg.paths.nc_dir) / "6990711"
    assert (out / "6990711_tech.nc").exists()
    assert (out / "6990711_Rtraj.nc").exists()
    assert (out / "6990711_meta.nc").exists()

    # csv4 metadata reaches every non-mono product: DAC code 'IN' in the
    # file, mapped institution name in the global (GDAC refs: INCOIS),
    # and the launch mission number 1 on Rtraj/meta (GDAC meta/mono = 1).
    def _centre(path: Path) -> str:
        with netCDF4.Dataset(path) as ds:
            arr = np.ma.filled(ds["DATA_CENTRE"][...], b" ")
            arr = arr.reshape(-1, arr.shape[-1])
            return str(netCDF4.chartostring(arr[0])).strip()

    # The published tech file carries exactly the GDAC ARVOR-I parameter
    # slots (family-generic projection -- no WMO/cycle conditionals), so
    # any current or future float of this family receives the same shape.
    from argo_decoder.nc.technical_arvor import _GDAC_TECH_SLOTS

    tech_path = out / "6990711_tech.nc"
    with netCDF4.Dataset(tech_path) as ds:
        ds.set_auto_mask(False)
        name_rows = ds["TECHNICAL_PARAMETER_NAME"][:]
        published = [str(netCDF4.chartostring(r)).strip() for r in name_rows]
        cycle_numbers = [int(c) for c in ds["CYCLE_NUMBER"][:]]
    slot_names = [n for n, _, _ in _GDAC_TECH_SLOTS]
    n_cycles = len(set(cycle_numbers))
    assert len(published) == 22 * n_cycles
    for i in range(n_cycles):
        assert published[i * 22 : (i + 1) * 22] == slot_names
    assert len(set(published)) == 21  # no internal-only names leak

    for name in ("6990711_tech.nc", "6990711_Rtraj.nc", "6990711_meta.nc"):
        with netCDF4.Dataset(out / name) as ds:
            assert ds.institution == "INCOIS", name
            assert _centre(out / name) == "IN", name
    for name in ("6990711_Rtraj.nc", "6990711_meta.nc"):
        with netCDF4.Dataset(out / name) as ds:
            values = np.ma.filled(ds["CONFIG_MISSION_NUMBER"][...], -1).ravel()
            used = {float(v) for v in values if 0 < float(v) < 99998}
            assert used == {1.0}, (name, used)
    profiles = sorted((out / "profiles").glob("R6990711_*.nc"))
    assert profiles, "no mono profiles written"
