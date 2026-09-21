"""Unit tests for the incoming-data ingestion layer (phase 1: discovery).

Contract under test:

* ``NormalizedArrival`` is source-independent; fields are only populated
  when the source genuinely provides them (no invented cycles/coords).
* ``LocalDataSource`` discovers landing-zone associations, resolves WMO via
  real metadata tokens (WMO/PTT/IMEI), and leaves unknown tokens unresolved
  (never guesses a WMO).
* ``IngestionRegistry``: silent first-scan baseline, fingerprint dedupe
  ("already-seen"), known-WMO vs new-WMO classification, ack lifecycle,
  append-only persistence across restarts.
* ``FTPDataSource``: env-driven, never claims ``connected`` without a real
  session, yields no fabricated floats, keeps credentials out of status
  payloads and error text.
* The REST surface never reports FTP CONNECTED without a real connection.

Run with:
    cd decoder-ui && PYTHONPATH=service python -m pytest tests/test_ingestion.py -q
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import pytest

# Isolate every test from the deployment's persisted runtime state.
_TMP = tempfile.mkdtemp(prefix="decoder-ui-ingestion-test-")
os.environ["ARGO_UI_DATA_DIR"] = _TMP

from datasources import NormalizedArrival  # noqa: E402
from datasources.ftp import FTPDataSource  # noqa: E402
from datasources.local import LocalDataSource  # noqa: E402
from ingestion import IngestionRegistry  # noqa: E402


def _zone() -> Path:
    d = Path(tempfile.mkdtemp(prefix="ingest-zone-"))
    return d


def _stub_identity(**overrides):
    base = {"1902844": (1902844, "APEX"), "10255": (1902844, "APEX"), "2901304": (2901304, "APEX")}
    base.update(overrides)
    return lambda: base


def _src(zone: Path, **kw) -> LocalDataSource:
    return LocalDataSource(ingest_dir=zone, watch_raw_roots=False,
                           identity_index_fn=_stub_identity(**kw.pop("tokens", {})), **kw)


# ---------------------------------------------------------------------------
# 1. Local source normalization
# ---------------------------------------------------------------------------

def test_local_resolves_known_wmo_and_only_reports_real_fields():
    zone = _zone()
    d = zone / "1902844"
    d.mkdir()
    (d / "12.txt").write_text("telemetry payload A")
    (d / "13.txt").write_text("telemetry payload B")
    recs = _src(zone).scan()
    assert len(recs) == 1
    r = recs[0]
    assert r.wmo == 1902844
    assert r.platform == "APEX"
    assert r.identifier == "1902844"
    assert r.source_kind == "local"
    assert r.files == 2
    assert r.arrived_at  # real mtime surfaced
    # Nothing invented: cycle/JULD coordinates stay unset.
    assert r.cycle_number is None and r.juld is None
    assert r.latitude is None and r.longitude is None


def test_local_resolves_ptt_token_to_same_wmo():
    zone = _zone()
    d = zone / "10255"  # PTT identity for the same float
    d.mkdir()
    (d / "frame.eml").write_text("x")
    (r,) = _src(zone).scan()
    assert r.wmo == 1902844 and r.identifier == "10255"


def test_local_unknown_token_is_not_guessed():
    zone = _zone()
    d = zone / "2999137"
    d.mkdir()
    (d / "mystery.bin").write_text("?")
    (r,) = _src(zone).scan()
    assert r.wmo is None and r.platform is None
    assert r.identifier == "2999137"


def test_local_ignores_loose_files_at_zone_root():
    zone = _zone()
    (zone / "dropped-alone.txt").write_text("unassociated")
    assert _src(zone).scan() == []


# ---------------------------------------------------------------------------
# 2. Registry semantics
# ---------------------------------------------------------------------------

def test_registry_baseline_is_silent_and_dedupes():
    zone = _zone()
    (zone / "1902844").mkdir()
    (zone / "1902844" / "1.txt").write_text("a")
    reg = IngestionRegistry(state_path=Path(_TMP) / "r1.json")
    reg.configure(_src(zone))
    s1 = reg.scan_now()
    assert s1["baseline"] is True and s1["new_arrivals"] == 0
    s2 = reg.scan_now()
    assert s2["new_arrivals"] == 0  # already-seen source data
    assert reg.arrivals() == []


def test_registry_flags_new_data_for_known_wmo():
    zone = _zone()
    (zone / "1902844").mkdir()
    (zone / "1902844" / "1.txt").write_text("a")
    reg = IngestionRegistry(state_path=Path(_TMP) / "r2.json")
    reg.configure(_src(zone))
    reg.scan_now()  # baseline
    (zone / "1902844" / "2.txt").write_text("new burst")
    time.sleep(0.02)
    s = reg.scan_now()
    assert s["new_arrivals"] == 1
    (row,) = reg.arrivals(state="new")
    assert row["wmo"] == 1902844 and row["state"] == "new"
    assert row["is_new_wmo"] is False  # float already known → "new data", not new float
    assert row["files"] == 2


def test_registry_flags_genuinely_new_wmo():
    zone = _zone()
    reg = IngestionRegistry(state_path=Path(_TMP) / "r3.json")
    reg.configure(_src(zone))
    reg.scan_now()  # empty baseline
    d = zone / "2901304"
    d.mkdir()
    (d / "burst.txt").write_text("first-ever data")
    s = reg.scan_now()
    assert s["new_arrivals"] == 1
    (row,) = reg.arrivals(state="new")
    assert row["wmo"] == 2901304 and row["is_new_wmo"] is True


def test_registry_ack_clears_only_visibility():
    zone = _zone()
    d = zone / "1902844"
    d.mkdir()
    (d / "1.txt").write_text("a")
    reg = IngestionRegistry(state_path=Path(_TMP) / "r4.json")
    reg.configure(_src(zone))
    reg.scan_now(); reg.scan_now()  # baseline + nothing
    (d / "2.txt").write_text("b")
    reg.scan_now()
    assert len(reg.arrivals(state="new")) == 1
    out = reg.ack("1902844")
    assert out["cleared"] == 1 and reg.arrivals(state="new") == []
    # Ack never deletes history (append-only audit trail).
    assert len(reg.arrivals()) == 1


def test_registry_persists_across_restart():
    zone = _zone()
    d = zone / "1902844"
    d.mkdir()
    (d / "1.txt").write_text("a")
    path = Path(_TMP) / "r5.json"
    reg = IngestionRegistry(state_path=path)
    reg.configure(_src(zone))
    reg.scan_now()
    reg2 = IngestionRegistry(state_path=path)
    reg2.configure(_src(zone))
    assert reg2.scan_now()["baseline"] is False  # state recovered
    assert reg2.scan_now()["new_arrivals"] == 0  # no phantom re-badge


# ---------------------------------------------------------------------------
# 3. Content-based identity (no mtime false positives)
# ---------------------------------------------------------------------------

def test_identical_content_re_materialized_is_not_new():
    """Same payload arriving with a fresh mtime (mirror sync, restore,
    sandbox re-provisioning) is already-seen — no spurious NEW DATA."""
    zone = _zone()
    d = zone / "1902844"
    d.mkdir()
    (d / "frame.txt").write_bytes(b"payload-AAA-1234")
    reg = IngestionRegistry(state_path=Path(_TMP) / "c1.json")
    reg.configure(_src(zone))
    reg.scan_now()  # baseline
    time.sleep(0.02)
    (d / "frame.txt").unlink()
    (d / "frame.txt").write_bytes(b"payload-AAA-1234")  # identical bytes, new mtime
    assert reg.scan_now()["new_arrivals"] == 0
    (d / "frame.txt").write_bytes(b"payload-BBB-9999")  # genuinely different
    assert reg.scan_now()["new_arrivals"] == 1


def test_v1_state_migrates_silently_keeping_history():
    zone = _zone()
    d = zone / "1902844"
    d.mkdir()
    (d / "frame.txt").write_text("x")
    path = Path(_TMP) / "mig.json"
    # Simulate a pre-upgrade (v1) state file with a 'new' arrival row.
    path.write_text('{"version": 1, "seen": {"fp": {}}, "seen_identities": ["wmo:1902844"], '
                    '"arrivals": [{"wmo": 1902844, "state": "new", "identifier": "1902844"}], '
                    '"baseline_done": true}')
    reg = IngestionRegistry(state_path=path)
    reg.configure(_src(zone))
    s = reg.scan_now()
    assert s["baseline"] is True and s["new_arrivals"] == 0  # silent rebaseline
    assert len(reg.arrivals()) == 1  # pre-existing history row kept


# ---------------------------------------------------------------------------
# 4. FTP source honesty
# ---------------------------------------------------------------------------

def test_ftp_unconfigured_is_honest():
    src = FTPDataSource()
    st = src.status()
    assert st.configured is False and st.connected is False
    assert "no FTP_HOST" in st.detail
    assert src.scan() == []  # nothing fabricated


def test_ftp_failed_connection_never_leaks_credentials():
    src = FTPDataSource(host="127.0.0.1", port=9, user="op-user", password="s3cret!", root="/in", connect_timeout_s=1.5)
    recs = src.scan()
    st = src.status()
    assert recs == [] and st.configured is True and st.connected is False
    blob = f"{st.detail} {st.last_error}"
    assert "s3cret!" not in blob and "op-user" not in blob
    assert st.detail.startswith("ftp://"), st.detail  # host/port/root are not credentials


def test_status_payload_never_fabricates_connection():
    reg = IngestionRegistry(state_path=Path(_TMP) / "r6.json")
    reg.configure(FTPDataSource(host="127.0.0.1", port=9, connect_timeout_s=1.5))
    payload = reg.status_payload()
    assert payload["mode"] in ("local", "ftp")
    assert payload["connected"] is False and payload["configured"] is True
    assert payload["kind"] == "ftp" and payload["test_mode"] is False  # real ftp mode, honestly disconnected


def test_local_status_labeled_dev_source():
    reg = IngestionRegistry(state_path=Path(_TMP) / "r7.json")
    reg.configure(_src(_zone()))
    payload = reg.status_payload()
    assert payload["kind"] == "local" and payload["test_mode"] is True
