"""Time helpers - parsing timestamps used in rsync logs and SBD email file names."""

from __future__ import annotations

from datetime import UTC, datetime


def parse_iso_z(value: str) -> datetime:
    """Parse an ISO-8601 UTC timestamp of the form ``YYYYmmddTHHMMSSZ`` or ``YYYY-MM-DDTHH:MM:SSZ``.

    Returns an aware ``datetime`` in UTC.
    """
    if not value:
        raise ValueError("empty timestamp")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1]
    # Coriolis file-naming convention: no separators, e.g. 20200629T083042
    if len(v) == 15 and v[8] == "T":
        return datetime.strptime(v, "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
    # Allow ISO with separators
    try:
        return datetime.fromisoformat(v).replace(tzinfo=UTC)
    except ValueError:
        # Fall back to date-only
        if len(v) == 8 and v.isdigit():
            return datetime.strptime(v, "%Y%m%d").replace(tzinfo=UTC)
        raise


def now_utc() -> datetime:
    """Return the current time in UTC."""
    return datetime.now(tz=UTC)


def format_co_prefix(dt: datetime | None = None, wmo: int | str = "") -> str:
    """Return the standard Coriolis XML/report prefix ``co041404_<ts>_<wmo>.xml``."""
    dt = dt or now_utc()
    ts = dt.strftime("%Y%m%dT%H%M%SZ")
    return f"co041404_{ts}_{wmo}.xml"
