"""APF11 Technical NetCDF writer.

Emits standard accumulating APF11 ``<WMO>_tech.nc`` adhering to:
1. Official Argo 3.1 technical specifications (manual §2.5.4).
2. Pinned upstream Coriolis routing: ``mappingTech = [1 3 7]`` in
   ``create_technical_time_series_apx_apf11_ir.m``, directing Air Bladder Pressure,
   Battery Voltage, and Internal Vacuum into numeric ``N_TECH_MEASUREMENT`` variables.
3. Native float32 precision, UTC Julian date, and cycle attribution.
4. Valid scalar parameters in ``N_TECH_PARAM``; unresolved multi-event lists
   (coulomb counter, destination completions) are kept in provenance receipts,
   never truncated or forced into scalar identities.
"""

from __future__ import annotations

from datetime import UTC, datetime
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import netCDF4
import numpy as np

from argo_decoder.nc.admt import DAC_INSTITUTION
from argo_decoder.writer.apf11_policy import APF11_NC_FORMAT
from argo_decoder.platforms.apex_apf11_ir.technical import CycleTechnical
from argo_decoder.platforms.apex_apf11_ir.technical_measurements import (
    CHANNELS,
    Occurrence,
    load_float_technical_records,
)

DATE_TIME = 14
STRING2, STRING8, STRING32 = 2, 8, 32
STRING4 = 4
STRING128 = 128
INT_FILL = np.int32(99999)
FLOAT_FILL = np.float32(99999.0)
DOUBLE_FILL = np.float64(999999.0)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y%m%d%H%M%S")


def _write_str_char(ds: netCDF4.Dataset, name: str, dim: str, value: str) -> None:
    """Create a fixed-width string scalar and store ``value`` space-padded."""
    width = int(ds.dimensions[dim].size)
    var = ds.createVariable(name, "S1", (dim,), fill_value=" ")
    data = np.zeros((width,), dtype="S1")
    raw = value.encode("ascii", "replace")[:width]
    data[: len(raw)] = np.frombuffer(raw, dtype="S1")
    data[len(raw) :] = b" "
    var[:] = data


class TechnicalRepresentationError(ValueError):
    """Complete inputs retained; no truncated or lossy NetCDF may be emitted."""

    def __init__(self, rows: Any, issues: list[str]) -> None:
        self.rows = tuple(rows)
        self.issues = tuple(issues)
        super().__init__("Argo technical STRING128 representation cannot preserve input: " + "; ".join(issues))


def validate_technical_rows(rows: list[tuple[str, str, int]]) -> None:
    """Argo manual 2.5 requires STRING128, not arbitrary wider/continued cells."""
    issues = []
    for name, value, cycle in rows:
        for field, text in (("name", name), ("value", value)):
            try:
                data = text.encode("ascii")
            except UnicodeEncodeError:
                issues.append(f"cycle {cycle} {name}: non-ASCII {field}")
                continue
            if len(data) > STRING128:
                issues.append(f"cycle {cycle} {name}: {field} has {len(data)} bytes (limit {STRING128})")
    if issues:
        raise TechnicalRepresentationError(rows, issues)


def build_tech_dataset(
    wmo: int,
    blocks: list[CycleTechnical] | None = None,
    *,
    records: list[Occurrence] | None = None,
    raw_dir: Path | None = None,
    cycles: set[int] | None = None,
    scalar_params: list[tuple[str, str, int]] | None = None,
    data_centre: str = "",
    date_creation: str | None = None,
) -> netCDF4.Dataset:
    """Construct an accumulating technical Dataset adhering to Coriolis routing.

    When ``raw_dir`` or ``records`` are supplied, numeric technical channels
    (Air Bladder, Battery Voltage, Internal Vacuum) are published as timeseries
    in ``N_TECH_MEASUREMENT``.
    """
    now = _now()
    created = date_creation or now

    # 1. Resolve numeric telemetry records
    all_records: list[Occurrence] = []
    if records is not None:
        all_records = records
    elif raw_dir is not None:
        all_records, _ = load_float_technical_records(raw_dir, cycles=cycles)

    tech_meas_rows: list[tuple[Occurrence, list[tuple[Any, float]]]] = []
    for r in all_records:
        if r.kind == "VITALS_CORE":
            tech_vals = [(c, v) for c, v in zip(CHANNELS, r.values) if c[3] == "TECH"]
            if tech_vals:
                tech_meas_rows.append((r, tech_vals))

    # 2. Resolve scalar technical rows
    rows: list[tuple[str, str, int]] = []
    if scalar_params is not None:
        rows = list(scalar_params)
        validate_technical_rows(rows)
    elif all_records or raw_dir is not None:
        # Extract valid scalar metrics from blocks if available
        if blocks:
            for b in sorted(blocks, key=lambda x: x.cycle):
                if getattr(b, "surface_offset", None) is not None:
                    rows.append(("PRES_SurfaceOffsetNotTruncated_dbar", f"{b.surface_offset:g}", b.cycle))
                if getattr(b, "piston_surface", None) is not None:
                    rows.append(("POSITION_PistonSurface_COUNT", str(b.piston_surface), b.cycle))
                if getattr(b, "park_samples", None) is not None:
                    rows.append(("NUMBER_ParkSamples_COUNT", str(b.park_samples), b.cycle))
            validate_technical_rows(rows)
    else:
        # Legacy/unit-test mode where only blocks are provided without telemetry
        if blocks:
            for block in sorted(blocks, key=lambda b: b.cycle):
                for name, value in block.rows():
                    rows.append((name, value, block.cycle))
            validate_technical_rows(rows)
            for block in blocks:
                if isinstance(block, CycleTechnical) and (
                    block.battery_voltage or block.internal_vacuum or block.battery_current
                    or block.piston_profile or block.piston_park or block.piston_surface is not None
                ):
                    raise TechnicalRepresentationError(rows, [
                        "legacy VITALS/display or piston-completion mapping is not a scalar contract; "
                        "use the provenance-aware numeric VITALS writer; piston completion remains blocked"
                    ])

    n_scalar_rows = len(rows)
    n_meas_rows = len(tech_meas_rows)

    # 3. Create Dataset
    ds = netCDF4.Dataset("inmemory", mode="w", format=APF11_NC_FORMAT, diskless=True)
    ds.createDimension("N_TECH_PARAM", None)  # unlimited
    ds.createDimension("STRING128", STRING128)
    ds.createDimension("STRING32", STRING32)
    ds.createDimension("STRING8", STRING8)
    ds.createDimension("STRING4", STRING4)
    ds.createDimension("STRING2", STRING2)
    ds.createDimension("DATE_TIME", DATE_TIME)

    if n_meas_rows > 0:
        ds.createDimension("N_TECH_MEASUREMENT", n_meas_rows)

    # Global attributes
    iso_created = f"{created[:4]}-{created[4:6]}-{created[6:8]}T{created[8:10]}:{created[10:12]}:{created[12:14]}Z"
    iso_now = f"{now[:4]}-{now[4:6]}-{now[6:8]}T{now[8:10]}:{now[10:12]}:{now[12:14]}Z"
    ds.setncattr("title", "Argo float technical data file")
    institution = DAC_INSTITUTION.get(data_centre, data_centre) if data_centre else ""
    ds.setncattr("institution", institution)
    ds.setncattr("source", "Argo float")
    ds.setncattr("history", f"{iso_created} creation;{iso_now} update")
    ds.setncattr("references", "http://www.argodatamgt.org/Documentation")
    ds.setncattr("comment", "")
    ds.setncattr("user_manual_version", "3.1")
    ds.setncattr("Conventions", "Argo-3.1 CF-1.6")
    ds.setncattr("featureType", "trajectoryProfile")

    # General variables
    _write_str_char(ds, "DATE_CREATION", "DATE_TIME", created)
    _write_str_char(ds, "DATE_UPDATE", "DATE_TIME", now)
    _write_str_char(ds, "PLATFORM_NUMBER", "STRING8", str(wmo))
    _write_str_char(ds, "DATA_CENTRE", "STRING2", data_centre)

    dt = ds.createVariable("DATA_TYPE", "S1", ("STRING32",), fill_value=" ")
    data = np.zeros((STRING32,), dtype="S1")
    raw = b"Argo technical data"
    data[: len(raw)] = np.frombuffer(raw, dtype="S1")
    data[len(raw) :] = b" "
    dt[:] = data
    dt.setncattr("long_name", "Data type")
    dt.setncattr("conventions", "Argo reference table 1")

    fv = ds.createVariable("FORMAT_VERSION", "S1", ("STRING4",), fill_value=" ")
    arr = np.zeros((STRING4,), dtype="S1")
    arr[:] = b" "
    raw = b"3.1"
    arr[:3] = np.frombuffer(raw, dtype="S1")
    fv[:] = arr
    fv.setncattr("long_name", "File format version")

    hv = ds.createVariable("HANDBOOK_VERSION", "S1", ("STRING4",), fill_value=" ")
    arr = np.zeros((STRING4,), dtype="S1")
    arr[:] = b" "
    raw = b"1.2"
    arr[1:4] = np.frombuffer(raw, dtype="S1")
    hv[:] = arr
    hv.setncattr("long_name", "Data handbook version")

    ds["PLATFORM_NUMBER"].setncattr("long_name", "Float unique identifier")
    ds["PLATFORM_NUMBER"].setncattr("conventions", "WMO float identifier : A9IIIII")
    ds["DATA_CENTRE"].setncattr("long_name", "Data centre in charge of float data processing")
    ds["DATA_CENTRE"].setncattr("conventions", "Argo reference table 4")
    ds["DATE_CREATION"].setncattr("long_name", "Date of file creation")
    ds["DATE_CREATION"].setncattr("conventions", "YYYYMMDDHHMISS")
    ds["DATE_UPDATE"].setncattr("long_name", "Date of update of this file")
    ds["DATE_UPDATE"].setncattr("conventions", "YYYYMMDDHHMISS")

    # Scalar section
    name_var = ds.createVariable("TECHNICAL_PARAMETER_NAME", "S1", ("N_TECH_PARAM", "STRING128"), fill_value=" ")
    value_var = ds.createVariable("TECHNICAL_PARAMETER_VALUE", "S1", ("N_TECH_PARAM", "STRING128"), fill_value=" ")
    cyc_var = ds.createVariable("CYCLE_NUMBER", "i4", ("N_TECH_PARAM",), fill_value=np.int32(INT_FILL))
    name_var.setncattr("long_name", "Name of technical parameter")
    value_var.setncattr("long_name", "Value of technical parameter")
    cyc_var.setncattr("long_name", "Float cycle number")
    cyc_var.setncattr("conventions", "0...N, 0 : launch cycle (if exists), 1 : first complete cycle")

    if n_scalar_rows > 0:
        name_mat = np.full((n_scalar_rows, STRING128), b" ", dtype="S1")
        value_mat = np.full((n_scalar_rows, STRING128), b" ", dtype="S1")
        cyc_col = np.full(n_scalar_rows, INT_FILL, dtype=np.int32)
        for i, (pname, pval, pcycle) in enumerate(rows):
            nb = pname.encode("ascii")
            vb = pval.encode("ascii")
            name_mat[i, : len(nb)] = np.frombuffer(nb, dtype="S1")
            value_mat[i, : len(vb)] = np.frombuffer(vb, dtype="S1")
            cyc_col[i] = np.int32(pcycle)
        name_var[:] = name_mat
        value_var[:] = value_mat
        cyc_var[:] = cyc_col

    # Numeric timeseries section
    if n_meas_rows > 0:
        juld = ds.createVariable("JULD", "f8", ("N_TECH_MEASUREMENT",), fill_value=DOUBLE_FILL)
        juld.setncatts({
            "long_name": "Julian day (UTC) of each measurement",
            "standard_name": "time",
            "units": "days since 1950-01-01 00:00:00 UTC",
            "conventions": "Relative julian days with decimal part (as parts of day)",
            "axis": "T",
        })

        cy_meas = ds.createVariable("CYCLE_NUMBER_MEAS", "i4", ("N_TECH_MEASUREMENT",), fill_value=INT_FILL)
        cy_meas.setncatts({
            "long_name": "Float cycle number of the measurement",
            "conventions": "0...N, 0 : launch cycle, 1 : first complete cycle",
        })

        meas_code = ds.createVariable("MEASUREMENT_CODE", "i4", ("N_TECH_MEASUREMENT",), fill_value=INT_FILL)
        meas_code.setncatts({
            "long_name": "Flag referring to a measurement event in the cycle",
            "conventions": "Argo reference table 15",
        })

        v_air = ds.createVariable("PRESSURE_AirBladder", "f4", ("N_TECH_MEASUREMENT",), fill_value=FLOAT_FILL)
        v_air.setncatts({"long_name": "Air bladder pressure", "units": "dbar"})

        v_bat = ds.createVariable("VOLTAGE_Battery", "f4", ("N_TECH_MEASUREMENT",), fill_value=FLOAT_FILL)
        v_bat.setncatts({"long_name": "battery voltage when battery capacity is unknown", "units": "volts"})

        v_vac = ds.createVariable("PRESSURE_InternalVacuum", "f4", ("N_TECH_MEASUREMENT",), fill_value=FLOAT_FILL)
        v_vac.setncatts({"long_name": "Internal vacuum pressure", "units": "dbar"})

        for idx, (occ, vals) in enumerate(tech_meas_rows):
            juld[idx] = occ.juld
            cy_meas[idx] = occ.cycle
            for (lookup, name, unit, route), val in vals:
                ds[name][idx] = np.float32(val)

    return ds


def write_tech_file(
    path: Path,
    wmo: int,
    blocks: list[CycleTechnical] | None = None,
    *,
    records: list[Occurrence] | None = None,
    raw_dir: Path | None = None,
    cycles: set[int] | None = None,
    scalar_params: list[tuple[str, str, int]] | None = None,
    data_centre: str = "",
    date_creation: str | None = None,
    write_receipt: bool = True,
) -> Path:
    """Write an accumulating ``<WMO>_tech.nc`` file in NetCDF-3 Classic format."""
    all_records: list[Occurrence] = []
    all_blocked: list[dict] = []
    if records is not None:
        all_records = records
    elif raw_dir is not None:
        all_records, all_blocked = load_float_technical_records(raw_dir, cycles=cycles)

    ds = build_tech_dataset(
        wmo,
        blocks,
        records=all_records,
        raw_dir=None,
        cycles=cycles,
        scalar_params=scalar_params,
        data_centre=data_centre,
        date_creation=date_creation,
    )

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = netCDF4.Dataset(str(path), mode="w", format=APF11_NC_FORMAT)
    try:
        for dim, d in ds.dimensions.items():
            out.createDimension(dim, None if d.isunlimited() else d.size)
        for name, var in ds.variables.items():
            kwargs = {}
            if "_FillValue" in var.ncattrs():
                kwargs["fill_value"] = var.getncattr("_FillValue")
            nv = out.createVariable(name, var.datatype, var.dimensions, **kwargs)
            for a in var.ncattrs():
                if a == "_FillValue":
                    continue
                nv.setncattr(a, var.getncattr(a))
            nv[:] = var[:]
        for a in ds.ncattrs():
            out.setncattr(a, ds.getncattr(a))
    finally:
        out.close()
        ds.close()

    # Write accompanying technical receipt when telemetry occurrences are present
    if write_receipt and all_records:
        receipt_path = path.parent / f"{wmo}_technical_receipt.json.gz"
        links = []
        rec_idx = 0
        for occ in all_records:
            if occ.kind == "VITALS_CORE":
                for (lookup, name, unit, route), val in zip(CHANNELS, occ.values):
                    if route == "TECH":
                        links.append({
                            "source": occ.receipt(),
                            "lookup": lookup,
                            "parameter": name,
                            "unit": unit,
                            "value": float(val),
                            "JULD": occ.juld,
                            "MC": None,
                            "output": path.name,
                            "record": rec_idx,
                        })
                    elif route == "BLOCKED":
                        all_blocked.append({
                            "occurrence": occ.receipt(),
                            "lookup": lookup,
                            "value": float(val),
                            "reason": "unit conflict across authorities; retained without assertion",
                        })
                rec_idx += 1

        receipt = {
            "status": "STANDARD_TECH_ONLY",
            "mapping_commit": "d4069390b21fe1e144fde6c503c99dcf03371177",
            "precision": "NC_FLOAT; exact native values; proved CSV companions retain original text",
            "MC_policy": "fill; no anchor association invented",
            "source_occurrences": len(all_records),
            "links": links,
            "blocked": all_blocked,
            "products": [{"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}],
        }
        receipt_path.write_bytes(gzip.compress(json.dumps(receipt, separators=(",", ":")).encode(), mtime=0))

    return path


__all__ = ["build_tech_dataset", "write_tech_file"]
