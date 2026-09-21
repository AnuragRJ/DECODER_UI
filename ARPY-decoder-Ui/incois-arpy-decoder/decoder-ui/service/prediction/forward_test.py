"""Forward test: does the shipped prediction actually come true?

The calibration radii in ``prediction_calibration.json`` are measured on a
retrospective corpus. The research plan designates a *forward test* as the
mechanism that keeps them honest in production (RESEARCH.md Section I): every
prediction the service issues is recorded once, and when the float later
publishes a genuinely newer verified fix the prediction is scored against it.

Design rules:

* **Recording is idempotent.** A record is keyed by (WMO, the fix the
  prediction was issued from), so re-serving the same cache cannot duplicate
  history; a new record only appears when the float really advances a cycle.
* **Scoring requires a newer verified fix.** A prediction is never scored
  against the fix it came from, and never against a fix whose time is not
  strictly later. No fix ⇒ the record stays open and is reported as pending.
* **Refused predictions are not logged.** ``insufficient_data`` /
  ``insufficient_validation`` rows have no position to test.
* **It is not a profile store.** Lines contain the service's own prediction plus
  the later measured error — no profile values, no measurements, no downloads.
  The existing cache/download remains the only record of upstream data; this
  file is an audit of the prediction feature itself.
* **Never fatal.** Any IO/parse problem degrades to a reported error; the Float
  Status payload is unaffected.

File format: append-only JSON Lines, one object per event::

    {"kind": "issued",  "wmo": 2902223, "issued_from_juld": 27990.0, "predicted_lat": ...}
    {"kind": "scored",  "wmo": 2902223, "observed_lat": ..., "error_km": ..., "within_r50": ...}

Environment:

* ``PREDICTION_FORWARD_LOG`` — ``0`` / ``off`` / ``false`` disables recording
  (metrics are then reported as disabled rather than silently empty).
* ``PREDICTION_FORWARD_LOG_PATH`` — override the file location.
"""

from __future__ import annotations

import json
import math
import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from prediction.features import FloatFeatures
from prediction.geometry import haversine_km

ENABLED_ENV = "PREDICTION_FORWARD_LOG"
PATH_ENV = "PREDICTION_FORWARD_LOG_PATH"
LOG_FILENAME = "prediction_forward_log.jsonl"

#: Files larger than this are rewritten keeping the most recent events, so the
#: audit cannot grow without bound. The cap is deliberately generous: one event
#: per float per cycle is ~1 kB/year for a 30-float fleet.
MAX_BYTES = 4 * 1024 * 1024
KEEP_FRACTION = 0.5

_OFF_VALUES = {"0", "off", "false", "no"}


def log_enabled() -> bool:
    raw = os.environ.get(ENABLED_ENV)
    if raw is None:
        return True
    return raw.strip().lower() not in _OFF_VALUES


def default_log_path() -> Path:
    override = os.environ.get(PATH_ENV)
    if override:
        return Path(override)
    try:
        from event_bus import DATA_DIR  # local import: avoids a hard import cycle

        return Path(DATA_DIR) / "fleet_status" / LOG_FILENAME
    except Exception:
        return Path(__file__).resolve().parents[2] / "data" / "fleet_status" / LOG_FILENAME


def _juld_to_iso(juld: float) -> str:
    return (datetime(1950, 1, 1, tzinfo=UTC) + timedelta(days=float(juld))).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _iso_to_juld(iso: str) -> float | None:
    try:
        when = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return (when - datetime(1950, 1, 1, tzinfo=UTC)).total_seconds() / 86400.0


@dataclass
class ForwardTestEvent:
    kind: str
    wmo: int
    issued_from_juld: float
    record: dict[str, Any]


class ForwardTestLog:
    """Append-only prediction audit with lazy, shared in-memory indexing."""

    def __init__(self, path: Path | None = None, enabled: bool | None = None) -> None:
        self.path = Path(path) if path is not None else default_log_path()
        self.enabled = log_enabled() if enabled is None else bool(enabled)
        self._lock = threading.Lock()
        self._loaded = False
        self._seen: set[str] = set()  # every (wmo, fix) ever recorded
        self._open: dict[str, dict[str, Any]] = {}  # recorded, not yet scored
        self._error: str | None = None

    # ------------------------------------------------------------- internals
    @staticmethod
    def key(wmo: int, issued_from_juld: float) -> str:
        return f"{int(wmo)}:{round(float(issued_from_juld), 6)}"

    def _load(self) -> None:
        """Read the file once per process; tolerate a partial/corrupt tail."""
        if self._loaded:
            return
        self._loaded = True
        if not self.path.is_file():
            return
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except Exception:
                    continue  # a torn line must not break the audit
                if not isinstance(event, dict):
                    continue
                wmo = event.get("wmo")
                juld = event.get("issued_from_juld")
                if wmo is None or juld is None:
                    continue
                key = self.key(int(wmo), float(juld))
                self._seen.add(key)
                if event.get("kind") == "issued":
                    self._open[key] = event
                else:
                    self._open.pop(key, None)
        except Exception as exc:  # unreadable audit is reported, never fatal
            self._error = f"{type(exc).__name__}: {exc}"

    def _append(self, event: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")

    def _rotate_if_needed(self) -> None:
        try:
            if not self.path.is_file() or self.path.stat().st_size <= MAX_BYTES:
                return
            lines = self.path.read_text(encoding="utf-8").splitlines()
            keep = lines[int(len(lines) * (1.0 - KEEP_FRACTION)) :]
            tmp = self.path.with_suffix(".jsonl.tmp")
            tmp.write_text("\n".join(keep) + "\n", encoding="utf-8")
            tmp.replace(self.path)
        except Exception as exc:
            self._error = f"{type(exc).__name__}: {exc}"

    @staticmethod
    def _next_fix_after(
        features: FloatFeatures | None,
        issued_from_juld: float,
        issued_from_cycle: int | None = None,
        expected_interval_days: float | None = None,
    ) -> dict[str, Any] | None:
        """The earliest verified fix that can score this prediction.

        Two conditions, both required:

        * strictly later in time than the issuing fix (never the fix it came
          from), and
        * a *next cycle* observation: a later cycle number when both cycles are
          known, otherwise at least half the expected cycle interval later.

        The second condition exists because a float can publish several cycles
        within a day (burst/telemetry artefacts). Scoring against such a fix
        measures a sub-cycle hop, not the next-profile prediction, and produced
        nonsense errors (2,078 km over 0.86 d) before this rule.
        """
        if features is None:
            return None
        later = [
            fix
            for fix in features.fixes
            if isinstance(fix, dict)
            and fix.get("juld") is not None
            and float(fix["juld"]) > float(issued_from_juld) + 1e-6
            and fix.get("lat") is not None
            and fix.get("lon") is not None
        ]
        if not later:
            return None
        later.sort(key=lambda fix: float(fix["juld"]))
        interval = float(expected_interval_days) if expected_interval_days else None
        for fix in later:
            cycle = fix.get("cycle")
            if cycle is not None and issued_from_cycle is not None and int(cycle) <= int(issued_from_cycle):
                continue  # same or earlier cycle: cannot be the next surfacing
            if interval and interval > 0:
                if float(fix["juld"]) - float(issued_from_juld) < 0.5 * interval:
                    continue  # too soon after the issuing fix to be the next surfacing
                return fix
            return fix
        return None

    # ---------------------------------------------------------------- public
    def observe(
        self,
        features_by_wmo: dict[int, FloatFeatures],
        predictions: dict[int, dict[str, Any]],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Record new predictions and score any whose next fix has arrived."""
        now = now or datetime.now(UTC)
        if not self.enabled:
            return {
                "enabled": False,
                "note": (
                    "forward-test recording disabled by "
                    f"{ENABLED_ENV}; radii rest on the retrospective corpus only"
                ),
            }
        issued = 0
        scored = 0
        with self._lock:
            self._load()
            try:
                # 1. record predictions that are new to the audit
                for wmo, payload in predictions.items():
                    if not isinstance(payload, dict) or not payload.get("available"):
                        continue  # a refusal has no position to test
                    features = features_by_wmo.get(int(wmo))
                    last_fix = features.last_fix if features is not None else None
                    if not last_fix or last_fix.get("juld") is None:
                        continue
                    key = self.key(int(wmo), float(last_fix["juld"]))
                    if key in self._seen:
                        continue
                    event = {
                        "kind": "issued",
                        "wmo": int(wmo),
                        "issued_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "issued_from_juld": round(float(last_fix["juld"]), 6),
                        "issued_from_iso": last_fix.get("juld_iso"),
                        "issued_from_cycle": last_fix.get("cycle"),
                        "issued_from_lat": payload.get("issued_from_position", [None, None])[0]
                        if payload.get("issued_from_position")
                        else None,
                        "issued_from_lon": payload.get("issued_from_position", [None, None])[1]
                        if payload.get("issued_from_position")
                        else None,
                        "target_time_iso": payload.get("target_time_iso"),
                        "predicted_lat": payload.get("predicted_lat"),
                        "predicted_lon": payload.get("predicted_lon"),
                        "method": payload.get("method"),
                        "fallback_rung": payload.get("fallback_rung"),
                        "r50_km": payload.get("r50_km"),
                        "r90_km": payload.get("r90_km"),
                        "region": payload.get("region"),
                        "cycle_class": payload.get("cycle_class"),
                        "expected_interval_days": payload.get("expected_interval_days"),
                        "validation_samples": payload.get("validation_samples"),
                        # Stage-1 pass: the issued record keeps the stage that produced it and
                        # the step it used, so Stage-0 and Stage-1 issues stay distinguishable
                        # and a later scoring run can never mix the two together.
                        "predictor_stage": payload.get("predictor_stage"),
                        "predictor_stage_label": payload.get("predictor_stage_label"),
                        "step_basis": payload.get("step_basis"),
                        "step_cycles": payload.get("step_cycles"),
                        "stage1_fallback_reason": payload.get("stage1_fallback_reason"),
                    }
                    self._append(event)
                    self._seen.add(key)
                    self._open[key] = event
                    issued += 1

                # 2. score open records once a genuinely newer fix exists
                for key, event in list(self._open.items()):
                    wmo = int(event["wmo"])
                    features = features_by_wmo.get(wmo)
                    observed = self._next_fix_after(
                        features,
                        float(event["issued_from_juld"]),
                        event.get("issued_from_cycle"),
                        event.get("expected_interval_days"),
                    )
                    if observed is None:
                        continue
                    predicted_lat = event.get("predicted_lat")
                    predicted_lon = event.get("predicted_lon")
                    if predicted_lat is None or predicted_lon is None:
                        continue
                    error_km = haversine_km(
                        float(predicted_lat),
                        float(predicted_lon),
                        float(observed["lat"]),
                        float(observed["lon"]),
                    )
                    target_juld = _iso_to_juld(str(event.get("target_time_iso") or ""))
                    time_error = (
                        abs(float(observed["juld"]) - target_juld)
                        if target_juld is not None
                        else None
                    )
                    r50 = event.get("r50_km")
                    r90 = event.get("r90_km")
                    scored_event = {
                        **event,
                        "kind": "scored",
                        "scored_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "observed_juld": round(float(observed["juld"]), 6),
                        "observed_iso": observed.get("juld_iso") or _juld_to_iso(float(observed["juld"])),
                        "observed_lat": observed.get("lat"),
                        "observed_lon": observed.get("lon"),
                        "error_km": round(error_km, 3),
                        "time_error_days": None if time_error is None else round(time_error, 4),
                        "within_r50": None if r50 is None else bool(error_km <= float(r50)),
                        "within_r90": None if r90 is None else bool(error_km <= float(r90)),
                    }
                    self._append(scored_event)
                    self._open.pop(key, None)
                    scored += 1
                self._rotate_if_needed()
                self._error = None
            except Exception as exc:
                self._error = f"{type(exc).__name__}: {exc}"
        summary = self.metrics()
        summary["issued_this_call"] = issued
        summary["scored_this_call"] = scored
        return summary

    def metrics(self) -> dict[str, Any]:
        """Aggregate what the audit measured so far (reads its own file)."""
        summary: dict[str, Any] = {
            "enabled": self.enabled,
            "path": str(self.path),
            "issued": 0,
            "scored": 0,
            "pending": 0,
            "error": self._error,
            "methods": {},
            "stages": {},
            "issued_by_stage": {},
            "floats": {},
            "overall": None,
            "note": (
                "deployment-local forward test of the ships-now prediction; "
                "separate from the retrospective corpus calibration"
            ),
        }
        if not self.path.is_file():
            return summary
        scored_rows: list[dict[str, Any]] = []
        issued_keys: set[str] = set()
        scored_keys: set[str] = set()
        issued_by_stage: dict[str, int] = {}
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except Exception:
                    continue
                if not isinstance(event, dict) or "wmo" not in event:
                    continue
                key = self.key(int(event["wmo"]), float(event.get("issued_from_juld") or 0.0))
                if event.get("kind") == "scored":
                    scored_keys.add(key)
                    scored_rows.append(event)
                else:
                    issued_keys.add(key)
                    # Stage-1 pass: pending issues are attributed to the stage that made
                    # them, so a validation deployment can see the mix before anything is
                    # scored (rows without a stage predate the Stage-1 pass: Stage-0)
                    stage_key = str(event.get("predictor_stage") or "stage0")
                    issued_by_stage[stage_key] = issued_by_stage.get(stage_key, 0) + 1
        except Exception as exc:
            summary["error"] = f"{type(exc).__name__}: {exc}"
            return summary
        summary["issued"] = len(issued_keys | scored_keys)
        summary["issued_by_stage"] = dict(sorted(issued_by_stage.items()))
        summary["scored"] = len(scored_keys)
        summary["pending"] = len(issued_keys - scored_keys)
        if not scored_rows:
            return summary
        errors = [float(row["error_km"]) for row in scored_rows if row.get("error_km") is not None]
        summary["overall"] = _summarize(errors, scored_rows)
        per_method: dict[str, list[dict[str, Any]]] = {}
        per_stage: dict[str, list[dict[str, Any]]] = {}
        per_float: dict[str, list[dict[str, Any]]] = {}
        for row in scored_rows:
            per_method.setdefault(str(row.get("method") or "unknown"), []).append(row)
            # records written before the Stage-1 pass carry no stage; they are all Stage-0
            per_stage.setdefault(str(row.get("predictor_stage") or "stage0"), []).append(row)
            per_float.setdefault(str(row.get("wmo")), []).append(row)
        summary["methods"] = {
            method: _summarize(
                [float(r["error_km"]) for r in rows if r.get("error_km") is not None], rows
            )
            for method, rows in sorted(per_method.items())
        }
        summary["stages"] = {
            stage: _summarize(
                [float(r["error_km"]) for r in rows if r.get("error_km") is not None], rows
            )
            for stage, rows in sorted(per_stage.items())
        }
        summary["floats"] = {
            wmo: _summarize([float(r["error_km"]) for r in rows if r.get("error_km") is not None], rows)
            for wmo, rows in sorted(per_float.items())
        }
        return summary


def _summarize(errors: list[float], rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    out: dict[str, Any] = {"n": len(errors)}
    if errors:
        ordered = sorted(errors)
        out.update(
            median_km=round(_quantile(ordered, 0.5), 2),
            mean_km=round(sum(ordered) / len(ordered), 2),
            p90_km=round(_quantile(ordered, 0.9), 2),
            max_km=round(ordered[-1], 2),
        )
    inside50 = [r for r in rows if r.get("within_r50") is not None]
    inside90 = [r for r in rows if r.get("within_r90") is not None]
    if inside50:
        out["within_r50_pct"] = round(100.0 * sum(bool(r["within_r50"]) for r in inside50) / len(inside50), 1)
    if inside90:
        out["within_r90_pct"] = round(100.0 * sum(bool(r["within_r90"]) for r in inside90) / len(inside90), 1)
    times = [float(r["time_error_days"]) for r in rows if r.get("time_error_days") is not None]
    if times:
        out["median_time_error_days"] = round(sorted(times)[len(times) // 2], 3)
    return out


def _quantile(ordered: list[float], q: float) -> float:
    if not ordered:
        return float("nan")
    if len(ordered) == 1:
        return ordered[0]
    position = q * (len(ordered) - 1)
    low = int(math.floor(position))
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


#: Process-wide instance: one audit file per service, shared by every request.
_LOG: ForwardTestLog | None = None
_LOG_LOCK = threading.Lock()


def get_log() -> ForwardTestLog:
    global _LOG
    with _LOG_LOCK:
        if _LOG is None:
            _LOG = ForwardTestLog()
        return _LOG


def reset_log_for_tests() -> None:
    """Drop the process-wide instance (unit tests use their own paths)."""
    global _LOG
    with _LOG_LOCK:
        _LOG = None
