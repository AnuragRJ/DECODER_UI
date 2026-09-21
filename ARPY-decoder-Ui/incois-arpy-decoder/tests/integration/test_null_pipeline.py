"""Tests that run the null-decoder end to end against the demo dataset."""

from __future__ import annotations

from pathlib import Path

from argo_decoder.config import load_config
from argo_decoder.pipeline.runner import run_pipeline


def test_null_decode_produces_nc_and_xml(
    demo_config: Path, demo_input: Path, tmp_path: Path
) -> None:
    cfg = load_config(demo_config)
    # Point the cfg at our demo input and tmp output.
    cfg.paths.rsync_data_dir = demo_input / "archive" / "cycle"
    cfg.paths.rsync_log_dir = demo_input / "rsync_list"
    cfg.paths.float_info_dir = demo_config.parent / "decArgo_config_floats" / "json_float_info"
    cfg.paths.float_meta_dir = (
        demo_config.parent / "decArgo_config_floats" / "json_float_meta_ir_sbd"
    )
    cfg.paths.xml_dir = tmp_path / "xml"
    cfg.paths.log_dir = tmp_path / "log"
    cfg.paths.csv_dir = tmp_path / "csv"
    cfg.paths.nc_dir = tmp_path / "nc"
    cfg.paths.nc_traj_3_1_dir = tmp_path / "nc"
    cfg.paths.nc_traj_3_2_dir = tmp_path / "nc"
    cfg.paths.iridium_decoded_dir = tmp_path / "iridium"

    result = run_pipeline(config=cfg, wmo=6902892, use_null_decoder=True, write_xml=True)
    assert result.status == "ok"
    assert result.n_cycles > 0
    # The demo IMEI directory for float 6902892 contains ~2215 co_*.txt files
    # (all cycles shipped in the demo data bundle).
    assert result.n_files > 40
    # XML report should be written.
    assert result.xml_report is not None and result.xml_report.exists()
    # NC directory should contain a mono-profile file per cycle in profiles/
    # plus the multi-profile <wmo>_prof.nc at the float root.
    nc_dir = tmp_path / "nc" / "6902892"
    assert nc_dir.exists()
    mono_files = list((nc_dir / "profiles").glob("R*.nc"))
    assert len(mono_files) == result.n_cycles
    assert (nc_dir / "6902892_prof.nc").exists()
