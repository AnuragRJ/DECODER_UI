"""Cycle phase anchors from APF11 science-log ``Message`` records.

The APF11 science log brackets every mission phase with a message record.
These message timestamps are what the float's own clock says the mission
did, and they are the anchors published by the GDAC:

* the mono-profile ``JULD`` equals the ``Surface Mission`` timestamp
  (verified positionally on all 138 R cycles of the primary parity float);
* the trajectory cycle anchors (``JULD_ASCENT_START`` etc.) and the 6
  ``MEASUREMENT_CODE`` rows equal the message timestamps
  (verified on cycle 189 and spot-checked across the corpus).

Nothing here reads a WMO, float name, serial or IMEI: anchors come from the
message text only, and the only float-specific content (``Username:``,
``Float ID:``) is intentionally inert.

Payloads appear in two spellings in the consolidated tables -- a plain
string and a Python ``b'...'`` repr of the same bytes -- because the
consolidation step preserved two raw-file decode variants. Both spellings
are normalised identically. It is decode-normalisation, not data selection.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from collections.abc import Iterable, Mapping

#: Seconds in a day; APF11 timestamps are UTC with no leap-second handling.
_JULD_EPOCH = dt.datetime(1950, 1, 1)


def timestamp_to_juld(timestamp: str) -> float:
    """Convert an APF11 ``YYYYMMDDTHHMMSS`` timestamp to Argo Julian days."""
    value = dt.datetime.strptime(timestamp, "%Y%m%dT%H%M%S")
    return (value - _JULD_EPOCH).total_seconds() / 86400.0


def juld_to_timestamp(juld: float) -> str:
    """Inverse of :func:`timestamp_to_juld`, second resolution."""
    return (_JULD_EPOCH + dt.timedelta(days=juld)).strftime("%Y%m%dT%H%M%S")


def _clean_payload(payload: str) -> str:
    """Normalise the two spellings of a message payload to bare text."""
    text = payload.strip()
    if text.startswith("b'") and text.endswith("'"):
        text = text[2:-1]
    if text.startswith('b"') and text.endswith('"'):
        text = text[2:-1]
    return text.rstrip("* ")


#: Phase anchors recognised from message prefixes. Tuple member order is the
#: field order of :class:`CyclePhases`; prefix matching follows the Coriolis
#: ``usedMessages`` list so the same anchors are available as in the
#: reference decoder (``ICE*`` anchors are included even though this corpus
#: never triggers them).
_PREFIX_TO_FIELD: tuple[tuple[str, str], ...] = (
    ("Prelude/Self Test", "prelude_start"),
    ("Park Descent Mission", "descent_start"),
    ("Park Mission", "park_start"),
    ("Deep Descent Mission", "park_end"),
    ("Profiling Mission", "profiling_start"),
    ("ASCENT", "profiling_start"),
    ("CP Started", "continuous_profile_start"),
    ("CP Stopped", "continuous_profile_end"),
    ("Surface Mission", "ascent_end"),
    ("ICEDESCENT", "ice_descent_start"),
    ("ICEASCENT", "ice_ascent_start"),
)

#: Longest-prefix-first matching so ``ICEASCENT`` wins over ``ASCENT`` is not
#: needed (``ICEDESCENT``/``ICEASCENT`` match first because the plain
#: ``ASCENT`` key is checked after the exact longer keys below).
_ORDERED_PREFIXES: tuple[tuple[str, str], ...] = (
    ("ICEDESCENT", "ice_descent_start"),
    ("ICEASCENT", "ice_ascent_start"),
) + _PREFIX_TO_FIELD


@dataclass(frozen=True)
class CyclePhases:
    """Mission-phase anchors for one cycle, each an APF11 timestamp string.

    Every field is ``None`` when the cycle's messages do not carry the
    anchor; absence is data, not something to synthesise.
    """

    cycle: int
    prelude_start: str | None = None
    descent_start: str | None = None
    park_start: str | None = None
    park_end: str | None = None
    profiling_start: str | None = None
    continuous_profile_start: str | None = None
    continuous_profile_end: str | None = None
    ascent_end: str | None = None
    ice_descent_start: tuple[str, ...] = ()
    ice_ascent_start: tuple[str, ...] = ()

    @property
    def juld(self) -> float | None:
        """Profile JULD: the ``Surface Mission`` timestamp.

        Verified: equals the GDAC mono-profile JULD at 1e-5 JULD resolution
        on every published R cycle of the primary parity float.
        """
        if self.ascent_end is None:
            return None
        return timestamp_to_juld(self.ascent_end)

    @property
    def profiling_window(self) -> tuple[str, str] | None:
        """Half-open ``[start, end)`` window of the sampled profile.

        Both averaged (CTD_CP) and discrete (CTD_PTS/FLBB/O2/NO3) records
        lie inside it; post-``Surface Mission`` samples (e.g. the surface
        O2 series) lie outside and are not profile data.
        """
        if self.profiling_start is None or self.ascent_end is None:
            return None
        return (self.profiling_start, self.ascent_end)


def parse_cycle_phases(rows: Iterable[Mapping[str, str]]) -> dict[int, CyclePhases]:
    """Build per-cycle phase anchors from consolidated ``Message`` rows.

    ``rows`` are the consolidated science-log Message records
    (``src_cycle, record_type, timestamp, payload``). Duplicate deliveries of
    the same message (duplex Iridium transmissions) collapse on
    ``(timestamp, payload)`` -- the same rule as for measurement records.
    The first occurrence of each anchor in timestamp order is used; a cycle
    carrying several profiling attempts (ICE) records every ICE anchor.
    """
    per_cycle: dict[int, list[tuple[str, str]]] = {}
    seen: set[tuple[int, str, str]] = set()
    for row in rows:
        if row.get("record_type") != "Message":
            continue
        try:
            cycle = int(row.get("src_cycle", ""))
        except ValueError:
            continue
        timestamp = str(row.get("timestamp", ""))
        text = _clean_payload(str(row.get("payload", "")))
        if (cycle, timestamp, text) in seen:
            continue
        seen.add((cycle, timestamp, text))
        per_cycle.setdefault(cycle, []).append((timestamp, text))

    out: dict[int, CyclePhases] = {}
    for cycle, events in per_cycle.items():
        fields: dict[str, object] = {"cycle": cycle}
        ice_descent: list[str] = []
        ice_ascent: list[str] = []
        for timestamp, text in sorted(events):
            for prefix, field in _ORDERED_PREFIXES:
                if not text.startswith(prefix):
                    continue
                if field == "ice_descent_start":
                    ice_descent.append(timestamp)
                elif field == "ice_ascent_start":
                    ice_ascent.append(timestamp)
                else:
                    # first occurrence wins; a second identical message in a
                    # cycle does not roll the phase anchor forward.
                    if fields.get(field) is None:
                        fields[field] = timestamp
                break
        fields["ice_descent_start"] = tuple(ice_descent)
        fields["ice_ascent_start"] = tuple(ice_ascent)
        out[cycle] = CyclePhases(**fields)  # type: ignore[arg-type]
    return out


__all__ = [
    "CyclePhases",
    "parse_cycle_phases",
    "timestamp_to_juld",
    "juld_to_timestamp",
]
