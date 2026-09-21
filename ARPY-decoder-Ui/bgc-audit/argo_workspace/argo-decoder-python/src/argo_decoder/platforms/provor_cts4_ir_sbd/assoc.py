"""Family-generic measurement association for PROVOR CTS4 (Phase 2A).

The BGC equations need multi-sensor inputs at common pressures: DOXY needs
salinity from the CTD at each optode pressure, BBP700 needs temperature and
salinity at each FLBB pressure. This module provides the two family-generic
primitives — grouping type-0 packets by ``(cycle, profile, phase)`` and
nearest-pressure CTD lookup — with no WMO logic, no cycle-specific hacks, and
no interpolation policy beyond documented nearest-neighbor matching.

Padding rule: all-zero raw records are short-profile padding (see :mod:`ctd`
/ :mod:`bgc`), never measurements; they are excluded from matchup by default
so a surface BGC sample cannot "match" padding at ``pres = 0``.
"""

from __future__ import annotations

from dataclasses import dataclass

from argo_decoder.platforms.provor_cts4_ir_sbd.bgc import FlbbRecord, O2Record
from argo_decoder.platforms.provor_cts4_ir_sbd.ctd import CtdRecord
from argo_decoder.platforms.provor_cts4_ir_sbd.packets import (
    DispatchedFile,
    MeasPacket,
)


@dataclass(frozen=True)
class ProfileKey:
    """Type-0 identity triple: header cycle + profile + phase (all wire)."""

    cycle: int
    profile: int
    phase: int


def group_meas(dispatched: DispatchedFile) -> dict[ProfileKey, list[MeasPacket]]:
    """Group a file's type-0 packets by :class:`ProfileKey` (packet order kept)."""
    groups: dict[ProfileKey, list[MeasPacket]] = {}
    for packet in dispatched.packets:
        if not isinstance(packet, MeasPacket):
            continue
        key = ProfileKey(cycle=packet.cycle, profile=packet.profile, phase=packet.phase)
        groups.setdefault(key, []).append(packet)
    return groups


def is_padding_ctd(record: CtdRecord) -> bool:
    """True for all-zero-raw CTD records (short-profile padding)."""
    return record.p_raw == 0 and record.t_raw == 0 and record.s_raw == 0


def is_padding_o2(record: O2Record) -> bool:
    """True for all-zero-raw oxygen records (short-profile padding)."""
    return (
        record.p_raw == 0
        and record.c1_raw == 0
        and record.c2_raw == 0
        and record.t_raw == 0
    )


def is_padding_flbb(record: FlbbRecord) -> bool:
    """True for all-zero-raw FLBB records (short-profile padding)."""
    return record.p_raw == 0 and record.chl_raw == 0 and record.bb_raw == 0


def nearest_ctd(
    records: tuple[CtdRecord, ...], pres_dbar: float, *, exclude_padding: bool = True
) -> CtdRecord | None:
    """Nearest-pressure CTD record, or None when nothing is eligible.

    Ties resolve to the first record in iteration order. With
    ``exclude_padding=True`` (default), all-zero-raw padding records never
    match; an all-padding (or empty) input then yields None so callers can set
    explicit fill values instead of fabricating inputs.
    """
    best: CtdRecord | None = None
    best_gap = float("inf")
    for record in records:
        if exclude_padding and is_padding_ctd(record):
            continue
        gap = abs(record.pres_dbar - pres_dbar)
        if gap < best_gap:
            best = record
            best_gap = gap
    return best


__all__ = [
    "ProfileKey",
    "group_meas",
    "is_padding_ctd",
    "is_padding_flbb",
    "is_padding_o2",
    "nearest_ctd",
]
