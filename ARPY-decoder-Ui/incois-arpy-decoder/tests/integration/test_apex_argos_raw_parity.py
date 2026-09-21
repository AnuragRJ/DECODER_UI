"""Real raw APEX ARGOS sample parity checks against GDAC profile files."""

from __future__ import annotations

from pathlib import Path

import netCDF4
import numpy as np
import pytest

from argo_decoder.config import DecoderConfig
from argo_decoder.config.models import TransmissionType
from argo_decoder.pipeline.runner import run_pipeline
from argo_decoder.platforms.apex_argos.frames import (
    iter_argos_messages_from_payload,
    select_redundant_messages,
)
from argo_decoder.platforms.apex_argos.profile import decode_profile, layout_for_decoder

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_ROOT = REPO_ROOT / "phase4_reference" / "raw" / "raw-files"
GDAC_ROOT = REPO_ROOT / "phase4_reference" / "gdac_profiles"
DEMO_CSV = REPO_ROOT / "config" / "registry.csv"


@pytest.mark.parametrize(
    ("raw_path", "decoder_id", "gdac_path"),
    [
        (
            RAW_ROOT / "102510" / "102510_2011-12-27_2901339_001.txt",
            1005,
            GDAC_ROOT / "D2901339_001.nc",
        ),
        (
            RAW_ROOT / "152389" / "152389_2026-01-04_2902222_328.txt",
            1010,
            GDAC_ROOT / "R2902222_328.nc",
        ),
        (
            RAW_ROOT / "152382" / "152382_2025-12-26_2902223_326.txt",
            1010,
            GDAC_ROOT / "R2902223_327.nc",
        ),
    ],
)
def test_raw_argos_ctd_profile_matches_gdac(
    raw_path: Path, decoder_id: int, gdac_path: Path
) -> None:
    if not raw_path.exists() or not gdac_path.exists():
        pytest.skip("raw ARGOS/GDAC reference files are not present in this workspace")
    messages = iter_argos_messages_from_payload(raw_path.read_bytes(), frame_length=31)
    selected = select_redundant_messages(messages)
    decoded = decode_profile(selected, layout=layout_for_decoder(decoder_id))
    actual = np.array(
        list(
            zip(decoded.pressure_dbar, decoded.temperature_deg_c, decoded.salinity_psu, strict=True)
        ),
        dtype=np.float64,
    )
    actual = actual[np.argsort(actual[:, 0])]
    with netCDF4.Dataset(gdac_path) as ds:
        expected = np.column_stack(
            [
                np.ma.filled(ds.variables[name][:], np.nan).ravel().astype(np.float64)
                for name in ("PRES", "TEMP", "PSAL")
            ]
        )
    assert actual.shape == expected.shape
    np.testing.assert_allclose(actual[:, 0], expected[:, 0], rtol=0.0, atol=1e-3)
    np.testing.assert_allclose(actual[:, 1], expected[:, 1], rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(actual[:, 2], expected[:, 2], rtol=0.0, atol=2e-6)


def test_pipeline_uses_payload_output_cycle_for_shifted_argos_archive(tmp_path: Path) -> None:
    if not (RAW_ROOT / "152382").exists():
        pytest.skip("raw ARGOS reference files are not present in this workspace")
    cfg = DecoderConfig()
    cfg.transmission_type = TransmissionType.ARGOS
    cfg.metadata.backend = "csv"  # type: ignore[assignment]
    cfg.metadata.registry_path = DEMO_CSV
    cfg.paths.rsync_data_dir = RAW_ROOT
    for name in ("xml", "nc", "log", "csv", "iridium", "tmp"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
    cfg.paths.xml_dir = tmp_path / "xml"
    cfg.paths.nc_dir = tmp_path / "nc"
    cfg.paths.log_dir = tmp_path / "log"
    cfg.paths.csv_dir = tmp_path / "csv"
    cfg.paths.iridium_decoded_dir = tmp_path / "iridium"
    cfg.paths.temporary_dir = tmp_path / "tmp"
    result = run_pipeline(config=cfg, wmo=2902223, xml_filename="argos.xml")
    assert result.status == "ok"
    assert result.n_files == 3
    profile_dir = tmp_path / "nc" / "2902223" / "profiles"
    assert (profile_dir / "R2902223_327.nc").exists()
    assert (profile_dir / "R2902223_328.nc").exists()
    assert (profile_dir / "R2902223_329.nc").exists()
    assert not (profile_dir / "R2902223_326.nc").exists()


def test_pipeline_derives_argos_discovery_from_metadata(tmp_path: Path) -> None:
    if not (RAW_ROOT / "152389").exists():
        pytest.skip("raw ARGOS reference files are not present in this workspace")

    cfg = DecoderConfig()
    # Deliberately leave cfg.transmission_type at its default IRIDIUM_SBD.
    # The pipeline must load metadata first, read FLOAT_TRANSMISSION_TYPE=1,
    # and then discover ARGOS files.
    cfg.metadata.backend = "csv"  # type: ignore[assignment]
    cfg.metadata.registry_path = DEMO_CSV
    cfg.paths.rsync_data_dir = RAW_ROOT
    for name in ("xml", "nc", "log", "csv", "iridium", "tmp"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
    cfg.paths.xml_dir = tmp_path / "xml"
    cfg.paths.nc_dir = tmp_path / "nc"
    cfg.paths.log_dir = tmp_path / "log"
    cfg.paths.csv_dir = tmp_path / "csv"
    cfg.paths.iridium_decoded_dir = tmp_path / "iridium"
    cfg.paths.temporary_dir = tmp_path / "tmp"

    result = run_pipeline(
        config=cfg,
        wmo=2902222,
        xml_filename="argos_metadata_discovery.xml",
        write_nc=False,
        write_xml=False,
    )

    assert result.status == "ok"
    assert result.n_files == 3
    assert result.n_cycles == 3
    assert cfg.transmission_type == TransmissionType.ARGOS
