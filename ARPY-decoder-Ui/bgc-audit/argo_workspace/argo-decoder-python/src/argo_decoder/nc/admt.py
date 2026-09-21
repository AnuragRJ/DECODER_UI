"""Shared ADMT NetCDF primitives.

Common building blocks for every ADMT product (``R*.nc`` mono profiles,
``<wmo>_Rtraj.nc`` trajectories and, later, ``<wmo>_meta.nc`` /
``<wmo>_tech.nc``):

* the fixed Argo string dimensions;
* fixed-width ``NC_CHAR`` encoding helpers;
* the Argo reference table 4 data-centre to institution mapping;
* the set of decoder-internal attributes that must not reach a
  published file;
* the eight standard Argo global attributes;
* a generic ``netCDF4`` writer.

The writer deliberately bypasses ``xarray.to_netcdf``: xarray appends a
spurious trailing ``string1`` dimension to every ``dtype='S1'`` array,
which breaks ADMT compliance, and it only emits dimensions that carry
data, whereas ADMT requires fixed dimensions to exist even when unused.

This module is pure and does no IO beyond :func:`write_admt_dataset`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal

import netCDF4
import numpy as np
import xarray as xr

# ---------------------------------------------------------------------------
# Fixed ADMT string dimensions (Argo user manual 3.1, table 4)
# ---------------------------------------------------------------------------
STRING2 = 2
STRING4 = 4
STRING8 = 8
STRING16 = 16
STRING32 = 32
STRING64 = 64
STRING128 = 128
STRING256 = 256
STRING1024 = 1024
DATE_TIME_LEN = 14  # YYYYMMDDHHMMSS; the dimension is named ``DATE_TIME``

# On-disk format for every ADMT product.
#
# Every GDAC reference file -- mono-profile, multi-profile, trajectory,
# metadata and technical -- is NETCDF3_CLASSIC, as produced by the Coriolis
# chain's ``netcdf.create(ncPathFileName, 'NC_CLOBBER')``
# (nc_create_multi_prof_file.m:468). Classic imposes two constraints the
# writers must respect: at most one unlimited dimension per file, and that
# dimension must be the first dimension of any variable using it. The
# largest reference file is 1.64 MB, far inside the 2 GiB classic limit, so
# NETCDF3_64BIT_OFFSET is not needed.
ADMT_NC_FORMAT: Final[Literal["NETCDF3_CLASSIC"]] = "NETCDF3_CLASSIC"

# Argo fill values shared across products.
CHAR_FILL = b" "
DOUBLE_FILL = np.float64(99999.0)
JULD_FILL = np.float64(999999.0)
FLOAT_FILL = np.float32(99999.0)
INT_FILL = np.int32(99999)

# JULD storage resolution advertised by the GDAC profile references.
JULD_RESOLUTION = np.float64(1e-5)


def encode_padded(value: str, width: int) -> bytes:
    """Encode to UTF-8 and right-pad (or truncate) to exactly ``width``."""
    raw = str(value)[:width].encode("utf-8")
    return raw + b" " * (width - len(raw))


def char_array(value: str, width: int) -> np.ndarray:
    """Return a 1-D ``S1`` array holding ``value`` padded to ``width``."""
    return np.frombuffer(encode_padded(value, width), dtype="S1").copy()


def scalar_char(value: str, width: int, dim: str | None = None) -> xr.DataArray:
    """Build a file-level ``(STRING<width>,)`` char variable.

    ``dim`` overrides the dimension name, which matters for date-valued
    scalars: ADMT puts those on ``DATE_TIME``, not ``STRING14``.
    """
    name = dim if dim is not None else f"STRING{width}"
    return xr.DataArray(char_array(value, width), dims=(name,))


def date_char(value: str) -> xr.DataArray:
    """Build a ``(DATE_TIME,)`` char variable for a YYYYMMDDHHMISS stamp."""
    return scalar_char(value, DATE_TIME_LEN, dim="DATE_TIME")


def scalar_flag(value: str | bytes) -> xr.DataArray:
    """Build a 0-d single-character variable (e.g. ``LAUNCH_QC``)."""
    raw = value.encode("ascii") if isinstance(value, str) else bytes(value)
    return xr.DataArray(np.array((raw[:1] or b" "), dtype="S1"))


def char_column(values: list[str], width: int, dim: str) -> xr.DataArray:
    """Build a 2-D ``(<dim>, STRING<width>)`` char array."""
    n = len(values)
    buf = bytearray(n * width)
    for i, value in enumerate(values):
        buf[i * width : (i + 1) * width] = encode_padded(value, width)
    arr = np.frombuffer(bytes(buf), dtype="S1").reshape(n, width)
    name = "DATE_TIME" if width == DATE_TIME_LEN else f"STRING{width}"
    return xr.DataArray(arr.copy(), dims=(dim, name))


def flag_column(values: list[str | bytes], dim: str) -> xr.DataArray:
    """Build a 1-D single-character flag array over ``dim``."""
    out = np.full(len(values), b" ", dtype="S1")
    for i, value in enumerate(values):
        raw = value.encode("ascii") if isinstance(value, str) else bytes(value)
        out[i] = raw[:1] or b" "
    return xr.DataArray(out, dims=(dim,))


# ---------------------------------------------------------------------------
# Argo reference table 4: DAC code -> institution name
# ---------------------------------------------------------------------------
DAC_INSTITUTION: dict[str, str] = {
    "AO": "AOML",
    "BO": "BODC",
    "CS": "CSIRO",
    "GE": "BSH",
    "HZ": "CSIO",
    "IF": "IFREMER",
    "IN": "INCOIS",
    "JA": "JMA",
    "KM": "KMA",
    "KO": "KORDI",
    "ME": "MEDS",
    "NA": "NAVO",
    "NM": "NMDIS",
    "PM": "PMEL",
    "SI": "SIO",
    "SP": "SPRI",
    "UW": "UW",
    "VL": "ISDGM",
    "WH": "WHOI",
}


def institution_for_data_centre(code: str) -> str:
    """Return the reference table 4 institution name for a DAC code.

    Unknown codes pass through unchanged so a new DAC still yields a
    meaningful attribute rather than an empty one.
    """
    key = str(code).strip().upper()
    return DAC_INSTITUTION.get(key, str(code).strip())


# ---------------------------------------------------------------------------
# Decoder-internal attributes
# ---------------------------------------------------------------------------
# Useful on the in-memory dataset (the multi-profile builder and the
# audit tooling read several of them) but not part of a published ADMT
# product, whose global attributes are exactly the eight standard ones.
INTERNAL_ATTRS: frozenset[str] = frozenset(
    {
        "apex_profile_class",
        "argos_location_class",
        "config_mission_number",
        "convention",
        "cycle",
        "data_state_indicator",
        "decoded_profile_number",
        "decoder",
        "decoder_id",
        "decoder_version",
        "engineering",
        "expected_profile_length",
        "frame_length",
        "history_records",
        "history_steps",
        "n_argos_fixes",
        "n_argos_messages",
        "n_argos_selected_messages",
        "n_crc_ok_messages",
        "output_cycle_number",
        "platform_type",
        "positioning_system",
        "qc_previous_values",
        "raw_cycle_number",
        "received_profile_bytes",
        "rtqc_tests_done_hex",
        "rtqc_tests_failed_hex",
        "scientific_calib",
        "superseded_raw_cycle_number",
        "trajectory_bin_counts",
        "vertical_sampling_scheme",
        "wmo",
    }
)


def standard_globals(
    *,
    title: str,
    institution: str,
    feature_type: str,
    created: datetime | None = None,
) -> dict[str, str]:
    """Return the eight standard Argo global attributes.

    ``institution`` is a DAC code and is mapped through reference
    table 4; the references carry the full name (``INCOIS``) while
    ``DATA_CENTRE`` carries the code (``IN``).
    """
    stamp = (created or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "title": title,
        "institution": institution_for_data_centre(institution),
        "source": "Argo float",
        "history": f"{stamp} creation",
        "references": "http://www.argodatamgt.org/Documentation",
        "user_manual_version": "3.1",
        "Conventions": "Argo-3.1 CF-1.6",
        "featureType": feature_type,
    }


def package_version() -> str:
    """Return this package's version shortened to fit ``STRING4``.

    ``HISTORY_SOFTWARE_RELEASE`` is four characters wide (the references
    carry ``V4.0``), so a PEP 440 version such as ``0.1.0a0`` becomes
    ``V0.1``.
    """
    from argo_decoder import __version__

    parts = str(__version__).split(".")
    major = parts[0] if parts else "0"
    minor = parts[1] if len(parts) > 1 else "0"
    return f"V{major}.{minor}"[:STRING4]


def utc_stamp(moment: datetime | None = None) -> str:
    """Return a ``YYYYMMDDHHMMSS`` stamp (UTC)."""
    return (moment or datetime.now(UTC)).strftime("%Y%m%d%H%M%S")


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def _nc_dtype(dtype: np.dtype[Any]) -> str | np.dtype[Any]:
    kind = dtype.kind
    if kind == "S":
        return "S1"
    if kind in ("i", "u"):
        return "i4" if dtype == np.int32 else dtype
    if kind == "f":
        return "f4" if dtype == np.float32 else "f8"
    return "f8"


def write_admt_dataset(
    ds: xr.Dataset,
    path: Path,
    *,
    fixed_dims: dict[str, int | None] | None = None,
    dim_order: tuple[str, ...] = (),
) -> None:
    """Write an ADMT dataset to ``path`` using ``netCDF4`` directly.

    Parameters
    ----------
    ds:
        Dataset to write. Variables are written in insertion order,
        which the ADMT reference files rely on.
    fixed_dims:
        Dimensions to create up front, in order. A value of ``None``
        creates an unlimited dimension. Dimensions carrying data that
        are not listed here are created afterwards from ``ds.sizes``.
    dim_order:
        Names from ``fixed_dims`` to create first, so the on-disk
        dimension order matches the references.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    declared = dict(fixed_dims or {})
    with netCDF4.Dataset(path, "w", format=ADMT_NC_FORMAT) as ncf:
        for name in dim_order:
            if name in declared:
                ncf.createDimension(name, declared.pop(name))
        for name, size in declared.items():
            ncf.createDimension(name, size)
        for dim, size in ds.sizes.items():
            if str(dim) not in ncf.dimensions:
                ncf.createDimension(str(dim), int(size))

        for key, value in ds.attrs.items():
            if value is None:
                continue
            setattr(ncf, key, value)

        for name, da in ds.data_vars.items():
            attrs = dict(da.attrs)
            fill = attrs.pop("_FillValue", None)
            var = ncf.createVariable(
                str(name),
                _nc_dtype(da.dtype),
                tuple(str(d) for d in da.dims),
                fill_value=fill,
                zlib=False,
            )
            for akey, avalue in attrs.items():
                if avalue is None:
                    continue
                if isinstance(avalue, np.generic):
                    # Keep the declared numpy width. ``.item()`` would
                    # return a Python float/int, which netCDF4 stores as
                    # float64/int64 -- the GDAC references write
                    # ``resolution``, ``valid_min`` and ``valid_max`` as
                    # float32, so upcasting them is a real header
                    # difference (0.1f becomes 0.10000000149011612).
                    var.setncattr(akey, avalue)
                    continue
                setattr(var, akey, avalue)
            values = da.values
            if da.dtype.kind == "S":
                values = np.asarray(values, dtype="S1")
            var[:] = values


__all__ = [
    "ADMT_NC_FORMAT",
    "CHAR_FILL",
    "DAC_INSTITUTION",
    "DATE_TIME_LEN",
    "DOUBLE_FILL",
    "FLOAT_FILL",
    "INTERNAL_ATTRS",
    "INT_FILL",
    "JULD_FILL",
    "JULD_RESOLUTION",
    "STRING2",
    "STRING4",
    "STRING8",
    "STRING16",
    "STRING32",
    "STRING64",
    "STRING128",
    "STRING256",
    "STRING1024",
    "char_array",
    "char_column",
    "date_char",
    "encode_padded",
    "flag_column",
    "institution_for_data_centre",
    "package_version",
    "scalar_char",
    "scalar_flag",
    "standard_globals",
    "utc_stamp",
    "write_admt_dataset",
]
