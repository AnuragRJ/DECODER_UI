from pathlib import Path
p=Path('/home/user/ARPY-decoder-Ui/incois-arpy-decoder/decoder-ui/service/fleet_status.py')
s=p.read_text()
s=s.replace('import asyncio\n','import asyncio\nimport copy\nimport math\n')
s=s.replace('FUTURE_SKEW_DAYS = 1.0','FUTURE_SKEW_DAYS = 0.0')
s=s.replace('STATE_VERSION = 1','STATE_VERSION = 2\nPARSER_VERSION = 2\nCOMMUNICATION_FIELDS = ("JULD_LAST_MESSAGE", "JULD_TRANSMISSION_END")\n# Deliberately do not promote unassessed, bad or interpolated positions to a\n# verified latest fix. RT2: 1 = good, 2 = probably good.\nPOSITION_QC_ACCEPTED = {"1", "2"}')
s=s.replace('PROFILE_PREFIX_PRIORITY = ["R", "D", "BR", "BD", "SR", "SD"]','PROFILE_PREFIX_PRIORITY = ["D", "R", "BD", "BR", "SD", "SR"]')
s=s.replace('_PROFILE_RE = re.compile(r"^([A-Z]+)(\\d{7})_(\\d{3})\\.nc$")','_PROFILE_RE = re.compile(r"^(BD|BR|SD|SR|D|R)(\\d{7})_(\\d{3,4})(D?)\\.nc$")')
a=s.index('def juld_to_datetime(');b=s.index('def parse_list_line(',a)
s=s[:a]+'''def juld_to_datetime(juld: float) -> datetime:
    """Argo JULD -> aware UTC, removing <1 ms floating-point second jitter."""
    seconds = float(juld) * 86400.0
    if abs(seconds - round(seconds)) < 0.001:
        seconds = float(round(seconds))
    return JULD_EPOCH + timedelta(seconds=seconds)


def juld_to_iso(juld: float) -> str:
    return juld_to_datetime(juld).isoformat()


def _parse_utc(value: Any) -> Optional[datetime]:
    """Never interpret an unqualified cache timestamp in the server's timezone."""
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


def _age_seconds(value: Any, now: datetime) -> Optional[float]:
    dt = _parse_utc(value)
    if dt is None or dt > now:
        return None
    return (now - dt).total_seconds()


def _valid_juld(value: Any, now: datetime) -> Optional[float]:
    try:
        v = float(value)
        if not np.isfinite(v) or not 0 <= v < FILL_JULD:
            return None
        if juld_to_datetime(v) > now:
            return None
        return v
    except (TypeError, ValueError, OverflowError):
        return None


def comm_status(days_since: Optional[float]) -> str:
    """Approved policy, on unrounded elapsed days; unavailable != inactive."""
    if days_since is None or not math.isfinite(days_since) or days_since < 0:
        return STATUS_NO_DATA
    if days_since <= 10:
        return STATUS_ACTIVE
    if days_since < 60:
        return STATUS_OVERDUE
    return STATUS_NO_COMM_60


'''+s[b:]
a=s.index('def summarize_profiles(');b=s.index('# -- netCDF4 reading',a)
s=s[:a]+'''def summarize_profiles(filenames: list[str], wmo: int) -> dict[str, Any]:
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
        return {"max_cycle": None, "missing": [], "n_files": n_files,
                "latest": None, "listing_cycles": 0, "available_cycles": 0}
    max_cycle = max(cycles)
    missing = [c for c in range(1, max_cycle + 1) if c not in cycles]
    # Preserve the actual filename (padding and descent suffix included).
    prefix, filename = min(cycles[max_cycle], key=lambda x: (
        PROFILE_PREFIX_PRIORITY.index(x[0]), x[1].endswith("D.nc"), x[1]))
    return {"max_cycle": max_cycle, "missing": missing, "n_files": n_files,
            "listing_cycles": len(cycles),
            "available_cycles": sum(c > 0 for c in cycles),
            "latest": {"prefix": prefix, "cycle": max_cycle, "file": filename}}


'''+s[b:]
a=s.index('def _farr(');b=s.index('# ---------------------------------------------------------------------------\n# FTP layer',a)
s=s[:a]+'''def _farr(var: Any) -> np.ndarray:
    """Preserve masks even on integer variables before converting fill to NaN."""
    try:
        return np.ma.asarray(var[:], dtype=float).filled(np.nan).ravel()
    except (ValueError, TypeError, IndexError):
        return np.array([], dtype=float)


def _char_at(var: Any, i: int) -> str:
    try:
        v = np.ma.asarray(var[:]).ravel()[i]
        if np.ma.is_masked(v):
            return ""
        return v.decode(errors="replace").strip() if isinstance(v, bytes) else str(v).strip()
    except (ValueError, TypeError, IndexError):
        return ""


def _texts(ds: netCDF4.Dataset, name: str) -> list[str]:
    if name not in ds.variables:
        return []
    a = np.ma.asarray(ds.variables[name][:])
    if a.dtype.kind == "S" and a.dtype.itemsize == 1:
        a = np.ma.filled(a, b" ")
        rows = a.reshape((-1, a.shape[-1])) if a.ndim > 1 else [a]
        return [np.asarray(row).tobytes().decode(errors="replace").strip(" \\x00") for row in rows]
    return [str(v).strip(" \\x00") for v in np.ma.filled(a, "").ravel()]


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
    valid_units = {"days since 1950-01-01 00:00:00 utc", "days since 1950-01-01 00:00:00",
                   "days since 1950-01-01", "days since 1950-01-01 00:00:00z"}
    if units not in valid_units:
        raise FloatSyncError(f"{name} has absent/unsupported time units: {units!r}")
    if str(getattr(var, "calendar", "standard")).lower() not in {"standard", "gregorian", "proleptic_gregorian"}:
        raise FloatSyncError(f"{name} has an unsupported calendar")
    return _farr(var)


def _int_at(values: np.ndarray, i: int) -> Optional[int]:
    if i < values.size and np.isfinite(values[i]) and 0 <= values[i] < 99999:
        return int(values[i]) if values[i] == int(values[i]) else None
    return None


def _position_ok(lat: Any, lon: Any, qc: Any) -> bool:
    try:
        return (qc in POSITION_QC_ACCEPTED and np.isfinite(float(lat)) and np.isfinite(float(lon))
                and abs(float(lat)) <= 90 and abs(float(lon)) <= 180)
    except (TypeError, ValueError):
        return False


def parse_rtraj(raw: bytes, wmo: int, now: Optional[datetime] = None) -> dict[str, Any]:
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
        out: dict[str, Any] = {"platform_number": str(wmo), "last_tx_juld": None,
            "last_tx_iso": None, "last_tx_field": None, "last_tx_status_rt19": "",
            "last_tx_index": None, "last_tx_cycle": None, "communication_error": None}
        cycle_index = _farr(ds.variables["CYCLE_NUMBER_INDEX"]) if "CYCLE_NUMBER_INDEX" in ds.variables else np.array([])
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
            out.update(last_tx_juld=value, last_tx_iso=juld_to_iso(value), last_tx_field=field,
                       last_tx_index=i, last_tx_cycle=_int_at(cycle_index, i),
                       last_tx_status_rt19=_char_at(status_var, i) if status_var is not None else "",
                       last_tx_units=str(ds.variables[field].units),
                       last_tx_long_name=str(getattr(ds.variables[field], "long_name", "")))
            break
        if out["last_tx_iso"] is None:
            out["communication_error"] = "No valid JULD_LAST_MESSAGE or JULD_TRANSMISSION_END in upstream Rtraj; measurement/profile JULD is not communication evidence."
        nums: list[int] = []
        for name in ("CYCLE_NUMBER_INDEX", "CYCLE_NUMBER"):
            if name in ds.variables:
                nums.extend(int(v) for v in _farr(ds.variables[name]) if np.isfinite(v) and 0 <= v < 99999 and v == int(v))
        out["traj_max_cycle"] = max(nums) if nums else None
        out["last_fix"] = None
        juld = _julds(ds, "JULD")
        lat = _farr(ds.variables["LATITUDE"]) if "LATITUDE" in ds.variables else np.array([])
        lon = _farr(ds.variables["LONGITUDE"]) if "LONGITUDE" in ds.variables else np.array([])
        cyc = _farr(ds.variables["CYCLE_NUMBER"]) if "CYCLE_NUMBER" in ds.variables else np.array([])
        mc = _farr(ds.variables["MEASUREMENT_CODE"]) if "MEASUREMENT_CODE" in ds.variables else np.array([])
        qc_var = ds.variables.get("POSITION_QC")
        for i in range(min(juld.size, lat.size, lon.size)):
            value = _valid_juld(juld[i], now)
            qc = _char_at(qc_var, i) if qc_var is not None else ""
            if value is None or not _position_ok(lat[i], lon[i], qc):
                continue
            if out["last_fix"] is not None and value <= out["last_fix"]["juld"]:
                continue
            out["last_fix"] = {"juld": value, "juld_iso": juld_to_iso(value),
                "lat": float(lat[i]), "lon": float(lon[i]), "cycle": _int_at(cyc, i),
                "mc": _int_at(mc, i), "pos_qc": qc, "index": i, "time_field": "JULD"}
        return out
    finally:
        ds.close()


def parse_profile(raw: bytes, wmo: int, filename_cycle: int,
                  now: Optional[datetime] = None) -> dict[str, Any]:
    """Coherent N_PROF row: position uses JULD_LOCATION, not profile JULD.

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
        out: dict[str, Any] = {"platform_number": str(wmo), "juld": None, "juld_iso": None,
            "lat": None, "lon": None, "pos_qc": "", "cycle": None,
            "cycle_mismatch": False, "position_juld": None, "position_iso": None,
            "position_time_field": "JULD_LOCATION", "position_index": None,
            "position_error": None}
        j = _julds(ds, "JULD")
        loc = _julds(ds, "JULD_LOCATION")
        lat = _farr(ds.variables["LATITUDE"]) if "LATITUDE" in ds.variables else np.array([])
        lon = _farr(ds.variables["LONGITUDE"]) if "LONGITUDE" in ds.variables else np.array([])
        cyc = _farr(ds.variables["CYCLE_NUMBER"]) if "CYCLE_NUMBER" in ds.variables else np.array([])
        qc_var = ds.variables.get("POSITION_QC")
        valid_j = [(i, float(v)) for i, v in enumerate(j) if _valid_juld(v, now) is not None]
        measured = max(valid_j, key=lambda item: item[1]) if valid_j else None
        known_cycles = [int(v) for v in cyc if np.isfinite(v) and 0 <= v < 99999]
        out["cycle_mismatch"] = any(c != filename_cycle for c in known_cycles)
        candidates = []
        for i in range(min(loc.size, lat.size, lon.size)):
            value = _valid_juld(loc[i], now)
            qc = _char_at(qc_var, i) if qc_var is not None else ""
            if (value is not None and not out["cycle_mismatch"] and
                    _position_ok(lat[i], lon[i], qc) and _int_at(cyc, i) == filename_cycle):
                candidates.append((i, value, qc))
        if candidates:
            i, value, qc = max(candidates, key=lambda item: item[1])
            out.update(lat=float(lat[i]), lon=float(lon[i]), pos_qc=qc,
                       position_juld=value, position_iso=juld_to_iso(value), position_index=i,
                       cycle=_int_at(cyc, i))
        else:
            flags = sorted({_char_at(qc_var, i) for i in range(lat.size)}) if qc_var is not None else []
            out["position_error"] = ("Profile position unavailable: require a matching cycle, paired finite coordinates, "
                                     f"POSITION_QC 1/2 and a valid JULD_LOCATION (QC present: {','.join(flags) or 'none'}).")
        if measured:
            i, value = measured
            out.update(juld=value, juld_iso=juld_to_iso(value))
            if out["cycle"] is None:
                out["cycle"] = _int_at(cyc, i)
        return out
    finally:
        ds.close()


'''+s[b:]
# Safe directory parsing: an invalid/empty DAC response must not erase a fleet.
s=s.replace('''    return out


def ftp_file_stat''','''    members = {n for n in out if re.fullmatch(r"\\d{7}", n)}
    if not members:
        raise FloatSyncError("DAC listing contains no valid WMO directories; membership is unverified")
    return members


def ftp_file_stat''')
s=s.replace('''        if parsed is None:
            continue
        name, size, mtime, is_dir = parsed''','''        if parsed is None:
            if ln.strip() and not re.fullmatch(r"total\\s+\\d+", ln.strip()):
                raise FloatSyncError("Unparseable profiles LIST response; refusing an incomplete inventory")
            continue
        name, size, mtime, is_dir = parsed''')
# Keep the top-level documentation honest.
start=s.index('"""');end=s.index('"""',start+3)+3
s=s[:start]+'''"""Float Status: cached, verifiable Ifremer/Argo GDAC observations.

Communication: per-cycle JULD_LAST_MESSAGE, else JULD_TRANSMISSION_END only.
Location: newest QC 1/2 position among trajectory fixes (JULD) and the highest
published cycle's profile (JULD_LOCATION); source and position time exposed.
Prof#: highest published cycle. Available profiles: distinct positive cycles.
Missing profiles: directory gaps 1..Prof#, not communication or decoder errors.
Freshness is separate from float communication status. A successful check of
unchanged files renews checked_at, never the observation's timestamp.
See decoder-ui/FLEET_STATUS.md for the field contract and limitations.
"""'''+s[end:]
p.write_text(s)
