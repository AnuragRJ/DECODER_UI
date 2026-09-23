"""Cache and background execution for the Argo Format Checker.

Persists per-WMO format-check results to disk and manages background
execution so that checker runs never block the fleet-status API.

Cache file: $DATA_DIR/fleet_status/format_checker.json
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from format_checker import (
    CHECKER_COMMIT,
    CHECKER_VERSION,
    CheckResult,
    STATUS_CHECKING,
    STATUS_CHECKER_ERROR,
    STATUS_INCOMPLETE,
    STATUS_NOT_CHECKED,
    checker_available,
    classify_files,
    discover_files,
    ensure_checker,
    not_checked_result,
    run_check,
)

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CACHE_PATH = DATA_DIR / "fleet_status" / "format_checker.json"
MAX_CONCURRENT_CHECKS = 1


class FormatCheckerCache:
    """Thread-safe cache for format-check results with background execution."""

    def __init__(self) -> None:
        self._cache: dict[int, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._queue: OrderedDict[int, bool] = OrderedDict()
        self._running: set[int] = set()
        self._task: asyncio.Task[None] | None = None
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _load(self) -> None:
        """Load cached results from disk."""
        if CACHE_PATH.is_file():
            try:
                data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
                self._cache = {int(k): v for k, v in data.items()}
                log.info("Format checker cache loaded: %d entries", len(self._cache))
            except Exception as exc:
                log.warning("Failed to load format checker cache: %s", exc)
                self._cache = {}
        else:
            self._cache = {}

    def _save(self) -> None:
        """Persist cache to disk atomically."""
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_PATH.with_suffix(".json.tmp")
        try:
            tmp.write_text(
                json.dumps(self._cache, indent=2, default=str),
                encoding="utf-8",
            )
            tmp.replace(CACHE_PATH)
        except Exception as exc:
            log.warning("Failed to save format checker cache: %s", exc)
            tmp.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get(self, wmo: int) -> dict[str, Any]:
        """Get the cached result for a WMO, or a not_checked placeholder."""
        entry = self._cache.get(wmo)
        if entry is None:
            return not_checked_result(wmo).to_dict()
        # If currently checking, mark status
        if wmo in self._running:
            result = dict(entry)
            result["status"] = STATUS_CHECKING
            result["stale"] = True
            return result
        # If queued, keep previous result but mark stale
        if wmo in self._queue:
            result = dict(entry)
            result["stale"] = True
            return result
        return entry

    def get_compact(self, wmo: int) -> dict[str, Any]:
        """Get a compact summary for the fleet-status table."""
        entry = self.get(wmo)
        return {
            "status": entry.get("status", STATUS_NOT_CHECKED),
            "accepted_files": entry.get("accepted_files", 0),
            "rejected_files": entry.get("rejected_files", 0),
            "total_files": entry.get("total_files", 0),
            "total_errors": entry.get("total_errors", 0),
            "total_warnings": entry.get("total_warnings", 0),
            "checked_at": entry.get("checked_at"),
            "stale": entry.get("stale", False),
        }

    def get_all_compact(self) -> dict[int, dict[str, Any]]:
        """Get compact summaries for all cached WMOs."""
        return {wmo: self.get_compact(wmo) for wmo in self._cache}

    def put(self, wmo: int, result: CheckResult) -> None:
        """Store a completed result."""
        self._cache[wmo] = result.to_dict()
        self._running.discard(wmo)
        self._save()
        log.info(
            "Format check result cached for WMO %d: %s (%d files, %d errors)",
            wmo, result.status, result.total_files, result.total_errors,
        )

    # ------------------------------------------------------------------
    # Cache invalidation
    # ------------------------------------------------------------------
    def invalidate_if_changed(
        self, wmo: int, new_fingerprints: dict[str, str]
    ) -> bool:
        """Check if file fingerprints changed since last check.

        If changed, marks the entry stale and returns True.
        """
        entry = self._cache.get(wmo)
        if entry is None:
            return True  # No cache → needs check
        old_fps = entry.get("fingerprints", {})
        if old_fps != new_fingerprints:
            entry["stale"] = True
            return True
        return False

    def mark_stale(self, wmo: int) -> None:
        """Explicitly mark a cached result as stale."""
        if wmo in self._cache:
            self._cache[wmo]["stale"] = True
            self._save()

    # ------------------------------------------------------------------
    # Background execution
    # ------------------------------------------------------------------
    async def enqueue(self, wmo: int) -> str:
        """Enqueue a format check for background execution.

        Returns the current status: 'queued' or 'checking'.
        """
        async with self._lock:
            if wmo in self._running:
                return STATUS_CHECKING
            self._queue[wmo] = True
            self._ensure_worker()
            return "queued"

    async def enqueue_stale(self, wmos: list[int]) -> int:
        """Enqueue all stale WMOs for re-checking. Returns count enqueued."""
        count = 0
        async with self._lock:
            for wmo in wmos:
                entry = self._cache.get(wmo)
                if entry and entry.get("stale"):
                    if wmo not in self._running:
                        self._queue[wmo] = True
                        count += 1
            if count > 0:
                self._ensure_worker()
        return count

    def _ensure_worker(self) -> None:
        """Ensure the background worker task is running."""
        if self._task is None or self._task.done():
            self._task = asyncio.ensure_future(self._worker())

    async def _worker(self) -> None:
        """Background worker that processes the check queue."""
        while True:
            async with self._lock:
                if not self._queue:
                    return
                wmo, _ = self._queue.popitem(last=False)
                self._running.add(wmo)

            try:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, self._run_check_sync, wmo
                )
                self.put(wmo, result)
            except Exception as exc:
                log.exception("Background format check failed for WMO %d", wmo)
                self.put(wmo, CheckResult(
                    wmo=wmo,
                    status=STATUS_CHECKER_ERROR,
                    checked_at=datetime.now(timezone.utc).isoformat(),
                    discovery={"files_found": 0, "files_not_found": 0,
                               "discovery_errors": [f"Worker error: {exc}"]},
                ))
            finally:
                self._running.discard(wmo)

            # Small delay between checks to be polite to FTP
            await asyncio.sleep(2)

    def _run_check_sync(self, wmo: int) -> CheckResult:
        """Synchronous format check execution (runs in executor)."""
        import ftplib

        # Ensure JAR is available
        try:
            ensure_checker()
        except Exception as exc:
            return CheckResult(
                wmo=wmo,
                status=STATUS_CHECKER_ERROR,
                checked_at=datetime.now(timezone.utc).isoformat(),
                discovery={"files_found": 0, "files_not_found": 0,
                           "discovery_errors": [f"Checker JAR unavailable: {exc}"]},
            )

        # Connect to FTP
        try:
            ftp = ftplib.FTP(timeout=60)
            ftp.connect("ftp.ifremer.fr", 21)
            ftp.login("anonymous", "format-checker@incois")
        except Exception as exc:
            return CheckResult(
                wmo=wmo,
                status=STATUS_INCOMPLETE,
                checked_at=datetime.now(timezone.utc).isoformat(),
                discovery={"files_found": 0, "files_not_found": 0,
                           "discovery_errors": [f"FTP connection failed: {exc}"]},
            )

        try:
            # Discover files
            classified, discovery = discover_files(wmo, ftp)
            if not classified:
                return CheckResult(
                    wmo=wmo,
                    status=STATUS_INCOMPLETE,
                    checked_at=datetime.now(timezone.utc).isoformat(),
                    discovery=discovery.__dict__,
                )

            # Build download list: (filename, subpath)
            files_to_download: list[tuple[str, str]] = []
            fingerprints: dict[str, str] = {}
            for fn, cat, cycle, fp in classified:
                subpath = "profiles" if cat in ("mono_profile", "bgc_profile") else ""
                files_to_download.append((fn, subpath))
                fingerprints[fn] = fp

            # Check if fingerprints changed (skip if unchanged)
            if not self.invalidate_if_changed(wmo, fingerprints):
                existing = self._cache.get(wmo)
                if existing and existing.get("status") not in (STATUS_NOT_CHECKED, STATUS_CHECKING):
                    log.info("Format check cache hit for WMO %d (fingerprints unchanged)", wmo)
                    existing["stale"] = False
                    return CheckResult(**{k: v for k, v in existing.items()
                                        if k in CheckResult.__dataclass_fields__})

            # Run the checker
            result = run_check(wmo, files_to_download, ftp)
            result.fingerprints = fingerprints
            return result
        finally:
            try:
                ftp.quit()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Post-sync hook
    # ------------------------------------------------------------------
    async def on_fleet_sync_complete(
        self, wmo_fingerprints: dict[int, dict[str, str]]
    ) -> None:
        """Called after fleet-status sync to detect changed files.

        wmo_fingerprints: {wmo: {filename: "size|mdtm", ...}}
        """
        stale_wmos = []
        for wmo, fps in wmo_fingerprints.items():
            if self.invalidate_if_changed(wmo, fps):
                stale_wmos.append(wmo)
        if stale_wmos:
            log.info(
                "Format checker: %d WMOs have changed files, scheduling re-check",
                len(stale_wmos),
            )
            await self.enqueue_stale(stale_wmos)
        self._save()

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        """Overall format checker status."""
        total = len(self._cache)
        checking = len(self._running)
        queued = len(self._queue)
        return {
            "cached_wmos": total,
            "checking": checking,
            "queued": queued,
            "checker_available": checker_available(),
            "checker_version": CHECKER_VERSION,
            "checker_commit": CHECKER_COMMIT,
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_instance: FormatCheckerCache | None = None


def get_cache() -> FormatCheckerCache:
    """Get or create the singleton cache instance."""
    global _instance
    if _instance is None:
        _instance = FormatCheckerCache()
    return _instance
