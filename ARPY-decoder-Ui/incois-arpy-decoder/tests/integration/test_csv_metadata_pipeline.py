"""Integration test: end-to-end pipeline with the CSV metadata backend."""

from __future__ import annotations

from pathlib import Path

import pytest

from argo_decoder.config import DecoderConfig
from argo_decoder.pipeline.runner import run_pipeline

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_CSV = REPO_ROOT / "config" / "registry.csv"


@pytest.fixture(scope="module")
def demo_input() -> Path:
    workspace = REPO_ROOT.parent
    return (
        workspace
        / "Coriolis-data-processing-chain-for-Argo-floats-container"
        / "decArgo_demo"
        / "input"
    )


def test_csv_backend_end_to_end(demo_input: Path, tmp_path: Path):
    assert DEMO_CSV.exists(), "config/registry.csv must be bootstrapped"
    cfg = DecoderConfig()
    cfg.metadata.backend = "csv"  # type: ignore[assignment]
    cfg.metadata.registry_path = DEMO_CSV
    cfg.paths.rsync_data_dir = demo_input / "archive" / "cycle"
    cfg.paths.rsync_log_dir = demo_input / "rsync_list"
    out = tmp_path / "out"
    for name in ("xml", "nc", "log", "csv", "iridium", "tmp"):
        (out / name).mkdir(parents=True, exist_ok=True)
    cfg.paths.xml_dir = out / "xml"
    cfg.paths.nc_dir = out / "nc"
    cfg.paths.log_dir = out / "log"
    cfg.paths.csv_dir = out / "csv"
    cfg.paths.iridium_decoded_dir = out / "iridium"
    cfg.paths.temporary_dir = out / "tmp"

    result = run_pipeline(
        config=cfg,
        wmo=6902892,
        xml_filename="test.xml",
        use_null_decoder=True,
    )
    assert result.status == "ok"
    assert result.n_cycles == 2215
    assert result.n_files == 2215
    assert result.xml_report is not None
    assert result.xml_report.exists()
    nc_root = out / "nc" / "6902892"
    mono_files = list((nc_root / "profiles").glob("R*.nc"))
    prof_file = nc_root / "6902892_prof.nc"
    assert len(mono_files) == 2215
    assert prof_file.exists()
