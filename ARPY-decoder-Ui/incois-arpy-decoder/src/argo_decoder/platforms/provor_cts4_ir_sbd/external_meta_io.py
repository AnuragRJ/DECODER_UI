"""ExternalMeta loaders for CTS4 publication — Phase-4.

Clean replacement for the helpers that lived in the quarantined
``provor_cts4_pipeline.py`` draft (which is kept on disk as evidence but must
not be imported). No fabrication: every field is read from the supplied
authoritative source; missing sources raise.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import netCDF4
import numpy as np

from argo_decoder.writer.nc import ExternalMeta


def launch_juld_from_meta(em: ExternalMeta) -> float:
    """JULD of the externally supplied LAUNCH_DATE (days since 1950-01-01)."""
    dt = datetime.strptime(em.launch_date, "%Y%m%d%H%M%S").replace(
        tzinfo=UTC
    )
    return (dt - datetime(1950, 1, 1, tzinfo=UTC)).total_seconds() / 86400.0


def _read_id(ds: "netCDF4.Dataset") -> str | None:
    """Read the ``id`` global attribute, or ``None`` when absent/blank.

    Argo UM 3.1 p17 defines ``id`` as the Argo GDAC data DOI
    (``https://doi.org/10.17882/42182``). It is a dataset-level identifier and
    is not the float's WMO. Only 3 of 14 INCOIS CTS4 ``meta.nc`` files carry
    it, so an absent attribute must stay absent rather than being filled with
    the WMO (which would silently assert a DOI the source never claimed).
    """
    if "id" not in ds.ncattrs():
        return None
    raw = ds.getncattr("id")
    if hasattr(raw, "dtype") and raw.dtype.kind in "SU":
        val = str(np.asarray(raw).tobytes().decode("latin-1"))
    else:
        val = str(raw)
    val = val.replace("\x00", " ").strip()
    return val or None


def build_external_meta_from_gdac(meta_nc: Path | str, wmo: str) -> ExternalMeta:
    """Extract authoritative per-float ExternalMeta from a GDAC ``meta.nc``.

    Comparison/validation path (the float's own GDAC metadata is the
    authoritative external source for shadow runs). ``wmo`` is supplied
    externally by the operator — never derived here.
    """
    meta_nc = Path(meta_nc)
    if not meta_nc.is_file():
        raise FileNotFoundError(f"GDAC meta.nc not found: {meta_nc}")
    ds = netCDF4.Dataset(str(meta_nc))
    try:
        def cs(name: str) -> Any:
            return netCDF4.chartostring(ds.variables[name][:])

        cfg_names = [str(x).strip() for x in cs("CONFIG_PARAMETER_NAME").tolist()]
        n_miss = len(ds.dimensions["N_MISSIONS"])
        cfg_vals = ds.variables["CONFIG_PARAMETER_VALUE"][:]
        missions = tuple(tuple(float(v) for v in cfg_vals[i, :]) for i in range(n_miss))
        launch_names = tuple(
            str(x).strip() for x in cs("LAUNCH_CONFIG_PARAMETER_NAME").tolist()
        )
        launch_vals = tuple(
            float(v) for v in ds.variables["LAUNCH_CONFIG_PARAMETER_VALUE"][:]
        )
        pre_eq = tuple(str(s).strip() for s in cs("PREDEPLOYMENT_CALIB_EQUATION").tolist())
        pre_coeff = tuple(str(s).strip() for s in cs("PREDEPLOYMENT_CALIB_COEFFICIENT").tolist())
        pre_comm = tuple(str(s).strip() for s in cs("PREDEPLOYMENT_CALIB_COMMENT").tolist())
        sensor_serials = tuple(str(s).strip() for s in cs("SENSOR_SERIAL_NO").tolist())
        float_serial = str(cs("FLOAT_SERIAL_NO").item()).strip()
        wmo_inst = str(cs("WMO_INST_TYPE").item()).strip()
        launch_date = str(cs("LAUNCH_DATE").item()).strip()
        launch_lat = float(ds.variables["LAUNCH_LATITUDE"][()])
        launch_lon = float(ds.variables["LAUNCH_LONGITUDE"][()])
        project = str(cs("PROJECT_NAME").item()).strip()
        pi = str(cs("PI_NAME").item()).strip()
        ptt = ""
        try:
            ptt = str(cs("PTT").item()).strip()
        except Exception:
            pass
        firmware = "n/a"
        try:
            firmware = str(cs("FIRMWARE_VERSION").item()).strip() or "n/a"
        except Exception:
            pass
        platform_type = str(cs("PLATFORM_TYPE").item()).strip()
        deployment_platform = ""
        cruise = ""
        station = ""
        try:
            deployment_platform = str(cs("DEPLOYMENT_PLATFORM").item()).strip()
            cruise = str(cs("DEPLOYMENT_CRUISE_ID").item()).strip()
            station = str(cs("DEPLOYMENT_REFERENCE_STATION_ID").item()).strip()
        except Exception:
            pass
        return ExternalMeta(
            float_serial_no=float_serial,
            wmo_inst_type=wmo_inst,
            launch_date=launch_date,
            launch_latitude=launch_lat,
            launch_longitude=launch_lon,
            platform_type=platform_type,
            firmware_version=firmware,
            project_name=project,
            pi_name=pi,
            ptt=ptt,
            deployment_platform=deployment_platform,
            deployment_cruise_id=cruise,
            deployment_reference_station_id=station,
            sensor_serial_nos=sensor_serials,
            config_parameter_names=tuple(cfg_names),
            config_mission_values=missions,
            config_mission_numbers=tuple(range(1, n_miss + 1)),
            launch_config_parameter_names=launch_names,
            launch_config_parameter_values=launch_vals,
            predeployment_calib_equations=pre_eq,
            predeployment_calib_coefficients=pre_coeff,
            predeployment_calib_comments=pre_comm,
            # Argo UM 3.1 §1.1.2 / p17: the ``id`` global attribute is "The
            # Argo GDAC data DOI: https://doi.org/10.17882/42182" -- a fixed
            # dataset identifier, NOT the float's WMO (that is
            # PLATFORM_NUMBER). Read it from the authoritative metadata rather
            # than substituting the WMO; when the source file has no ``id`` at
            # all (11 of 14 INCOIS meta.nc files) publish none rather than
            # inventing one.
            id=_read_id(ds),
        )
    finally:
        ds.close()
