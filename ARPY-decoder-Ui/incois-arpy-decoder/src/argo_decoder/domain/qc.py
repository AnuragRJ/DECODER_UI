"""Real-time QC domain model (Argo reference table 2 flags)."""

from __future__ import annotations

from enum import IntEnum


class QcFlag(IntEnum):
    """Argo QC flag values per reference table 2.

    Values match MATLAB ``g_decArgo_qcStr*`` globals exactly:
      0 = no QC performed,
      1 = good,
      2 = probably good,
      3 = probably bad (correctable),
      4 = bad,
      5 = changed,
      6 = not used / not-decoded,
      7 = nominal (reserved),
      8 = estimated / interpolated,
      9 = missing value.
    """

    NO_QC = 0
    GOOD = 1
    PROBABLY_GOOD = 2
    PROBABLY_BAD = 3
    BAD = 4
    CHANGED = 5
    NOT_DECODED = 6
    NOMINAL = 7
    ESTIMATED = 8
    MISSING = 9


class QcTestResult:
    """Result of one RTQC test on one profile."""

    def __init__(self, test_name: str, flag: QcFlag, message: str = "") -> None:
        self.test_name = test_name
        self.flag = flag
        self.message = message

    def __repr__(self) -> str:  # pragma: no cover
        return f"QcTestResult({self.test_name}={self.flag.name})"


def merge_qc_results(results: list[QcTestResult]) -> QcFlag:
    """Worst-flag wins merge (standard Argo QC logic)."""
    if not results:
        return QcFlag.NO_QC
    return max((r.flag for r in results), default=QcFlag.NO_QC)
