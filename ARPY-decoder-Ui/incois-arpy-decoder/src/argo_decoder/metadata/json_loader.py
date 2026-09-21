"""Metadata loader that reads the existing ``*_info.json`` / ``*_meta.json`` files.

This is the Phase-0 backend and remains supported forever: it lets the decoder
consume exactly the JSON layout produced by MATLAB and documented in the repo.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from pathlib import Path

from argo_decoder.metadata.models import FloatInfo, FloatMeta, FloatRegistryRow

_INFO_RE = re.compile(r"^(?P<wmo>\d+)_(?P<ptt>[^_]+)_info\.json$")


class JsonLoader:
    """Load ``FloatInfo`` / ``FloatMeta`` from the existing directory layout.

    Parameters
    ----------
    info_dir:
        Directory containing ``<wmo>_<ptt>_info.json`` files.
    meta_dir:
        Directory containing ``<wmo>_meta.json`` files.

    """

    def __init__(self, info_dir: Path | str, meta_dir: Path | str) -> None:
        self.info_dir = Path(info_dir)
        self.meta_dir = Path(meta_dir)
        self._info_index: dict[int, Path] | None = None

    # --- MetadataLoader protocol ---
    def get_float(self, wmo: int) -> FloatRegistryRow | None:
        info = self.load_info(wmo) if self._info_path(wmo) else None
        if info is None:
            return None
        meta = self.load_meta(wmo) if (self.meta_dir / f"{wmo}_meta.json").exists() else None
        return FloatRegistryRow(
            wmo=info.wmo,
            ptt=info.ptt,
            platform_maker=_infer_maker(info, meta),
            platform_type=info.float_type,
            platform_family=getattr(meta, "platform_family", "FLOAT") if meta else "FLOAT",
            transmission_type=3,  # set by caller via config.paths when known
            decoder_id=info.decoder_id,
            decoder_version=info.decoder_version,
            firmware_version=getattr(meta, "firmware_version", "") if meta else "",
            frame_length=info.frame_length,
            cycle_length_hours=info.cycle_length_hours,
            drift_sampling_period_hours=info.drift_sampling_period_hours,
            delay_before_mission_minutes=info.delay_minutes,
            launch_date_utc=info.launch_date,
            launch_lon=info.launch_lon,
            launch_lat=info.launch_lat,
            reference_day=info.reference_day,
            end_decoding_date=info.end_decoding_date,
            dm_flag=info.dm_flag,
        )

    def iter_floats(self, wmos: Iterable[int] | None = None) -> Iterator[FloatRegistryRow]:
        wmo_set = set(wmos) if wmos is not None else None
        for path in self._ensure_index().values():
            m = _INFO_RE.match(path.name)
            if not m:
                continue
            wmo = int(m.group("wmo"))
            if wmo_set is not None and wmo not in wmo_set:
                continue
            row = self.get_float(wmo)
            if row is not None:
                yield row

    def load_info(self, wmo: int) -> FloatInfo:
        path = self._info_path(wmo)
        if path is None:
            raise FileNotFoundError(f"No info JSON found for WMO {wmo} in {self.info_dir}")
        return FloatInfo.from_json_file(path)

    def load_meta(self, wmo: int) -> FloatMeta:
        path = self.meta_dir / f"{wmo}_meta.json"
        if not path.exists():
            raise FileNotFoundError(f"No meta JSON found for WMO {wmo} in {self.meta_dir}")
        return FloatMeta.from_json_file(path)

    # --- internal ---
    def _ensure_index(self) -> dict[int, Path]:
        if self._info_index is None:
            idx: dict[int, Path] = {}
            if self.info_dir.exists():
                for path in self.info_dir.glob("*_info.json"):
                    m = _INFO_RE.match(path.name)
                    if m:
                        idx[int(m.group("wmo"))] = path
            self._info_index = idx
        return self._info_index

    def _info_path(self, wmo: int) -> Path | None:
        return self._ensure_index().get(wmo)


def _infer_maker(info: FloatInfo, meta: FloatMeta | None) -> str:
    if meta is not None and meta.platform_maker:
        return str(meta.platform_maker)
    ft = (info.float_type or "").upper()
    if ft in {"PROVOR", "ARVOR", "ARVOR_D", "ARVOR_I", "ARVOR_N", "ARVOR_C"}:
        return "NKE"
    if ft.startswith("APEX"):
        return "APEX"
    if ft.startswith("NEMO"):
        return "NEMO"
    if ft.startswith("NOVA"):
        return "NOVA"
    return "UNKNOWN"
