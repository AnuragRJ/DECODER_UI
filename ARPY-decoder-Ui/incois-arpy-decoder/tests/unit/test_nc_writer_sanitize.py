"""Regression tests for NetCDF writer attribute sanitization."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from argo_decoder.config.models import DecoderConfig
from argo_decoder.nc.writer import _sanitize_attrs, write_outputs
from argo_decoder.platforms.base import DecodeResult


def _make_ds() -> xr.Dataset:
    return xr.Dataset(
        {"PRES": (("N_LEVELS",), np.array([10.0, 20.0, 30.0], dtype=np.float64))},
        attrs={"wmo": 6902892, "cycle": 1, "notes": "ok"},
    )


def test_sanitize_converts_dict_attr_to_json_string() -> None:
    ds = _make_ds()
    ds.attrs["trajectory_bin_counts"] = {"290": 3, "292": 1}
    _sanitize_attrs(ds)
    val = ds.attrs["trajectory_bin_counts"]
    assert isinstance(val, str)
    assert json.loads(val) == {"290": 3, "292": 1}


def test_sanitize_leaves_primitives_alone() -> None:
    ds = _make_ds()
    ds.attrs["pi"] = "christine"
    ds.attrs["cycle"] = 42
    ds.attrs["q_thresh"] = 0.03
    ds.attrs["flag"] = b"1"
    ds.attrs["list_v"] = [1, 2, 3]
    _sanitize_attrs(ds)
    assert ds.attrs["pi"] == "christine"
    assert ds.attrs["cycle"] == 42
    assert ds.attrs["q_thresh"] == pytest.approx(0.03)
    assert ds.attrs["flag"] == b"1"
    assert ds.attrs["list_v"] == [1, 2, 3]


def test_sanitize_converts_none_to_empty_string() -> None:
    ds = _make_ds()
    ds.attrs["maybe"] = None
    _sanitize_attrs(ds)
    assert ds.attrs["maybe"] == ""


def test_write_outputs_with_dict_attrs_does_not_crash() -> None:
    """A dict-valued debug attr must not break the mono-profile write.

    Since Phase 5B the published ADMT file carries only the standard Argo
    global attributes, so ``trajectory_bin_counts`` is deliberately not
    written through; the point of this regression test is that the write
    still succeeds and the science survives.
    """
    ds = _make_ds()
    ds.attrs["trajectory_bin_counts"] = {"290": 3, "292": 1}
    res = DecodeResult(wmo=6902892)
    res.mono_profile_datasets[1] = ds
    with tempfile.TemporaryDirectory() as td:
        cfg = DecoderConfig()
        cfg.paths.nc_dir = td
        written = write_outputs(res, cfg)
        assert any(k.startswith("mono_") for k in written)
        nc_path = Path(td) / "6902892" / "profiles" / "R6902892_001.nc"
        with xr.open_dataset(nc_path) as loaded:
            assert "trajectory_bin_counts" not in loaded.attrs
            assert loaded.attrs["title"] == "Argo float vertical profile"
            np.testing.assert_array_equal(
                np.asarray(loaded["PRES"].values).ravel(),
                np.array([10.0, 20.0, 30.0], dtype=np.float32),
            )
