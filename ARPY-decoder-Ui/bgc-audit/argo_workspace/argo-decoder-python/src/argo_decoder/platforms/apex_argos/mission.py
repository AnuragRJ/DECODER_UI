"""Minimal mission helpers for APEX ARGOS floats."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from argo_decoder.platforms.apex_argos.frames import ArgosFix
from argo_decoder.platforms.apex_argos.profile import datetime_to_juld


@dataclass(frozen=True)
class ApexArgosMissionContext:
    launch_date: datetime
    launch_latitude: float | None = None
    launch_longitude: float | None = None


def profile_juld_from_messages(received_at: list[datetime | None]) -> float | None:
    """Return the first selected transmission time.

    This anchors ARGOS fix selection (see :func:`select_profile_fix`) and
    is the fallback profile JULD for a cycle with no usable fix.

    It is **not** the published profile JULD for INCOIS products. The
    ADMT definition of profile JULD is the float's ascent-end time, and
    the APEX engineering message does carry a float clock
    (``EPOCH + TINIT``, decoded in :mod:`.engineering`) -- but neither
    matches the reference. Measured on WMO 2902224 cycle 345:

    ======================================  ==========================
    candidate                               offset vs GDAC ``JULD``
    ======================================  ==========================
    first transmission (this function)      +73.4 min
    ``EPOCH + TINIT - 10 min`` (float RTC)  -85.9 min
    time of the selected surface fix        **0 s**
    ======================================  ==========================

    INCOIS sets ``JULD = JULD_LOCATION``: across 443 GDAC R-files for
    WMO 2902223 and 2902224 the two agree in 440 (99.3%), the three
    exceptions differing by 2-25 min. The decoder therefore publishes
    the fix time; see ``platforms/apex_argos/decoder.py``.
    """
    dates = [dt for dt in received_at if dt is not None]
    if not dates:
        return None
    return datetime_to_juld(min(dates))


# ARGOS location class -> Argo POSITION_QC (reference table 2).
#
# A located ARGOS fix is flagged '1' (good). Measured against the
# ``_Rtraj.nc`` MC=703 blocks of the four reference floats, which hold
# 22 040 located fixes between them:
#
#     WMO 2901304    230/236   97.5% '1'
#     WMO 2902222   6098/6401  95.3% '1'
#     WMO 2902223   4645/4881  95.2% '1'
#     WMO 2902224   5816/6158  94.4% '1'
#
# The residual '2'/'3' flags are *not* a function of the CLS class --
# every class appears under every flag -- so they cannot be assigned
# from the class alone. They are the DAC's own real-time position tests
# (Argo QC Manual v3.9 tests 20/21), applied to the fix sequence rather
# than to the individual fix. Neither a literal impossible-location test
# (all these positions are valid) nor a speed screen reproduces the
# selection: on WMO 2901304 the six flagged fixes have implied speeds of
# 0.44, 1.20, 3.73 and 544 m/s against a 7.18 m/s maximum among the
# accepted ones, so speed separates one of the six at best.
#
# The class-independent part of the convention is therefore applied and
# the DAC's per-fix test is not guessed at. This is a deliberate,
# measured 5% residual rather than an unknown.
#
# Class Z is CLS's "invalid location" marker and is flagged bad.
_LOCATION_CLASS_QC: dict[str, bytes] = {
    "3": b"1",
    "2": b"1",
    "1": b"1",
    "0": b"1",
    "A": b"1",
    "B": b"1",
    "Z": b"4",
}


def position_qc_for_location_class(location_class: str) -> bytes:
    """Return the real-time Argo POSITION_QC flag for an ARGOS class."""
    return _LOCATION_CLASS_QC.get(location_class.strip().upper(), b"1")


def select_profile_fix(fixes: Sequence[ArgosFix], juld: float | None) -> ArgosFix | None:
    """Pick the ARGOS fix that represents the profile surface position.

    Derived from the supplied GDAC ``R*.nc`` references: the profile
    position is the **first fix acquired at or after the profile JULD**,
    i.e. the first surface location obtained once the float began
    transmitting the profile. Verified against all five references for
    which the originating raw file is available.

    Falls back to the last available fix when every fix predates JULD,
    and returns ``None`` when the file carries no usable fix.
    """
    if not fixes:
        return None
    ordered = sorted(fixes, key=lambda fix: fix.at)
    if juld is None:
        return ordered[-1]
    # Allow a small tolerance so a fix stamped in the same second as the
    # first message still counts as "at or after" the profile time.
    threshold = juld - 2.0 / 86400.0
    for fix in ordered:
        if datetime_to_juld(fix.at) >= threshold:
            return fix
    return ordered[-1]


__all__ = [
    "ApexArgosMissionContext",
    "position_qc_for_location_class",
    "profile_juld_from_messages",
    "select_profile_fix",
]
