"""Authoritative cycle attribution for PROVOR CTS4 / decoder-301 telemetry (Phase 1).

Implementation contract: ``provor_bio_irsbd/PROVOR_CTS4_PHASE1_DESIGN_NOTE.md`` §1/§6.

Byte authority: NKE ``5.8_MUT_PROVBIOII-FLBB_UTI_GB_Rev3_20130924`` §7 (first-party
manual; preserved at ``provor_bio_irsbd/ref/``). Every cycle-bearing packet carries
its own cycle identifier in its header:

* type-``0x00`` bytes2-3 (u16be) — the data cycle, genuine including 0;
* 255/254 bytes7-8 (u16be) — the session parameter cycle.

Attribution is purely structural: no WMO, no directory names, no filename parsing
(the ``.sbd`` numeric suffix is the Iridium MOMSN, NEVER the cycle), no per-group
branches, no assumed cycle rhythm. Files whose packets unanimously agree carry that
cycle; files with several distinct header cycles are recorded MULTI_CYCLE (backlog
pattern, legal per NKE §7.4 — never a conflict, never silently resolved).
Within-class disagreements (two 255s differing, 255-vs-254 mismatch) are RECORDED
as conflicts (never raised) so the tests can pin their absence.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from argo_decoder.platforms.provor_cts4_ir_sbd.framer import frame_file
from argo_decoder.platforms.provor_cts4_ir_sbd.packets import (
    DispatchedFile,
    MeasPacket,
    PacketType,
    ParamPacket,
    dispatch_framed,
)


class CycleBasis(Enum):
    """How a file's cycle value was established (or why it was not)."""

    UNANIMOUS = "unanimous"
    MULTI_CYCLE = "multi_cycle"
    NO_CYCLE_INFO = "no_cycle_info"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class FileAttribution:
    """Cycle attribution of one ``.sbd`` file."""

    path: Path
    group: str
    has_mission_params: bool
    has_tech_params: bool
    mission_cycle: int | None
    tech_cycle: int | None
    n_meas_rows: int
    meas_cycles: tuple[int, ...]
    cycle: int | None
    basis: CycleBasis
    conflicts: tuple[str, ...]


@dataclass(frozen=True)
class GroupAttribution:
    """Cycle attribution of one float group (one telemetry directory)."""

    group: str
    directory: Path
    files: tuple[FileAttribution, ...]

    @property
    def mission_cycles(self) -> tuple[int, ...]:
        """Sorted distinct 255 mission-param cycles observed in this group."""
        return tuple(sorted({f.mission_cycle for f in self.files if f.mission_cycle is not None}))

    @property
    def param_data_files(self) -> tuple[FileAttribution, ...]:
        """Files carrying BOTH parameter packets and measurement rows."""
        return tuple(
            f
            for f in self.files
            if (f.has_mission_params or f.has_tech_params) and f.n_meas_rows > 0
        )

    @property
    def data_only_files(self) -> tuple[FileAttribution, ...]:
        """Files carrying measurement rows but NO parameter packet."""
        return tuple(
            f
            for f in self.files
            if not f.has_mission_params and not f.has_tech_params and f.n_meas_rows > 0
        )


def _unanimous(values: list[int], *, what: str, conflicts: list[str]) -> int | None:
    distinct = sorted(set(values))
    if not distinct:
        return None
    if len(distinct) > 1:
        conflicts.append(f"multiple {what} values in one file: {distinct}")
        return None
    return distinct[0]


def attribute_file(dispatched: DispatchedFile, *, group: str) -> FileAttribution:
    """Attribute one dispatched file to a cycle (structural rules only)."""
    conflicts: list[str] = []
    mission_values = [
        p.cycle
        for p in dispatched.packets
        if isinstance(p, ParamPacket) and p.kind is PacketType.MISSION_PARAMS
    ]
    tech_values = [
        p.cycle
        for p in dispatched.packets
        if isinstance(p, ParamPacket) and p.kind is PacketType.TECH_PARAMS
    ]
    meas_values = [p.cycle for p in dispatched.packets if isinstance(p, MeasPacket)]
    mission_cycle = _unanimous(mission_values, what="255 cycle", conflicts=conflicts)
    tech_cycle = _unanimous(tech_values, what="254 cycle", conflicts=conflicts)
    has_mission = bool(mission_values)
    has_tech = bool(tech_values)
    meas_cycles = tuple(sorted(set(meas_values)))
    if mission_cycle is not None and tech_cycle is not None and mission_cycle != tech_cycle:
        conflicts.append(f"255 cycle {mission_cycle} disagrees with 254 cycle {tech_cycle}")

    observed = set(meas_values)
    if mission_cycle is not None:
        observed.add(mission_cycle)
    if tech_cycle is not None:
        observed.add(tech_cycle)

    cycle: int | None = None
    if conflicts:
        basis = CycleBasis.CONFLICT
    elif not observed:
        basis = CycleBasis.NO_CYCLE_INFO
    elif len(observed) == 1:
        basis = CycleBasis.UNANIMOUS
        cycle = next(iter(observed))
    else:
        basis = CycleBasis.MULTI_CYCLE
    return FileAttribution(
        path=dispatched.path,
        group=group,
        has_mission_params=has_mission,
        has_tech_params=has_tech,
        mission_cycle=mission_cycle,
        tech_cycle=tech_cycle,
        n_meas_rows=len(meas_values),
        meas_cycles=meas_cycles,
        cycle=cycle,
        basis=basis,
        conflicts=tuple(conflicts),
    )


def attribute_group(group_dir: Path) -> GroupAttribution:
    """Attribute every ``.sbd`` file in one group directory (sorted order)."""
    files = tuple(
        attribute_file(dispatch_framed(frame_file(path)), group=group_dir.name)
        for path in sorted(group_dir.rglob("*.sbd"))
    )
    return GroupAttribution(group=group_dir.name, directory=group_dir, files=files)


def iter_group_dirs(root: Path) -> list[Path]:
    """Immediate subdirectories of ``root`` containing ``.sbd`` files (sorted)."""
    return sorted(d for d in root.iterdir() if d.is_dir() and next(d.rglob("*.sbd"), None))


def basis_census(groups: tuple[GroupAttribution, ...]) -> Counter[CycleBasis]:
    """Count attribution bases over a set of groups (reporting helper)."""
    census: Counter[CycleBasis] = Counter()
    for group in groups:
        for item in group.files:
            census[item.basis] += 1
    return census


__all__ = [
    "CycleBasis",
    "FileAttribution",
    "GroupAttribution",
    "attribute_file",
    "attribute_group",
    "basis_census",
    "iter_group_dirs",
]
