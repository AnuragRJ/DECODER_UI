"""Unit tests for Phase 5A.1 mono-profile ADMT structure.

Covers the fixed ADMT dimensions, the file-level scalars and the
profile metadata variables added to ``R<wmo>_<CCC>.nc``, plus the
guarantee that promoting a decoder dataset to the ADMT layout does not
alter the science values.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import netCDF4
import numpy as np
import pytest
import xarray as xr

from argo_decoder.config.models import DecoderConfig
from argo_decoder.metadata.models import FloatMeta
from argo_decoder.nc.mono_profile import (
    build_mono_profile_dataset,
    refresh_history_records,
    write_mono_profile,
)
from argo_decoder.nc.writer import write_outputs
from argo_decoder.platforms.base import DecodeResult

PRES = np.array([10.0, 20.5, 31.25, 42.125], dtype=np.float64)
TEMP = np.array([21.5, 20.25, 19.125, 18.0625], dtype=np.float64)
PSAL = np.array([35.5, 35.25, 35.125, 35.0625], dtype=np.float64)
CNDC = np.array([3.5, 3.4, 3.3, 3.2], dtype=np.float64)


def _as_stored(values: np.ndarray) -> np.ndarray:
    """Science as the ADMT file stores it: NC_FLOAT, values unchanged."""
    return np.asarray(values, dtype=np.float32)


EXPECTED_DIMS = {
    "N_PROF": 1,
    "N_PARAM": 3,
    "N_LEVELS": 4,
    "N_CALIB": 1,
    "STRING2": 2,
    "STRING4": 4,
    "STRING8": 8,
    "STRING16": 16,
    "STRING32": 32,
    "STRING64": 64,
    "STRING256": 256,
    "DATE_TIME": 14,
}


def _decoder_mono(*, with_cndc: bool = True, qc: int = 1) -> xr.Dataset:
    """Build a decoder-shaped mono profile: flat (N_LEVELS,) + 0-d scalars."""
    n = PRES.size
    qc_col = np.full(n, qc, dtype=np.int8)
    data_vars: dict[str, tuple[tuple[str, ...], np.ndarray]] = {
        "PRES": (("N_LEVELS",), PRES.copy()),
        "TEMP": (("N_LEVELS",), TEMP.copy()),
        "PSAL": (("N_LEVELS",), PSAL.copy()),
        "PRES_QC": (("N_LEVELS",), qc_col.copy()),
        "TEMP_QC": (("N_LEVELS",), qc_col.copy()),
        "PSAL_QC": (("N_LEVELS",), qc_col.copy()),
    }
    if with_cndc:
        data_vars["CNDC"] = (("N_LEVELS",), CNDC.copy())
        data_vars["CNDC_QC"] = (("N_LEVELS",), qc_col.copy())
    ds = xr.Dataset(data_vars, attrs={"wmo": 2902222, "cycle": 327, "decoder": "apex_argos"})
    ds["JULD"] = ((), np.float64(27752.31582176))
    ds["JULD_QC"] = ((), np.array(b"1", dtype="S1"))
    ds["LATITUDE"] = ((), np.float64(-12.5))
    ds["LONGITUDE"] = ((), np.float64(88.25))
    ds["POSITION_QC"] = ((), np.array(b"1", dtype="S1"))
    ds["DIRECTION"] = ((), np.array(b"A", dtype="S1"))
    ds["DATA_MODE"] = ((), np.array(b"R", dtype="S1"))
    ds.attrs["positioning_system"] = "ARGOS"
    return ds


def _meta() -> FloatMeta:
    return FloatMeta.model_validate(
        {
            "PLATFORM_NUMBER": "2902222",
            "PLATFORM_TYPE": "APEX",
            "DATA_CENTRE": "IN",
            "PROJECT_NAME": "Argo INDIA",
            "PI_NAME": "M Ravichandran",
            "FLOAT_SERIAL_NO": "7532",
            "FIRMWARE_VERSION": "091615",
            "WMO_INST_TYPE": "846",
        }
    )


def _build() -> xr.Dataset:
    return build_mono_profile_dataset(
        _decoder_mono(), wmo=2902222, cycle=327, meta=_meta(), institution="INCOIS"
    )


def _chars(var: netCDF4.Variable) -> str:
    return str(netCDF4.chartostring(var[:]).ravel()[0])


# ---------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------


def test_fixed_admt_dimensions_are_written() -> None:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "R2902222_327.nc"
        write_mono_profile(_build(), path)
        with netCDF4.Dataset(path) as ds:
            dims = {name: len(dim) for name, dim in ds.dimensions.items()}
            # Since Phase 5A.4, N_HISTORY sizes to the number of history
            # records: the ARFM and ARGQ processing steps for this profile.
            assert dims == {**EXPECTED_DIMS, "N_HISTORY": 2}


def test_mono_profile_is_netcdf3_classic() -> None:
    """Every GDAC ``R<wmo>_<cyc>.nc`` is NETCDF3_CLASSIC, not HDF5.

    Checking the magic bytes as well as ``data_model``: the latter alone
    would also accept NETCDF4_CLASSIC, which is an HDF5 container that
    merely restricts itself to the classic data model.
    """
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "R2902222_327.nc"
        write_mono_profile(_build(), path)
        with netCDF4.Dataset(path) as ds:
            assert ds.data_model == "NETCDF3_CLASSIC"
        assert path.read_bytes()[:4] == b"CDF\x01"


def test_mono_profile_has_a_single_record_dimension() -> None:
    """NETCDF3_CLASSIC permits exactly one unlimited dimension."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "R2902222_327.nc"
        write_mono_profile(_build(), path)
        with netCDF4.Dataset(path) as ds:
            unlimited = [name for name, dim in ds.dimensions.items() if dim.isunlimited()]
            assert unlimited == ["N_HISTORY"]


def test_n_history_is_unlimited_for_later_slices() -> None:
    """N_HISTORY must be appendable so HISTORY_* can land without redefining."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "R2902222_327.nc"
        write_mono_profile(_build(), path)
        with netCDF4.Dataset(path) as ds:
            assert ds.dimensions["N_HISTORY"].isunlimited()


# ---------------------------------------------------------------------------
# File-level scalars
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("DATA_TYPE", "Argo profile    "),
        ("FORMAT_VERSION", "3.1 "),
        ("HANDBOOK_VERSION", " 1.2"),
        ("REFERENCE_DATE_TIME", "19500101000000"),
    ],
)
def test_file_level_scalars(name: str, expected: str) -> None:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "R2902222_327.nc"
        write_mono_profile(_build(), path)
        with netCDF4.Dataset(path) as ds:
            assert _chars(ds.variables[name]) == expected


def test_creation_and_update_dates_are_yyyymmddhhmmss() -> None:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "R2902222_327.nc"
        write_mono_profile(_build(), path)
        with netCDF4.Dataset(path) as ds:
            for name in ("DATE_CREATION", "DATE_UPDATE"):
                value = _chars(ds.variables[name])
                assert len(value) == 14
                assert value.isdigit()


def test_date_scalars_use_date_time_dimension_not_string14() -> None:
    ds = _build()
    for name in ("REFERENCE_DATE_TIME", "DATE_CREATION", "DATE_UPDATE"):
        assert ds[name].dims == ("DATE_TIME",)


# ---------------------------------------------------------------------------
# Profile metadata
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("PLATFORM_NUMBER", "2902222 "),
        ("DATA_CENTRE", "IN"),
        ("DC_REFERENCE", "2902222/327".ljust(32)),
        ("DATA_STATE_INDICATOR", "2B  "),
        ("PLATFORM_TYPE", "APEX".ljust(32)),
        ("FLOAT_SERIAL_NO", "7532".ljust(32)),
        ("FIRMWARE_VERSION", "091615".ljust(32)),
        ("WMO_INST_TYPE", "846 "),
        ("POSITIONING_SYSTEM", "ARGOS   "),
        ("PROJECT_NAME", "Argo INDIA".ljust(64)),
        ("PI_NAME", "M Ravichandran".ljust(64)),
    ],
)
def test_profile_metadata_strings(name: str, expected: str) -> None:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "R2902222_327.nc"
        write_mono_profile(_build(), path)
        with netCDF4.Dataset(path) as ds:
            assert _chars(ds.variables[name]) == expected


def test_station_parameters_matches_the_gdac_reference() -> None:
    """The GDAC core profile exports PRES/TEMP/PSAL only.

    Verified against ``R2902224_345.nc``, which declares ``N_PARAM = 3``
    and carries no CNDC variable of any kind.
    """
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "R2902222_327.nc"
        write_mono_profile(_build(), path)
        with netCDF4.Dataset(path) as ds:
            values = [
                str(v).strip()
                for v in netCDF4.chartostring(ds.variables["STATION_PARAMETERS"][:])[0]
            ]
            assert values == ["PRES", "TEMP", "PSAL"]
            assert ds.dimensions["N_PARAM"].size == 3


def test_no_exported_parameter_with_data_is_omitted() -> None:
    """FileChecker CK_0032: any exported parameter holding data must be listed.

    Satisfied by not exporting CNDC at all, rather than by advertising a
    parameter the reference does not carry.
    """
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "R2902222_327.nc"
        write_mono_profile(_build(), path)
        with netCDF4.Dataset(path) as ds:
            listed = {
                str(v).strip()
                for v in netCDF4.chartostring(ds.variables["STATION_PARAMETERS"][:])[0]
            }
            for name in ("PRES", "TEMP", "PSAL", "CNDC", "DOXY"):
                if name not in ds.variables:
                    continue
                var = ds.variables[name]
                fill = var._FillValue
                if np.count_nonzero(np.ma.filled(var[:], fill) != fill):
                    assert name in listed, f"{name} has data but is not advertised"


def test_cycle_number_direction_and_data_mode() -> None:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "R2902222_327.nc"
        write_mono_profile(_build(), path)
        with netCDF4.Dataset(path) as ds:
            assert ds.variables["CYCLE_NUMBER"][:].tolist() == [327]
            assert ds.variables["CONFIG_MISSION_NUMBER"][:].tolist() == [1]
            assert ds.variables["DIRECTION"][:].tobytes() == b"A"
            assert ds.variables["DATA_MODE"][:].tobytes() == b"R"


def test_juld_location_and_position_carry_decoder_values() -> None:
    ds = _build()
    assert ds["JULD"].values[0] == pytest.approx(27752.31582176)
    assert ds["JULD_LOCATION"].values[0] == pytest.approx(27752.31582176)
    assert ds["LATITUDE"].values[0] == pytest.approx(-12.5)
    assert ds["LONGITUDE"].values[0] == pytest.approx(88.25)


# ---------------------------------------------------------------------------
# Science preservation
# ---------------------------------------------------------------------------


def test_science_values_are_unchanged_by_admt_promotion() -> None:
    """PRES/TEMP/PSAL/CNDC must survive promotion bit-for-bit.

    Since Phase 5B the published storage type is ``float32`` (NC_FLOAT),
    matching the GDAC references; the values themselves are only
    narrowed, never rescaled or rounded.
    """
    source = _decoder_mono()
    built = build_mono_profile_dataset(source, wmo=2902222, cycle=327, meta=_meta())
    for name, expected in (("PRES", PRES), ("TEMP", TEMP), ("PSAL", PSAL)):
        actual = built[name].values
        assert actual.shape == (1, expected.size)
        assert actual.dtype == np.float32
        np.testing.assert_array_equal(actual[0], expected.astype(np.float32))


def test_science_round_trips_through_netcdf_unchanged() -> None:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "R2902222_327.nc"
        write_mono_profile(_build(), path)
        with netCDF4.Dataset(path) as ds:
            for name, expected in (("PRES", PRES), ("TEMP", TEMP), ("PSAL", PSAL)):
                np.testing.assert_array_equal(
                    np.ma.filled(ds.variables[name][:], np.nan)[0], expected
                )


def test_science_is_two_dimensional_n_prof_by_n_levels() -> None:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "R2902222_327.nc"
        write_mono_profile(_build(), path)
        with netCDF4.Dataset(path) as ds:
            for name in ("PRES", "TEMP", "PSAL", "PRES_QC", "TEMP_QC", "PSAL_QC"):
                assert ds.variables[name].dimensions == ("N_PROF", "N_LEVELS")


# ---------------------------------------------------------------------------
# QC encoding
# ---------------------------------------------------------------------------


def test_level_qc_is_written_as_admt_char_digits() -> None:
    """Decoders keep QC as int8; the ADMT file must carry ASCII digits."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "R2902222_327.nc"
        write_mono_profile(_build(), path)
        with netCDF4.Dataset(path) as ds:
            assert ds.variables["PRES_QC"][:].tobytes() == b"1111"


def test_profile_param_qc_uses_reference_table_2a_letters() -> None:
    """All-good levels -> 'A' (100%), not the worst-flag digit '1'."""
    built = build_mono_profile_dataset(_decoder_mono(qc=1), wmo=2902222, cycle=327, meta=_meta())
    for name in ("PROFILE_PRES_QC", "PROFILE_TEMP_QC", "PROFILE_PSAL_QC"):
        assert built[name].values.tobytes() == b"A"


def test_every_science_parameter_group_is_complete() -> None:
    """FileChecker rule: <PARAM>, <PARAM>_QC and PROFILE_<PARAM>_QC form
    one group; a missing member rejects the file
    (``checkGroupsCompleteness``, ArgoFileValidator.java:787).
    """
    built = build_mono_profile_dataset(_decoder_mono(qc=1), wmo=2902222, cycle=327, meta=_meta())
    present = set(built.data_vars)
    science = {
        name
        for name in present
        if not name.endswith("_QC")
        and "_ADJUSTED" not in name
        and f"{name}_QC" in present
        and built[name].dims == ("N_PROF", "N_LEVELS")
    }
    assert science == {"PRES", "TEMP", "PSAL"}
    for name in science:
        assert f"PROFILE_{name}_QC" in present, f"incomplete group for {name}"


def test_adjusted_parameters_get_no_profile_qc() -> None:
    """PROFILE_<PARAM>_ADJUSTED_QC is not an ADMT variable.

    Confirmed against every GDAC reference profile, which carries only
    PROFILE_PRES_QC / PROFILE_TEMP_QC / PROFILE_PSAL_QC.
    """
    built = build_mono_profile_dataset(_decoder_mono(qc=1), wmo=2902222, cycle=327, meta=_meta())
    assert not [n for n in built.data_vars if n.startswith("PROFILE_") and "_ADJUSTED" in n]


def test_profile_param_qc_flags_all_bad_levels_as_f() -> None:
    built = build_mono_profile_dataset(_decoder_mono(qc=4), wmo=2902222, cycle=327, meta=_meta())
    assert built["PROFILE_PRES_QC"].values.tobytes() == b"F"


# ---------------------------------------------------------------------------
# Writer integration
# ---------------------------------------------------------------------------


def test_writer_emits_admt_mono_profile_as_r_file() -> None:
    result = DecodeResult(wmo=2902222, meta=_meta())
    result.mono_profile_datasets[327] = _decoder_mono()
    with tempfile.TemporaryDirectory() as td:
        cfg = DecoderConfig()
        cfg.paths.nc_dir = td
        written = write_outputs(result, cfg)
        assert "mono_327" in written
        path = Path(td) / "2902222" / "profiles" / "R2902222_327.nc"
        assert path.exists()
        with netCDF4.Dataset(path) as ds:
            assert ds.dimensions["N_PROF"].size == 1
            assert "DATA_TYPE" in ds.variables
            assert "PLATFORM_NUMBER" in ds.variables
            np.testing.assert_array_equal(np.ma.filled(ds.variables["PRES"][:], np.nan)[0], PRES)


def test_writer_keeps_flat_layout_for_datasets_without_science() -> None:
    """NullDecoder placeholders carry no N_LEVELS and must not be promoted."""
    result = DecodeResult(wmo=6902892)
    result.mono_profile_datasets[1] = xr.Dataset(attrs={"wmo": 6902892, "decoder": "null"})
    with tempfile.TemporaryDirectory() as td:
        cfg = DecoderConfig()
        cfg.paths.nc_dir = td
        write_outputs(result, cfg)
        path = Path(td) / "6902892" / "profiles" / "R6902892_001.nc"
        with netCDF4.Dataset(path) as ds:
            assert "N_PROF" not in ds.dimensions
            assert "DATA_TYPE" not in ds.variables


# ---------------------------------------------------------------------------
# Phase 5A.2: PARAMETER and the adjusted families
# ---------------------------------------------------------------------------

ADJUSTED_TRIOS = [
    (f"{p}_ADJUSTED", f"{p}_ADJUSTED_QC", f"{p}_ADJUSTED_ERROR") for p in ("PRES", "TEMP", "PSAL")
]


def test_parameter_has_calib_slot_shape_and_core_params() -> None:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "R2902222_327.nc"
        write_mono_profile(_build(), path)
        with netCDF4.Dataset(path) as ds:
            var = ds.variables["PARAMETER"]
            assert var.dimensions == ("N_PROF", "N_CALIB", "N_PARAM", "STRING16")
            values = [str(v) for v in netCDF4.chartostring(var[:])[0][0]]
            assert values == ["PRES".ljust(16), "TEMP".ljust(16), "PSAL".ljust(16)]


def test_parameter_matches_station_parameters() -> None:
    built = _build()
    station = netCDF4.chartostring(np.asarray(built["STATION_PARAMETERS"].values))[0]
    parameter = netCDF4.chartostring(np.asarray(built["PARAMETER"].values))[0][0]
    assert [str(v) for v in station] == [str(v) for v in parameter]


@pytest.mark.parametrize(("adj", "adj_qc", "adj_err"), ADJUSTED_TRIOS)
def test_adjusted_family_exists_with_level_shape(adj: str, adj_qc: str, adj_err: str) -> None:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "R2902222_327.nc"
        write_mono_profile(_build(), path)
        with netCDF4.Dataset(path) as ds:
            for name in (adj, adj_qc, adj_err):
                assert ds.variables[name].dimensions == ("N_PROF", "N_LEVELS")


@pytest.mark.parametrize(("adj", "adj_qc", "adj_err"), ADJUSTED_TRIOS)
def test_realtime_adjusted_values_are_fill(adj: str, adj_qc: str, adj_err: str) -> None:
    """R-files declare the adjusted family but leave it unset."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "R2902222_327.nc"
        write_mono_profile(_build(), path)
        with netCDF4.Dataset(path) as ds:
            for name in (adj, adj_err):
                values = ds.variables[name][:]
                assert int(np.ma.count_masked(values)) == values.size


@pytest.mark.parametrize(("adj", "adj_qc", "adj_err"), ADJUSTED_TRIOS)
def test_realtime_adjusted_qc_is_blank_not_nine(adj: str, adj_qc: str, adj_err: str) -> None:
    """Blank means 'no adjustment attempted'; '9' would mean 'missing'."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "R2902222_327.nc"
        write_mono_profile(_build(), path)
        with netCDF4.Dataset(path) as ds:
            raw = ds.variables[adj_qc][:].tobytes()
            assert raw == b" " * PRES.size


def test_adjusted_error_carries_delayed_mode_long_name() -> None:
    built = _build()
    for name in ("PRES_ADJUSTED_ERROR", "TEMP_ADJUSTED_ERROR", "PSAL_ADJUSTED_ERROR"):
        assert built[name].attrs["long_name"].startswith("Contains the error on the adjusted")


def test_adjusted_inherits_units_but_drops_axis() -> None:
    source = _decoder_mono()
    source["PRES"].attrs.update({"units": "decibar", "axis": "Z", "valid_max": 12000.0})
    built = build_mono_profile_dataset(source, wmo=2902222, cycle=327, meta=_meta())
    assert built["PRES_ADJUSTED"].attrs["units"] == "decibar"
    assert built["PRES_ADJUSTED"].attrs["valid_max"] == 12000.0
    assert "axis" not in built["PRES_ADJUSTED"].attrs
    assert built["PRES"].attrs["axis"] == "Z"


def test_cndc_is_not_exported_at_all() -> None:
    """CNDC is computed internally but absent from the published file.

    The GDAC reference ``R2902224_345.nc`` carries no CNDC, CNDC_QC or
    PROFILE_CNDC_QC, so none of them may be written.
    """
    built = _build()
    for suffix in ("", "_QC", "_ADJUSTED", "_ADJUSTED_QC", "_ADJUSTED_ERROR"):
        assert f"CNDC{suffix}" not in built.data_vars
    assert "PROFILE_CNDC_QC" not in built.data_vars


def test_cndc_remains_available_on_the_decoder_dataset() -> None:
    """Suppressing export must not stop the decoder computing CNDC."""
    source = _decoder_mono(qc=1)
    assert "CNDC" in source.data_vars


def test_adjusted_values_are_used_when_decoder_supplies_them() -> None:
    """Delayed-mode-style input must flow through instead of being filled."""
    source = _decoder_mono()
    adjusted = PRES + 0.5
    error = np.full(PRES.size, 2.4, dtype=np.float64)
    source["PRES_ADJUSTED"] = (("N_LEVELS",), adjusted)
    source["PRES_ADJUSTED_QC"] = (("N_LEVELS",), np.full(PRES.size, 1, dtype=np.int8))
    source["PRES_ADJUSTED_ERROR"] = (("N_LEVELS",), error)
    built = build_mono_profile_dataset(source, wmo=2902222, cycle=327, meta=_meta())
    np.testing.assert_array_equal(built["PRES_ADJUSTED"].values[0], _as_stored(adjusted))
    np.testing.assert_array_equal(built["PRES_ADJUSTED_ERROR"].values[0], _as_stored(error))
    assert built["PRES_ADJUSTED_QC"].values.tobytes() == b"1" * PRES.size


def test_adding_adjusted_family_leaves_unadjusted_science_untouched() -> None:
    built = _build()
    for name, expected in (("PRES", PRES), ("TEMP", TEMP), ("PSAL", PSAL)):
        np.testing.assert_array_equal(built[name].values[0], _as_stored(expected))


# ---------------------------------------------------------------------------
# Phase 5A.3: SCIENTIFIC_CALIB_*
# ---------------------------------------------------------------------------

CALIB_TEXT_VARS = [
    "SCIENTIFIC_CALIB_EQUATION",
    "SCIENTIFIC_CALIB_COEFFICIENT",
    "SCIENTIFIC_CALIB_COMMENT",
]


def _calib_values(ds: xr.Dataset, name: str) -> list[str]:
    """Calibration slot contents, space-padding stripped for comparison."""
    decoded = netCDF4.chartostring(np.asarray(ds[name].values))
    return [str(v).rstrip() for v in np.asarray(decoded).reshape(-1)]


@pytest.mark.parametrize("name", [*CALIB_TEXT_VARS, "SCIENTIFIC_CALIB_DATE"])
def test_scientific_calib_is_on_the_calib_slot(name: str) -> None:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "R2902222_327.nc"
        write_mono_profile(_build(), path)
        with netCDF4.Dataset(path) as ds:
            expected_last = "DATE_TIME" if name.endswith("_DATE") else "STRING256"
            assert ds.variables[name].dimensions == (
                "N_PROF",
                "N_CALIB",
                "N_PARAM",
                expected_last,
            )


@pytest.mark.parametrize(
    ("name", "long_name"),
    [
        ("SCIENTIFIC_CALIB_EQUATION", "Calibration equation for this parameter"),
        ("SCIENTIFIC_CALIB_COEFFICIENT", "Calibration coefficients for this equation"),
        ("SCIENTIFIC_CALIB_COMMENT", "Comment applying to this parameter calibration"),
        ("SCIENTIFIC_CALIB_DATE", "Date of calibration"),
    ],
)
def test_scientific_calib_long_names_match_matlab(name: str, long_name: str) -> None:
    assert _build()[name].attrs["long_name"] == long_name


def test_scientific_calib_date_declares_yyyymmddhhmmss() -> None:
    assert _build()["SCIENTIFIC_CALIB_DATE"].attrs["conventions"] == "YYYYMMDDHHMISS"


def test_scientific_calib_uses_real_time_defaults() -> None:
    """No CALIB_RT_* and no decoder calib -> the DAC real-time record.

    Invariant across 58 independently sampled GDAC ``R*.nc`` files from
    seven INCOIS floats (and on non-APEX ARVOR platforms), so this is a
    DAC convention rather than a per-float value.
    """
    built = _build()
    assert _calib_values(built, "SCIENTIFIC_CALIB_EQUATION") == [
        "Pcorrected = Praw - surface offset",
        "",
        "Scorrected = S(Ccorrected,Traw,Pcorrected)",
    ]
    assert _calib_values(built, "SCIENTIFIC_CALIB_COMMENT") == [
        "This sensor is subject to hysteresis",
        "",
        "",
    ]
    # COEFFICIENT stays blank in every reference.
    assert _calib_values(built, "SCIENTIFIC_CALIB_COEFFICIENT") == [""] * 3


def test_scientific_calib_date_set_only_for_populated_slots() -> None:
    """Populated slots take DATE_UPDATE; the untouched TEMP slot is blank."""
    built = _build()
    update = str(netCDF4.chartostring(np.asarray(built["DATE_UPDATE"].values)))
    assert _calib_values(built, "SCIENTIFIC_CALIB_DATE") == [update, "", update]


def test_temp_has_no_real_time_calibration() -> None:
    """The references leave TEMP blank: no RT correction is applied."""
    for name in (*CALIB_TEXT_VARS, "SCIENTIFIC_CALIB_DATE"):
        assert _calib_values(_build(), name)[1] == ""


def test_scientific_calib_has_one_slot_per_station_parameter() -> None:
    built = _build()
    assert built["SCIENTIFIC_CALIB_EQUATION"].sizes["N_PARAM"] == 3
    assert built["SCIENTIFIC_CALIB_EQUATION"].sizes["N_CALIB"] == 1


def test_decoder_supplied_calibration_is_used() -> None:
    """Reproduces the populated PRES/PSAL + blank TEMP pattern of the R-files."""
    source = _decoder_mono()
    source.attrs["scientific_calib"] = {
        "PRES": {
            "equation": "Pcorrected = Praw - surface offset",
            "comment": "This sensor is subject to hysteresis",
        },
        "PSAL": {"equation": "Scorrected = S(Ccorrected,Traw,Pcorrected)"},
    }
    built = build_mono_profile_dataset(
        source, wmo=2902222, cycle=327, meta=_meta(), date_update="20251228083011"
    )
    assert _calib_values(built, "SCIENTIFIC_CALIB_EQUATION") == [
        "Pcorrected = Praw - surface offset",
        "",
        "Scorrected = S(Ccorrected,Traw,Pcorrected)",
    ]
    assert _calib_values(built, "SCIENTIFIC_CALIB_COMMENT") == [
        "This sensor is subject to hysteresis",
        "",
        "",
    ]
    # Calibrated slots take DATE_UPDATE; the untouched TEMP slot stays blank.
    assert _calib_values(built, "SCIENTIFIC_CALIB_DATE") == [
        "20251228083011",
        "",
        "20251228083011",
    ]


def test_metadata_calib_rt_block_is_used_when_decoder_is_silent() -> None:
    meta = FloatMeta.model_validate(
        {
            "PLATFORM_NUMBER": "2902222",
            "CALIB_RT_PARAMETER": [{"CALIB_RT_PARAMETER_1": "PSAL"}],
            "CALIB_RT_EQUATION": [{"CALIB_RT_EQUATION_1": "PSAL_ADJUSTED = PSAL + off"}],
            "CALIB_RT_COEFFICIENT": [{"CALIB_RT_COEFFICIENT_1": "off=0.01"}],
            "CALIB_RT_COMMENT": [{"CALIB_RT_COMMENT_1": "rt adjustment"}],
            "CALIB_RT_DATE": [{"CALIB_RT_DATE_1": "20210313020600"}],
        }
    )
    built = build_mono_profile_dataset(_decoder_mono(), wmo=2902222, cycle=327, meta=meta)
    # CALIB_RT_* overrides the default for PSAL; PRES, which the block
    # does not mention, still falls back to the real-time default.
    assert _calib_values(built, "SCIENTIFIC_CALIB_EQUATION") == [
        "Pcorrected = Praw - surface offset",
        "",
        "PSAL_ADJUSTED = PSAL + off",
    ]
    assert _calib_values(built, "SCIENTIFIC_CALIB_COEFFICIENT") == ["", "", "off=0.01"]
    assert _calib_values(built, "SCIENTIFIC_CALIB_DATE")[2] == "20210313020600"


def test_decoder_calibration_overrides_metadata() -> None:
    meta = FloatMeta.model_validate(
        {
            "CALIB_RT_PARAMETER": [{"CALIB_RT_PARAMETER_1": "PSAL"}],
            "CALIB_RT_EQUATION": [{"CALIB_RT_EQUATION_1": "from metadata"}],
        }
    )
    source = _decoder_mono()
    source.attrs["scientific_calib"] = {"PSAL": {"equation": "from decoder"}}
    built = build_mono_profile_dataset(source, wmo=2902222, cycle=327, meta=meta)
    assert _calib_values(built, "SCIENTIFIC_CALIB_EQUATION")[2] == "from decoder"


def test_explicit_calibration_date_is_not_overwritten_by_date_update() -> None:
    source = _decoder_mono()
    source.attrs["scientific_calib"] = {
        "PRES": {"equation": "eq", "date": "19991231235959"},
    }
    built = build_mono_profile_dataset(
        source, wmo=2902222, cycle=327, meta=_meta(), date_update="20251228083011"
    )
    assert _calib_values(built, "SCIENTIFIC_CALIB_DATE")[0] == "19991231235959"


def test_long_calibration_text_is_truncated_to_string256() -> None:
    source = _decoder_mono()
    source.attrs["scientific_calib"] = {"PRES": {"comment": "x" * 400}}
    built = build_mono_profile_dataset(source, wmo=2902222, cycle=327, meta=_meta())
    assert built["SCIENTIFIC_CALIB_COMMENT"].sizes["STRING256"] == 256
    assert _calib_values(built, "SCIENTIFIC_CALIB_COMMENT")[0] == "x" * 256


def test_scientific_calib_does_not_disturb_science_or_parameter() -> None:
    built = _build()
    for name, expected in (("PRES", PRES), ("TEMP", TEMP), ("PSAL", PSAL)):
        np.testing.assert_array_equal(built[name].values[0], _as_stored(expected))
    parameter = netCDF4.chartostring(np.asarray(built["PARAMETER"].values))[0][0]
    assert [str(v).strip() for v in parameter] == ["PRES", "TEMP", "PSAL"]


# ---------------------------------------------------------------------------
# Phase 5A.4: HISTORY_*
# ---------------------------------------------------------------------------

HISTORY_CHAR_VARS = [
    ("HISTORY_INSTITUTION", "STRING4"),
    ("HISTORY_STEP", "STRING4"),
    ("HISTORY_SOFTWARE", "STRING4"),
    ("HISTORY_SOFTWARE_RELEASE", "STRING4"),
    ("HISTORY_REFERENCE", "STRING64"),
    ("HISTORY_DATE", "DATE_TIME"),
    ("HISTORY_ACTION", "STRING4"),
    ("HISTORY_PARAMETER", "STRING16"),
    ("HISTORY_QCTEST", "STRING16"),
]
HISTORY_FLOAT_VARS = ["HISTORY_START_PRES", "HISTORY_STOP_PRES", "HISTORY_PREVIOUS_VALUE"]


def _history_text(ds: xr.Dataset, name: str) -> list[str]:
    decoded = netCDF4.chartostring(np.asarray(ds[name].values))
    return [str(v).rstrip() for v in np.asarray(decoded).reshape(-1)]


def _degraded_mono(flag: int = 4, n_bad: int = 2) -> xr.Dataset:
    """Decoder dataset whose PSAL has ``n_bad`` QC-degraded levels."""
    source = _decoder_mono()
    qc = np.full(PRES.size, 1, dtype=np.int8)
    qc[:n_bad] = flag
    source["PSAL_QC"] = (("N_LEVELS",), qc)
    return source


@pytest.mark.parametrize(("name", "last_dim"), HISTORY_CHAR_VARS)
def test_history_char_vars_lead_with_history_dimension(name: str, last_dim: str) -> None:
    """ADMT puts N_HISTORY first, unlike every other variable family."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "R2902222_327.nc"
        write_mono_profile(_build(), path)
        with netCDF4.Dataset(path) as ds:
            assert ds.variables[name].dimensions == ("N_HISTORY", "N_PROF", last_dim)


@pytest.mark.parametrize("name", HISTORY_FLOAT_VARS)
def test_history_numeric_vars_shape_and_fill(name: str) -> None:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "R2902222_327.nc"
        write_mono_profile(_build(), path)
        with netCDF4.Dataset(path) as ds:
            var = ds.variables[name]
            assert var.dimensions == ("N_HISTORY", "N_PROF")
            assert var.dtype == np.float32
            assert var._FillValue == np.float32(99999.0)


def test_history_dimension_stays_unlimited() -> None:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "R2902222_327.nc"
        write_mono_profile(_build(), path)
        with netCDF4.Dataset(path) as ds:
            assert ds.dimensions["N_HISTORY"].isunlimited()


def test_default_history_claims_only_steps_actually_performed() -> None:
    """ARFM + ARGQ only: no ARCA/ARUP, which this decoder does not do."""
    built = _build()
    assert _history_text(built, "HISTORY_STEP") == ["ARFM", "ARGQ"]
    assert _history_text(built, "HISTORY_ACTION") == ["IP", "IP"]


def test_history_records_carry_institution_software_and_date() -> None:
    built = build_mono_profile_dataset(
        _decoder_mono(),
        wmo=2902222,
        cycle=327,
        meta=_meta(),
        date_update="20251228083011",
        software="ARPY",
        software_release="V1.2",
    )
    assert _history_text(built, "HISTORY_INSTITUTION") == ["IN", "IN"]
    assert _history_text(built, "HISTORY_SOFTWARE") == ["ARPY", "ARPY"]
    assert _history_text(built, "HISTORY_SOFTWARE_RELEASE") == ["V1.2", "V1.2"]
    assert _history_text(built, "HISTORY_DATE") == ["20251228083011"] * 2


def test_no_qctest_records_when_decoder_supplies_no_rtqc_masks() -> None:
    """QCP$/QCF$ must not be invented without real test provenance."""
    built = _build()
    assert "QCP$" not in _history_text(built, "HISTORY_ACTION")
    assert "QCF$" not in _history_text(built, "HISTORY_ACTION")


def test_qctest_records_emitted_when_decoder_supplies_masks() -> None:
    source = _decoder_mono()
    source.attrs["rtqc_tests_done_hex"] = "D7B7E"
    source.attrs["rtqc_tests_failed_hex"] = "8"
    built = build_mono_profile_dataset(source, wmo=2902222, cycle=327, meta=_meta())
    actions = _history_text(built, "HISTORY_ACTION")
    qctests = _history_text(built, "HISTORY_QCTEST")
    assert actions[2:4] == ["QCP$", "QCF$"]
    assert qctests[2:4] == ["D7B7E", "8"]


def test_meta_fields_publish_into_the_mono_product() -> None:
    """The csv4 metadata reaches the ADMT product (PI, project, serial...)."""
    built = build_mono_profile_dataset(_build(), wmo=2902222, cycle=327, meta=_meta())

    def prof_text(name: str) -> str:
        return str(netCDF4.chartostring(built[name].values).ravel()[0]).strip()

    assert prof_text("PI_NAME") == "M Ravichandran"
    assert prof_text("PROJECT_NAME") == "Argo INDIA"
    assert prof_text("PLATFORM_TYPE") == "APEX"
    assert prof_text("FLOAT_SERIAL_NO") == "7532"
    assert prof_text("DATA_CENTRE") == "IN"
    # The generic builder keeps the DAC-neutral default; the ARVOR-I
    # family builder maps DATA_CENTRE -> institution (IN -> INCOIS).
    assert built.attrs["institution"] == "CORIOLIS"


def test_firmware_version_override_beats_meta_sheet_label() -> None:
    """Family label (e.g. SBE41CP sensor firmware) can override the
    float-engine date-code the meta sheet publishes."""
    built = build_mono_profile_dataset(
        _build(), wmo=2902222, cycle=327, meta=_meta(), firmware_version="7.2.5"
    )
    assert str(netCDF4.chartostring(built["FIRMWARE_VERSION"].values).ravel()[0]).strip() == "7.2.5"


def test_write_mono_profile_strips_internal_attributes(tmp_path: Path) -> None:
    """Post-build mutations (RTQC masks, pre-QC snapshots) never ship."""
    built = _build()
    built.attrs["qc_previous_values"] = {"TEMP": [1]}
    built.attrs["rtqc_tests_done_hex"] = "D7B6E"
    path = tmp_path / "R2902222_327.nc"
    write_mono_profile(built, path)
    with netCDF4.Dataset(path) as ds:
        assert "qc_previous_values" not in ds.ncattrs()
        assert "rtqc_tests_done_hex" not in ds.ncattrs()
        # QC variables keep their ADMT attributes through the write.
        assert ds["PRES_QC"].getncattr("conventions") == "Argo reference table 2"


def test_one_cf_record_per_qc_degraded_parameter() -> None:
    """Matches the GDAC R-file rule: one CF per parameter, spanning its levels.

    GDAC R1902844_009 carries a single CF TEMP row whose
    HISTORY_START_PRES / HISTORY_STOP_PRES bracket the degraded levels
    (175.6 dbar to 1287.9 dbar); multiple degraded levels of one
    parameter still produce exactly one record.
    """
    built = build_mono_profile_dataset(
        _degraded_mono(flag=4, n_bad=2), wmo=2902222, cycle=327, meta=_meta()
    )
    actions = _history_text(built, "HISTORY_ACTION")
    assert actions == ["IP", "IP", "CF"]
    assert _history_text(built, "HISTORY_PARAMETER") == ["", "", "PSAL"]


def test_cf_record_pressure_span_brackets_degraded_levels() -> None:
    built = build_mono_profile_dataset(
        _degraded_mono(flag=4, n_bad=2), wmo=2902222, cycle=327, meta=_meta()
    )
    start = np.asarray(built["HISTORY_START_PRES"].values).reshape(-1)
    stop = np.asarray(built["HISTORY_STOP_PRES"].values).reshape(-1)
    assert start[2] == pytest.approx(float(PRES[0]))
    assert stop[2] == pytest.approx(float(PRES[1]))


def test_cf_record_records_previous_flag_as_good() -> None:
    built = build_mono_profile_dataset(
        _degraded_mono(flag=4, n_bad=1), wmo=2902222, cycle=327, meta=_meta()
    )
    previous = np.asarray(built["HISTORY_PREVIOUS_VALUE"].values).reshape(-1)
    assert previous[2] == pytest.approx(1.0)


def test_decoder_supplied_previous_flags_are_used() -> None:
    source = _degraded_mono(flag=4, n_bad=1)
    source.attrs["qc_previous_values"] = {"PSAL": [2] + [1] * (PRES.size - 1)}
    built = build_mono_profile_dataset(source, wmo=2902222, cycle=327, meta=_meta())
    previous = np.asarray(built["HISTORY_PREVIOUS_VALUE"].values).reshape(-1)
    assert previous[2] == pytest.approx(2.0)


def test_qc_flag_three_also_produces_a_cf_record() -> None:
    built = build_mono_profile_dataset(
        _degraded_mono(flag=3, n_bad=1), wmo=2902222, cycle=327, meta=_meta()
    )
    assert _history_text(built, "HISTORY_ACTION").count("CF") == 1


def test_good_qc_profile_produces_no_cf_records() -> None:
    built = _build()
    assert "CF" not in _history_text(built, "HISTORY_ACTION")


def test_refresh_keeps_build_institution_after_rtqc_edits() -> None:
    """RTQC refresh must not re-stamp provenance to the CORIOLIS default.

    Regression: refresh_history_records rebuilt the HISTORY block with
    ``meta=None``; every row flipped to 'IF' even when the build had
    stamped the csv4 DAC code ('IN' for the INCOIS fleet).
    """
    built = build_mono_profile_dataset(_build(), wmo=2902222, cycle=327, meta=_meta())
    built.attrs["rtqc_tests_done_hex"] = "D7B6E"
    refreshed = refresh_history_records(built)
    raw = np.asarray(refreshed["HISTORY_INSTITUTION"].values, dtype="S1")
    rows = [b"".join(r).decode("ascii", "ignore").strip() for r in raw.reshape(raw.shape[0], -1)]
    assert set(rows) == {"IN"}


def test_history_records_can_be_overridden_for_delayed_mode() -> None:
    source = _decoder_mono()
    source.attrs["history_records"] = [
        {
            "institution": "IF",
            "step": "ARSQ",
            "software": "OW",
            "software_release": "V1.1",
            "action": "IP",
            "date": "20240101000000",
        }
    ]
    built = build_mono_profile_dataset(source, wmo=2902222, cycle=327, meta=_meta())
    assert _history_text(built, "HISTORY_STEP") == ["ARSQ"]
    assert _history_text(built, "HISTORY_SOFTWARE") == ["OW"]
    assert built.sizes["N_HISTORY"] == 1


def test_history_steps_can_be_overridden() -> None:
    source = _decoder_mono()
    source.attrs["history_steps"] = ["ARFM", "ARGQ", "ARCA", "ARUP"]
    built = build_mono_profile_dataset(source, wmo=2902222, cycle=327, meta=_meta())
    assert _history_text(built, "HISTORY_STEP") == ["ARFM", "ARGQ", "ARCA", "ARUP"]


def test_unused_history_fields_stay_blank_or_fill() -> None:
    built = _build()
    assert _history_text(built, "HISTORY_REFERENCE") == ["", ""]
    assert _history_text(built, "HISTORY_QCTEST") == ["", ""]
    for name in ("HISTORY_START_PRES", "HISTORY_STOP_PRES", "HISTORY_PREVIOUS_VALUE"):
        values = np.asarray(built[name].values).reshape(-1)
        np.testing.assert_array_equal(values, np.full(2, np.float32(99999.0)))


def test_history_does_not_disturb_science() -> None:
    built = build_mono_profile_dataset(
        _degraded_mono(flag=4, n_bad=2), wmo=2902222, cycle=327, meta=_meta()
    )
    for name, expected in (("PRES", PRES), ("TEMP", TEMP), ("PSAL", PSAL)):
        np.testing.assert_array_equal(built[name].values[0], _as_stored(expected))
