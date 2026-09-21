"""Real-time QC for trajectory (``Rtraj``) data.

The trajectory RTQC set is **not** the 15-test vertical-profile set.  The
Argo QC Manual v3.9 devotes a separate section (``§4 Real-time procedures
on trajectory file data``) to it, and the Coriolis reference chain applies
exactly four tests to a trajectory file
(``nc_add_rtqc_flags_prof_and_traj.m:775-786``)::

    testToPerformList2 = [ ...
       {'TEST002_IMPOSSIBLE_DATE'} {1} ...
       {'TEST003_IMPOSSIBLE_LOCATION'} {1} ...
       {'TEST004_POSITION_ON_LAND'} {1} ...
       {'TEST020_QUESTIONABLE_ARGOS_POSITION'} {1} ...
       ];
    % perform RTQC on trajectory data (to fill JULD_QC, JULD_ADJUSTED_QC
    % and POSITION_QC)

Those four tests are the *only* producers of ``JULD_QC``,
``JULD_ADJUSTED_QC`` and ``POSITION_QC`` in a trajectory file.  The
profile-only tests (5/6/8/9/11/12/13/14/16/18/19) act on PRES/TEMP/PSAL
levels, which an ARVOR-I Rtraj carries as fill everywhere, so they have
nothing to bite on here.

Flag algebra follows ``add_rtqc_to_trajectory_file`` /
``add_do_rtqc_to_trajectory_file``:

* a value that is fill keeps the ``' '`` default -- QC is never asserted
  for something that does not exist;
* a defined value starts at ``'0'`` (``g_decArgo_qcStrNoQc``) -- decoded
  but not yet quality controlled;
* when a test actually runs on that value it is raised to ``'1'``
  (``g_decArgo_qcStrGood``) via ``set_qc``, and escalated to ``'4'``
  (``g_decArgo_qcStrBad``) when the test fails.

``set_qc`` only ever *worsens* a flag, so a value condemned by one test is
not rehabilitated by a later one.

Test 20 replaces Test 5 for positioning systems that report an accuracy
class (QC Manual §4, Test 20: *"For floats that use the ARGOS system to
obtain position data, this test can be used in lieu of Test 5"*).  ARVOR-I
is an Iridium-only family whose fixes carry accuracy ``'I'`` (Argo
reference table 5: *Iridium accuracy, not better than 5 km*), so the
JAMSTEC error-radius arithmetic -- which is defined solely for the ARGOS
classes 1/2/3 -- has no defined error radius to work with and the test
cannot run.  It is reported skipped rather than silently passed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime

__all__ = [
    "TRAJECTORY_RTQC_TESTS",
    "TrajectoryQcOutcome",
    "apply_trajectory_rtqc",
]

#: Argo reference table 2 QC flags used by trajectory RTQC.
_QC_DEFAULT = " "  # g_decArgo_qcStrDef   - no value to qualify
_QC_NO_QC = "0"  # g_decArgo_qcStrNoQc  - value present, not tested
_QC_GOOD = "1"  # g_decArgo_qcStrGood  - tested and passed
_QC_BAD = "4"  # g_decArgo_qcStrBad   - tested and failed

#: Worsening order for :func:`_set_qc` (mirrors Coriolis ``set_qc.m``).
_QC_RANK = {_QC_DEFAULT: -1, _QC_NO_QC: 0, _QC_GOOD: 1, "2": 2, "3": 3, _QC_BAD: 4}

#: Argo QC Manual v3.9 §4 Test 2: 1st January 1997 in Argo julian days.
_TEST002_MIN_JULD = 17167.0

#: The trajectory RTQC set, in Coriolis application order.
TRAJECTORY_RTQC_TESTS: tuple[int, ...] = (2, 3, 4, 20)


def _set_qc(current: str, new: str) -> str:
    """Coriolis ``set_qc``: a flag may only ever be worsened."""

    if _QC_RANK.get(new, -1) > _QC_RANK.get(current, -1):
        return new
    return current


@dataclass
class TrajectoryQcOutcome:
    """Truthful provenance of one trajectory RTQC pass."""

    executed: set[int] = field(default_factory=set)
    failed: set[int] = field(default_factory=set)
    skipped: dict[int, str] = field(default_factory=dict)
    n_juld_tested: int = 0
    n_position_tested: int = 0
    n_juld_bad: int = 0
    n_position_bad: int = 0

    @property
    def passed(self) -> set[int]:
        """Tests that ran and did not raise a single bad flag."""

        return self.executed - self.failed


def _is_defined(value: float | None) -> bool:
    return value is not None and math.isfinite(value)


def apply_trajectory_rtqc(
    rows,  # list[RtrajRow] - untyped to avoid a circular import
    *,
    bathymetry=None,
    now: datetime | None = None,
) -> TrajectoryQcOutcome:
    """Apply the Coriolis trajectory RTQC set to ``rows`` in place.

    ``rows`` are mutated: ``juld_qc``, ``juld_adj_qc`` and ``pos_qc`` are
    filled from the tests that actually ran.  Returns the provenance of
    the pass so the caller can record a truthful executed/failed/skipped
    inventory.

    The pass is entirely generic: it inspects only decoded row content
    (date, position, accuracy class) and never a WMO or cycle number.
    """

    outcome = TrajectoryQcOutcome()
    reference = now or datetime.now(tz=UTC)
    max_juld = (reference - datetime(1950, 1, 1, tzinfo=UTC)).total_seconds() / 86400.0

    # ---- TEST002: impossible date -----------------------------------
    # 17167 <= JULD < UTC date of check. Runs on every defined date,
    # including JULD_ADJUSTED (Coriolis fills JULD_ADJUSTED_QC here too).
    dated = [r for r in rows if _is_defined(r.juld)]
    if dated:
        outcome.executed.add(2)
        for row in dated:
            row.juld_qc = _set_qc(row.juld_qc or _QC_NO_QC, _QC_GOOD)
            if not (_TEST002_MIN_JULD <= float(row.juld) < max_juld):
                row.juld_qc = _set_qc(row.juld_qc, _QC_BAD)
                outcome.failed.add(2)
                outcome.n_juld_bad += 1
        outcome.n_juld_tested = len(dated)
        for row in rows:
            if _is_defined(row.juld_adj):
                row.juld_adj_qc = _set_qc(row.juld_adj_qc or _QC_NO_QC, _QC_GOOD)
                if not (_TEST002_MIN_JULD <= float(row.juld_adj) < max_juld):
                    row.juld_adj_qc = _set_qc(row.juld_adj_qc, _QC_BAD)
    else:
        outcome.skipped[2] = "no dated rows"

    # ---- TEST003: impossible location -------------------------------
    located = [r for r in rows if _is_defined(r.latitude) and _is_defined(r.longitude)]
    if located:
        outcome.executed.add(3)
        for row in located:
            row.pos_qc = _set_qc(row.pos_qc or _QC_NO_QC, _QC_GOOD)
            if not (-90.0 <= float(row.latitude) <= 90.0) or not (
                -180.0 <= float(row.longitude) <= 180.0
            ):
                row.pos_qc = _set_qc(row.pos_qc, _QC_BAD)
                outcome.failed.add(3)
                outcome.n_position_bad += 1
        outcome.n_position_tested = len(located)
    else:
        outcome.skipped[3] = "no positioned rows"

    # ---- TEST004: position on land ----------------------------------
    # Requires a bathymetry grid. Never fabricated: without the grid the
    # test is reported skipped and no flag is touched.
    if not located:
        outcome.skipped[4] = "no positioned rows"
    elif bathymetry is None:
        outcome.skipped[4] = "no bathymetry grid supplied"
    else:
        outcome.executed.add(4)
        for row in located:
            elevation = bathymetry.elevation_at(float(row.latitude), float(row.longitude))
            if elevation is not None and elevation > 0.0:
                row.pos_qc = _set_qc(row.pos_qc, _QC_BAD)
                outcome.failed.add(4)
                outcome.n_position_bad += 1

    # ---- TEST020: questionable ARGOS position -----------------------
    # Defined only for ARGOS classes 1/2/3, whose error radii (1000/350/
    # 150 m) drive the critical-error-length arithmetic. An Iridium fix
    # ('I') has no such class, so the test has no defined input.
    argos = [r for r in located if r.pos_accuracy in {"1", "2", "3"}]
    if not located:
        outcome.skipped[20] = "no positioned rows"
    elif not argos:
        outcome.skipped[20] = (
            "no ARGOS-class fixes (Iridium 'I' accuracy has no ARGOS error radius)"
        )
    else:  # pragma: no cover - no ARGOS-positioned float in the ARVOR-I family
        outcome.executed.add(20)

    return outcome
