"""140-byte SBD framer for PROVOR CTS4 / decoder-301 telemetry (Phase 1).

Implementation contract: ``provor_bio_irsbd/PROVOR_CTS4_PHASE1_DESIGN_NOTE.md`` §6.

The frame geometry rests on two independent authorities that agree:

* Coriolis ``decode_sbd_file_cts4.m``: reshape the payload into 140-byte rows,
  truncate a 1024-byte file to 980 bytes first, and drop rows that are entirely
  ``0x00`` or entirely ``0x1A`` (26).
* Telemetry census (progress-log entry (ak)): all 517 workspace files are exact
  multiples of 140 bytes (420..1960).

The framer performs NO interpretation: it validates sizes and yields rows only.
Unframeable input fails loudly (:class:`FramingError`); nothing is skipped silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: Coriolis CTS4 row length in bytes (``decode_sbd_file_cts4.m`` reshape width).
FRAME_LEN = 140

#: Coriolis pre-truncation rule: a 1024-byte SBD attachment keeps its first 980 bytes.
CORIOLIS_PADDED_LEN = 1024
CORIOLIS_PADDED_KEEP = 980

#: Row fill values dropped by the Coriolis blank-row rule (all-``0x00`` / all-``0x1A``).
BLANK_ROW_VALUES = frozenset({0x00, 0x1A})


class FramingError(ValueError):
    """Raised when raw bytes cannot be framed into 140-byte packets."""


@dataclass(frozen=True)
class FramedFile:
    """One ``.sbd`` file split into validated 140-byte rows."""

    path: Path
    size_bytes: int
    truncated_1024: bool
    rows: tuple[bytes, ...]
    kept_indices: tuple[int, ...]
    dropped_blank: int

    @property
    def n_rows_total(self) -> int:
        """Row count before blank-row filtering."""
        return len(self.rows) + self.dropped_blank


def _is_blank(row: bytes) -> bool:
    first = row[0]
    return first in BLANK_ROW_VALUES and all(b == first for b in row)


def frame_bytes(data: bytes, *, path: Path | None = None) -> FramedFile:
    """Frame raw ``.sbd`` bytes into 140-byte rows.

    Applies the Coriolis 1024→980 truncation rule, requires an exact multiple
    of 140 bytes afterwards, and drops blank rows per the Coriolis rule.

    Raises:
        FramingError: if the (possibly truncated) length is not a multiple of 140.
    """
    size = len(data)
    truncated = False
    if size == CORIOLIS_PADDED_LEN:
        data = data[:CORIOLIS_PADDED_KEEP]
        truncated = True
    if len(data) % FRAME_LEN != 0:
        raise FramingError(
            f"{path or '<memory>'}: {len(data)} bytes after truncation is not a "
            f"multiple of {FRAME_LEN}"
        )
    rows: list[bytes] = []
    kept: list[int] = []
    dropped = 0
    for index in range(len(data) // FRAME_LEN):
        row = data[index * FRAME_LEN : (index + 1) * FRAME_LEN]
        if _is_blank(row):
            dropped += 1
            continue
        rows.append(row)
        kept.append(index)
    return FramedFile(
        path=path if path is not None else Path("<memory>"),
        size_bytes=size,
        truncated_1024=truncated,
        rows=tuple(rows),
        kept_indices=tuple(kept),
        dropped_blank=dropped,
    )


def frame_file(path: Path) -> FramedFile:
    """Read and frame one ``.sbd`` file from disk."""
    return frame_bytes(path.read_bytes(), path=path)


__all__ = [
    "BLANK_ROW_VALUES",
    "CORIOLIS_PADDED_KEEP",
    "CORIOLIS_PADDED_LEN",
    "FRAME_LEN",
    "FramedFile",
    "FramingError",
    "frame_bytes",
    "frame_file",
]
