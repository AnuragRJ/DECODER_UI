"""Per-platform decoders (Provor, Apex, Nemo, Nova, Remocean).

Phase 0 only defines the :class:`PlatformDecoder` abstract base class and a
``NullDecoder`` used by the shadow pipeline until the real implementations land.
Phase 2 adds :class:`ProvorIridiumSbdDecoder` for NKE Provor/Arvor floats on
Iridium SBD, routed through ``decoder_table.yaml``.

Importing this package triggers plugin registration (``@register_decoder``
side-effects) for all built-in plugins.
"""

from __future__ import annotations

from argo_decoder.platforms import (  # noqa: F401  (registration side-effect)
    apex_argos,
    provor_ir_sbd,
)
from argo_decoder.platforms.apex_argos import ApexArgosDecoder
from argo_decoder.platforms.base import NullDecoder, PlatformDecoder, get_decoder
from argo_decoder.platforms.provor_ir_sbd import ArvorISbdDecoder, ProvorIridiumSbdDecoder

__all__ = [
    "ApexArgosDecoder",
    "ArvorISbdDecoder",
    "NullDecoder",
    "PlatformDecoder",
    "ProvorIridiumSbdDecoder",
    "get_decoder",
]
