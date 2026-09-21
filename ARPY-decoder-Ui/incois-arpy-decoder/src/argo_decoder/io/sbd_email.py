"""Iridium SBD e-mail parser.

The Coriolis decoder ingests Short Burst Data (SBD) messages delivered by
Iridium as RFC-822 e-mails (MIME multipart). The e-mails are stored on
disk as ``co_<ts>_<imei>_<cycle>_<profile>_<size>.txt`` files inside the
``rsync/archive/cycle/<imei>/`` tree.

Each e-mail has:

* A 7-bit inline text body containing session metadata
  (MOMSN, MTMSN, session time, GPS fix, CEPradius).
* An optional ``application/octet-stream`` attachment named
  ``<imei>.sbd`` containing the raw binary payload (up to 340 bytes
  for Iridium SBD; in practice 0 or 300 bytes for Provor/Arvor).

Payloads that are **0 bytes long** (session-status / "ping" messages
like the very first ``co_*_000004_*.txt`` file in the demo dataset) are
perfectly normal — they carry an updated GPS fix but no sensor data.

Non-goals
---------
This module is strictly about parsing I/O. It does **not** decode the
binary payload into scientific values; that is the job of the platform
plugins (see :mod:`argo_decoder.platforms.provor_ir_sbd`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path

# ---------------------------------------------------------------------------
# Regexes for the inline text/plain body of SBD e-mails
# ---------------------------------------------------------------------------

_MOMSN_RE = re.compile(r"^MOMSN:\s*(\d+)\s*$", re.MULTILINE)
_MTMSN_RE = re.compile(r"^MTMSN:\s*(\d+)\s*$", re.MULTILINE)
_SESSION_RE = re.compile(r"^Time of Session \(UTC\):\s*(.+?)\s*$", re.MULTILINE)
_STATUS_RE = re.compile(r"^Session Status:\s*([0-9A-Fa-fxX]+)\s*-\s*(.+)$", re.MULTILINE)
_SIZE_RE = re.compile(r"^Message Size \(bytes\):\s*(\d+)\s*$", re.MULTILINE)
_LOC_RE = re.compile(
    r"^Unit Location:\s*Lat\s*=\s*(-?\d+\.\d+)\s+Long\s*=\s*(-?\d+\.\d+)\s*$",
    re.MULTILINE,
)
_CEP_RE = re.compile(r"^CEPradius\s*=\s*(\d+)\s*$", re.MULTILINE)

# Iridium session times look like "Mon Jun 29 08:30:42 2020" (always UTC).
_SESSION_FMT = "%a %b %d %H:%M:%S %Y"


@dataclass(frozen=True)
class SbdSessionInfo:
    """Session metadata extracted from the text body of one SBD e-mail."""

    momsn: int | None = None
    mtmsn: int | None = None
    session_status_code: str | None = None
    session_status_text: str | None = None
    message_size_bytes: int = 0
    session_time_utc: datetime | None = None
    gps_lat: float | None = None
    gps_lon: float | None = None
    cep_radius_km: int | None = None


@dataclass
class SbdMessage:
    """One parsed SBD delivery (e-mail + optional binary payload)."""

    source_path: Path
    imei: str
    cycle: int
    profile: int
    rsync_size_bytes: int
    received_at: datetime | None = None
    session: SbdSessionInfo = field(default_factory=SbdSessionInfo)
    payload: bytes = b""

    @property
    def has_payload(self) -> bool:
        return len(self.payload) > 0


def _parse_session_text(body: str) -> SbdSessionInfo:
    """Extract session fields from the text/plain body of an SBD email."""

    def _group(pattern: re.Pattern[str], text: str, group: int = 1) -> str | None:
        m = pattern.search(text)
        return m.group(group) if m else None

    momsn_s = _group(_MOMSN_RE, body)
    mtmsn_s = _group(_MTMSN_RE, body)
    size_s = _group(_SIZE_RE, body)
    status_code = _group(_STATUS_RE, body, 1)
    status_text = _group(_STATUS_RE, body, 2)

    session_dt: datetime | None = None
    s = _group(_SESSION_RE, body)
    if s:
        try:
            session_dt = datetime.strptime(s.strip(), _SESSION_FMT).replace(tzinfo=UTC)
        except ValueError:
            session_dt = None

    gps_lat: float | None = None
    gps_lon: float | None = None
    m = _LOC_RE.search(body)
    if m:
        gps_lat = float(m.group(1))
        gps_lon = float(m.group(2))

    cep_s = _group(_CEP_RE, body)
    cep = int(cep_s) if cep_s is not None else None

    return SbdSessionInfo(
        momsn=int(momsn_s) if momsn_s is not None else None,
        mtmsn=int(mtmsn_s) if mtmsn_s is not None else None,
        session_status_code=status_code.strip() if status_code else None,
        session_status_text=status_text.strip() if status_text else None,
        message_size_bytes=int(size_s) if size_s is not None else 0,
        session_time_utc=session_dt,
        gps_lat=gps_lat,
        gps_lon=gps_lon,
        cep_radius_km=cep,
    )


_FILENAME_RE = re.compile(
    r"^co_(?P<ts>\d{8}T\d{6}Z)_(?P<imei>\d{15})_(?P<cycle>\d{6})_(?P<prof>\d{6})_(?P<size>\d+)\.txt$"
)


def parse_filename(name: str) -> tuple[str, int, int, int, datetime] | None:
    """Parse a ``co_*.txt`` filename into its components.

    Returns ``(imei, cycle, profile, rsync_size_bytes, received_at)`` or
    ``None`` if the name doesn't match the expected pattern.
    """
    m = _FILENAME_RE.match(name)
    if not m:
        return None
    ts = datetime.strptime(m.group("ts"), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    return (
        m.group("imei"),
        int(m.group("cycle")),
        int(m.group("prof")),
        int(m.group("size")),
        ts,
    )


def parse_sbd_email(path: str | Path) -> SbdMessage:
    """Parse one ``co_*.txt`` SBD e-mail file from disk.

    Raises :class:`ValueError` if the file cannot be parsed as an SBD email
    (missing filename pattern, no MIME structure, etc.).
    """
    p = Path(path)
    with p.open("rb") as fh:
        raw = fh.read()
    session, payload = parse_sbd_bytes(raw)

    parsed = parse_filename(p.name)
    if parsed is None:
        raise ValueError(f"Not an SBD co_*.txt filename: {p.name!r}")
    imei, cycle, profile, rsync_size, recv_dt = parsed
    return SbdMessage(
        source_path=p,
        imei=imei,
        cycle=cycle,
        profile=profile,
        rsync_size_bytes=rsync_size,
        received_at=recv_dt,
        session=session,
        payload=payload,
    )


def parse_sbd_bytes(raw: bytes) -> tuple[SbdSessionInfo, bytes]:
    """Parse the bytes of an SBD e-mail (RFC-822 MIME).

    Returns ``(session_info, binary_payload)``. If ``raw`` does not look
    like a MIME message (no ``MIME-Version`` / ``Content-Type`` headers),
    it is treated as a bare binary SBD payload and the returned session
    info is empty.
    """
    if not raw:
        return SbdSessionInfo(message_size_bytes=0), b""

    head = raw[:2048]
    looks_like_email = b"MIME-Version" in head or head.lstrip().startswith(b"From ")
    if not looks_like_email:
        return SbdSessionInfo(message_size_bytes=len(raw)), bytes(raw)

    try:
        msg: EmailMessage = BytesParser(policy=policy.default).parsebytes(raw)
    except Exception:
        return SbdSessionInfo(message_size_bytes=len(raw)), bytes(raw)

    text_body = ""
    payload = b""
    if msg.is_multipart():
        for part in msg.walk():
            disp = part.get_content_disposition()
            ctype = part.get_content_type()
            if disp == "attachment":
                blob = part.get_payload(decode=True)
                if blob:
                    payload = bytes(blob)
                    break
            if ctype == "text/plain" and disp in (None, "inline"):
                try:
                    text_body = part.get_content() or ""
                except (LookupError, UnicodeDecodeError):
                    text_body = ""
    else:
        try:
            text_body = msg.get_content() or ""
        except (LookupError, UnicodeDecodeError):
            text_body = ""
    session = _parse_session_text(text_body)
    return session, payload


__all__ = [
    "SbdMessage",
    "SbdSessionInfo",
    "parse_filename",
    "parse_sbd_email",
]
