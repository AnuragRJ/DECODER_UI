"""Source-independent ingestion abstraction for the INCOIS ARPY workstation.

This package defines the normalized arrival contract every data source must
produce — LOCAL raw-file drops today, INCOIS FTP/SFTP/API later. The decoder
and the Fleet UI never depend on the physical packaging of incoming source
objects: a source object may describe ONE float or MANY floats (or, until the
real INCOIS format is supplied, an opaque object whose parsing is deferred).

Contract — :class:`NormalizedArrival`
-------------------------------------
One record per *float-association* discovered in a scan. Fields are only
populated when the source genuinely provides them; nothing is invented:

``fingerprint``      stable dedupe key (source kind + identity + content stat)
``wmo``              WMO / PLATFORM_NUMBER once confidently resolved, else None
``identifier``       raw identity token found at the source (dir/file/object)
``platform``         platform type, only when resolvable from real metadata
``cycle_number``     only when the source actually carries a cycle identifier
``juld``             source-side data timestamp (arrival mtime / JULD), ISO
``latitude/longitude`` only when the source actually carries coordinates
``source_id``        concrete source object (relative path / remote object key)
``source_kind``      "local" | "ftp" | ... (matches DATA_SOURCE mode)
``arrived_at``       newest source-side data timestamp (ISO 8601)
``files``            number of underlying files/objects composing this record
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable


@dataclass
class NormalizedArrival:
    """One normalized float association discovered during a source scan."""

    fingerprint: str
    identifier: str
    source_id: str
    source_kind: str
    arrived_at: str
    wmo: Optional[int] = None
    platform: Optional[str] = None
    cycle_number: Optional[int] = None
    juld: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    files: int = 0
    parser_pending: bool = False  # opaque source object; real parser plugs in later

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SourceStatus:
    """Sanitized source description — never contains credentials."""

    kind: str
    configured: bool
    connected: bool
    detail: str
    test_mode: bool = False
    poll_interval_s: float = 60.0
    last_scan_at: Optional[str] = None
    last_error: Optional[str] = None


@runtime_checkable
class DataSource(Protocol):
    """Interface every incoming-data source implements.

    ``scan`` must be side-effect free with respect to the decoder: it only
    observes the source and returns normalized records. It MUST NOT raise —
    failures are reported through :meth:`status` instead.
    """

    kind: str

    def scan(self) -> list[NormalizedArrival]:
        ...

    def status(self) -> SourceStatus:
        ...


def content_fingerprint(kind: str, identity: str, stats: list[tuple[str, int, object]]) -> str:
    """Deterministic dedupe key: identity + (name, size, key³) of each object.

    ``key³`` is any stable per-object discriminator (mtime for remote
    objects, content hash for local files — see LocalDataSource).
    Unchanged data reproduces the same fingerprint ("already-seen source
    data"); any genuinely new/changed payload changes it naturally.
    """
    h = hashlib.sha1()
    h.update(kind.encode())
    h.update(identity.encode())
    for name, size, third in sorted(stats):
        h.update(f"{name}:{size}:{third}".encode())
    return h.hexdigest()


def redact_secret(text: str, *secrets: str | None) -> str:
    """Scrub credentials out of any error/log text before it can surface."""
    out = str(text)
    for secret in secrets:
        if secret:
            out = out.replace(secret, "***")
    return out
