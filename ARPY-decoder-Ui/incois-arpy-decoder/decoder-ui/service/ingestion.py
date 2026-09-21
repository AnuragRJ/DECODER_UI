"""Ingestion registry — detects new arrivals from the active DataSource.

Semantics (phase 1 — discovery only, no automatic decoding):

* ``scan_now()`` pulls normalized records from the active source and
  dedupes them by content fingerprint: unchanged source data reproduces
  the same fingerprint → "already-seen"; any new/changed association
  yields an arrival row with ``state="new"``.
* The **first ever** scan is a silent baseline (existing raw stores must
  not badge the whole fleet as NEW DATA on service start).
* ``is_new_wmo`` distinguishes "newly seen WMO" from "newly arrived data
  for a known WMO" (resolved identity never seen before).
* State persists to ``<ARGO_UI_DATA_DIR>/ingestion.json`` so restarts are
  incremental, and history stays append-only for audit.
* ``ack()`` marks a float's arrivals seen (the UI's NEW DATA badge clears);
  it acknowledges visibility only — it never starts decoding.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from datasources import DataSource, NormalizedArrival, SourceStatus
from event_bus import DATA_DIR

MAX_ARRIVAL_ROWS = 500
# v2: local-source fingerprints are content-based (sha1 of payload, not
# mtime). A v1 state file keeps its arrival HISTORY but re-baselines the
# seen-map once, so re-materialized identical files are not rebadged.
STATE_VERSION = 2


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class IngestionRegistry:
    def __init__(self, state_path: Path | None = None) -> None:
        self._state_path = state_path or (DATA_DIR / "ingestion.json")
        self._source: Optional[DataSource] = None
        self._seen: dict[str, dict[str, Any]] = {}
        self._seen_identities: set[str] = set()
        self._arrivals: list[dict[str, Any]] = []
        self._baseline_done = False
        self._scan_count = 0
        self._last_scan_at: Optional[str] = None
        self._last_scan_records = 0
        self._last_new = 0
        self._lock = threading.Lock()
        self._poll_task: Optional[asyncio.Task] = None
        self._poll_interval_s = float(os.environ.get("INGESTION_POLL_INTERVAL", "60"))

    # ---------------- state ----------------
    @property
    def state_path(self) -> Path:
        return self._state_path

    def _load(self) -> None:
        try:
            if not self._state_path.is_file():
                return
            data = json.loads(self._state_path.read_text())
            if not isinstance(data, dict):
                return
            version = int(data.get("version") or 1)
            if version < STATE_VERSION:
                # Migration: keep the audit trail, rebaseline the dedupe map.
                self._arrivals = list(data.get("arrivals") or [])
                self._seen, self._seen_identities = {}, set()
                self._baseline_done = False
                return
            self._seen = dict(data.get("seen") or {})
            self._seen_identities = set(data.get("seen_identities") or [])
            self._arrivals = list(data.get("arrivals") or [])
            self._baseline_done = bool(data.get("baseline_done"))
        except Exception:
            # Corrupt state must never break the service; start fresh.
            self._seen, self._seen_identities, self._arrivals = {}, set(), []
            self._baseline_done = False

    def _save(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._state_path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(
                    {
                        "version": STATE_VERSION,
                        "seen": self._seen,
                        "seen_identities": sorted(self._seen_identities),
                        "arrivals": self._arrivals[-MAX_ARRIVAL_ROWS:],
                        "baseline_done": self._baseline_done,
                    },
                    indent=1,
                )
            )
            tmp.replace(self._state_path)
        except Exception:
            pass

    # ---------------- source ----------------
    def configure(self, source: DataSource) -> None:
        with self._lock:
            self._source = source
            self._load()

    # ---------------- scanning ----------------
    def scan_now(self) -> dict[str, Any]:
        """Pull records from the active source and register new arrivals."""
        if self._source is None:
            raise RuntimeError("no data source configured")
        records = self._source.scan()
        now = _utcnow()
        new_rows = 0
        with self._lock:
            baseline_scan = not self._baseline_done
            for rec in records:
                fp = rec.fingerprint
                if fp in self._seen:
                    continue  # already-seen source data
                identity_key = f"wmo:{rec.wmo}" if rec.wmo is not None else f"id:{rec.identifier}"
                is_new_identity = identity_key not in self._seen_identities
                self._seen[fp] = {"identifier": rec.identifier, "first_seen_at": now}
                self._seen_identities.add(identity_key)
                if baseline_scan:
                    continue  # initial inventory is NOT "new data"
                row = rec.to_dict()
                row.update(
                    {
                        "ingested_at": now,
                        "state": "new",
                        "is_new_wmo": bool(rec.wmo is not None and is_new_identity),
                    }
                )
                self._arrivals.append(row)
                new_rows += 1
            self._arrivals = self._arrivals[-MAX_ARRIVAL_ROWS:]
            self._baseline_done = True
            self._scan_count += 1
            self._last_scan_at = now
            self._last_scan_records = len(records)
            self._last_new = new_rows
            self._save()
        return {"records": len(records), "new_arrivals": new_rows, "baseline": baseline_scan}

    # ---------------- api payloads ----------------
    def arrivals(self, state: Optional[str] = None) -> list[dict[str, Any]]:
        with self._lock:
            rows = list(reversed(self._arrivals))
        if state:
            rows = [r for r in rows if r.get("state") == state]
        return rows

    def ack(self, identifier: str) -> dict[str, Any]:
        """Mark every arrival for a WMO/identifier as seen (UI badge clears)."""
        ident = str(identifier).strip()
        cleared = 0
        with self._lock:
            for row in self._arrivals:
                if row.get("state") != "new":
                    continue
                if str(row.get("wmo")) == ident or str(row.get("identifier")) == ident:
                    row["state"] = "seen"
                    cleared += 1
            self._save()
        return {"identifier": ident, "cleared": cleared}

    def status_payload(self) -> dict[str, Any]:
        src_status: SourceStatus = (
            self._source.status()
            if self._source is not None
            else SourceStatus(kind="none", configured=False, connected=False, detail="no data source configured")
        )
        payload = asdict(src_status)
        with self._lock:
            payload.update(
                {
                    "mode": os.environ.get("DATA_SOURCE", "local"),
                    # The live INCOIS operational feed is not provisioned yet:
                    # any non-ftp source is a development/test source and the
                    # UI must label it as such (never present it as INCOIS).
                    "test_mode": src_status.kind != "ftp",
                    "poll_interval_s": self._poll_interval_s,
                    "scans": self._scan_count,
                    "last_scan_at": self._last_scan_at,
                    "last_scan_records": self._last_scan_records,
                    "last_new_arrivals": self._last_new,
                    "arrivals_total": len(self._arrivals),
                    "new_arrivals": sum(1 for r in self._arrivals if r.get("state") == "new"),
                }
            )
        return payload

    # ---------------- background polling ----------------
    async def _poll_loop(self) -> None:
        while True:
            try:
                if self._source is not None:
                    await asyncio.to_thread(self.scan_now)
            except Exception:
                pass
            await asyncio.sleep(max(self._poll_interval_s, 5.0))

    def start(self) -> None:
        if self._poll_task is None:
            self._poll_task = asyncio.create_task(self._poll_loop())

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


ingestion = IngestionRegistry()


def build_source_from_env() -> DataSource:
    """Select the active source from configuration only (no credentials in code)."""
    mode = (os.environ.get("DATA_SOURCE") or "local").strip().lower()
    if mode == "ftp":
        from datasources.ftp import FTPDataSource

        return FTPDataSource(
            host=os.environ.get("FTP_HOST") or None,
            port=int(os.environ.get("FTP_PORT", "21")),
            user=os.environ.get("FTP_USER"),
            password=os.environ.get("FTP_PASSWORD"),
            root=os.environ.get("FTP_ROOT", "/"),
        )
    from datasources.local import LocalDataSource

    return LocalDataSource()
