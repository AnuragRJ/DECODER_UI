"""Unit tests for the JsonLoader metadata backend."""

from __future__ import annotations

from pathlib import Path

from argo_decoder.metadata import JsonLoader
from argo_decoder.metadata.validators import validate_float_info

DEMO_ROOT = (
    Path(__file__).resolve().parents[3]
    / "Coriolis-data-processing-chain-for-Argo-floats-container"
    / "decArgo_demo"
)
# tests/unit/test_metadata_loader.py sits 4 levels below workspace root:
# workspace/argo-decoder-python/tests/unit/ → parents[3]=workspace
# (mirror of conftest.py logic)


def test_json_loader_finds_demo_floats() -> None:
    info_dir = DEMO_ROOT / "config" / "decArgo_config_floats" / "json_float_info"
    meta_dir = DEMO_ROOT / "config" / "decArgo_config_floats" / "json_float_meta_ir_sbd"
    loader = JsonLoader(info_dir, meta_dir)

    rows = list(loader.iter_floats())
    wmos = {r.wmo for r in rows}
    assert 6902892 in wmos
    assert 6903014 in wmos

    info = loader.load_info(6902892)
    assert info.wmo == 6902892
    assert info.float_type == "PROVOR"
    report = validate_float_info(info)
    assert report.ok, [i.message for i in report.issues]

    meta = loader.load_meta(6902892)
    assert meta.platform_number == "6902892"
    assert meta.platform_maker == "NKE"
