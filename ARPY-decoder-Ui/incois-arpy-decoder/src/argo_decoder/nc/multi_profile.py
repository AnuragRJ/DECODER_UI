"""Multi-profile (_prof.nc) builder.

Implements M6: stacks the per-cycle mono-profile ``xr.Dataset`` objects
produced by the decoders into a single ADMT-3.1 / CF-1.6 compliant
``<wmo>_prof.nc`` file with dimensions ``(N_PROF, N_LEVELS)``.

Two public entry points are provided:

* :func:`build_multi_profile_dataset` returns an in-memory ``xr.Dataset``
  suitable for inspection / unit testing.
* :func:`write_multi_profile` writes the stacked file directly via the
  ``netCDF4`` library (same mechanism MATLAB uses) so NC_CHAR arrays do
  **not** acquire the spurious trailing ``string1`` dimension that
  xarray's netcdf4 backend injects. This gives byte-layout parity with
  ``<wmo>_prof.nc`` produced by the MATLAB oracle.

Design notes
------------

* The Argo reference format for core Argo profilers (manual v3.1) stores
  every cycle of a mission in one file. ``N_PROF`` is the number of
  profiles (one per cycle per direction on this float, so typically
  == number of cycles for an ascending-only CTDO float like 6902892).
* ``N_LEVELS`` is the maximum number of vertical levels across all
  stacked profiles. Shorter profiles are padded to this length with
  their parameter-specific ``_FillValue`` and QC='9' (missing).
* Profile-level scalar variables (JULD, LATITUDE, LONGITUDE,
  CYCLE_NUMBER, DIRECTION, DATA_MODE, JULD_QC, POSITION_QC,
  PROFILE_<PARAM>_QC) become 1-D arrays indexed by ``N_PROF``.
* Per-level science arrays (PRES, TEMP, PSAL, CNDC, DOXY, and their
  QC companions) become 2-D arrays with shape ``(N_PROF, N_LEVELS)``.
* String-valued metadata (PLATFORM_NUMBER, DATA_TYPE, STATION_PARAMETERS,
  etc.) follow ADMT fixed-length CHAR convention with trailing-spaces
  written as true NC_CHAR arrays (no spurious trailing dimension).
* Per-mono ``ds.attrs`` debug counters are deliberately NOT copied to
  the multi file; the multi file only carries the standard Argo global
  attributes so it validates cleanly against the ADMT checker.

The builder is a **pure function** of the mono-profile datasets plus
``FloatMeta``; it does no IO.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import netCDF4
import numpy as np
import xarray as xr

from argo_decoder.metadata.models import FloatMeta
from argo_decoder.nc.admt import ADMT_NC_FORMAT, institution_for_data_centre

# ---------------------------------------------------------------------------
# ADMT fixed string dimensions (manual v3.1 table 4).
# The dimension *names* follow MATLAB / Argo NetCDF convention exactly --
# STRING2, STRING4, ..., STRING256 for fixed-length char strings and
# DATE_TIME for the 14-char YYYYMMDDHHMMSS timestamps. We expose the
# lengths as module constants for clarity.
# ---------------------------------------------------------------------------
STRING2 = 2
STRING4 = 4
STRING8 = 8
STRING16 = 16
STRING32 = 32
STRING64 = 64
STRING256 = 256
DATE_TIME_LEN = 14  # YYYYMMDDHHMMSS (dimension name is ``DATE_TIME``)

#: Descriptive attributes for the twelve ``HISTORY_*`` variables.
#:
#: Verified verbatim against the GDAC ``_prof.nc`` references for WMO
#: 2902222 and 2902223 -- 12/12 variables, with no attribute present in
#: the references that is absent here and none added that they do not
#: carry. ``conventions`` and ``units`` genuinely do not apply to every
#: variable, so they are omitted rather than blank-filled.
#:
#: These must be written at variable-creation time. The group is emitted
#: with ``N_HISTORY = 0`` (a structural invariant of ``_prof.nc``), so
#: any attribute assignment driven by a per-record loop would never run
#: and the ADMT format check would report them missing.
_HISTORY_ATTRS: dict[str, dict[str, str]] = {
    "HISTORY_INSTITUTION": {
        "long_name": "Institution which performed action",
        "conventions": "Argo reference table 4",
    },
    "HISTORY_STEP": {
        "long_name": "Step in data processing",
        "conventions": "Argo reference table 12",
    },
    "HISTORY_SOFTWARE": {
        "long_name": "Name of software which performed action",
        "conventions": "Institution dependent",
    },
    "HISTORY_SOFTWARE_RELEASE": {
        "long_name": "Version/release of software which performed action",
        "conventions": "Institution dependent",
    },
    "HISTORY_REFERENCE": {
        "long_name": "Reference of database",
        "conventions": "Institution dependent",
    },
    "HISTORY_DATE": {
        "long_name": "Date the history record was created",
        "conventions": "YYYYMMDDHHMISS",
    },
    "HISTORY_ACTION": {
        "long_name": "Action performed on data",
        "conventions": "Argo reference table 7",
    },
    "HISTORY_PARAMETER": {
        "long_name": "Station parameter action is performed on",
        "conventions": "Argo reference table 3",
    },
    "HISTORY_START_PRES": {
        "long_name": "Start pressure action applied on",
        "units": "decibar",
    },
    "HISTORY_STOP_PRES": {
        "long_name": "Stop pressure action applied on",
        "units": "decibar",
    },
    "HISTORY_PREVIOUS_VALUE": {
        "long_name": "Parameter/Flag previous value before action",
    },
    "HISTORY_QCTEST": {
        "long_name": "Documentation of tests performed, tests failed (in hex form)",
        "conventions": ("Write tests performed when ACTION=QCP$; tests failed when ACTION=QCF$"),
    },
}

# Argo fill values used in the multi-profile file.
_CHAR_FILL = " "
_DOUBLE_FILL = np.float64(99999.0)
_DOUBLE_FILL_JULD = np.float64(999999.0)
_FLOAT_FILL = np.float32(99999.0)
_INT_FILL = np.int32(99999)

# Science variables that live in the (N_PROF, N_LEVELS) plane and their
# dtype / fill / attributes.  The list is ordered per ADMT convention:
# PRES first, then TEMP, PSAL, CNDC, then BGC params (DOXY).
# Core-parameter specs follow the published ADMT conventions verified in
# Phase 5B against the GDAC references: NC_FLOAT storage with a 99999.0
# fill, and the reference spelling of long_name/units. DOXY keeps its
# own convention (no BGC reference file is available to verify it).
_SCIENCE_VARS: tuple[dict[str, Any], ...] = (
    {
        "name": "PRES",
        "dtype": np.float32,
        "fill": np.float32(99999.0),
        "attrs": {
            "long_name": "Sea water pressure, equals 0 at sea-level",
            "standard_name": "sea_water_pressure",
            "units": "decibar",
            "valid_min": np.float32(0.0),
            "valid_max": np.float32(12000.0),
            "C_format": "%7.1f",
            "FORTRAN_format": "F7.1",
            "resolution": np.float32(0.1),
            "axis": "Z",
        },
    },
    {
        "name": "TEMP",
        "dtype": np.float32,
        "fill": np.float32(99999.0),
        "attrs": {
            "long_name": "Sea temperature in-situ ITS-90 scale",
            "standard_name": "sea_water_temperature",
            "units": "degree_Celsius",
            "valid_min": np.float32(-2.5),
            "valid_max": np.float32(40.0),
            "C_format": "%9.3f",
            "FORTRAN_format": "F9.3",
            "resolution": np.float32(0.001),
        },
    },
    {
        "name": "PSAL",
        "dtype": np.float32,
        "fill": np.float32(99999.0),
        "attrs": {
            "long_name": "Practical salinity",
            "standard_name": "sea_water_salinity",
            "units": "psu",
            "valid_min": np.float32(2.0),
            "valid_max": np.float32(41.0),
            "C_format": "%9.3f",
            "FORTRAN_format": "F9.3",
            "resolution": np.float32(0.001),
        },
    },
    {
        "name": "CNDC",
        "dtype": np.float32,
        "fill": np.float32(99999.0),
        "attrs": {
            "long_name": "Electrical conductivity",
            "standard_name": "sea_water_electrical_conductivity",
            "units": "mhos/m",
            "valid_min": np.float32(0.0),
            "valid_max": np.float32(8.5),
            "C_format": "%10.4f",
            "FORTRAN_format": "F10.4",
            "resolution": np.float32(0.0001),
        },
    },
    {
        "name": "DOXY",
        "dtype": np.float64,
        "fill": np.float64(9999.999),
        "attrs": {
            "long_name": "Dissolved oxygen",
            "standard_name": "moles_of_oxygen_per_unit_mass_in_sea_water",
            "units": "micromole/kg",
            "valid_min": np.float64(-5.0),
            "valid_max": np.float64(600.0),
            "C_format": "%9.3f",
            "FORTRAN_format": "F9.3",
            "resolution": np.float64(0.001),
        },
    },
)


# QC flags for each science variable: char '0'..'9', shape (N_PROF, N_LEVELS).
def _qc_attrs() -> dict[str, str]:
    return {
        "long_name": "quality flag",
        "conventions": "Argo reference table 2",
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _zpad(s: str, n: int) -> str:
    """Right-pad a string to exactly ``n`` characters with spaces."""
    b = s[:n]
    return b + " " * (n - len(b))


def _encode_padded(s: str, n: int) -> bytes:
    """Encode a string to utf-8 bytes and right-pad to ``n`` bytes with spaces."""
    enc = str(s)[:n].encode("utf-8")
    return enc + b" " * (n - len(enc))


def _scalar_char(s: str, n: int) -> xr.DataArray:
    """Build a 1-D char DataArray ``(STRINGn,)`` for a single fixed-length string
    (used for file-level scalars like DATA_TYPE, FORMAT_VERSION)."""
    buf = _encode_padded(s, n)
    arr = np.frombuffer(buf, dtype="S1").copy()
    return xr.DataArray(arr, dims=(f"STRING{n}",))


def _to_chararr(values: list[str], n: int) -> xr.DataArray:
    """Build a 2-D char DataArray ``(N_PROF, STRINGn)`` from a list of strings.

    xarray writes this as an ``NC_CHAR`` variable with a trailing
    string-length dimension, which is what the ADMT checker expects.
    """
    n_prof = len(values)
    # Pre-allocate as a contiguous bytes buffer then view as S1.
    buf = bytearray(n_prof * n)
    for i, v in enumerate(values):
        buf[i * n : (i + 1) * n] = _encode_padded(str(v), n)
    arr = np.frombuffer(buf, dtype="S1").reshape(n_prof, n)
    return xr.DataArray(arr.copy(), dims=("N_PROF", f"STRING{n}"))


def _to_chararr_3d(values: list[list[str]], n: int, str_len: int) -> xr.DataArray:
    """Build a 3-D char DataArray ``(N_PROF, N_PARAM, STRINGn)``.

    Used for STATION_PARAMETERS, where each profile carries up to N_PARAM
    parameter names padded to ``str_len`` characters.
    """
    n_prof = len(values)
    buf = bytearray(n_prof * n * str_len)
    for i, row in enumerate(values):
        for j in range(n):
            payload = str(row[j]) if j < len(row) else ""
            chunk = _encode_padded(payload, str_len)
            off = (i * n + j) * str_len
            buf[off : off + str_len] = chunk
    arr = np.frombuffer(buf, dtype="S1").reshape(n_prof, n, str_len)
    return xr.DataArray(arr.copy(), dims=("N_PROF", "N_PARAM", f"STRING{str_len}"))


def _scalar_from_ds(ds: xr.Dataset, name: str, fill: Any) -> Any:
    """Extract a scalar value from a mono-profile dataset.

    Handles three representations used across the decoders:

    * 0-d numpy scalar (numeric variables such as JULD/LATITUDE).
    * 1-element char arrays with dim ``string1`` (e.g. JULD_QC).
    * Missing variables return ``fill``.
    """
    if name not in ds.data_vars:
        return fill
    v = ds[name].values
    if isinstance(v, np.ndarray):
        if v.ndim == 0:
            return v.item()
        if v.size >= 1:
            return v.flat[0]
        return fill
    return v


def _worst_qc(qc_bytes: np.ndarray) -> str:
    """Return the worst (highest-numeric) QC flag in a byte array of QC values.

    Skips fill values (b' ' / b'\\x00' / b'9' only if missing). Mirrors
    MATLAB's "worst flag wins" behaviour used for PROFILE_<PARAM>_QC.
    """
    # Iterating a np.ndarray with dtype ``S1`` yields ``numpy.bytes_``
    # scalars, which aren't accepted by ``bytes([...])``; decode them to
    # Python bytes via .item() first.
    worst: int | None = None
    for b in qc_bytes.ravel():
        ch = b.item() if hasattr(b, "item") else bytes(b)
        if not isinstance(ch, (bytes, bytearray)):
            continue
        if len(ch) != 1:
            continue
        c = ch[0]
        if 48 <= c <= 57 and c != 48:  # digits '1'..'9'
            v = c - 48
            if worst is None or v > worst:
                worst = v
    if worst is None:
        return "9"
    return str(worst)


def _pad_col(data: np.ndarray, fill: Any, n_levels: int) -> np.ndarray:
    """Pad/truncate a 1-D science column to ``n_levels`` with ``fill``."""
    col = np.asarray(data)
    out = np.full(n_levels, fill, dtype=col.dtype)
    n = min(len(col), n_levels)
    out[:n] = col[:n]
    return out


def _pad_qc_col(qc: np.ndarray, n_levels: int) -> np.ndarray:
    """Pad a QC byte/char column to ``n_levels`` with b'9' (missing)."""
    col = np.asarray(qc, dtype="S1")
    out = np.full(n_levels, b"9", dtype="S1")
    n = min(len(col), n_levels)
    out[:n] = col[:n]
    return out


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------


def _pad_to_levels(values: np.ndarray, n_levels: int, fill: Any) -> np.ndarray:
    """Right-pad a ``(1, k)`` row out to ``(1, n_levels)`` with ``fill``."""
    row = np.asarray(values)
    if row.ndim == 1:
        row = row.reshape(1, -1)
    if row.shape[1] >= n_levels:
        return row[:, :n_levels]
    pad = np.full((row.shape[0], n_levels - row.shape[1]), fill, dtype=row.dtype)
    return np.concatenate([row, pad], axis=1)


def build_multi_profile_dataset(
    mono_datasets: dict[int, xr.Dataset],
    meta: FloatMeta | None,
    *,
    wmo: int,
    decoder_version: str = "",
    institution: str = "CORIOLIS",
    data_centre: str | None = None,
) -> xr.Dataset:
    """Stack per-cycle ADMT mono profiles into one ``<wmo>_prof.nc``.

    This is deliberately a **stacker over**
    :func:`~argo_decoder.nc.mono_profile.build_mono_profile_dataset`
    rather than a second ADMT implementation. The multi-profile writer
    previously duplicated an older Phase 3 layout and so never received
    the Phase 5A.1-5A.4 upgrades (fixed dimensions, ``PARAMETER``,
    ``SCIENTIFIC_CALIB_*``, ``HISTORY_*``, the adjusted trios, the
    reference-table-2a ``PROFILE_<PARAM>_QC``) nor the later CNDC-export
    and float32-attribute corrections. Building each profile with the
    mono builder and concatenating along ``N_PROF`` keeps the two
    products structurally identical by construction.

    Three things genuinely differ from the mono case and are handled
    here rather than in the mono builder:

    * ``N_LEVELS`` is the maximum across the stacked cycles; shorter
      profiles are padded with each parameter's ``_FillValue`` and
      ``QC='9'``.
    * ``DC_REFERENCE`` is ``"<wmo>/<cycle>"`` per profile.
    * ``HISTORY_*`` is **not** stacked. Every GDAC ``_prof.nc`` inspected
      (six INCOIS floats, mixed real-time and delayed-mode) carries
      ``N_HISTORY = 0``, so the dimension and variables are emitted
      empty. Per-cycle history stays in the mono files.
    """
    from argo_decoder.nc.mono_profile import build_mono_profile_dataset

    ordered_cycles = sorted(mono_datasets)
    if not ordered_cycles:
        raise ValueError("build_multi_profile_dataset requires at least one profile")

    resolved_centre = data_centre or (getattr(meta, "data_centre", None) or "")
    resolved_institution = (
        institution_for_data_centre(resolved_centre) if resolved_centre else institution
    )

    # Build every cycle through the mono ADMT builder, so each profile is
    # already correct before it is stacked.
    built = {
        cycle: build_mono_profile_dataset(
            mono_datasets[cycle],
            wmo=wmo,
            cycle=cycle,
            meta=meta,
            institution=resolved_institution,
            software_release=decoder_version or None,
        )
        for cycle in ordered_cycles
    }

    n_prof = len(ordered_cycles)
    n_levels = max(int(ds.sizes.get("N_LEVELS", 0)) for ds in built.values())
    template = built[ordered_cycles[0]]

    data_vars: dict[str, xr.DataArray] = {}
    for name, first in template.data_vars.items():
        dims = tuple(str(d) for d in first.dims)

        # HISTORY_* is not stacked; see the docstring.
        if name.startswith("HISTORY_"):
            continue

        # File-level scalars (no N_PROF axis) are copied verbatim.
        if "N_PROF" not in dims:
            data_vars[name] = first
            continue

        rows = []
        for cycle in ordered_cycles:
            source = built[cycle]
            if name not in source.data_vars:
                continue
            values = np.asarray(source[name].values)
            if "N_LEVELS" in dims:
                fill = first.attrs.get("_FillValue")
                if fill is None:
                    fill = b"9" if values.dtype.kind == "S" else np.float32(99999.0)
                values = _pad_to_levels(values, n_levels, fill)
            rows.append(values)
        stacked = np.concatenate(rows, axis=0)
        data_vars[name] = xr.DataArray(stacked, dims=dims, attrs=dict(first.attrs))

    # DC_REFERENCE: "<wmo>/<cycle>" per profile. The mono builder leaves
    # it blank because a mono file has no station list to disambiguate.
    references = [f"{wmo}/{cycle}" for cycle in ordered_cycles]
    data_vars["DC_REFERENCE"] = _to_chararr(references, STRING32).assign_attrs(
        long_name="Station unique identifier in data centre",
        conventions="Data centre convention",
        _FillValue=b" ",
    )

    # Empty HISTORY group. The dimension and all twelve variables must
    # exist for the ADMT format check, but carry no records: every GDAC
    # ``_prof.nc`` inspected reports ``N_HISTORY = 0``. Shapes and dtypes
    # follow the references exactly.
    for name, width in (
        ("HISTORY_INSTITUTION", STRING4),
        ("HISTORY_STEP", STRING4),
        ("HISTORY_SOFTWARE", STRING4),
        ("HISTORY_SOFTWARE_RELEASE", STRING4),
        ("HISTORY_REFERENCE", STRING64),
        ("HISTORY_DATE", DATE_TIME_LEN),
        ("HISTORY_ACTION", STRING4),
        ("HISTORY_PARAMETER", STRING16),
        ("HISTORY_QCTEST", STRING16),
    ):
        dim = "DATE_TIME" if width == DATE_TIME_LEN else f"STRING{width}"
        data_vars[name] = xr.DataArray(
            np.empty((0, n_prof, width), dtype="S1"),
            dims=("N_HISTORY", "N_PROF", dim),
            attrs={**_HISTORY_ATTRS[name], "_FillValue": b" "},
        )
    for name in ("HISTORY_START_PRES", "HISTORY_STOP_PRES", "HISTORY_PREVIOUS_VALUE"):
        data_vars[name] = xr.DataArray(
            np.empty((0, n_prof), dtype=np.float32),
            dims=("N_HISTORY", "N_PROF"),
            attrs={**_HISTORY_ATTRS[name], "_FillValue": np.float32(99999.0)},
        )

    dataset = xr.Dataset(data_vars, attrs=dict(template.attrs))
    dataset.attrs["title"] = "Argo float vertical profile"
    return dataset


def write_multi_profile(ds: xr.Dataset, path: Path) -> None:
    """Write a multi-profile xr.Dataset to ``path`` using ``netCDF4`` directly.

    We bypass xarray's ``to_netcdf`` for the multi file because xarray's
    netcdf4 backend appends a trailing ``string1`` dimension to every
    ``dtype='S1'`` array, which breaks ADMT compliance and prevents
    parity with MATLAB's ``<wmo>_prof.nc``. Writing with netCDF4 directly
    (as MATLAB does via the matlab netcdf API) produces the exact NC_CHAR
    shape expected by the Argo reference manual.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with netCDF4.Dataset(path, "w", format=ADMT_NC_FORMAT) as ncf:
        # ---- dimensions ----
        dim_sizes: dict[str, int] = {}
        for d, sz in ds.sizes.items():
            dim_name = str(d)
            ncf.createDimension(dim_name, int(sz))
            dim_sizes[dim_name] = int(sz)

        # ---- global attributes ----
        for k, v in ds.attrs.items():
            if v is None:
                continue
            setattr(ncf, k, v)

        # ---- variables ----
        for name, da in ds.data_vars.items():
            var_name = str(name)
            attrs = dict(da.attrs)
            fill = attrs.pop("_FillValue", None)
            dtype_kind = da.dtype.kind
            nc_dtype: str | np.dtype[Any]
            if dtype_kind == "S":
                nc_dtype = "S1"
            elif dtype_kind in ("u", "i"):
                if da.dtype == np.int8:
                    nc_dtype = "i1"
                elif da.dtype == np.int32:
                    nc_dtype = "i4"
                elif da.dtype == np.int64:
                    nc_dtype = "i8"
                else:
                    nc_dtype = da.dtype
            elif dtype_kind == "f":
                nc_dtype = "f4" if da.dtype == np.float32 else "f8"
            else:
                nc_dtype = "f8"
            var_dims = tuple(str(d) for d in da.dims)
            var = ncf.createVariable(
                var_name,
                nc_dtype,
                var_dims,
                fill_value=fill,
                zlib=False,
            )
            for ak, av in attrs.items():
                if av is None:
                    continue
                # netCDF4 rejects np.generic attrs
                if isinstance(av, (np.generic,)):
                    av = av.item()
                setattr(var, ak, av)
            # Assign data. For S1 arrays we flatten/encode as needed.
            vals = da.values
            if dtype_kind == "S":
                # Ensure S1 dtype and write raw bytes.
                vals = np.asarray(vals, dtype="S1")
            var[:] = vals
