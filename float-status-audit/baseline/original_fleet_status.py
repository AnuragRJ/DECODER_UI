"""Float communication monitoring — Ifremer/Argo GDAC synchronization.

Fleet-level upstream communication truth for the INCOIS float fleet. Every
communication timestamp comes from the authoritative Ifremer GDAC over
anonymous FTP; no local decoder timestamp (run time, processing time,
profile JULD, file arrival) is ever substituted.

Source contract (verified against live GDAC 2026-09-17 — see
decoder-ui/FLEET_STATUS.md, never guessed):
  host ................ ftp.ifremer.fr:21 (anonymous; env-overridable)
  root ................ /ifremer/argo
  fleet membership .... /ifremer/argo/dac/incois/<wmo>/ exists
  trajectory .......... /ifremer/argo/dac/incois/<wmo>/<wmo>_Rtraj.nc
  Last Transmission ... max valid per-cycle JULD_LAST_MESSAGE
                        ("Date of latest float message received"),
                        fallback JULD_TRANSMISSION_END
                        ("Transmission end date"), then — for vintage
                        files whose per-cycle fields are absent/fill —
                        max valid measurement-row JULD; the field
                        actually used is recorded per float
  Prof# / missing ..... max cycle + gaps over profiles/ filenames
                        (R/D/BR/BD/SR/SD union; cycle 0 excluded)
  Lon/Lat ............. latest upstream profile LATITUDE/LONGITUDE,
                        fallback = trajectory last valid fix

Design mirrors ingestion.py: JSON cache with atomic writes, a background
asyncio poll loop delegating to a worker thread, start/stop lifecycle, and
a module singleton. Sync NEVER raises to callers — failures are recorded in
the sync/float status and the last valid cache keeps serving.
"""

from __future__ import annotations

import asyncio
import ftplib
import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Optional

import netCDF4
import numpy as np

from event_bus import DATA_DIR

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

JULD_EPOCH = datetime(1950, 1, 1, tzinfo=timezone.utc)
#: JULD values at/above this are fill (covers the writer 90000 convention and
#: the files' 999999 _FillValue).
FILL_JULD = 90000.0
#: A "message received" timestamp more than this far in the future is
#: impossible (predicted cycle events exist in N_MEASUREMENT space) and is
#: rejected wherever it appears.
FUTURE_SKEW_DAYS = 1.0

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

STATE_VERSION = 1

#: Latest-profile preference when several families share the max cycle.
PROFILE_PREFIX_PRIORITY = ["R", "D", "BR", "BD", "SR", "SD"]

_LIST_RE = re.compile(
    r"^([bcdlps-][rwxstST-]{9})\s+\d+\s+\S+\s+\S+\s+(\d+)\s+"
    r"([A-Z][a-z]{2})\s+(\d{1,2})\s+(\d{4}|\d{1,2}:\d{2})\s+(\S.*?)\s*$"
)
_PROFILE_RE = re.compile(r"^([A-Z]+)(\d{7})_(\d{3})\.nc$")
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


class FloatSyncError(Exception):
    """Per-float refresh failure (keeps any previously cached row)."""


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def juld_to_datetime(juld: float) -> datetime:
    """JULD (days since 1950-01-01 UTC) -> aware UTC datetime."""
    return JULD_EPOCH + timedelta(days=float(juld))


def juld_to_iso(juld: float) -> str:
    return juld_to_datetime(juld).isoformat()


def _valid_juld(value: Any, now: datetime) -> Optional[float]:
    """A JULD value usable as communication evidence, else None."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(v) or v >= FILL_JULD:
        return None
    if v > (now - JULD_EPOCH).total_seconds() / 86400.0 + FUTURE_SKEW_DAYS:
        return None
    return v


def comm_status(days_since: Optional[float]) -> str:
    """§6 status rule. Boundaries: ACTIVE while the 10-day window has not
    passed (days<=10); OVERDUE once it has and under 60 days; NO-COMM at 60+;
    NO DATA without a timestamp (never labeled dead)."""
    if days_since is None:
        return STATUS_NO_DATA
    if days_since <= 10:
        return STATUS_ACTIVE
    if days_since < 60:
        return STATUS_OVERDUE
    return STATUS_NO_COMM_60


def parse_list_line(line: str, now: Optional[datetime] = None) -> Optional[tuple[str, int, float, bool]]:
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
            dt = datetime(now.year, month, day, int(hh), int(mm), tzinfo=timezone.utc)
        except ValueError:
            return None
        if dt > now + timedelta(days=1):
            # Recent-mtime form with an implied year belongs to last year.
            try:
                dt = datetime(now.year - 1, month, day, int(hh), int(mm), tzinfo=timezone.utc)
            except ValueError:
                return None
    else:
        try:
            dt = datetime(int(year_or_time), month, day, tzinfo=timezone.utc)
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
    """Prof# / gaps / latest-file choice from profiles/ filenames only.

    Union over R/D/BR/BD/SR/SD families; cycle 0 excluded from gap math
    (launch-cycle profiles are rare and must not read as missing).
    """
    cycles: dict[int, list[str]] = {}
    n_files = 0
    for fn in filenames:
        m = _PROFILE_RE.match(fn)
        if not m or int(m.group(2)) != int(wmo):
            continue
        n_files += 1
        cycles.setdefault(int(m.group(3)), []).append(m.group(1))
    if not cycles:
        return {"max_cycle": None, "missing": [], "n_files": n_files,
                "latest": None, "listing_cycles": 0}
    max_cycle = max(cycles)
    missing = [c for c in range(1, max_cycle + 1) if c not in cycles]
    prefs = cycles[max_cycle]
    prefs.sort(key=lambda p: PROFILE_PREFIX_PRIORITY.index(p)
               if p in PROFILE_PREFIX_PRIORITY else len(PROFILE_PREFIX_PRIORITY))
    latest_prefix = prefs[0]
    return {
        "max_cycle": max_cycle,
        "missing": missing,
        "n_files": n_files,
        "listing_cycles": len(cycles),
        "latest": {"prefix": latest_prefix, "cycle": max_cycle,
                   "file": f"{latest_prefix}{wmo}_{max_cycle:03d}.nc"},
    }


# -- netCDF4 reading ---------------------------------------------------------

def _farr(var: Any) -> np.ndarray:
    """Float array with masked/fill entries as NaN (never raises)."""
    try:
        raw = var[:]
    except Exception:
        return np.array([], dtype=float)
    try:
        if np.ma.isMaskedArray(raw):
            raw = raw.filled(np.nan)
        return np.asarray(raw, dtype=float)
    except Exception:
        return np.array([], dtype=float)


def _char_at(var: Any, i: int) -> str:
    """Single character (RT19 STATUS / QC flags) as a stripped string."""
    try:
        v = var[i]
        if np.ma.is_masked(v):
            return ""
        if isinstance(v, bytes):
            return v.decode(errors="replace").strip()
        return np.asarray(v).tobytes().decode(errors="replace").strip("\x00").strip()
    except Exception:
        return ""


def _scalar_text(ds: netCDF4.Dataset, name: str) -> str:
    try:
        return np.asarray(ds.variables[name][:]).tobytes().decode(errors="replace").strip("\x00").strip()
    except Exception:
        return ""


def parse_rtraj(raw: bytes, wmo: int, now: Optional[datetime] = None) -> dict[str, Any]:
    """Extract communication evidence from a GDAC *_Rtraj.nc image.

    Returns last-tx (field + value + RT19 status code), trajectory max cycle
    and last valid fix. Raises FloatSyncError when the file carries no usable
    communication timestamp at all.
    """
    now = now or _utcnow()
    try:
        ds = netCDF4.Dataset(f"{wmo}_Rtraj.nc", memory=bytes(raw))
    except Exception as exc:
        raise FloatSyncError(f"Rtraj unreadable: {exc}") from exc
    try:
        platform = _scalar_text(ds, "PLATFORM_NUMBER")
        if platform and platform != str(wmo):
            raise FloatSyncError(f"Rtraj PLATFORM_NUMBER {platform!r} != {wmo}")
        out: dict[str, Any] = {"platform_number": platform or str(wmo)}
        # Per-cycle communication fields (order-independent max).
        last_tx: Optional[float] = None
        last_tx_field: Optional[str] = None
        last_tx_status = ""
        for field in ("JULD_LAST_MESSAGE", "JULD_TRANSMISSION_END"):
            if field not in ds.variables:
                continue
            arr = _farr(ds.variables[field])
            best = -1
            best_v: Optional[float] = None
            for i, v in enumerate(arr.tolist()):
                vv = _valid_juld(v, now)
                if vv is not None and (best_v is None or vv > best_v):
                    best_v = vv
                    best = i
            if best_v is not None:
                last_tx, last_tx_field = best_v, field
                status_var = f"{field}_STATUS"
                if status_var in ds.variables:
                    last_tx_status = _char_at(ds.variables[status_var], best)
                break
        if last_tx is None or last_tx_field is None:
            # Tertiary fallback for vintage files whose per-cycle message
            # fields are absent or entirely fill (observed: 2012-era Rtraj):
            # the latest valid measurement-row JULD is still genuine upstream
            # evidence of float activity. Same future-guard applies, and the
            # field actually used is recorded (never silently substituted).
            if "JULD" in ds.variables:
                for v in _farr(ds.variables["JULD"]).ravel().tolist():
                    vv = _valid_juld(v, now)
                    if vv is not None and (last_tx is None or vv > last_tx):
                        last_tx, last_tx_field = vv, "JULD (measurement max)"
            if last_tx is None or last_tx_field is None:
                raise FloatSyncError(
                    "Rtraj has no usable JULD_LAST_MESSAGE / JULD_TRANSMISSION_END / JULD")
        out["last_tx_juld"] = last_tx
        out["last_tx_iso"] = juld_to_iso(last_tx)
        out["last_tx_field"] = last_tx_field
        out["last_tx_status_rt19"] = last_tx_status
        # Trajectory cycle span (context for the detail view).
        traj_max: Optional[int] = None
        for name in ("CYCLE_NUMBER_INDEX", "CYCLE_NUMBER"):
            if name in ds.variables:
                try:
                    vals = np.asarray(ds.variables[name][:]).ravel().tolist()
                    nums = [int(v) for v in vals
                            if not np.ma.is_masked(v) and int(v) not in (99999,)]
                    if nums:
                        traj_max = max(nums) if traj_max is None else max(traj_max, max(nums))
                except Exception:
                    continue
        out["traj_max_cycle"] = traj_max
        # Last valid fix: max-JULD measurement row with a valid position.
        out["last_fix"] = None
        try:
            juld = _farr(ds.variables["JULD"])
            lat = _farr(ds.variables["LATITUDE"])
            lon = _farr(ds.variables["LONGITUDE"])
        except KeyError:
            juld, lat, lon = np.array([]), np.array([]), np.array([])
        n = min(juld.size, lat.size, lon.size)
        cyc = np.asarray(ds.variables["CYCLE_NUMBER"][:]).ravel() if "CYCLE_NUMBER" in ds.variables else None
        mc = np.asarray(ds.variables["MEASUREMENT_CODE"][:]).ravel() if "MEASUREMENT_CODE" in ds.variables else None
        best_fix: Optional[dict[str, Any]] = None
        best_j = -1.0
        for i in range(n):
            vv = _valid_juld(juld[i], now)
            if vv is None or vv <= best_j:
                continue
            la, lo = float(lat[i]), float(lon[i])
            if not (np.isfinite(la) and np.isfinite(lo) and abs(la) <= 90 and abs(lo) <= 180):
                continue
            best_j = vv
            best_fix = {
                "juld": vv,
                "juld_iso": juld_to_iso(vv),
                "lat": la,
                "lon": lo,
                "cycle": (int(cyc[i]) if cyc is not None and i < cyc.size and not np.ma.is_masked(cyc[i]) else None),
                "mc": (int(mc[i]) if mc is not None and i < mc.size and not np.ma.is_masked(mc[i]) else None),
                "pos_qc": (_char_at(ds.variables["POSITION_QC"], i) if "POSITION_QC" in ds.variables else ""),
            }
        out["last_fix"] = best_fix
        return out
    finally:
        try:
            ds.close()
        except Exception:
            pass


def parse_profile(raw: bytes, wmo: int, filename_cycle: int,
                  now: Optional[datetime] = None) -> dict[str, Any]:
    """JULD + position from the latest upstream profile file image.

    Missing variables degrade to None fields (never fatal): the trajectory
    fix remains as the position fallback.
    """
    now = now or _utcnow()
    try:
        ds = netCDF4.Dataset(f"latest_{wmo}.nc", memory=bytes(raw))
    except Exception as exc:
        raise FloatSyncError(f"profile file unreadable: {exc}") from exc
    try:
        out: dict[str, Any] = {"juld": None, "juld_iso": None, "lat": None,
                               "lon": None, "pos_qc": "", "cycle": None,
                               "cycle_mismatch": False}
        if "JULD" in ds.variables:
            for v in _farr(ds.variables["JULD"]).ravel().tolist():
                vv = _valid_juld(v, now)
                if vv is not None:
                    out["juld"], out["juld_iso"] = vv, juld_to_iso(vv)
                    break
        for name, key in (("LATITUDE", "lat"), ("LONGITUDE", "lon")):
            if name in ds.variables:
                arr = _farr(ds.variables[name]).ravel().tolist()
                lim = 90 if key == "lat" else 180
                for v in arr:
                    if np.isfinite(v) and abs(v) <= lim:
                        out[key] = float(v)
                        break
        if "POSITION_QC" in ds.variables:
            try:
                out["pos_qc"] = _scalar_text(ds, "POSITION_QC")[:8]
            except Exception:
                out["pos_qc"] = ""
        if "CYCLE_NUMBER" in ds.variables:
            try:
                c = int(np.asarray(ds.variables["CYCLE_NUMBER"][:]).ravel().tolist()[0])
                out["cycle"] = None if c in (99999,) else c
                if out["cycle"] is not None and out["cycle"] != int(filename_cycle):
                    out["cycle_mismatch"] = True
            except Exception:
                pass
        return out
    finally:
        try:
            ds.close()
        except Exception:
            pass


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
    return out


def ftp_file_stat(ftp: ftplib.FTP, path: str) -> tuple[Optional[int], Optional[str]]:
    """(size, MDTM 'YYYYMMDDHHMMSS') — each None-tolerant."""
    size: Optional[int] = None
    try:
        size = ftp.size(path)
    except Exception:
        pass
    mdtm: Optional[str] = None
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
        state_path: Optional[Path] = None,
        fleet_fn: Optional[FleetFn] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        root: Optional[str] = None,
        timeout_s: Optional[float] = None,
        interval_s: Optional[float] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        self._state_path = state_path or (DATA_DIR / "fleet_status" / "cache.json")
        self._fleet_fn = fleet_fn or _default_fleet
        self._host = host or os.environ.get("FLEET_FTP_HOST", "ftp.ifremer.fr")
        self._port = port or int(os.environ.get("FLEET_FTP_PORT", "21"))
        self._root = (root or os.environ.get("FLEET_FTP_ROOT", "/ifremer/argo")).rstrip("/") or "/"
        self._timeout = timeout_s or float(os.environ.get("FLEET_FTP_TIMEOUT_S", "30"))
        self._interval = interval_s or float(os.environ.get("FLEET_SYNC_INTERVAL_S", "21600"))
        self._enabled = (os.environ.get("FLEET_SYNC_ENABLED", "1") != "0") if enabled is None else enabled
        self._rows: dict[str, dict[str, Any]] = {}
        self._sync: dict[str, Any] = {
            "status": SYNC_NEVER, "last_attempt_at": None, "last_success_at": None,
            "error": None, "counts": {}, "duration_s": None,
        }
        self._lock = threading.Lock()
        self._running = False
        self._progress = {"done": 0, "total": 0}
        self._poll_task: Optional[asyncio.Task] = None
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
            "field": ("JULD_LAST_MESSAGE (fallback JULD_TRANSMISSION_END, "
                      "then JULD measurement max for vintage files)"),
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
            if not isinstance(data, dict) or int(data.get("version") or 0) != STATE_VERSION:
                return
            rows = data.get("rows")
            if isinstance(rows, dict):
                self._rows = {str(k): v for k, v in rows.items() if isinstance(v, dict)}
            sync = data.get("sync")
            if isinstance(sync, dict):
                for k in ("status", "last_attempt_at", "last_success_at", "error", "counts", "duration_s"):
                    if k in sync:
                        self._sync[k] = sync[k]
                if self._sync.get("status") == SYNC_RUNNING:
                    # A crash mid-cycle must not wedge the status forever.
                    self._sync["status"] = SYNC_NEVER if not self._rows else SYNC_DEGRADED
        except Exception:
            self._rows, self._sync["status"] = {}, SYNC_NEVER

    def _save(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._state_path.with_suffix(".json.tmp")
            with self._lock:
                payload = {"version": STATE_VERSION, "rows": self._rows, "sync": dict(self._sync)}
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.replace(self._state_path)
        except Exception:
            pass

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
                    self._record_float_error(wmo, str(exc) or "sync failed",
                                             in_dac=(str(wmo) in members or wmo in members))
                except Exception as exc:  # never let one float kill the cycle
                    failed += 1
                    self._record_float_error(wmo, f"{type(exc).__name__}: {exc}",
                                             in_dac=(str(wmo) in members or wmo in members))
                with self._lock:
                    self._progress["done"] += 1
            now_iso = _utcnow().isoformat()
            with self._lock:
                self._sync.update({
                    "status": SYNC_OK if failed == 0 else SYNC_DEGRADED,
                    "last_success_at": now_iso,
                    "error": None if failed == 0 else f"{failed} float(s) failed refresh (kept last valid rows)",
                    "counts": {"total": len(wmos), "updated": updated,
                               "unchanged": unchanged, "failed": failed},
                    "duration_s": round(time.time() - t0, 1),
                })
            self._save()
            return {"accepted": True, "status": self._sync["status"], "counts": dict(self._sync["counts"])}
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
            self._sync.update({"status": SYNC_ERROR, "error": error,
                               "duration_s": round(time.time() - t0, 1)})
        self._save()
        return {"accepted": True, "status": SYNC_ERROR, "error": error}

    def _record_float_error(self, wmo: int, error: str, in_dac: Optional[bool] = None) -> None:
        with self._lock:
            row = self._rows.get(str(wmo))
            if row is None:
                self._rows[str(wmo)] = {
                    "wmo": wmo, "in_incois_dac": in_dac, "rtraj": None,
                    "profiles": None, "error": error, "updated_at": None,
                }
            else:
                row["error"] = error
                if in_dac is not None:
                    row["in_incois_dac"] = in_dac

    def _refresh_float(self, ftp: ftplib.FTP, wmo: int, members: set[str]) -> bool:
        """Refresh one float's cached upstream snapshot. Returns True when
        anything was re-fetched. Raises FloatSyncError (row untouched)."""
        key = str(wmo)
        with self._lock:
            old = self._rows.get(key)
        if key not in members and wmo not in members:
            row = {"wmo": wmo, "in_incois_dac": False, "rtraj": None,
                   "profiles": None, "error": None, "updated_at": _utcnow().isoformat(),
                   "reason": "no record in Ifremer dac/incois"}
            with self._lock:
                prev = self._rows.get(key)
                self._rows[key] = row
            return not (isinstance(prev, dict) and prev.get("in_incois_dac") is False)
        base = f"{self._root}/dac/incois/{wmo}"
        try:
            size, mdtm = ftp_file_stat(ftp, f"{base}/{wmo}_Rtraj.nc")
        except Exception as exc:
            raise FloatSyncError(f"Rtraj stat failed: {exc}") from exc
        if size is None and mdtm is None:
            raise FloatSyncError("Rtraj absent upstream")
        rtraj_fp = f"{mdtm}|{size}"
        try:
            entries = ftp_list_entries(ftp, f"{base}/profiles")
        except Exception as exc:
            raise FloatSyncError(f"profiles listing failed: {exc}") from exc
        prof_fp = listing_fingerprint(entries)
        old_rtraj_fp = (old or {}).get("rtraj_fp")
        old_prof_fp = (old or {}).get("profiles_fp")
        if old and old.get("in_incois_dac") and old_rtraj_fp == rtraj_fp \
                and old_prof_fp == prof_fp and not old.get("error") \
                and (old.get("rtraj") or {}).get("last_tx_iso"):
            return False  # unchanged upstream — no download
        now = _utcnow()
        # Trajectory block (reused when its own fingerprint is unchanged).
        if old and old.get("rtraj") and old_rtraj_fp == rtraj_fp:
            rtraj_block = old["rtraj"]
        else:
            try:
                raw = ftp_retrieve(ftp, f"{base}/{wmo}_Rtraj.nc")
            except Exception as exc:
                raise FloatSyncError(f"Rtraj download failed: {exc}") from exc
            rtraj_block = parse_rtraj(raw, wmo, now)
            rtraj_block["mdtm"] = mdtm
            rtraj_block["size"] = size
        # Profiles block (listing always re-summarized; file fetched on change).
        summary = summarize_profiles([n for (n, _s, _m) in entries], wmo)
        latest_parse = (old.get("profiles") or {}).get("latest_parse") \
            if old and old_prof_fp == prof_fp else None
        latest = summary.get("latest")
        if latest and latest_parse is None:
            try:
                praw = ftp_retrieve(ftp, f"{base}/profiles/{latest['file']}")
            except Exception as exc:
                raise FloatSyncError(f"latest profile download failed: {exc}") from exc
            latest_parse = parse_profile(praw, wmo, latest["cycle"], now)
        profiles_block = dict(summary)
        profiles_block["latest_parse"] = latest_parse
        row = {"wmo": wmo, "in_incois_dac": True, "rtraj": rtraj_block,
               "profiles": profiles_block, "rtraj_fp": rtraj_fp,
               "profiles_fp": prof_fp, "error": None,
               "updated_at": now.isoformat()}
        with self._lock:
            self._rows[key] = row
        return True

    # -- serve ----------------------------------------------------------
    def payload(self) -> dict[str, Any]:
        """Full Float Status payload; derived fields computed from cached
        last-tx + wall clock so status is always fresh without re-sync."""
        now = _utcnow()
        try:
            fleet = self._fleet_fn()
            meta = {int(f["wmo"]): f for f in fleet if str(f.get("wmo", "")).isdigit()}
        except Exception:
            meta = {}
        try:
            from datasources.local import build_wmo_identity_map

            identities = build_wmo_identity_map()
        except Exception:
            identities = {}
        with self._lock:
            rows = dict(self._rows)
            sync = dict(self._sync)
            running = self._running
            progress = dict(self._progress)
        wmos = sorted(set(meta) | {int(k) for k in rows if str(k).isdigit()})
        floats = [self._serve_row(w, rows.get(str(w)), meta.get(w),
                                  identities.get(w, {}), now) for w in wmos]
        summary = {
            "total": len(floats),
            "active": sum(1 for f in floats if f["status"] == STATUS_ACTIVE),
            "overdue": sum(1 for f in floats if f["status"] == STATUS_OVERDUE),
            "no_comm_60": sum(1 for f in floats if f["status"] == STATUS_NO_COMM_60),
            "no_data": sum(1 for f in floats if f["status"] == STATUS_NO_DATA),
            "profiles_missing_total": sum(f["profiles_missing"] or 0 for f in floats),
            "total_profiles": sum(f["prof_num"] or 0 for f in floats),
        }
        sync_out = dict(sync)
        sync_out.update({"running": running, "progress": progress,
                         "interval_s": self._interval,
                         "status": SYNC_DISABLED if not self._enabled else
                         (SYNC_RUNNING if running and sync.get("status") == SYNC_RUNNING
                          else sync.get("status"))})
        return {"generated_at": now.isoformat(), "sync": sync_out,
                "summary": summary, "floats": floats,
                "source": self.source_info}

    @staticmethod
    def _serve_row(wmo: int, row: Optional[dict[str, Any]],
                   preset: Optional[dict[str, Any]],
                   identity: dict[str, str], now: datetime) -> dict[str, Any]:
        ptt = (identity.get("ptt") or "").strip()
        imei = (identity.get("imei") or "").strip()
        out: dict[str, Any] = {
            "wmo": wmo,
            "internal_id": ptt or imei or None,
            "ptt": ptt or None,
            "imei": imei or None,
            "float_type": (preset or {}).get("platform_type") or "—",
            "transmission_type": (preset or {}).get("transmission_type") or "—",
            "in_incois_dac": (row or {}).get("in_incois_dac"),
            "prof_num": None, "profiles_missing": None, "profiles_missing_list": [],
            "lon": None, "lat": None, "pos_source": None, "pos_qc": None,
            "last_tx_iso": None, "last_tx_field": None, "last_tx_status_rt19": None,
            "days_since_last_tx": None, "expected_next_iso": None, "status": STATUS_NO_DATA,
            "traj_max_cycle": None, "latest_profile": None, "traj_last_fix": None,
            "traj_lagging_profiles": None, "rtraj_mdtm": None,
            "error": None, "updated_at": None,
        }
        if not row:
            out["error"] = "awaiting first synchronization"
            return out
        out["error"] = row.get("error")
        out["updated_at"] = row.get("updated_at")
        if row.get("in_incois_dac") is False:
            out["error"] = out["error"] or row.get("reason") or "no record in Ifremer dac/incois"
            return out
        rtraj = row.get("rtraj") or {}
        profs = row.get("profiles") or {}
        out["traj_max_cycle"] = rtraj.get("traj_max_cycle")
        out["rtraj_mdtm"] = rtraj.get("mdtm")
        out["traj_last_fix"] = rtraj.get("last_fix")
        out["prof_num"] = profs.get("max_cycle")
        missing = profs.get("missing") or []
        out["profiles_missing_list"] = missing
        out["profiles_missing"] = len(missing) if profs.get("max_cycle") is not None else None
        latest = profs.get("latest")
        parsed = profs.get("latest_parse") or {}
        if latest:
            out["latest_profile"] = {
                "file": latest.get("file"), "prefix": latest.get("prefix"),
                "cycle": latest.get("cycle"), "juld_iso": parsed.get("juld_iso"),
                "lat": parsed.get("lat"), "lon": parsed.get("lon"),
                "pos_qc": parsed.get("pos_qc") or None,
                "cycle_mismatch": bool(parsed.get("cycle_mismatch")),
            }
        # Freshest honest upstream position: latest profile, else traj fix.
        if parsed.get("lat") is not None and parsed.get("lon") is not None:
            out["lat"], out["lon"] = parsed["lat"], parsed["lon"]
            out["pos_source"] = "profile"
            out["pos_qc"] = parsed.get("pos_qc") or None
        elif (rtraj.get("last_fix") or {}).get("lat") is not None:
            fix = rtraj["last_fix"]
            out["lat"], out["lon"] = fix["lat"], fix["lon"]
            out["pos_source"] = "traj"
            out["pos_qc"] = fix.get("pos_qc") or None
        last_iso = rtraj.get("last_tx_iso")
        if last_iso:
            try:
                last_tx = datetime.fromisoformat(last_iso)
                days = (now - last_tx).total_seconds() / 86400.0
            except (ValueError, TypeError):
                days = None
            out["last_tx_iso"] = last_iso
            out["last_tx_field"] = rtraj.get("last_tx_field")
            out["last_tx_status_rt19"] = rtraj.get("last_tx_status_rt19") or None
            if days is not None:
                out["days_since_last_tx"] = round(days, 3)
                out["expected_next_iso"] = (last_tx + timedelta(days=10)).isoformat()
                out["status"] = comm_status(days)
        # DAC-lag evidence: profile measurement newer than traj last message.
        if last_iso and parsed.get("juld_iso"):
            try:
                out["traj_lagging_profiles"] = (
                    datetime.fromisoformat(parsed["juld_iso"]) >
                    datetime.fromisoformat(last_iso) + timedelta(hours=12))
            except (ValueError, TypeError):
                out["traj_lagging_profiles"] = None
        return out

    # -- background polling (mirrors ingestion) --------------------------
    async def _poll_loop(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.sync_now)
            except Exception:
                pass
            await asyncio.sleep(max(self._interval, 300.0))

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
