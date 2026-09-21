"""Float Status: cached, verifiable Ifremer/Argo GDAC observations.

Communication: per-cycle JULD_LAST_MESSAGE, else JULD_TRANSMISSION_END only.
Location: newest QC 1/2 position across trajectory fixes (JULD), full profile
history and the latest file (JULD_LOCATION); source and position time exposed.
Prof#: highest published cycle. Available profiles: distinct positive cycles.
Missing profiles: directory gaps 1..Prof#, not communication or decoder errors.
Freshness is separate from float communication status. A successful check of
unchanged files renews checked_at, never the observation's timestamp.
See decoder-ui/FLEET_STATUS.md for the field contract and limitations.
"""

from __future__ import annotations

import asyncio
import copy
import ftplib
import hashlib
import json
import math
import os
import re
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

import netCDF4
import numpy as np
from event_bus import DATA_DIR

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

JULD_EPOCH = datetime(1950, 1, 1, tzinfo=UTC)
#: JULD values at/above this are fill (covers the writer 90000 convention and
#: the files' 999999 _FillValue).
FILL_JULD = 90000.0
# Future observations are rejected, including predicted trajectory events.

STATUS_ACTIVE = "ACTIVE"
STATUS_OVERDUE = "OVERDUE"
STATUS_NO_COMM_60 = "NO COMMUNICATION 60+ DAYS"
STATUS_NO_DATA = "NO DATA"

SYNC_OK = "ok"
SYNC_DEGRADED = "degraded"
SYNC_ERROR = "error"
SYNC_NEVER = "never-synced"
SYNC_DISABLED = "disabled"
SYNC_RUNNING = "running"

STATE_VERSION = 2
PARSER_VERSION = 2
COMMUNICATION_FIELDS = ("JULD_LAST_MESSAGE", "JULD_TRANSMISSION_END")
# Deliberately do not promote unassessed, bad or interpolated positions to a
# verified latest fix. RT2: 1 = good, 2 = probably good.
POSITION_QC_ACCEPTED = {"1", "2"}

#: Latest-profile preference when several families share the max cycle.
PROFILE_PREFIX_PRIORITY = ["D", "R", "BD", "BR", "SD", "SR"]

_LIST_RE = re.compile(
    r"^([bcdlps-][rwxstST-]{9})\s+\d+\s+\S+\s+\S+\s+(\d+)\s+"
    r"([A-Z][a-z]{2})\s+(\d{1,2})\s+(\d{4}|\d{1,2}:\d{2})\s+(\S.*?)\s*$"
)
_PROFILE_RE = re.compile(r"^(BD|BR|SD|SR|D|R)(\d{7})_(\d{3,4})(D?)\.nc$")
_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    )
}


class FloatSyncError(Exception):
    """Per-float refresh failure (keeps any previously cached row)."""


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


def juld_to_datetime(juld: float) -> datetime:
    """Argo JULD -> aware UTC, removing <1 ms floating-point second jitter."""
    seconds = float(juld) * 86400.0
    if abs(seconds - round(seconds)) < 0.001:
        seconds = float(round(seconds))
    return JULD_EPOCH + timedelta(seconds=seconds)


def juld_to_iso(juld: float) -> str:
    return juld_to_datetime(juld).isoformat()


def _parse_utc(value: Any) -> datetime | None:
    """Never interpret an unqualified cache timestamp in the server's timezone."""
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(UTC) if dt.tzinfo is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


def _age_seconds(value: Any, now: datetime) -> float | None:
    dt = _parse_utc(value)
    if dt is None or dt > now:
        return None
    return (now - dt).total_seconds()


def _valid_juld(value: Any, now: datetime) -> float | None:
    try:
        v = float(value)
        if not np.isfinite(v) or not 0 <= v < FILL_JULD:
            return None
        if juld_to_datetime(v) > now:
            return None
        return v
    except (TypeError, ValueError, OverflowError):
        return None


def comm_status(days_since: float | None) -> str:
    """Approved policy, on unrounded elapsed days; unavailable != inactive."""
    if days_since is None or not math.isfinite(days_since) or days_since < 0:
        return STATUS_NO_DATA
    if days_since <= 10:
        return STATUS_ACTIVE
    if days_since < 60:
        return STATUS_OVERDUE
    return STATUS_NO_COMM_60


def parse_list_line(line: str, now: datetime | None = None) -> tuple[str, int, float, bool] | None:
    """Parse one Unix-style FTP LIST line -> (name, size, mtime_epoch, is_dir).

    The mtime is used ONLY for change fingerprints, never displayed as data.
    Returns None for unparsable lines ("total ..." headers, blanks).
    """
    m = _LIST_RE.match(line.strip())
    if not m:
        return None
    perms, size_s, mon_s, day_s, year_or_time, name = m.groups()
    try:
        size = int(size_s)
        month = _MONTHS[mon_s]
        day = int(day_s)
    except (KeyError, ValueError):
        return None
    now = now or _utcnow()
    if ":" in year_or_time:
        hh, mm = year_or_time.split(":")
        try:
            dt = datetime(now.year, month, day, int(hh), int(mm), tzinfo=UTC)
        except ValueError:
            return None
        if dt > now + timedelta(days=1):
            # Recent-mtime form with an implied year belongs to last year.
            try:
                dt = datetime(now.year - 1, month, day, int(hh), int(mm), tzinfo=UTC)
            except ValueError:
                return None
    else:
        try:
            dt = datetime(int(year_or_time), month, day, tzinfo=UTC)
        except ValueError:
            return None
    return (name, size, dt.timestamp(), perms[0] == "d")


def listing_fingerprint(entries: list[tuple[str, int, float]]) -> str:
    """Stable sha1 over sorted (name, size, mtime) triples."""
    h = hashlib.sha1()
    for name, size, mtime in sorted(entries):
        h.update(f"{name}\t{size}\t{mtime:.0f}\n".encode())
    h.update(f"n={len(entries)}".encode())
    return h.hexdigest()


def summarize_profiles(filenames: list[str], wmo: int) -> dict[str, Any]:
    """Prof# is the highest published cycle, NOT the available-profile count.

    Count distinct positive cycles across only official R/D/BR/BD/SR/SD
    families, including descent suffix D and four-digit cycles. A BGC sensor
    grid or an additional family/direction is not another missing/present
    cycle. Gaps mean absent files in 1..max, not missing communications or
    failed decoder jobs. No later cycles are invented from trajectory data.
    """
    cycles: dict[int, list[tuple[str, str]]] = {}
    n_files = 0
    for fn in sorted(set(filenames)):
        m = _PROFILE_RE.fullmatch(fn)
        if not m or int(m.group(2)) != int(wmo):
            continue
        n_files += 1
        cycles.setdefault(int(m.group(3)), []).append((m.group(1), fn))
    if not cycles:
        return {
            "max_cycle": None,
            "missing": [],
            "n_files": n_files,
            "latest": None,
            "listing_cycles": 0,
            "available_cycles": 0,
        }
    max_cycle = max(cycles)
    missing = [c for c in range(1, max_cycle + 1) if c not in cycles]
    # Preserve the actual filename (padding and descent suffix included).
    prefix, filename = min(
        cycles[max_cycle],
        key=lambda x: (PROFILE_PREFIX_PRIORITY.index(x[0]), x[1].endswith("D.nc"), x[1]),
    )
    return {
        "max_cycle": max_cycle,
        "missing": missing,
        "n_files": n_files,
        "listing_cycles": len(cycles),
        "available_cycles": sum(c > 0 for c in cycles),
        "latest": {"prefix": prefix, "cycle": max_cycle, "file": filename},
    }


# -- netCDF4 reading ---------------------------------------------------------


def _farr(var: Any) -> np.ndarray:
    """Preserve masks even on integer variables before converting fill to NaN."""
    try:
        return np.ma.asarray(var[:], dtype=float).filled(np.nan).ravel()
    except (ValueError, TypeError, IndexError):
        return np.array([], dtype=float)


def _char_at(var: Any, i: int) -> str:
    try:
        v = var[i]
        if np.ma.is_masked(v):
            return ""
        item = np.asarray(v).ravel()[0].item()
        return (
            item.decode(errors="replace").strip() if isinstance(item, bytes) else str(item).strip()
        )
    except (ValueError, TypeError, IndexError):
        return ""


def _flags(ds: netCDF4.Dataset, name: str) -> np.ndarray:
    if name not in ds.variables:
        return np.array([], dtype="U1")
    return np.ma.filled(ds.variables[name][:], b" ").astype("U1").ravel()


def _texts(ds: netCDF4.Dataset, name: str) -> list[str]:
    if name not in ds.variables:
        return []
    a = np.ma.asarray(ds.variables[name][:])
    if a.dtype.kind == "S" and a.dtype.itemsize == 1:
        a = np.ma.filled(a, b" ")
        rows = a.reshape((-1, a.shape[-1])) if a.ndim > 1 else [a]
        return [np.asarray(row).tobytes().decode(errors="replace").strip(" \x00") for row in rows]
    return [str(v).strip(" \x00") for v in np.ma.filled(a, "").ravel()]


def _scalar_text(ds: netCDF4.Dataset, name: str) -> str:
    return next(iter(_texts(ds, name)), "")


def _check_platform(ds: netCDF4.Dataset, wmo: int, product: str) -> None:
    values = _texts(ds, "PLATFORM_NUMBER")
    if not values or any(value != str(wmo) for value in values):
        raise FloatSyncError(f"{product} PLATFORM_NUMBER missing or does not match WMO {wmo}")


def _julds(ds: netCDF4.Dataset, name: str) -> np.ndarray:
    if name not in ds.variables:
        return np.array([], dtype=float)
    var = ds.variables[name]
    units = " ".join(str(getattr(var, "units", "")).lower().split())
    # Argo's documented epoch; do not silently interpret a foreign time axis.
    valid_units = {
        "days since 1950-01-01 00:00:00 utc",
        "days since 1950-01-01 00:00:00",
        "days since 1950-01-01",
        "days since 1950-01-01 00:00:00z",
    }
    if units not in valid_units:
        raise FloatSyncError(f"{name} has absent/unsupported time units: {units!r}")
    if str(getattr(var, "calendar", "standard")).lower() not in {
        "standard",
        "gregorian",
        "proleptic_gregorian",
    }:
        raise FloatSyncError(f"{name} has an unsupported calendar")
    return _farr(var)


def _int_at(values: np.ndarray, i: int) -> int | None:
    if i < values.size and np.isfinite(values[i]) and 0 <= values[i] < 99999:
        return int(values[i]) if values[i] == int(values[i]) else None
    return None


def _position_ok(lat: Any, lon: Any, qc: Any) -> bool:
    try:
        return (
            qc in POSITION_QC_ACCEPTED
            and np.isfinite(float(lat))
            and np.isfinite(float(lon))
            and abs(float(lat)) <= 90
            and abs(float(lon)) <= 180
        )
    except (TypeError, ValueError):
        return False


def parse_rtraj(raw: bytes, wmo: int, now: datetime | None = None) -> dict[str, Any]:
    """Parse only genuine per-cycle communication fields; retain independent
    position data even when no communication evidence exists (legacy files).
    Measurement JULD, profile time, mtime and processing time are NEVER used
    as last transmission. Missing communication is NO DATA, not a sync error.
    """
    now = now or _utcnow()
    try:
        ds = netCDF4.Dataset(f"{wmo}_Rtraj.nc", memory=bytes(raw))
    except Exception as exc:
        raise FloatSyncError(f"Rtraj unreadable: {exc}") from exc
    try:
        _check_platform(ds, wmo, "Rtraj")
        out: dict[str, Any] = {
            "platform_number": str(wmo),
            "last_tx_juld": None,
            "last_tx_iso": None,
            "last_tx_field": None,
            "last_tx_status_rt19": "",
            "last_tx_index": None,
            "last_tx_cycle": None,
            "communication_error": None,
        }
        cycle_index = (
            _farr(ds.variables["CYCLE_NUMBER_INDEX"])
            if "CYCLE_NUMBER_INDEX" in ds.variables
            else np.array([])
        )
        for field in COMMUNICATION_FIELDS:
            if field not in ds.variables:
                continue
            if ds.variables[field].dimensions != ("N_CYCLE",):
                raise FloatSyncError(f"{field} is not a per-cycle communication field")
            arr = _julds(ds, field)
            valid = [(i, float(v)) for i, v in enumerate(arr) if _valid_juld(v, now) is not None]
            if not valid:
                continue
            i, value = max(valid, key=lambda item: item[1])
            status_var = ds.variables.get(f"{field}_STATUS")
            out.update(
                last_tx_juld=value,
                last_tx_iso=juld_to_iso(value),
                last_tx_field=field,
                last_tx_index=i,
                last_tx_cycle=_int_at(cycle_index, i),
                last_tx_status_rt19=_char_at(status_var, i) if status_var is not None else "",
                last_tx_units=str(ds.variables[field].units),
                last_tx_long_name=str(getattr(ds.variables[field], "long_name", "")),
            )
            break
        if out["last_tx_iso"] is None:
            out["communication_error"] = (
                "No valid JULD_LAST_MESSAGE or JULD_TRANSMISSION_END in upstream Rtraj; "
                "measurement/profile JULD is not communication evidence."
            )
        nums: list[int] = []
        for name in ("CYCLE_NUMBER_INDEX", "CYCLE_NUMBER"):
            if name in ds.variables:
                nums.extend(
                    int(v)
                    for v in _farr(ds.variables[name])
                    if np.isfinite(v) and 0 <= v < 99999 and v == int(v)
                )
        out["traj_max_cycle"] = max(nums) if nums else None
        out["last_fix"] = None
        juld = _julds(ds, "JULD")
        lat = _farr(ds.variables["LATITUDE"]) if "LATITUDE" in ds.variables else np.array([])
        lon = _farr(ds.variables["LONGITUDE"]) if "LONGITUDE" in ds.variables else np.array([])
        cyc = (
            _farr(ds.variables["CYCLE_NUMBER"]) if "CYCLE_NUMBER" in ds.variables else np.array([])
        )
        mc = (
            _farr(ds.variables["MEASUREMENT_CODE"])
            if "MEASUREMENT_CODE" in ds.variables
            else np.array([])
        )
        qc_values = _flags(ds, "POSITION_QC")
        for i in range(min(juld.size, lat.size, lon.size)):
            value = _valid_juld(juld[i], now)
            qc = str(qc_values[i]) if i < qc_values.size else ""
            if value is None or not _position_ok(lat[i], lon[i], qc):
                continue
            if out["last_fix"] is not None and value <= out["last_fix"]["juld"]:
                continue
            out["last_fix"] = {
                "juld": value,
                "juld_iso": juld_to_iso(value),
                "lat": float(lat[i]),
                "lon": float(lon[i]),
                "cycle": _int_at(cyc, i),
                "mc": _int_at(mc, i),
                "pos_qc": qc,
                "index": i,
                "time_field": "JULD",
            }
        return out
    finally:
        ds.close()


def parse_profile(
    raw: bytes, wmo: int, filename_cycle: int | None, now: datetime | None = None
) -> dict[str, Any]:
    """Coherent N_PROF row: position uses JULD_LOCATION, not profile JULD.

    filename_cycle=None reads the full <wmo>_prof.nc history without assuming
    cycle numbers are chronological (resets and repeated sensor rows exist).
    Profile JULD remains separate measurement evidence only. Never assemble
    a coordinate pair from different rows, accept bad QC, or trust a foreign
    WMO. A missing location timestamp cannot establish the latest position.
    """
    now = now or _utcnow()
    try:
        ds = netCDF4.Dataset(f"latest_{wmo}.nc", memory=bytes(raw))
    except Exception as exc:
        raise FloatSyncError(f"profile file unreadable: {exc}") from exc
    try:
        _check_platform(ds, wmo, "profile")
        out: dict[str, Any] = {
            "platform_number": str(wmo),
            "juld": None,
            "juld_iso": None,
            "lat": None,
            "lon": None,
            "pos_qc": "",
            "cycle": None,
            "cycle_mismatch": False,
            "position_juld": None,
            "position_iso": None,
            "position_time_field": "JULD_LOCATION",
            "position_index": None,
            "position_error": None,
        }
        j = _julds(ds, "JULD")
        loc = _julds(ds, "JULD_LOCATION")
        lat = _farr(ds.variables["LATITUDE"]) if "LATITUDE" in ds.variables else np.array([])
        lon = _farr(ds.variables["LONGITUDE"]) if "LONGITUDE" in ds.variables else np.array([])
        cyc = (
            _farr(ds.variables["CYCLE_NUMBER"]) if "CYCLE_NUMBER" in ds.variables else np.array([])
        )
        qc_values = _flags(ds, "POSITION_QC")
        valid_j = [(i, float(v)) for i, v in enumerate(j) if _valid_juld(v, now) is not None]
        measured = max(valid_j, key=lambda item: item[1]) if valid_j else None
        known_cycles = [int(v) for v in cyc if np.isfinite(v) and 0 <= v < 99999]
        out["cycle"] = _int_at(cyc, 0)
        out["cycle_mismatch"] = filename_cycle is not None and any(
            c != filename_cycle for c in known_cycles
        )
        candidates = []
        for i in range(min(loc.size, lat.size, lon.size)):
            value = _valid_juld(loc[i], now)
            qc = str(qc_values[i]) if i < qc_values.size else ""
            if (
                value is not None
                and not out["cycle_mismatch"]
                and _position_ok(lat[i], lon[i], qc)
                and _int_at(cyc, i) is not None
                and (filename_cycle is None or _int_at(cyc, i) == filename_cycle)
            ):
                candidates.append((i, value, qc))
        if candidates:
            i, value, qc = max(candidates, key=lambda item: item[1])
            out.update(
                lat=float(lat[i]),
                lon=float(lon[i]),
                pos_qc=qc,
                position_juld=value,
                position_iso=juld_to_iso(value),
                position_index=i,
                cycle=_int_at(cyc, i),
            )
        else:
            flags = sorted(set(qc_values.tolist()))
            out["position_qc_observed"] = flags
            out["position_error"] = (
                "Profile position unavailable: require a matching cycle, "
                "paired finite coordinates, POSITION_QC 1/2 and a valid JULD_LOCATION "
                f"(QC present: {','.join(flags) or 'none'})."
            )
        if measured:
            i, value = measured
            out.update(
                juld=value,
                juld_iso=juld_to_iso(value),
                measurement_index=i,
                measurement_cycle=_int_at(cyc, i),
            )
            if out["cycle"] is None:
                out["cycle"] = _int_at(cyc, i)
        return out
    finally:
        ds.close()


# ---------------------------------------------------------------------------
# FTP layer (anonymous; no credentials anywhere)
# ---------------------------------------------------------------------------


def ftp_membership(ftp: ftplib.FTP, dac_dir: str) -> set[str]:
    """WMO directory names present under the DAC dir (single NLIST)."""
    try:
        names = ftp.nlst(dac_dir)
    except ftplib.error_perm as exc:
        raise FloatSyncError(f"DAC listing failed: {exc}") from exc
    out = set()
    for n in names:
        base = n.rsplit("/", 1)[-1].strip()
        if base and base not in (".", ".."):
            out.add(base)
    members = {n for n in out if re.fullmatch(r"\d{7}", n)}
    if not members:
        raise FloatSyncError(
            "DAC listing contains no valid WMO directories; membership is unverified"
        )
    return members


def ftp_file_stat(ftp: ftplib.FTP, path: str) -> tuple[int | None, str | None]:
    """(size, MDTM 'YYYYMMDDHHMMSS') — each None-tolerant."""
    size: int | None = None
    try:
        size = ftp.size(path)
    except Exception:
        pass
    mdtm: str | None = None
    try:
        resp = ftp.sendcmd(f"MDTM {path}")
        if resp.startswith("213"):
            mdtm = resp[4:].strip()
    except Exception:
        pass
    return size, mdtm


def ftp_list_entries(ftp: ftplib.FTP, path: str) -> list[tuple[str, int, float]]:
    """Files (not dirs) in a remote dir as (name, size, mtime_epoch)."""
    lines: list[str] = []
    ftp.retrlines(f"LIST {path}", lines.append)
    now = _utcnow()
    out = []
    for ln in lines:
        parsed = parse_list_line(ln, now)
        if parsed is None:
            if ln.strip() and not re.fullmatch(r"total\s+\d+", ln.strip()):
                raise FloatSyncError(
                    "Unparseable profiles LIST response; refusing an incomplete inventory"
                )
            continue
        name, size, mtime, is_dir = parsed
        if not is_dir:
            out.append((name, size, mtime))
    return out


def ftp_retrieve(ftp: ftplib.FTP, path: str) -> bytes:
    buf = BytesIO()
    ftp.retrbinary(f"RETR {path}", buf.write, blocksize=1024 * 1024)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Sync registry (mirrors ingestion.py lifecycle)
# ---------------------------------------------------------------------------

FleetFn = Callable[[], list[dict[str, Any]]]


def _default_fleet() -> list[dict[str, Any]]:
    import path_resolver

    return path_resolver.build_dynamic_float_presets()


class FleetSyncRegistry:
    """Periodic Ifremer GDAC sync + cache + serve-time derivation."""

    def __init__(
        self,
        state_path: Path | None = None,
        fleet_fn: FleetFn | None = None,
        host: str | None = None,
        port: int | None = None,
        root: str | None = None,
        timeout_s: float | None = None,
        interval_s: float | None = None,
        enabled: bool | None = None,
    ) -> None:
        self._state_path = state_path or (DATA_DIR / "fleet_status" / "cache.json")
        self._fleet_fn = fleet_fn or _default_fleet
        self._host = host or os.environ.get("FLEET_FTP_HOST", "ftp.ifremer.fr")
        self._port = port or int(os.environ.get("FLEET_FTP_PORT", "21"))
        self._root = (root or os.environ.get("FLEET_FTP_ROOT", "/ifremer/argo")).rstrip("/") or "/"
        self._timeout = timeout_s or float(os.environ.get("FLEET_FTP_TIMEOUT_S", "30"))
        requested_interval = (
            interval_s
            if interval_s is not None
            else float(os.environ.get("FLEET_SYNC_INTERVAL_S", "21600"))
        )
        self._interval = (
            max(float(requested_interval), 300.0)
            if math.isfinite(float(requested_interval))
            else 21600.0
        )
        self._enabled = (
            (os.environ.get("FLEET_SYNC_ENABLED", "1") != "0") if enabled is None else enabled
        )
        self._rows: dict[str, dict[str, Any]] = {}
        self._sync: dict[str, Any] = {
            "status": SYNC_NEVER,
            "last_attempt_at": None,
            "last_success_at": None,
            "error": None,
            "counts": {},
            "duration_s": None,
            "last_completed_at": None,
            "persistence_error": None,
        }
        self._lock = threading.Lock()
        self._running = False
        self._progress = {"done": 0, "total": 0}
        self._poll_task: asyncio.Task | None = None
        self._load()

    # -- config surface -------------------------------------------------
    @property
    def state_path(self) -> Path:
        return self._state_path

    @property
    def interval_s(self) -> float:
        return self._interval

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def source_info(self) -> dict[str, Any]:
        return {
            "host": self._host,
            "port": self._port,
            "root": self._root,
            "dac": "incois",
            "product": "dac/incois/<wmo>/<wmo>_Rtraj.nc",
            "field": "JULD_LAST_MESSAGE (JULD_TRANSMISSION_END only if unavailable)",
            "position_policy": (
                "Newest QC 1/2 trajectory JULD fix or JULD_LOCATION in full _prof.nc "
                "history / latest profile file; no local coordinates"
            ),
            "profile_policy": (
                "Prof# = highest published cycle; available = distinct positive cycles; "
                "missing = gaps in 1..Prof#"
            ),
            "interval_s": self._interval,
        }

    def is_running(self) -> bool:
        with self._lock:
            return self._running

    # -- persistence ----------------------------------------------------
    def _load(self) -> None:
        try:
            if not self._state_path.is_file():
                return
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or int(data.get("version") or 0) not in (
                1,
                STATE_VERSION,
            ):
                return
            rows = data.get("rows")
            if isinstance(rows, dict):
                self._rows = {str(k): v for k, v in rows.items() if isinstance(v, dict)}
            sync = data.get("sync")
            if isinstance(sync, dict):
                for k in (
                    "status",
                    "last_attempt_at",
                    "last_success_at",
                    "last_completed_at",
                    "error",
                    "counts",
                    "duration_s",
                    "persistence_error",
                ):
                    if k in sync:
                        self._sync[k] = sync[k]
                if self._sync.get("status") == SYNC_RUNNING:
                    # A crash mid-cycle must not wedge the status forever.
                    self._sync["status"] = SYNC_NEVER if not self._rows else SYNC_DEGRADED
        except Exception:
            self._rows, self._sync["status"] = {}, SYNC_NEVER

    def _save(self) -> bool:
        """Atomic cache commit. Never call an unpersisted refresh successful."""
        tmp = self._state_path.with_suffix(".json.tmp")
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                self._sync["persistence_error"] = None
                payload = {
                    "version": STATE_VERSION,
                    "rows": copy.deepcopy(self._rows),
                    "sync": dict(self._sync),
                }
            tmp.write_text(json.dumps(payload, allow_nan=False), encoding="utf-8")
            tmp.replace(self._state_path)
            return True
        except Exception as exc:
            with self._lock:
                self._sync["persistence_error"] = (
                    f"Cache persistence failed: {type(exc).__name__}: {exc}"
                )
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    # -- sync -----------------------------------------------------------
    def _begin(self) -> bool:
        with self._lock:
            if self._running or not self._enabled:
                return False
            self._running = True
            self._progress = {"done": 0, "total": 0}
            return True

    def try_begin(self) -> bool:
        """Atomic test-and-set for externally triggered cycles (manual POST).
        Returns False when a cycle is already in flight or sync is disabled
        (the caller must then NOT call run_cycle)."""
        return self._begin()

    def _end(self) -> None:
        with self._lock:
            self._running = False

    def sync_now(self) -> dict[str, Any]:
        """Run one full cycle in the calling thread (poll loop delegates via
        asyncio.to_thread). Returns immediately when a cycle is in flight."""
        if not self._begin():
            with self._lock:
                state = SYNC_DISABLED if not self._enabled else SYNC_RUNNING
            return {"accepted": False, "state": state}
        try:
            return self._cycle()
        finally:
            self._end()

    def run_cycle(self) -> dict[str, Any]:
        """Entry for already-begun cycles (manual POST trigger)."""
        try:
            return self._cycle()
        finally:
            self._end()

    def _connect(self) -> ftplib.FTP:
        ftp = ftplib.FTP(timeout=self._timeout)
        ftp.connect(self._host, self._port)
        ftp.login(user="anonymous", passwd="fleet-status@incois")
        return ftp

    def _cycle(self) -> dict[str, Any]:
        t0 = time.time()
        attempt_at = _utcnow().isoformat()
        with self._lock:
            self._sync["last_attempt_at"] = attempt_at
            self._sync["status"] = SYNC_RUNNING
            self._sync["error"] = None
        try:
            fleet = self._fleet_fn()
            wmos = sorted({int(f["wmo"]) for f in fleet if str(f.get("wmo", "")).isdigit()})
            if not wmos:
                raise FloatSyncError("local fleet is empty; no upstream records were checked")
        except Exception as exc:
            return self._fail(f"fleet list unavailable: {exc}", t0)
        with self._lock:
            self._progress = {"done": 0, "total": len(wmos)}
        try:
            ftp = self._connect()
        except Exception as exc:
            return self._fail(f"FTP {self._host}:{self._port} unreachable: {exc}", t0)
        try:
            try:
                members = ftp_membership(ftp, f"{self._root}/dac/incois")
            except Exception as exc:
                return self._fail(f"DAC listing failed: {exc}", t0)
            updated = unchanged = failed = 0
            for wmo in wmos:
                try:
                    changed = self._refresh_float(ftp, wmo, members)
                    if changed:
                        updated += 1
                    else:
                        unchanged += 1
                except FloatSyncError as exc:
                    failed += 1
                    self._record_float_error(
                        wmo,
                        str(exc) or "sync failed",
                        in_dac=(str(wmo) in members or wmo in members),
                    )
                except Exception as exc:  # never let one float kill the cycle
                    failed += 1
                    self._record_float_error(
                        wmo,
                        f"{type(exc).__name__}: {exc}",
                        in_dac=(str(wmo) in members or wmo in members),
                    )
                with self._lock:
                    self._progress["done"] += 1
            now_iso = _utcnow().isoformat()
            with self._lock:
                previous_success = self._sync.get("last_success_at")
                self._sync.update(
                    {
                        "status": SYNC_OK if failed == 0 else SYNC_DEGRADED,
                        "last_completed_at": now_iso,
                        "last_success_at": now_iso if failed == 0 else previous_success,
                        "error": None
                        if failed == 0
                        else f"{failed} float(s) failed refresh (kept last valid rows)",
                        "counts": {
                            "total": len(wmos),
                            "updated": updated,
                            "unchanged": unchanged,
                            "failed": failed,
                        },
                        "duration_s": round(time.time() - t0, 1),
                    }
                )
            if not self._save():
                with self._lock:
                    self._sync.update(
                        status=SYNC_DEGRADED,
                        last_success_at=previous_success,
                        error=self._sync["persistence_error"],
                    )
            return {
                "accepted": True,
                "status": self._sync["status"],
                "counts": dict(self._sync["counts"]),
            }
        finally:
            try:
                ftp.quit()
            except Exception:
                try:
                    ftp.close()
                except Exception:
                    pass

    def _fail(self, error: str, t0: float) -> dict[str, Any]:
        with self._lock:
            self._sync.update(
                {"status": SYNC_ERROR, "error": error, "duration_s": round(time.time() - t0, 1)}
            )
        self._save()
        return {"accepted": True, "status": SYNC_ERROR, "error": error}

    def _record_float_error(self, wmo: int, error: str, in_dac: bool | None = None) -> None:
        with self._lock:
            row = self._rows.get(str(wmo))
            if row is None:
                self._rows[str(wmo)] = {
                    "wmo": wmo,
                    "in_incois_dac": in_dac,
                    "rtraj": None,
                    "profiles": None,
                    "error": error,
                    "updated_at": None,
                }
            else:
                row["error"] = error
                if in_dac is not None:
                    row["in_incois_dac"] = in_dac

    def _refresh_float(self, ftp: ftplib.FTP, wmo: int, members: set[str]) -> bool:
        """Commit only a complete, validated row. Errors retain old data and
        old checked_at. Parser revisions force re-reading unchanged products.
        """
        key = str(wmo)
        with self._lock:
            old = copy.deepcopy(self._rows.get(key))
        now = _utcnow()
        if key not in members and wmo not in members:
            row = {
                "wmo": wmo,
                "in_incois_dac": False,
                "rtraj": None,
                "profiles": None,
                "error": None,
                "updated_at": now.isoformat(),
                "checked_at": now.isoformat(),
                "parser_version": PARSER_VERSION,
                "reason": (
                    "Outside configured DAC: no record in Ifremer dac/incois "
                    "(other DACs are not searched)"
                ),
            }
            with self._lock:
                self._rows[key] = row
            return not (isinstance(old, dict) and old.get("in_incois_dac") is False)
        base = f"{self._root}/dac/incois/{wmo}"
        size, mdtm = ftp_file_stat(ftp, f"{base}/{wmo}_Rtraj.nc")
        if size is None and mdtm is None:
            raise FloatSyncError("Rtraj absent upstream")
        rtraj_fp = f"{mdtm}|{size}"
        try:
            entries = ftp_list_entries(ftp, f"{base}/profiles")
        except Exception as exc:
            raise FloatSyncError(f"profiles listing failed: {exc}") from exc
        prof_fp = listing_fingerprint(entries)
        aggregate_name = f"{wmo}_prof.nc"
        aggregate_size, aggregate_mdtm = ftp_file_stat(ftp, f"{base}/{aggregate_name}")
        aggregate_fp = (
            f"{aggregate_mdtm}|{aggregate_size}"
            if aggregate_mdtm is not None or aggregate_size is not None
            else None
        )
        if aggregate_fp is None and (old or {}).get("profile_aggregate"):
            raise FloatSyncError(
                "Full profile history unavailable; retained previously verified row"
            )
        old_rtraj_fp = (old or {}).get("rtraj_fp")
        old_prof_fp = (old or {}).get("profiles_fp")
        current_parser = (old or {}).get("parser_version") == PARSER_VERSION
        if (
            old
            and old.get("in_incois_dac")
            and current_parser
            and old_rtraj_fp == rtraj_fp
            and old_prof_fp == prof_fp
            and not old.get("error")
            and "profile_aggregate_fp" in old
            and old.get("profile_aggregate_fp") == aggregate_fp
        ):
            old["checked_at"] = _utcnow().isoformat()
            with self._lock:
                self._rows[key] = old
            return False
        if current_parser and old and old.get("rtraj") and old_rtraj_fp == rtraj_fp:
            rtraj_block = old["rtraj"]
        else:
            try:
                raw = ftp_retrieve(ftp, f"{base}/{wmo}_Rtraj.nc")
            except Exception as exc:
                raise FloatSyncError(f"Rtraj download failed: {exc}") from exc
            rtraj_block = parse_rtraj(raw, wmo, now)
            rtraj_block.update(mdtm=mdtm, size=size, sha256=hashlib.sha256(raw).hexdigest())
        summary = summarize_profiles([n for (n, _s, _m) in entries], wmo)
        latest_parse = (
            (old.get("profiles") or {}).get("latest_parse")
            if current_parser and old and old_prof_fp == prof_fp
            else None
        )
        latest = summary.get("latest")
        if latest and latest_parse is None:
            try:
                praw = ftp_retrieve(ftp, f"{base}/profiles/{latest['file']}")
            except Exception as exc:
                raise FloatSyncError(f"latest profile download failed: {exc}") from exc
            latest_parse = parse_profile(praw, wmo, latest["cycle"], now)
            latest_parse["sha256"] = hashlib.sha256(praw).hexdigest()
        profiles_block = dict(summary, latest_parse=latest_parse)
        aggregate = (
            (old or {}).get("profile_aggregate")
            if current_parser and (old or {}).get("profile_aggregate_fp") == aggregate_fp
            else None
        )
        if aggregate_fp is not None and aggregate is None:
            try:
                araw = ftp_retrieve(ftp, f"{base}/{aggregate_name}")
            except Exception as exc:
                raise FloatSyncError(f"Full profile history download failed: {exc}") from exc
            aggregate = parse_profile(araw, wmo, None, now)
            aggregate.update(
                file=aggregate_name,
                mdtm=aggregate_mdtm,
                size=aggregate_size,
                sha256=hashlib.sha256(araw).hexdigest(),
            )
        row = {
            "wmo": wmo,
            "in_incois_dac": True,
            "rtraj": rtraj_block,
            "profiles": profiles_block,
            "rtraj_fp": rtraj_fp,
            "profiles_fp": prof_fp,
            "profile_aggregate": aggregate,
            "profile_aggregate_fp": aggregate_fp,
            "error": None,
            "updated_at": now.isoformat(),
            "checked_at": _utcnow().isoformat(),
            "parser_version": PARSER_VERSION,
        }
        with self._lock:
            self._rows[key] = row
        return True

    # -- serve ----------------------------------------------------------
    def payload(self) -> dict[str, Any]:
        """Observation age and cache freshness are distinct dimensions."""
        fleet_error = None
        try:
            meta = {int(f["wmo"]): f for f in self._fleet_fn() if str(f.get("wmo", "")).isdigit()}
        except Exception as exc:
            meta = None
            fleet_error = f"Local fleet unavailable; displaying cached membership: {exc}"
        try:
            from datasources.local import build_wmo_identity_map

            identities = build_wmo_identity_map()
        except Exception:
            identities = {}
        with self._lock:
            rows = copy.deepcopy(self._rows)
            sync = dict(self._sync)
            running = self._running
            progress = dict(self._progress)
        # Take the derivation clock after the snapshot: a worker may have
        # verified rows while local preset discovery was running.
        now = _utcnow()
        # An old cache must not silently add removed floats to the current fleet.
        wmos = sorted(meta if meta is not None else {int(k) for k in rows if str(k).isdigit()})
        floats = [
            self._serve_row(
                w, rows.get(str(w)), (meta or {}).get(w), identities.get(w, {}), now, self._interval
            )
            for w in wmos
        ]
        summary = {
            "total": len(floats),
            "active": sum(f["status"] == STATUS_ACTIVE for f in floats),
            "overdue": sum(f["status"] == STATUS_OVERDUE for f in floats),
            "no_comm_60": sum(f["status"] == STATUS_NO_COMM_60 for f in floats),
            "no_data": sum(f["status"] == STATUS_NO_DATA for f in floats),
            "profiles_missing_total": sum(f["profiles_missing"] or 0 for f in floats),
            "total_profiles": sum(f["profile_count"] or 0 for f in floats),
            "profile_records_known": sum(f["profile_count"] is not None for f in floats),
            "stale_rows": sum(f["stale"] for f in floats),
        }
        age = _age_seconds(sync.get("last_success_at"), now)
        stale = (
            age is None
            or age > self._interval
            or summary["stale_rows"] > 0
            or sync.get("status") in (SYNC_ERROR, SYNC_DEGRADED)
            or bool(sync.get("persistence_error"))
            or bool(fleet_error)
        )
        sync.update(
            running=running,
            progress=progress,
            interval_s=self._interval,
            stale=stale,
            age_seconds=age,
            stale_reason=(
                fleet_error
                or sync.get("error")
                or sync.get("persistence_error")
                or (
                    "No fully successful synchronization"
                    if age is None
                    else "Cached observations need re-verification"
                    if stale
                    else None
                )
            ),
            status=SYNC_DISABLED
            if not self._enabled
            else (SYNC_RUNNING if running else sync.get("status")),
        )
        return {
            "generated_at": now.isoformat(),
            "sync": sync,
            "summary": summary,
            "floats": floats,
            "source": self.source_info,
        }

    @staticmethod
    def _serve_row(
        wmo: int,
        row: dict[str, Any] | None,
        preset: dict[str, Any] | None,
        identity: dict[str, str],
        now: datetime,
        interval_s: float = 21600.0,
    ) -> dict[str, Any]:
        def identity_value(value: Any) -> str | None:
            text = str(value or "").strip()
            if (
                text.lower() in {"", "n/a", "nan", "none", "null", "redacted", "sanitized"}
                or "redacted" in text.lower()
                or "*" in text
            ):
                return None
            return text

        ptt, imei = identity_value(identity.get("ptt")), identity_value(identity.get("imei"))
        out: dict[str, Any] = {
            "wmo": wmo,
            "internal_id": ptt or imei,
            "ptt": ptt,
            "imei": imei,
            "float_type": (preset or {}).get("platform_type") or "—",
            "transmission_type": (preset or {}).get("transmission_type") or "—",
            "in_incois_dac": (row or {}).get("in_incois_dac"),
            "prof_num": None,
            "profile_count": None,
            "profiles_missing": None,
            "profiles_missing_list": [],
            "lon": None,
            "lat": None,
            "pos_source": None,
            "pos_qc": None,
            "position_iso": None,
            "position_time_field": None,
            "position_file": None,
            "position_error": None,
            "last_tx_iso": None,
            "last_tx_field": None,
            "last_tx_status_rt19": None,
            "last_tx_index": None,
            "last_tx_cycle": None,
            "communication_error": None,
            "days_since_last_tx": None,
            "expected_next_iso": None,
            "status": STATUS_NO_DATA,
            "traj_max_cycle": None,
            "latest_profile": None,
            "traj_last_fix": None,
            "traj_lagging_profiles": None,
            "rtraj_mdtm": None,
            "error": None,
            "updated_at": None,
            "checked_at": None,
            "stale": True,
            "stale_reason": "Awaiting first upstream verification",
            "cache_age_seconds": None,
        }
        if not row:
            out["error"] = "awaiting first synchronization"
            return out
        out.update(
            error=row.get("error"),
            updated_at=row.get("updated_at"),
            checked_at=row.get("checked_at"),
        )
        age = _age_seconds(row.get("checked_at"), now)
        old_parser = row.get("parser_version") != PARSER_VERSION
        position_inventory_pending = (
            row.get("in_incois_dac") is not False and "profile_aggregate_fp" not in row
        )
        out["cache_age_seconds"] = age
        out["stale"] = bool(
            old_parser
            or position_inventory_pending
            or row.get("error")
            or age is None
            or age > interval_s
        )
        out["stale_reason"] = row.get("error") or (
            "Legacy cache needs source re-validation"
            if old_parser
            else "Full profile position inventory needs verification"
            if position_inventory_pending
            else "No verified upstream check time"
            if age is None
            else "Upstream check older than the sync interval"
            if age > interval_s
            else None
        )
        if row.get("in_incois_dac") is False:
            out["communication_error"] = row.get("reason") or "no record in Ifremer dac/incois"
            return out
        rtraj, profs = row.get("rtraj") or {}, row.get("profiles") or {}
        out.update(
            traj_max_cycle=rtraj.get("traj_max_cycle"),
            rtraj_mdtm=rtraj.get("mdtm"),
            prof_num=profs.get("max_cycle"),
        )
        missing = sorted(set(profs.get("missing") or []))
        out["profiles_missing_list"] = missing
        out["profiles_missing"] = len(missing) if profs.get("max_cycle") is not None else None
        # Version-1 profiles lacked available_cycles; max minus observed gaps
        # is sufficient for positive-cycle availability (never invent a file).
        if "available_cycles" in profs:
            out["profile_count"] = profs["available_cycles"]
        elif profs.get("max_cycle") is not None:
            out["profile_count"] = max(0, profs["max_cycle"] - len(missing))
        latest, parsed = profs.get("latest"), profs.get("latest_parse") or {}
        if latest:
            out["latest_profile"] = {
                "file": latest.get("file"),
                "prefix": latest.get("prefix"),
                "cycle": latest.get("cycle"),
                "juld_iso": parsed.get("juld_iso"),
                "lat": parsed.get("lat"),
                "lon": parsed.get("lon"),
                "pos_qc": parsed.get("pos_qc") or None,
                "cycle_mismatch": bool(parsed.get("cycle_mismatch")),
                "position_iso": parsed.get("position_iso"),
                "position_error": parsed.get("position_error"),
            }
        candidates = []
        fix = rtraj.get("last_fix") or {}
        fix_time = _parse_utc(fix.get("juld_iso"))
        if (
            fix_time is not None
            and fix_time <= now
            and _position_ok(fix.get("lat"), fix.get("lon"), fix.get("pos_qc"))
        ):
            out["traj_last_fix"] = fix
            candidates.append((fix_time, "traj", fix, "JULD", f"{wmo}_Rtraj.nc"))
        profile_time = _parse_utc(parsed.get("position_iso"))
        if (
            not old_parser
            and profile_time is not None
            and profile_time <= now
            and not parsed.get("cycle_mismatch")
            and parsed.get("platform_number") == str(wmo)
            and _position_ok(parsed.get("lat"), parsed.get("lon"), parsed.get("pos_qc"))
        ):
            candidates.append(
                (profile_time, "profile", parsed, "JULD_LOCATION", (latest or {}).get("file"))
            )
        aggregate = row.get("profile_aggregate") or {}
        aggregate_time = _parse_utc(aggregate.get("position_iso"))
        if (
            not old_parser
            and aggregate_time is not None
            and aggregate_time <= now
            and aggregate.get("platform_number") == str(wmo)
            and _position_ok(aggregate.get("lat"), aggregate.get("lon"), aggregate.get("pos_qc"))
        ):
            candidates.append(
                (aggregate_time, "profile", aggregate, "JULD_LOCATION", aggregate.get("file"))
            )
        out["position_error"] = (
            "Legacy profile cache has no verified location time; refresh required"
            if old_parser and latest
            else parsed.get("position_error")
        )
        if not aggregate and not old_parser:
            note = (
                "Full profile history unavailable; position search limited to trajectory "
                "and highest published cycle."
            )
            out["position_error"] = (
                f"{out['position_error']} {note}" if out["position_error"] else note
            )
        if candidates:
            # Prefer the direct trajectory fix when observation times tie.
            dt, source, pos, field, filename = max(candidates, key=lambda c: (c[0], c[1] == "traj"))
            out.update(
                lat=pos["lat"],
                lon=pos["lon"],
                pos_source=source,
                pos_qc=pos["pos_qc"],
                position_iso=dt.isoformat(),
                position_time_field=field,
                position_file=filename,
            )
        elif out["position_error"] is None:
            out["position_error"] = "No timestamped QC 1/2 upstream position available"
        field = rtraj.get("last_tx_field")
        last_tx = _parse_utc(rtraj.get("last_tx_iso"))
        if field in COMMUNICATION_FIELDS and last_tx is not None and last_tx <= now:
            raw_juld = _valid_juld(rtraj.get("last_tx_juld"), now)
            if raw_juld is not None:
                last_tx = juld_to_datetime(raw_juld)
            days = (now - last_tx).total_seconds() / 86400.0
            out.update(
                last_tx_iso=last_tx.isoformat(),
                last_tx_field=field,
                last_tx_status_rt19=rtraj.get("last_tx_status_rt19") or None,
                last_tx_index=rtraj.get("last_tx_index"),
                last_tx_cycle=rtraj.get("last_tx_cycle"),
                days_since_last_tx=days,
                expected_next_iso=(last_tx + timedelta(days=10)).isoformat(),
                status=comm_status(days),
            )
        else:
            out["communication_error"] = rtraj.get("communication_error") or (
                "Cached measurement JULD is not an authoritative communication timestamp"
                if field and field not in COMMUNICATION_FIELDS
                else "No valid upstream communication timestamp"
            )
        measurements = [
            dt
            for dt in (_parse_utc(parsed.get("juld_iso")), _parse_utc(aggregate.get("juld_iso")))
            if dt is not None
        ]
        measurement = max(measurements) if measurements else None
        if out["last_tx_iso"] and measurement:
            out["traj_lagging_profiles"] = measurement > last_tx + timedelta(hours=12)
        return out

    # -- background polling (mirrors ingestion) --------------------------
    async def _poll_loop(self) -> None:
        while True:
            started = time.monotonic()
            try:
                await asyncio.to_thread(self.sync_now)
            except Exception as exc:
                self._fail(f"Scheduled sync failed: {type(exc).__name__}: {exc}", time.time())
            # Start-to-start cadence, not interval plus a potentially long
            # download. Do not overlap cycles or spin if a cycle overruns.
            await asyncio.sleep(max(1.0, self._interval - (time.monotonic() - started)))

    def start(self) -> None:
        if self._poll_task is None and self._enabled:
            try:
                self._poll_task = asyncio.create_task(self._poll_loop())
            except RuntimeError:
                self._poll_task = None

    async def stop(self) -> None:
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            self._poll_task = None


fleet_sync = FleetSyncRegistry()
