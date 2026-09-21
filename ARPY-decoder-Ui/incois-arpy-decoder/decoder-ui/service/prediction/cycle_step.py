"""Stage-1: a cycle-scale displacement step for the next-surfacing prediction.

Stage-0's rung-4 step is the *newest observed hop*, treated as one cycle. That is
correct only when the hop is cycle-scale. It is wrong in two measured ways
(`audit/stage1_audit_output.txt`, 5,265 corpus cycles):

* **bursty sampling** — 3.99 % of hops are < 0.5 x the expected interval (a float
  can publish several cycles within hours; 2902089's newest hop is 0.74 d on a
  5.00 d cycle, 2902113's is 0.50 d on a 10.00 d cycle). Using such a hop as a
  full cycle under-predicts the drift and, when the burst positions jump, can
  point anywhere: Stage-0's sub-cycle cases show p90 445 km / RMSE 892 km while
  its cycle-scale cases show p90 178 km / RMSE 207 km.
* **mission gaps** — 0.45 % of hops span more than 1.5 cycles (2902091's newest
  hop is 10.03 d on a 1.00 d cycle). Using such a hop as one cycle over-predicts;
  Stage-0's multi-cycle cases show median 60 km / p90 1,120 km.

Stage-1 therefore estimates the displacement of *approximately one expected
profile cycle* from a window of fixes whose span is closest to that interval,
using only fixes at or before the prediction timestamp:

* **matched window** — scanning back from the newest fix, the *freshest* pair
  ``(older fix, newest fix)`` whose span lies inside ``[0.75, 1.25]`` cycles gives
  the raw displacement (recency beats a marginally better-matched older window,
  because drift evolves). Spans below the band are skipped, never rescaled.
* **normalised window** — when the best span lies in ``(1.25, 3.0]`` cycles the
  displacement is divided by the whole number of cycles it spans
  (``k = round(span / interval) >= 2``), i.e. the mean per-cycle displacement
  over the gap. A gap is never treated as one cycle.
* **median window** (evaluated variant) — component-wise median of the freshest
  matched one-cycle displacements of the last up to three anchors, which is less
  sensitive to a single eddy but lags a changing flow.
* **no usable window** — fewer than two fixes, or no span within 3 cycles (only
  short sub-cycle spans available) → ``None``. The caller then keeps the
  documented Stage-0 step and records why, so Stage-1 never invents a step.

Nothing here reads a fix observed after the newest one; the caller passes the
already-leakage-guarded fix list.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Sequence

#: Selection of the Step-1 step model. ``off`` keeps Stage-0 behaviour exactly.
CYCLE_STEP_ENV = "PREDICTION_CYCLE_STEP"
STEP_OFF = "off"
STEP_WINDOW = "window"
STEP_MEDIAN = "median"
CYCLE_STEP_MODES = (STEP_OFF, STEP_WINDOW, STEP_MEDIAN)

#: Shipped default. Decided by the out-of-sample comparison in
#: ``prediction/validate_cycle.py`` (see STAGE1_REPORT.md); ``off`` restores the
#: Stage-0 baseline byte-for-byte.
#: Shipped default. The Stage-1 comparison against the Stage-0 baseline did not meet
#: the pre-registered ship criterion (see prediction-validation/STAGE1_REPORT.md), so
#: Stage-0 remains the default Predictor and the cycle-scale step is opt-in via
#: ``PREDICTION_CYCLE_STEP=window|median``.
DEFAULT_CYCLE_STEP = STEP_OFF

#: Window bands, in units of the expected cycle interval.
WINDOW_LOW = 0.75
WINDOW_HIGH = 1.25
WINDOW_MAX = 3.0
#: Anchors whose matched windows are pooled by the median variant.
MEDIAN_WINDOWS = 3


@dataclass(frozen=True)
class CycleStep:
    """A displacement representing approximately one expected cycle."""

    dlat_km: float
    dlon_km: float
    basis: str
    span_days: float
    ratio: float
    cycles: int
    windows_used: int


def _ordered_fixes(fixes: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    usable = [
        fix
        for fix in fixes
        if fix.get("lat") is not None and fix.get("lon") is not None and fix.get("juld") is not None
    ]
    usable.sort(key=lambda fix: float(fix["juld"]))
    return usable


def _span(fixes: list[dict[str, Any]], older: int, newer: int) -> float:
    return float(fixes[newer]["juld"]) - float(fixes[older]["juld"])


def matched_window(
    fixes: Sequence[dict[str, Any]], interval_days: float, *, max_cycles: float = WINDOW_MAX
) -> tuple[int, int, float] | None:
    """The freshest window that represents about one cycle, ending at the newest fix.

    Recency wins inside the accepted band: scanning backwards from the newest fix,
    the **first** span whose ratio is in ``[WINDOW_LOW, WINDOW_HIGH]`` is returned,
    because the most recent cycle-scale displacement is the best estimate of the
    next one. Only when no in-band span exists does the search continue to the
    longest admissible span (``<= max_cycles``) so the caller can normalise a
    multi-cycle gap instead of mistaking it for one cycle. Spans shorter than the
    band are skipped, never rescaled: a telemetry burst is not a cycle.
    """
    ordered = _ordered_fixes(fixes)
    if len(ordered) < 2 or not interval_days or interval_days <= 0:
        return None
    newest = len(ordered) - 1
    longest: tuple[int, int, float] | None = None
    for older in range(newest - 1, -1, -1):
        span = _span(ordered, older, newest)
        if span <= 0:
            continue
        if span > max_cycles * interval_days:
            break
        ratio = span / interval_days
        if WINDOW_LOW <= ratio <= WINDOW_HIGH:
            return (older, newest, span)
        if ratio > WINDOW_HIGH:
            longest = (older, newest, span)  # keep scanning: a fresher band hit may exist
    return longest


def _normalise_k(span: float, interval_days: float) -> int | None:
    k = int(round(span / interval_days)) if interval_days > 0 else 0
    return k if k >= 2 else None


def _component_median(steps: list[tuple[float, float]]) -> tuple[float, float]:
    ordered_lat = sorted(step[0] for step in steps)
    ordered_lon = sorted(step[1] for step in steps)
    middle = len(steps) // 2
    if len(steps) % 2:
        return ordered_lat[middle], ordered_lon[middle]
    return (
        0.5 * (ordered_lat[middle - 1] + ordered_lat[middle]),
        0.5 * (ordered_lon[middle - 1] + ordered_lon[middle]),
    )


def cycle_scale_step(
    fixes: Sequence[dict[str, Any]],
    interval_days: float,
    *,
    mode: str = STEP_WINDOW,
    max_cycles: float = WINDOW_MAX,
) -> CycleStep | None:
    """A one-cycle displacement step, or ``None`` when the history cannot give one.

    Returning ``None`` is the documented fallback trigger: the caller keeps the
    Stage-0 step and reports the reason. A step is never fabricated from less
    information than this function requires.
    """
    if mode == STEP_OFF:
        return None
    ordered = _ordered_fixes(fixes)
    if len(ordered) < 2 or not interval_days or interval_days <= 0:
        return None

    if mode == STEP_MEDIAN:
        steps: list[tuple[float, float]] = []
        spans: list[float] = []
        for anchor in range(len(ordered) - 1, max(0, len(ordered) - MEDIAN_WINDOWS) - 1, -1):
            window = matched_window(ordered[: anchor + 1], interval_days, max_cycles=max_cycles)
            if window is None:
                continue
            older, newer, span = window
            ratio = span / interval_days
            older_fix, newer_fix = ordered[older], ordered[newer]
            if ratio < WINDOW_LOW or ratio > max_cycles:
                continue
            k = 1 if ratio <= WINDOW_HIGH else _normalise_k(span, interval_days)
            if k is None:
                continue
            dlat, dlon = _displacement(older_fix, newer_fix)
            steps.append((dlat / k, dlon / k))
            spans.append(span)
        if len(steps) < 2:
            return None
        dlat, dlon = _component_median(steps)
        return CycleStep(
            dlat_km=dlat,
            dlon_km=dlon,
            basis=(
                f"median of {len(steps)} matched one-cycle windows "
                f"(last {min(len(spans), MEDIAN_WINDOWS)} anchors, {min(spans):.2f}-{max(spans):.2f} d spans)"
            ),
            span_days=sum(spans) / len(spans),
            ratio=(sum(spans) / len(spans)) / interval_days,
            cycles=1,
            windows_used=len(steps),
        )

    window = matched_window(ordered, interval_days, max_cycles=max_cycles)
    if window is None:
        return None
    older, newer, span = window
    ratio = span / interval_days
    older_fix, newer_fix = ordered[older], ordered[newer]
    if ratio < WINDOW_LOW:
        return None  # every available span is sub-cycle: no cycle-scale window
    if ratio <= WINDOW_HIGH:
        dlat, dlon = _displacement(older_fix, newer_fix)
        return CycleStep(
            dlat_km=dlat,
            dlon_km=dlon,
            basis=(
                f"cycle-scale window {span:.2f} d = {ratio:.2f} x the {interval_days:.2f} d expected "
                f"interval ({newer - older} fix(es) back)"
            ),
            span_days=span,
            ratio=ratio,
            cycles=1,
            windows_used=1,
        )
    k = _normalise_k(span, interval_days)
    if k is None:
        return None
    dlat, dlon = _displacement(older_fix, newer_fix)
    return CycleStep(
        dlat_km=dlat / k,
        dlon_km=dlon / k,
        basis=(
            f"multi-cycle window {span:.2f} d = {ratio:.2f} cycles, divided by {k} "
            f"(mean per-cycle drift; never treated as one cycle)"
        ),
        span_days=span,
        ratio=ratio,
        cycles=k,
        windows_used=1,
    )


def _displacement(older: dict[str, Any], newer: dict[str, Any]) -> tuple[float, float]:
    from prediction.geometry import displacement_km

    return displacement_km(older["lat"], older["lon"], newer["lat"], newer["lon"])


def resolve_cycle_step_mode(value: str | None = None) -> str:
    """The configured mode, falling back to the documented default."""
    raw = value if value is not None else os.environ.get(CYCLE_STEP_ENV)
    if raw is None:
        return DEFAULT_CYCLE_STEP
    text = str(raw).strip().lower()
    if text in ("", "default"):
        return DEFAULT_CYCLE_STEP
    if text in ("0", "false", "no", "off", "baseline", "stage0"):
        return STEP_OFF
    if text in CYCLE_STEP_MODES:
        return text
    return DEFAULT_CYCLE_STEP


def fallback_reason(fixes: Sequence[dict[str, Any]], interval_days: float, *, mode: str = STEP_WINDOW) -> str:
    """Human-readable reason a cycle-scale step could **not** be built.

    The wording mirrors :func:`cycle_scale_step` exactly: if that function would
    return a step for these fixes, this function says so instead of inventing a
    failure, so the string can be attached to a payload without contradicting it.
    """
    step = cycle_scale_step(fixes, interval_days, mode=mode)
    if step is not None:
        return f"cycle-scale window available ({step.basis})"

    ordered = _ordered_fixes(fixes)
    if len(ordered) < 2:
        return "fewer than two verified fixes in the cached trajectory"
    if not interval_days or interval_days <= 0:
        return "no usable expected cycle interval"
    window = matched_window(ordered, interval_days)
    if window is None:
        newest = float(ordered[-1]["juld"])
        span = newest - float(ordered[0]["juld"])
        if span < WINDOW_LOW * interval_days:
            # every fix is closer together than one cycle: a bursty transmitter, not a
            # cycle-scale history. Stretching a burst into a cycle is exactly what the
            # Stage-1 step refuses to do.
            return (
                f"cached history spans only {span:.2f} d = {span / interval_days:.2f} x the "
                f"{interval_days:.2f} d interval (< {WINDOW_LOW:g} x): telemetry burst, not a cycle"
            )
        return (
            f"no window within {WINDOW_MAX:g} cycles of the {interval_days:.2f} d interval "
            f"(cached history spans {span:.2f} d)"
        )
    span = window[2]
    ratio = span / interval_days
    if ratio < WINDOW_LOW:
        return (
            f"newest usable window spans only {span:.2f} d = {ratio:.2f} x the "
            f"{interval_days:.2f} d interval (< {WINDOW_LOW:g} x): telemetry burst, not a cycle"
        )
    return (
        f"newest admissible window spans {span:.2f} d = {ratio:.2f} cycles, which is not a "
        f"whole number of cycles the step could be normalised by"
    )
