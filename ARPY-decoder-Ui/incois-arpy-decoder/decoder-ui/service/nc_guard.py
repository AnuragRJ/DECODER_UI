"""Global re-entrant lock serializing all service-side netCDF4 access.

The netCDF4 library is not thread-safe for cross-thread Dataset use
(``NetCDF: Not a valid ID``). Every service code path that touches netCDF4
either runs under :func:`nc_guard` or is wrapped in :func:`nc_locked`; the
APF11 builder additionally holds the lock for its whole run.
"""

from __future__ import annotations

import functools
from contextlib import contextmanager
from typing import Any, Callable, TypeVar

import netCDF4  # noqa: F401  — warmed once so all modules share one instance

_NC_LOCK = __import__("threading").RLock()

F = TypeVar("F", bound=Callable[..., Any])


@contextmanager
def nc_guard():
    """Hold the global netCDF4 RLock for one whole operation."""
    with _NC_LOCK:
        yield


def nc_locked(fn: F) -> F:
    """Serialize ``fn`` on the global netCDF4 RLock (re-entrant per thread)."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with _NC_LOCK:
            return fn(*args, **kwargs)

    return wrapper  # type: ignore[return-value]


def install() -> None:
    """Idempotent monkey-patch: wrap Dataset open/close in the RLock too.

    Belt and braces on top of the explicit guards — any stray netCDF4 use
    from third-party code still touches the shared lock.
    """

    import netCDF4 as _nc

    if getattr(_nc.Dataset, "_nc_guard_patched", False):
        return

    orig_init = _nc.Dataset.__init__
    orig_close = _nc.Dataset.close

    @functools.wraps(orig_init)
    def init(self: Any, *args: Any, **kwargs: Any) -> None:
        with _NC_LOCK:
            orig_init(self, *args, **kwargs)

    @functools.wraps(orig_close)
    def close(self: Any, *args: Any, **kwargs: Any) -> Any:
        with _NC_LOCK:
            return orig_close(self, *args, **kwargs)

    _nc.Dataset.__init__ = init  # type: ignore[method-assign]
    _nc.Dataset.close = close  # type: ignore[method-assign]
    _nc.Dataset._nc_guard_patched = True
