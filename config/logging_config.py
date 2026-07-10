"""
ExperimentIQ — Centralized Logging Configuration

Purpose:
    Configures Python's standard logging framework for the entire pipeline.
    Supports both console output (via rich for developer experience) and
    file-based structured output (for audit trails and debugging).

Design:
    - Single function call sets up the entire logging infrastructure.
    - Rich handler provides coloured, formatted console output.
    - File handler uses standard formatter for log parsing compatibility.
    - Log level is fully configurable via settings.

Dependencies:
    - rich >= 13.0 (console handler)
    - config.settings (LoggingSettings)

Inputs:
    LoggingSettings from config.settings.

Outputs:
    Configured Python logging subsystem.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-40s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def configure_logging(
    level: str = "INFO",
    log_file: Optional[Path] = None,
    use_rich: bool = True,
) -> None:
    """
    Configure the root logger for the ExperimentIQ pipeline.

    Sets up one or two handlers depending on configuration:
    - Console handler: rich RichHandler (if use_rich=True) or StreamHandler.
    - File handler: RotatingFileHandler (if log_file is provided).

    This function is idempotent: calling it multiple times does not duplicate
    handlers because it clears existing handlers first.

    Args:
        level: Log level string ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL").
        log_file: Absolute path to the log file. None disables file logging.
        use_rich: If True, use the rich library for coloured console output.

    Returns:
        None

    Raises:
        ValueError: If the provided level string is not a valid log level.
    """
    numeric_level = getattr(logging, level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f"Invalid log level: {level!r}")

    root_logger = logging.getLogger()

    # Remove existing handlers to prevent duplication on re-initialisation
    root_logger.handlers.clear()
    root_logger.setLevel(numeric_level)

    # ------------------------------------------------------------------
    # Console Handler
    # ------------------------------------------------------------------
    if use_rich:
        console_handler = _build_rich_handler(numeric_level)
    else:
        console_handler = _build_stream_handler(numeric_level)

    root_logger.addHandler(console_handler)

    # ------------------------------------------------------------------
    # File Handler (optional)
    # ------------------------------------------------------------------
    if log_file is not None:
        file_handler = _build_file_handler(log_file, numeric_level)
        root_logger.addHandler(file_handler)

    # Suppress noisy third-party loggers
    _suppress_noisy_loggers()

    logging.getLogger(__name__).info(
        "Logging initialised | level=%s | file=%s | rich=%s",
        level,
        str(log_file) if log_file else "disabled",
        use_rich,
    )


def configure_logging_from_settings() -> None:
    """
    Configure logging using the application settings singleton.

    Convenience wrapper that reads settings and calls configure_logging().
    Should be called once at pipeline startup before any other imports.

    Returns:
        None
    """
    # Import here to avoid circular import at module level
    from config.settings import get_settings

    settings = get_settings()
    configure_logging(
        level=settings.logging.level,
        log_file=settings.logging.log_file_path(),
        use_rich=settings.logging.use_rich,
    )


# ---------------------------------------------------------------------------
# Private Builder Functions
# ---------------------------------------------------------------------------


def _build_rich_handler(level: int) -> logging.Handler:
    """
    Build a rich console handler with markup and structured output.

    Args:
        level: Numeric log level.

    Returns:
        logging.Handler: Configured RichHandler.
    """
    try:
        from rich.logging import RichHandler

        handler = RichHandler(
            level=level,
            show_time=True,
            show_path=True,
            markup=True,
            rich_tracebacks=True,
            tracebacks_show_locals=False,
        )
        handler.setFormatter(logging.Formatter("%(message)s", datefmt="[%H:%M:%S]"))
        return handler
    except ImportError:
        # Gracefully fall back if rich is not installed
        logging.warning("rich not available, falling back to StreamHandler")
        return _build_stream_handler(level)


def _build_stream_handler(level: int) -> logging.StreamHandler:
    """
    Build a standard stream handler writing to stdout.

    Args:
        level: Numeric log level.

    Returns:
        logging.StreamHandler: Configured handler.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    handler.setFormatter(formatter)
    return handler


def _build_file_handler(log_file: Path, level: int) -> logging.Handler:
    """
    Build a rotating file handler for persistent log storage.

    Rotates at 50 MB, keeping up to 5 backup files.

    Args:
        log_file: Absolute path to the log file.
        level: Numeric log level.

    Returns:
        logging.Handler: Configured RotatingFileHandler.
    """
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        filename=log_file,
        maxBytes=50 * 1024 * 1024,  # 50 MB
        backupCount=5,
        encoding="utf-8",
    )
    handler.setLevel(level)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    handler.setFormatter(formatter)
    return handler


def _suppress_noisy_loggers() -> None:
    """
    Silence overly verbose third-party loggers that pollute pipeline output.

    Sets noisy loggers to WARNING level regardless of root logger level.
    """
    noisy_loggers = [
        "sqlalchemy.engine",
        "sqlalchemy.pool",
        "sqlalchemy.orm",
        "urllib3.connectionpool",
        "matplotlib",
        "PIL",
        "fontTools",
        "weasyprint",
        "cssselect2",
        "tinycss2",
    ]
    for name in noisy_loggers:
        logging.getLogger(name).setLevel(logging.WARNING)
