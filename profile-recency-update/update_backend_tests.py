from pathlib import Path
root=Path('/home/user/ARPY-decoder-Ui/incois-arpy-decoder/decoder-ui/tests')
p=root/'test_fleet_status.py';s=p.read_text()
s=s.replace('fs.comm_status','fs.profile_data_status')
s=s.replace('"NO COMMUNICATION 60+ DAYS"','"NO RECENT PROFILE DATA 60+ DAYS"').replace('"ACTIVE"','"ACTIVE / RECENT PROFILE"').replace('"OVERDUE"','"PROFILE OVERDUE"')
s=s.replace('''        raise ftplib.error_perm("550 not found")

    def sendcmd''','''        for name, raw in self.profile_files.items():
            if path.endswith(name):
                return len(raw)
        raise ftplib.error_perm("550 not found")

    def sendcmd''')
s=s.replace('''        profile_files={"R2909999_025.nc": prof},
        mdtms={"2909999_Rtraj.nc": "20260909061405"},''','''        profile_files={"R2909999_025.nc": prof, "2909999_prof.nc": prof},
        mdtms={"2909999_Rtraj.nc": "20260909061405", "2909999_prof.nc": "20260909061405"},''')
s=s.replace('''assert fake.downloads == ["2909999_Rtraj.nc", "R2909999_025.nc"]''','''assert fake.downloads == ["2909999_prof.nc", "2909999_Rtraj.nc", "R2909999_025.nc"]''')
s=s.replace('row["status"]','row["data_status"]').replace('ghost["status"]','ghost["data_status"]')
s=s.replace('''    assert row["last_tx_field"] == "JULD_LAST_MESSAGE"
    assert abs(row["days_since_last_tx"] - 3.0) < 0.05
    assert row["expected_next_iso"] is not None
    assert row["traj_lagging_profiles"] is True  # profile (2d ago) newer than traj msg (3d ago)''','''    assert row["last_profile_field"] == "JULD"
    assert row["last_profile_file"] == "2909999_prof.nc"
    assert abs(row["days_since_last_profile"] - 2.0) < 0.05
    assert row["expected_next_profile_iso"] is not None
    assert row["approx_profiles_missed"] == 0  # inventory still has one exact gap
    assert "last_tx_iso" not in row''')
a=s.index('def test_serve_row_status_matrix():');b=s.index('# ---------------------------------------------------------------------------',a)
s=s[:a]+'''def test_serve_row_status_matrix():
    base = {"wmo": 1, "in_incois_dac": True, "parser_version": fs.PARSER_VERSION,
            "rtraj": {}, "profiles": {}, "error": None, "updated_at": None}
    for days, want in [(3, fs.STATUS_RECENT), (30, fs.STATUS_OVERDUE), (200, fs.STATUS_NO_RECENT_60)]:
        row = dict(base, profile_aggregate={"file": "1_prof.nc", "platform_number": "1",
                                           "juld": _juld(NOW - timedelta(days=days))})
        got = FleetSyncRegistry._serve_row(1, row, {"platform_type": "APEX"}, {}, NOW)
        assert got["data_status"] == want
        assert got["expected_next_profile_iso"] is not None
    nodata = FleetSyncRegistry._serve_row(1, base, {}, {}, NOW)
    assert nodata["data_status"] == "NO DATA"


'''+s[b:]
p.write_text(s)

p=root/'test_fleet_status_audit.py';s=p.read_text()
s=s.replace('''        "rtraj": rtraj or {},
        "profiles":''','''        "rtraj": rtraj or {},
        "profile_aggregate": dict(profile, file="2909999_prof.nc") if profile else None,
        "profile_aggregate_fp": "test",
        "profiles":''')
a=s.index('    if (\n',s.index('def test_all_32_existing_float_cache_records'));b=s.index('    p = r.get("profiles")',a)
s=s[:a]+'''    # The old committed cache has no full *_prof.nc history. Neither its
    # trajectory timestamps nor its latest individual profile may be used.
    assert got["data_status"] == "NO DATA"
    for key in ("last_profile_iso", "expected_next_profile_iso", "days_since_last_profile", "approx_profiles_missed"):
        assert got[key] is None
    assert got["profile_date_error"]
'''+s[b:]
s=s.replace('''sum(r["status"] == "NO DATA" for r in rows) == 4''','''sum(r["data_status"] == "NO DATA" for r in rows) == 32''')
s=s.replace('fs.comm_status','fs.profile_data_status')
s=s.replace('"NO COMMUNICATION 60+ DAYS"','"NO RECENT PROFILE DATA 60+ DAYS"').replace('"ACTIVE"','"ACTIVE / RECENT PROFILE"').replace('"OVERDUE"','"PROFILE OVERDUE"')
s=s.replace('''    tx = AS_OF - timedelta(days=days)
    r = _row({"last_tx_field": "JULD_LAST_MESSAGE", "last_tx_iso": tx.isoformat()}, now=AS_OF)
    got = fs.FleetSyncRegistry._serve_row(2909999, r, {}, {}, AS_OF)
    assert got["status"] == want
    assert got["days_since_last_tx"] == pytest.approx(days, abs=1e-11)''','''    date = AS_OF - timedelta(days=days)
    r = _row(profile={"platform_number": "2909999", "juld": _juld(date)}, now=AS_OF)
    got = fs.FleetSyncRegistry._serve_row(2909999, r, {}, {}, AS_OF)
    assert got["data_status"] == want
    assert got["days_since_last_profile"] == pytest.approx(days, abs=1e-8)''')
a=s.index('@pytest.mark.parametrize("iso",');b=s.index('def test_floating_juld_roundoff',a)
s=s[:a]+'''@pytest.mark.parametrize("value", [None, "bad", float("nan"), float("inf"), 999999, -1, _juld(AS_OF + timedelta(days=1))])
def test_bad_and_future_cached_profile_values_are_unavailable(value):
    row = _row(profile={"platform_number": "2909999", "juld": value}, now=AS_OF)
    got = fs.FleetSyncRegistry._serve_row(2909999, row, {}, {}, AS_OF)
    assert got["last_profile_iso"] is None and got["data_status"] == "NO DATA"


def test_profile_epoch_output_is_utc():
    date = datetime.fromisoformat("2026-09-11T05:30:00+05:30")
    row = _row(profile={"platform_number": "2909999", "juld": _juld(date)}, now=AS_OF)
    got = fs.FleetSyncRegistry._serve_row(2909999, row, {}, {}, AS_OF)
    assert got["last_profile_iso"] == "2026-09-11T00:00:00+00:00"
    assert got["expected_next_profile_iso"] == AS_OF.isoformat()
    assert got["data_status"] == fs.STATUS_RECENT
    assert got["approx_profiles_missed"] == 1  # Exact day 10 is still recent.


'''+s[b:]
s=s.replace('''    assert got["days_since_last_tx"] == 5  # Neither location nor profile time substituted.''','''    assert got["days_since_last_profile"] == pytest.approx(30)  # JULD, not location or trajectory time.''')
s=s.replace('''assert fake.downloads == ["2909999_Rtraj.nc", "R2909999_025.nc"]''','''assert fake.downloads == ["2909999_prof.nc", "2909999_Rtraj.nc", "R2909999_025.nc"]''')
s=s.replace('''    assert row["status"] == "NO DATA" and row["profile_count"] == 24''','''    assert row["data_status"] == fs.STATUS_RECENT and row["profile_count"] == 24
    assert row["approx_profiles_missed"] == 0''')
s=s.replace('''    del fake.mdtms["2909999_prof.nc"]
    assert reg.sync_now()''','''    del fake.mdtms["2909999_prof.nc"]
    del fake.profile_files["2909999_prof.nc"]
    assert reg.sync_now()''')
p.write_text(s)
