"""APF11 cycle/profile attribution.

The raw file name carries the attribution directly:

    ``NNN-0319.CCC.<timestamp>.<family>.<kind>[.gz]``
     └──┬──┘└┬┘└───┬────┘└──┬──┘
    float_id cycle timestamp family

    e.g. ``<float_id>.148.20240305T042848.science_log.bin.gz``

``float_id`` is the Webb build identifier (``NNN-0319``), ``cycle`` is the
Argo cycle number, and the timestamp is when the file was written. Nothing here
reads a WMO, so attribution works for any APF11 float.

Cycle 000 is handled explicitly rather than by default. In all four floats of
this corpus it is the launch test cycle: its only CTD record is ``CTD_PT``,
whereas every later cycle carries ``CTD_bins``. That is an observable property
of the telemetry, not a hard-coded rule, so a float whose cycle 000 looked like
a normal profile would be classified as one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: ``<float_id>.<cycle>.<timestamp>.<family>.<ext>``
#:
#: ``kind`` covers the two binary/text raw forms and, in addition, ``csv``:
#: one float in this corpus ships already-decoded ``*.science_log.csv`` /
#: ``*.vitals_log.csv`` alongside its ``.gz`` siblings. Those carry the same
#: attribution in the same position, so they parse identically.
_FILENAME_RE = re.compile(
    r"^(?P<float_id>\d{3}-\d{4})\.(?P<cycle>\d{3,})\.(?P<ts>\d{8}T\d{6})"
    r"\.(?P<family>[a-z_]+)\.(?P<kind>bin|txt|csv)(?:\.gz)?$"
)


@dataclass(frozen=True)
class FileAttribution:
    """What a raw file name says about the record it contains."""

    float_id: str
    cycle: int
    timestamp: str
    family: str
    kind: str
    filename: str

    @property
    def is_binary(self) -> bool:
        return self.kind == "bin"

    @property
    def is_predecoded(self) -> bool:
        """True for the already-decoded ``.csv`` files one float ships."""
        return self.kind == "csv"


def parse_filename(name: str) -> FileAttribution | None:
    """Parse one APF11 raw file name.

    Returns ``None`` for anything that does not match, so an unexpected file is
    reported rather than silently attributed to the wrong cycle.
    """
    base = name.rsplit("/", 1)[-1]
    m = _FILENAME_RE.match(base)
    if not m:
        return None
    return FileAttribution(
        float_id=m.group("float_id"),
        cycle=int(m.group("cycle")),
        timestamp=m.group("ts"),
        family=m.group("family"),
        kind=m.group("kind"),
        filename=base,
    )


@dataclass(frozen=True)
class CycleProfile:
    """Per-cycle CTD attribution derived from ``CTD_bins`` and the record mix.

    ``is_launch_test`` is set when the cycle carries no ``CTD_bins`` summary,
    which in this corpus identifies the launch test cycle. A caller can publish
    such a cycle flagged, or exclude it; this module does not decide.
    """

    cycle: int
    ctd_record_types: tuple[str, ...]
    has_bins: bool
    bins_samples: int | None
    bins_count: int | None
    bins_maxpress: float | None
    has_salinity: bool
    timestamps: tuple[str, ...]

    @property
    def is_launch_test(self) -> bool:
        """True when the cycle carries no ``CTD_bins`` per-cycle summary."""
        return not self.has_bins

    @property
    def is_attributable(self) -> bool:
        """True when the cycle has enough structure to be a normal profile."""
        return self.has_bins


def attribute_cycles(
    cycles: dict[int, dict],
) -> dict[int, CycleProfile]:
    """Build a :class:`CycleProfile` for each cycle.

    ``cycles`` maps a cycle number to a dict with optional keys
    ``record_types`` (iterable of CTD record-type names), ``bins`` (the
    ``(samples, bins, maxpress)`` tuple, if a summary record exists) and
    ``timestamps``.
    """
    out: dict[int, CycleProfile] = {}
    for cycle, info in cycles.items():
        types = tuple(sorted(set(info.get("record_types", ()))))
        bins = info.get("bins")
        out[cycle] = CycleProfile(
            cycle=cycle,
            ctd_record_types=types,
            has_bins=bins is not None,
            bins_samples=bins[0] if bins else None,
            bins_count=bins[1] if bins else None,
            bins_maxpress=bins[2] if bins else None,
            has_salinity=bool(info.get("has_salinity", False)),
            timestamps=tuple(sorted(info.get("timestamps", ()))),
        )
    return out


__all__ = [
    "CycleProfile",
    "FileAttribution",
    "attribute_cycles",
    "parse_filename",
]
