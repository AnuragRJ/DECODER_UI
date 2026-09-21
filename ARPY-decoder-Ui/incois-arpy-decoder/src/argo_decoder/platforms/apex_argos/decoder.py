"""APEX ARGOS :class:`PlatformDecoder` plugin."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import numpy as np

from argo_decoder.config import DecoderTable, get_decoder_table
from argo_decoder.config.decoder_table import DecoderTableEntry
from argo_decoder.config.models import DecoderConfig
from argo_decoder.domain.frames import CycleData, RawFrame
from argo_decoder.io.rsync import CYCLE_FROM_TELEMETRY
from argo_decoder.metadata.models import FloatInfo, FloatMeta
from argo_decoder.nc.metadata_file import build_metadata_dataset
from argo_decoder.nc.technical import build_technical_dataset, build_technical_records
from argo_decoder.nc.trajectory import build_trajectory_dataset
from argo_decoder.platforms.apex_argos.engineering import (
    ApexEngineeringData,
    decode_auxiliary_engineering,
    decode_engineering,
    engineering_layout_for_decoder,
)
from argo_decoder.platforms.apex_argos.frames import (
    ArgosFix,
    ArgosMessage,
    iter_argos_messages_from_payload,
    parse_argos_fixes,
    reception_count,
    select_redundant_messages,
    split_transmission_text,
    transmission_time_span,
)
from argo_decoder.platforms.apex_argos.mission import (
    position_qc_for_location_class,
    profile_juld_from_messages,
    select_profile_fix,
)
from argo_decoder.platforms.apex_argos.profile import (
    ApexArgosProfileLayout,
    cycle_number_wrap_for,
    datetime_to_juld,
    decode_profile,
    juld_to_datetime,
    layout_for_decoder,
    profile_to_xarray,
)
from argo_decoder.platforms.apex_argos.trajectory import (
    ArgosCycleTelemetry,
    build_argos_trajectory_records,
    config_parameter,
)
from argo_decoder.platforms.base import DecodeResult, PlatformDecoder, register_decoder
from argo_decoder.rtqc import apply_cross_cycle_rtqc, open_gebco
from argo_decoder.util.logging import get_logger

_log = get_logger()

#: Pressures at or above this are the ADMT ``99999.0`` fill, not a
#: measurement. Well clear of any real ocean pressure.
FLOAT_FILL_THRESHOLD_DBAR = 99999.0

#: JULD values at or above this are the ADMT ``999999.0`` fill, not a time.
JULD_FILL_THRESHOLD = 999999.0


def _profile_score(ds: object) -> tuple[int, int, int]:
    """Return a deterministic quality score for duplicate ARGOS output cycles."""
    # Kept loosely typed to avoid importing xarray at runtime just for scoring.
    sizes = getattr(ds, "sizes", {})
    attrs = getattr(ds, "attrs", {})
    return (
        int(sizes.get("N_LEVELS", 0)),
        int(attrs.get("n_argos_selected_messages", 0)),
        int(attrs.get("n_crc_ok_messages", 0)),
    )


def _should_replace_existing_profile(existing: object, candidate: object) -> bool:
    """Choose the richer decode when duplicate raw ARGOS files map to one cycle."""
    return _profile_score(candidate) >= _profile_score(existing)


#: Saturated byte values an APF9 reports when a channel was never
#: measured. Seen together across every self-test transmission in the
#: archive (WMO 2901304 2010-11-30, 2010-12-15 and 2011-02-13).
_SATURATED_COUNTS = frozenset({0xFE, 0xFF})

#: The APF9 profile-id sentinel: the saturated counter value 16 the float
#: reports on its first transmission(s) after deployment, with the
#: ``profile_id_overflow`` status bit set. It is a marker, not a count
#: (see ``_resolve_sentinel_cycles``). A transmission whose decoded id is
#: *not* this value must never be routed through the sentinel path, even
#: when the overflow bit is set -- floats past their first counter period
#: keep the overflow bit latched on every subsequent transmission
#: (verified on all 2902224 status words = 0x8001 for cycles 325/326/345).
_PROFILE_ID_SENTINEL = 16


def _dominant_float_id(cycles: Sequence[CycleData], *, frame_length: int) -> int | None:
    """Return the float/hull id most often transmitted by this float.

    Message 1 carries the ``FLT`` float-id field (payload bytes 1-2, the
    hull/controller-board number). Every genuine transmission of one float
    reports the same value, so the mode over all CRC-valid message-1
    copies of the archive is that float's identity.

    Used to withhold foreign transmissions: operator exports have been
    observed to mix other floats' passes into a PTT directory (2902224
    passes inside 2902206's ``152397_..._359.txt``; an id-811 burst inside
    2902222's ``_329`` file). Publishing such a burst under a cycle number
    derived from its profile id would invent a cycle the float never flew.
    Returns ``None`` when no message 1 is available, disabling the guard.
    """
    counts: Counter[int] = Counter()
    for cycle in cycles:
        for frame in cycle.frames:
            try:
                messages = iter_argos_messages_from_payload(
                    frame.payload, frame_length=frame_length
                )
            except Exception:
                continue
            for msg in messages:
                if msg.message_number == 1 and msg.crc_ok and len(msg.payload) >= 3:
                    counts[int.from_bytes(msg.payload[1:3], "big")] += 1
    if not counts:
        return None
    return counts.most_common(1)[0][0]


#: Largest plausible magnitude for the surface-pressure offset, in dbar.
#: Real values sit within a dbar or so of zero; the self tests report
#: 256.0, -1484.8 and -2713.6.
_MAX_PLAUSIBLE_SURFACE_OFFSET_DBAR = 20.0


def _engineering_is_measured(engineering: ApexEngineeringData | None) -> bool:
    """Does this engineering block hold measurements rather than self-test junk?

    The APF9 raises the profile-id sentinel both on its first real cycle
    and on the deployment self test. Only the latter carries saturated
    counters and a nonsensical surface offset, so those two cases are
    told apart on the physics rather than on position in the archive.
    """
    if engineering is None:
        return False
    offset = engineering.surface_pressure_dbar
    if offset is None or abs(offset) > _MAX_PLAUSIBLE_SURFACE_OFFSET_DBAR:
        return False
    counters = (
        engineering.piston_position_surface_counts,
        engineering.air_bladder_pressure_counts,
    )
    return not any(value in _SATURATED_COUNTS for value in counters if value is not None)


#: The cycle whose surfacing bounds the float's first descent.
_FIRST_MISSION_CYCLE = 1


def _cycle_one_start_date(datasets: Mapping[int, Any]) -> str | None:
    """``START_DATE`` from cycle 1's ``JULD_LOCATION``, or ``None``.

    ``START_DATE`` is *"Date (UTC) of the first descent of the float"*
    (Argo User Manual v3.3 §2.4; identical wording in Coriolis
    ``create_nc_meta_file_3_1.m:2696``). It is a **deployment property**:
    fixed for the life of the float, and therefore it must not depend on
    which cycles happen to be in the archive being decoded.

    Coriolis never derives it -- every reference to ``START_DATE`` in the
    chain is a 1:1 mapping from the operator database into the float's
    JSON metadata (e.g.
    ``generate_json_float_meta_apx_argos_.m:1015``), reformatted at
    ``create_nc_meta_file_3_1.m:2974``. Its output is consequently the
    same whether one cycle or three hundred are processed. We have no
    such field, so we fall back to the earliest instant the telemetry can
    evidence, and only when the archive actually contains cycle 1.

    **This is a DAC convention, not the literal specification.** Cycle
    1's ``JULD_LOCATION`` is the first satellite fix *after the first
    ascent*, so it lags the true first descent by most of a cycle: on the
    DPF floats it sits 1.10 cycle lengths after ``LAUNCH_DATE`` (263 h
    against a 6 h programmed prelude). It is used because it is the
    earliest *observed* evidence that the mission had begun, and because
    it reproduces the INCOIS reference exactly on all ten comparable
    floats -- whereas the spec-literal ``LAUNCH_DATE + prelude`` misses
    by a mean of 78 h and a maximum of 258 h.

    Returns ``None`` when cycle 1 is absent or carries no location, so
    the caller leaves the ``_FillValue``. That is permitted: the manual
    declares ``START_DATE:_FillValue = " "``, §2.4.9 "Mandatory meta-data
    parameters" does *not* list the field, and Coriolis itself skips the
    write when the source value is empty
    (``create_nc_meta_file_3_1.m:2968``) -- two of the thirteen metadata
    files shipped with that chain carry an empty ``START_DATE``.

    Extrapolating backwards from a later cycle would invent a deployment
    fact and is deliberately not attempted.
    """
    dataset = datasets.get(_FIRST_MISSION_CYCLE)
    if dataset is None or not hasattr(dataset, "get"):
        return None
    location = dataset.get("JULD_LOCATION")
    if location is None:
        return None
    value = float(np.asarray(location.values).ravel()[0])
    if not np.isfinite(value) or value >= JULD_FILL_THRESHOLD:
        return None
    return juld_to_datetime(value).strftime("%Y%m%d%H%M%S")


def _max_ascent_pressures(datasets: Mapping[int, Any]) -> dict[int, float]:
    """Deepest ascending-profile pressure per cycle, in dbar.

    Feeds the ``GROUNDED`` derivation (see
    :func:`~argo_decoder.platforms.apex_argos.trajectory.grounded_flag`).
    Only ascending profiles count: ``GROUNDED`` asks whether the float
    reached its programmed *profile* pressure, which is a property of the
    ascent, and a descending cast would answer a different question.

    Pressures are taken as decoded -- fill and non-finite values are
    dropped, but QC flags are not applied. That is deliberate and
    measured: screening out QC ``'4'``/``'9'`` levels first drops
    agreement with the INCOIS references from 2 305/2 315 to 1 816/2 315,
    because the deep levels of a short cycle are exactly the ones the
    deepest-pressure and grey-list tests flag. The question is how deep
    the float went, not how good the sample was.

    Cycles with no usable level are omitted, so the caller reports them
    ``'U'`` rather than inventing a depth of zero.
    """
    out: dict[int, float] = {}
    for cycle, ds in datasets.items():
        if cycle < 0:
            continue
        pres = ds.get("PRES") if hasattr(ds, "get") else None
        if pres is None:
            continue
        direction = ds.get("DIRECTION") if hasattr(ds, "get") else None
        if direction is not None:
            raw = np.asarray(direction.values).ravel()
            if raw.size:
                item = raw[0]
                code = item.decode("ascii", "replace") if isinstance(item, bytes) else str(item)
                if code.strip().upper() != "A":
                    continue
        values = np.asarray(pres.values, dtype=float).ravel()
        usable = values[np.isfinite(values) & (values < FLOAT_FILL_THRESHOLD_DBAR)]
        if usable.size:
            out[cycle] = float(usable.max())
    return out


def _named_burst_index(parts: Sequence[bytes], received_at: datetime | None) -> int:
    """Index of the burst the file is named for.

    ``received_at`` is the date discovery read off the file name. A
    ground-station dump is named for the pass that produced it, so the
    burst covering that date is the one entitled to the file's cycle
    number; the others are repeats of passes earlier files already
    delivered.

    A dump can hold more than one burst on the named date -- WMO
    2902201's ``..._2026-01-04_..._359.txt`` opens with a single stray
    reception at 05:41 and carries the actual surfacing from 12:33 to
    22:43. The named cycle goes to the burst with the most receptions
    among those covering the date, because the transmission the file was
    produced for is the one that filled it; giving the number to the
    one-message fragment strands the real profile as unresolved.

    Bursts are ordered by time, so the last one is the newest. That is
    the fallback when the name carries no date or no burst covers it.
    """
    if not parts:
        return 0
    if received_at is not None:
        target = received_at.date()
        matches: list[tuple[int, int]] = []
        for index, part in enumerate(parts):
            span = transmission_time_span(part)
            if span is None:
                continue
            first, last = span
            if first.date() <= target <= last.date():
                matches.append((reception_count(part), index))
        if matches:
            # Most receptions wins; ties break towards the later burst.
            return max(matches)[1]
    return len(parts) - 1


def _split_multi_transmission_cycles(
    cycles: Sequence[CycleData], *, frame_length: int
) -> list[CycleData]:
    """Split any raw file that holds more than one surfacing.

    An ARGOS ground-station dump is a time window, not a cycle. When a
    pass straddles two surfacings the file carries both, and treating it
    as a single cycle lets redundancy selection keep the majority copy
    and silently discard the other transmission.

    Files whose name carries a cycle number are split too. The name tells
    us which cycle the file was *filed under*, not that it holds only that
    cycle: WMO 2902222's ``..._328.txt`` spans 2026-01-03 to 01-11 and
    holds a second surfacing, and merging them put ``JULD_LAST_MESSAGE``
    seven days late.

    Which burst keeps the file's number is decided **by time, not by
    position**. A ground-station dump is named for the pass that triggered
    it, and the older passes it happens to repeat belong to cycles that
    were already delivered by earlier files. The named cycle therefore
    goes to the burst containing the file's own reception date -- the same
    ``min(dataDateList)`` comparison Coriolis makes in
    ``split_argos_file.m:74-88`` -- falling back to the latest burst when
    the name carries no date. Taking the *first* burst instead is what
    dated WMO 2902206 cycle 360 to 2026-01-05 when its own file is named
    for the 10th, five days late.

    The remaining bursts fall through to telemetry-based cycle recovery
    like any other unresolved transmission, taking successively lower
    provisional keys so the list stays in transmission order once sorted,
    which is what the order-based recovery relies on.
    """
    del frame_length  # the split works on the text, not parsed frames
    if not cycles:
        return []
    out: list[CycleData] = []
    next_key = min(min(c.cycle for c in cycles), CYCLE_FROM_TELEMETRY) - 1
    for cycle in cycles:
        if len(cycle.frames) != 1:
            out.append(cycle)
            continue
        frame = cycle.frames[0]
        parts = split_transmission_text(frame.payload)
        if len(parts) < 2:
            out.append(cycle)
            continue
        named = _named_burst_index(parts, frame.received_at)
        for position, part in enumerate(parts):
            key = cycle.cycle if position == named else next_key
            if position != named:
                next_key -= 1
            split = CycleData(wmo=cycle.wmo, cycle=key)
            split.frames.append(
                RawFrame(payload=part, cycle=key, profile=key, received_at=frame.received_at)
            )
            out.append(split)
        _log.info(
            "apex_argos_file_split_into_transmissions",
            wmo=cycle.wmo,
            n_transmissions=len(parts),
        )
    return sorted(out, key=lambda c: c.cycle)


def _resolve_sentinel_cycles(
    cycles: Sequence[CycleData],
    *,
    layout: ApexArgosProfileLayout,
    decoder_id: int,
    frame_length: int,
    np0: int,
) -> dict[int, int]:
    """Assign cycle numbers to transmissions whose profile id is a sentinel.

    On its first transmission after deployment the APF9 reports the
    saturated profile id 16 with the ``profile_id_overflow`` status bit
    set. That is a marker, not a count, and when the file name carries no
    cycle either (``<ptt>_<date>.txt`` archives) there is nothing left to
    read the number from.

    Transmission order supplies it: the files are already in
    chronological order, so a sentinel that sits ``k`` positions before
    the first file with a usable id belongs ``k`` cycles earlier. A
    sentinel *before* the deployment -- the pre-deployment self test --
    therefore lands on a non-positive number and is filtered out
    downstream instead of being published.

    Order alone is not enough to *trust* the result, though. The APF9
    also raises the sentinel on its deployment self test, whose
    engineering block is saturated rather than measured, and that
    transmission is not a cycle at all. On WMO 2901304 the 2011-02-13
    file reports a 256.0 dbar surface offset, piston counts of 254 and an
    air-bladder count of 255 -- the same saturated bytes the two
    pre-deployment test files carry -- while the real cycle 1 that GDAC
    publishes (2011-02-14, park piston 15, pump 11972 s) is absent from
    the archive entirely. Numbering the self test "cycle 1" would publish
    saturated counters under a real cycle's identity.

    Such a transmission is therefore left unresolved: the caller keeps
    its negative provisional key and the writer withholds it. A sentinel
    is only assigned a cycle number when its engineering block reads as a
    genuine measurement.

    Returns a mapping keyed by the provisional (negative) cycle key.
    """
    resolved: dict[int, int] = {}
    anchor_index: int | None = None
    anchor_cycle: int | None = None
    for index, cycle in enumerate(cycles):
        if cycle.cycle > CYCLE_FROM_TELEMETRY:
            continue
        messages: list[ArgosMessage] = []
        for frame in cycle.frames:
            messages.extend(
                iter_argos_messages_from_payload(frame.payload, frame_length=frame_length)
            )
        selected = select_redundant_messages(messages)
        engineering = decode_engineering(selected, decoder_id=decoder_id)
        if engineering is not None and engineering.profile_id_overflow:
            continue
        decoded_cycle = decode_profile(selected, layout=layout).output_cycle_number
        if decoded_cycle is None:
            continue
        anchor_index, anchor_cycle = index, decoded_cycle + np0
        break
    if anchor_index is None or anchor_cycle is None:
        return resolved
    for index, cycle in enumerate(cycles):
        if cycle.cycle > CYCLE_FROM_TELEMETRY or index >= anchor_index:
            continue
        messages = []
        for frame in cycle.frames:
            messages.extend(
                iter_argos_messages_from_payload(frame.payload, frame_length=frame_length)
            )
        engineering = decode_engineering(select_redundant_messages(messages), decoder_id=decoder_id)
        if not _engineering_is_measured(engineering):
            continue
        resolved[cycle.cycle] = anchor_cycle - (anchor_index - index)
    return resolved


@register_decoder
class ApexArgosDecoder(PlatformDecoder):
    """Decoder for WRC/APEX floats over ARGOS."""

    platform_type = "apex_argos"

    def __init__(self, config: DecoderConfig, *, decoder_table: DecoderTable | None = None) -> None:
        super().__init__(config)
        self._table = decoder_table or get_decoder_table()

    def can_handle(self, info: FloatInfo, meta: FloatMeta | None) -> bool:
        del meta
        entry: DecoderTableEntry | None = None
        if info.decoder_id > 0:
            try:
                entry = self._table.by_decoder_id(info.decoder_id)
            except KeyError:
                entry = None
        if entry is None:
            try:
                entry = self._table.by_platform_version(info.float_type, info.decoder_version)
            except KeyError:
                return False
        return entry.transmission == "ARGOS" and entry.platform_type == "APEX"

    @staticmethod
    def _counter_wrap(
        layout: ApexArgosProfileLayout, info: FloatInfo, cycle: CycleData
    ) -> int | None:
        """Roll-over offset for this cycle's transmitted profile id.

        Derived from how long the float has been deployed when this
        transmission was received, so a float still inside its first
        counter period gets ``0`` rather than a tabulated constant.
        Returns ``None`` when the layout has no rolling counter, leaving
        ``decode_profile`` on its static offset.
        """
        if layout.counter_modulus <= 0:
            return None
        received = [f.received_at for f in cycle.frames if f.received_at is not None]
        launch = getattr(info, "launch_date", None)
        if not received or launch is None:
            return 0
        # Raw ARGOS timestamps are naive UTC; registry launch dates are
        # tz-aware. Compare on a single convention rather than crashing.
        first = min(received)
        if first.tzinfo is None:
            first = first.replace(tzinfo=UTC)
        if launch.tzinfo is None:
            launch = launch.replace(tzinfo=UTC)
        elapsed_hours = (first - launch).total_seconds() / 3600.0
        return cycle_number_wrap_for(
            layout,
            elapsed_hours=elapsed_hours,
            cycle_length_hours=float(info.cycle_length_hours or 0) or None,
        )

    def decode_float(
        self, wmo: int, info: FloatInfo, meta: FloatMeta | None, cycles: list[CycleData]
    ) -> DecodeResult:
        result = DecodeResult(
            wmo=wmo,
            cycles=cycles,
            info=info,
            meta=meta,
            decoder_version=info.decoder_version,
            institution=(meta.data_centre if meta is not None and meta.data_centre else "CORIOLIS"),
        )
        try:
            entry = self._table.by_decoder_id(info.decoder_id)
            layout = layout_for_decoder(info.decoder_id, entry.profile_class)
        except KeyError as exc:
            result.errors.append(str(exc))
            return result

        # TEST004 (position on land) needs a bathymetry grid. Opened once
        # per float and reused for every cycle: the file is multi-gigabyte,
        # so re-opening per profile would be prohibitive. ``open_gebco``
        # returns None when the grid is not configured or not present, in
        # which case the test is simply not run.
        bathymetry = open_gebco(self.config.rtqc.reference_files.gebco_file)
        if bathymetry is None:
            _log.debug("apex_argos_test004_skipped", wmo=wmo, reason="no_gebco_grid")

        telemetry: dict[int, ArgosCycleTelemetry] = {}
        #: Earliest ARGOS fix per output cycle, across every burst that
        #: maps to it. A cycle assembled from several raw bursts (repeated
        #: filename-cycle demotion) must anchor its mono JULD on the
        #: surfacing's first fix regardless of which burst is retained
        #: (2902224: the kept Jan-2 burst's first fix is 00:28 while the
        #: Jan-1 19:24:55 surfacing fix lives in another burst).
        earliest_fix_by_cycle: dict[int, ArgosFix] = {}
        #: Distinct raw filename-cycle keys that contributed to each output
        #: cycle. Only cycles with more than one *distinct* raw key were
        #: assembled from a repeated-suffix demotion (the 2902224 case);
        #: cycles whose only candidate has a single (even provisional)
        #: key -- e.g. date-only 1005 files split into bursts -- keep the
        #: normal first-fix convention.
        raw_keys_by_cycle: dict[int, set[int]] = {}
        #: All ARGOS fixes and CRC-valid message times across every burst
        #: mapping to each output cycle. Used to union the Rtraj telemetry
        #: of multi-burst (repeated-suffix demoted) cycles so MC 703
        #: carries every fix of the surfacing and MC 704 is the surfacing's
        #: last message, matching the reference.
        fixes_by_cycle: dict[int, list[ArgosFix]] = {}
        msg_times_by_cycle: dict[int, list[datetime]] = {}
        engineering_by_cycle: dict[int, ApexEngineeringData] = {}
        ordered_cycles = _split_multi_transmission_cycles(
            sorted(cycles, key=lambda c: c.cycle), frame_length=entry.frame_length
        )
        expected_float_id = _dominant_float_id(ordered_cycles, frame_length=entry.frame_length)
        sentinel_cycles = _resolve_sentinel_cycles(
            ordered_cycles,
            layout=layout,
            decoder_id=info.decoder_id,
            frame_length=entry.frame_length,
            np0=info.profile_count_offset,
        )
        for cycle in ordered_cycles:
            messages: list[ArgosMessage] = []
            fixes: list[ArgosFix] = []
            for frame in cycle.frames:
                messages.extend(
                    iter_argos_messages_from_payload(
                        frame.payload,
                        frame_length=entry.frame_length,
                        received_at=frame.received_at,
                    )
                )
                fixes.extend(parse_argos_fixes(frame.payload))
            selected = select_redundant_messages(messages)
            decoded = decode_profile(
                selected, layout=layout, cycle_number_wrap=self._counter_wrap(layout, info, cycle)
            )
            # Engineering / technical state for this cycle. Decoded once
            # here and attached to the dataset so downstream products
            # consume the object rather than reparsing messages.
            engineering = decode_engineering(selected, decoder_id=info.decoder_id)
            # Auxiliary engineering block: the tail of the last message
            # after the profile samples (D3 p.7).
            # ARGOS reception statistics (D2 rows 239-249). Derived from
            # the received satellite data, so they need no float
            # telemetry beyond identifying the cycle.
            if engineering is not None:
                classes: dict[str, int] = {}
                for one_fix in fixes:
                    key = one_fix.location_class.strip().upper()
                    if key:
                        classes[key] = classes.get(key, 0) + 1
                engineering.n_argos_positions = len(fixes)
                engineering.argos_position_classes = classes
                engineering.n_transmission_frames = len(messages)
                engineering.n_transmission_frames_crc_ok = sum(1 for msg in messages if msg.crc_ok)
            if engineering is not None and decoded.auxiliary_bytes:
                eng_layout = engineering_layout_for_decoder(info.decoder_id)
                if eng_layout is not None:
                    decode_auxiliary_engineering(decoded.auxiliary_bytes, eng_layout, engineering)
            # The transmitted profile id is the primary cycle source. It is
            # not always usable: on the first transmission after deployment
            # the APF9 reports the saturated id 16 with the
            # ``profile_id_overflow`` status bit set, which is a sentinel and
            # not a cycle count (verified on 2901339 cycle 0 and on 2901304's
            # two pre-deployment test transmissions plus its cycle 1). When
            # the name carries no cycle either, fall back to the file's
            # position in transmission order rather than publishing the
            # sentinel as if it were a real cycle number.
            output_cycle = decoded.output_cycle_number
            if output_cycle is not None:
                # cycle = profile_id + wrap + np0. The wrap is a firmware
                # property (8-bit roll-over) already applied by the profile
                # layout; np0 is the deployment offset from the registry.
                output_cycle += info.profile_count_offset
            # Foreign transmissions must never be published under this
            # float's cycles. The message-1 FLT field identifies the
            # transmitter; a burst whose id is not this float's is another
            # float's pass mixed into the archive (operator export
            # artifact, verified on 2902206/2902222 raw files). Withhold
            # it entirely -- profile, engineering and trajectory.
            if (
                expected_float_id is not None
                and engineering is not None
                and engineering.float_id is not None
                and engineering.float_id != expected_float_id
            ):
                _log.info(
                    "apex_argos_foreign_transmission_withheld",
                    wmo=wmo,
                    raw_cycle=cycle.cycle,
                    float_id=engineering.float_id,
                    expected_float_id=expected_float_id,
                )
                continue
            overflowed = engineering is not None and engineering.profile_id_overflow
            sentinel_id = decoded.profile_number == _PROFILE_ID_SENTINEL
            if overflowed and sentinel_id and cycle.cycle <= CYCLE_FROM_TELEMETRY:
                # The saturated profile id 16 is a sentinel, not a count,
                # and the file name carries no cycle either. Fall back to
                # the value derived from transmission order. Each such
                # transmission carries its own provisional key (see
                # ``pipeline.runner``), so they resolve independently.
                #
                # The gate on ``sentinel_id`` is load-bearing: the overflow
                # bit alone is not a sentinel. Floats past their first
                # 256-cycle counter period keep the bit latched on every
                # transmission (2902224: status 0x8001 on all cycles), so
                # an overflowed *real* cycle on a provisional key must be
                # numbered from its telemetry like any other cycle.
                output_cycle = sentinel_cycles.get(cycle.cycle)
            if output_cycle is None:
                output_cycle = cycle.cycle
            # Fix selection is anchored on the first transmission, which
            # bounds the profile from above (see mission.select_profile_fix).
            transmission_juld = profile_juld_from_messages([msg.received_at for msg in selected])
            fix = select_profile_fix(fixes, transmission_juld)
            # INCOIS sets the profile JULD to the time of the selected
            # surface fix: across 443 GDAC R-files for WMO 2902223 and
            # 2902224, JULD equals JULD_LOCATION in 440 (99.3%). Verified
            # end-to-end on 2902223 cycle 348, where the raw file is
            # available and the selected fix reproduces the reference
            # JULD exactly. The first-transmission time is retained as
            # the fallback when the cycle carries no usable fix.
            juld = datetime_to_juld(fix.at) if fix is not None else transmission_juld
            ds = profile_to_xarray(
                decoded,
                wmo=wmo,
                cycle=output_cycle,
                platform_type=info.float_type,
                decoder_version=info.decoder_version,
                decoder_id=info.decoder_id,
                juld=juld,
                latitude=fix.latitude if fix is not None else None,
                longitude=fix.longitude if fix is not None else None,
                juld_location=datetime_to_juld(fix.at) if fix is not None else None,
                position_qc_in=(
                    position_qc_for_location_class(fix.location_class) if fix is not None else None
                ),
                profile_pressure_dbar=config_parameter(meta, "CONFIG_ProfilePressure_dbar"),
                bathymetry=bathymetry,
                extra_attrs={
                    "raw_cycle_number": cycle.cycle,
                    "frame_length": entry.frame_length,
                    "n_argos_messages": len(messages),
                    "n_argos_selected_messages": len(selected),
                    "n_crc_ok_messages": sum(1 for msg in messages if msg.crc_ok),
                    "n_argos_fixes": len(fixes),
                    **({"engineering": engineering.as_dict()} if engineering is not None else {}),
                    **({"argos_location_class": fix.location_class} if fix is not None else {}),
                },
            )
            # Trajectory telemetry: keep the richest observation per
            # output cycle, mirroring the mono-profile selection policy.
            entry_tel = ArgosCycleTelemetry(
                cycle_number=output_cycle,
                fixes=list(fixes),
                # CRC-valid receptions define the transmission window.
                # Verified on cycle 327 of 2902222: the CRC-ok first and
                # last reception reproduce the reference
                # JULD_FIRST_MESSAGE and JULD_LAST_MESSAGE exactly,
                # whereas raw receptions include a corrupt earlier frame
                # and the redundancy-selected subset stops too early.
                message_times=[
                    m.received_at for m in messages if m.received_at is not None and m.crc_ok
                ],
                engineering=engineering,
            )
            if engineering is not None:
                engineering_by_cycle[output_cycle] = engineering

            prior = telemetry.get(output_cycle)
            if prior is None or len(entry_tel.fixes) >= len(prior.fixes):
                telemetry[output_cycle] = entry_tel

            existing = result.mono_profile_datasets.get(output_cycle)
            if existing is None or _should_replace_existing_profile(existing, ds):
                if existing is not None:
                    ds.attrs["superseded_raw_cycle_number"] = existing.attrs.get(
                        "raw_cycle_number",
                        -1,
                    )
                result.mono_profile_datasets[output_cycle] = ds
                kept = True
            else:
                kept = False
            # A cycle assembled from several raw bursts (repeated
            # filename-cycle demotion) must keep the *surfacing's* date:
            # the mono JULD/JULD_LOCATION is the earliest fix of any burst
            # belonging to the output cycle (the Rtraj MC702 anchor). The
            # per-burst dataset JULD is the retained burst's own selected
            # fix (anchored on the redundancy-selected first message,
            # which can be later than the surfacing's first fix), so the
            # earliest fix is tracked across all bursts and stamped at
            # the end. Single-burst cycles are unaffected (their earliest
            # fix is their own).
            raw_keys_by_cycle.setdefault(output_cycle, set()).add(cycle.cycle)
            fixes_by_cycle.setdefault(output_cycle, []).extend(fixes)
            msg_times_by_cycle.setdefault(output_cycle, []).extend(
                m.received_at for m in messages if m.received_at is not None and m.crc_ok
            )
            for one_fix in fixes:
                if one_fix.at is None:
                    continue
                earliest = earliest_fix_by_cycle.get(output_cycle)
                if earliest is None or one_fix.at < earliest.at:
                    earliest_fix_by_cycle[output_cycle] = one_fix
            _log.info(
                "apex_argos_cycle_decoded",
                wmo=wmo,
                raw_cycle=cycle.cycle,
                output_cycle=output_cycle,
                messages=len(messages),
                selected=len(selected),
                levels=ds.sizes.get("N_LEVELS", 0),
                kept=kept,
            )

        # Stamp the surfacing's earliest fix onto the mono profile date —
        # but only for cycles assembled from a repeated-suffix demotion,
        # i.e. cycles to which more than one distinct raw filename-cycle
        # key contributed (2902224: `_001` and `_011` both map to cycle
        # 325). For those cycles the retained dataset's own JULD is the
        # retained burst's selected fix, which can be later than the
        # surfacing's first fix (2902224 cyc325: Jan-2 00:28 vs Jan-1
        # 19:24:55). The earliest fix across all bursts is the Rtraj MC702
        # anchor and matches INCOIS's JULD==JULD_LOCATION convention.
        # All other cycles — single raw file, or date-only files whose
        # extra bursts are strays of the previous surfacing (1005 fleet)
        # — keep their existing first-fix convention untouched.
        for cycle_num, ds in result.mono_profile_datasets.items():
            if len(raw_keys_by_cycle.get(cycle_num, ())) < 2:
                continue
            earliest = earliest_fix_by_cycle.get(cycle_num)
            if earliest is None:
                continue
            earliest_juld = datetime_to_juld(earliest.at)
            for attr in ("JULD", "JULD_LOCATION"):
                current = ds.variables[attr].values
                if current is not None and float(current.ravel()[0]) > earliest_juld:
                    ds.variables[attr].values = earliest_juld

        # Union the Rtraj telemetry of multi-burst (repeated-suffix
        # demoted) cycles -- the Rtraj counterpart of the mono-JULD anchor
        # above. The per-cycle ``telemetry`` currently keeps the richest
        # single burst, but the reference publishes every fix of the
        # surfacing (MC 703) and the surfacing's last message (MC 704):
        # 2902224 cyc325 = 7 fixes across the Jan-1/Jan-2 bursts and MC 704
        # = Jan-2 03:11:46; cyc326 = 8 fixes and MC 704 = Jan-12 02:09:44.
        # Union message times (so MC 702/704 are the surfacing's min/max
        # CRC-valid receptions) and deduplicate fixes by (time, position).
        # Single-key cycles keep the existing richest-burst telemetry.
        for cycle_num in list(telemetry):
            if len(raw_keys_by_cycle.get(cycle_num, ())) < 2:
                continue
            all_fixes = fixes_by_cycle.get(cycle_num, [])
            all_times = msg_times_by_cycle.get(cycle_num, [])
            seen: set[tuple[datetime, float, float]] = set()
            unique_fixes: list[ArgosFix] = []
            for fix in all_fixes:
                if fix.at is None:
                    continue
                fix_key = (fix.at, fix.latitude, fix.longitude)
                if fix_key not in seen:
                    seen.add(fix_key)
                    unique_fixes.append(fix)
            prior_tel = telemetry[cycle_num]
            telemetry[cycle_num] = ArgosCycleTelemetry(
                cycle_number=cycle_num,
                fixes=sorted(unique_fixes, key=lambda f: f.at),
                message_times=sorted(set(all_times)),
                engineering=prior_tel.engineering,
            )
            _log.info(
                "apex_argos_multiburst_trajectory_unioned",
                wmo=wmo,
                cycle=cycle_num,
                n_fixes=len(unique_fixes),
                n_message_times=len(set(all_times)),
            )

        # The grid is a multi-gigabyte file handle; release it as soon as
        # every cycle has been scored.
        if bathymetry is not None:
            bathymetry.close()

        # Cross-cycle RTQC (TEST005/016/018). These compare a profile
        # against its predecessor, so they can only run once every cycle
        # has been decoded. Restricted to resolved cycles: a provisional
        # negative key is not a real position in the float's sequence, so
        # "previous cycle" would be meaningless across it.
        publishable = {c: d for c, d in result.mono_profile_datasets.items() if c >= 0}
        if len(publishable) > 1:
            cross_failures = apply_cross_cycle_rtqc(publishable)
            if cross_failures:
                _log.info(
                    "apex_argos_cross_cycle_rtqc",
                    wmo=wmo,
                    failures={c: sorted(t) for c, t in sorted(cross_failures.items())},
                )

        # Transmissions whose cycle number could not be established keep a
        # negative provisional key. They are real telemetry -- self tests
        # and unattributable receptions -- but publishing them under a
        # pseudo-cycle would invent a cycle the float never flew, and the
        # references carry no such entry.
        unresolved = sorted(c for c in set(engineering_by_cycle) | set(telemetry) if c < 0)
        if unresolved:
            _log.info("apex_argos_cycles_unresolved", wmo=wmo, cycles=unresolved)
        engineering_by_cycle = {c: e for c, e in engineering_by_cycle.items() if c >= 0}
        telemetry = {c: t for c, t in telemetry.items() if c >= 0}

        if engineering_by_cycle:
            tech_records = build_technical_records(engineering_by_cycle)
            if tech_records:
                result.tech_dataset = build_technical_dataset(
                    tech_records,
                    wmo=wmo,
                    meta=meta,
                    institution=result.institution,
                )
                _log.info(
                    "apex_argos_technical_built",
                    wmo=wmo,
                    n_tech_param=len(tech_records),
                    n_cycles=len(engineering_by_cycle),
                )

        # START_DATE precedence, in order:
        #   1. a genuine operator value in the metadata backend -- the
        #      only source Coriolis ever uses;
        #   2. else cycle 1's JULD_LOCATION, when the archive holds
        #      cycle 1 (a DAC convention, see _cycle_one_start_date);
        #   3. else the _FillValue.
        #
        # Passing ``None`` here leaves the metadata value in place, so
        # rule 1 is expressed by *not* overriding: ``metadata_file``
        # already falls back to the backend's ``start_date``.
        result.meta_dataset = build_metadata_dataset(
            wmo=wmo,
            meta=meta,
            institution=result.institution,
            start_date=_cycle_one_start_date(result.mono_profile_datasets),
        )

        if telemetry:
            traj_records = build_argos_trajectory_records(
                list(telemetry.values()),
                meta=meta,
                max_ascent_pressure_dbar=_max_ascent_pressures(result.mono_profile_datasets),
            )
            result.traj_dataset = build_trajectory_dataset(
                traj_records,
                wmo=wmo,
                meta=meta,
                institution=result.institution,
                platform_type=info.float_type,
                firmware_version=info.decoder_version,
            )
            _log.info(
                "apex_argos_trajectory_built",
                wmo=wmo,
                n_measurement=len(traj_records.measurements),
                n_cycle=len(traj_records.cycles),
            )
        return result


__all__ = ["ApexArgosDecoder"]
