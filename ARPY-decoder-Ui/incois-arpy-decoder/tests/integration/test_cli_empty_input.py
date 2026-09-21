"""A decode that reads no telemetry must fail, not report success.

Before this was fixed, pointing ``--input`` at a tree that held no files
for the requested WMO produced ``status="ok"`` with ``n_files=0`` and a
single ``<wmo>_meta.nc`` -- which is written from metadata alone and so
appears even when nothing was decoded. A mistyped path was therefore
indistinguishable from a real run.
"""

from __future__ import annotations

from pathlib import Path

from argo_decoder.config import DecoderConfig
from argo_decoder.metadata import builder
from argo_decoder.metadata.multi_csv_loader import MultiCsvLoader
from argo_decoder.pipeline.runner import run_pipeline

REPO_ROOT = Path(__file__).resolve().parents[2]
METADATA_DIR = REPO_ROOT / "config" / "metadata"


def _config(tmp_path: Path, data_dir: Path) -> DecoderConfig:
    cfg = DecoderConfig()
    cfg.metadata.backend = "csv4"  # type: ignore[assignment]
    cfg.metadata.registry_path = METADATA_DIR
    cfg.paths.rsync_data_dir = data_dir
    cfg.paths.rsync_log_dir = data_dir
    out = tmp_path / "out"
    for name in ("xml", "nc", "log", "csv", "iridium", "tmp"):
        (out / name).mkdir(parents=True, exist_ok=True)
    cfg.paths.xml_dir = out / "xml"
    cfg.paths.nc_dir = out / "nc"
    cfg.paths.log_dir = out / "log"
    cfg.paths.csv_dir = out / "csv"
    cfg.paths.iridium_decoded_dir = out / "iridium"
    cfg.paths.temporary_dir = out / "tmp"
    return cfg


def test_empty_input_is_reported_as_failure(tmp_path: Path) -> None:
    """Zero discovered files must set ``nok`` and explain why."""
    empty = tmp_path / "empty"
    empty.mkdir()
    result = run_pipeline(config=_config(tmp_path, empty), wmo=2901304)

    assert result.n_files == 0
    assert result.status == "nok"
    assert result.errors, "an empty decode must carry an explanatory error"
    joined = " ".join(result.errors)
    assert "no input files" in joined
    # The message has to name the directory actually searched, which is
    # the single most useful fact when the layout is wrong.
    assert str(empty) in joined


def test_nonexistent_input_directory_is_also_a_failure(tmp_path: Path) -> None:
    """Discovery returns empty for a missing dir; that is still not ok."""
    result = run_pipeline(config=_config(tmp_path, tmp_path / "nope"), wmo=2901304)
    assert result.status == "nok"
    assert result.n_files == 0


def test_materialize_from_four_csv_carries_calibration(tmp_path: Path) -> None:
    """The four-CSV backend must round-trip PREDEPLOYMENT_CALIB_* to JSON.

    Materialising from the legacy single ``registry.csv`` writes ``"n/a"``
    for these fields, which the writer renders as blank and the Argo file
    checker rejects with six "Empty" errors.
    """
    row = MultiCsvLoader(METADATA_DIR).get_float(2901304)
    assert row is not None
    path = builder.write_meta_json(builder.build_meta(row), tmp_path)

    import json

    payload = json.loads(path.read_text())
    for key in ("PREDEPLOYMENT_CALIB_EQUATION", "PREDEPLOYMENT_CALIB_COEFFICIENT"):
        values = [v for entry in payload[key] for v in entry.values()]
        assert len(values) == 3
        assert all(v and v != "n/a" for v in values), f"{key} must be populated"
    coefficients = [
        v for entry in payload["PREDEPLOYMENT_CALIB_COEFFICIENT"] for v in entry.values()
    ]
    assert coefficients[0].startswith("ser# = 5234 pressure coeffs:")
