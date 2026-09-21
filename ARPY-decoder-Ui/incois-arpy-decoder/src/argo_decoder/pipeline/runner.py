"""Top-level pipeline runner.

Given a populated :class:`DecoderConfig`, executes the decode flow and returns
a structured :class:`PipelineResult`. Phase 0 only exercises IO, metadata, and
null decoding - real science lands in Phases 2-5.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from argo_decoder.config import DecoderConfig, load_config
from argo_decoder.config.models import TransmissionType
from argo_decoder.domain.frames import CycleData, RawFrame
from argo_decoder.io.rsync import CYCLE_FROM_TELEMETRY, CycleFile, discover
from argo_decoder.io.xml_report import write_xml_report
from argo_decoder.metadata import MetadataLoader
from argo_decoder.metadata.models import FloatMeta
from argo_decoder.metadata.validators import validate_float_info, validate_float_meta
from argo_decoder.nc.writer import write_outputs
from argo_decoder.pipeline.metadata_stage import build_metadata_loader
from argo_decoder.platforms import NullDecoder, get_decoder
from argo_decoder.platforms.base import DecodeResult, PlatformDecoder
from argo_decoder.util.logging import get_logger
from argo_decoder.util.time import now_utc, parse_iso_z


@dataclass
class PipelineResult:
    wmo: int
    status: str
    n_cycles: int
    n_files: int
    xml_report: Path | None = None
    nc_checksums: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0


def _build_metadata_loader(config: DecoderConfig) -> MetadataLoader:
    """Construct the metadata backend from config.

    Dispatches to :func:`build_metadata_loader` which picks CSV/JSON/etc.
    based on ``config.metadata.backend``.
    """
    return build_metadata_loader(config)


def _transmission_type_from_meta(meta: FloatMeta | None) -> TransmissionType | None:
    """Return FLOAT_TRANSMISSION_TYPE from meta.json when present.

    Legacy JSON files did not always carry this field; in that case the
    caller keeps the transmission type already present in ``DecoderConfig``.
    """
    if meta is None:
        return None
    raw: object = None
    extra = getattr(meta, "model_extra", None)
    if isinstance(extra, dict):
        raw = extra.get("FLOAT_TRANSMISSION_TYPE")
    if raw in (None, ""):
        raw = getattr(meta, "FLOAT_TRANSMISSION_TYPE", None)
    if raw in (None, ""):
        return None
    try:
        return TransmissionType(int(str(raw)))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Invalid FLOAT_TRANSMISSION_TYPE for WMO {meta.platform_number}: {raw!r}"
        ) from exc


def run_pipeline(
    config: DecoderConfig | None = None,
    *,
    config_path: Path | None = None,
    wmo: int | None = None,
    xml_filename: str | None = None,
    write_nc: bool = True,
    write_xml: bool = True,
    use_null_decoder: bool = False,
) -> PipelineResult:
    """End-to-end decode for one WMO (or a list, in later phases)."""
    t0 = time.perf_counter()
    log = get_logger()
    config = config or load_config(config_path)
    if wmo is not None:
        config.float_wmo = wmo
    wmo_int = config.float_wmo
    if wmo_int is None:
        raise ValueError("No WMO specified for this run")

    log = log.bind(wmo=wmo_int, stage="pipeline")
    log.info("pipeline_start")

    # 1. Load metadata first; it can override transmission_type before discovery.
    loader = _build_metadata_loader(config)
    info = loader.load_info(wmo_int)
    info_report = validate_float_info(info)
    for issue in info_report.issues:
        if issue.level == "error":
            log.error("metadata_error", code=issue.code, message=issue.message)
        else:
            log.warning("metadata_warning", code=issue.code, message=issue.message)

    meta = None
    try:
        meta = loader.load_meta(wmo_int)
        meta_report = validate_float_meta(meta)
        for issue in meta_report.issues:
            if issue.level == "error":
                log.error("meta_error", code=issue.code, message=issue.message)
    except FileNotFoundError:
        log.warning("meta_missing")

    meta_transmission = _transmission_type_from_meta(meta)
    if meta_transmission is not None:
        config.transmission_type = meta_transmission

    # 2. Discover inputs after metadata-driven transmission type is known.
    index = discover(config)

    # 3. Select files for this WMO: map IMEI/PTT to our WMO.
    # PTT is sometimes the full 15-digit IMEI (SBD), sometimes a shorter
    # trailing ID (legacy meta files store a 6-digit suffix), and sometimes
    # a hex/decimal ID (Argos). Match any IMEI directory name that equals or
    # ends-with any of the known identifiers for this float.
    meta_ptt = getattr(meta, "ptt", "") if meta is not None else ""
    meta_imei = getattr(meta, "imei", "") if meta is not None else ""
    id_candidates: set[str] = {str(info.ptt), str(info.wmo)}
    if meta_ptt:
        id_candidates.add(str(meta_ptt))
    if meta_imei:
        id_candidates.add(str(meta_imei))
    id_candidates.discard("")
    ptt_to_wmo: dict[str, int] = {}
    for imei in index.all_imeis():
        for cand in id_candidates:
            if imei == cand or imei.endswith(cand):
                ptt_to_wmo[imei] = wmo_int
                break
    files: list[CycleFile] = index.files_for_wmo(wmo_int, ptt_to_wmo=ptt_to_wmo)
    log.info("input_files", n=len(files))
    if not files:
        # A decode that reads nothing is not a success. Silently returning
        # "ok" here made a mistyped or wrong-layout --input indistinguishable
        # from a real run: the only output was <wmo>_meta.nc, which needs no
        # telemetry at all.
        log.error(
            "no_input_files",
            wmo=wmo_int,
            rsync_data_dir=str(config.paths.rsync_data_dir),
            searched_ids=sorted(id_candidates),
            discovered_ids=sorted(index.all_imeis()),
        )

    # 4. Build cycles from files (Phase 0: placeholder frame list; real parsing
    # in Phase 2).
    cycles: dict[int, CycleData] = {}
    for position, cf in enumerate(files):
        # Files whose name carries no cycle number all share the
        # CYCLE_FROM_TELEMETRY sentinel. Grouping on it would merge every
        # transmission into one bucket, so give each file its own provisional
        # key; the decoder replaces it with the cycle the float transmits.
        # Provisional keys must stay in transmission order once sorted, so
        # they count *up* towards the sentinel rather than down away from
        # it: the earliest file gets the most negative key. Sorting on the
        # raw position would reverse the archive and break the
        # order-based cycle recovery in the APEX decoder.
        #
        # The key also has to reach the decoder, which iterates CycleData
        # values: leaving every unresolved cycle at the bare sentinel
        # would make the transmissions indistinguishable there even
        # though they are separate dict entries here.
        key = (
            cf.cycle
            if cf.cycle != CYCLE_FROM_TELEMETRY
            else CYCLE_FROM_TELEMETRY - (len(files) - 1 - position)
        )
        if cf.cycle != CYCLE_FROM_TELEMETRY and key in cycles:
            # A repeated filename cycle is not trustworthy: the suffix is an
            # operator-assigned cycle label that has been observed to be
            # wrong (2902223: consistently true - 1) and to repeat across
            # distinct surfacings (2902224: cycles 325 and 326 both labelled
            # ``_001``). Merging such files would fuse two surfacings into
            # one cycle. Give this file its own provisional key and let the
            # telemetry-based cycle recovery assign the true cycle; the
            # per-output-cycle "richest kept" policy resolves any remaining
            # duplicates. The demoted keys start below the date-only
            # provisional range ([-len(files), -1]) and strictly decrease
            # with position, preserving the transmission-order invariant.
            key = CYCLE_FROM_TELEMETRY - (len(files) + 1) - position
            while key in cycles:
                key -= 1
        cd = cycles.setdefault(key, CycleData(wmo=wmo_int, cycle=key))
        received = parse_iso_z(cf.received_at) if cf.received_at else None
        with open(cf.path, "rb") as fh:
            payload = fh.read()
        cd.frames.append(
            RawFrame(
                payload=payload,
                cycle=cf.cycle,
                profile=cf.profile,
                received_at=received,
                path=cf.path,
            )
        )

    # 5. Decode
    decoder: PlatformDecoder = (
        NullDecoder(config) if use_null_decoder else get_decoder(info, meta, config)
    )
    log.info("decoder_selected", decoder=type(decoder).__name__)
    decoded: DecodeResult = decoder.decode_float(wmo_int, info, meta, list(cycles.values()))
    if not files:
        decoded.errors.append(
            f"no input files found for WMO {wmo_int} under "
            f"{config.paths.rsync_data_dir}: nothing was decoded"
        )

    # 6. Write NetCDFs
    checksums: dict[str, str] = {}
    if write_nc:
        checksums = write_outputs(decoded, config)

    # 7. Write XML report
    xml_path: Path | None = None
    duration = time.perf_counter() - t0
    if write_xml:
        xml_name = xml_filename or (
            f"co041404_{now_utc().strftime('%Y%m%dT%H%M%SZ')}_{wmo_int}.xml"
        )
        dec_ver = getattr(config, "decoder_version", None) or "0.1.0a0"
        xml_path = write_xml_report(
            config.paths.xml_dir,
            filename=xml_name,
            wmo=wmo_int,
            status="ok" if not decoded.errors else "nok",
            decoder_version=f"python-{dec_ver}",
            float_decoder=type(decoder).__name__,
            message="; ".join(decoded.errors),
            n_files=len(files),
            n_cycles=len(cycles),
            duration_seconds=duration,
        )

    log.info(
        "pipeline_end",
        n_cycles=len(cycles),
        n_files=len(files),
        duration_s=duration,
        nc_files=len(checksums),
    )
    return PipelineResult(
        wmo=wmo_int,
        status="ok" if not decoded.errors else "nok",
        n_cycles=len(cycles),
        n_files=len(files),
        xml_report=xml_path,
        nc_checksums=checksums,
        errors=list(decoded.errors),
        duration_seconds=duration,
    )
