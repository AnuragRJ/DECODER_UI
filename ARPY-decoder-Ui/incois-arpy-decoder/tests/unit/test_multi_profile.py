"""Unit tests for M6 multi-profile stacking (<wmo>_prof.nc)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import netCDF4
import numpy as np
import pytest
import xarray as xr

from argo_decoder.metadata.models import FloatMeta
from argo_decoder.nc.multi_profile import build_multi_profile_dataset, write_multi_profile


def _mono(
    cycle: int,
    pres: np.ndarray,
    temp: np.ndarray,
    psal: np.ndarray,
    *,
    cndc: np.ndarray | None = None,
    doxy: np.ndarray | None = None,
    direction: bytes = b"A",
    data_mode: bytes = b"R",
    juld: float = 1000.0,
    juld_qc: bytes = b"1",
    lat: float = -47.0,
    lon: float = -47.0,
    pos_qc: bytes = b"1",
) -> xr.Dataset:
    n = pres.size
    qc = np.array([b"1"] * n, dtype="S1")
    data_vars: dict[str, tuple[str, np.ndarray]] = {
        "PRES": (("N_LEVELS",), pres),
        "TEMP": (("N_LEVELS",), temp),
        "PSAL": (("N_LEVELS",), psal),
        "PRES_QC": (("N_LEVELS",), qc.copy()),
        "TEMP_QC": (("N_LEVELS",), qc.copy()),
        "PSAL_QC": (("N_LEVELS",), qc.copy()),
    }
    if cndc is not None:
        data_vars["CNDC"] = (("N_LEVELS",), cndc)
        data_vars["CNDC_QC"] = (("N_LEVELS",), np.array([b"1"] * cndc.size, dtype="S1"))
    if doxy is not None:
        data_vars["DOXY"] = (("N_LEVELS",), doxy)
        data_vars["DOXY_QC"] = (("N_LEVELS",), np.array([b"1"] * doxy.size, dtype="S1"))
    ds = xr.Dataset(data_vars)
    ds["DIRECTION"] = xr.DataArray(np.array([direction], dtype="S1"), dims=("string1",))
    ds["DATA_MODE"] = xr.DataArray(np.array([data_mode], dtype="S1"), dims=("string1",))
    ds["JULD"] = xr.DataArray(np.float64(juld))
    ds["JULD_QC"] = xr.DataArray(np.array([juld_qc], dtype="S1"), dims=("string1",))
    ds["LATITUDE"] = xr.DataArray(np.float64(lat))
    ds["LONGITUDE"] = xr.DataArray(np.float64(lon))
    ds["POSITION_QC"] = xr.DataArray(np.array([pos_qc], dtype="S1"), dims=("string1",))
    ds.attrs["cycle"] = cycle
    return ds


def _meta() -> FloatMeta:
    return FloatMeta.model_validate(
        {
            "PLATFORM_NUMBER": "6902892",
            "PI_NAME": "Christine PROVOST",
            "PROJECT_NAME": "GMMC BACI",
            "DATA_CENTRE": "IF",
            "PLATFORM_TYPE": "ARVOR_D",
            "FLOAT_SERIAL_NO": "AD2700-18FR005",
            "FIRMWARE_VERSION": "5608A14",
            "WMO_INST_TYPE": "838",
            "POSITIONING_SYSTEM": [
                {"POSITIONING_SYSTEM": "GPS"},
                {"POSITIONING_SYSTEM": "IRIDIUM"},
            ],
        }
    )


def test_build_multi_profile_dataset_stacks_two_profiles() -> None:
    mono = {
        1: _mono(
            1,
            pres=np.array([10.0, 20.0, 30.0], dtype=np.float64),
            temp=np.array([10.0, 9.0, 8.0], dtype=np.float64),
            psal=np.array([35.0, 35.0, 35.0], dtype=np.float64),
        ),
        2: _mono(
            2,
            pres=np.array([5.0, 15.0], dtype=np.float64),
            temp=np.array([12.0, 11.0], dtype=np.float64),
            psal=np.array([34.5, 34.6], dtype=np.float64),
            juld=2000.0,
            lat=-40.0,
            lon=-50.0,
        ),
    }
    ds = build_multi_profile_dataset(mono, _meta(), wmo=6902892, decoder_version="test")

    assert ds.sizes["N_PROF"] == 2
    assert ds.sizes["N_LEVELS"] == 3  # max of 3 and 2
    assert ds.sizes["N_PARAM"] == 3  # PRES/TEMP/PSAL (no CNDC/DOXY)
    # Cycle ordering
    np.testing.assert_array_equal(ds["CYCLE_NUMBER"].values, np.array([1, 2], dtype=np.int32))
    # JULD per profile
    np.testing.assert_allclose(ds["JULD"].values, [1000.0, 2000.0])
    # PRES padded
    np.testing.assert_allclose(
        ds["PRES"].values,
        # Short profiles pad to the stack's N_LEVELS with the ADMT
        # 99999.0 fill (aligned with the mono-profile files in Phase 6A).
        np.array([[10.0, 20.0, 30.0], [5.0, 15.0, 99999.0]], dtype=np.float32),
        atol=1e-6,
    )
    # Padded slots carry blank QC, matching the GDAC references: profile 9
    # of 2902223_prof.nc has 58/59 real levels, pad QC ' ' and
    # PROFILE_PRES_QC 'A'.
    assert bytes(ds["PRES_QC"].values[1, 2]) == b" "
    # PROFILE_<PARAM>_QC is the reference-table-2a letter grade (all levels
    # good -> 'A'), not the worst per-level digit. Padding is excluded from
    # the percentage, so a short profile still grades 'A'.
    assert bytes(ds["PROFILE_PRES_QC"].values[0]) == b"A"
    assert bytes(ds["PROFILE_PRES_QC"].values[1]) == b"A"

    # PLATFORM_NUMBER is 8-char padded
    assert bytes(ds["PLATFORM_NUMBER"].values[0]).rstrip() == b"6902892"


def test_write_multi_profile_round_trip_has_no_string1_dim() -> None:
    mono = {
        1: _mono(
            1,
            pres=np.array([100.0, 200.0], dtype=np.float64),
            temp=np.array([8.0, 7.0], dtype=np.float64),
            psal=np.array([35.0, 35.0], dtype=np.float64),
            cndc=np.array([3.5, 3.6], dtype=np.float64),
            doxy=np.array([200.0, 210.0], dtype=np.float64),
        )
    }
    ds = build_multi_profile_dataset(mono, _meta(), wmo=6902892, decoder_version="test")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "6902892_prof.nc"
        write_multi_profile(ds, p)
        assert p.exists() and p.stat().st_size > 0
        with netCDF4.Dataset(p, "r") as ncf:
            # No spurious string1 dimension
            assert "string1" not in ncf.dimensions
            # Correct scalar-char dims (data type is |S1, dim = STRING16 only)
            assert ncf.variables["DATA_TYPE"].dimensions == ("STRING16",)
            assert ncf.variables["REFERENCE_DATE_TIME"].dimensions == ("DATE_TIME",)
            # QC per-profile vars are plain 1-D NC_CHAR
            assert ncf.variables["DIRECTION"].dimensions == ("N_PROF",)
            assert ncf.variables["JULD_QC"].dimensions == ("N_PROF",)
            assert ncf.variables["PRES_QC"].dimensions == ("N_PROF", "N_LEVELS")
            # STATION_PARAMETERS is 3-D
            assert ncf.variables["STATION_PARAMETERS"].dimensions == (
                "N_PROF",
                "N_PARAM",
                "STRING16",
            )
            # FillValue for PRES
            assert abs(ncf.variables["PRES"]._FillValue - 99999.0) < 1e-6
            # Science values round-trip
            np.testing.assert_allclose(ncf.variables["PRES"][0, :2], [100.0, 200.0])


def test_write_multi_profile_rejects_empty_profile_set() -> None:
    with pytest.raises(ValueError, match="at least one profile"):
        build_multi_profile_dataset({}, _meta(), wmo=6902892)


# ---------------------------------------------------------------------------
# Phase 6A: multi-profile aligned with the post-5B ADMT conventions
# ---------------------------------------------------------------------------


def test_core_params_use_admt_float32_and_fill() -> None:
    """<wmo>_prof.nc must share the mono-profile storage conventions."""
    ds = build_multi_profile_dataset(
        {
            1: _mono(
                1,
                pres=np.array([10.0, 20.0], dtype=np.float64),
                temp=np.array([10.0, 9.0], dtype=np.float64),
                psal=np.array([35.0, 35.0], dtype=np.float64),
            )
        },
        meta=None,
        wmo=6902892,
    )
    for name in ("PRES", "TEMP", "PSAL"):
        assert ds[name].dtype == np.float32
        assert ds[name].attrs["_FillValue"] == np.float32(99999.0)


def test_core_param_long_names_match_reference_spelling() -> None:
    ds = build_multi_profile_dataset(
        {
            1: _mono(
                1,
                pres=np.array([10.0], dtype=np.float64),
                temp=np.array([10.0], dtype=np.float64),
                psal=np.array([35.0], dtype=np.float64),
            )
        },
        meta=None,
        wmo=6902892,
    )
    assert ds["PRES"].attrs["long_name"] == "Sea water pressure, equals 0 at sea-level"
    assert ds["TEMP"].attrs["long_name"] == "Sea temperature in-situ ITS-90 scale"
    assert ds["PSAL"].attrs["standard_name"] == "sea_water_salinity"


def test_institution_is_mapped_through_reference_table_4() -> None:
    ds = build_multi_profile_dataset(
        {
            1: _mono(
                1,
                pres=np.array([10.0], dtype=np.float64),
                temp=np.array([10.0], dtype=np.float64),
                psal=np.array([35.0], dtype=np.float64),
            )
        },
        meta=None,
        wmo=2902222,
        institution="IN",
    )
    assert ds.attrs["institution"] == "INCOIS"


def test_decoder_version_is_not_a_published_global() -> None:
    ds = build_multi_profile_dataset(
        {
            1: _mono(
                1,
                pres=np.array([10.0], dtype=np.float64),
                temp=np.array([10.0], dtype=np.float64),
                psal=np.array([35.0], dtype=np.float64),
            )
        },
        meta=None,
        wmo=6902892,
        decoder_version="1.2.3",
    )
    assert "decoder_version" not in ds.attrs
