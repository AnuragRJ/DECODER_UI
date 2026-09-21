"""ARGOS cycle-file discovery tests."""

from __future__ import annotations

from argo_decoder.config.models import DecoderConfig, TransmissionType
from argo_decoder.io.rsync import discover


def test_discover_argos_format1_date_only_datetime_and_format2(tmp_path):
    root = tmp_path / "archive" / "cycle"
    root.mkdir(parents=True)
    (root / "102510_2012-01-02-03-04-05_2901339_007.txt").write_text("", encoding="ascii")
    (root / "152389_2026-01-04_2902222_328.txt").write_text("", encoding="ascii")
    fmt2_dir = root / "152399"
    fmt2_dir.mkdir()
    (fmt2_dir / "152399_2902201_12.txt").write_text("", encoding="ascii")

    cfg = DecoderConfig()
    cfg.transmission_type = TransmissionType.ARGOS
    cfg.paths.rsync_data_dir = root
    index = discover(cfg)

    assert sorted(index.all_imeis()) == ["102510", "152389", "152399"]
    assert index.files_for("102510")[0].received_at == "20120102T030405Z"
    assert index.files_for("152389")[0].received_at == "20260104T000000Z"
    assert index.files_for("152399")[0].cycle == 12
