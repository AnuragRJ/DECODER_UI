"""APF11 raw-corpus runner: science delivery files -> consolidated rows.

The per-cycle delivery files of the raw corpus
(``<float-id>.<cycle>.<delivery-ts>.science_log.csv``) are the
float-decoded science tables exactly as transmitted. This module turns them
into the consolidated row layout the decode layer consumes
(``src_cycle, record_type, timestamp, payload, None-rest``) and gathers the
GPS rows of neighbouring cycles that the position rule brackets on. It
changes no science rules and carries no float identifiers.
"""

from __future__ import annotations

import gzip
import re
from pathlib import Path
from typing import Iterable, Iterator, Mapping

_CYCLE_RE = re.compile(r"^[^.]+\.(\d+)\.[^.]+\.science_log\.csv$")
_SYSTEM_RE = re.compile(r"^[^.]+\.(\d+)\.[^.]+\.system_log\.txt(\.gz)?$")


def cycle_of_science_csv(path: Path) -> int | None:
    m = _CYCLE_RE.match(path.name)
    return int(m.group(1)) if m else None


def cycle_of_system_log(path: Path) -> int | None:
    m = _SYSTEM_RE.match(path.name)
    return int(m.group(1)) if m else None


def read_science_csv(path: Path) -> list[Mapping[str, str]]:
    """One delivery file -> consolidated rows (duplex duplicates kept).

    Duplicates collapse later, in the same layer that handles consolidated
    duplicates (:func:`deduplicate_samples`); nothing is dropped here.
    """
    cycle = cycle_of_science_csv(path)
    assert cycle is not None, path
    open_fn = gzip.open if path.suffix == ".gz" else open
    rows: list[Mapping[str, str]] = []
    with open_fn(path, "rt", errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\r\n")
            if not line:
                continue
            parts = line.split(",")
            if len(parts) < 3 or parts[0] in ("record_type",):
                continue
            rec_type, timestamp = parts[0], parts[1]
            payload = parts[2] if len(parts) > 2 else ""
            row: dict = {
                "src_cycle": str(cycle),
                "record_type": rec_type,
                "timestamp": timestamp,
                "payload": payload,
            }
            if len(parts) > 3:
                # same overflow convention as the consolidated DictReader
                row[None] = parts[3:]
            rows.append(row)
    return rows


def float_science_rows(float_dir: str | Path) -> Iterator[Mapping[str, str]]:
    """Every science row of one float's raw directory, in file order."""
    float_dir = Path(float_dir)
    for path in sorted(float_dir.glob("*.science_log.csv*")):
        if cycle_of_science_csv(path) is None:
            continue
        yield from read_science_csv(path)


def float_system_logs(float_dir: str | Path) -> dict[int, list[Path]]:
    """cycle -> system_log paths, both text and gz variants, delivery order."""
    float_dir = Path(float_dir)
    out: dict[int, list[Path]] = {}
    for path in sorted(float_dir.glob("*.system_log.txt*")):
        c = cycle_of_system_log(path)
        if c is not None:
            out.setdefault(c, []).append(path)
    return out


__all__ = [
    "cycle_of_science_csv",
    "cycle_of_system_log",
    "float_science_rows",
    "float_system_logs",
    "read_science_csv",
]
