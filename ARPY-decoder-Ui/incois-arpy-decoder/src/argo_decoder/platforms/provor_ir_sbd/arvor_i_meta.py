"""ARVOR-I ``<WMO>_meta.nc`` adapter — telemetry-derived metadata + registry merge.

Implements the Phase-6 design of
``docs/phase_reports/ARVOR_I_META_NC_MAPPING_2026-08-27.md`` on top of the
generic, unmodified ``argo_decoder.nc.metadata_file`` builder and the
existing metadata stack.  The input architecture mirrors the project's
APF9 reference architecture (CSV -> FloatRegistryRow ->
``metadata.builder.build_meta`` -> ``FloatMeta`` -> generic builder); for
ARVOR-I the registry side is the Coriolis ``<WMO>_meta.json`` file read
through :meth:`FloatMeta.from_json_file` (the same contract
``metadata.json_loader.JsonLoader`` serves), and the telemetry side
supplies only what the chain itself could derive from the raw stream.

Field provenance (investigation report §3/§8; never fabricated):

* **Telemetry-derived** (``ArvorScienceResult`` + transport evidence):
  ``PLATFORM_NUMBER``; ``TRANS_SYSTEM='IRIDIUM'`` (Iridium SBD .eml
  transport, PROVEN); ``POSITIONING_SYSTEM='GPS'`` (Tech#1 GPS fixes,
  PROVEN; single system: the ``update_meta_data.m`` L270-283
  IRIDIUM-addition rule is NOT applied because its exclusion lists are
  not resolvable for decIds 222/232 from the public sources and the
  production GDAC files carry a single system — UNKNOWN, documented);
  ``LAUNCH_DATE`` (the established launch constants, equal to GDAC —
  PROVEN); ``PLATFORM_FAMILY='FLOAT'`` (ADMT constant for Argo floats);
  ``PLATFORM_MAKER='NKE'`` (decIds 222/232 are members of
  ``decoderIdListNke`` — PROVEN family fact, not per-float data);
  ``PLATFORM_TYPE='ARVOR'`` (decId 222/232 Arvor family per the chain's
  writer case comments — INFERRED family-level).
* **Registry-supplied** (only when ``meta_json_path`` is given — the
  Coriolis registry json is mandatory in production but absent from this
  workspace): PTT/IMEI, serial numbers, firmware/manual/format ids,
  maker/battery/controller details, project/PI/centre/owner, deployment
  platform, ``LAUNCH_LAT/LON``, ``START_DATE``, sensor/parameter tables,
  pre-deployment calibration sheets, CONFIG blocks.
* **Fills when neither source provides a value** (proper ADMT fills /
  blanks, classified DATA-COVERAGE): everything in the registry list
  above, including ``LAUNCH_LATITUDE``/``LONGITUDE`` = 99999.0 fill (the
  pre-launch mails are factory deck tests, not the deployment site) and
  ``START_DATE`` (the nearest raw evidence is 14 s from the registry
  value — not equal, so not emitted).  Library defaults that would
  publish unproven values (``data_centre='IF'`, ``float_owner=
  'IFREMER'``) are explicitly blanked here.

When no registry json is supplied, ``DATA_CENTRE`` is left blank and the
global ``institution`` attribute is set to ``'CORIOLIS'`` — the same
documented MATLAB default the Phase-4A/4B/5 products use for these
floats (see ``nc/technical_arvor.py``); with a registry json the
registry's ``DATA_CENTRE`` drives both, per the generic builder.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import xarray as xr

from argo_decoder.metadata.models import FloatMeta
from argo_decoder.nc.admt import DOUBLE_FILL, institution_for_data_centre
from argo_decoder.nc.metadata_file import (
    build_metadata_dataset,
    write_metadata_file,
)
from argo_decoder.platforms.provor_ir_sbd.arvor_i_science import (
    ArvorScienceResult,
)

#: decId -> published PLATFORM_TYPE (Arvor family writer case,
#: create_nc_meta_file_3_1.m L1436+; family-level, not per-float).
_DECID_PLATFORM_TYPE = {222: "ARVOR", 232: "ARVOR"}

#: Documented MATLAB default for the ``institution`` global when the float
#: meta json carries no DATA_CENTRE (4A/4B/5 product-family consistency).
_DEFAULT_INSTITUTION = "CORIOLIS"


def _resolve_platform_type(result: ArvorScienceResult | None) -> str:
    if result is None:
        return ""
    from argo_decoder.platforms.provor_ir_sbd.arvor_i_tech import resolve_dec_id

    dec_id = resolve_dec_id(result)
    if dec_id is None:
        return ""
    return _DECID_PLATFORM_TYPE.get(dec_id, "")


def _first_descent_utc(result: ArvorScienceResult | None) -> datetime | None:
    """UTC instant of the float's first descent, or ``None``.

    Argo User's Manual 3.44.0 §2.4.5 defines ``START_DATE`` as the "Date
    (UTC) of the first descent of the float". The Trajectory Cookbook 6.1
    §2.2 (p.19) defines DST (MC 100) as the "Time when float leaves the
    surface, beginning descent" -- the same instant -- and its Arvor annex
    (p.99) records DST as transmitted by the float.

    The earliest decoded ``descent_to_park_start`` across all cycles is
    therefore the first descent. Taking the minimum rather than "cycle 1"
    keeps the rule correct when the first transmitted cycle is not the
    lowest-numbered one, or when cycle 1 was never received.

    Generic: no WMO, hull or cycle literal, and ``None`` when the stream
    carries no dated descent, so the field stays fill rather than being
    invented.
    """

    if result is None:
        return None
    starts = [
        cycle.timing.descent_to_park_start
        for cycle in getattr(result, "cycles", [])
        if getattr(cycle, "timing", None) is not None
        and cycle.timing.descent_to_park_start is not None
    ]
    if not starts:
        return None
    return datetime(1950, 1, 1, tzinfo=UTC) + timedelta(days=float(min(starts)))


def build_arvor_float_meta(
    *,
    wmo: int,
    launch_date: datetime,
    result: ArvorScienceResult | None = None,
    meta_json_path: Path | str | None = None,
) -> FloatMeta:
    """Build the ARVOR-I :class:`FloatMeta`.

    Registry json (Coriolis ``<WMO>_meta.json``) is authoritative for the
    registry fields when supplied; telemetry-derived fields below are
    applied on top only where the registry value is absent (the platform
    number always reflects ``wmo``).  Without a registry json every
    registry-sourced field stays blank/fill — nothing is copied from GDAC.
    """
    if meta_json_path is not None:
        meta = FloatMeta.from_json_file(meta_json_path)
    else:
        meta = FloatMeta()
        meta.launch_qc = "1"

    # --- telemetry-derived (always known for a decoded ARVOR-I stream) ---
    meta.platform_number = str(wmo)
    if not meta.trans_system:
        meta.trans_system = [{"TRANS_SYSTEM_1": "IRIDIUM"}]
    if not meta.positioning_system:
        meta.positioning_system = [{"POSITIONING_SYSTEM_1": "GPS"}]
    if not meta.platform_family:
        meta.platform_family = "FLOAT"
    if not meta.platform_maker:
        meta.platform_maker = "NKE"  # decoderIdListNke membership (PROVEN family)
    if not meta.platform_type:
        meta.platform_type = _resolve_platform_type(result)
    if not meta.launch_date:
        moment = launch_date if launch_date.tzinfo is not None else launch_date.replace(tzinfo=UTC)
        meta.launch_date = moment.strftime("%Y-%m-%dT%H:%M:%S")

    # START_DATE from the decoded first descent -------------------------
    #
    # Argo User's Manual 3.44.0 §2.4.5 defines START_DATE as the "Date
    # (UTC) of the first descent of the float".  For this family that
    # instant is transmitted: the Trajectory Cookbook 6.1 Annex (Arvor,
    # p.99) maps MC 100 (DST) to "Descent to park Start Time ... 2: value
    # is transmitted by the float", and §2.2 (p.19) defines DST as "Time
    # when float leaves the surface, beginning descent" -- the manual's
    # wording for START_DATE.
    #
    # MC 89 (cycle start) is deliberately NOT used: the same annex calls
    # it the "buoyancy reduction start time", i.e. the float is still at
    # the surface pumping oil, 56-132 min before it actually leaves.
    # Publishing that as "first descent" would misdate the event.
    #
    # The operator-declared value (four CSVs, via the registry json)
    # stays authoritative; this only fills the gap when the sheets carry
    # no start date. Derived, never invented: absent a decoded DST the
    # field stays fill.
    if not meta.start_date:
        first_descent = _first_descent_utc(result)
        if first_descent is not None:
            meta.start_date = first_descent.strftime("%Y-%m-%dT%H:%M:%S")

    # --- no-fabrication blanks when the registry json is absent ---
    # START_DATE is exempt: it is now derived from decoded telemetry
    # (above) rather than copied from the registry, so it survives here.
    if meta_json_path is None:
        meta.launch_latitude = float(DOUBLE_FILL)
        meta.launch_longitude = float(DOUBLE_FILL)
        meta.data_centre = ""  # would otherwise default to 'IF'
        meta.float_owner = ""  # would otherwise default to 'IFREMER'

    # Keep the flag consistent with the value it qualifies (Argo
    # reference table 2, QC Manual 3.9 §6.1): '1' "Good data" once a
    # start date is published, '9' "Missing value ... parameter will
    # record FillValue" while it is not. Computed last so it reflects the
    # final state of START_DATE, whatever produced it. Never blank --
    # blank is not a table-2 member and the GDAC FileChecker rejects it
    # (CK_0122).
    meta.start_date_qc = "1" if meta.start_date else "9"

    return meta


def build_arvor_meta_nc(
    *,
    wmo: int,
    launch_date: datetime,
    result: ArvorScienceResult | None = None,
    meta_json_path: Path | str | None = None,
    date_creation: str | None = None,
    date_update: str | None = None,
) -> xr.Dataset:
    """Build the ARVOR-I ``<WMO>_meta.nc`` dataset via the generic builder."""
    meta = build_arvor_float_meta(
        wmo=wmo, launch_date=launch_date, result=result, meta_json_path=meta_json_path
    )
    centre = (meta.data_centre or "").strip()
    ds = build_metadata_dataset(
        wmo=wmo,
        meta=meta,
        institution=centre or "",
        date_creation=date_creation,
        date_update=date_update,
    )
    if not centre:
        # Same documented MATLAB default as the 4A/4B/5 products.
        ds.attrs["institution"] = _DEFAULT_INSTITUTION
    else:
        # The GDAC meta references publish the reference-table-4 name
        # (IN -> INCOIS), not the 2-letter DAC code the generic builder
        # copies from DATA_CENTRE -- same mapping as the mono products.
        ds.attrs["institution"] = institution_for_data_centre(centre)
    return ds


def write_arvor_meta_nc(ds: xr.Dataset, path: Path) -> None:
    """Write the metadata dataset to ``path`` (generic ADMT writer)."""
    write_metadata_file(ds, path)
