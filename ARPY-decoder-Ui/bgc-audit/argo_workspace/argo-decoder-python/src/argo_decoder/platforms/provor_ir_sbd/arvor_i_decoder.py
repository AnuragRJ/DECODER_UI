"""Generic ARVOR-I SBE41CP Iridium-SBD decoder plugin (adapter).

Routes floats whose ``decoder_table`` entry carries
``profile_class: arvor_i_sbe41cp`` (engines 5900A05 -> ids 222/223/225 and
5900A05B -> id 232) onto the existing validated ARVOR-I stack
(Phases 3-9): :func:`read_arvor_i_eml` -> :func:`reconstruct_science` ->
the tech / Rtraj / mono-profile / meta writers.

This module is glue only. It contains no parsing or science logic and no
per-float conditionals: the engine is identified from the telemetry
itself (Tech#1 firmware checksum via :func:`resolve_engine`, mirroring
``check_decoder_id.m``), never from the WMO or the sheet firmware string.

Outputs are written by the existing ARVOR-I writers into the generic
pipeline layout (``nc/<wmo>/{<wmo>_tech,_Rtraj,_meta}.nc`` +
``profiles/R<wmo>_NNN.nc``), so the generic NetCDF writer is bypassed:
its ADMT wrappers implement the NKE demo layouts, and reshaping the
validated ARVOR-I datasets through them would alter output semantics.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from argo_decoder.config.models import DecoderConfig
from argo_decoder.domain.frames import CycleData
from argo_decoder.metadata.models import FloatInfo, FloatMeta
from argo_decoder.nc.rtraj_arvor import build_arvor_rtraj_nc_dataset, write_arvor_rtraj_file
from argo_decoder.nc.technical_arvor import write_arvor_tech_nc
from argo_decoder.platforms.base import DecodeResult, PlatformDecoder, register_decoder
from argo_decoder.platforms.provor_ir_sbd.arvor_i import (
    ARVOR_I_DECODER_IDS,
    ArvorIridiumMessage,
    momsn_from_filename,
    read_arvor_i_eml,
    resolve_engine,
)
from argo_decoder.platforms.provor_ir_sbd.arvor_i_meta import (
    build_arvor_meta_nc,
    write_arvor_meta_nc,
)
from argo_decoder.platforms.provor_ir_sbd.arvor_i_prof import (
    apply_coriolis_profile_qc,
    build_arvor_mono_profiles,
    write_arvor_mono_profiles,
)
from argo_decoder.platforms.provor_ir_sbd.arvor_i_rtraj import build_arvor_rtraj_dataset
from argo_decoder.platforms.provor_ir_sbd.arvor_i_science import (
    reconstruct_science,
)
from argo_decoder.platforms.provor_ir_sbd.arvor_i_tech import build_arvor_tech_dataset
from argo_decoder.util.logging import get_logger

#: Wire-protocol family naming shared with ``decoder_table.yaml``.
ARVOR_I_PROFILE_CLASS = "arvor_i_sbe41cp"

_log = get_logger().bind(component="ArvorISbdDecoder")


def _message_sort_key(msg: ArvorIridiumMessage) -> tuple[int, str]:
    """Transmission order: MOMSN (header, else filename), then filename."""
    momsn = msg.session.momsn
    if momsn is None:
        momsn = momsn_from_filename(msg.source_path.name)
    name = msg.source_path.name
    return (momsn if momsn is not None else 0, name)


@register_decoder
class ArvorISbdDecoder(PlatformDecoder):
    """ARVOR-I SBE41CP adapter around the validated Phase 3-9 stack."""

    platform_type = "ARVOR_I"

    def __init__(self, config: DecoderConfig, decoder_table=None) -> None:
        super().__init__(config)
        # Lazy import to avoid a circular import at module load.
        from argo_decoder.config.decoder_table import get_decoder_table

        self._table = decoder_table or get_decoder_table()

    def can_handle(self, info: FloatInfo, meta: FloatMeta | None) -> bool:
        del meta  # routing keys on the table only: profile class, else id
        # Family-first: the four-CSV backend derives the wire-protocol
        # family from the sheet signature (manufacturer + CTD model +
        # comms) and carries it as PROFILE_CLASS. This keeps the sheets
        # the only metadata authority: no registry, no per-float ids.
        profile_class = getattr(info, "profile_class", "") or ""
        if profile_class:
            if profile_class != ARVOR_I_PROFILE_CLASS:
                return False
            return bool(self._table.entries_for_profile_class(profile_class))
        # Legacy path: numeric decoder id (info.json / registry rows).
        if not info.decoder_id:
            return False
        try:
            entry = self._table.by_decoder_id(info.decoder_id)
        except KeyError:
            return False
        return entry.profile_class == ARVOR_I_PROFILE_CLASS

    def decode_float(
        self,
        wmo: int,
        info: FloatInfo,
        meta: FloatMeta | None,
        cycles: list[CycleData],
    ) -> DecodeResult:
        result = DecodeResult(wmo=wmo)
        result.info = info
        result.meta = meta
        result.decoder_version = info.decoder_version

        # 1) Collect messages from the discovered delivery files. The
        #    source path is required: the SBD payload lives in the .sbd
        #    sidecar resolved from it by the existing reader.
        messages: list[ArvorIridiumMessage] = []
        for cd in cycles:
            for rf in cd.frames:
                path = rf.path
                if path is None:
                    result.errors.append(
                        f"frame without source path (cycle key {cd.cycle}); the ARVOR-I "
                        "reader resolves the .sbd sidecar from the .eml path"
                    )
                    continue
                try:
                    messages.append(read_arvor_i_eml(path))
                except Exception as exc:  # parse failure on one mail must not lose the float
                    result.errors.append(f"{Path(path).name}: {exc}")
        if not messages:
            result.errors.append("no ARVOR-I messages parsed")
            return result
        messages.sort(key=_message_sort_key)

        # 2) Science reconstruction (engine is resolved from the telemetry
        #    checksum inside the stack; launch date is float metadata).
        launch = info.launch_date
        if launch.tzinfo is None:
            # Sheets/registry datetimes may arrive offset-naive; the stack
            # compares against aware UTC timestamps.
            launch = launch.replace(tzinfo=UTC)
        try:
            science = reconstruct_science(messages, launch_date=launch)
        except Exception as exc:
            result.errors.append(f"reconstruct_science failed: {exc}")
            return result

        # 3) Engine evidence gate: every observed checksum must resolve to
        #    a decoder family this module implements.
        checksums = {
            rec.tech1.firmware_checksum
            for rec in science.gps_records
            if getattr(rec, "tech1", None) is not None and rec.tech1.firmware_checksum is not None
        }
        for checksum in sorted(checksums):
            try:
                _engine, ids = resolve_engine(checksum)
            except Exception as exc:
                result.errors.append(f"unsupported firmware checksum {checksum}: {exc}")
                continue
            if not ids & ARVOR_I_DECODER_IDS:
                result.errors.append(
                    f"firmware checksum {checksum} maps to decoder ids {sorted(ids)}, "
                    f"outside the ARVOR-I SBE41CP family {sorted(ARVOR_I_DECODER_IDS)}"
                )
            else:
                _log.info("engine_resolved", wmo=wmo, firmware_checksum=checksum, ids=sorted(ids))

        # 4) Write products with the existing validated writers, in the
        #    generic on-disk layout.
        out_root = Path(self.config.paths.nc_dir) / str(wmo)
        profiles_dir = out_root / "profiles"
        profiles_dir.mkdir(parents=True, exist_ok=True)

        records = build_arvor_mono_profiles(
            science,
            wmo=wmo,
            meta=meta,
            firmware_version=self._sensor_firmware_version(wmo),
        )

        # Optional real-time QC stage (common engine; default OFF). The
        # pre-RTQC products above are the validated baseline: nothing in
        # this block runs unless rtqc.apply_rtqc is explicitly enabled,
        # and every test that cannot run is recorded as skipped in the
        # QCP$ mask rather than being counted as performed.
        if self.config.rtqc.apply_rtqc:
            from argo_decoder.rtqc import apply_rtqc_to_profiles, open_gebco

            bathymetry = open_gebco(self.config.rtqc.reference_files.gebco_file)
            if bathymetry is None:
                _log.info("arvor_i_rtqc_test004_skipped", wmo=wmo, reason="no_gebco_grid")
            pressure = self._config_profile_pressure(wmo)
            summaries = apply_rtqc_to_profiles(
                [r for r in records if r.direction == "A"],
                bathymetry=bathymetry,
                profile_pressure_dbar=pressure,
            )
            # Refresh the Ref-Table-2a letters and the HISTORY block
            # (QCP$/QCF$/CF records) from the post-RTQC dataset.
            from argo_decoder.nc.mono_profile import refresh_history_records

            for rec in records:
                rec.dataset = apply_coriolis_profile_qc(rec.dataset)
                rec.dataset = refresh_history_records(rec.dataset)
            n_failed = sum(1 for s in summaries.values() if s["failed"])
            _log.info(
                "arvor_i_rtqc_applied",
                wmo=wmo,
                profiles=len(summaries),
                profiles_with_failures=n_failed,
                test004="run" if bathymetry is not None else "skipped",
                test019="run" if pressure is not None else "skipped",
            )

        written = write_arvor_mono_profiles(records, profiles_dir)
        _log.info("mono_profiles_written", wmo=wmo, n=len(written))

        tech_ds = build_arvor_tech_dataset(science, wmo=wmo)
        write_arvor_tech_nc(
            tech_ds,
            out_root / f"{wmo}_tech.nc",
            # csv4 DATA_CENTRE ('IN'): the GDAC references publish it plus
            # the mapped institution name (IN -> INCOIS) on _tech.nc.
            data_centre=_meta_field(meta, "data_centre"),
        )

        rtraj_rows = build_arvor_rtraj_dataset(
            science,
            wmo=wmo,
            # Coriolis add_launch_data_ir_sbd seeds the MC 0 (cycle -1)
            # launch row from float info; the csv4 meta sheet carries the
            # deployment position, and the GDAC references publish
            # exactly those sheet values (lat/long + launch JULD).
            launch_position=self._launch_position(wmo, launch),
        )
        rtraj_ds = build_arvor_rtraj_nc_dataset(
            rtraj_rows,
            data_centre=_meta_field(meta, "data_centre"),
            project_name=_meta_field(meta, "project_name"),
            pi_name=_meta_field(meta, "pi_name"),
            wmo_inst_type=_meta_field(meta, "wmo_inst_type"),
            float_serial_no=_meta_field(meta, "float_serial_no"),
            firmware_version=_meta_field(meta, "firmware_version"),
        )
        write_arvor_rtraj_file(rtraj_ds, out_root / f"{wmo}_Rtraj.nc")

        meta_json = self._materialized_meta_json(wmo)
        meta_ds = build_arvor_meta_nc(
            wmo=wmo,
            launch_date=launch,
            result=science,
            meta_json_path=meta_json,
        )
        write_arvor_meta_nc(meta_ds, out_root / f"{wmo}_meta.nc")

        result.cycles = list(cycles)
        return result

    def _launch_position(
        self, wmo: int, launch: datetime | None
    ) -> tuple[float, float, float] | None:
        """csv4 launch position as the ``(juld, lon, lat)`` launch-row seed.

        Returns ``None`` (row skipped, as before) when the sheets carry no
        usable deployment position (blank/zero/fill) or no launch date.
        """
        if launch is None:
            return None
        registry = getattr(self.config.metadata, "registry_path", None)
        if not registry:
            return None
        try:
            from argo_decoder.metadata.multi_csv_loader import MultiCsvLoader

            info = MultiCsvLoader(str(registry)).load_info(wmo)
        except Exception:
            return None
        lat = float(getattr(info, "launch_lat", 0.0) or 0.0)
        lon = float(getattr(info, "launch_lon", 0.0) or 0.0)
        if lat == 0.0 or lon == 0.0 or abs(lat) >= 99998.0 or abs(lon) >= 99998.0:
            return None
        if launch.tzinfo is None:
            launch = launch.replace(tzinfo=UTC)
        from argo_decoder.platforms.provor_ir_sbd.arvor_i_science import days_from_1950

        return (days_from_1950(launch), lon, lat)

    def _sensor_firmware_version(self, wmo: int) -> str | None:
        """Sensor-info ``firmware revision number`` (e.g. SBE41CP "7.2.5").

        The label GDAC publishes in FIRMWARE_VERSION for the ARVOR-I
        family, read from the same csv4 sheets that feed every other
        metadata field. Absent -> ``None`` and the float-engine
        date-code from the meta sheet is published instead.
        """
        registry = getattr(self.config.metadata, "registry_path", None)
        if not registry:
            return None
        try:
            from argo_decoder.metadata.multi_csv_loader import MultiCsvLoader

            row = MultiCsvLoader(str(registry)).get_float(wmo)
        except Exception:
            return None
        if row is None:
            return None
        value = getattr(row, "sensor_firmware_version", None)
        if value is None and getattr(row, "model_extra", None):
            value = row.model_extra.get("sensor_firmware_version")
        return str(value).strip() if value else None

    def _config_profile_pressure(self, wmo: int) -> float | None:
        """CONFIG_ProfilePressure_dbar (TEST019 input) from the 4 CSVs.

        The config_params sheet read through the same csv4 metadata
        backend that feeds every other ARVOR-I field -- the launch
        configuration is float metadata, so the sheets are the only
        authority. Absent/invalid -> ``None`` and TEST019 reports
        not-run rather than inventing a limit.
        """
        # Primary: the csv4 backend behind this decode.
        registry = getattr(self.config.metadata, "registry_path", None)
        if registry:
            try:
                from argo_decoder.metadata.multi_csv_loader import MultiCsvLoader

                row = MultiCsvLoader(str(registry)).get_float(wmo)
                for name, value in row.config_parameters or []:
                    if str(name) == "CONFIG_ProfilePressure_dbar":
                        try:
                            parsed = float(value)
                        except (TypeError, ValueError):
                            return None
                        return parsed if parsed > 0 else None
                return None
            except Exception:
                pass  # unknown WMO / unreadable sheets -> honest skip
        # Fallback: a materialised float-meta JSON from a previous run.
        for path in self._meta_json_candidates(wmo):
            pressure = self._pressure_from_meta_json(path)
            if pressure is not None:
                return pressure
        return None

    def _meta_json_candidates(self, wmo: int) -> list[Path]:
        """Every location the csv4 backend may have materialised meta."""
        roots = [
            getattr(self.config.paths, "float_meta_dir", None),
            getattr(self.config.metadata, "materialized_dir", None),
        ]
        out: list[Path] = []
        for root in roots:
            if not root:
                continue
            base = Path(root)
            out.append(base / f"{wmo}_meta.json")
            out.extend(base.glob(f"*/{wmo}_meta.json"))
        return [p for p in out if p.is_file()]

    @staticmethod
    def _pressure_from_meta_json(path: Path) -> float | None:
        """Extract CONFIG_ProfilePressure_dbar from a materialised JSON."""
        import json

        try:
            data = json.loads(Path(path).read_text())
        except (OSError, ValueError):
            return None
        names = data.get("CONFIG_PARAMETER_NAME") or []
        values = data.get("CONFIG_PARAMETER_VALUE") or []
        if not (isinstance(names, list) and isinstance(values, list)):
            return None
        flat_names: dict[str, str] = {}
        for entry in names:
            if isinstance(entry, dict):
                flat_names.update({str(k): str(v) for k, v in entry.items()})
        flat_values: dict[str, str] = {}
        for entry in values:
            if isinstance(entry, dict):
                flat_values.update({str(k): str(v) for k, v in entry.items()})
        for key, param_name in flat_names.items():
            if param_name == "CONFIG_ProfilePressure_dbar":
                raw = flat_values.get(key.replace("NAME", "VALUE"))
                try:
                    parsed = float(raw)
                except (TypeError, ValueError):
                    return None
                return parsed if parsed > 0 else None
        return None

    def _materialized_meta_json(self, wmo: int) -> Path | None:
        """The csv4 backend materialises ``<wmo>_meta.json`` from the sheets."""
        meta_dir = getattr(self.config.paths, "float_meta_dir", None)
        if not meta_dir:
            return None
        candidate = Path(meta_dir) / f"{wmo}_meta.json"
        return candidate if candidate.exists() else None


def _meta_field(meta: FloatMeta | None, name: str) -> str:
    value = getattr(meta, name, "") if meta is not None else ""
    return str(value) if value else ""


__all__ = ["ARVOR_I_PROFILE_CLASS", "ArvorISbdDecoder"]
