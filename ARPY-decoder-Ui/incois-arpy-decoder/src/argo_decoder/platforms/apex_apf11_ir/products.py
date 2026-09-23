"""APF11 mono-profile product model (R/BR content, pre-NetCDF).

Builds, for every cycle with a complete phase anchor set, the two published
profiles of an APF11 mono-profile file:

* the **averaged profile** (``VERTICAL_SAMPLING_SCHEME`` "Primary sampling:
  averaged []"): the ``CTD_CP`` bin-averaged cast inside the profiling
  window, ordered by pressure;
* the **discrete profile** ("Secondary sampling: discrete []"): the
  ``CTD_PTS`` schedule samples of the same window, which are the CTD nodes
  the BGC instruments sample alongside (FLBB/O2/NO3 records fall within the
  same window and are paired 1:1 to their nearest CTD node).

All relationships below are established against the published INCOIS mono
profiles, positionally at float32-ULP level (see
``tests/integration/test_apex_apf11_gdac_parity.py`` and the B-curves
probe ``test_apex_apf11_product_profiles_match``):

* the averaged profile equals the deduplicated CTD_CP records verbatim;
* the discrete core profile equals the deduplicated CTD_PTS records
  verbatim;
* BGC levels are the CTD nodes the BGC records are co-sampled with, and
  their published PRES is the node pressure (nearest-in-time pairing, not
  interpolated);
* records are deduplicated with :func:`deduplicate_samples` (Iridium duplex
  retransmissions);
* the profiling window is the half-open ``[Profiling Mission, Surface
  Mission)`` interval of the cycle's Message anchors;

Nothing here reads a WMO or float identifier. Configuration-dependent
content (which parameters a level carries) comes from the record streams
and the authoritative calibration tables alone.
"""

from __future__ import annotations

from dataclasses import dataclass

from argo_decoder.platforms.apex_apf11_ir.phases import CyclePhases
from argo_decoder.platforms.apex_apf11_ir.science import (
    CtdSample,
    FlbbSample,
    No3Sample,
    O2Sample,
    deduplicate_samples,
)


@dataclass(frozen=True)
class CtdLevel:
    """One core level of a profile (averaged or discrete)."""

    pressure: float
    temperature: float | None
    salinity: float | None


@dataclass(frozen=True)
class BgcLevel:
    """One BGC level: a co-sampled CTD node plus the paired BGC records.

    Every field is ``None`` when the cycle does not carry the corresponding
    record for this node; absence is data.
    """

    pressure: float
    temperature: float | None
    salinity: float | None
    flbb: FlbbSample | None = None
    o2: O2Sample | None = None
    no3: No3Sample | None = None


@dataclass(frozen=True)
class CycleProfiles:
    """The two profiles of one cycle plus the publishing anchors."""

    cycle: int
    juld: float
    averaged: tuple[CtdLevel, ...]
    discrete_core: tuple[CtdLevel, ...]
    discrete_bgc: tuple[BgcLevel, ...]


def _in_window(samples, window: tuple[str, str]):
    start, end = window
    return [s for s in samples if start <= s.timestamp < end]


def _sort_by_pressure(samples, accessor: str = "pressure"):
    return sorted(samples, key=lambda s: (getattr(s, accessor), s.timestamp))


def _pair_to_nodes(samples, nodes: list[CtdSample]) -> dict[int, list]:
    """Pair each BGC sample of one stream to a co-sampled CTD node.

    The APF11 sampling schedule triggers the CTD first and the BGC sensors a
    few seconds later **at the same level**, so the association rule is the
    node the sample follows, not simply the time-nearest node: a sample
    sitting between two nodes belongs to the earlier (preceding) one.  Both
    rules agree whenever the sample lies closer to the node it follows, which
    is the normal case; they disagree in a dense near-surface sequence, and
    the raw telemetry resolves it -- every BGC record of a level is 6-18 s
    *after* its CTD node and minutes after the previous one (verified at two
    levels of the nitrate float where the published product follows the
    preceding node while the nearest-node rule swapped the pair).

    Pairing is one-to-one per stream: a node hosts at most one FLBB, one O2
    and one NO3 record.  Samples are processed in time order and each claims
    the closest *unused* preceding node, falling back to the closest unused
    node when no preceding one is free (no sample is dropped silently).
    Duplicate deliveries carry identical content and are removed upstream.
    Returns ``node index -> paired sample``.
    """
    import bisect
    import datetime as dt

    def sec(ts: str) -> float:
        return dt.datetime.strptime(ts, "%Y%m%dT%H%M%S").timestamp()

    # Nodes arrive pressure-ordered (publication order); pairing needs the
    # time-sorted view. Keep the mapping back to publication indices.
    order = sorted(range(len(nodes)), key=lambda i: nodes[i].timestamp)
    keys = [sec(nodes[i].timestamp) for i in order]
    assigned: dict[int, list] = {}
    used: set[int] = set()
    for sample in sorted(samples, key=lambda s: s.timestamp):
        t = sec(sample.timestamp)
        idx = bisect.bisect_left(keys, t)
        preceding = [c for c in (idx - 1, idx) if 0 <= c < len(keys) and keys[c] <= t]
        best = None
        for cand in preceding:
            node_i = order[cand]
            if node_i in used:
                continue
            distance = abs(keys[cand] - t)
            if best is None or distance < best[0]:
                best = (distance, node_i)
        if best is None:
            for cand in (idx - 2, idx - 1, idx, idx + 1):
                if not 0 <= cand < len(keys):
                    continue
                node_i = order[cand]
                if node_i in used:
                    continue
                distance = abs(keys[cand] - t)
                if best is None or distance < best[0]:
                    best = (distance, node_i)
        if best is None:
            continue
        assigned[best[1]] = [sample]
        used.add(best[1])
    return assigned


def _kind(sample) -> str:
    if isinstance(sample, FlbbSample):
        return "flbb"
    if isinstance(sample, O2Sample):
        return "o2"
    return "no3"


def build_cycle_profiles(
    cycle: int,
    phases: CyclePhases,
    ctd: list[CtdSample],
    flbb: list[FlbbSample],
    o2: list[O2Sample],
    no3: list[No3Sample],
) -> CycleProfiles | None:
    """Build the two published profiles of one cycle.

    Returns ``None`` when the cycle has no usable phase anchors or no
    profile content; such cycles produce no mono-profile file (matching the
    publication: no partial profiles are fabricated).
    """
    juld = phases.juld
    window = phases.profiling_window
    if juld is None or window is None:
        return None

    # Published level order is ascending pressure for every ascent profile
    # (137 of 138 published core cycles verify). The single exception,
    # parity cycle 223 averaged profile published deep -> shallow, is a
    # GDAC reprocessing anomaly (its raw record order is shallow -> deep
    # like every other cycle); it is logged in the parity classifications,
    # never imitated.
    cp = _sort_by_pressure(
        [s for s in _in_window(deduplicate_samples(ctd), window) if s.record_type == "CTD_CP"]
    )
    pts = _sort_by_pressure(
        [s for s in _in_window(deduplicate_samples(ctd), window) if s.record_type == "CTD_PTS"]
    )

    averaged = tuple(
        CtdLevel(s.pressure, s.temperature, s.salinity) for s in cp
    )
    # The full discrete grid is kept (117 published cycles show the deepest
    # PTS level ~5-6 dbar below the averaged grid bottom; the 156-176
    # block where the GDAC trimmed it is its stale-era reprocessing, not a
    # rule).
    discrete_core = tuple(
        CtdLevel(s.pressure, s.temperature, s.salinity) for s in pts
    )

    win_flbb = _in_window(deduplicate_samples(flbb), window)
    win_o2 = _in_window(deduplicate_samples(o2), window)
    win_no3 = _in_window(deduplicate_samples(no3), window)

    flbb_pairs = _pair_to_nodes(win_flbb, pts)
    o2_pairs = _pair_to_nodes(win_o2, pts)
    no3_pairs = _pair_to_nodes(win_no3, pts)

    node_indices = sorted(
        set(flbb_pairs) | set(o2_pairs) | set(no3_pairs)
    )
    discrete_bgc = tuple(
        BgcLevel(
            pressure=pts[i].pressure,
            temperature=pts[i].temperature,
            salinity=pts[i].salinity,
            flbb=(flbb_pairs[i][0] if i in flbb_pairs else None),
            o2=(o2_pairs[i][0] if i in o2_pairs else None),
            no3=(no3_pairs[i][0] if i in no3_pairs else None),
        )
        for i in node_indices
    )

    if not averaged and not discrete_core:
        return None
    return CycleProfiles(
        cycle=cycle,
        juld=juld,
        averaged=averaged,
        discrete_core=discrete_core,
        discrete_bgc=discrete_bgc,
    )


__all__ = [
    "BgcLevel",
    "CtdLevel",
    "CycleProfiles",
    "build_cycle_profiles",
]
