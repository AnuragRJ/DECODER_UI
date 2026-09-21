"""Configuration loading and validation."""

from __future__ import annotations

from argo_decoder.config.decoder_table import (
    DecoderTable,
    DecoderTableEntry,
    PlatformFamily,
    TransmissionKind,
    get_decoder_table,
    load_decoder_table,
)
from argo_decoder.config.loader import load_config
from argo_decoder.config.models import (
    DecoderConfig,
    OutputFlags,
    PathSet,
    RtqcConfig,
    TransmissionType,
)

__all__ = [
    "DecoderConfig",
    "DecoderTable",
    "DecoderTableEntry",
    "OutputFlags",
    "PathSet",
    "PlatformFamily",
    "RtqcConfig",
    "TransmissionKind",
    "TransmissionType",
    "get_decoder_table",
    "load_config",
    "load_decoder_table",
]
