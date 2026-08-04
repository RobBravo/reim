"""Structured logging configuration built on ``structlog``.

Console rendering is used locally; JSON is used when ``REIM_LOG_JSON=true`` so
logs stay machine-readable in containers and CI.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from reim.core.config import Settings, get_settings

_configured = False


def configure_logging(settings: Settings | None = None, *, force: bool = False) -> None:
    """Configure stdlib logging and structlog once per process.

    Args:
        settings: Settings to read the level and renderer from. Defaults to the
            process-wide settings.
        force: Reconfigure even if logging was already set up (used by tests).
    """
    global _configured
    if _configured and not force:
        return

    settings = settings or get_settings()
    level = getattr(logging, settings.log_level, logging.INFO)

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level, force=True)
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(max(level, logging.WARNING))

    processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]
    if settings.log_json:
        processors.extend(
            [structlog.processors.format_exc_info, structlog.processors.JSONRenderer()]
        )
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty()))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str, **initial_values: Any) -> structlog.stdlib.BoundLogger:
    """Return a bound structured logger.

    Args:
        name: Logger name, conventionally the module ``__name__``.
        **initial_values: Fields bound to every record emitted by this logger.
    """
    configure_logging()
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    if initial_values:
        logger = logger.bind(**initial_values)
    return logger
