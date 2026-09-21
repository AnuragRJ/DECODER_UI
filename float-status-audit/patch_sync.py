from pathlib import Path
p=Path('/home/user/ARPY-decoder-Ui/incois-arpy-decoder/decoder-ui/service/fleet_status.py')
s=p.read_text()
s=s.replace('v = np.ma.asarray(var[:]).ravel()[i]','v = var[i]')
a=s.index('def _texts(')
s=s[:a]+'''def _flags(ds: netCDF4.Dataset, name: str) -> np.ndarray:
    if name not in ds.variables:
        return np.array([], dtype="U1")
    return np.ma.filled(ds.variables[name][:], b" ").astype("U1").ravel()


'''+s[a:]
s=s.replace('qc_var = ds.variables.get("POSITION_QC")','qc_values = _flags(ds, "POSITION_QC")')
s=s.replace('qc = _char_at(qc_var, i) if qc_var is not None else ""','qc = str(qc_values[i]) if i < qc_values.size else ""')
s=s.replace('flags = sorted({_char_at(qc_var, i) for i in range(lat.size)}) if qc_var is not None else []','flags = sorted(set(qc_values.tolist()))\n            out["position_qc_observed"] = flags')
s=s.replace('self._interval = interval_s or float(os.environ.get("FLEET_SYNC_INTERVAL_S", "21600"))','''requested_interval = interval_s if interval_s is not None else float(os.environ.get("FLEET_SYNC_INTERVAL_S", "21600"))
        self._interval = max(float(requested_interval), 300.0) if math.isfinite(float(requested_interval)) else 21600.0''')
s=s.replace('"error": None, "counts": {}, "duration_s": None,','"error": None, "counts": {}, "duration_s": None,\n            "last_completed_at": None, "persistence_error": None,')
s=s.replace('''"field": ("JULD_LAST_MESSAGE (fallback JULD_TRANSMISSION_END, "
                      "then JULD measurement max for vintage files)"),''','''"field": "JULD_LAST_MESSAGE (JULD_TRANSMISSION_END only if unavailable)",
            "position_policy": "Newest QC 1/2 trajectory JULD fix or highest-cycle profile JULD_LOCATION; no local coordinates",
            "profile_policy": "Prof# = highest published cycle; available = distinct positive cycles; missing = gaps in 1..Prof#",''')
s=s.replace('int(data.get("version") or 0) != STATE_VERSION','int(data.get("version") or 0) not in (1, STATE_VERSION)')
s=s.replace('for k in ("status", "last_attempt_at", "last_success_at", "error", "counts", "duration_s"):','for k in ("status", "last_attempt_at", "last_success_at", "last_completed_at", "error", "counts", "duration_s", "persistence_error"):')
a=s.index('    def _save(');b=s.index('    # -- sync',a)
s=s[:a]+'''    def _save(self) -> bool:
        """Atomic cache commit. Never call an unpersisted refresh successful."""
        tmp = self._state_path.with_suffix(".json.tmp")
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                self._sync["persistence_error"] = None
                payload = {"version": STATE_VERSION, "rows": copy.deepcopy(self._rows),
                           "sync": dict(self._sync)}
            tmp.write_text(json.dumps(payload, allow_nan=False), encoding="utf-8")
            tmp.replace(self._state_path)
            return True
        except Exception as exc:
            with self._lock:
                self._sync["persistence_error"] = f"Cache persistence failed: {type(exc).__name__}: {exc}"
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return False

'''+s[b:]
s=s.replace('''            wmos = sorted({int(f["wmo"]) for f in fleet if str(f.get("wmo", "")).isdigit()})
        except''','''            wmos = sorted({int(f["wmo"]) for f in fleet if str(f.get("wmo", "")).isdigit()})
            if not wmos:
                raise FloatSyncError("local fleet is empty; no upstream records were checked")
        except''')
s=s.replace('''            now_iso = _utcnow().isoformat()
            with self._lock:
                self._sync.update({
                    "status": SYNC_OK if failed == 0 else SYNC_DEGRADED,
                    "last_success_at": now_iso,''','''            now_iso = _utcnow().isoformat()
            with self._lock:
                previous_success = self._sync.get("last_success_at")
                self._sync.update({
                    "status": SYNC_OK if failed == 0 else SYNC_DEGRADED,
                    "last_completed_at": now_iso,
                    "last_success_at": now_iso if failed == 0 else previous_success,''')
s=s.replace('''            self._save()
            return {"accepted": True, "status": self._sync["status"], "counts": dict(self._sync["counts"])}''','''            if not self._save():
                with self._lock:
                    self._sync.update(status=SYNC_DEGRADED, last_success_at=previous_success,
                                      error=self._sync["persistence_error"])
            return {"accepted": True, "status": self._sync["status"], "counts": dict(self._sync["counts"])}''')
a=s.index('    def _refresh_float(');b=s.index('    # -- serve',a)
s=s[:a]+'''    def _refresh_float(self, ftp: ftplib.FTP, wmo: int, members: set[str]) -> bool:
        """Commit only a complete, validated row. Errors retain old data and
        old checked_at. Parser revisions force re-reading unchanged products.
        """
        key = str(wmo)
        with self._lock:
            old = copy.deepcopy(self._rows.get(key))
        now = _utcnow()
        if key not in members and wmo not in members:
            row = {"wmo": wmo, "in_incois_dac": False, "rtraj": None,
                   "profiles": None, "error": None, "updated_at": now.isoformat(),
                   "checked_at": now.isoformat(), "parser_version": PARSER_VERSION,
                   "reason": "no record in Ifremer dac/incois"}
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
        old_rtraj_fp = (old or {}).get("rtraj_fp")
        old_prof_fp = (old or {}).get("profiles_fp")
        current_parser = (old or {}).get("parser_version") == PARSER_VERSION
        if (old and old.get("in_incois_dac") and current_parser and
                old_rtraj_fp == rtraj_fp and old_prof_fp == prof_fp and not old.get("error")):
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
        latest_parse = (old.get("profiles") or {}).get("latest_parse") if current_parser and old and old_prof_fp == prof_fp else None
        latest = summary.get("latest")
        if latest and latest_parse is None:
            try:
                praw = ftp_retrieve(ftp, f"{base}/profiles/{latest['file']}")
            except Exception as exc:
                raise FloatSyncError(f"latest profile download failed: {exc}") from exc
            latest_parse = parse_profile(praw, wmo, latest["cycle"], now)
            latest_parse["sha256"] = hashlib.sha256(praw).hexdigest()
        profiles_block = dict(summary, latest_parse=latest_parse)
        row = {"wmo": wmo, "in_incois_dac": True, "rtraj": rtraj_block,
               "profiles": profiles_block, "rtraj_fp": rtraj_fp, "profiles_fp": prof_fp,
               "error": None, "updated_at": now.isoformat(),
               "checked_at": _utcnow().isoformat(), "parser_version": PARSER_VERSION}
        with self._lock:
            self._rows[key] = row
        return True

'''+s[b:]
a=s.index('    def payload(');b=s.index('    # -- background polling',a)
s=s[:a]+'''    def payload(self) -> dict[str, Any]:
        """Observation age and cache freshness are distinct dimensions."""
        now = _utcnow()
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
        # An old cache must not silently add removed floats to the current fleet.
        wmos = sorted(meta if meta is not None else {int(k) for k in rows if str(k).isdigit()})
        floats = [self._serve_row(w, rows.get(str(w)), (meta or {}).get(w),
                                  identities.get(w, {}), now, self._interval) for w in wmos]
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
        stale = (age is None or age > self._interval or summary["stale_rows"] > 0 or
                 sync.get("status") in (SYNC_ERROR, SYNC_DEGRADED) or bool(sync.get("persistence_error")) or bool(fleet_error))
        sync.update(running=running, progress=progress, interval_s=self._interval,
                    stale=stale, age_seconds=age,
                    stale_reason=(fleet_error or sync.get("error") or sync.get("persistence_error") or
                                  ("No fully successful synchronization" if age is None else
                                   "Cached observations need re-verification" if stale else None)),
                    status=SYNC_DISABLED if not self._enabled else (SYNC_RUNNING if running else sync.get("status")))
        return {"generated_at": now.isoformat(), "sync": sync, "summary": summary,
                "floats": floats, "source": self.source_info}

    @staticmethod
    def _serve_row(wmo: int, row: Optional[dict[str, Any]],
                   preset: Optional[dict[str, Any]], identity: dict[str, str],
                   now: datetime, interval_s: float = 21600.0) -> dict[str, Any]:
        def identity_value(value: Any) -> Optional[str]:
            text = str(value or "").strip()
            if text.lower() in {"", "n/a", "nan", "none", "null", "redacted", "sanitized"} or "redacted" in text.lower() or "*" in text:
                return None
            return text
        ptt, imei = identity_value(identity.get("ptt")), identity_value(identity.get("imei"))
        out: dict[str, Any] = {
            "wmo": wmo, "internal_id": ptt or imei, "ptt": ptt, "imei": imei,
            "float_type": (preset or {}).get("platform_type") or "—",
            "transmission_type": (preset or {}).get("transmission_type") or "—",
            "in_incois_dac": (row or {}).get("in_incois_dac"),
            "prof_num": None, "profile_count": None, "profiles_missing": None, "profiles_missing_list": [],
            "lon": None, "lat": None, "pos_source": None, "pos_qc": None,
            "position_iso": None, "position_time_field": None, "position_file": None, "position_error": None,
            "last_tx_iso": None, "last_tx_field": None, "last_tx_status_rt19": None,
            "last_tx_index": None, "last_tx_cycle": None, "communication_error": None,
            "days_since_last_tx": None, "expected_next_iso": None, "status": STATUS_NO_DATA,
            "traj_max_cycle": None, "latest_profile": None, "traj_last_fix": None,
            "traj_lagging_profiles": None, "rtraj_mdtm": None,
            "error": None, "updated_at": None, "checked_at": None,
            "stale": True, "stale_reason": "Awaiting first upstream verification", "cache_age_seconds": None,
        }
        if not row:
            out["error"] = "awaiting first synchronization"
            return out
        out.update(error=row.get("error"), updated_at=row.get("updated_at"), checked_at=row.get("checked_at"))
        age = _age_seconds(row.get("checked_at"), now)
        old_parser = row.get("parser_version") != PARSER_VERSION
        out["cache_age_seconds"] = age
        out["stale"] = bool(old_parser or row.get("error") or age is None or age > interval_s)
        out["stale_reason"] = (row.get("error") or ("Legacy cache needs source re-validation" if old_parser else
                               "No verified upstream check time" if age is None else
                               "Upstream check older than the sync interval" if age > interval_s else None))
        if row.get("in_incois_dac") is False:
            out["communication_error"] = row.get("reason") or "no record in Ifremer dac/incois"
            return out
        rtraj, profs = row.get("rtraj") or {}, row.get("profiles") or {}
        out.update(traj_max_cycle=rtraj.get("traj_max_cycle"), rtraj_mdtm=rtraj.get("mdtm"),
                   prof_num=profs.get("max_cycle"))
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
            out["latest_profile"] = {"file": latest.get("file"), "prefix": latest.get("prefix"),
                "cycle": latest.get("cycle"), "juld_iso": parsed.get("juld_iso"),
                "lat": parsed.get("lat"), "lon": parsed.get("lon"), "pos_qc": parsed.get("pos_qc") or None,
                "cycle_mismatch": bool(parsed.get("cycle_mismatch")),
                "position_iso": parsed.get("position_iso"), "position_error": parsed.get("position_error")}
        candidates = []
        fix = rtraj.get("last_fix") or {}
        fix_time = _parse_utc(fix.get("juld_iso"))
        if fix_time is not None and fix_time <= now and _position_ok(fix.get("lat"), fix.get("lon"), fix.get("pos_qc")):
            out["traj_last_fix"] = fix
            candidates.append((fix_time, "traj", fix, "JULD", f"{wmo}_Rtraj.nc"))
        profile_time = _parse_utc(parsed.get("position_iso"))
        if (not old_parser and profile_time is not None and profile_time <= now and
                not parsed.get("cycle_mismatch") and parsed.get("platform_number") == str(wmo) and
                _position_ok(parsed.get("lat"), parsed.get("lon"), parsed.get("pos_qc"))):
            candidates.append((profile_time, "profile", parsed, "JULD_LOCATION", (latest or {}).get("file")))
        out["position_error"] = ("Legacy profile cache has no verified location time; refresh required" if old_parser and latest else parsed.get("position_error"))
        if candidates:
            # Prefer the direct trajectory fix when observation times tie.
            dt, source, pos, field, filename = max(candidates, key=lambda c: (c[0], c[1] == "traj"))
            out.update(lat=pos["lat"], lon=pos["lon"], pos_source=source, pos_qc=pos["pos_qc"],
                       position_iso=dt.isoformat(), position_time_field=field, position_file=filename)
        elif out["position_error"] is None:
            out["position_error"] = "No timestamped QC 1/2 upstream position available"
        field = rtraj.get("last_tx_field")
        last_tx = _parse_utc(rtraj.get("last_tx_iso"))
        if field in COMMUNICATION_FIELDS and last_tx is not None and last_tx <= now:
            raw_juld = _valid_juld(rtraj.get("last_tx_juld"), now)
            if raw_juld is not None:
                last_tx = juld_to_datetime(raw_juld)
            days = (now - last_tx).total_seconds() / 86400.0
            out.update(last_tx_iso=last_tx.isoformat(), last_tx_field=field,
                       last_tx_status_rt19=rtraj.get("last_tx_status_rt19") or None,
                       last_tx_index=rtraj.get("last_tx_index"), last_tx_cycle=rtraj.get("last_tx_cycle"),
                       days_since_last_tx=days, expected_next_iso=(last_tx + timedelta(days=10)).isoformat(),
                       status=comm_status(days))
        else:
            out["communication_error"] = rtraj.get("communication_error") or (
                "Cached measurement JULD is not an authoritative communication timestamp" if field and field not in COMMUNICATION_FIELDS else
                "No valid upstream communication timestamp")
        measurement = _parse_utc(parsed.get("juld_iso"))
        if out["last_tx_iso"] and measurement:
            out["traj_lagging_profiles"] = measurement > last_tx + timedelta(hours=12)
        return out

'''+s[b:]
s=s.replace('''            except Exception:
                pass
            await asyncio.sleep(max(self._interval, 300.0))''','''            except Exception as exc:
                self._fail(f"Scheduled sync failed: {type(exc).__name__}: {exc}", time.time())
            await asyncio.sleep(self._interval)''')
p.write_text(s)
