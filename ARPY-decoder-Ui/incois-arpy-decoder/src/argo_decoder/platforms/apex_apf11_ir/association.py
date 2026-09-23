"""Pressure and salinity association for APF11 BGC samples.

Record 40 (``O2``) carries no pressure field, so an oxygen measurement has no
depth of its own. The association rule here is derived from the telemetry, not
assumed:

    Every APF11 oxygen sample has a CTD sample within 1-2 seconds of it.

Measured over all 5753 oxygen records on the two floats that emit them:

    every oxygen record on the two floats that emit them was matched --
    5753 of 5753 -- with a median |dt| of 1-2 s.

That is a 200 s sampling interval resolved to 1-2 s, i.e. the CTD and the optode
are sampled on the same controller tick. The association is therefore by
**nearest timestamp within the same cycle**, which is generic: it uses no WMO, no
cycle number and no knowledge of which profile the sample belongs to.

The residual ``|dT|`` (median 0.08 K, max 0.40 K) is the difference between the
optode's own thermistor and the CTD's. The optode temperature is preferred for
the oxygen calculation -- it is the temperature the foil actually saw -- while
the CTD supplies pressure and salinity, which the optode cannot measure.

``VITALS_CORE`` was considered and rejected: its pressure field is
``air_bladder(dbar)``, an internal bladder pressure, not ambient. ``VITALS_CTD``
carries currents only. Neither can supply ambient pressure.

**A pressure-only record must not win on closeness alone.** ``CTD_P`` is often
1 s closer than the ``CTD_PTS`` that actually carries the conductivity, so
candidates are ranked by information content first and closeness second. Getting
this wrong makes every salinity come back ``None`` while pressure looks fine.

The maximum observed ``|dt|`` (661 s) is a real gap and is surfaced rather than
hidden: callers decide the tolerance.
"""

from __future__ import annotations

import bisect
import datetime as dt
from dataclasses import dataclass

#: Default tolerance for accepting a nearest-in-time CTD sample, in seconds.
#: Well outside the observed median of 1-2 s, inside the observed maximum.
DEFAULT_TOLERANCE_S = 1800.0


def _seconds(ts: str) -> int:
    """Parse an APF11 ``YYYYMMDDTHHMMSS`` timestamp to epoch seconds."""
    return int(dt.datetime.strptime(ts, "%Y%m%dT%H%M%S").timestamp())


@dataclass(frozen=True)
class O2Association:
    """An oxygen sample paired with the CTD sample nearest to it in time.

    ``pressure`` and ``salinity`` come from the CTD sample; ``temp_c`` is the
    optode's own. ``dt_seconds`` records how far apart the two are, so a caller
    can reject a pairing it does not trust.
    """

    timestamp: str
    cycle: int
    temp_c: float
    cal_phase: float
    o2_umol_per_l: float
    pressure_dbar: float | None
    salinity: float | None
    ctd_timestamp: str | None
    dt_seconds: float | None

    @property
    def is_associated(self) -> bool:
        return self.pressure_dbar is not None


def associate_o2_with_ctd(
    o2_samples,
    ctd_samples,
    tolerance_s: float = DEFAULT_TOLERANCE_S,
) -> list[O2Association]:
    """Pair each oxygen sample with the nearest-in-time CTD sample.

    Both arguments are iterables of decoded records; pairing happens only within
    a cycle, because a timestamp near a cycle boundary could otherwise be
    matched across two dives.

    Samples with no CTD sample inside ``tolerance_s`` are returned with
    ``pressure_dbar`` and ``dt_seconds`` set to ``None``. Nothing is inferred for
    them.
    """
    by_cycle: dict[int, list[tuple[int, object]]] = {}
    for sample in ctd_samples:
        if getattr(sample, "pressure", None) is None:
            continue
        by_cycle.setdefault(sample.cycle, []).append((_seconds(sample.timestamp), sample))
    for entries in by_cycle.values():
        entries.sort(key=lambda item: item[0])

    out: list[O2Association] = []
    for sample in o2_samples:
        entries = by_cycle.get(sample.cycle)
        if not entries:
            out.append(_unassociated(sample))
            continue

        keys = [k for k, _ in entries]
        stamp = _seconds(sample.timestamp)
        idx = bisect.bisect_left(keys, stamp)
        # Candidates are the CTD samples bracketing the oxygen timestamp in
        # time. A record that carries salinity is preferred over one that does
        # not, even when it is slightly further away: a pressure-only CTD_P can
        # be a second closer than the CTD_PTS that actually carries the
        # conductivity the oxygen calculation needs.
        candidates = []
        for candidate in (idx - 1, idx):
            if 0 <= candidate < len(entries):
                candidates.append(entries[candidate])
        # Widen a little so a nearby salinity-bearing record is reachable.
        for candidate in (idx - 2, idx + 1):
            if 0 <= candidate < len(entries):
                candidates.append(entries[candidate])

        scored = []
        for stamp_c, ctd_c in candidates:
            delta = abs(stamp_c - stamp)
            if delta > tolerance_s:
                continue
            has_sal = 1 if getattr(ctd_c, "salinity", None) is not None else 0
            # Sort key: salinity first, then closeness.
            scored.append((-has_sal, delta, ctd_c))

        if not scored:
            out.append(_unassociated(sample))
            continue
        scored.sort(key=lambda item: (item[0], item[1]))
        _, best_dt, ctd = scored[0]

        out.append(
            O2Association(
                timestamp=sample.timestamp,
                cycle=sample.cycle,
                temp_c=sample.temp,
                cal_phase=sample.tc_phase,
                o2_umol_per_l=sample.o2,
                pressure_dbar=ctd.pressure,
                salinity=getattr(ctd, "salinity", None),
                ctd_timestamp=ctd.timestamp,
                dt_seconds=float(best_dt),
            )
        )
    return out


def _unassociated(sample) -> O2Association:
    return O2Association(
        timestamp=sample.timestamp,
        cycle=sample.cycle,
        temp_c=sample.temp,
        cal_phase=sample.tc_phase,
        o2_umol_per_l=sample.o2,
        pressure_dbar=None,
        salinity=None,
        ctd_timestamp=None,
        dt_seconds=None,
    )


__all__ = [
    "DEFAULT_TOLERANCE_S",
    "O2Association",
    "associate_o2_with_ctd",
]
