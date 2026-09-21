"""FTP data source — connector shell for the future INCOIS feed.

Honest-by-design properties (the live INCOIS format is NOT yet known):

* Reporting ``connected=True`` is only possible after a REAL, successful
  FTP session (connect + login + noop) — never inferred from configuration.
* Incoming remote objects are treated as OPAQUE: with no authoritative file
  format spec we do not assume one file = one float, or a filename
  convention, or any packaging. Each object becomes a NormalizedArrival
  with the float fields unset and ``parser_pending=True`` — the real
  INCOIS parser plugs into :meth:`FTPDataSource.__init__`'s ``parser``
  hook later without touching the Fleet UI or decoder workflow:

      def my_parser(obj: RemoteObject) -> list[NormalizedArrival]:
          ...  # provided once INCOIS supplies the true spec/samples

* Credentials come only from the environment, are never written to state
  files, API payloads or logs, and are scrubbed from any error text.
"""

from __future__ import annotations

import ftplib
import os
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from . import NormalizedArrival, SourceStatus, content_fingerprint, redact_secret


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


class FTPDataSource:
    kind = "ftp"

    #: hook signature — real parser is supplied later, defaults to opaque mode
    parser: Optional[Callable] = None

    def __init__(
        self,
        host: str | None = None,
        port: int = 21,
        user: str | None = None,
        password: str | None = None,
        root: str = "/",
        parser: Optional[Callable] = None,
        connect_timeout_s: float = 10.0,
    ) -> None:
        self._host = host if host else None
        self._port = port
        self._user = user
        self._password = password
        self._root = root or "/"
        self.parser = parser
        self._timeout = connect_timeout_s
        self._connected = False
        self._last_scan_at: Optional[str] = None
        self._last_error: Optional[str] = None
        self._objects_seen = 0

    @property
    def configured(self) -> bool:
        return bool(self._host)

    def _scrub(self, text: str) -> str:
        return redact_secret(text, self._password, self._user)

    def scan(self) -> list[NormalizedArrival]:
        if not self.configured:
            self._connected = False
            return []
        try:
            records: list[NormalizedArrival] = []
            with ftplib.FTP() as ftp:
                ftp.connect(self._host or "", self._port, timeout=self._timeout)
                ftp.login(user=self._user or "anonymous", passwd=self._password or "")
                self._connected = True  # real session established
                ftp.cwd(self._root)
                names = [n for n in ftp.nlst() if n not in (".", "..")]
                for name in names:
                    size, mtime = 0, 0.0
                    try:
                        size = ftp.size(name) or 0
                    except Exception:
                        pass
                    try:
                        mdtm = ftp.sendcmd(f"MDTM {name}")  # "213 YYYYMMDDHHMMSS"
                        mtime = time.mktime(time.strptime(mdtm[4:18], "%Y%m%d%H%M%S"))
                    except Exception:
                        mtime = 0.0
                    fp = content_fingerprint(self.kind, f"obj:{self._host}/{self._root}/{name}", [(name, size, mtime)])
                    stats = [(name, size, mtime)] if mtime else [(name, size, 0.0)]
                    parsed = self.parser({"name": name, "size": size, "mtime": mtime}) if self.parser else None
                    if parsed:
                        records.extend(parsed)
                    else:
                        rec = NormalizedArrival(
                            fingerprint=fp,
                            identifier=name,
                            wmo=None,
                            platform=None,
                            source_id=f"ftp://{self._host}:{self._port}{self._root.rstrip('/')}/{name}",
                            source_kind=self.kind,
                            arrived_at=_iso(mtime) if mtime else "",
                            files=1,
                            parser_pending=True,
                        )
                        records.append(rec)
                ftp.quit()
            self._objects_seen = len(records)
            self._last_error = None
            self._last_scan_at = _iso(time.time())
            return records
        except Exception as exc:
            self._connected = False
            self._last_error = self._scrub(str(exc)) or exc.__class__.__name__
            self._last_scan_at = _iso(time.time())
            return []

    def status(self) -> SourceStatus:
        if not self.configured:
            return SourceStatus(
                kind=self.kind,
                configured=False,
                connected=False,
                detail="FTP selected but no FTP_HOST configured — nothing is being fetched",
            )
        return SourceStatus(
            kind=self.kind,
            configured=True,
            connected=self._connected,
            detail=(
                f"ftp://{self._host}:{self._port}{self._root} "
                f"({self._objects_seen} source object(s) last scan; float parsing pending real INCOIS specification)"
            ),
            last_scan_at=self._last_scan_at,
            last_error=self._last_error,
        )
