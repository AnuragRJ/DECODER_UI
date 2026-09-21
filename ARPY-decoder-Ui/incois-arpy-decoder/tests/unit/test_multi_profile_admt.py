"""ADMT parity for the multi-profile ``<wmo>_prof.nc`` product.

The mono-profile writer received the Phase 5A.1-5A.4 ADMT upgrades
(fixed dimensions, ``PARAMETER``, ``SCIENTIFIC_CALIB_*``, ``HISTORY_*``,
the adjusted trios and the reference-table-2a ``PROFILE_<PARAM>_QC``)
while the multi-profile stacker did not. These tests pin the contract
that both products are built from the same building blocks.

The central guard is
:func:`test_multi_profile_cycle_matches_mono_profile_bit_for_bit`: for
every shared variable, profile *N* of ``<wmo>_prof.nc`` must equal
``R<wmo>_<N>.nc``. Any future divergence between the two writers fails
here rather than being discovered against the GDAC months later.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import netCDF4
import numpy as np
import pytest
import xarray as xr

from argo_decoder.metadata.models import FloatMeta
from argo_decoder.nc.mono_profile import build_mono_profile_dataset, write_mono_profile
from argo_decoder.nc.multi_profile import build_multi_profile_dataset, write_multi_profile

# ---------------------------------------------------------------------------
# Fixtures: three cycles with *different* level counts, so N_LEVELS padding
# is genuinely exercised (WMO 2901339 really does carry 57/58/59).
# ---------------------------------------------------------------------------

_LEVEL_COUNTS = {1: 59, 2: 58, 3: 57}


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


def _decoder_mono(cycle: int, n_levels: int) -> xr.Dataset:
    """One decoder-shaped mono dataset with ``n_levels`` real levels."""
    rng = np.arange(n_levels, dtype=np.float32)
    pres = 5.0 + rng * 20.0
    temp = 25.0 - rng * 0.3
    psal = 34.5 + rng * 0.01
    cndc = 4.2 + rng * 0.001
    qc = np.ones(n_levels, dtype=np.int8)
    data_vars: dict[str, Any] = {
        "PRES": (("N_LEVELS",), pres),
        "TEMP": (("N_LEVELS",), temp),
        "PSAL": (("N_LEVELS",), psal),
        "CNDC": (("N_LEVELS",), cndc),
        "PRES_QC": (("N_LEVELS",), qc.copy()),
        "TEMP_QC": (("N_LEVELS",), qc.copy()),
        "PSAL_QC": (("N_LEVELS",), qc.copy()),
        "CNDC_QC": (("N_LEVELS",), qc.copy()),
    }
    ds = xr.Dataset(data_vars)
    for name in ("PRES", "TEMP", "PSAL", "CNDC"):
        ds[name].attrs["_FillValue"] = np.float32(99999.0)
    ds.attrs.update(
        {
            "cycle_number": cycle,
            "juld": 27000.0 + cycle,
            "latitude": -58.8,
            "longitude": -134.0,
            "juld_location": 27000.0 + cycle,
            "position_qc": "1",
            "juld_qc": "1",
            "data_mode": "R",
            "direction": "A",
        }
    )
    return ds


def _mono_set() -> dict[int, xr.Dataset]:
    return {c: _decoder_mono(c, n) for c, n in _LEVEL_COUNTS.items()}


def _build_multi() -> xr.Dataset:
    return build_multi_profile_dataset(_mono_set(), meta=_meta(), wmo=2902222)


def _chars(value: Any) -> str:
    return str(netCDF4.chartostring(np.asarray(value)))


# ---------------------------------------------------------------------------
# THE invariant: prof.nc profile N == R<wmo>_N.nc
# ---------------------------------------------------------------------------

#: Variables that legitimately differ between the two products.
#:
#: ``HISTORY_*`` is not stacked: every GDAC ``_prof.nc`` checked carries
#: ``N_HISTORY = 0`` (six INCOIS floats, mixed R and D). The mono file
#: keeps its own per-cycle history.
#: ``SCIENTIFIC_CALIB_DATE`` defaults to DATE_UPDATE, so the two files can
#: land on either side of a second boundary when written separately.
_PROFILE_ONLY = {"DATE_CREATION", "DATE_UPDATE", "SCIENTIFIC_CALIB_DATE"}


def _history(name: str) -> bool:
    return name.startswith("HISTORY_")


@pytest.mark.parametrize("cycle", sorted(_LEVEL_COUNTS))
def test_multi_profile_cycle_matches_mono_profile_bit_for_bit(cycle: int, tmp_path: Path) -> None:
    """Profile *N* of the stacked file equals the standalone mono file.

    Values are compared only over each cycle's own level count: the
    stacked file pads shorter profiles out to the file-wide maximum,
    which is correct ADMT behaviour rather than a difference.
    """
    monos = _mono_set()
    multi_path = tmp_path / "2902222_prof.nc"
    write_multi_profile(build_multi_profile_dataset(monos, meta=_meta(), wmo=2902222), multi_path)

    mono_path = tmp_path / f"R2902222_{cycle:03d}.nc"
    write_mono_profile(
        build_mono_profile_dataset(monos[cycle], wmo=2902222, cycle=cycle, meta=_meta()),
        mono_path,
    )

    n_real = _LEVEL_COUNTS[cycle]
    with netCDF4.Dataset(multi_path) as multi, netCDF4.Dataset(mono_path) as mono:
        index = int(np.where(np.ma.filled(multi["CYCLE_NUMBER"][:], -1) == cycle)[0][0])

        missing = [
            name for name in mono.variables if name not in multi.variables and not _history(name)
        ]
        assert not missing, f"multi-profile file is missing {missing}"

        for name in mono.variables:
            if name in _PROFILE_ONLY or _history(name):
                continue
            mono_var, multi_var = mono[name], multi[name]
            if "N_PROF" not in mono_var.dimensions:
                continue  # file-level scalar, compared separately

            left = np.ma.filled(mono_var[0], -9999)
            right = np.ma.filled(multi_var[index], -9999)
            if left.ndim and left.shape and "N_LEVELS" in mono_var.dimensions:
                left, right = left[:n_real], right[:n_real]
            assert np.array_equal(np.asarray(left), np.asarray(right)), (
                f"{name} differs between prof.nc[{index}] and R..._{cycle:03d}.nc"
            )


# ---------------------------------------------------------------------------
# Structure: the Phase 5A building blocks must reach the stacked file
# ---------------------------------------------------------------------------


def test_multi_profile_is_netcdf3_classic(tmp_path: Path) -> None:
    """Every GDAC ``<wmo>_prof.nc`` is NETCDF3_CLASSIC, not HDF5.

    The Coriolis chain writes with ``netcdf.create(..., 'NC_CLOBBER')``
    (``nc_create_multi_prof_file.m:468``), which yields classic. Guard the
    magic bytes too: ``data_model`` alone would still pass for
    NETCDF4_CLASSIC, which is an HDF5 container.
    """
    path = tmp_path / "p.nc"
    write_multi_profile(_build_multi(), path)
    with netCDF4.Dataset(path) as ds:
        assert ds.data_model == "NETCDF3_CLASSIC"
    assert path.read_bytes()[:4] == b"CDF\x01"


def test_multi_profile_has_a_single_record_dimension(tmp_path: Path) -> None:
    """NETCDF3_CLASSIC permits exactly one unlimited dimension."""
    path = tmp_path / "p.nc"
    write_multi_profile(_build_multi(), path)
    with netCDF4.Dataset(path) as ds:
        unlimited = [name for name, dim in ds.dimensions.items() if dim.isunlimited()]
        assert unlimited == ["N_HISTORY"]


def test_admt_dimensions_present(tmp_path: Path) -> None:
    """N_CALIB and N_HISTORY are required; both were absent before."""
    path = tmp_path / "p.nc"
    write_multi_profile(_build_multi(), path)
    with netCDF4.Dataset(path) as ds:
        assert ds.dimensions["N_CALIB"].size == 1
        # Every GDAC _prof.nc carries N_HISTORY = 0.
        assert ds.dimensions["N_HISTORY"].size == 0
        assert ds.dimensions["N_PARAM"].size == 3
        assert ds.dimensions["N_PROF"].size == len(_LEVEL_COUNTS)


def test_required_admt_variables_present(tmp_path: Path) -> None:
    path = tmp_path / "p.nc"
    write_multi_profile(_build_multi(), path)
    required = [
        "PARAMETER",
        "SCIENTIFIC_CALIB_EQUATION",
        "SCIENTIFIC_CALIB_COEFFICIENT",
        "SCIENTIFIC_CALIB_COMMENT",
        "SCIENTIFIC_CALIB_DATE",
        "HISTORY_INSTITUTION",
        "HISTORY_STEP",
        "HISTORY_SOFTWARE",
        "HISTORY_SOFTWARE_RELEASE",
        "HISTORY_REFERENCE",
        "HISTORY_DATE",
        "HISTORY_ACTION",
        "HISTORY_PARAMETER",
        "HISTORY_START_PRES",
        "HISTORY_STOP_PRES",
        "HISTORY_PREVIOUS_VALUE",
        "HISTORY_QCTEST",
    ]
    for param in ("PRES", "TEMP", "PSAL"):
        required += [f"{param}_ADJUSTED", f"{param}_ADJUSTED_QC", f"{param}_ADJUSTED_ERROR"]
    with netCDF4.Dataset(path) as ds:
        absent = [name for name in required if name not in ds.variables]
        assert not absent, f"missing ADMT variables: {absent}"


def test_cndc_is_not_exported(tmp_path: Path) -> None:
    """The mono writer excludes decoder-derived CNDC; so must the stacker."""
    path = tmp_path / "p.nc"
    write_multi_profile(_build_multi(), path)
    with netCDF4.Dataset(path) as ds:
        assert not [v for v in ds.variables if "CNDC" in v]
        params = [
            str(v).strip()
            for v in np.asarray(netCDF4.chartostring(ds["STATION_PARAMETERS"][:])).reshape(-1)
        ]
        assert set(params) == {"PRES", "TEMP", "PSAL"}


# ---------------------------------------------------------------------------
# Semantics that were wrong because the stacker predated APEX support
# ---------------------------------------------------------------------------


def test_profile_param_qc_uses_reference_table_2a(tmp_path: Path) -> None:
    """Letter grade, not the worst-flag digit and not a hardcoded '9'."""
    path = tmp_path / "p.nc"
    write_multi_profile(_build_multi(), path)
    with netCDF4.Dataset(path) as ds:
        for name in ("PROFILE_PRES_QC", "PROFILE_TEMP_QC", "PROFILE_PSAL_QC"):
            flags = set(ds[name][:].tobytes().decode())
            assert flags == {"A"}, f"{name} = {flags}, expected table-2a 'A'"


def test_config_mission_number_is_the_mission_not_the_cycle(tmp_path: Path) -> None:
    """GDAC reports 1 for all 348 profiles of WMO 2902222."""
    path = tmp_path / "p.nc"
    write_multi_profile(_build_multi(), path)
    with netCDF4.Dataset(path) as ds:
        values = np.ma.filled(ds["CONFIG_MISSION_NUMBER"][:], -1).tolist()
        assert values == [1] * len(_LEVEL_COUNTS), values
        assert (
            ds["CONFIG_MISSION_NUMBER"].long_name
            == "Unique number denoting the missions performed by the float"
        )
        assert ds["CONFIG_MISSION_NUMBER"].conventions == "1...N, 1 : first complete mission"


def test_dc_reference_is_wmo_slash_cycle(tmp_path: Path) -> None:
    path = tmp_path / "p.nc"
    write_multi_profile(_build_multi(), path)
    with netCDF4.Dataset(path) as ds:
        values = [
            str(v).strip()
            for v in np.asarray(netCDF4.chartostring(ds["DC_REFERENCE"][:])).reshape(-1)
        ]
        assert values == [f"2902222/{c}" for c in sorted(_LEVEL_COUNTS)]


def test_vertical_sampling_scheme_is_discrete(tmp_path: Path) -> None:
    """APEX transmits discrete levels; 'averaged' was a PROVOR assumption."""
    path = tmp_path / "p.nc"
    write_multi_profile(_build_multi(), path)
    with netCDF4.Dataset(path) as ds:
        values = {
            str(v).strip()
            for v in np.asarray(netCDF4.chartostring(ds["VERTICAL_SAMPLING_SCHEME"][:])).reshape(-1)
        }
        assert values == {"Primary sampling: discrete []"}


# ---------------------------------------------------------------------------
# N_LEVELS padding across three different level counts
# ---------------------------------------------------------------------------


def test_shorter_profiles_are_padded_with_fill_and_qc_9(tmp_path: Path) -> None:
    """57/58/59-level cycles stack to N_LEVELS=59 without corrupting data."""
    path = tmp_path / "p.nc"
    write_multi_profile(_build_multi(), path)
    with netCDF4.Dataset(path) as ds:
        assert ds.dimensions["N_LEVELS"].size == max(_LEVEL_COUNTS.values())
        cycles = np.ma.filled(ds["CYCLE_NUMBER"][:], -1)
        for cycle, n_real in _LEVEL_COUNTS.items():
            index = int(np.where(cycles == cycle)[0][0])
            pres = np.ma.filled(ds["PRES"][index], 99999.0)
            assert int(np.count_nonzero(pres != 99999.0)) == n_real
            qc = ds["PRES_QC"][index].tobytes().decode()
            assert set(qc[:n_real]) == {"1"}
            assert set(qc[n_real:]) <= {"9", " "}


# ---------------------------------------------------------------------------
# HISTORY_* descriptive attributes (must exist even though N_HISTORY == 0)
# ---------------------------------------------------------------------------

#: Verified verbatim against the GDAC ``_prof.nc`` references for WMO
#: 2902222 and 2902223. A value of ``None`` means the reference does not
#: carry that attribute, so we must not add it either.
_EXPECTED_HISTORY_ATTRS: dict[str, tuple[str, str | None, str | None]] = {
    "HISTORY_INSTITUTION": (
        "Institution which performed action",
        "Argo reference table 4",
        None,
    ),
    "HISTORY_STEP": ("Step in data processing", "Argo reference table 12", None),
    "HISTORY_SOFTWARE": (
        "Name of software which performed action",
        "Institution dependent",
        None,
    ),
    "HISTORY_SOFTWARE_RELEASE": (
        "Version/release of software which performed action",
        "Institution dependent",
        None,
    ),
    "HISTORY_REFERENCE": ("Reference of database", "Institution dependent", None),
    "HISTORY_DATE": ("Date the history record was created", "YYYYMMDDHHMISS", None),
    "HISTORY_ACTION": ("Action performed on data", "Argo reference table 7", None),
    "HISTORY_PARAMETER": (
        "Station parameter action is performed on",
        "Argo reference table 3",
        None,
    ),
    "HISTORY_START_PRES": ("Start pressure action applied on", None, "decibar"),
    "HISTORY_STOP_PRES": ("Stop pressure action applied on", None, "decibar"),
    "HISTORY_PREVIOUS_VALUE": (
        "Parameter/Flag previous value before action",
        None,
        None,
    ),
    "HISTORY_QCTEST": (
        "Documentation of tests performed, tests failed (in hex form)",
        "Write tests performed when ACTION=QCP$; tests failed when ACTION=QCF$",
        None,
    ),
}


@pytest.mark.parametrize("name", sorted(_EXPECTED_HISTORY_ATTRS))
def test_history_variables_carry_descriptive_attributes(name: str, tmp_path: Path) -> None:
    """Attributes must be written at creation time, not per record.

    ``N_HISTORY`` is 0 for every ``_prof.nc``, so any assignment driven by
    a per-record loop never runs and the ADMT format check reports 23
    missing-attribute errors.
    """
    path = tmp_path / "p.nc"
    write_multi_profile(_build_multi(), path)
    long_name, conventions, units = _EXPECTED_HISTORY_ATTRS[name]
    with netCDF4.Dataset(path) as ds:
        variable = ds[name]
        assert variable.long_name == long_name
        if conventions is None:
            assert "conventions" not in variable.ncattrs()
        else:
            assert variable.conventions == conventions
        if units is None:
            assert "units" not in variable.ncattrs()
        else:
            assert variable.units == units


def test_history_group_stays_empty(tmp_path: Path) -> None:
    """Adding attributes must not add records."""
    path = tmp_path / "p.nc"
    write_multi_profile(_build_multi(), path)
    with netCDF4.Dataset(path) as ds:
        assert ds.dimensions["N_HISTORY"].size == 0
        for name in _EXPECTED_HISTORY_ATTRS:
            assert ds[name].shape[0] == 0
