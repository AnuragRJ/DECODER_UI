"""Rsync manifest + cycle-file discovery.

Walks the rsync tree and returns an ordered list of input files per WMO/IMEI.
Phase 0 implements discovery for Iridium SBD (transmission type 3), which is
what the demo dataset exercises.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from argo_decoder.config.models import DecoderConfig, TransmissionType

_CO_FILE_RE = re.compile(
    r"^co_(?P<ts>\d{8}T\d{6}Z)_(?P<imei>\d{15})_(?P<cycle>\d{6})_(?P<prof>\d{6})_(?P<size>\d+)\.txt$"
)
_RSYNC_LOG_RE = re.compile(r"^rsync_(?P<ts>\d{8}T\d{6}Z)\.txt$")
_ARGOS_FMT1_RE = re.compile(
    r"^(?P<ptt>\d{5,6})_"
    r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})-"
    r"(?P<hour>\d{2})-(?P<minute>\d{2})-(?P<second>\d{2})_"
    r"(?P<wmo>\d{7})_(?P<cycle>\d{1,6})(?:_.*)?\.txt$"
)
_ARGOS_DATE_RE = re.compile(
    r"^(?P<ptt>\d{5,6})_"
    r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})_"
    r"(?P<wmo>\d{7})_(?P<cycle>\d{1,6})(?:_.*)?\.txt$"
)
_ARGOS_FMT2_RE = re.compile(r"^(?P<ptt>\d{5,6})_(?P<wmo>\d{7})_(?P<cycle>\d{1,6})(?:_.*)?\.txt$")
_ARGOS_FALLBACK_RE = re.compile(r"(?P<ptt>\d{5,6}).*?(?P<wmo>\d{7})_(?P<cycle>\d{3,6}).*\.txt$")
#: ``<ptt>_<YYYY-MM-DD>.txt`` -- one Argos ground-station dump per satellite
#: pass, carrying neither WMO nor cycle number in the file name. Every other
#: pattern above can read the cycle straight off the name; here it exists only
#: inside the telemetry, so discovery records :data:`CYCLE_FROM_TELEMETRY` and
#: the APEX decoder substitutes the transmitted profile id (see
#: ``ApexArgosDecoder`` / ``output_cycle_number``). Ordering by date keeps the
#: files in transmission order for the decoder's own sequencing.
_ARGOS_PTT_DATE_RE = re.compile(
    r"^(?P<ptt>\d{5,6})_(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})\.txt$"
)

#: Sentinel cycle for files whose name carries no cycle number. Negative so it
#: can never collide with a real Argos cycle, and so anything that reaches an
#: output without being replaced is obvious rather than silently plausible.
CYCLE_FROM_TELEMETRY = -1


@dataclass(frozen=True)
class CycleFile:
    """One raw transmission file (Iridium SBD e-mail or ARGOS cycle file)."""

    path: Path
    imei: str
    cycle: int
    profile: int
    size_bytes: int
    received_at: str  # ISO "YYYYmmddTHHMMSSZ"

    @property
    def wmo(self) -> int | None:
        # Populated by the pipeline once we map IMEI→WMO from meta/info.
        return getattr(self, "_wmo", None)


@dataclass
class RsyncIndex:
    """Index of raw cycle files grouped by IMEI."""

    files_by_imei: dict[str, list[CycleFile]] = field(default_factory=dict)

    def all_imeis(self) -> Iterable[str]:
        yield from sorted(self.files_by_imei.keys())

    def files_for(self, imei: str) -> list[CycleFile]:
        return list(self.files_by_imei.get(imei, []))

    def files_for_wmo(self, wmo: int, *, ptt_to_wmo: dict[str, int]) -> list[CycleFile]:
        out: list[CycleFile] = []
        for imei in list(self.files_by_imei):
            if ptt_to_wmo.get(imei) == wmo:
                out.extend(self.files_by_imei[imei])
        return sorted(out, key=lambda c: (c.cycle, c.profile, c.received_at))


def discover(config: DecoderConfig) -> RsyncIndex:
    """Discover raw cycle files for the given configuration.

    Implemented for IRIDIUM_SBD at Phase 0. Phase 4 extends to ARGOS, RUDICS,
    and Remocean.
    """
    index = RsyncIndex()

    if config.transmission_type == TransmissionType.IRIDIUM_SBD:
        return _discover_sbd(config)
    if config.transmission_type == TransmissionType.ARGOS:
        return _discover_argos(config)
    # RUDICS and Remocean are later-phase scope; return an empty index so the
    # null/skeleton pipeline can still start.
    return index


#: ARVOR-I operator delivery files: ``redacted_imei_<prefix>_<momsn>.eml``
#: with the SBD payload in a same-named ``.sbd`` sidecar. Carries no cycle
#: number -- cycles come from the telemetry (CYCLE_FROM_TELEMETRY), exactly
#: as for the demo ``co_*`` files whose suffix is untrustworthy.
_ARVOR_EML_RE = re.compile(r"^redacted_imei_(?P<prefix>\d+)_(?P<momsn>\d+)\.eml$")


def _discover_sbd(config: DecoderConfig) -> RsyncIndex:
    index = RsyncIndex()
    archive = Path(config.paths.rsync_data_dir)
    if not archive.exists():
        return index
    for imei_dir in sorted(p for p in archive.iterdir() if p.is_dir()):
        files: list[CycleFile] = []
        for entry in sorted(imei_dir.iterdir()):
            m = _CO_FILE_RE.match(entry.name)
            if m:
                files.append(
                    CycleFile(
                        path=entry,
                        imei=m.group("imei"),
                        cycle=int(m.group("cycle")),
                        profile=int(m.group("prof")),
                        size_bytes=int(m.group("size")),
                        received_at=m.group("ts"),
                    )
                )
                continue
            # ARVOR-I delivery files: the transceiver directory name is the
            # mapping key (matched against PTT/IMEI/WMO candidates by the
            # pipeline, same as the demo tree's IMEI directories).
            if _ARVOR_EML_RE.match(entry.name):
                files.append(
                    CycleFile(
                        path=entry,
                        imei=imei_dir.name,
                        cycle=CYCLE_FROM_TELEMETRY,
                        profile=CYCLE_FROM_TELEMETRY,
                        size_bytes=entry.stat().st_size,
                        received_at="",
                    )
                )
        if files:
            index.files_by_imei[imei_dir.name] = files
    return index


def _argos_received_at(match: re.Match[str]) -> str:
    names = match.groupdict()
    if not all(names.get(name) for name in ("year", "month", "day")):
        return ""
    hour = names.get("hour") or "00"
    minute = names.get("minute") or "00"
    second = names.get("second") or "00"
    return f"{names['year']}{names['month']}{names['day']}T{hour}{minute}{second}Z"


def _match_argos_file(path: Path) -> tuple[str, int, str] | None:
    """Return ``(ptt, cycle, received_at)`` for known ARGOS file names."""
    for pattern in (_ARGOS_FMT1_RE, _ARGOS_DATE_RE, _ARGOS_FMT2_RE, _ARGOS_FALLBACK_RE):
        match = pattern.match(path.name)
        if match is None:
            continue
        return (match.group("ptt"), int(match.group("cycle")), _argos_received_at(match))
    # No cycle in the name: defer to the cycle number the float transmits.
    match = _ARGOS_PTT_DATE_RE.match(path.name)
    if match is not None:
        return (match.group("ptt"), CYCLE_FROM_TELEMETRY, _argos_received_at(match))
    return None


def _discover_argos(config: DecoderConfig) -> RsyncIndex:
    """Discover APEX/legacy ARGOS cycle files by PTT."""
    index = RsyncIndex()
    archive = Path(config.paths.rsync_data_dir)
    if not archive.exists():
        return index
    files_by_ptt: dict[str, list[CycleFile]] = {}
    for entry in sorted(p for p in archive.rglob("*.txt") if p.is_file()):
        matched = _match_argos_file(entry)
        if matched is None:
            continue
        ptt, cycle, received_at = matched
        files_by_ptt.setdefault(ptt, []).append(
            CycleFile(
                path=entry,
                imei=ptt,
                cycle=cycle,
                profile=cycle,
                size_bytes=entry.stat().st_size,
                received_at=received_at,
            )
        )
    for ptt, files in sorted(files_by_ptt.items()):
        index.files_by_imei[ptt] = sorted(
            files, key=lambda c: (c.cycle, c.received_at, c.path.name)
        )
    return index
