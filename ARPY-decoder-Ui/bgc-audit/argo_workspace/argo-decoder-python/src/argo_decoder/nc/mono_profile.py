"""Mono-profile (R<wmo>_<CCC>.nc) ADMT builder.

Implements Phase 5A.1: promotes the decoder's in-memory mono-profile
``xr.Dataset`` (a flat ``(N_LEVELS,)`` science block plus 0-d scalars)
into an ADMT-3.1 / CF-1.6 shaped single-profile dataset with the fixed
Argo dimensions and the file-level / profile-level metadata variables.

Scope of this slice
-------------------

Added here:

* fixed ADMT dimensions ``N_PROF=1``, ``N_PARAM``, ``N_CALIB=1``,
  ``N_HISTORY`` (unlimited, initially empty), ``DATE_TIME=14`` and
  ``STRING2/4/8/16/32/64/256``;
* file-level scalars ``DATA_TYPE``, ``FORMAT_VERSION``,
  ``HANDBOOK_VERSION``, ``REFERENCE_DATE_TIME``, ``DATE_CREATION``,
  ``DATE_UPDATE``;
* profile metadata ``PLATFORM_NUMBER``, ``PROJECT_NAME``, ``PI_NAME``,
  ``STATION_PARAMETERS``, ``CYCLE_NUMBER``, ``DIRECTION``,
  ``DATA_CENTRE``, ``DC_REFERENCE``, ``DATA_STATE_INDICATOR``,
  ``DATA_MODE``, ``PLATFORM_TYPE``, ``FLOAT_SERIAL_NO``,
  ``FIRMWARE_VERSION``, ``WMO_INST_TYPE``, ``POSITIONING_SYSTEM``,
  ``VERTICAL_SAMPLING_SCHEME``, ``CONFIG_MISSION_NUMBER``,
  ``JULD_LOCATION`` and ``PROFILE_<PARAM>_QC``;
* re-shaping of the existing science block to ``(N_PROF, N_LEVELS)`` and
  of the per-level QC to ADMT ``NC_CHAR``.

Added in Phase 5A.2:

* ``PARAMETER`` on the ``N_CALIB`` calibration slot;
* the ``<PARAM>_ADJUSTED``, ``<PARAM>_ADJUSTED_QC`` and
  ``<PARAM>_ADJUSTED_ERROR`` families for the ADMT core parameters.

Added in Phase 5A.3:

* ``SCIENTIFIC_CALIB_EQUATION``, ``SCIENTIFIC_CALIB_COEFFICIENT``,
  ``SCIENTIFIC_CALIB_COMMENT`` and ``SCIENTIFIC_CALIB_DATE``, completing
  the ``N_CALIB`` group.

Deliberately **not** implemented yet: the ``HISTORY_*`` group. The
``N_HISTORY`` dimension is already created so those variables can be
appended without a further dimension change.

Science values are carried through **bit-for-bit**: the builder only
reshapes ``(N_LEVELS,)`` to ``(1, N_LEVELS)`` and never casts the
floating-point dtype, so PRES/TEMP/PSAL/CNDC are unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from argo_decoder.metadata.models import FloatMeta
from argo_decoder.nc.admt import (
    INTERNAL_ATTRS,
    institution_for_data_centre,
    package_version,
    write_admt_dataset,
)
from argo_decoder.nc.multi_profile import (
    DATE_TIME_LEN,
    STRING2,
    STRING4,
    STRING8,
    STRING16,
    STRING32,
    STRING64,
    STRING256,
    _encode_padded,
    _scalar_char,
    _scalar_from_ds,
)

# ADMT core-Argo profile parameters, in reference-file order.
_CORE_PARAMS: tuple[str, ...] = ("PRES", "TEMP", "PSAL")

#: Parameters this writer publishes to the mono-profile file.
#:
#: The GDAC core profiles for these floats carry exactly the three core
#: parameters -- verified against ``R2902224_345.nc``, which declares
#: ``N_PARAM = 3`` and contains no ``CNDC``, ``CNDC_QC`` or
#: ``PROFILE_CNDC_QC``. Decoder-derived conductivity is therefore
#: computed and retained in memory but not exported.
#:
#: Widening this set is the single supported way to publish another
#: parameter: every dependent structure is built from it, so they cannot
#: drift out of step.
_EXPORTED_PARAMS: frozenset[str] = frozenset(_CORE_PARAMS)

_DOUBLE_FILL = np.float64(99999.0)
_DOUBLE_FILL_JULD = np.float64(999999.0)
# JULD storage resolution advertised by the GDAC references (~0.86 s).
_JULD_RESOLUTION = np.float64(1e-5)
_INT_FILL = np.int32(99999)

# Fixed ADMT dimensions that must exist in every mono-profile file, even
# when no variable in this slice references them yet (N_CALIB/N_HISTORY).
_FIXED_STRING_DIMS: tuple[tuple[str, int], ...] = (
    ("STRING2", STRING2),
    ("STRING4", STRING4),
    ("STRING8", STRING8),
    ("STRING16", STRING16),
    ("STRING32", STRING32),
    ("STRING64", STRING64),
    ("STRING256", STRING256),
    ("DATE_TIME", DATE_TIME_LEN),
)


def _date_char(value: str) -> xr.DataArray:
    """Build a ``(DATE_TIME,)`` char array for a YYYYMMDDHHMISS stamp.

    ``_scalar_char`` would name the dimension ``STRING14``; ADMT requires
    the distinct ``DATE_TIME`` dimension for date-valued scalars.
    """
    buf = _encode_padded(value, DATE_TIME_LEN)
    arr = np.frombuffer(buf, dtype="S1").copy()
    return xr.DataArray(arr, dims=("DATE_TIME",))


def _prof_char(value: str, width: int) -> xr.DataArray:
    """Build an ``(N_PROF, STRING<width>)`` char array for one profile."""
    buf = _encode_padded(value, width)
    arr = np.frombuffer(buf, dtype="S1").copy().reshape(1, width)
    return xr.DataArray(arr, dims=("N_PROF", f"STRING{width}"))


def _prof_flag(value: bytes | str) -> xr.DataArray:
    """Build an ``(N_PROF,)`` single-character flag array."""
    raw = value.encode("ascii") if isinstance(value, str) else bytes(value)
    ch = raw[:1] or b" "
    return xr.DataArray(np.array([ch], dtype="S1"), dims=("N_PROF",))


def _station_parameters(params: list[str]) -> xr.DataArray:
    """Build ``(N_PROF, N_PARAM, STRING16)`` for the single profile."""
    n_param = len(params)
    buf = bytearray(n_param * STRING16)
    for j, name in enumerate(params):
        buf[j * STRING16 : (j + 1) * STRING16] = _encode_padded(name, STRING16)
    arr = np.frombuffer(bytes(buf), dtype="S1").reshape(1, n_param, STRING16)
    return xr.DataArray(arr.copy(), dims=("N_PROF", "N_PARAM", "STRING16"))


def _qc_to_char(values: Any, n_levels: int) -> np.ndarray:
    """Convert a per-level QC column to ADMT ``NC_CHAR`` ``(1, N_LEVELS)``.

    The decoders keep QC as small integers (``int8``) in memory; the Argo
    format requires the ASCII digit. Byte/char columns are passed
    through unchanged so both in-memory representations are accepted.
    """
    out = np.full((1, n_levels), b"9", dtype="S1")
    col = np.asarray(values).reshape(-1)
    n = min(col.size, n_levels)
    for i in range(n):
        item = col[i]
        if isinstance(item, (bytes, np.bytes_)):
            ch = bytes(item)[:1] or b"9"
        else:
            ch = str(int(item)).encode("ascii")[:1]
        out[0, i] = ch
    return out


def _profile_qc_flag(qc_chars: np.ndarray) -> str:
    """Return the Argo reference table 2a flag for a per-level QC row.

    Table 2a encodes the *percentage* of levels holding a good flag
    (QC 1, 2, 5 or 8) -- it is not the worst-flag digit used by
    ``<PARAM>_QC``::

        A = 100%      B = 75-100%   C = 50-75%
        D = 25-50%    E = 0-25%     F = 0%
        ' ' = no QC performed (no non-fill levels)
    """
    flags = [
        bytes(ch)[:1]
        for ch in np.asarray(qc_chars, dtype="S1").reshape(-1)
        if bytes(ch)[:1] not in (b" ", b"", b"\x00")
    ]
    if not flags:
        return " "
    good = sum(1 for ch in flags if ch in (b"1", b"2", b"5", b"8"))
    pct = 100.0 * good / len(flags)
    if pct == 100.0:
        return "A"
    if pct >= 75.0:
        return "B"
    if pct >= 50.0:
        return "C"
    if pct >= 25.0:
        return "D"
    if pct > 0.0:
        return "E"
    return "F"


def _adjusted_vars(
    name: str,
    source: xr.DataArray,
    ds: xr.Dataset,
    n_levels: int,
) -> dict[str, xr.DataArray]:
    """Build the ``<PARAM>_ADJUSTED{,_QC,_ERROR}`` trio for one parameter.

    Real-time (``R*.nc``) output carries the adjusted family as declared
    but unset: the GDAC R-file references have every ``_ADJUSTED`` and
    ``_ADJUSTED_ERROR`` level at ``_FillValue`` and every
    ``_ADJUSTED_QC`` level blank, because the adjustment is a
    delayed-mode product. Values are only emitted when the decoder has
    actually produced them, which no current platform does.

    The adjusted variable inherits the unadjusted variable's attributes
    (per MATLAB ``nc_create_multi_prof_file.m``, which copies
    long_name/standard_name/units/valid_min/valid_max/C_format/
    FORTRAN_format/resolution) minus ``axis``, which the references drop
    on the adjusted form.
    """
    fill = _PARAM_FILL
    dims = ("N_PROF", "N_LEVELS")
    out: dict[str, xr.DataArray] = {}

    canonical = _admt_param_attrs(name, source.attrs)
    adj_name = f"{name}_ADJUSTED"
    adj_attrs = {k: v for k, v in canonical.items() if k != "axis"}
    adj_attrs["_FillValue"] = fill
    if adj_name in ds.data_vars:
        adj_values = _to_param_array(
            ds[adj_name].values, n_levels, ds[adj_name].attrs.get("_FillValue")
        )
    else:
        adj_values = np.full((1, n_levels), fill, dtype=np.float32)
    out[adj_name] = xr.DataArray(adj_values, dims=dims, attrs=adj_attrs)

    adj_qc_name = f"{adj_name}_QC"
    if adj_qc_name in ds.data_vars:
        qc_values = _qc_to_char(ds[adj_qc_name].values, n_levels)
    else:
        # Blank (not '9'): no adjustment has been attempted.
        qc_values = np.full((1, n_levels), b" ", dtype="S1")
    out[adj_qc_name] = xr.DataArray(
        qc_values,
        dims=dims,
        attrs={
            "long_name": "quality flag",
            "conventions": "Argo reference table 2",
            "_FillValue": b" ",
        },
    )

    err_name = f"{adj_name}_ERROR"
    err_attrs: dict[str, Any] = {
        "long_name": (
            "Contains the error on the adjusted values as determined by the delayed mode QC process"
        )
    }
    for key in ("units", "C_format", "FORTRAN_format", "resolution"):
        if key in canonical:
            err_attrs[key] = canonical[key]
    err_attrs["_FillValue"] = fill
    if err_name in ds.data_vars:
        err_values = _to_param_array(
            ds[err_name].values, n_levels, ds[err_name].attrs.get("_FillValue")
        )
    else:
        err_values = np.full((1, n_levels), fill, dtype=np.float32)
    out[err_name] = xr.DataArray(err_values, dims=dims, attrs=err_attrs)

    return out


def _parameter_var(params: list[str]) -> xr.DataArray:
    """Build ``PARAMETER`` ``(N_PROF, N_CALIB, N_PARAM, STRING16)``.

    Same parameter list as ``STATION_PARAMETERS``, carried across the
    single calibration slot.
    """
    n_param = len(params)
    buf = bytearray(n_param * STRING16)
    for j, name in enumerate(params):
        buf[j * STRING16 : (j + 1) * STRING16] = _encode_padded(name, STRING16)
    arr = np.frombuffer(bytes(buf), dtype="S1").reshape(1, 1, n_param, STRING16)
    return xr.DataArray(arr.copy(), dims=("N_PROF", "N_CALIB", "N_PARAM", "STRING16"))


def _numbered_meta_values(meta: FloatMeta | None, key: str) -> list[str]:
    """Read a MATLAB-style numbered metadata block into an ordered list.

    The ``*_meta.json`` layout stores these as a single-element list of
    dicts keyed by ``<KEY>_1``, ``<KEY>_2``, ... for example::

        "CALIB_RT_EQUATION": [{"CALIB_RT_EQUATION_1": "PSAL_ADJUSTED = ..."}]

    Returns ``[]`` when the block is absent or empty, which is the case
    for every float currently in scope.
    """
    if meta is None:
        return []
    raw = getattr(meta, key.lower(), None)
    if raw is None:
        raw = (meta.model_extra or {}).get(key)
    if not raw:
        return []
    values: list[str] = []
    for row in raw:
        if not isinstance(row, dict):
            continue

        def _index(item: tuple[str, Any]) -> int:
            suffix = item[0].rsplit("_", 1)[-1]
            return int(suffix) if suffix.isdigit() else 0

        for _, value in sorted(row.items(), key=_index):
            values.append("" if value is None else str(value))
    return values


def _rt_calibration(meta: FloatMeta | None, params: list[str]) -> dict[str, dict[str, str]]:
    """Map ``{param: {equation, coefficient, comment, date}}`` from metadata.

    Mirrors the MATLAB ``CALIB_RT_*`` real-time calibration block, which
    is keyed by ``CALIB_RT_PARAMETER``. Entries for parameters that are
    not in this profile are ignored.
    """
    names = _numbered_meta_values(meta, "CALIB_RT_PARAMETER")
    if not names:
        return {}
    equations = _numbered_meta_values(meta, "CALIB_RT_EQUATION")
    coefficients = _numbered_meta_values(meta, "CALIB_RT_COEFFICIENT")
    comments = _numbered_meta_values(meta, "CALIB_RT_COMMENT")
    dates = _numbered_meta_values(meta, "CALIB_RT_DATE")

    def _at(values: list[str], index: int) -> str:
        return values[index] if index < len(values) else ""

    out: dict[str, dict[str, str]] = {}
    for i, name in enumerate(names):
        if name not in params:
            continue
        out[name] = {
            "equation": _at(equations, i),
            "coefficient": _at(coefficients, i),
            "comment": _at(comments, i),
            "date": _at(dates, i),
        }
    return out


#: Real-time ``SCIENTIFIC_CALIB_*`` defaults, per parameter.
#:
#: A real-time profile has had no delayed-mode calibration, but the DAC
#: still records *which* correction the processing chain applies. These
#: strings are that record.
#:
#: Evidence: they are invariant across every real-time reference
#: available. 58 independently sampled GDAC ``R*.nc`` files spanning
#: seven INCOIS floats yield exactly **one** distinct equation triplet,
#: one comment triplet and one coefficient triplet, and the populated
#: ``SCIENTIFIC_CALIB_DATE`` slots always equal ``DATE_UPDATE``. The same
#: text also appears on non-APEX INCOIS floats (checked on three ARVOR
#: platforms), so it is a DAC real-time convention rather than an APEX
#: or firmware-specific value.
#:
#: TEMP is deliberately absent: the references leave its slot blank
#: because no correction is applied to temperature in real time.
#:
#: This is the lowest-precedence source. Decoder-supplied values and a
#: float's ``CALIB_RT_*`` metadata block both override it, so a float
#: that genuinely carries its own calibration is unaffected.
_RT_CALIB_DEFAULTS: Mapping[str, Mapping[str, str]] = {
    "PRES": {
        "equation": "Pcorrected = Praw - surface offset",
        "coefficient": "",
        "comment": "This sensor is subject to hysteresis",
    },
    "PSAL": {
        "equation": "Scorrected = S(Ccorrected,Traw,Pcorrected)",
        "coefficient": "",
        "comment": "",
    },
}


def _calib_char(values: list[str], width: int) -> xr.DataArray:
    """Build ``(N_PROF, N_CALIB, N_PARAM, <width>)`` calibration text.

    ``width`` is ``STRING256`` for the text fields and ``DATE_TIME`` for
    ``SCIENTIFIC_CALIB_DATE``; the dimension name follows from it.
    """
    n_param = len(values)
    buf = bytearray(n_param * width)
    for j, value in enumerate(values):
        buf[j * width : (j + 1) * width] = _encode_padded(value, width)
    arr = np.frombuffer(bytes(buf), dtype="S1").reshape(1, 1, n_param, width)
    dim = "DATE_TIME" if width == DATE_TIME_LEN else f"STRING{width}"
    return xr.DataArray(arr.copy(), dims=("N_PROF", "N_CALIB", "N_PARAM", dim))


def _scientific_calib_vars(
    params: list[str],
    ds: xr.Dataset,
    meta: FloatMeta | None,
    date_update: str,
) -> dict[str, xr.DataArray]:
    """Build the four ``SCIENTIFIC_CALIB_*`` variables for one profile.

    Precedence per parameter:

    1. decoder-supplied values on ``ds.attrs['scientific_calib']``
       (``{param: {equation, coefficient, comment, date}}``), which is
       how a future delayed-mode or RT-adjustment path supplies them;
    2. the float's ``CALIB_RT_*`` metadata block;
    3. :data:`_RT_CALIB_DEFAULTS`, the DAC's standing real-time record of
       which correction the processing chain applies;
    4. blank, for a parameter with no entry in any of the above.

    A parameter with an equation but no explicit date takes
    ``DATE_UPDATE``, matching the supplied GDAC ``R*.nc`` references
    where the populated PRES/PSAL slots carry exactly ``DATE_UPDATE``
    and the untouched TEMP slot is blank.
    """
    from_decoder = ds.attrs.get("scientific_calib")
    decoder_calib: dict[str, Any] = from_decoder if isinstance(from_decoder, dict) else {}
    meta_calib = _rt_calibration(meta, params)

    equations: list[str] = []
    coefficients: list[str] = []
    comments: list[str] = []
    dates: list[str] = []
    for name in params:
        entry: dict[str, Any] = {}
        if isinstance(decoder_calib.get(name), dict):
            entry = dict(decoder_calib[name])
        elif name in meta_calib:
            entry = dict(meta_calib[name])
        elif name in _RT_CALIB_DEFAULTS:
            entry = dict(_RT_CALIB_DEFAULTS[name])
        equation = str(entry.get("equation", "") or "")
        coefficient = str(entry.get("coefficient", "") or "")
        comment = str(entry.get("comment", "") or "")
        date = str(entry.get("date", "") or "")
        if not date and (equation or coefficient or comment):
            date = date_update
        equations.append(equation)
        coefficients.append(coefficient)
        comments.append(comment)
        dates.append(date)

    out: dict[str, xr.DataArray] = {}
    out["SCIENTIFIC_CALIB_EQUATION"] = _calib_char(equations, STRING256)
    out["SCIENTIFIC_CALIB_EQUATION"].attrs = {
        "long_name": "Calibration equation for this parameter",
        "_FillValue": b" ",
    }
    out["SCIENTIFIC_CALIB_COEFFICIENT"] = _calib_char(coefficients, STRING256)
    out["SCIENTIFIC_CALIB_COEFFICIENT"].attrs = {
        "long_name": "Calibration coefficients for this equation",
        "_FillValue": b" ",
    }
    out["SCIENTIFIC_CALIB_COMMENT"] = _calib_char(comments, STRING256)
    out["SCIENTIFIC_CALIB_COMMENT"].attrs = {
        "long_name": "Comment applying to this parameter calibration",
        "_FillValue": b" ",
    }
    out["SCIENTIFIC_CALIB_DATE"] = _calib_char(dates, DATE_TIME_LEN)
    out["SCIENTIFIC_CALIB_DATE"].attrs = {
        "long_name": "Date of calibration",
        "conventions": "YYYYMMDDHHMISS",
        "_FillValue": b" ",
    }
    return out


# Canonical ADMT parameter attributes, transcribed from the supplied GDAC
# R*.nc references (Argo user manual 3.1, reference table 3). The decoder
# carries its own working attributes on the in-memory dataset; the ADMT
# file is the published product, so the published spelling wins here --
# 'decibar' not 'dbar', 'Sea water pressure, equals 0 at sea-level' not
# 'Sea pressure', and the C_format/FORTRAN_format/resolution triplet the
# references always include.
_PARAM_ATTRS: dict[str, dict[str, Any]] = {
    "PRES": {
        "long_name": "Sea water pressure, equals 0 at sea-level",
        "standard_name": "sea_water_pressure",
        "units": "decibar",
        "axis": "Z",
        "valid_min": np.float32(0.0),
        "valid_max": np.float32(12000.0),
        "C_format": "%7.1f",
        "FORTRAN_format": "F7.1",
        "resolution": np.float32(0.1),
    },
    "TEMP": {
        "long_name": "Sea temperature in-situ ITS-90 scale",
        "standard_name": "sea_water_temperature",
        "units": "degree_Celsius",
        "valid_min": np.float32(-2.5),
        "valid_max": np.float32(40.0),
        "C_format": "%9.3f",
        "FORTRAN_format": "F9.3",
        "resolution": np.float32(0.001),
    },
    "PSAL": {
        "long_name": "Practical salinity",
        "standard_name": "sea_water_salinity",
        "units": "psu",
        "valid_min": np.float32(2.0),
        "valid_max": np.float32(41.0),
        "C_format": "%9.3f",
        "FORTRAN_format": "F9.3",
        "resolution": np.float32(0.001),
    },
    "CNDC": {
        "long_name": "Electrical conductivity",
        "standard_name": "sea_water_electrical_conductivity",
        "units": "mhos/m",
        "valid_min": np.float32(0.0),
        "valid_max": np.float32(8.5),
        "C_format": "%10.4f",
        "FORTRAN_format": "F10.4",
        "resolution": np.float32(0.0001),
    },
}

# ADMT stores core profile parameters as NC_FLOAT with a 99999.0 fill.
_PARAM_FILL = np.float32(99999.0)

# Decoder working/provenance attributes. These are genuinely useful on
# the in-memory dataset (the multi-profile builder and the audit tooling
# read several of them) but they are not part of the published ADMT
# product: the GDAC references carry exactly eight global attributes.
# They are therefore dropped when the mono-profile file is built.
_INTERNAL_ATTRS = INTERNAL_ATTRS


def _admt_param_attrs(name: str, source_attrs: Mapping[str, Any]) -> dict[str, Any]:
    """Return the published ADMT attributes for a profile parameter.

    Falls back to the decoder's own attributes for parameters outside
    the canonical table so future sensors are not silently stripped.
    """
    canonical = _PARAM_ATTRS.get(name)
    if canonical is None:
        attrs = dict(source_attrs)
        attrs.setdefault("_FillValue", _PARAM_FILL)
        return attrs
    return {**canonical, "_FillValue": _PARAM_FILL}


def _to_param_array(values: Any, n_levels: int, source_fill: Any) -> np.ndarray:
    """Cast a science column to the ADMT float32 layout.

    Values equal to the decoder's own fill, plus any NaN, are replaced by
    the ADMT ``99999.0`` fill so the published file uses one convention.
    Real measurements are only narrowed float64 -> float32, which is the
    published storage type; no rounding or unit change is applied.
    """
    col = np.asarray(values, dtype=np.float64).reshape(-1)
    out = np.full(n_levels, float(_PARAM_FILL), dtype=np.float64)
    count = min(col.size, n_levels)
    out[:count] = col[:count]
    missing = ~np.isfinite(out)
    if source_fill is not None and np.isfinite(float(source_fill)):
        missing |= np.isclose(out, float(source_fill), rtol=0.0, atol=1e-9)
    out[missing] = float(_PARAM_FILL)
    return out.astype(np.float32).reshape(1, n_levels)


_package_version = package_version


def _history_char(values: list[str], width: int) -> xr.DataArray:
    """Build ``(N_HISTORY, N_PROF, <width>)`` history text.

    Note the dimension order: unlike every other variable in this module
    the history dimension **leads**, matching the ADMT layout and the
    GDAC references.
    """
    n_hist = len(values)
    buf = bytearray(n_hist * width)
    for i, value in enumerate(values):
        buf[i * width : (i + 1) * width] = _encode_padded(value, width)
    arr = np.frombuffer(bytes(buf), dtype="S1").reshape(n_hist, 1, width)
    dim = "DATE_TIME" if width == DATE_TIME_LEN else f"STRING{width}"
    return xr.DataArray(arr.copy(), dims=("N_HISTORY", "N_PROF", dim))


def _history_float(values: list[float]) -> xr.DataArray:
    """Build ``(N_HISTORY, N_PROF)`` numeric history data."""
    arr = np.asarray(values, dtype=np.float32).reshape(len(values), 1)
    return xr.DataArray(arr, dims=("N_HISTORY", "N_PROF"))


def _changed_qc_records(ds: xr.Dataset, params: list[str]) -> list[dict[str, Any]]:
    """Derive one ``CF`` (change-flag) record per QC-degraded parameter.

    The GDAC ``R*.nc`` references carry exactly one ``CF`` record per
    *parameter* with at least one level raised above good by real-time
    QC (not one per level): on 1902844 ``_006`` TEMP and PSAL each carry
    one ``CF`` at the single degraded level, on ``_009`` TEMP one ``CF``
    covers the degraded pair. ``HISTORY_START_PRES`` / ``HISTORY_STOP_PRES``
    bracket the degraded levels (equal when only one level is degraded);
    ``HISTORY_PREVIOUS_VALUE`` carries the pre-change flag of the first
    degraded level -- the truthful previous state of *this* pipeline
    (``0`` = the Coriolis no-QC seed) rather than an assumed ``1``.

    A decoder can supply the pre-change flags explicitly as
    ``ds.attrs['qc_previous_values'] = {param: [...]}`` (dict or JSON
    string). Without them the flag is reconstructed as 'good' (1).
    """
    import json as _json

    raw_previous = ds.attrs.get("qc_previous_values")
    previous: dict[str, Any] = {}
    if isinstance(raw_previous, dict):
        previous = raw_previous
    elif isinstance(raw_previous, str) and raw_previous.startswith("{"):
        try:
            loaded = _json.loads(raw_previous)
            if isinstance(loaded, dict):
                previous = loaded
        except ValueError:
            previous = {}
    pres = (
        np.asarray(ds["PRES"].values, dtype=np.float64).reshape(-1)
        if "PRES" in ds.data_vars
        else None
    )
    records: list[dict[str, Any]] = []
    for name in params:
        qc_name = f"{name}_QC"
        if qc_name not in ds.data_vars:
            continue
        flags = np.asarray(ds[qc_name].values).reshape(-1)
        prior = previous.get(name)
        prior_arr = np.asarray(prior).reshape(-1) if prior is not None else None
        degraded: list[int] = []
        for level, flag in enumerate(flags):
            if isinstance(flag, (bytes, np.bytes_)):
                raw = bytes(flag).strip()
                value = int(raw) if raw.isdigit() else 0
            else:
                value = int(flag)
            if value in (3, 4):
                degraded.append(level)
        if not degraded:
            continue
        first, last = degraded[0], degraded[-1]
        if prior_arr is not None and first < prior_arr.size:
            before = float(prior_arr[first])
        else:
            before = 1.0
        record: dict[str, Any] = {"parameter": name, "previous_value": before}
        if pres is not None and last < pres.size:
            start = float(pres[first])
            stop = float(pres[last])
            finite = np.isfinite(start) and np.isfinite(stop)
            record["start_pres"] = start if finite and abs(start) < 99998.0 else None
            record["stop_pres"] = stop if finite and abs(stop) < 99998.0 else None
        records.append(record)
    return records


def _history_records(
    ds: xr.Dataset,
    meta: FloatMeta | None,
    params: list[str],
    date_update: str,
    software: str,
    software_release: str,
    institution: str | None = None,
) -> list[dict[str, Any]]:
    """Assemble the real-time history record list for one profile.

    Derived from the six supplied GDAC ``R*.nc`` references, which all
    share the same structure:

    1. four processing-step records with ``ACTION='IP'`` for steps
       ``ARFM`` (format conversion), ``ARGQ`` (real-time QC), ``ARCA``
       (calibration) and ``ARUP`` (GDAC update);
    2. one ``QCP$`` record listing the tests performed as a hex mask;
    3. one ``QCF$`` record listing the tests failed as a hex mask;
    4. zero or more ``CF`` records, one per QC-degraded level.

    Only steps this decoder genuinely performs are emitted by default:
    ``ARFM`` (it converts raw ARGOS transmissions to the Argo format)
    and ``ARGQ`` (it runs the real-time QC suite). ``ARCA`` and ``ARUP``
    are *not* claimed -- no scientific calibration is applied to these
    floats and the GDAC upload is performed downstream by the DAC, not
    here -- so asserting them would be fabricating provenance.

    ``QCP$``/``QCF$`` are emitted only when the decoder supplies the
    corresponding hex masks; the current RTQC layer does not retain that
    provenance, so those records are omitted rather than invented.

    A pipeline may override the whole list via
    ``ds.attrs['history_records']``, or the step list via
    ``ds.attrs['history_steps']``, which is how delayed-mode processing
    will contribute its own records.
    """
    override = ds.attrs.get("history_records")
    if isinstance(override, list) and override:
        return [dict(rec) for rec in override if isinstance(rec, dict)]

    # ``institution`` lets a rebuild (refresh after in-place QC edits)
    # carry the original build's DAC code instead of falling back to the
    # CORIOLIS default -- the meta object is not available there.
    institution = institution or _meta_str(meta, "data_centre", "IF")
    base: dict[str, Any] = {
        "institution": institution,
        "software": software,
        "software_release": software_release,
        "date": date_update,
    }

    steps = ds.attrs.get("history_steps")
    step_list = (
        [str(s) for s in steps] if isinstance(steps, (list, tuple)) and steps else ["ARFM", "ARGQ"]
    )
    records: list[dict[str, Any]] = [{**base, "step": step, "action": "IP"} for step in step_list]

    tests_done = ds.attrs.get("rtqc_tests_done_hex")
    tests_failed = ds.attrs.get("rtqc_tests_failed_hex")
    if tests_done:
        records.append(
            {**base, "step": "ARGQ", "action": "QCP$", "qctest": str(tests_done)},
        )
        records.append(
            {
                **base,
                "step": "ARGQ",
                "action": "QCF$",
                "qctest": str(tests_failed) if tests_failed else "0",
            },
        )

    for changed in _changed_qc_records(ds, params):
        records.append(
            {
                **base,
                "step": "ARGQ",
                "action": "CF",
                "parameter": changed["parameter"],
                "previous_value": changed["previous_value"],
                "start_pres": changed.get("start_pres"),
                "stop_pres": changed.get("stop_pres"),
            },
        )
    return records


def _history_vars(records: list[dict[str, Any]]) -> dict[str, xr.DataArray]:
    """Build the twelve ``HISTORY_*`` variables from assembled records."""
    fill = np.float32(99999.0)

    def _text(key: str) -> list[str]:
        return [str(rec.get(key, "") or "") for rec in records]

    def _number(key: str) -> list[float]:
        out: list[float] = []
        for rec in records:
            value = rec.get(key)
            out.append(float(fill) if value is None else float(value))
        return out

    out: dict[str, xr.DataArray] = {}
    spec: tuple[tuple[str, str, int, dict[str, str]], ...] = (
        (
            "HISTORY_INSTITUTION",
            "institution",
            STRING4,
            {
                "long_name": "Institution which performed action",
                "conventions": "Argo reference table 4",
            },
        ),
        (
            "HISTORY_STEP",
            "step",
            STRING4,
            {
                "long_name": "Step in data processing",
                "conventions": "Argo reference table 12",
            },
        ),
        (
            "HISTORY_SOFTWARE",
            "software",
            STRING4,
            {
                "long_name": "Name of software which performed action",
                "conventions": "Institution dependent",
            },
        ),
        (
            "HISTORY_SOFTWARE_RELEASE",
            "software_release",
            STRING4,
            {
                "long_name": "Version/release of software which performed action",
                "conventions": "Institution dependent",
            },
        ),
        (
            "HISTORY_REFERENCE",
            "reference",
            STRING64,
            {
                "long_name": "Reference of database",
                "conventions": "Institution dependent",
            },
        ),
        (
            "HISTORY_DATE",
            "date",
            DATE_TIME_LEN,
            {
                "long_name": "Date the history record was created",
                "conventions": "YYYYMMDDHHMISS",
            },
        ),
        (
            "HISTORY_ACTION",
            "action",
            STRING4,
            {
                "long_name": "Action performed on data",
                "conventions": "Argo reference table 7",
            },
        ),
        (
            "HISTORY_PARAMETER",
            "parameter",
            STRING16,
            {
                "long_name": "Station parameter action is performed on",
                "conventions": "Argo reference table 3",
            },
        ),
        (
            "HISTORY_QCTEST",
            "qctest",
            STRING16,
            {
                "long_name": "Documentation of tests performed, tests failed (in hex form)",
                "conventions": (
                    "Write tests performed when ACTION=QCP$; tests failed when ACTION=QCF$"
                ),
            },
        ),
    )
    for var_name, key, width, attrs in spec:
        out[var_name] = _history_char(_text(key), width)
        out[var_name].attrs = {**attrs, "_FillValue": b" "}

    numeric: tuple[tuple[str, str, dict[str, Any]], ...] = (
        (
            "HISTORY_START_PRES",
            "start_pres",
            {"long_name": "Start pressure action applied on", "units": "decibar"},
        ),
        (
            "HISTORY_STOP_PRES",
            "stop_pres",
            {"long_name": "Stop pressure action applied on", "units": "decibar"},
        ),
        (
            "HISTORY_PREVIOUS_VALUE",
            "previous_value",
            {"long_name": "Parameter/Flag previous value before action"},
        ),
    )
    for var_name, key, attrs in numeric:
        out[var_name] = _history_float(_number(key))
        out[var_name].attrs = {**attrs, "_FillValue": fill}
    return out


def _meta_str(meta: FloatMeta | None, attr: str, default: str = "") -> str:
    if meta is None:
        return default
    value = getattr(meta, attr, "")
    return str(value) if value else default


def _positioning_system(ds: xr.Dataset, meta: FloatMeta | None) -> str:
    """Resolve POSITIONING_SYSTEM from decoder attrs, then metadata."""
    from_attrs = ds.attrs.get("positioning_system")
    if from_attrs:
        return str(from_attrs)
    if meta is not None:
        for row in meta.positioning_system:
            for value in row.values():
                if value:
                    return str(value)
    return "ARGOS"


def build_mono_profile_dataset(
    ds: xr.Dataset,
    *,
    wmo: int,
    cycle: int,
    meta: FloatMeta | None = None,
    institution: str = "CORIOLIS",
    firmware_version: str | None = None,
    date_creation: str | None = None,
    date_update: str | None = None,
    software: str = "ARPY",
    software_release: str | None = None,
) -> xr.Dataset:
    """Return an ADMT-3.1 shaped mono-profile dataset built from ``ds``.

    Parameters
    ----------
    ds:
        Decoder mono-profile dataset: ``(N_LEVELS,)`` science variables
        with ``<PARAM>_QC`` companions plus 0-d ``JULD``/``LATITUDE``/
        ``LONGITUDE``/``DIRECTION``/``DATA_MODE`` scalars.
    wmo, cycle:
        Float identifier and cycle number for this profile.
    meta:
        Float metadata used to populate PROJECT_NAME/PI_NAME/serials.
        Safe blank-padded defaults are used when ``None``.
    institution:
        Value for the global ``institution`` attribute.
    date_creation, date_update:
        ``YYYYMMDDHHMMSS`` stamps; default to "now" (UTC).
    software, software_release:
        Identify the processing software in the ``HISTORY_*`` records.
        ``software_release`` defaults to this package's version.

    Science values are copied without any dtype conversion.
    """
    now = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    created = date_creation or now
    updated = date_update or now
    release = software_release if software_release is not None else _package_version()

    n_levels = int(ds.sizes.get("N_LEVELS", 0))
    # ------------------------------------------------------------------
    # THE parameter-selection point.
    #
    # Everything downstream -- the science block, <PARAM>_QC,
    # PROFILE_<PARAM>_QC, STATION_PARAMETERS, PARAMETER,
    # SCIENTIFIC_CALIB_* and the HISTORY_* records -- is derived from
    # this one list, so restricting it here keeps every structure
    # internally consistent without per-variable special cases.
    #
    # Only parameters in ``_EXPORTED_PARAMS`` are published. The decoder
    # still computes CNDC (it is required to derive PSAL and remains on
    # the in-memory dataset for the trajectory and audit layers), but the
    # GDAC reference profiles for these INCOIS floats export PRES, TEMP
    # and PSAL only -- ``R2902224_345.nc`` has ``N_PARAM = 3`` and no
    # CNDC variable of any kind. Exporting it additionally forces a
    # choice between two FileChecker errors: omit it from
    # STATION_PARAMETERS and CK_0032 rejects the file ("Does not specify
    # 'CNDC'. Variable contains data."), or advertise it and diverge from
    # the reference. Not exporting it resolves both.
    core_present = [p for p in _CORE_PARAMS if p in ds.data_vars]
    extra_present = [
        str(name)
        for name in ds.data_vars
        if str(name) not in _CORE_PARAMS
        and str(name) in _EXPORTED_PARAMS
        and not str(name).endswith("_QC")
        and ds[name].dims == ("N_LEVELS",)
    ]
    science_params = core_present + extra_present
    # STATION_PARAMETERS must list every parameter that carries data.
    # The GDAC FileChecker (CK_0032, ArgoProfileFileValidator.java:1250)
    # reads each allowed parameter absent from the list and rejects the
    # file if any level is non-fill: "Does not specify '<PARAM>'.
    # Variable contains data." CNDC is a current, non-deprecated Argo
    # reference-table-3 parameter (NVS R03, owl:deprecated=false), so the
    # decoder-derived conductivity has to be advertised here.
    station_params = science_params or core_present

    data_vars: dict[str, xr.DataArray] = {}

    # ------------------------------------------------------------------
    # File-level scalars
    # ------------------------------------------------------------------
    data_vars["DATA_TYPE"] = _scalar_char("Argo profile", STRING16)
    data_vars["DATA_TYPE"].attrs = {
        "long_name": "Data type",
        "conventions": "Argo reference table 1",
        "_FillValue": b" ",
    }
    data_vars["FORMAT_VERSION"] = _scalar_char("3.1", STRING4)
    data_vars["FORMAT_VERSION"].attrs = {
        "long_name": "File format version",
        "_FillValue": b" ",
    }
    # Right-aligned to match the GDAC references these files are audited
    # against (all 26 supplied INCOIS profiles carry ' 1.2').
    data_vars["HANDBOOK_VERSION"] = _scalar_char(" 1.2", STRING4)
    data_vars["HANDBOOK_VERSION"].attrs = {
        "long_name": "Data handbook version",
        "_FillValue": b" ",
    }
    data_vars["REFERENCE_DATE_TIME"] = _date_char("19500101000000")
    data_vars["REFERENCE_DATE_TIME"].attrs = {
        "long_name": "Date of reference for Julian days",
        "conventions": "YYYYMMDDHHMISS",
        "_FillValue": b" ",
    }
    data_vars["DATE_CREATION"] = _date_char(created)
    data_vars["DATE_CREATION"].attrs = {
        "long_name": "Date of file creation",
        "conventions": "YYYYMMDDHHMISS",
        "_FillValue": b" ",
    }
    data_vars["DATE_UPDATE"] = _date_char(updated)
    data_vars["DATE_UPDATE"].attrs = {
        "long_name": "Date of update of this file",
        "conventions": "YYYYMMDDHHMISS",
        "_FillValue": b" ",
    }

    # ------------------------------------------------------------------
    # Profile metadata
    # ------------------------------------------------------------------
    data_vars["PLATFORM_NUMBER"] = _prof_char(str(wmo), STRING8)
    data_vars["PLATFORM_NUMBER"].attrs = {
        "long_name": "Float unique identifier",
        "conventions": "WMO float identifier : A9IIIII",
        "_FillValue": b" ",
    }
    data_vars["PROJECT_NAME"] = _prof_char(_meta_str(meta, "project_name"), STRING64)
    data_vars["PROJECT_NAME"].attrs = {
        "long_name": "Name of the project",
        "_FillValue": b" ",
    }
    data_vars["PI_NAME"] = _prof_char(_meta_str(meta, "pi_name"), STRING64)
    data_vars["PI_NAME"].attrs = {
        "long_name": "Name of the principal investigator",
        "_FillValue": b" ",
    }
    data_vars["STATION_PARAMETERS"] = _station_parameters(station_params)
    data_vars["STATION_PARAMETERS"].attrs = {
        "long_name": "List of available parameters for the station",
        "conventions": "Argo reference table 3",
        "_FillValue": b" ",
    }
    data_vars["CYCLE_NUMBER"] = xr.DataArray(
        np.array([cycle], dtype=np.int32),
        dims=("N_PROF",),
        attrs={
            "long_name": "Float cycle number",
            "conventions": "0...N, 0 : launch cycle (if exists), 1 : first complete cycle",
            "_FillValue": _INT_FILL,
        },
    )
    direction = _scalar_from_ds(ds, "DIRECTION", b"A")
    data_vars["DIRECTION"] = _prof_flag(direction)
    data_vars["DIRECTION"].attrs = {
        "long_name": "Direction of the station profiles",
        "conventions": "A: ascending profiles, D: descending profiles",
        "_FillValue": b" ",
    }
    data_vars["DATA_CENTRE"] = _prof_char(_meta_str(meta, "data_centre", "IF"), STRING2)
    data_vars["DATA_CENTRE"].attrs = {
        "long_name": "Data centre in charge of float data processing",
        "conventions": "Argo reference table 4",
        "_FillValue": b" ",
    }
    data_vars["DC_REFERENCE"] = _prof_char(f"{wmo}/{cycle}", STRING32)
    data_vars["DC_REFERENCE"].attrs = {
        "long_name": "Station unique identifier in data centre",
        "conventions": "Data centre convention",
        "_FillValue": b" ",
    }
    # Real-time output that has passed automatic QC: Argo reference
    # table 6 code "2B". Delayed-mode ("2C") is not produced here.
    data_vars["DATA_STATE_INDICATOR"] = _prof_char("2B", STRING4)
    data_vars["DATA_STATE_INDICATOR"].attrs = {
        "long_name": "Degree of processing the data have passed through",
        "conventions": "Argo reference table 6",
        "_FillValue": b" ",
    }
    data_mode = _scalar_from_ds(ds, "DATA_MODE", b"R")
    data_vars["DATA_MODE"] = _prof_flag(data_mode)
    data_vars["DATA_MODE"].attrs = {
        "long_name": "Delayed mode or real time data",
        "conventions": "R : real time; D : delayed mode; A : real time with adjustment",
        "_FillValue": b" ",
    }
    platform_type = _meta_str(meta, "platform_type") or str(ds.attrs.get("platform_type", ""))
    data_vars["PLATFORM_TYPE"] = _prof_char(platform_type, STRING32)
    data_vars["PLATFORM_TYPE"].attrs = {
        "long_name": "Type of float",
        "conventions": "Argo reference table 23",
        "_FillValue": b" ",
    }
    data_vars["FLOAT_SERIAL_NO"] = _prof_char(_meta_str(meta, "float_serial_no"), STRING32)
    data_vars["FLOAT_SERIAL_NO"].attrs = {
        "long_name": "Serial number of the float",
        "_FillValue": b" ",
    }
    # ``firmware_version`` lets a family publish the reference label the
    # GDAC files carry (e.g. the SBE41CP sensor firmware for ARVOR-I)
    # when it differs from the float-engine date-code in the meta sheet.
    firmware = (
        firmware_version
        or _meta_str(meta, "firmware_version")
        or str(ds.attrs.get("decoder_version", ""))
    )
    data_vars["FIRMWARE_VERSION"] = _prof_char(firmware, STRING32)
    data_vars["FIRMWARE_VERSION"].attrs = {
        "long_name": "Instrument firmware version",
        "_FillValue": b" ",
    }
    data_vars["WMO_INST_TYPE"] = _prof_char(_meta_str(meta, "wmo_inst_type"), STRING4)
    data_vars["WMO_INST_TYPE"].attrs = {
        "long_name": "Coded instrument type",
        "conventions": "Argo reference table 8",
        "_FillValue": b" ",
    }

    # ------------------------------------------------------------------
    # Date / location (values carried through unchanged)
    # ------------------------------------------------------------------
    juld_raw = _scalar_from_ds(ds, "JULD", _DOUBLE_FILL_JULD)
    juld_value = np.float64(juld_raw)
    if not np.isfinite(juld_value):
        juld_value = _DOUBLE_FILL_JULD
    juld_attrs: dict[str, Any] = {
        "long_name": "Julian day (UTC) of the station relative to REFERENCE_DATE_TIME",
        "standard_name": "time",
        "units": "days since 1950-01-01 00:00:00 UTC",
        "conventions": "Relative julian days with decimal part (as parts of day)",
        "resolution": _JULD_RESOLUTION,
        "_FillValue": _DOUBLE_FILL_JULD,
        "axis": "T",
    }
    data_vars["JULD"] = xr.DataArray(
        np.array([juld_value], dtype=np.float64), dims=("N_PROF",), attrs=juld_attrs
    )
    data_vars["JULD_QC"] = _prof_flag(_scalar_from_ds(ds, "JULD_QC", b"0"))
    data_vars["JULD_QC"].attrs = {
        "long_name": "Quality on date and time",
        "conventions": "Argo reference table 2",
        "_FillValue": b" ",
    }
    # JULD_LOCATION is the acquisition time of the surface fix that gave
    # LATITUDE/LONGITUDE. Falls back to JULD only when the decoder could
    # not associate a fix with this profile.
    location_raw = _scalar_from_ds(ds, "JULD_LOCATION", _DOUBLE_FILL_JULD)
    location_value = np.float64(location_raw)
    if not np.isfinite(location_value) or location_value == _DOUBLE_FILL_JULD:
        location_value = juld_value
    data_vars["JULD_LOCATION"] = xr.DataArray(
        np.array([location_value], dtype=np.float64),
        dims=("N_PROF",),
        attrs={
            "long_name": "Julian day (UTC) of the location relative to REFERENCE_DATE_TIME",
            "units": "days since 1950-01-01 00:00:00 UTC",
            "conventions": "Relative julian days with decimal part (as parts of day)",
            "resolution": _JULD_RESOLUTION,
            "_FillValue": _DOUBLE_FILL_JULD,
            "axis": "T",
        },
    )
    lat = np.float64(_scalar_from_ds(ds, "LATITUDE", _DOUBLE_FILL))
    lon = np.float64(_scalar_from_ds(ds, "LONGITUDE", _DOUBLE_FILL))
    data_vars["LATITUDE"] = xr.DataArray(
        np.array([lat if np.isfinite(lat) else _DOUBLE_FILL], dtype=np.float64),
        dims=("N_PROF",),
        attrs={
            "long_name": "Latitude of the station, best estimate",
            "standard_name": "latitude",
            "units": "degree_north",
            "_FillValue": _DOUBLE_FILL,
            "valid_min": np.float64(-90.0),
            "valid_max": np.float64(90.0),
            "axis": "Y",
        },
    )
    data_vars["LONGITUDE"] = xr.DataArray(
        np.array([lon if np.isfinite(lon) else _DOUBLE_FILL], dtype=np.float64),
        dims=("N_PROF",),
        attrs={
            "long_name": "Longitude of the station, best estimate",
            "standard_name": "longitude",
            "units": "degree_east",
            "_FillValue": _DOUBLE_FILL,
            "valid_min": np.float64(-180.0),
            "valid_max": np.float64(180.0),
            "axis": "X",
        },
    )
    data_vars["POSITION_QC"] = _prof_flag(_scalar_from_ds(ds, "POSITION_QC", b"0"))
    data_vars["POSITION_QC"].attrs = {
        "long_name": "Quality on position (latitude and longitude)",
        "conventions": "Argo reference table 2",
        "_FillValue": b" ",
    }
    data_vars["POSITIONING_SYSTEM"] = _prof_char(_positioning_system(ds, meta), STRING8)
    data_vars["POSITIONING_SYSTEM"].attrs = {
        "long_name": "Positioning system",
        "_FillValue": b" ",
    }
    vss = str(ds.attrs.get("vertical_sampling_scheme", "Primary sampling: discrete []"))
    data_vars["VERTICAL_SAMPLING_SCHEME"] = _prof_char(vss, STRING256)
    data_vars["VERTICAL_SAMPLING_SCHEME"].attrs = {
        "long_name": "Vertical sampling scheme",
        "conventions": "Argo reference table 16",
        "_FillValue": b" ",
    }
    data_vars["CONFIG_MISSION_NUMBER"] = xr.DataArray(
        np.array([int(ds.attrs.get("config_mission_number", 1))], dtype=np.int32),
        dims=("N_PROF",),
        attrs={
            "long_name": "Unique number denoting the missions performed by the float",
            "conventions": "1...N, 1 : first complete mission",
            "_FillValue": _INT_FILL,
        },
    )

    # ------------------------------------------------------------------
    # Science block: reshape only, never re-cast.
    # ------------------------------------------------------------------
    for name in science_params:
        source = ds[name]
        data_vars[name] = xr.DataArray(
            _to_param_array(source.values, n_levels, source.attrs.get("_FillValue")),
            dims=("N_PROF", "N_LEVELS"),
            attrs=_admt_param_attrs(name, source.attrs),
        )
        qc_name = f"{name}_QC"
        qc_values = ds[qc_name].values if qc_name in ds.data_vars else np.full(n_levels, 9)
        data_vars[qc_name] = xr.DataArray(
            _qc_to_char(qc_values, n_levels),
            dims=("N_PROF", "N_LEVELS"),
            attrs={
                "long_name": "quality flag",
                "conventions": "Argo reference table 2",
                "_FillValue": b" ",
            },
        )
        # Adjusted family: only the ADMT core parameters carry one
        # (``adjAllowed`` in MATLAB ``nc_create_multi_prof_file.m``), so
        # the decoder-derived CNDC is excluded.
        if name in _CORE_PARAMS:
            data_vars.update(_adjusted_vars(name, source, ds, n_levels))

    # PROFILE_<PARAM>_QC: Argo reference table 2a percentage-of-good flag.
    # Iterates every science parameter, not just the STATION_PARAMETERS
    # core set: the GDAC FileChecker treats <PARAM>, <PARAM>_QC and
    # PROFILE_<PARAM>_QC as one parameter group and rejects the file if
    # any member is absent. The decoder-derived CNDC has the first two,
    # so it needs the third.
    for name in science_params:
        qc_name = f"{name}_QC"
        if qc_name in data_vars:
            flag = _profile_qc_flag(np.asarray(data_vars[qc_name].values, dtype="S1"))
        else:
            flag = " "
        data_vars[f"PROFILE_{name}_QC"] = _prof_flag(flag)
        data_vars[f"PROFILE_{name}_QC"].attrs = {
            "long_name": f"Global quality flag of {name} profile",
            "conventions": "Argo reference table 2a",
            "_FillValue": b" ",
        }

    # PARAMETER plus the SCIENTIFIC_CALIB_* group complete the N_CALIB
    # calibration slot. HISTORY_* remains deferred.
    data_vars["PARAMETER"] = _parameter_var(station_params)
    data_vars["PARAMETER"].attrs = {
        "long_name": "List of parameters with calibration information",
        "conventions": "Argo reference table 3",
        "_FillValue": b" ",
    }
    data_vars.update(_scientific_calib_vars(station_params, ds, meta, updated))

    # HISTORY_* group. Records are derived from what the decoder actually
    # did (processing steps, RTQC provenance, QC flag changes); an empty
    # list yields a zero-length N_HISTORY rather than invented records.
    history = _history_records(
        ds,
        meta,
        station_params,
        updated,
        software=software,
        software_release=release,
    )
    data_vars.update(_history_vars(history))

    out = xr.Dataset(data_vars)
    # Preserve the decoder's provenance attributes, then layer the
    # standard Argo globals on top. Internal counters are dropped: the
    # published ADMT file carries only the eight standard globals, and
    # the decoder's working attributes remain on the in-memory dataset
    # for the multi-profile builder and the audit tooling.
    out.attrs.update({k: v for k, v in ds.attrs.items() if k not in _INTERNAL_ATTRS})
    out.attrs.update(
        {
            "title": "Argo float vertical profile",
            # Reference table 4 institution name, not the DAC code.
            "institution": institution_for_data_centre(institution),
            "source": "Argo float",
            "history": f"{datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')} creation",
            "references": "http://www.argodatamgt.org/Documentation",
            "user_manual_version": "3.1",
            "Conventions": "Argo-3.1 CF-1.6",
            "featureType": "trajectoryProfile",
        }
    )
    return out


def refresh_history_records(ds: xr.Dataset) -> xr.Dataset:
    """Rebuild the ``HISTORY_*`` block after in-place QC flag edits.

    :func:`build_mono_profile_dataset` materialises ``HISTORY_*`` when the
    product is first assembled -- before any downstream real-time QC has
    run. Pipelines that mutate ``*_QC`` flags or set the
    ``rtqc_tests_done_hex`` / ``rtqc_tests_failed_hex`` /
    ``qc_previous_values`` attributes afterwards call this to re-derive
    the ``QCP$`` / ``QCF$`` / ``CF`` records from the edited dataset.

    Provenance fields (institution, software, release, date) are carried
    over from the existing records when present, so the refreshed block
    stays consistent with the original build instead of re-stamping it.
    """
    if "HISTORY_ACTION" not in ds.data_vars:
        return ds

    def _first(key: str) -> str | None:
        if key not in ds.data_vars:
            return None
        raw = np.asarray(ds[key].values, dtype="S1")
        text = b"".join(raw.reshape(-1)[: raw.shape[-1]]).decode("ascii", "ignore").strip()
        return text or None

    def _row(key: str, row: int) -> str | None:
        if key not in ds.data_vars:
            return None
        raw = np.asarray(ds[key].values, dtype="S1")
        if raw.ndim < 2:
            return None
        text = b"".join(raw.reshape(raw.shape[0], -1)[row]).decode("ascii", "ignore").strip()
        return text or None

    records_override = ds.attrs.get("history_records")
    if isinstance(records_override, list) and records_override:
        return ds  # explicit override wins; do not touch

    params: list[str] = []
    if "PARAMETER" in ds.data_vars:
        raw = np.asarray(ds["PARAMETER"].values, dtype="S1")
        # PARAMETER is (N_PROF, N_PARAM, STRING16): one row per parameter,
        # not per profile slot -- flattening the leading dims would
        # concatenate all names into one (the bug that suppressed the CF
        # records on every RTQC product).
        rows = raw.reshape(-1, raw.shape[-1]) if raw.ndim >= 2 else raw.reshape(1, -1)
        params = [b"".join(row).decode("ascii", "ignore").strip() for row in rows]
    date = _row("HISTORY_DATE_TIME", 0)
    # Keep the original build provenance on the re-derived records.
    institution = _first("HISTORY_INSTITUTION")
    records = _history_records(
        ds,
        meta=None,
        params=params,
        date_update=date or datetime.now(UTC).strftime("%Y%m%d%H%M%S"),
        software=_first("HISTORY_SOFTWARE") or "ARPY",
        software_release=_first("HISTORY_SOFTWARE_RELEASE"),
        institution=institution,
    )
    for key in list(ds.data_vars):
        if key.startswith("HISTORY_"):
            del ds[key]
    ds.update(_history_vars(records))
    return ds


def write_mono_profile(ds: xr.Dataset, path: Path) -> None:
    """Write an ADMT mono-profile dataset to ``path``.

    Delegates to :func:`argo_decoder.nc.admt.write_admt_dataset`, which
    bypasses ``xarray.to_netcdf`` for two reasons: xarray appends a
    spurious trailing ``string1`` dimension to every ``dtype='S1'``
    array, and the fixed ADMT dimensions ``N_CALIB`` / ``N_HISTORY``
    must exist even when no variable references them.
    """
    fixed: dict[str, int | None] = {
        "N_PROF": 1,
        "N_PARAM": int(ds.sizes.get("N_PARAM", len(_CORE_PARAMS))),
        "N_LEVELS": int(ds.sizes.get("N_LEVELS", 0)),
        "N_CALIB": 1,
        # Unlimited so HISTORY records can be appended without a
        # dimension change.
        "N_HISTORY": None,
    }
    for dim_name, size in _FIXED_STRING_DIMS:
        fixed[dim_name] = size
    # Internal working attributes (RTQC masks, pre-QC flag snapshots,
    # decoder counters) live on the in-memory dataset; the published
    # ADMT product carries only its standard globals. build_mono_profile_
    # dataset strips them at assembly; post-build mutations (the RTQC
    # stage) re-add them, so strip again here -- idempotent for paths
    # that never carried them.
    for key in _INTERNAL_ATTRS:
        ds.attrs.pop(key, None)
    write_admt_dataset(
        ds,
        path,
        fixed_dims=fixed,
        dim_order=("N_PROF", "N_PARAM", "N_LEVELS", "N_CALIB", "N_HISTORY"),
    )
