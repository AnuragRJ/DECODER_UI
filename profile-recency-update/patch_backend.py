from pathlib import Path
p=Path('/home/user/ARPY-decoder-Ui/incois-arpy-decoder/decoder-ui/service/fleet_status.py')
s=p.read_text()
end=s.index('"""',3)+3
s='''"""Float Status: latest published profile recency from Ifremer/Argo GDAC.

Monitoring uses ONLY max valid JULD in dac/incois/<wmo>/<wmo>_prof.nc.
Expected interval: 10 UTC days. Missed profiles are an approximate time-based
estimate, separate from the exact published-cycle inventory. Trajectory data
is retained for the existing verified position selector, not data status.
See decoder-ui/FLEET_STATUS.md for source, cache and validity contracts.
"""'''+s[end:]
s=s.replace('STATUS_ACTIVE = "ACTIVE"','STATUS_RECENT = "ACTIVE / RECENT PROFILE"')
s=s.replace('STATUS_OVERDUE = "OVERDUE"','STATUS_OVERDUE = "PROFILE OVERDUE"')
s=s.replace('STATUS_NO_COMM_60 = "NO COMMUNICATION 60+ DAYS"','STATUS_NO_RECENT_60 = "NO RECENT PROFILE DATA 60+ DAYS"')
s=s.replace('PARSER_VERSION = 2','PARSER_VERSION = 2\nPROFILE_RECENCY_VERSION = 1\nPROFILE_INTERVAL_DAYS = 10')
s=s.replace('def comm_status(days_since: float | None) -> str:', 'def profile_data_status(days_since: float | None) -> str:')
s=s.replace('return STATUS_ACTIVE','return STATUS_RECENT').replace('return STATUS_NO_COMM_60','return STATUS_NO_RECENT_60')
s=s.replace('if days_since <= 10:', 'if days_since <= PROFILE_INTERVAL_DAYS:')
# Date validity uses the existing masked / finite / nonfuture Argo epoch guard.
# Do not couple monitoring validity to position QC or to the largest cycle.
s=s.replace('''        j = _julds(ds, "JULD")
        loc = _julds(ds, "JULD_LOCATION")''','''        if "JULD" in ds.variables and ds.variables["JULD"].dimensions != ("N_PROF",):
            raise FloatSyncError("Profile JULD must use the N_PROF dimension")
        j = _julds(ds, "JULD")
        location_error = None
        try:
            loc = _julds(ds, "JULD_LOCATION")
        except FloatSyncError as exc:
            # A bad location time must not suppress an independently valid
            # profile measurement date. The existing trajectory fix can serve.
            loc = np.array([])
            location_error = str(exc)''')
s=s.replace('''                f"(QC present: {','.join(flags) or 'none'})."
            )''','''                f"(QC present: {','.join(flags) or 'none'})."
            )
            if location_error:
                out["position_error"] += f" {location_error}"''')
s=s.replace('''            "product": "dac/incois/<wmo>/<wmo>_Rtraj.nc",
            "field": "JULD_LAST_MESSAGE (JULD_TRANSMISSION_END only if unavailable)",''','''            "monitoring": "profile-recency",
            "product": "dac/incois/<wmo>/<wmo>_prof.nc",
            "field": "JULD (maximum valid value over N_PROF)",
            "expected_profile_interval_days": PROFILE_INTERVAL_DAYS,
            "approximation_note": (
                "Approximate estimate based on the expected 10-day profile cycle."
            ),''')
s=s.replace('''"missing = gaps in 1..Prof#"''','''"inventory gaps = absent file cycles in 1..Prof# (not Approx. Profiles Missed)"''')
s=s.replace('''else f"{failed} float(s) failed refresh (kept last valid rows)",''','''else f"{failed} float(s) had source refresh failures (kept last valid affected data)",''')
a=s.index('    def _refresh_float(');b=s.index('    # -- serve',a)
s=s[:a]+'''    def _refresh_float(self, ftp: ftplib.FTP, wmo: int, members: set[str]) -> bool:
        """Refresh independent source blocks. Profile recency must not wait
        for trajectory or inventory success. Each failed block retains its
        last valid data; a partial row is explicitly stale/degraded.
        """
        key = str(wmo)
        with self._lock:
            old = copy.deepcopy(self._rows.get(key))
        now = _utcnow()
        if key not in members and wmo not in members:
            row = {"wmo": wmo, "in_incois_dac": False, "rtraj": None,
                   "profiles": None, "profile_aggregate": None,
                   "profile_aggregate_fp": None, "error": None,
                   "updated_at": now.isoformat(), "checked_at": now.isoformat(),
                   "profile_checked_at": now.isoformat(),
                   "parser_version": PARSER_VERSION,
                   "profile_recency_version": PROFILE_RECENCY_VERSION,
                   "reason": "Outside configured DAC: no profile product in Ifremer dac/incois"}
            with self._lock:
                self._rows[key] = row
            return not (old and old.get("in_incois_dac") is False)

        base = f"{self._root}/dac/incois/{wmo}"
        row = copy.deepcopy(old) if old else {
            "wmo": wmo, "rtraj": None, "profiles": None,
            "profile_aggregate": None, "checked_at": None,
            "updated_at": None, "profile_checked_at": None,
        }
        row.update(in_incois_dac=True, error=None)
        row.pop("reason", None)
        errors: list[str] = []
        changed = old is None
        parser_current = (old or {}).get("parser_version") == PARSER_VERSION

        # Primary monitoring source: the complete published profile history.
        # Missing/unreadable history never falls back to another product/date.
        profile_name = f"{wmo}_prof.nc"
        try:
            size, mdtm = ftp_file_stat(ftp, f"{base}/{profile_name}")
            if size is None and mdtm is None:
                raise FloatSyncError(f"{profile_name} absent or unavailable upstream")
            fp = f"{mdtm}|{size}"
            aggregate = (old or {}).get("profile_aggregate")
            reusable = (parser_current and aggregate and
                        (old or {}).get("profile_recency_version") == PROFILE_RECENCY_VERSION and
                        (old or {}).get("profile_aggregate_fp") == fp and
                        aggregate.get("file") == profile_name and
                        aggregate.get("platform_number") == key)
            if not reusable:
                raw = ftp_retrieve(ftp, f"{base}/{profile_name}")
                aggregate = parse_profile(raw, wmo, None, now)
                aggregate.update(file=profile_name, mdtm=mdtm, size=size,
                                 sha256=hashlib.sha256(raw).hexdigest())
                changed = True
            row.update(profile_aggregate=aggregate, profile_aggregate_fp=fp,
                       profile_checked_at=_utcnow().isoformat(),
                       profile_recency_version=PROFILE_RECENCY_VERSION,
                       profile_sync_error=None)
        except Exception as exc:
            message = f"Profile history refresh failed: {exc}"
            errors.append(message)
            row["profile_sync_error"] = message
            row.pop("profile_aggregate_fp", None)  # re-read on recovery

        # Position evidence only. An unavailable Rtraj cannot block a newer
        # profile date; no message timestamp is used in monitoring formulas.
        try:
            size, mdtm = ftp_file_stat(ftp, f"{base}/{wmo}_Rtraj.nc")
            if size is None and mdtm is None:
                raise FloatSyncError("Rtraj absent or unavailable upstream")
            fp = f"{mdtm}|{size}"
            rtraj = (old or {}).get("rtraj")
            if not (parser_current and rtraj and (old or {}).get("rtraj_fp") == fp):
                raw = ftp_retrieve(ftp, f"{base}/{wmo}_Rtraj.nc")
                rtraj = parse_rtraj(raw, wmo, now)
                rtraj.update(mdtm=mdtm, size=size, sha256=hashlib.sha256(raw).hexdigest())
                changed = True
            row.update(rtraj=rtraj, rtraj_fp=fp)
        except Exception as exc:
            errors.append(f"Trajectory position refresh failed: {exc}")
            row.pop("rtraj_fp", None)

        # Exact published inventory and the existing latest-file position
        # candidate are independent of the time-based approximate estimate.
        try:
            entries = ftp_list_entries(ftp, f"{base}/profiles")
            fp = listing_fingerprint(entries)
            if not (parser_current and (old or {}).get("profiles") is not None and
                    (old or {}).get("profiles_fp") == fp):
                summary = summarize_profiles([n for n, _size, _mtime in entries], wmo)
                latest, parsed = summary.get("latest"), None
                if latest:
                    raw = ftp_retrieve(ftp, f"{base}/profiles/{latest['file']}")
                    parsed = parse_profile(raw, wmo, latest["cycle"], now)
                    parsed["sha256"] = hashlib.sha256(raw).hexdigest()
                row["profiles"] = dict(summary, latest_parse=parsed)
                changed = True
            row["profiles_fp"] = fp
        except Exception as exc:
            errors.append(f"Profile inventory/position refresh failed: {exc}")
            row.pop("profiles_fp", None)

        row["parser_version"] = PARSER_VERSION
        if changed:
            row["updated_at"] = now.isoformat()
        if not errors:
            row["checked_at"] = _utcnow().isoformat()
        else:
            row["error"] = "; ".join(errors)
        with self._lock:
            self._rows[key] = row
        if errors:
            # The cycle records a partial failure, without undoing successful
            # profile refreshes or advancing the fleet-wide full-success time.
            raise FloatSyncError(row["error"])
        return changed

'''+s[b:]
# Keep all position selection code intact; change only the monitoring payload.
s=s.replace('''"active": sum(f["status"] == STATUS_ACTIVE for f in floats),
            "overdue": sum(f["status"] == STATUS_OVERDUE for f in floats),
            "no_comm_60": sum(f["status"] == STATUS_NO_COMM_60 for f in floats),
            "no_data": sum(f["status"] == STATUS_NO_DATA for f in floats),
            "profiles_missing_total": sum(f["profiles_missing"] or 0 for f in floats),''','''"recent_profile": sum(f["data_status"] == STATUS_RECENT for f in floats),
            "profile_overdue": sum(f["data_status"] == STATUS_OVERDUE for f in floats),
            "no_recent_profile_60": sum(f["data_status"] == STATUS_NO_RECENT_60 for f in floats),
            "no_data": sum(f["data_status"] == STATUS_NO_DATA for f in floats),
            "approx_profiles_missed_total": (
                sum(f["approx_profiles_missed"] or 0 for f in floats)
                if any(f["approx_profiles_missed"] is not None for f in floats) else None
            ),
            "profile_dates_known": sum(f["last_profile_iso"] is not None for f in floats),''')
s=s.replace('''            "last_tx_iso": None,
            "last_tx_field": None,
            "last_tx_status_rt19": None,
            "last_tx_index": None,
            "last_tx_cycle": None,
            "communication_error": None,
            "days_since_last_tx": None,
            "expected_next_iso": None,
            "status": STATUS_NO_DATA,''','''            "last_profile_iso": None,
            "last_profile_juld": None,
            "last_profile_index": None,
            "last_profile_cycle": None,
            "last_profile_file": f"{wmo}_prof.nc",
            "last_profile_field": "JULD",
            "profile_date_error": None,
            "profile_checked_at": None,
            "days_since_last_profile": None,
            "expected_next_profile_iso": None,
            "approx_profiles_missed": None,
            "data_status": STATUS_NO_DATA,''')
s=s.replace('''            "traj_lagging_profiles": None,
''','')
s=s.replace('''            out["error"] = "awaiting first synchronization"
            return out''','''            out["error"] = "awaiting first synchronization"
            out["profile_date_error"] = "Awaiting published profile history"
            return out''')
s=s.replace('''            out["communication_error"] = row.get("reason") or "no record in Ifremer dac/incois"''','''            out["profile_date_error"] = row.get("reason") or "No profile history in Ifremer dac/incois"''')
a=s.index('        field = rtraj.get("last_tx_field")',s.index('    def _serve_row('));b=s.index('        return out',a)
s=s[:a]+'''        # Monitoring authority is strictly <WMO>_prof.nc:JULD. Do not use
        # the individual latest-cycle file, JULD_LOCATION, trajectory fields,
        # publication/processing timestamps, or local decoder history here.
        out["profile_checked_at"] = row.get("profile_checked_at") or row.get("checked_at")
        source_valid = (not old_parser and aggregate.get("file") == f"{wmo}_prof.nc" and
                        aggregate.get("platform_number") == str(wmo))
        value = _valid_juld(aggregate.get("juld"), now) if source_valid else None
        if value is not None:
            latest_date = juld_to_datetime(value)
            days = (now - latest_date).total_seconds() / 86400.0
            out.update(
                last_profile_iso=latest_date.isoformat(), last_profile_juld=value,
                last_profile_index=aggregate.get("measurement_index"),
                last_profile_cycle=aggregate.get("measurement_cycle"),
                expected_next_profile_iso=(latest_date + timedelta(days=PROFILE_INTERVAL_DAYS)).isoformat(),
                days_since_last_profile=days,
                approx_profiles_missed=math.floor(days / PROFILE_INTERVAL_DAYS),
                data_status=profile_data_status(days),
            )
        else:
            out["profile_date_error"] = row.get("profile_sync_error") or (
                f"No valid profile JULD in {wmo}_prof.nc" if source_valid else
                f"No verified {wmo}_prof.nc history available; no alternate timestamp is used"
            )
'''+s[b:]
p.write_text(s)
p=p.with_name('api.py');s=p.read_text();s=s.replace('Float communication monitoring — Ifremer/Argo GDAC upstream truth.', 'Float profile/data-recency monitoring — Ifremer/Argo GDAC published profiles.')
s=s.replace('derived fields (days-since, status, expected-next) are computed at serve', 'profile-derived fields (days-since, data status, expected-next) are computed at serve')
s=s.replace('"""Fleet communication rows + sync state + summary (cached upstream)."""', '"""Published profile-recency rows + sync state + summary (cached upstream)."""')
p.write_text(s)
