"""Platform decoder plugin interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import xarray as xr

from argo_decoder.config.models import DecoderConfig
from argo_decoder.domain.frames import CycleData
from argo_decoder.metadata.models import FloatInfo, FloatMeta


@dataclass
class DecodeResult:
    """Result of decoding one float."""

    wmo: int
    cycles: list[CycleData] = field(default_factory=list)
    mono_profile_datasets: dict[int, xr.Dataset] = field(default_factory=dict)
    multi_profile_dataset: xr.Dataset | None = None
    tech_dataset: xr.Dataset | None = None
    meta_dataset: xr.Dataset | None = None
    traj_dataset: xr.Dataset | None = None
    errors: list[str] = field(default_factory=list)
    # Metadata reference (optional): used by the writer when building the
    # ADMT-compliant multi-profile (_prof.nc) file from mono datasets.
    info: FloatInfo | None = None
    meta: FloatMeta | None = None
    decoder_version: str = ""
    institution: str = "CORIOLIS"

    def merge(self, other: DecodeResult) -> None:
        self.mono_profile_datasets.update(other.mono_profile_datasets)
        for c in other.cycles:
            if c not in self.cycles:
                self.cycles.append(c)
        self.errors.extend(other.errors)
        for attr in ("multi_profile_dataset", "tech_dataset", "meta_dataset", "traj_dataset"):
            if getattr(other, attr) is not None and getattr(self, attr) is None:
                setattr(self, attr, getattr(other, attr))
        # Carry info/meta/version forward from whichever side has them.
        if self.info is None and other.info is not None:
            self.info = other.info
        if self.meta is None and other.meta is not None:
            self.meta = other.meta
        if not self.decoder_version and other.decoder_version:
            self.decoder_version = other.decoder_version


class PlatformDecoder(ABC):
    """Base class for per-platform decoders."""

    platform_type: str = ""

    def __init__(self, config: DecoderConfig) -> None:
        self.config = config

    @abstractmethod
    def can_handle(self, info: FloatInfo, meta: FloatMeta | None) -> bool:
        """Return True if this decoder handles the given float."""

    @abstractmethod
    def decode_float(
        self, wmo: int, info: FloatInfo, meta: FloatMeta | None, cycles: list[CycleData]
    ) -> DecodeResult:
        """Decode one float's cycles into in-memory xarray datasets."""


class NullDecoder(PlatformDecoder):
    """Decoder used in Phase 0 - discovers and counts input files but emits
    only structural metadata (no science). Serves as the "plumbing end-to-end"
    baseline and lets the harness/shadow pipeline exercise every IO path before
    any science is implemented.
    """

    platform_type = "null"

    def can_handle(self, info: FloatInfo, meta: FloatMeta | None) -> bool:
        return True

    def decode_float(
        self, wmo: int, info: FloatInfo, meta: FloatMeta | None, cycles: list[CycleData]
    ) -> DecodeResult:
        result = DecodeResult(wmo=wmo, cycles=cycles)
        for cycle in cycles:
            # Emit a minimal mono-profile dataset with correct dimensions so
            # downstream NetCDF writer test can validate structure.
            ds = xr.Dataset(
                attrs={
                    "wmo": wmo,
                    "cycle": cycle.cycle,
                    "decoder": "null",
                    "platform_type": info.float_type,
                    "decoder_version": info.decoder_version,
                }
            )
            result.mono_profile_datasets[cycle.cycle] = ds
        return result


_REGISTRY: list[type[PlatformDecoder]] = []


def register_decoder(cls: type[PlatformDecoder]) -> type[PlatformDecoder]:
    """Decorator for platform plugins.

    Plugins are appended to the registry. NullDecoder is installed as a
    final fallback (it matches every float) so ``get_decoder`` always
    returns something useful.
    """
    _REGISTRY.append(cls)
    return cls


def get_decoder(info: FloatInfo, meta: FloatMeta | None, config: DecoderConfig) -> PlatformDecoder:
    for cls in _REGISTRY:
        if cls is NullDecoder:
            continue
        d = cls(config)
        if d.can_handle(info, meta):
            return d
    return NullDecoder(config)


# NullDecoder is the last-resort fallback (appended after all real plugins).
_REGISTRY.append(NullDecoder)
