"""Structured logging configuration for the decoder."""

from __future__ import annotations

import logging
import sys
from collections.abc import Mapping, Sequence
from typing import Any

import structlog

_SHARED_PROCESSORS: Sequence[structlog.types.Processor] = (
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.processors.StackInfoRenderer(),
    structlog.processors.UnicodeDecoder(),
)


def configure_logging(level: str = "INFO", *, json_output: bool = False) -> None:
    """Configure structlog + stdlib logging.

    In dev we produce human-friendly key/value console output; in production we
    emit JSON for log scrapers (Loki/ELK).
    """
    log_level = logging.getLevelName(level.upper()) if isinstance(level, str) else level

    if json_output:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=list(_SHARED_PROCESSORS),
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *_SHARED_PROCESSORS,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def get_logger(*args: str | None, **initial_values: Any) -> structlog.stdlib.BoundLogger:
    """Return a bound structured logger.

    All events get the standard context (run_id, wmo, platform, stage) when the
    caller binds it. Call-site example::

        log = get_logger()
        log.info("event_name", key=value)
    """
    logger: structlog.stdlib.BoundLogger = structlog.wrap_logger(
        structlog.get_logger(*args, **initial_values),
        wrapper_class=structlog.stdlib.BoundLogger,
    )
    return logger


def bind_context(**kwargs: Any) -> Mapping[str, Any]:
    """Bind contextvars that are attached to every subsequent log event."""
    structlog.contextvars.clear_contextvars()
    bound: Mapping[str, Any] = structlog.contextvars.bind_contextvars(**kwargs)
    return bound
