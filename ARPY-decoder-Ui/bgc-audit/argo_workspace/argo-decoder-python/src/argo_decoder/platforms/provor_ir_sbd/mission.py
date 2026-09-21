"""Mission-configuration state and ascent/descent timing assembly.

Implements the logic MATLAB spreads across ``compute_prv_dates_221_228_229.m``,
``get_float_config_ir_sbd``, and ``update_float_config_ir_sbd_221_230.m``:

* :class:`MissionConfig` accumulates CONFIG parameters seeded from
  :class:`~argo_decoder.metadata.models.FloatMeta` and updated as PARAMETER
  packets are decoded.
* :func:`compute_trans_start_date` / :func:`compute_ascent_end_offset_minutes`
  / :func:`compute_profile_datetime` implement the CTS4 fast-path ascent-end
  formula from MATLAB:

  .. code-block:: matlab

     transStartDate = fix(gpsDate) + transStartHour/24;
     if mod(cycle, inAirPeriod) == 0
         ascentEndDate = transStartDate - (10 + 2*PT31 + round(PT32/100/60)) / 1440;
     else
         ascentEndDate = transStartDate - (10 + round(PT04/100/60)) / 1440;
     end

The module keeps deliberately close to the MATLAB semantics so the
oracle (Docker + MCR) comparison is straightforward.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# CONFIG defaults (Coriolis static-configuration defaults; overridden from meta)
# ---------------------------------------------------------------------------

#: Default buoyancy acquisition duration (centiseconds) used when CONFIG_PT04
#: is missing from the parameter stream (180 s = 3 minutes).
_DEFAULT_PT04_CENTISEC = 18000

#: Default in-air acquisition duration (minutes).
_DEFAULT_PT31_MIN = 5

#: Default in-air pump/buoyancy acquisition duration (centiseconds).
_DEFAULT_PT32_CENTISEC = 33000

#: Default in-air measurement periodicity (cycles); ``1`` means every cycle.
_DEFAULT_PT33_CYCLES = 1


@dataclass
class MissionConfig:
    """Accumulated CONFIG parameters for one float."""

    pt04_centisec: int = _DEFAULT_PT04_CENTISEC
    pt31_min: int = _DEFAULT_PT31_MIN
    pt32_centisec: int = _DEFAULT_PT32_CENTISEC
    pt33_cycles: int = _DEFAULT_PT33_CYCLES

    # Bookkeeping
    last_param_packet_time: datetime | None = None
    updates: int = 0

    def seed_from_meta(self, meta_kv: dict[str, Any]) -> None:
        """Seed CONFIG values from a FloatMeta ``CONFIG_PARAMETER_*`` mapping.

        ``meta_kv`` maps short CONFIG names (e.g. ``"CONFIG_PT04"``) to their
        raw values. PT04/PT32 are in centiseconds; PT31 in minutes; PT33 in
        cycles.
        """
        for key, value in meta_kv.items():
            short = str(key)[:11]
            if short == "CONFIG_PT04":
                self._assign_int("pt04_centisec", value)
            elif short == "CONFIG_PT31":
                self._assign_int("pt31_min", value)
            elif short == "CONFIG_PT32":
                self._assign_int("pt32_centisec", value)
            elif short == "CONFIG_PT33":
                self._assign_int("pt33_cycles", value)

    def apply_param1(
        self,
        pt04_centisec: int | None,
        pt31_min: int | None,
        pt32_centisec: int | None,
        pt33_cycles: int | None,
        packet_time: datetime | None = None,
    ) -> None:
        """Apply values from a PARAMETER_1 packet (last-wins semantics)."""
        if pt04_centisec is not None:
            self.pt04_centisec = int(pt04_centisec)
        if pt31_min is not None:
            self.pt31_min = int(pt31_min)
        if pt32_centisec is not None:
            self.pt32_centisec = int(pt32_centisec)
        if pt33_cycles is not None:
            self.pt33_cycles = int(pt33_cycles)
        if packet_time is not None:
            self.last_param_packet_time = packet_time
        self.updates += 1

    def _assign_int(self, attr: str, value: Any) -> None:
        try:
            if value in (None, "", "nan"):
                return
            iv = int(float(str(value)))
            if iv > 0:
                setattr(self, attr, iv)
        except (TypeError, ValueError):
            return


# ---------------------------------------------------------------------------
# Timing computation
# ---------------------------------------------------------------------------


def _at_midnight_utc(dt: datetime) -> datetime:
    d = dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def compute_trans_start_date(gps_date: datetime, trans_start_hour: int | None) -> datetime | None:
    """Compute ``transStartDate`` (MATLAB convention).

    ``trans_start_hour`` is an integer hour-of-day (0..23) at tabTech1(37).
    If the candidate falls after ``gps_date`` subtract a day (transmission
    hour refers to the prior midnight).
    """
    if trans_start_hour is None:
        return None
    h = int(trans_start_hour)
    if not 0 <= h <= 23:
        return None
    midnight = _at_midnight_utc(gps_date)
    candidate = midnight + timedelta(hours=h)
    if candidate > gps_date:
        candidate -= timedelta(days=1)
    return candidate


def compute_ascent_end_offset_minutes(cycle_number: int, mission: MissionConfig) -> float:
    """Offset in minutes from ``transStartDate`` back to ``ascentEndDate``
    (22 dbar crossing).

    Always includes the 10 minute post-22-dbar wait, plus either:
      * two PT31-minute in-air windows + rounded PT32 buoyancy acquisition
        when ``cycle % PT33 == 0``; or
      * a single PT04 buoyancy acquisition (rounded to nearest minute).
    """
    offset_min = 10.0
    if mission.pt33_cycles > 0 and (cycle_number % mission.pt33_cycles) == 0:
        buoy_min = round((mission.pt32_centisec / 100.0) / 60.0)
        offset_min += 2 * mission.pt31_min + buoy_min
    else:
        buoy_min = round((mission.pt04_centisec / 100.0) / 60.0)
        offset_min += buoy_min
    return offset_min


def compute_profile_datetime(
    *,
    cycle_number: int,
    mission: MissionConfig,
    gps_date: datetime | None,
    trans_start_hour: int | None,
    email_session_dt: datetime | None,
    launch_date: datetime,
) -> tuple[datetime, str, bytes]:
    """Pick the best JULD datetime for an ascending profile.

    Priority:
      1. GPS_ASCENT_END   - transStart - CONFIG offsets (best).
      2. GPS_FIX          - raw GPS fix time when trans hour unknown.
      3. IRIDIUM_SESSION  - first Iridium session timestamp.
      4. LAUNCH_DATE      - ultimate fallback.

    Returns ``(dt, source, qc)``.
    """
    launch = launch_date if launch_date.tzinfo else launch_date.replace(tzinfo=UTC)

    if gps_date is not None:
        gd = gps_date if gps_date.tzinfo else gps_date.replace(tzinfo=UTC)
        trans_start = compute_trans_start_date(gd, trans_start_hour)
        if trans_start is not None:
            off = compute_ascent_end_offset_minutes(cycle_number, mission)
            return trans_start - timedelta(minutes=off), "GPS_ASCENT_END", b"1"
        return gd, "GPS_FIX", b"1"

    if email_session_dt is not None:
        d = email_session_dt if email_session_dt.tzinfo else email_session_dt.replace(tzinfo=UTC)
        return d, "IRIDIUM_SESSION", b"0"

    return launch, "LAUNCH_DATE", b"0"


__all__ = [
    "MissionConfig",
    "compute_ascent_end_offset_minutes",
    "compute_profile_datetime",
    "compute_trans_start_date",
]
