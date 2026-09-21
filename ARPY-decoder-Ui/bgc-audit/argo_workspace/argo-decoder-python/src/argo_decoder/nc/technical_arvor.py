"""ARVOR-I ADMT technical (``<wmo>_tech.nc``) writer — Phase 4A.

Thin NetCDF writer for the technical product model built by
:mod:`argo_decoder.platforms.provor_ir_sbd.arvor_i_tech`.  The layout,
variable order, dtypes, attributes and header values transcribe
``create_nc_tech_file_3_1.m`` (the writer the Coriolis chain dispatches to
for Iridium SBD PROVOR/ARVOR floats; read end-to-end, toolbox 20250516_076a):

* dimensions ``DATE_TIME``/``STRING128``/``STRING32``/``STRING8``/
  ``STRING4``/``STRING2`` and ``N_TECH_PARAM`` (unlimited), created in that
  order;
* variables in definition order ``PLATFORM_NUMBER``, ``DATA_TYPE``,
  ``FORMAT_VERSION``, ``HANDBOOK_VERSION``, ``DATA_CENTRE``,
  ``DATE_CREATION``, ``DATE_UPDATE``, ``TECHNICAL_PARAMETER_NAME``,
  ``TECHNICAL_PARAMETER_VALUE``, ``CYCLE_NUMBER``;
* ``TECHNICAL_PARAMETER_NAME``/``_VALUE`` are ``NC_CHAR(N_TECH_PARAM,
  STRING128)`` with values stored as text (``num2str`` for numbers, exact
  ``sprintf`` strings for dates/times);
* header values ``DATA_TYPE='Argo technical data'``, ``FORMAT_VERSION=
  '3.1'``, ``HANDBOOK_VERSION='1.2'``, ``DATA_CENTRE`` from float metadata
  (single-space fallback when absent, as in the MATLAB writer);
* global attributes as written by the MATLAB chain, including
  ``decoder_version`` (``CODA_076a`` by default -- the Coriolis toolbox
  version this writer mirrors) and the Argo DOI ``id`` attribute.

No ARVOR/PROVOR GDAC ``_tech.nc`` exists in the workspace, so GDAC
comparison is DATA-COVERAGE-limited; the ADMT conventions themselves are
proven in this repo by ``nc/admt.py`` against the APEX GDAC references.
The APEX writer (``nc/technical.py``) is untouched.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import xarray as xr

from argo_decoder.nc.admt import (
    DATE_TIME_LEN,
    INT_FILL,
    STRING2,
    STRING4,
    STRING8,
    STRING32,
    STRING128,
    char_column,
    date_char,
    institution_for_data_centre,
    scalar_char,
    utc_stamp,
    write_admt_dataset,
)
from argo_decoder.platforms.provor_ir_sbd.arvor_i_tech import (
    ArvorTechDataset,
    TechParamRow,
)

_TECH = "N_TECH_PARAM"

# create_nc_tech_file_3_1.m / init_default_values.m
DECODER_VERSION = "CODA_076a"
ARGO_DOI = "https://doi.org/10.17882/42182"
HISTORY_SUFFIX = "last update (coriolis float real time data processing)"


# ---------------------------------------------------------------------------
# GDAC publication projection (ARVOR-I family)
# ---------------------------------------------------------------------------
#: The INCOIS GDAC ``_tech.nc`` publishes a fixed 22-slot row set per cycle
#: (21 unique names; the InternalVacuum name occupies two slots, the second
#: one blank). Slots map to the canonical Coriolis decode by internal row
#: name; ``kind`` selects the published representation:
#:   None      -> identity (value text passes through),
#:   "hours"   -> HHMM -> decimal hours (MATLAB num2str-style text),
#:   "ft_h/m/s -> CLOCK_FloatTime_* from the decoded float-clock timestamp.
#: ``internal=None`` slots are the intentionally blank GDAC placeholders
#: (no source item exists in the Coriolis 222-family table -- or, for the
#: duplicate vacuum slot, GDAC publishes no value there).
_GDAC_TECH_SLOTS: tuple[tuple[str, str | None, str | None], ...] = (
    (
        "VOLTAGE_BatteryInitialAtProfileDepth_volts",
        "VOLTAGE_BatteryPumpStartProfile_volts",
        None,
    ),
    (
        "PRESSURE_InternalVacuum_inHg",
        "PRESSURE_InternalVacuumAtSurface_mbar",
        None,
    ),
    ("FLAG_ProfileTermination_hex", None, None),
    (
        "CLOCK_StartDescentToPark_hours",
        "CLOCK_StartDescentProfile_HHMM",
        "hours",
    ),
    (
        "NUMBER_ValveActionsAtSurfaceDuringDescent_COUNT",
        "NUMBER_ValveActionsAtSurfaceDuringDescent_COUNT",
        None,
    ),
    (
        "CLOCK_InitialStabilizationDuringDescentToPark_hours",
        "CLOCK_InitialStabilizationDuringDescentToPark_HHMM",
        "hours",
    ),
    (
        "NUMBER_ValveActionsDuringDescentToPark_COUNT",
        "NUMBER_ValveActionsDuringDescentToPark_COUNT",
        None,
    ),
    (
        "NUMBER_PumpActionsDuringDescentToPark_COUNT",
        "NUMBER_PumpActionsDuringDescentToPark_COUNT",
        None,
    ),
    (
        "CLOCK_EndDescentToPark_hours",
        "CLOCK_EndDescentToPark_HHMM",
        "hours",
    ),
    (
        "NUMBER_RepositionsDuringPark_COUNT",
        "NUMBER_RepositionsDuringPark_COUNT",
        None,
    ),
    (
        "NUMBER_PumpActionsDuringAscentToSurface_COUNT",
        "NUMBER_PumpActionsDuringAscentToSurface_COUNT",
        None,
    ),
    (
        "CLOCK_EndAscentToSurface_hours",
        "CLOCK_TransmissionStart_HHMM",
        "hours",
    ),
    ("NUMBER_PumpActionsAtSurface_COUNT", None, None),
    ("CLOCK_FloatTime_hours", None, "ft_h"),
    ("CLOCK_FloatTime_minutes", None, "ft_m"),
    ("CLOCK_FloatTime_seconds", None, "ft_s"),
    # Scientifically correct Coriolis decode (item 47 twos8/10 -> dbar).
    # GDAC publishes the raw centibar count under this name (x10 of ours,
    # verified on every overlapping cell) -- a demonstrated unit error that
    # is NOT reproduced; the correct dbar value is published.
    (
        "PRES_SurfaceOffsetNotTruncated_dbar",
        "PRES_SurfaceOffsetCorrectedNotResetNegative_1cBarResolution_dbar",
        None,
    ),
    # Duplicate InternalVacuum slot: GDAC keeps the slot and publishes it
    # blank (it drops the ProfileStart value); the structure is preserved.
    ("PRESSURE_InternalVacuum_inHg", None, None),
    # GDAC publishes Argos-style names on this Iridium family; kept for
    # publication compatibility (the decode itself is Iridium-native).
    (
        "NUMBER_AscentArgosMessages_COUNT",
        "NUMBER_AscentIridiumPackets_COUNT",
        None,
    ),
    ("NUMBER_AscentSamples_COUNT", None, None),
    (
        "NUMBER_ParkArgosMessages_COUNT",
        "NUMBER_ParkIridiumPackets_COUNT",
        None,
    ),
    (
        "NUMBER_ParkSamples_COUNT",
        "NUMBER_ParkCTDSamplesInternal_COUNT",
        None,
    ),
)


def _gdac_hours_text(hhmm: str) -> str:
    """HHMM clock text -> decimal-hours text (GDAC formatting).

    Rule recovered from every hour cell of the four GDAC references:
    round to 4 decimals; when that carries fewer than 5 significant
    digits, keep 5 significant digits instead; trim trailing zeros
    (e.g. 2043 -> '20.7167', 0108 -> '1.1333', 0005 -> '0.083333',
    26/60 -> '0.43333', 1200 -> '12').
    """

    raw = int(hhmm)
    hours = raw // 100 + (raw % 100) / 60.0
    if hours == 0:
        return "0"
    text = f"{hours:.4f}"
    significant = len(text.replace("-", "").replace(".", "").lstrip("0"))
    if significant < 5:
        text = f"{hours:.5g}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def arvor_tech_publication_rows(rows: list, float_times: dict | None = None) -> list:
    """Project canonical Coriolis tech rows onto the GDAC publication slots.

    Pure family-generic projection: per cycle (ascending) the fixed
    ``_GDAC_TECH_SLOTS`` row set is emitted -- renames applied, HHMM clocks
    converted to decimal hours, the decoded float-clock timestamp split
    into hours/minutes/seconds, and blank placeholders emitted verbatim.
    Values derive exclusively from the decoded ``rows`` / ``float_times``
    (raw telemetry -> decoder); nothing is read from any GDAC file. The
    pre-mission (cycle 0) block GDAC carries has no counterpart in the
    decode (no such buffer in the telemetry) and is not fabricated.
    """
    times = float_times or {}
    by_cycle: dict[int, dict[str, object]] = {}
    for row in rows:
        by_cycle.setdefault(row.cycle_number, {})[row.name] = row
    published: list = []
    for cycle in sorted(by_cycle):
        internal = by_cycle[cycle]
        stamp = times.get(cycle)
        for gdac_name, internal_name, kind in _GDAC_TECH_SLOTS:
            value = ""
            param_id = 0
            source = "publication projection"
            if internal_name is not None:
                row = internal.get(internal_name)
                if row is not None:
                    value = _gdac_hours_text(row.value) if kind == "hours" else row.value
                    param_id = getattr(row, "param_id", 0)
                    source = f"publication projection of {internal_name}"
            elif kind in ("ft_h", "ft_m", "ft_s") and stamp is not None:
                part = {"ft_h": stamp.hour, "ft_m": stamp.minute, "ft_s": stamp.second}[kind]
                value = str(part)
                source = "publication projection of tech1 float_time (items 41-46)"
            published.append(
                TechParamRow(
                    cycle_number=cycle,
                    param_id=param_id,
                    name=gdac_name,
                    value=value,
                    source=source,
                )
            )
    return published


def build_arvor_tech_nc_dataset(
    rows: list[TechParamRow],
    *,
    wmo: int,
    data_centre: str = " ",
    decoder_version: str = DECODER_VERSION,
    date_creation: str | None = None,
    date_update: str | None = None,
    float_times: dict | None = None,
) -> xr.Dataset:
    """Build the ``<wmo>_tech.nc`` dataset from the final row list.

    ``rows`` must already be in final order (cycles ascending, alphabetical
    by parameter name within a cycle) and contain only ``_tech.nc`` rows --
    :attr:`ArvorTechDataset.tech_rows` provides exactly that view. The rows
    are then projected onto the fixed GDAC publication slots (see
    :func:`arvor_tech_publication_rows`); pass the decoded ``float_times``
    to emit the CLOCK_FloatTime_* rows.
    """

    rows = arvor_tech_publication_rows(rows, float_times)
    now = utc_stamp()
    created = date_creation or now
    updated = date_update or now
    centre = data_centre if data_centre else " "

    def iso(stamp: str) -> str:
        return datetime.strptime(stamp, "%Y%m%d%H%M%S").strftime("%Y-%m-%dT%H:%M:%SZ")

    data_vars: dict[str, xr.DataArray] = {}

    data_vars["PLATFORM_NUMBER"] = scalar_char(str(wmo), STRING8)
    data_vars["PLATFORM_NUMBER"].attrs = {
        "long_name": "Float unique identifier",
        "conventions": "WMO float identifier : A9IIIII",
        "_FillValue": b" ",
    }

    data_vars["DATA_TYPE"] = scalar_char("Argo technical data", STRING32)
    data_vars["DATA_TYPE"].attrs = {
        "long_name": "Data type",
        "conventions": "Argo reference table 1",
        "_FillValue": b" ",
    }

    data_vars["FORMAT_VERSION"] = scalar_char("3.1", STRING4)
    data_vars["FORMAT_VERSION"].attrs = {
        "long_name": "File format version",
        "_FillValue": b" ",
    }

    data_vars["HANDBOOK_VERSION"] = scalar_char("1.2", STRING4)
    data_vars["HANDBOOK_VERSION"].attrs = {
        "long_name": "Data handbook version",
        "_FillValue": b" ",
    }

    data_vars["DATA_CENTRE"] = scalar_char(centre, STRING2)
    data_vars["DATA_CENTRE"].attrs = {
        "long_name": "Data centre in charge of float data processing",
        "conventions": "Argo reference table 4",
        "_FillValue": b" ",
    }

    data_vars["DATE_CREATION"] = date_char(created)
    data_vars["DATE_CREATION"].attrs = {
        "long_name": "Date of file creation",
        "conventions": "YYYYMMDDHHMISS",
        "_FillValue": b" ",
    }

    data_vars["DATE_UPDATE"] = date_char(updated)
    data_vars["DATE_UPDATE"].attrs = {
        "long_name": "Date of update of this file",
        "conventions": "YYYYMMDDHHMISS",
        "_FillValue": b" ",
    }

    data_vars["TECHNICAL_PARAMETER_NAME"] = char_column([r.name for r in rows], STRING128, _TECH)
    data_vars["TECHNICAL_PARAMETER_NAME"].attrs = {
        "long_name": "Name of technical parameter",
        "_FillValue": b" ",
    }

    data_vars["TECHNICAL_PARAMETER_VALUE"] = char_column([r.value for r in rows], STRING128, _TECH)
    data_vars["TECHNICAL_PARAMETER_VALUE"].attrs = {
        "long_name": "Value of technical parameter",
        "_FillValue": b" ",
    }

    data_vars["CYCLE_NUMBER"] = xr.DataArray(
        np.asarray([r.cycle_number for r in rows], dtype=np.int32),
        dims=(_TECH,),
        attrs={
            "long_name": "Float cycle number",
            "conventions": ("0...N, 0 : launch cycle (if exists), 1 : first complete cycle"),
            "_FillValue": INT_FILL,
        },
    )

    out = xr.Dataset(data_vars)
    # create_nc_tech_file_3_1.m global attributes, in putAtt order.
    out.attrs["title"] = "Argo float technical data file"
    if centre.strip():
        out.attrs["institution"] = institution_for_data_centre(centre)
    else:
        # MATLAB default when the float meta JSON carries no DATA_CENTRE.
        out.attrs["institution"] = "CORIOLIS"
    out.attrs["source"] = "Argo float"
    out.attrs["history"] = f"{iso(created)} creation; {iso(updated)} {HISTORY_SUFFIX}"
    out.attrs["references"] = "http://www.argodatamgt.org/Documentation"
    out.attrs["user_manual_version"] = "3.1"
    out.attrs["Conventions"] = "Argo-3.1 CF-1.6"
    out.attrs["decoder_version"] = decoder_version
    out.attrs["id"] = ARGO_DOI
    return out


def build_arvor_tech_nc_dataset_from_product(
    dataset: ArvorTechDataset,
    *,
    data_centre: str = " ",
    decoder_version: str = DECODER_VERSION,
    date_creation: str | None = None,
    date_update: str | None = None,
) -> xr.Dataset:
    """Convenience wrapper taking the full :class:`ArvorTechDataset`."""

    if dataset.wmo is None:
        raise ValueError("ArvorTechDataset.wmo is required to write _tech.nc")
    return build_arvor_tech_nc_dataset(
        dataset.tech_rows,
        wmo=dataset.wmo,
        data_centre=data_centre,
        decoder_version=decoder_version,
        date_creation=date_creation,
        date_update=date_update,
        float_times=dataset.float_times,
    )


def write_arvor_tech_file(ds: xr.Dataset, path: Path) -> None:
    """Write an ARVOR technical dataset in MATLAB dimension order."""

    fixed: dict[str, int | None] = {
        "DATE_TIME": DATE_TIME_LEN,
        "STRING128": STRING128,
        "STRING32": STRING32,
        "STRING8": STRING8,
        "STRING4": STRING4,
        "STRING2": STRING2,
        # unlimited, as in create_nc_tech_file_3_1.m
        _TECH: None,
    }
    write_admt_dataset(
        ds,
        path,
        fixed_dims=fixed,
        dim_order=(
            "DATE_TIME",
            "STRING128",
            "STRING32",
            "STRING8",
            "STRING4",
            "STRING2",
            _TECH,
        ),
    )


def write_arvor_tech_nc(
    dataset: ArvorTechDataset,
    path: Path,
    *,
    data_centre: str = " ",
    decoder_version: str = DECODER_VERSION,
    date_creation: str | None = None,
    date_update: str | None = None,
) -> Path:
    """Build and write ``<wmo>_tech.nc`` for a technical product model."""

    ds = build_arvor_tech_nc_dataset_from_product(
        dataset,
        data_centre=data_centre,
        decoder_version=decoder_version,
        date_creation=date_creation,
        date_update=date_update,
    )
    write_arvor_tech_file(ds, path)
    return path


__all__ = [
    "ARGO_DOI",
    "DECODER_VERSION",
    "build_arvor_tech_nc_dataset",
    "build_arvor_tech_nc_dataset_from_product",
    "write_arvor_tech_file",
    "write_arvor_tech_nc",
]
