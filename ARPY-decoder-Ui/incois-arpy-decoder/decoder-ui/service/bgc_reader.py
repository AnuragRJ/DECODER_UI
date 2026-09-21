"""N_PROF-aware BGC (BR file) reader for 301 floats.

Parses a published ``BR<wmo>_<cyc>.nc`` file profile-by-profile: each profile
keeps its own STATION_PARAMETERS list, pressure grid, per-parameter series
with level QC, and the file's own units/long names. No parameter name, unit,
or scale is hardcoded — everything displayed downstream comes from here.

G2-signature flagging is purely observational: a file *matches the documented
G2 signature* when it has a non-standard layout (N_PROF != 4) AND at least one
profile whose labeled sensor channels are entirely fill. That is a statement
about file contents, verifiable by inspection; the causal explanation (writer
template masking in the frozen backend) lives in the audit report, not in
this data.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import netCDF4 as nc
import numpy as np


#: Core parameters are never treated as BGC sensor channels (rule-based, so a
#: future core-only profile can never be mislabeled BGC).
CORE_PARAMS = frozenset({"PRES", "TEMP", "PSAL"})


def _qc_char(val: Any) -> str:
    """Decodes one S1 QC element; masked (fill) levels read as "9" (missing).

    Calling `.tobytes()` on a masked element raises AttributeError, so the
    mask is tested first. Fill levels carry no measurement, hence QC 9 —
    never a fabricated good/bad flag.
    """
    try:
        if val is None or val is np.ma.masked:
            return "9"
        if isinstance(val, np.ma.MaskedArray) and bool(np.ma.getmaskarray(val).any()):
            return "9"
        raw = val.tobytes() if hasattr(val, "tobytes") else bytes(val)
        return raw.decode("ascii")
    except Exception:
        return "9"


def _col_floats(col: Any) -> list[float | None]:
    """One (N_LEVELS,) masked column -> floats with fill as None."""
    try:
        arr = np.asarray(col, dtype=float)
    except Exception:
        return [None] * len(col)
    mask = np.ma.getmaskarray(np.ma.asarray(col))
    out: list[float | None] = []
    for v, m in zip(arr.tolist(), mask.tolist()):
        if m or v is None or (isinstance(v, float) and (np.isnan(v) or abs(v) >= 99990.0)):
            out.append(None)
        else:
            out.append(float(v))
    return out


def _first_float(var: Any) -> float | None:
    try:
        if getattr(var, "ndim", 0) and var.shape and var.shape[0] > 0:
            v = var[0]
        else:
            v = var[...]
        if np.ma.is_masked(v):
            return None
        return float(v)
    except Exception:
        return None


def read_br_file(path: Path | str) -> dict[str, Any]:
    """Reads one BR file into header + per-profile BGC series.

    Returns ``{"n_prof", "cycle_number", "latitude", "longitude",
    "position_qc", "juld", "profiles", "matches_g2_signature"}`` where each
    profile is ``{"profile_index", "station_parameters", "levels_count",
    "sensor_data_present", "param_units", "param_labels", "samples"}`` and
    each sample is ``{"level", "PRES", <PARAM>, <PARAM>_QC, ...}``.
    Values are never rounded (BGC spans 1e-7..1e2); fill reads as None.
    """
    path = Path(path)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ds = nc.Dataset(path, "r")
        try:
            n_prof = len(ds.dimensions["N_PROF"]) if "N_PROF" in ds.dimensions else 0
            n_levels = len(ds.dimensions["N_LEVELS"]) if "N_LEVELS" in ds.dimensions else 0

            header = {
                "n_prof": n_prof,
                "cycle_number": None,
                "latitude": None,
                "longitude": None,
                "position_qc": "1",
                "juld": None,
            }
            if "CYCLE_NUMBER" in ds.variables:
                try:
                    header["cycle_number"] = int(_first_float(ds.variables["CYCLE_NUMBER"]))  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    pass
            for key, varname, limit in (
                ("latitude", "LATITUDE", 99990.0),
                ("longitude", "LONGITUDE", 99990.0),
                ("juld", "JULD", 999990.0),
            ):
                if varname in ds.variables:
                    v = _first_float(ds.variables[varname])
                    if v is not None and abs(v) < limit:
                        header[key] = round(v, 4)
            if "POSITION_QC" in ds.variables:
                var = ds.variables["POSITION_QC"]
                header["position_qc"] = _qc_char(var[0] if getattr(var, "ndim", 0) else var[...])

            if "STATION_PARAMETERS" in ds.variables:
                sp = nc.chartostring(ds.variables["STATION_PARAMETERS"][:]).tolist()
            else:
                sp = []
            pres_var = ds.variables.get("PRES")

            profiles: list[dict[str, Any]] = []
            for i in range(n_prof):
                params = [str(x).strip() for x in (sp[i] if i < len(sp) else [])]
                params = [p for p in params if p]
                sensor_params = [p for p in params if p not in CORE_PARAMS and p in ds.variables]

                pres_col = (
                    _col_floats(pres_var[i, :])
                    if pres_var is not None and len(pres_var.shape) > 1
                    else [None] * n_levels
                )
                series: dict[str, list[float | None]] = {}
                qcs: dict[str, list[str]] = {}
                units: dict[str, str] = {}
                labels: dict[str, str] = {}
                for pname in sensor_params:
                    var = ds.variables[pname]
                    series[pname] = (
                        _col_floats(var[i, :])
                        if len(var.shape) > 1
                        else _col_floats(var[:])
                    )
                    try:
                        units[pname] = str(var.getncattr("units"))
                    except Exception:
                        units[pname] = ""
                    try:
                        labels[pname] = str(var.getncattr("long_name"))
                    except Exception:
                        labels[pname] = pname
                    qc_var = ds.variables.get(f"{pname}_QC")
                    if qc_var is not None:
                        row = []
                        for lvl in range(n_levels):
                            try:
                                el = qc_var[i, lvl] if len(qc_var.shape) > 1 else qc_var[lvl]
                            except Exception:
                                row.append("9")
                                continue
                            row.append(_qc_char(el))
                        qcs[pname] = row
                    else:
                        # No QC published for this channel: "not assessed" is
                        # the true statement, never a plotted-as-good fake.
                        qcs[pname] = ["0"] * n_levels

                samples: list[dict[str, Any]] = []
                for lvl in range(n_levels):
                    row: dict[str, Any] = {"level": lvl + 1, "PRES": pres_col[lvl] if lvl < len(pres_col) else None}
                    for pname in sensor_params:
                        vals = series.get(pname, [])
                        row[pname] = vals[lvl] if lvl < len(vals) else None
                        q = qcs.get(pname, [])
                        row[f"{pname}_QC"] = q[lvl] if lvl < len(q) else "0"
                    samples.append(row)

                sensor_present = True
                if sensor_params:
                    sensor_present = any(
                        v is not None for pname in sensor_params for v in series.get(pname, [])
                    )
                profiles.append(
                    {
                        "profile_index": i,
                        "station_parameters": params,
                        "levels_count": n_levels,
                        "sensor_data_present": sensor_present,
                        "param_units": units,
                        "param_labels": labels,
                        "samples": samples,
                    }
                )

            matches_g2 = False
            if n_prof != 4:
                for prof, params in (
                    (prof, prof["station_parameters"]) for prof in profiles
                ):
                    labeled = [p for p in params if p not in CORE_PARAMS]
                    if labeled and not prof["sensor_data_present"]:
                        matches_g2 = True
                        break

            return {
                "n_prof": n_prof,
                "cycle_number": header["cycle_number"],
                "latitude": header["latitude"],
                "longitude": header["longitude"],
                "position_qc": header["position_qc"],
                "juld": header["juld"],
                "profiles": profiles,
                "matches_g2_signature": matches_g2,
            }
        finally:
            ds.close()
