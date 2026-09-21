"""Ocean-current provider interface (server-side only).

The engine asks a provider for a velocity at (lat, lon, depth, time). Nothing in
the browser ever requests current data: providers are constructed here, run on
the API side, and their absence is an explicit, reported state rather than an
invented field.

Shipped default: **no provider configured** (``PREDICTION_CURRENTS_PROVIDER``
unset). The engine then selects the validated history/prior baseline and says so
in the payload. Configuring a provider is an INCOIS/deployment decision — it
needs credentials, and no credentials are committed or defaulted here.

Candidate products (see RESEARCH.md section 2.3): CMEMS GLOBAL_ANALYSISFORECAST_PHY_001_024
(GLO12, 1/12 deg, daily 10-day forecast), GLORYS12V1 reanalysis for hindcasts,
or an approved INCOIS HOOFS/OSF product. Any of them can be wrapped in
:class:`CurrentProvider` and returned by :func:`get_provider` without touching
the prediction or UI layers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class CurrentSourceUnavailable(Exception):
    """Provider is requested but cannot serve data (missing config/credentials)."""


@runtime_checkable
class CurrentProvider(Protocol):
    """Minimal interface a current-model adapter must implement."""

    name: str

    def available(self) -> bool:
        """True only when the provider can actually answer velocity()."""

    def describe(self) -> str:
        """Human-readable provenance for the payload (never credentials)."""

    def velocity(
        self,
        lat: float,
        lon: float,
        depth_dbar: float,
        when_juld: float,
    ) -> tuple[float, float]:
        """(eastward, northward) velocity in m/s at a time, or raise."""


@dataclass
class NoCurrentProvider:
    """Explicit "no current data" state (the default deployment)."""

    name: str = "none"
    reason: str = "no ocean-current provider configured for this deployment"

    def available(self) -> bool:
        return False

    def describe(self) -> str:
        return self.reason

    def velocity(self, lat: float, lon: float, depth_dbar: float, when_juld: float):
        raise CurrentSourceUnavailable(self.reason)


@dataclass
class UnconfiguredCMEMSProvider:
    """CMEMS/GLORYS adapter placeholder with a real credential gate.

    Deliberately does **not** fabricate velocities: until a deployment supplies
    credentials *and* the adapter implementation, it reports itself unavailable
    so the engine falls back to the validated baseline. This keeps the physics
    integration point explicit without shipping an untested data path.
    """

    name: str = "cmems_glo12"
    username_env: str = "CMEMS_USERNAME"
    password_env: str = "CMEMS_PASSWORD"

    def _credentials_present(self) -> bool:
        return bool(os.environ.get(self.username_env) and os.environ.get(self.password_env))

    def available(self) -> bool:
        return False  # adapter not implemented; never claims to be ready

    def describe(self) -> str:
        if not self._credentials_present():
            return "CMEMS GLO12 requested but credentials are absent (no current data used)"
        return "CMEMS GLO12 credentials present but the adapter is not implemented in this build"

    def velocity(self, lat: float, lon: float, depth_dbar: float, when_juld: float):
        raise CurrentSourceUnavailable(self.describe())


#: Registered providers by environment name. Adding a real adapter is a
#: one-line change here plus its unit tests — no UI or prediction changes.
PROVIDERS: dict[str, type] = {
    "none": NoCurrentProvider,
    "cmems_glo12": UnconfiguredCMEMSProvider,
    "glorys12": UnconfiguredCMEMSProvider,
}


def provider_from_env() -> CurrentProvider:
    requested = (os.environ.get("PREDICTION_CURRENTS_PROVIDER") or "none").strip().lower()
    factory = PROVIDERS.get(requested, NoCurrentProvider)
    try:
        provider = factory()
    except Exception:
        provider = NoCurrentProvider(reason=f"provider {requested!r} failed to initialise")
    return provider  # type: ignore[return-value]
