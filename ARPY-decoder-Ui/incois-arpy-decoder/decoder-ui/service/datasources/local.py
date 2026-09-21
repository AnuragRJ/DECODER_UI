"""Local data source — file-based discovery of incoming float telemetry.

This source drives today's workstation and remains the reference/test source:

* It keeps watching the SAME raw input roots the decoder has always used
  (:func:`path_resolver.find_raw_input_directories`), so existing local
  discovery keeps working and file stats changes for a known float surface
  as "newly arrived data for a known WMO".
* It additionally watches a dedicated landing zone (``LOCAL_INGEST_DIR``,
  default ``<ARGO_UI_DATA_DIR>/incoming``) where operators — or the INCOIS
  feed bridge once provisioned — drop new material. Each *subdirectory* of
  the landing zone is one float association (dir name = WMO / PTT / IMEI
  token). Loose files at the zone root are intentionally ignored: with no
  authoritative INCOIS packaging spec we must not guess associations.

Identity resolution is purely metadata-driven (WMO ↔ PTT ↔ IMEI via the
existing multi-CSV registries); no float list is hardcoded anywhere.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from . import NormalizedArrival, SourceStatus, content_fingerprint

import path_resolver
from event_bus import DATA_DIR

_TELEMETRY_SUFFIXES = {".txt", ".eml", ".sbd", ".bin", ".dat", ".msg", ".log"}
_IDENTITY_CACHE_TTL_S = 300.0


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def build_identity_index() -> dict[str, tuple[int, Optional[str]]]:
    """Map identity tokens → (wmo, platform) from real float metadata only.

    Tokens: WMO (str), PTT (raw and zero-stripped), IMEI. Values come from
    the same metadata backends that power /api/presets — nothing invented.
    """
    index: dict[str, tuple[int, Optional[str]]] = {}
    try:
        for preset in path_resolver.build_dynamic_float_presets():
            wmo = int(preset["wmo"])
            platform = preset.get("platform_type") or None
            index.setdefault(str(wmo), (wmo, platform))
    except Exception:
        pass
    try:
        from argo_decoder.metadata.multi_csv_loader import MultiCsvLoader

        for mdir in path_resolver.find_metadata_directories(path_resolver.PROJECT_ROOT):
            try:
                loader = MultiCsvLoader(mdir)
            except Exception:
                continue
            for f in loader.iter_floats():
                try:
                    wmo = int(f.wmo)
                except Exception:
                    continue
                platform = index.get(str(wmo), (wmo, None))[1]
                try:
                    info = loader.load_info(wmo)
                    platform = platform or getattr(info, "float_type", None) or None
                    ptt = str(getattr(info, "ptt", "") or "").strip()
                    if ptt:
                        index.setdefault(ptt, (wmo, platform))
                        index.setdefault(ptt.lstrip("0") or ptt, (wmo, platform))
                except Exception:
                    continue
                try:
                    meta = loader.load_meta(wmo)
                    imei = str(getattr(meta, "IMEI", "") or "").strip()
                    if imei:
                        index.setdefault(imei, (wmo, platform))
                except Exception:
                    continue
    except Exception:
        pass
    return index


def build_wmo_identity_map() -> dict[int, dict[str, str]]:
    """Map WMO -> {"ptt": ..., "imei": ...} from real registries only.

    Union of the csv4 metadata directories (via MultiCsvLoader — the same
    backend powering /api/presets) and the single-file registry CSVs
    (wmo/ptt/imei columns). csv4 wins on conflict (authoritative per-float
    metadata); registries only fill gaps. Empty strings when no identity is
    on record — never guessed.

    Powers the Float Status "Internal ID" display column (identity only,
    never a communication signal). Deliberately standalone: ingestion's
    build_identity_index() behavior above is frozen.
    """
    out: dict[int, dict[str, str]] = {}
    # 1. csv4 metadata directories (authoritative per-float records).
    try:
        from argo_decoder.metadata.multi_csv_loader import MultiCsvLoader

        try:
            mdirs = path_resolver.find_metadata_directories(path_resolver.PROJECT_ROOT)
        except Exception:
            mdirs = []
        for mdir in mdirs:
            try:
                loader = MultiCsvLoader(mdir)
            except Exception:
                continue
            try:
                floats = list(loader.iter_floats())
            except Exception:
                continue
            for f in floats:
                try:
                    wmo = int(f.wmo)
                except Exception:
                    continue
                try:
                    info = loader.load_info(wmo)
                    ptt = str(getattr(info, "ptt", "") or "").strip()
                except Exception:
                    ptt = ""
                try:
                    meta = loader.load_meta(wmo)
                    imei = str(getattr(meta, "IMEI", "") or "").strip()
                except Exception:
                    imei = ""
                slot = out.setdefault(wmo, {"ptt": "", "imei": ""})
                if ptt and not slot["ptt"]:
                    slot["ptt"] = ptt
                if imei and not slot["imei"]:
                    slot["imei"] = imei
    except Exception:
        pass
    # 2. Single-file registry CSVs (wmo/ptt/imei columns) fill gaps only.
    try:
        import csv as _csv

        try:
            rfiles = path_resolver.find_registry_files(path_resolver.PROJECT_ROOT)
        except Exception:
            rfiles = []
        for rfile in rfiles:
            try:
                fh = open(rfile, "r", encoding="utf-8-sig")
            except OSError:
                continue
            try:
                reader = _csv.DictReader(fh)
                for row in reader:
                    try:
                        wmo_s = (row.get("wmo") or "").strip()
                        if not wmo_s.isdigit():
                            continue
                        slot = out.setdefault(int(wmo_s), {"ptt": "", "imei": ""})
                        ptt = (row.get("ptt") or "").strip()
                        imei = (row.get("imei") or "").strip()
                        if ptt and not slot["ptt"]:
                            slot["ptt"] = ptt
                        if imei and not slot["imei"]:
                            slot["imei"] = imei
                    except Exception:
                        continue
            finally:
                try:
                    fh.close()
                except Exception:
                    pass
    except Exception:
        pass
    return out


def _dir_stats(d: Path) -> list[tuple[str, int, float, Path]]:
    out: list[tuple[str, int, float, Path]] = []
    try:
        for f in sorted(d.rglob("*")):
            try:
                if f.is_file() and not f.name.startswith("."):
                    st = f.stat()
                    out.append((str(f.relative_to(d)), st.st_size, st.st_mtime, f))
            except OSError:
                continue
    except OSError:
        pass
    return out


def _content_key(rel: str, size: int, mtime: int, file_path: Path, big_cutoff: int = 50 * 1024 * 1024) -> tuple[str, int, str]:
    """Dedupe key component for a file: (name, size, content-hash).

    Content (not mtime) drives "new vs already-seen": identical telemetry
    re-materialized elsewhere (backup restore, mirror sync, sandbox
    re-provisioning) must NOT badge as new arrivals, while any genuinely
    different payload must. Tiny local files → cheap full hash per scan;
    oversized files fall back to name+size+mtime (documented compromise).
    """
    if size > big_cutoff:
        return (rel, size, f"meta:{mtime}")
    try:
        h = hashlib.sha1()
        with file_path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return (rel, size, f"sha1:{h.hexdigest()}")
    except OSError:
        return (rel, size, f"meta:{mtime}")


def _collect_float_stats(root: Path, tokens: set[str]) -> list[tuple[str, int, float, Path]]:
    """Stats of files associated with any identity token under a raw root.

    Mirrors the discovery semantics the workstation already uses for
    decoding (token-named subdirectory, flat files prefixed by token,
    archive/cycle/<token>) — enriched with size/mtime/real-path for
    content-based dedupe. Rel ids are prefixed so two roots can never alias.
    """
    found: list[tuple[str, int, float, Path]] = []
    tag = f"{root.parent.name}/{root.name}"
    try:
        if not root.is_dir():
            return found
        for item in root.iterdir():
            try:
                if item.is_dir() and item.name in tokens:
                    for rel, size, mt, p in _dir_stats(item):
                        found.append((f"{tag}/{item.name}/{rel}", size, mt, p))
                elif item.is_file() and not item.name.startswith("."):
                    if any(tok and tok in item.name for tok in tokens):
                        st = item.stat()
                        found.append((f"{tag}/{item.name}", st.st_size, st.st_mtime, item))
            except OSError:
                continue
        for tok in tokens:
            cand = root / "archive" / "cycle" / tok
            if cand.is_dir():
                for rel, size, mt, p in _dir_stats(cand):
                    found.append((f"{tag}/archive/cycle/{tok}/{rel}", size, mt, p))
    except OSError:
        pass
    return found


class LocalDataSource:
    """Watches local raw stores + the INCOMING landing zone."""

    kind = "local"

    def __init__(
        self,
        ingest_dir: Path | None = None,
        watch_raw_roots: bool = True,
        identity_index_fn: Callable[[], dict[str, tuple[int, Optional[str]]]] | None = None,
    ) -> None:
        env_dir = __import__("os").environ.get("LOCAL_INGEST_DIR")
        self.ingest_dir = Path(env_dir).expanduser() if env_dir else (ingest_dir or (DATA_DIR / "incoming"))
        try:
            self.ingest_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        self.watch_raw_roots = watch_raw_roots
        self._identity_index_fn = identity_index_fn or build_identity_index
        self._identity_index: dict[str, tuple[int, Optional[str]]] = {}
        self._identity_built_at = 0.0
        self._last_scan_ok: Optional[bool] = None
        self._last_error: Optional[str] = None
        self._last_scan_at: Optional[str] = None
        self._roots_seen = 0

    # -- internal ---------------------------------------------------------
    def _identity(self) -> dict[str, tuple[int, Optional[str]]]:
        now = time.time()
        if now - self._identity_built_at > _IDENTITY_CACHE_TTL_S or not self._identity_index:
            self._identity_index = self._identity_index_fn()
            self._identity_built_at = now
        return self._identity_index

    @staticmethod
    def _record(fp: str, token: str, stats: list[tuple[str, int, float]], assoc: tuple[int | None, str | None] | None, source_id: str, files: int) -> NormalizedArrival:
        wmo: Optional[int] = None
        platform: Optional[str] = None
        if assoc is not None:
            wmo, platform = assoc
        newest = max((m for (_n, _s, m, *_rest) in stats), default=0.0)
        return NormalizedArrival(
            fingerprint=fp,
            identifier=token,
            wmo=wmo,
            platform=platform,
            source_id=source_id,
            source_kind=LocalDataSource.kind,
            arrived_at=_iso(newest) if newest else "",
            files=files,
        )

    def _resolve_token(self, token: str) -> tuple[int | None, str | None] | None:
        idx = self._identity()
        if token in idx:
            return idx[token]
        stripped = token.lstrip("0")
        if stripped in idx:
            return idx[stripped]
        return None

    # -- DataSource interface --------------------------------------------
    def scan(self) -> list[NormalizedArrival]:
        records: list[NormalizedArrival] = []
        try:
            # 1. Landing zone: one association per subdirectory (no guessing).
            zone_records = 0
            if self.ingest_dir.is_dir():
                for child in sorted(self.ingest_dir.iterdir()):
                    try:
                        if not child.is_dir() or child.name.startswith("."):
                            continue
                        stats = _dir_stats(child)
                        if not stats:
                            continue
                        keys = [_content_key(rel, size, mt, path) for (rel, size, mt, path) in stats]
                        fp = content_fingerprint(self.kind, f"zone:{child.name}", keys)
                        files = sum(1 for (n, _s, _m, _p) in stats if Path(n).suffix.lower() in _TELEMETRY_SUFFIXES) or len(stats)
                        records.append(
                            self._record(fp, child.name, stats, self._resolve_token(child.name), f"incoming/{child.name}", files)
                        )
                        zone_records += 1
                    except OSError:
                        continue

            # 2. Existing raw roots: per-known-float fingerprints.
            root_records = 0
            if self.watch_raw_roots:
                idx = self._identity()
                by_wmo: dict[int, set[str]] = {}
                for tok, (wmo, _plat) in idx.items():
                    by_wmo.setdefault(wmo, set()).add(tok)
                roots = path_resolver.find_raw_input_directories(path_resolver.PROJECT_ROOT)
                self._roots_seen = len(roots)
                for wmo, tokens in sorted(by_wmo.items()):
                    stats_all: list[tuple[str, int, float, Path]] = []
                    for root in roots:
                        stats_all.extend(_collect_float_stats(root, tokens))
                    if not stats_all:
                        continue
                    # Dedupe identical content seen in overlapping roots.
                    keys = {_content_key(rel, size, mt, path) for (rel, size, mt, path) in stats_all}
                    keys_sorted = sorted(keys)
                    fp = content_fingerprint(self.kind, f"wmo:{wmo}", keys_sorted)
                    platform = idx.get(str(wmo), (wmo, None))[1]
                    files = len(keys_sorted)
                    records.append(self._record(fp, str(wmo), stats_all, (wmo, platform), f"raw-store/wmo:{wmo}", files))
                    root_records += 1

            self._last_scan_ok = True
            self._last_error = None
            self._last_scan_at = _iso(time.time())
            self._detail = f"landing zone {self.ingest_dir} ({zone_records} associations) + {self._roots_seen} raw root(s) ({root_records} floats)"
            return records
        except Exception as exc:  # never bubble up — status() carries it
            self._last_scan_ok = False
            self._last_error = str(exc)
            self._last_scan_at = _iso(time.time())
            return []

    _detail: str = "not scanned yet"

    def status(self) -> SourceStatus:
        return SourceStatus(
            kind=self.kind,
            configured=True,
            connected=bool(self._last_scan_ok),
            detail=self._detail,
            last_scan_at=self._last_scan_at,
            last_error=self._last_error,
        )
